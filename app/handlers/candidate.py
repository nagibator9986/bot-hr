"""Сценарий соискателя: анкета (11 шагов), подтверждение, редактирование."""

from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CandidateStatus, Role, Schedule
from app.db.models.candidate import Candidate
from app.db.models.user import User
from app.handlers.subscription import offer_subscription_prompt
from app.handlers.ui import show_main_menu
from app.keyboards.callbacks import (
    AboutPolishCB,
    ConfirmCB,
    EditFieldCB,
    PositionCB,
    ScheduleCB,
    SkipCB,
)
from app.keyboards.inline import (
    about_polish_keyboard,
    confirm_keyboard,
    edit_fields_keyboard,
    position_keyboard,
    schedule_keyboard,
    skip_keyboard,
)
from app.keyboards.reply import cancel_keyboard, request_contact_keyboard
from app.locales import RU
from app.repositories.candidate import CandidateRepo
from app.services.access_control import AccessControlService
from app.services.enrichment import resolve_position
from app.services.gemini import gemini
from app.services.notifications import announce_new_candidate
from app.services.profile import render_candidate_summary
from app.states.candidate import CandidateEdit, CandidateForm
from app.utils.validators import clean_text, parse_age, parse_experience, parse_phone, parse_salary

router = Router(name="candidate")


# ─────────────────────────────── РЕГИСТРАЦИЯ ───────────────────────────────
@router.message(CandidateForm.name, F.text)
async def on_name(message: Message, state: FSMContext) -> None:
    name = clean_text(message.text or "", max_len=64)
    if len(name) < 2:
        await message.answer(RU["validation_name"])
        return
    await state.update_data(name=name)
    await state.set_state(CandidateForm.age)
    await message.answer(RU["ask_age"])


@router.message(CandidateForm.age, F.text)
async def on_age(message: Message, state: FSMContext) -> None:
    age = parse_age(message.text or "")
    if age is None:
        await message.answer(RU["validation_age"])
        return
    await state.update_data(age=age)
    await state.set_state(CandidateForm.city)
    await message.answer(RU["ask_city"])


@router.message(CandidateForm.city, F.text)
async def on_city(message: Message, state: FSMContext) -> None:
    await state.update_data(city=clean_text(message.text or "", max_len=64))
    await state.set_state(CandidateForm.preferred_area)
    await message.answer(RU["ask_preferred_area"])


@router.message(CandidateForm.preferred_area, F.text)
async def on_preferred_area(message: Message, state: FSMContext) -> None:
    preferred_area = clean_text(message.text or "", max_len=128)
    if not preferred_area:
        await message.answer(RU["validation_text_empty"])
        return
    await state.update_data(preferred_area=preferred_area)
    await state.set_state(CandidateForm.desired_position)
    await message.answer(RU["ask_desired_position"], reply_markup=position_keyboard())


@router.callback_query(CandidateForm.desired_position, PositionCB.filter())
async def on_position_pick(
    callback: CallbackQuery, callback_data: PositionCB, state: FSMContext
) -> None:
    await callback.answer()
    if callback_data.value == "custom":
        await state.set_state(CandidateForm.desired_position_custom)
        if isinstance(callback.message, Message):
            await callback.message.answer("Напишите название должности 👇")
        return
    await state.update_data(
        desired_position=callback_data.value,
        position_normalized=callback_data.value,
    )
    await state.set_state(CandidateForm.experience)
    if isinstance(callback.message, Message):
        await callback.message.answer(RU["ask_experience"])


@router.message(CandidateForm.desired_position_custom, F.text)
@router.message(CandidateForm.desired_position, F.text)
async def on_position_custom(message: Message, state: FSMContext) -> None:
    """Принимаем должность и текстом тоже — не заставляем жать кнопку."""
    position = clean_text(message.text or "", max_len=128)
    if not position:
        await message.answer(RU["validation_text_empty"])
        return
    await state.update_data(
        desired_position=position,
        position_normalized=await resolve_position(position),
    )
    await state.set_state(CandidateForm.experience)
    await message.answer(RU["ask_experience"])


@router.message(CandidateForm.experience, F.text)
async def on_experience(message: Message, state: FSMContext) -> None:
    years = parse_experience(message.text or "")
    if years is None:
        await message.answer(RU["validation_experience"])
        return
    await state.update_data(experience_years=years)
    await state.set_state(CandidateForm.previous_jobs)
    await message.answer(RU["ask_previous_jobs"], reply_markup=skip_keyboard("previous_jobs"))


@router.message(CandidateForm.previous_jobs, F.text)
async def on_previous_jobs(message: Message, state: FSMContext) -> None:
    await state.update_data(previous_jobs=clean_text(message.text or ""))
    await _ask_schedule(message, state)


@router.callback_query(CandidateForm.previous_jobs, SkipCB.filter())
async def on_previous_jobs_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(previous_jobs=None)
    if isinstance(callback.message, Message):
        await _ask_schedule(callback.message, state)


async def _ask_schedule(message: Message, state: FSMContext) -> None:
    await state.set_state(CandidateForm.schedule)
    await message.answer(RU["ask_schedule"], reply_markup=schedule_keyboard())


@router.callback_query(CandidateForm.schedule, ScheduleCB.filter())
async def on_schedule(
    callback: CallbackQuery, callback_data: ScheduleCB, state: FSMContext
) -> None:
    await callback.answer()
    await state.update_data(schedule=Schedule(callback_data.value).value)
    await state.set_state(CandidateForm.salary)
    if isinstance(callback.message, Message):
        await callback.message.answer(RU["ask_salary"])


@router.message(CandidateForm.schedule)
async def on_schedule_invalid(message: Message) -> None:
    await message.answer("Выберите график кнопкой ниже 👇")


@router.message(CandidateForm.salary, F.text)
async def on_salary(message: Message, state: FSMContext) -> None:
    salary = parse_salary(message.text or "")
    if salary is None:
        await message.answer(RU["validation_salary"])
        return
    await state.update_data(expected_salary=salary)
    await state.set_state(CandidateForm.about)
    await message.answer(RU["ask_about"], reply_markup=skip_keyboard("about"))


@router.message(CandidateForm.about, F.text)
async def on_about(message: Message, state: FSMContext) -> None:
    raw = clean_text(message.text or "")
    # AI предлагает аккуратную версию «о себе» — кандидат выбирает вариант сам.
    polished = await gemini.polish_about(raw)
    if polished and polished.strip().lower() != raw.strip().lower():
        await state.update_data(about=raw, about_polished=polished)
        await message.answer(
            RU["about_polish_offer"].format(polished=polished),
            reply_markup=about_polish_keyboard(),
        )
        return
    await state.update_data(about=raw)
    await _ask_photo(message, state)


@router.callback_query(CandidateForm.about, AboutPolishCB.filter())
async def on_about_polish_choice(
    callback: CallbackQuery, callback_data: AboutPolishCB, state: FSMContext
) -> None:
    await callback.answer()
    if callback_data.choice == "ai":
        data = await state.get_data()
        await state.update_data(about=data.get("about_polished"))
    if isinstance(callback.message, Message):
        with suppress(Exception):
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(RU["about_polish_applied"])
        await _ask_photo(callback.message, state)


@router.callback_query(CandidateForm.about, SkipCB.filter())
async def on_about_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(about=None)
    if isinstance(callback.message, Message):
        await _ask_photo(callback.message, state)


async def _ask_photo(message: Message, state: FSMContext) -> None:
    await state.set_state(CandidateForm.photo)
    await message.answer(RU["ask_photo"])


@router.message(CandidateForm.photo, F.photo)
async def on_photo(message: Message, state: FSMContext) -> None:
    assert message.photo is not None
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await state.set_state(CandidateForm.contact)
    await message.answer(RU["ask_contact"], reply_markup=request_contact_keyboard())


@router.message(CandidateForm.photo)
async def on_photo_invalid(message: Message) -> None:
    await message.answer(RU["ask_photo_invalid"])


@router.message(CandidateForm.contact, F.contact)
async def on_contact_shared(message: Message, state: FSMContext) -> None:
    assert message.contact is not None
    await _finish_contact(message, state, message.contact.phone_number)


@router.message(CandidateForm.contact, F.text)
async def on_contact_typed(message: Message, state: FSMContext) -> None:
    phone = parse_phone(message.text or "")
    if phone is None:
        await message.answer(RU["validation_phone"])
        return
    await _finish_contact(message, state, phone)


async def _finish_contact(message: Message, state: FSMContext, phone: str) -> None:
    data = await state.update_data(contact=phone)
    await state.set_state(CandidateForm.confirm)
    preview = Candidate(
        name=data["name"],
        age=data["age"],
        city=data["city"],
        preferred_area=data.get("preferred_area"),
        desired_position=data["desired_position"],
        position_normalized=data["position_normalized"],
        experience_years=data["experience_years"],
        previous_jobs=data.get("previous_jobs"),
        schedule=data["schedule"],
        expected_salary=data["expected_salary"],
        contact=data["contact"],
        about=data.get("about"),
    )
    await message.answer(RU["confirm_profile_title"], reply_markup=cancel_keyboard())
    await message.answer_photo(
        photo=data["photo_file_id"],
        caption=render_candidate_summary(preview),
        reply_markup=confirm_keyboard("candidate"),
    )


@router.callback_query(CandidateForm.confirm, ConfirmCB.filter(F.target == "candidate"))
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
        await _show_edit_menu(msg)
        await state.set_state(CandidateEdit.choosing_field)
        return

    data = await state.get_data()
    candidate = await _save_candidate(session, user.id, data)
    await state.clear()

    matches = await announce_new_candidate(callback.bot, session, candidate)  # type: ignore[arg-type]
    text = RU["candidate_saved"]
    if matches:
        text += f"\n\nПодходящих вакансий: {matches}. Откройте «🔍 Смотреть вакансии»."
    await show_main_menu(msg, Role.CANDIDATE, text=text)
    if not await AccessControlService(session).has_full_access(user.id):
        await offer_subscription_prompt(msg, Role.CANDIDATE)


async def _save_candidate(
    session: AsyncSession, user_id: int, data: dict[str, object]
) -> Candidate:
    return await CandidateRepo(session).upsert(
        user_id=user_id,
        name=data["name"],
        age=data["age"],
        city=data["city"],
        preferred_area=data.get("preferred_area"),
        desired_position=data["desired_position"],
        position_normalized=data["position_normalized"],
        experience_years=data["experience_years"],
        previous_jobs=data.get("previous_jobs"),
        schedule=data["schedule"],
        expected_salary=data["expected_salary"],
        contact=data["contact"],
        photo_file_id=data["photo_file_id"],
        resume_file_id=data.get("resume_file_id"),
        resume_file_name=data.get("resume_file_name"),
        about=data.get("about"),
        status=CandidateStatus.SEARCHING,
    )


# ──────────────────────── ПРОСМОТР И РЕДАКТИРОВАНИЕ ─────────────────────────
async def show_candidate_profile(
    message: Message, session: AsyncSession, user: User
) -> None:
    candidate = await CandidateRepo(session).get_by_user_id(user.id)
    if candidate is None:
        await message.answer(RU["profile_none_candidate"])
        return
    await message.answer_photo(
        photo=candidate.photo_file_id,
        caption=render_candidate_summary(candidate),
    )
    if candidate.resume_file_id:
        await message.answer_document(
            document=candidate.resume_file_id, caption="📎 Ваше резюме"
        )


async def start_candidate_edit(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    candidate = await CandidateRepo(session).get_by_user_id(user.id)
    if candidate is None:
        await message.answer(RU["profile_none_candidate"])
        return
    await _show_edit_menu(message)
    await state.set_state(CandidateEdit.choosing_field)


async def _show_edit_menu(message: Message) -> None:
    await message.answer(RU["edit_what"], reply_markup=edit_fields_keyboard())


_EDIT_PROMPTS: dict[str, tuple[object, str]] = {
    "name": (CandidateEdit.name, RU["ask_name"]),
    "age": (CandidateEdit.age, RU["ask_age"]),
    "city": (CandidateEdit.city, RU["ask_city"]),
    "preferred_area": (CandidateEdit.preferred_area, RU["ask_preferred_area"]),
    "position": (CandidateEdit.position, RU["ask_desired_position"]),
    "experience": (CandidateEdit.experience, RU["ask_experience"]),
    "schedule": (CandidateEdit.schedule, RU["ask_schedule"]),
    "salary": (CandidateEdit.salary, RU["ask_salary"]),
    "about": (CandidateEdit.about, RU["ask_about"]),
    "photo": (CandidateEdit.photo, RU["ask_photo"]),
    "contact": (CandidateEdit.contact, RU["ask_contact"]),
}


@router.callback_query(CandidateEdit.choosing_field, EditFieldCB.filter())
async def on_edit_field_chosen(
    callback: CallbackQuery, callback_data: EditFieldCB, state: FSMContext
) -> None:
    await callback.answer()
    entry = _EDIT_PROMPTS.get(callback_data.field)
    if entry is None or not isinstance(callback.message, Message):
        return
    target_state, prompt = entry
    await state.set_state(target_state)  # type: ignore[arg-type]
    if callback_data.field == "position":
        await callback.message.answer(prompt, reply_markup=position_keyboard())
    elif callback_data.field == "schedule":
        await callback.message.answer(prompt, reply_markup=schedule_keyboard())
    elif callback_data.field == "contact":
        await callback.message.answer(prompt, reply_markup=request_contact_keyboard())
    else:
        await callback.message.answer(prompt)


async def _apply_edit(
    message: Message, state: FSMContext, session: AsyncSession, user: User, **field: object
) -> None:
    await CandidateRepo(session).upsert(user_id=user.id, **field)
    await state.set_state(CandidateEdit.choosing_field)
    await message.answer(RU["edit_done"])
    await _show_edit_menu(message)


@router.message(CandidateEdit.name, F.text)
async def edit_name(message: Message, state: FSMContext, session: AsyncSession,
                    user: User) -> None:
    name = clean_text(message.text or "", max_len=64)
    if len(name) < 2:
        await message.answer(RU["validation_name"])
        return
    await _apply_edit(message, state, session, user, name=name)


@router.message(CandidateEdit.age, F.text)
async def edit_age(message: Message, state: FSMContext, session: AsyncSession,
                   user: User) -> None:
    age = parse_age(message.text or "")
    if age is None:
        await message.answer(RU["validation_age"])
        return
    await _apply_edit(message, state, session, user, age=age)


@router.message(CandidateEdit.city, F.text)
async def edit_city(message: Message, state: FSMContext, session: AsyncSession,
                    user: User) -> None:
    await _apply_edit(message, state, session, user,
                      city=clean_text(message.text or "", max_len=64))


@router.message(CandidateEdit.preferred_area, F.text)
async def edit_preferred_area(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    value = clean_text(message.text or "", max_len=128)
    if not value:
        await message.answer(RU["validation_text_empty"])
        return
    await _apply_edit(message, state, session, user, preferred_area=value)


@router.callback_query(CandidateEdit.position, PositionCB.filter())
async def edit_position_pick(
    callback: CallbackQuery, callback_data: PositionCB, state: FSMContext,
    session: AsyncSession, user: User,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if callback_data.value == "custom":
        await callback.message.answer("Напишите название должности 👇")
        return
    await _apply_edit(
        callback.message, state, session, user,
        desired_position=callback_data.value, position_normalized=callback_data.value,
    )


@router.message(CandidateEdit.position, F.text)
async def edit_position_custom(message: Message, state: FSMContext, session: AsyncSession,
                               user: User) -> None:
    position = clean_text(message.text or "", max_len=128)
    if not position:
        await message.answer(RU["validation_text_empty"])
        return
    await _apply_edit(message, state, session, user,
                      desired_position=position,
                      position_normalized=await resolve_position(position))


@router.message(CandidateEdit.experience, F.text)
async def edit_experience(message: Message, state: FSMContext, session: AsyncSession,
                          user: User) -> None:
    years = parse_experience(message.text or "")
    if years is None:
        await message.answer(RU["validation_experience"])
        return
    await _apply_edit(message, state, session, user, experience_years=years)


@router.callback_query(CandidateEdit.schedule, ScheduleCB.filter())
async def edit_schedule(
    callback: CallbackQuery, callback_data: ScheduleCB, state: FSMContext,
    session: AsyncSession, user: User,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _apply_edit(callback.message, state, session, user,
                          schedule=Schedule(callback_data.value).value)


@router.message(CandidateEdit.salary, F.text)
async def edit_salary(message: Message, state: FSMContext, session: AsyncSession,
                      user: User) -> None:
    salary = parse_salary(message.text or "")
    if salary is None:
        await message.answer(RU["validation_salary"])
        return
    await _apply_edit(message, state, session, user, expected_salary=salary)


@router.message(CandidateEdit.about, F.text)
async def edit_about(message: Message, state: FSMContext, session: AsyncSession,
                     user: User) -> None:
    await _apply_edit(message, state, session, user, about=clean_text(message.text or ""))


@router.message(CandidateEdit.photo, F.photo)
async def edit_photo(message: Message, state: FSMContext, session: AsyncSession,
                     user: User) -> None:
    assert message.photo is not None
    await _apply_edit(message, state, session, user, photo_file_id=message.photo[-1].file_id)


@router.message(CandidateEdit.photo)
async def edit_photo_invalid(message: Message) -> None:
    await message.answer(RU["ask_photo_invalid"])


@router.message(CandidateEdit.contact, F.contact)
async def edit_contact_shared(message: Message, state: FSMContext, session: AsyncSession,
                              user: User) -> None:
    assert message.contact is not None
    await _apply_edit(message, state, session, user, contact=message.contact.phone_number)


@router.message(CandidateEdit.contact, F.text)
async def edit_contact_typed(message: Message, state: FSMContext, session: AsyncSession,
                             user: User) -> None:
    phone = parse_phone(message.text or "")
    if phone is None:
        await message.answer(RU["validation_phone"])
        return
    await _apply_edit(message, state, session, user, contact=phone)
