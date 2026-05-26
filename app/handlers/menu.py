"""Главное меню: обработка кнопок reply-клавиатуры (вне FSM)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Role
from app.db.models.match import Match
from app.db.models.user import User
from app.handlers.browse import browse_candidates, browse_vacancies
from app.handlers.candidate import show_candidate_profile, start_candidate_edit
from app.handlers.employer import show_employer_vacancies
from app.handlers.ui import start_employer_form
from app.keyboards.inline import propose_interview_keyboard, role_keyboard, tariff_keyboard
from app.locales import RU
from app.repositories.candidate import CandidateRepo
from app.repositories.match import MatchRepo
from app.repositories.vacancy import EmployerRepo
from app.services.access_control import AccessControlService
from app.services.profile import position_label
from app.utils.text import mask_address, mask_name

router = Router(name="menu")
# Все хендлеры меню работают только вне активной FSM-формы.
router.message.filter(StateFilter(None))


@router.message(F.text.in_({RU["menu_search_vacancies"], RU["menu_search_candidates"]}))
async def on_search(message: Message, session: AsyncSession, user: User) -> None:
    if user.role == Role.EMPLOYER:
        await browse_candidates(message, session, user)
    else:
        await browse_vacancies(message, session, user)


@router.message(Command("search"))
async def cmd_search(message: Message, session: AsyncSession, user: User) -> None:
    await on_search(message, session, user)


@router.message(F.text == RU["menu_my_profile"])
async def on_my_profile(message: Message, session: AsyncSession, user: User) -> None:
    await show_candidate_profile(message, session, user)


@router.message(Command("profile"))
async def cmd_profile(message: Message, session: AsyncSession, user: User) -> None:
    if user.role == Role.EMPLOYER:
        await show_employer_vacancies(message, session, user)
    else:
        await show_candidate_profile(message, session, user)


@router.message(F.text == RU["menu_my_vacancies"])
async def on_my_vacancies(message: Message, session: AsyncSession, user: User) -> None:
    await show_employer_vacancies(message, session, user)


@router.message(F.text == RU["menu_edit_profile"])
async def on_edit_profile(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await start_candidate_edit(message, state, session, user)


@router.message(F.text == RU["menu_new_vacancy"])
async def on_new_vacancy(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await start_employer_form(message, state, session, user.id)


@router.message(F.text == RU["menu_switch_role"])
async def on_switch_role(message: Message) -> None:
    await message.answer(RU["role_switch_prompt"], reply_markup=role_keyboard())


@router.message(F.text == RU["menu_matches"])
async def on_matches(message: Message, session: AsyncSession, user: User) -> None:
    matches = await _user_matches(session, user)
    if not matches:
        await message.answer("Пока взаимных откликов нет. Листайте карточки 🔍")
        return
    full_access = await AccessControlService(session).has_full_access(user.id)
    await message.answer(f"💚 <b>Ваши отклики ({len(matches)})</b>")
    for match in matches:
        text = _match_line(match, user.role, full_access=full_access)
        reply_markup = None
        if user.role == Role.EMPLOYER and full_access and match.interview is None:
            reply_markup = propose_interview_keyboard(match.id)
        await message.answer(text, reply_markup=reply_markup)
    if not full_access:
        await message.answer(
            RU["matches_locked_hint"],
            reply_markup=tariff_keyboard(_role_to_kb(user.role)),
        )


async def _user_matches(session: AsyncSession, user: User) -> list[Match]:
    repo = MatchRepo(session)
    if user.role == Role.EMPLOYER:
        employer = await EmployerRepo(session).get_by_user_id(user.id)
        if employer is None:
            return []
        return await repo.list_mutual_for_user(employer_id=employer.id)
    candidate = await CandidateRepo(session).get_by_user_id(user.id)
    if candidate is None:
        return []
    return await repo.list_mutual_for_user(candidate_id=candidate.id)


def _match_line(match: Match, role: Role | None, *, full_access: bool) -> str:
    vacancy = match.vacancy
    candidate = match.candidate
    position = position_label(vacancy.position_normalized, vacancy.position)
    if role == Role.EMPLOYER:
        name = candidate.name if full_access else mask_name(candidate.name)
        contact = candidate.contact if full_access else RU["preview_contact_hidden"]
        return (
            f"🧑‍🍳 {position}\n"
            f"👤 {name}, опыт {candidate.experience_years} лет\n"
            f"📞 {contact}"
        )
    company = vacancy.employer.company_name if vacancy.employer else "—"
    address = vacancy.address
    phone = vacancy.employer.phone if vacancy.employer else "—"
    if not full_access:
        company = "***"
        address = mask_address(vacancy.address)
        phone = RU["preview_contact_hidden"]
    return (
        f"🏢 {company} · {position}\n"
        f"📍 {address}\n"
        f"📞 {phone}"
    )


def _role_to_kb(role: Role | None) -> str:
    return "candidate" if role == Role.CANDIDATE else "employer"
