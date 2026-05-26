"""Назначение собеседования (ТЗ §5).

Поток после взаимного матча:
  1. Работодатель жмёт «📅 Предложить время» → вводит 1-3 слота текстом.
  2. Бот шлёт слоты кандидату кнопками.
  3. Кандидат выбирает слот → собеседование зафиксировано, поставлены
     напоминания за 24 ч и 2 ч, обе стороны уведомлены.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CandidateStatus, InterviewStatus
from app.db.models.user import User
from app.handlers.ui import show_main_menu
from app.keyboards.callbacks import InterviewCB, InterviewSlotCB
from app.keyboards.inline import interview_slots_keyboard, tariff_keyboard
from app.keyboards.reply import cancel_keyboard
from app.locales import RU
from app.repositories.candidate import CandidateRepo
from app.repositories.match import InterviewRepo, MatchRepo
from app.services.access_control import AccessControlService
from app.services.enrichment import resolve_interview_slots
from app.services.notifications import NotificationService
from app.services.profile import position_label
from app.services.scheduler import schedule_interview_reminders
from app.states.interview import InterviewScheduling
from app.utils.time import format_dt

router = Router(name="interview")


# ──────────────── 1. Работодатель инициирует и вводит слоты ─────────────────
@router.callback_query(InterviewCB.filter())
async def on_propose(
    callback: CallbackQuery, callback_data: InterviewCB, state: FSMContext, session: AsyncSession
) -> None:
    match = await MatchRepo(session).get_full(callback_data.match_id)
    if match is None or match.vacancy is None or match.vacancy.employer is None:
        await callback.answer(RU["interview_match_gone"], show_alert=True)
        return
    if not await AccessControlService(session).has_full_access(match.vacancy.employer.user_id):
        await callback.answer(RU["interview_requires_subscription"], show_alert=True)
        return
    await callback.answer()
    await state.update_data(match_id=callback_data.match_id)
    await state.set_state(InterviewScheduling.employer_proposes_slots)
    if isinstance(callback.message, Message):
        await callback.message.answer(RU["interview_ask_slots"], reply_markup=cancel_keyboard())


@router.message(InterviewScheduling.employer_proposes_slots)
async def on_slots_entered(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    # Сначала строгий формат, затем AI разбирает живую речь («завтра после обеда»).
    slots = await resolve_interview_slots(message.text or "")
    if not slots:
        await message.answer(RU["interview_slots_invalid"])
        return

    data = await state.get_data()
    await state.clear()

    match = await MatchRepo(session).get_full(data["match_id"])
    if match is None or match.candidate is None or match.vacancy is None:
        await show_main_menu(message, user.role, text=RU["interview_match_gone"])
        return

    vacancy = match.vacancy
    interview = await InterviewRepo(session).upsert_proposal(
        match_id=match.id,
        proposed_slots=[s.isoformat() for s in slots],
        address=vacancy.address,
    )

    # Шлём слоты кандидату.
    company = vacancy.employer.company_name if vacancy.employer else "—"
    position = position_label(vacancy.position_normalized, vacancy.position)
    notifier = NotificationService(message.bot)  # type: ignore[arg-type]
    if match.candidate.user is not None:
        candidate_full = await AccessControlService(session).has_full_access(match.candidate.user_id)
        await notifier.send(
            match.candidate.user.tg_id,
            (
                RU["interview_propose_to_candidate"].format(
                    company=company, position=position, address=vacancy.address
                )
                if candidate_full
                else RU["mutual_match_candidate_locked"].format(
                    company=company, position=position
                )
            ),
            reply_markup=(
                interview_slots_keyboard(interview.id, slots)
                if candidate_full
                else tariff_keyboard("candidate")
            ),
        )
    await show_main_menu(message, user.role, text=RU["interview_slots_sent"])


# ──────────────── 2. Кандидат выбирает слот ─────────────────────────────────
@router.callback_query(InterviewSlotCB.filter())
async def on_slot_chosen(
    callback: CallbackQuery,
    callback_data: InterviewSlotCB,
    session: AsyncSession,
) -> None:
    interview = await InterviewRepo(session).get_full(callback_data.interview_id)
    if interview is None or interview.status != InterviewStatus.PROPOSED:
        await callback.answer(RU["interview_slot_taken"], show_alert=True)
        return
    if not await AccessControlService(session).has_full_access(interview.match.candidate.user_id):
        await callback.answer(RU["interview_requires_subscription"], show_alert=True)
        return

    slots = interview.proposed_slots or []
    if not 0 <= callback_data.slot_index < len(slots):
        await callback.answer(RU["interview_slot_taken"], show_alert=True)
        return

    chosen = datetime.fromisoformat(slots[callback_data.slot_index])
    await InterviewRepo(session).confirm(interview, chosen)
    schedule_interview_reminders(interview_id=interview.id, scheduled_at=chosen)

    match = interview.match
    vacancy = match.vacancy
    candidate = match.candidate
    company = vacancy.employer.company_name if vacancy.employer else "—"
    position = position_label(vacancy.position_normalized, vacancy.position)
    when = format_dt(chosen)

    await callback.answer()
    if isinstance(callback.message, Message):
        with suppress(Exception):
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            RU["interview_confirmed_candidate"].format(
                company=company, position=position, address=interview.address, time=when
            )
        )

    # Кандидат приглашён — обновляем статус анкеты.
    await CandidateRepo(session).set_status(candidate, CandidateStatus.INVITED)

    # Уведомляем работодателя.
    notifier = NotificationService(callback.bot)  # type: ignore[arg-type]
    if vacancy.employer is not None and vacancy.employer.user is not None:
        await notifier.send(
            vacancy.employer.user.tg_id,
            RU["interview_confirmed_employer"].format(
                name=candidate.name, position=position, time=when
            ),
        )
