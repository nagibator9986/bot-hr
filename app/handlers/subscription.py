"""Подписка: тариф → оплата через Kaspi (заявка админу) или промокод (ТЗ §10)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import Role, Tariff
from app.core.exceptions import PromoError
from app.db.models.user import User
from app.keyboards.callbacks import PaymentCB, TariffCB
from app.keyboards.inline import payment_claim_keyboard, tariff_keyboard
from app.locales import RU
from app.repositories.promo import PaymentClaimRepo
from app.services.access_control import AccessControlService
from app.services.notifications import NotificationService
from app.services.payments import tariff_info
from app.services.promo import PromoService
from app.states.promo import PromoForm
from app.utils.time import utcnow
from app.utils.validators import clean_text

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
async def on_tariff_chosen(callback: CallbackQuery, callback_data: TariffCB) -> None:
    from app.keyboards.inline import pay_now_keyboard

    tariff = Tariff(callback_data.value)
    info = tariff_info(tariff)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            RU["subscription_tariff_card"].format(label=info.label, price=info.price),
            reply_markup=pay_now_keyboard(tariff, kaspi_url=settings.kaspi_payment_url),
        )


@router.callback_query(PaymentCB.filter(F.action == "claim"))
async def on_payment_claim(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession, user: User
) -> None:
    """Пользователь нажал «Я оплатил» — заводим заявку и зовём админов."""
    tariff = Tariff(callback_data.tariff)
    info = tariff_info(tariff)
    await callback.answer()

    claim = await PaymentClaimRepo(session).create(
        user_id=user.id, tariff=tariff, amount=info.price
    )
    await _notify_admins_about_claim(callback, user, tariff, claim.id)

    if callback.message:
        await callback.message.answer(RU["payment_claim_sent"])


@router.callback_query(PaymentCB.filter(F.action == "promo"))
async def on_promo_start(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    await callback.answer()
    await state.set_state(PromoForm.waiting_code)
    if callback.message:
        await callback.message.answer(RU["promo_ask_code"])


@router.message(PromoForm.waiting_code, F.text)
async def on_promo_code(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    code = clean_text(message.text or "", max_len=32)
    if not code:
        await message.answer(RU["promo_ask_code"])
        return
    await state.clear()
    try:
        sub = await PromoService(session).redeem(user_id=user.id, code=code)
    except PromoError as e:
        await message.answer(e.user_message)
        return
    await message.answer(
        RU["promo_activated"].format(
            tariff=tariff_info(Tariff(sub.tariff)).label,
            until=sub.expires_at.strftime("%Y-%m-%d"),
        )
    )


async def _notify_admins_about_claim(
    callback: CallbackQuery, user: User, tariff: Tariff, claim_id: int
) -> None:
    info = tariff_info(tariff)
    notifier = NotificationService(callback.bot)  # type: ignore[arg-type]
    username = f"@{user.tg_username}" if user.tg_username else "—"
    text = RU["admin_payment_claim"].format(
        tg_id=user.tg_id, username=username, label=info.label, price=info.price
    )
    kb = payment_claim_keyboard(claim_id)
    for admin_id in settings.admin_ids:
        await notifier.send(admin_id, text, reply_markup=kb)


def _role_to_kb(role: Role | None) -> str:
    return "candidate" if role == Role.CANDIDATE else "employer"


async def offer_subscription_prompt(message: Message, role: Role | None) -> None:
    await message.answer(
        RU["subscription_offer_after_profile"],
        reply_markup=tariff_keyboard(_role_to_kb(role)),
    )
