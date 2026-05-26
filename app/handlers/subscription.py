"""Команды подписки: /pay, /subscription, callback оплаты (ТЗ §10)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import Role, Tariff
from app.db.models.user import User
from app.keyboards.callbacks import PaymentCB, TariffCB
from app.keyboards.inline import pay_now_keyboard, tariff_keyboard
from app.locales import RU
from app.services.access_control import AccessControlService
from app.services.payments import PaymentService, tariff_info
from app.services.referrals import ReferralService
from app.utils.time import utcnow

router = Router(name="subscription")


@router.message(Command("subscription", "my_subscription"))
@router.message(F.text == RU["menu_subscription"])
async def cmd_subscription(message: Message, session: AsyncSession, user: User) -> None:
    sub = await AccessControlService(session).get_active_subscription(user.id)
    if sub is None:
        await message.answer(
            RU["subscription_required"] + "\n\n" + RU["subscription_choose_tariff"],
            reply_markup=tariff_keyboard(_role_to_kb(user.role)),
        )
        return

    days_left = max(0, (sub.expires_at - utcnow()).days)
    await message.answer(
        RU["subscription_status"].format(
            tariff=tariff_info(Tariff(sub.tariff)).label,
            days_left=days_left,
            status=RU["subscription_active"],
        )
    )


@router.message(Command("pay"))
async def cmd_pay(message: Message, user: User) -> None:
    await message.answer(
        RU["subscription_choose_tariff"],
        reply_markup=tariff_keyboard(_role_to_kb(user.role)),
    )


@router.callback_query(TariffCB.filter())
async def on_tariff_chosen(
    callback: CallbackQuery, callback_data: TariffCB
) -> None:
    tariff = Tariff(callback_data.value)
    info = tariff_info(tariff)
    simulate = settings.payment_provider in {"manual", "simulation"}
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            RU["subscription_tariff_card"].format(label=info.label, price=info.price),
            reply_markup=pay_now_keyboard(tariff, simulate=simulate),
        )


@router.callback_query(PaymentCB.filter())
async def on_pay_start(
    callback: CallbackQuery,
    callback_data: PaymentCB,
    session: AsyncSession,
    user: User,
) -> None:
    tariff = Tariff(callback_data.tariff)
    await callback.answer()
    if callback_data.action == "simulate":
        sub = await PaymentService(session).simulate_payment(user_id=user.id, tariff=tariff)
        await ReferralService(session).grant_on_payment(user.id)
        if callback.message:
            await callback.message.answer(
                RU["payment_simulated"].format(until=sub.expires_at.strftime("%Y-%m-%d"))
            )
        return

    link = await PaymentService(session).create_payment_link(user_id=user.id, tariff=tariff)
    if callback.message:
        await callback.message.answer(RU["payment_link"].format(link=link))


def _role_to_kb(role: Role | None) -> str:
    return "candidate" if role == Role.CANDIDATE else "employer"


async def offer_subscription_prompt(message: Message, role: Role | None) -> None:
    await message.answer(
        RU["subscription_offer_after_profile"],
        reply_markup=tariff_keyboard(_role_to_kb(role)),
    )
