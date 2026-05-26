"""/start, выбор роли, /cancel, /help, intent-fallback (ТЗ §1).

Пользователь может иметь обе роли; `User.role` хранит активную роль интерфейса.
"""

from __future__ import annotations

from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Intent, Role
from app.db.models.user import User
from app.handlers.browse import browse_candidates, browse_vacancies
from app.handlers.ui import show_main_menu, start_candidate_form, start_employer_form
from app.keyboards.callbacks import RoleCB
from app.keyboards.inline import role_keyboard
from app.locales import RU
from app.repositories.user import UserRepo
from app.services.conversation import ConversationService
from app.services.gemini import gemini
from app.services.intent import detect_intent, resolve_intent
from app.services.referrals import ReferralService, parse_start_param
from app.services.roles import has_profile, preferred_role

router = Router(name="common")
# Отдельный роутер для catch-all — регистрируется ПОСЛЕДНИМ (см. bot.py).
fallback_router = Router(name="fallback")

async def _route_by_role(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    """Отправляет пользователя в нужное место по зафиксированной роли."""
    role = await preferred_role(session, user.id, user.role)
    if role is not None:
        if user.role != role:
            await UserRepo(session).set_role(user, role)
        await show_main_menu(message, role, text=RU["start_back"])
        return

    await message.answer(RU["start_greeting"], reply_markup=role_keyboard())


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    await state.clear()

    referrer_id = parse_start_param(command.args)
    if referrer_id is not None and referrer_id != user.id:
        with suppress(Exception):
            await ReferralService(session).attach_referrer(
                referrer_id=referrer_id, referee_id=user.id
            )

    await _route_by_role(message, state, session, user)


@router.callback_query(RoleCB.filter())
async def on_role_chosen(
    callback: CallbackQuery,
    callback_data: RoleCB,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    desired = Role(callback_data.value)
    await callback.answer()
    msg = callback.message if isinstance(callback.message, Message) else None
    if msg is None:
        return

    await UserRepo(session).set_role(user, desired)
    if await has_profile(session, user.id, desired):
        await show_main_menu(msg, desired, text=RU["role_switched"])
        return

    if desired == Role.CANDIDATE:
        await start_candidate_form(msg, state)
    else:
        await start_employer_form(msg, state, session, user.id)


@router.message(Command("cancel"))
@router.message(F.text == RU["btn_cancel"])
async def cmd_cancel(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await show_main_menu(message, user.role, text=RU["cancelled"])


@router.message(Command("menu"))
async def cmd_menu(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await state.clear()
    await _route_by_role(message, state, session, user)


@router.message(Command("help"))
@router.message(F.text == RU["menu_help"])
async def cmd_help(message: Message) -> None:
    await message.answer(RU["help"])


@router.message(Command("myid"))
async def cmd_myid(message: Message, user: User) -> None:
    """Показывает Telegram ID — нужно, чтобы выдать себе права модератора."""
    await message.answer(
        f"🆔 Ваш Telegram ID: <code>{user.tg_id}</code>\n\n"
        "Чтобы получить доступ к модерации (/admin), впишите этот ID в "
        "<code>ADMIN_IDS</code> в файле <code>.env</code> и перезапустите бота."
    )


# ── catch-all: распознаём интент только вне FSM и вне известных кнопок ──────
@fallback_router.message(StateFilter(None), F.text, ~F.via_bot)
async def fallback_text(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    if not message.text:
        return

    role = await preferred_role(session, user.id, user.role)
    if role is not None:
        # Зарегистрированный пользователь. Явное намерение действовать — ведём
        # сразу в нужную функцию, а не в общий AI-ответ.
        intent = detect_intent(message.text).intent
        if role == Role.CANDIDATE and intent == Intent.SEEKING_JOB:
            await browse_vacancies(message, session, user)
            return
        if role == Role.EMPLOYER and intent == Intent.SEEKING_EMPLOYEE:
            await browse_candidates(message, session, user)
            return

        # Иначе — вопрос в поддержку. Контекст сообщает AI, что профиль уже есть,
        # чтобы он не предлагал «заполнить анкету» повторно.
        history = await ConversationService(session).recent_context(user.id)
        role_label = "соискатель" if role == Role.CANDIDATE else "работодатель"
        context = (
            f"Пользователь уже зарегистрирован как {role_label}, профиль заполнен. "
            f"Не предлагай заполнять анкету заново.\n{history}"
        ).strip()
        answer = await gemini.answer_support(message.text, context=context)
        if answer:
            await message.answer(answer)
            await show_main_menu(message, role)
        else:
            await show_main_menu(message, role, text=RU["unknown_command"])
        return

    result = await resolve_intent(message.text)
    if result.intent == Intent.SEEKING_JOB:
        await UserRepo(session).set_role(user, Role.CANDIDATE)
        await start_candidate_form(message, state)
    elif result.intent == Intent.SEEKING_EMPLOYEE:
        await UserRepo(session).set_role(user, Role.EMPLOYER)
        await start_employer_form(message, state, session, user.id)
    else:
        await message.answer(RU["start_greeting"], reply_markup=role_keyboard())
