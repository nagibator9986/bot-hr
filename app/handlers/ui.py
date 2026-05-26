"""Общие UI-хелперы для хендлеров (без собственных роутеров).

Вынесены отдельно, чтобы не было циклических импортов между common/menu/candidate.
"""

from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Role
from app.keyboards.reply import cancel_keyboard, main_menu
from app.locales import RU
from app.repositories.vacancy import EmployerRepo
from app.states.candidate import CandidateForm
from app.states.employer import EmployerForm


async def show_main_menu(message: Message, role: Role | None, *, text: str | None = None) -> None:
    await message.answer(text or RU["menu_title"], reply_markup=main_menu(role))


async def start_candidate_form(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(RU["candidate_intro"], reply_markup=cancel_keyboard())
    await message.answer(RU["ask_name"])
    await state.set_state(CandidateForm.name)


async def start_employer_form(
    message: Message, state: FSMContext, session: AsyncSession, user_id: int
) -> None:
    """Возвращающийся работодатель сразу заполняет вакансию;
    новый — сначала проходит регистрацию компании."""
    await state.clear()
    employer = await EmployerRepo(session).get_by_user_id(user_id)
    if employer is not None:
        await state.update_data(employer_id=employer.id, is_returning=True)
        await message.answer(RU["vacancy_intro"], reply_markup=cancel_keyboard())
        await message.answer(RU["ask_employer_city"])
        await state.set_state(EmployerForm.city)
    else:
        await state.update_data(is_returning=False)
        await message.answer(RU["employer_reg_intro"], reply_markup=cancel_keyboard())
        await message.answer(RU["ask_company"])
        await state.set_state(EmployerForm.company)
