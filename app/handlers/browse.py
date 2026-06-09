"""Свайп-просмотр карточек (Дайвинчик-стиль): кандидат листает вакансии,
работодатель — кандидатов. ❤️/👎, взаимный лайк → обмен контактами."""

from __future__ import annotations

from contextlib import suppress

from aiogram import Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CandidateStatus, Reaction, Role
from app.core.exceptions import CandidateLimitReachedError
from app.db.models.match import Match
from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.handlers.ui import show_main_menu
from app.keyboards.callbacks import BrowseCB, SwipeCB
from app.keyboards.inline import propose_interview_keyboard, swipe_keyboard, tariff_keyboard
from app.locales import RU
from app.repositories.candidate import CandidateRepo
from app.repositories.vacancy import EmployerRepo
from app.services.access_control import AccessControlService
from app.services.browse import BrowseService, Card
from app.services.notifications import NotificationService
from app.services.profile import position_label, render_candidate_card, render_vacancy_card
from app.utils.text import mask_name
from app.utils.time import utcnow

router = Router(name="browse")


# ─────────────────────────── публичные точки входа ─────────────────────────
async def browse_vacancies(message: Message, session: AsyncSession, user: User) -> None:
    candidate = await CandidateRepo(session).get_by_user_id(user.id)
    if candidate is None:
        await message.answer(RU["profile_none_candidate"])
        return
    card = await BrowseService(session).next_for_candidate(candidate)
    if card is None:
        await show_main_menu(message, user.role, text=RU["browse_empty_candidate"])
        return
    await message.answer(RU["browse_start_candidate"])
    full_access = await AccessControlService(session).has_full_access(user.id)
    await _send_card(message, card, Role.CANDIDATE, full_access=full_access)


async def browse_candidates(message: Message, session: AsyncSession, user: User) -> None:
    employer = await EmployerRepo(session).get_by_user_id(user.id)
    if employer is None:
        await message.answer(RU["profile_none_employer"])
        return
    if not employer.is_verified:
        await message.answer(RU["browse_not_verified"])
        return
    svc = BrowseService(session)
    vacancy = await svc.employer_active_vacancy(employer.id)
    if vacancy is None:
        await message.answer(RU["profile_none_employer"])
        return
    card = await svc.next_for_employer(vacancy)
    if card is None:
        await show_main_menu(message, user.role, text=RU["browse_empty_employer"])
        return
    await message.answer(RU["browse_start_employer"])
    access = AccessControlService(session)
    full_access = await access.has_full_access(user.id)
    if not await _gate_employer_card(message, access, card, user.id, full_access=full_access):
        return
    await _send_card(message, card, Role.EMPLOYER, full_access=full_access)


# ──────────────────────────────── свайпы ───────────────────────────────────
@router.callback_query(SwipeCB.filter())
async def on_swipe(
    callback: CallbackQuery,
    callback_data: SwipeCB,
    session: AsyncSession,
    user: User,
) -> None:
    reaction = Reaction(callback_data.reaction)
    svc = BrowseService(session)
    is_mutual, match = await svc.react(
        match_id=callback_data.match_id, by_role=user.role or Role.CANDIDATE,
        reaction=reaction,
    )
    await callback.answer(
        RU["browse_liked"] if reaction == Reaction.LIKE else RU["browse_skipped"]
    )

    msg = callback.message if isinstance(callback.message, Message) else None
    if msg is None:
        return

    # Снимаем кнопки с предыдущей карточки.
    with suppress(Exception):
        await msg.edit_reply_markup(reply_markup=None)

    if is_mutual and match is not None:
        await _announce_mutual(callback, session, match)

    await _send_next(msg, session, user)


@router.callback_query(BrowseCB.filter())
async def on_browse_action(
    callback: CallbackQuery, callback_data: BrowseCB, session: AsyncSession, user: User
) -> None:
    await callback.answer()
    msg = callback.message if isinstance(callback.message, Message) else None
    if msg is None:
        return
    if callback_data.action == "stop":
        with suppress(Exception):
            await msg.edit_reply_markup(reply_markup=None)
        await show_main_menu(msg, user.role, text=RU["browse_stopped"])
    elif callback_data.action == "next":
        await _send_next(msg, session, user)


# ──────────────────────────────── helpers ──────────────────────────────────
async def _send_next(message: Message, session: AsyncSession, user: User) -> None:
    if user.role == Role.EMPLOYER:
        employer = await EmployerRepo(session).get_by_user_id(user.id)
        if employer is None:
            return
        svc = BrowseService(session)
        vacancy = await svc.employer_active_vacancy(employer.id)
        card = await svc.next_for_employer(vacancy) if vacancy else None
        if card is None:
            await show_main_menu(message, user.role, text=RU["browse_empty_employer"])
            return
        access = AccessControlService(session)
        full_access = await access.has_full_access(user.id)
        if not await _gate_employer_card(message, access, card, user.id, full_access=full_access):
            return
        await _send_card(message, card, Role.EMPLOYER, full_access=full_access)
    else:
        candidate = await CandidateRepo(session).get_by_user_id(user.id)
        if candidate is None:
            return
        card = await BrowseService(session).next_for_candidate(candidate)
        if card is None:
            await show_main_menu(message, user.role, text=RU["browse_empty_candidate"])
            return
        full_access = await AccessControlService(session).has_full_access(user.id)
        await _send_card(message, card, Role.CANDIDATE, full_access=full_access)


def _with_hint(caption: str, hint: str | None) -> str:
    """Добавляет к карточке AI-подсказку «почему подходит», если она есть."""
    return f"{caption}\n\n💡 {hint}" if hint else caption


async def _send_card(
    message: Message, card: Card, viewer_role: Role, *, full_access: bool
) -> None:
    kb = swipe_keyboard(card.match.id)
    if viewer_role == Role.CANDIDATE and card.vacancy is not None:
        caption = _with_hint(
            render_vacancy_card(card.vacancy, preview=not full_access), card.ai_hint
        )
        if card.vacancy.photo_file_id:
            await message.answer_photo(
                photo=card.vacancy.photo_file_id, caption=caption, reply_markup=kb
            )
        else:
            await message.answer(caption, reply_markup=kb)
    elif card.candidate is not None:
        await message.answer_photo(
            photo=card.candidate.photo_file_id,
            caption=_with_hint(
                render_candidate_card(card.candidate, preview=not full_access),
                card.ai_hint,
            ),
            reply_markup=kb,
        )


async def _announce_mutual(
    callback: CallbackQuery, session: AsyncSession, match: Match
) -> None:
    """Взаимный лайк → контакты обеим сторонам + кнопка назначить собеседование."""
    candidate = match.candidate
    vacancy = match.vacancy
    if candidate is None or vacancy is None or vacancy.employer is None:
        return
    employer = vacancy.employer
    notifier = NotificationService(callback.bot)  # type: ignore[arg-type]
    position = position_label(vacancy.position_normalized, vacancy.position)
    access = AccessControlService(session)
    candidate_full = await access.has_full_access(candidate.user_id)
    employer_full = await access.has_full_access(employer.user_id)

    # Кандидату предложена вакансия — отражаем в статусе анкеты.
    if candidate.status not in (CandidateStatus.INVITED, CandidateStatus.HIRED):
        await CandidateRepo(session).set_status(candidate, CandidateStatus.OFFERED)

    if candidate.user is not None:
        candidate_text = (
            RU["mutual_match_candidate"].format(
                company=employer.company_name,
                position=position,
                address=vacancy.address,
                contact=employer.phone,
            )
            if candidate_full
            else RU["mutual_match_candidate_locked"].format(
                company=employer.company_name,
                position=position,
            )
        )
        await notifier.send(
            candidate.user.tg_id,
            candidate_text,
            reply_markup=None if candidate_full else tariff_keyboard("candidate"),
        )
    if employer.user is not None:
        employer_text = (
            RU["mutual_match_employer"].format(
                position=position,
                name=candidate.name,
                experience=candidate.experience_years,
                contact=candidate.contact,
            )
            if employer_full
            else RU["mutual_match_employer_locked"].format(
                position=position,
                name=mask_name(candidate.name),
                experience=candidate.experience_years,
            )
        )
        await notifier.send(
            employer.user.tg_id,
            employer_text,
            reply_markup=(
                propose_interview_keyboard(match.id)
                if employer_full
                else tariff_keyboard("employer")
            ),
        )


async def _gate_employer_card(
    message: Message,
    access: AccessControlService,
    card: Card,
    user_id: int,
    *,
    full_access: bool,
) -> bool:
    """Проверяет лимит просмотров перед показом карточки работодателю.

    Возвращает False и предлагает апгрейд, если лимит тарифа исчерпан — карточку
    показывать не нужно. Важно: ошибка лимита больше НЕ всплывает в глобальный
    on_error (который откатывал бы транзакцию вместе с реакцией и инкрементом).
    """
    if not full_access:
        return True
    try:
        sub = await access.can_view_candidate(user_id)
    except CandidateLimitReachedError:
        await message.answer(
            RU["browse_limit_reached"], reply_markup=tariff_keyboard("employer")
        )
        return False
    await _consume_employer_view_if_needed(access, card.match, sub)
    return True


async def _consume_employer_view_if_needed(
    access: AccessControlService, match: Match, sub: Subscription
) -> None:
    if match.employer_seen_at is not None:
        return
    match.employer_seen_at = utcnow()
    await access.consume_candidate_view(sub)
