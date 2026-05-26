"""Сценарий работодателя: регистрация компании (с проверкой) + создание вакансии."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Role, Schedule, VacancyStatus, VerificationStatus
from app.db.models.employer import Employer
from app.db.models.user import User
from app.db.models.vacancy import Vacancy
from app.handlers.subscription import offer_subscription_prompt
from app.handlers.ui import show_main_menu, start_employer_form
from app.keyboards.callbacks import (
    ConfirmCB,
    PositionCB,
    ScheduleCB,
    SkipCB,
    VacancyActionCB,
)
from app.keyboards.inline import (
    confirm_keyboard,
    position_keyboard,
    schedule_keyboard,
    skip_keyboard,
    vacancy_actions_keyboard,
)
from app.keyboards.reply import cancel_keyboard, request_contact_keyboard
from app.locales import RU
from app.repositories.vacancy import EmployerRepo, VacancyRepo
from app.services.access_control import AccessControlService
from app.services.enrichment import resolve_position, structure_requirements
from app.services.notifications import announce_new_vacancy
from app.services.profile import render_vacancy_summary
from app.services.verification import VerificationService
from app.states.employer import EmployerForm
from app.utils.validators import clean_text, parse_phone, parse_salary

router = Router(name="employer")


# ───────────────────── РЕГИСТРАЦИЯ КОМПАНИИ (новый работодатель) ────────────
@router.message(EmployerForm.company, F.text)
async def on_company(message: Message, state: FSMContext) -> None:
    company = clean_text(message.text or "", max_len=128)
    if not company:
        await message.answer(RU["validation_text_empty"])
        return
    await state.update_data(company=company)
    await state.set_state(EmployerForm.contact_person)
    await message.answer(RU["ask_contact_person"])


@router.message(EmployerForm.contact_person, F.text)
async def on_contact_person(message: Message, state: FSMContext) -> None:
    person = clean_text(message.text or "", max_len=128)
    if not person:
        await message.answer(RU["validation_text_empty"])
        return
    await state.update_data(contact_person=person)
    await state.set_state(EmployerForm.phone)
    await message.answer(RU["ask_employer_phone"], reply_markup=request_contact_keyboard())


@router.message(EmployerForm.phone, F.contact)
async def on_phone(message: Message, state: FSMContext, user: User) -> None:
    contact = message.contact
    assert contact is not None
    # Номер принимаем всегда (без тупиков в регистрации). Отметка phone_verified
    # ставится только если контакт действительно принадлежит этому аккаунту.
    verified = contact.user_id == user.tg_id
    await state.update_data(phone=contact.phone_number, phone_verified=verified)
    await _ask_city(message, state)


@router.message(EmployerForm.phone, F.text)
async def on_phone_typed(message: Message, state: FSMContext) -> None:
    phone = parse_phone(message.text or "")
    if phone is None:
        await message.answer(RU["validation_phone"])
        return
    await state.update_data(phone=phone, phone_verified=False)
    await _ask_city(message, state)


# ──────────────────────────── СОЗДАНИЕ ВАКАНСИИ ────────────────────────────
async def _ask_city(message: Message, state: FSMContext) -> None:
    await state.set_state(EmployerForm.city)
    await message.answer(RU["ask_employer_city"], reply_markup=cancel_keyboard())


@router.message(EmployerForm.city, F.text)
async def on_city(message: Message, state: FSMContext) -> None:
    await state.update_data(city=clean_text(message.text or "", max_len=64))
    await state.set_state(EmployerForm.position)
    await message.answer(RU["ask_position"], reply_markup=position_keyboard())


@router.callback_query(EmployerForm.position, PositionCB.filter())
async def on_position_pick(
    callback: CallbackQuery, callback_data: PositionCB, state: FSMContext
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if callback_data.value == "custom":
        await state.set_state(EmployerForm.position_custom)
        await callback.message.answer("Напишите название должности 👇")
        return
    await state.update_data(
        position=callback_data.value, position_normalized=callback_data.value
    )
    await state.set_state(EmployerForm.requirements)
    await callback.message.answer(RU["ask_requirements"])


@router.message(EmployerForm.position_custom, F.text)
@router.message(EmployerForm.position, F.text)
async def on_position_custom(message: Message, state: FSMContext) -> None:
    position = clean_text(message.text or "", max_len=128)
    if not position:
        await message.answer(RU["validation_text_empty"])
        return
    await state.update_data(
        position=position, position_normalized=await resolve_position(position)
    )
    await state.set_state(EmployerForm.requirements)
    await message.answer(RU["ask_requirements"])


@router.message(EmployerForm.requirements, F.text)
async def on_requirements(message: Message, state: FSMContext) -> None:
    text = clean_text(message.text or "")
    # AI вытаскивает из свободного текста минимальный опыт, навыки и сводку;
    # без AI — regex по опыту, остальное остаётся как исходный текст.
    requirements, experience_min = await structure_requirements(text)
    await state.update_data(
        requirements=requirements, experience_min=experience_min
    )
    await state.set_state(EmployerForm.conditions)
    await message.answer(RU["ask_conditions"], reply_markup=skip_keyboard("conditions"))


@router.message(EmployerForm.conditions, F.text)
async def on_conditions(message: Message, state: FSMContext) -> None:
    await state.update_data(conditions=clean_text(message.text or ""))
    await _ask_salary_min(message, state)


@router.callback_query(EmployerForm.conditions, SkipCB.filter())
async def on_conditions_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(conditions=None)
    if isinstance(callback.message, Message):
        await _ask_salary_min(callback.message, state)


async def _ask_salary_min(message: Message, state: FSMContext) -> None:
    await state.set_state(EmployerForm.salary_min)
    await message.answer(RU["ask_vacancy_salary_min"])


@router.message(EmployerForm.salary_min, F.text)
async def on_salary_min(message: Message, state: FSMContext) -> None:
    salary = parse_salary(message.text or "")
    if salary is None:
        await message.answer(RU["validation_salary"])
        return
    await state.update_data(salary_min=salary)
    await state.set_state(EmployerForm.salary_max)
    await message.answer(RU["ask_vacancy_salary_max"])


@router.message(EmployerForm.salary_max, F.text)
async def on_salary_max(message: Message, state: FSMContext) -> None:
    salary = parse_salary(message.text or "")
    if salary is None:
        await message.answer(RU["validation_salary"])
        return
    data = await state.get_data()
    if salary < data["salary_min"]:
        await message.answer(RU["validation_salary_range"])
        return
    await state.update_data(salary_max=salary)
    await state.set_state(EmployerForm.schedule)
    await message.answer(RU["ask_vacancy_schedule"], reply_markup=schedule_keyboard())


@router.callback_query(EmployerForm.schedule, ScheduleCB.filter())
async def on_schedule(
    callback: CallbackQuery, callback_data: ScheduleCB, state: FSMContext
) -> None:
    await callback.answer()
    await state.update_data(schedule=Schedule(callback_data.value).value)
    await state.set_state(EmployerForm.address)
    if isinstance(callback.message, Message):
        await callback.message.answer(RU["ask_address"])


@router.message(EmployerForm.schedule)
async def on_schedule_invalid(message: Message) -> None:
    await message.answer("Выберите график кнопкой ниже 👇")


@router.message(EmployerForm.address, F.text)
async def on_address(message: Message, state: FSMContext) -> None:
    await state.update_data(address=clean_text(message.text or "", max_len=256))
    await state.set_state(EmployerForm.photo)
    await message.answer(RU["ask_vacancy_photo"], reply_markup=skip_keyboard("vacancy_photo"))


@router.message(EmployerForm.photo, F.photo)
async def on_photo(message: Message, state: FSMContext) -> None:
    assert message.photo is not None
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await _show_confirm(message, state)


@router.callback_query(EmployerForm.photo, SkipCB.filter())
async def on_photo_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(photo_file_id=None)
    if isinstance(callback.message, Message):
        await _show_confirm(callback.message, state)


async def _show_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(EmployerForm.confirm)

    company = data.get("company", "ваша компания")
    preview = Vacancy(
        position=data["position"],
        position_normalized=data["position_normalized"],
        city=data["city"],
        salary_min=data["salary_min"],
        salary_max=data["salary_max"],
        schedule=data["schedule"],
        address=data["address"],
        conditions=data.get("conditions"),
        requirements=data.get("requirements") or {"raw": ""},
    )
    preview.employer = Employer(company_name=company)
    await message.answer(RU["confirm_vacancy_title"], reply_markup=cancel_keyboard())
    summary = render_vacancy_summary(preview)
    if data.get("photo_file_id"):
        await message.answer_photo(
            photo=data["photo_file_id"], caption=summary,
            reply_markup=confirm_keyboard("vacancy"),
        )
    else:
        await message.answer(summary, reply_markup=confirm_keyboard("vacancy"))


@router.callback_query(EmployerForm.confirm, ConfirmCB.filter(F.target == "vacancy"))
async def on_confirm(
    callback: CallbackQuery,
    callback_data: ConfirmCB,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    await callback.answer()
    msg = callback.message if isinstance(callback.message, Message) else None
    if msg is None:
        return

    if callback_data.action == "edit":
        await start_employer_form(msg, state, session, user.id)
        return

    data = await state.get_data()
    await state.clear()

    if data.get("is_returning"):
        await _save_returning(callback, msg, session, data)
    else:
        await _save_new_employer(callback, msg, session, user, data)


async def _save_returning(
    callback: CallbackQuery, msg: Message, session: AsyncSession, data: dict[str, Any]
) -> None:
    employers = EmployerRepo(session)
    employer = await employers.get_by_id(data["employer_id"])
    if employer is None:
        await show_main_menu(msg, Role.EMPLOYER, text=RU["error_generic"])
        return

    verified = employer.is_verified
    vacancy = await VacancyRepo(session).create(
        employer_id=employer.id,
        position=data["position"],
        position_normalized=data["position_normalized"],
        city=data["city"],
        salary_min=data["salary_min"],
        salary_max=data["salary_max"],
        schedule=data["schedule"],
        address=data["address"],
        conditions=data.get("conditions"),
        experience_min=data.get("experience_min", 0),
        requirements=data.get("requirements") or {"raw": ""},
        photo_file_id=data.get("photo_file_id"),
        status=VacancyStatus.ACTIVE if verified else VacancyStatus.IN_PROGRESS,
    )
    if verified:
        matches = await announce_new_vacancy(callback.bot, session, vacancy)  # type: ignore[arg-type]
        text = RU["vacancy_saved"]
        if matches:
            text += f"\n\nПодходящих кандидатов: {matches}."
        await show_main_menu(msg, Role.EMPLOYER, text=text)
    else:
        await show_main_menu(msg, Role.EMPLOYER, text=RU["vacancy_saved_pending"])
    if not await AccessControlService(session).has_full_access(employer.user_id):
        await offer_subscription_prompt(msg, Role.EMPLOYER)


async def _save_new_employer(
    callback: CallbackQuery,
    msg: Message,
    session: AsyncSession,
    user: User,
    data: dict[str, Any],
) -> None:
    employer = await EmployerRepo(session).upsert(
        user_id=user.id,
        company_name=data["company"],
        city=data["city"],
        contact_person=data["contact_person"],
        phone=data["phone"],
        bin=None,
        phone_verified=data.get("phone_verified", False),
        verification_status=VerificationStatus.PENDING,
    )
    vacancy = await VacancyRepo(session).create(
        employer_id=employer.id,
        position=data["position"],
        position_normalized=data["position_normalized"],
        city=data["city"],
        salary_min=data["salary_min"],
        salary_max=data["salary_max"],
        schedule=data["schedule"],
        address=data["address"],
        conditions=data.get("conditions"),
        experience_min=data.get("experience_min", 0),
        requirements=data.get("requirements") or {"raw": ""},
        photo_file_id=data.get("photo_file_id"),
        status=VacancyStatus.IN_PROGRESS,
    )
    approved = await VerificationService(session).route_after_registration(
        callback.bot, employer, vacancy  # type: ignore[arg-type]
    )
    if approved:
        await msg.answer(RU["employer_approved_self"])
        await show_main_menu(msg, Role.EMPLOYER, text=RU["vacancy_saved"])
    else:
        await show_main_menu(
            msg, Role.EMPLOYER,
            text=RU["employer_pending"].format(company=employer.company_name),
        )
    if not await AccessControlService(session).has_full_access(user.id):
        await offer_subscription_prompt(msg, Role.EMPLOYER)


# ──────────────────────────── ПРОСМОТР ВАКАНСИЙ ────────────────────────────
async def show_employer_vacancies(
    message: Message, session: AsyncSession, user: User
) -> None:
    employer = await EmployerRepo(session).get_by_user_id(user.id)
    if employer is None:
        await message.answer(RU["profile_none_employer"])
        return

    status_line = {
        VerificationStatus.PENDING: "⏳ Компания на проверке",
        VerificationStatus.APPROVED: "✅ Компания проверена",
        VerificationStatus.REJECTED: "❌ Проверка не пройдена",
    }.get(employer.verification_status, "")
    await message.answer(f"🏢 <b>{employer.company_name}</b>\n{status_line}")

    vacancies = await VacancyRepo(session).list_by_employer(employer.id)
    if not vacancies:
        await message.answer("Вакансий пока нет. Создайте — «➕ Новая вакансия».")
        return
    for vacancy in vacancies:
        vacancy.employer = employer
        vstatus = {
            VacancyStatus.ACTIVE: "🟢 активна",
            VacancyStatus.IN_PROGRESS: "⏳ ожидает проверки",
            VacancyStatus.CLOSED: "⚪️ закрыта",
        }.get(vacancy.status, "")
        summary = f"{render_vacancy_summary(vacancy)}\n\nСтатус: {vstatus}"
        kb = vacancy_actions_keyboard(
            vacancy.id, is_closed=vacancy.status == VacancyStatus.CLOSED
        )
        if vacancy.photo_file_id:
            await message.answer_photo(
                photo=vacancy.photo_file_id, caption=summary, reply_markup=kb
            )
        else:
            await message.answer(summary, reply_markup=kb)


@router.callback_query(VacancyActionCB.filter())
async def on_vacancy_action(
    callback: CallbackQuery, callback_data: VacancyActionCB, session: AsyncSession, user: User
) -> None:
    vacancies = VacancyRepo(session)
    vacancy = await vacancies.get(callback_data.vacancy_id)
    employer = await EmployerRepo(session).get_by_user_id(user.id)
    # Действие доступно только владельцу вакансии.
    if vacancy is None or employer is None or vacancy.employer_id != employer.id:
        await callback.answer(RU["error_generic"], show_alert=True)
        return

    if callback_data.action == "close":
        await vacancies.set_status(vacancy, VacancyStatus.CLOSED)
        await callback.answer(RU["vacancy_closed"])
    else:  # reopen
        new_status = (
            VacancyStatus.IN_PROGRESS
            if not employer.is_verified
            else VacancyStatus.ACTIVE
        )
        await vacancies.set_status(vacancy, new_status)
        await callback.answer(RU["vacancy_reopened"])

    if isinstance(callback.message, Message):
        is_closed = vacancy.status == VacancyStatus.CLOSED
        with suppress(Exception):
            await callback.message.edit_reply_markup(
                reply_markup=vacancy_actions_keyboard(vacancy.id, is_closed=is_closed)
            )
