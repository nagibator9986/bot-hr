"""Реферальная программа: «Пригласить друга», «Мой баланс», «Вывести» (ТЗ §11)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import InsufficientBalanceError
from app.db.models.user import User
from app.keyboards.callbacks import ReferralCB
from app.keyboards.inline import referral_keyboard
from app.locales import RU
from app.services.referrals import ReferralService, make_referral_link
from app.states.withdrawal import WithdrawalForm
from app.utils.validators import parse_phone

router = Router(name="referral")


@router.message(Command("invite", "referral"))
@router.message(F.text == RU["btn_invite"])
async def cmd_invite(message: Message, session: AsyncSession, user: User) -> None:
    invited, granted, balance = await ReferralService(session).referrer_stats(user.id)
    link = make_referral_link(settings.bot_username, user.id)
    await message.answer(
        RU["referral_card"].format(
            link=link, invited=invited, granted=granted, balance=balance
        ),
        reply_markup=referral_keyboard(),
    )


@router.callback_query(ReferralCB.filter(F.action == "balance"))
async def on_balance(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> None:
    balance = await ReferralService(session).get_balance(user.id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(RU["balance_card"].format(balance=balance))


@router.callback_query(ReferralCB.filter(F.action == "withdraw"))
async def on_withdraw_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    balance = await ReferralService(session).get_balance(user.id)
    if balance < settings.referral_min_withdrawal:
        await callback.answer(
            RU["withdrawal_min"].format(amount=settings.referral_min_withdrawal),
            show_alert=True,
        )
        return

    await callback.answer()
    await state.update_data(amount=balance)
    await state.set_state(WithdrawalForm.kaspi_phone)
    if callback.message:
        await callback.message.answer(RU["ask_kaspi_phone"])


@router.message(WithdrawalForm.kaspi_phone, F.text)
async def on_kaspi_phone(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    phone = parse_phone(message.text or "")
    if phone is None:
        await message.answer(RU["validation_phone"])
        return

    data = await state.get_data()
    amount = data["amount"]
    try:
        await ReferralService(session).request_withdrawal(
            user_id=user.id, amount=amount, kaspi_phone=phone
        )
    except InsufficientBalanceError as e:
        await message.answer(e.user_message)
        await state.clear()
        return

    await state.clear()
    await message.answer(RU["withdrawal_submitted"])
