"""Команды администратора: вручную подтвердить платёж, обработать вывод (MVP)."""

from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import (
    PaymentClaimStatus,
    ReferralStatus,
    Tariff,
    VacancyStatus,
    VerificationStatus,
    WithdrawalStatus,
)
from app.core.exceptions import DuplicatePaymentError
from app.db.models.employer import Employer
from app.db.models.user import User
from app.keyboards.callbacks import AdminMenuCB, EmployerModerationCB, PaymentClaimCB
from app.keyboards.inline import admin_menu_keyboard
from app.locales import RU
from app.repositories.candidate import CandidateRepo
from app.repositories.match import MatchRepo
from app.repositories.promo import PaymentClaimRepo, PromoCodeRepo, PromoterRepo
from app.repositories.referral import ReferralRepo, WithdrawalRepo
from app.repositories.subscription import PaymentRepo, SubscriptionRepo
from app.repositories.user import UserRepo
from app.repositories.vacancy import EmployerRepo, VacancyRepo
from app.services.conversation import ConversationService
from app.services.notifications import NotificationService
from app.services.payments import PaymentService, tariff_info
from app.services.referrals import ReferralService, make_promoter_link
from app.services.verification import VerificationService
from app.states.employer import RejectReason
from app.utils.validators import clean_text

router = Router(name="admin")
_ADMIN_IDS = set(settings.admin_ids)
router.message.filter(F.from_user.id.in_(_ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(_ADMIN_IDS))


_ADMIN_HELP_TEXT = (
    "<b>🛡 Админ-панель</b>\n"
    "Жмите кнопки ниже — или используйте команды:\n\n"
    "/pending — работодатели на проверке\n"
    "/candidates_active — активные соискатели\n"
    "/vacancies_active — активные вакансии\n"
    "/vacancies_closed — закрытые вакансии\n"
    "/applications — кто откликнулся / взаимные интересы\n"
    "/subscribers — активные подписки и недавние оплаты\n"
    "/history <code>&lt;tg_id&gt; [limit]</code> — история диалога\n"
    "/logic — где менять бизнес-логику\n"
    "/grant <code>&lt;tg_id&gt; &lt;tariff&gt;</code> — выдать подписку\n"
    "/payouts — список заявок на вывод\n"
    "/paid <code>&lt;id&gt;</code> — пометить заявку выплаченной\n"
    "\n<b>Промокоды и промоутеры</b>\n"
    "/promo_new <code>&lt;tariff&gt; &lt;days&gt; [max_uses]</code> — создать промокод\n"
    "/promos — активные промокоды\n"
    "/promoter_new <code>&lt;имя&gt; [tg_id]</code> — создать промоутера (ссылка 1000 ₸)\n"
    "/promoters — промоутеры и их статистика\n"
    "/referrals — кто сколько привёл (топ)\n"
    "/invited_by <code>&lt;tg_id&gt;</code> — кого привёл конкретный человек"
)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer(_ADMIN_HELP_TEXT, reply_markup=admin_menu_keyboard())


@router.callback_query(AdminMenuCB.filter())
async def on_admin_menu(
    callback: CallbackQuery, callback_data: AdminMenuCB, session: AsyncSession
) -> None:
    """Маршрутизатор кнопок админ-меню — переиспользует те же функции, что и команды."""
    await callback.answer()
    msg = callback.message if isinstance(callback.message, Message) else None
    if msg is None:
        return
    action = callback_data.action
    if action == "pending":
        await cmd_pending(msg, session)
    elif action == "candidates":
        await cmd_candidates_active(msg, session)
    elif action == "vac_active":
        await cmd_vacancies_active(msg, session)
    elif action == "vac_closed":
        await cmd_vacancies_closed(msg, session)
    elif action == "apps":
        await cmd_applications(msg, session)
    elif action == "subs":
        await cmd_subscribers(msg, session)
    elif action == "payouts":
        await cmd_payouts(msg, session)
    elif action == "help":
        await msg.answer(_ADMIN_HELP_TEXT, reply_markup=admin_menu_keyboard())


# ──────────────────── Модерация работодателей (HR-проверка) ─────────────────
@router.message(Command("pending"))
async def cmd_pending(message: Message, session: AsyncSession) -> None:
    from app.keyboards.inline import employer_moderation_keyboard

    stmt = select(Employer).where(
        Employer.verification_status == VerificationStatus.PENDING
    )
    employers = list((await session.execute(stmt)).scalars().all())
    if not employers:
        await message.answer("Заявок на проверку нет.")
        return
    await message.answer(f"⏳ На проверке: {len(employers)}")
    for emp in employers:
        await message.answer(
            f"🏢 <b>{emp.company_name}</b>\n"
            f"БИН: <code>{emp.bin or '—'}</code>\n"
            f"Город: {emp.city}\n"
            f"Контакт: {emp.contact_person}, {emp.phone}",
            reply_markup=employer_moderation_keyboard(emp.id),
        )


@router.callback_query(EmployerModerationCB.filter(F.action == "approve"))
async def on_approve_employer(
    callback: CallbackQuery, callback_data: EmployerModerationCB, session: AsyncSession
) -> None:
    employer = await EmployerRepo(session).get_by_id(callback_data.employer_id)
    if employer is None or employer.verification_status != VerificationStatus.PENDING:
        await callback.answer("Эта заявка уже обработана.", show_alert=True)
        return
    await VerificationService(session).approve(callback.bot, employer)  # type: ignore[arg-type]
    await callback.answer("Одобрено ✅")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"✅ Работодатель «{employer.company_name}» одобрен."
        )


@router.callback_query(EmployerModerationCB.filter(F.action == "reject"))
async def on_reject_employer(
    callback: CallbackQuery,
    callback_data: EmployerModerationCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    employer = await EmployerRepo(session).get_by_id(callback_data.employer_id)
    if employer is None or employer.verification_status != VerificationStatus.PENDING:
        await callback.answer("Эта заявка уже обработана.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(reject_employer_id=employer.id)
    await state.set_state(RejectReason.waiting)
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"Напишите причину отклонения для «{employer.company_name}»:"
        )


@router.message(RejectReason.waiting, F.text)
async def on_reject_reason(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    await state.clear()
    employer = await EmployerRepo(session).get_by_id(data.get("reject_employer_id", 0))
    if employer is None:
        await message.answer("Работодатель не найден.")
        return
    reason = clean_text(message.text or "", max_len=256) or "не указана"
    await VerificationService(session).reject(message.bot, employer, reason)  # type: ignore[arg-type]
    await message.answer(f"❌ Работодатель «{employer.company_name}» отклонён.")


@router.message(Command("grant"))
async def cmd_grant(message: Message, session: AsyncSession) -> None:
    """/grant <tg_id> <tariff_value> — ручная активация подписки."""
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Использование: /grant <tg_id> <tariff>")
        return
    try:
        tg_id = int(parts[1])
        tariff = Tariff(parts[2])
    except (ValueError, KeyError):
        await message.answer("Неверный формат.")
        return

    from app.repositories.user import UserRepo

    target = await UserRepo(session).get_by_tg_id(tg_id)
    if target is None:
        await message.answer("Пользователь не найден.")
        return

    from app.services.payments import tariff_info

    info = tariff_info(tariff)
    sub = await PaymentService(session).confirm_payment(
        user_id=target.id,
        tariff=tariff,
        provider="manual",
        provider_payment_id=f"manual:{target.id}:{message.message_id}",
        amount=info.price,
    )
    # Если был реферер — начисляем бонус
    await ReferralService(session).grant_on_payment(target.id)
    await message.answer(
        f"✅ Подписка {info.label} активирована для tg={tg_id}, до {sub.expires_at:%Y-%m-%d}."
    )


@router.message(Command("history"))
async def cmd_history(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /history <tg_id> [limit]")
        return
    try:
        tg_id = int(parts[1])
        limit = int(parts[2]) if len(parts) >= 3 else 20
    except ValueError:
        await message.answer("Неверный формат.")
        return

    user = await UserRepo(session).get_by_tg_id(tg_id)
    if user is None:
        await message.answer("Пользователь не найден.")
        return
    lines = await ConversationService(session).history_lines(user.id, limit=limit)
    if not lines:
        await message.answer("История пока пустая.")
        return
    await message.answer(f"🗂 История tg={tg_id}\n\n" + "\n\n".join(lines))


@router.message(Command("candidates_active"))
async def cmd_candidates_active(message: Message, session: AsyncSession) -> None:
    items = await CandidateRepo(session).list_active(limit=30)
    if not items:
        await message.answer("Активных соискателей нет.")
        return
    lines = [
        (
            f"#{c.id} · {c.name} · {c.city}"
            f"{f' / {c.preferred_area}' if c.preferred_area else ''}\n"
            f"{c.desired_position} · статус: {c.status} · {c.contact}"
        )
        for c in items
    ]
    await message.answer("🧑‍🍳 <b>Активные соискатели</b>\n\n" + "\n\n".join(lines))


@router.message(Command("vacancies_active"))
async def cmd_vacancies_active(message: Message, session: AsyncSession) -> None:
    items = await VacancyRepo(session).list_by_statuses(
        [VacancyStatus.ACTIVE, VacancyStatus.IN_PROGRESS], limit=30
    )
    if not items:
        await message.answer("Активных вакансий нет.")
        return
    lines = [
        (
            f"#{v.id} · {v.position} · {v.city}\n"
            f"Компания: {v.employer.company_name if v.employer else '—'} · статус: {v.status}\n"
            f"Адрес: {v.address}"
        )
        for v in items
    ]
    await message.answer("📋 <b>Активные вакансии</b>\n\n" + "\n\n".join(lines))


@router.message(Command("vacancies_closed"))
async def cmd_vacancies_closed(message: Message, session: AsyncSession) -> None:
    items = await VacancyRepo(session).list_by_statuses([VacancyStatus.CLOSED], limit=30)
    if not items:
        await message.answer("Закрытых вакансий нет.")
        return
    lines = [
        (
            f"#{v.id} · {v.position} · {v.city}\n"
            f"Компания: {v.employer.company_name if v.employer else '—'} · статус: {v.status}"
        )
        for v in items
    ]
    await message.answer("📦 <b>Закрытые вакансии</b>\n\n" + "\n\n".join(lines))


@router.message(Command("applications"))
async def cmd_applications(message: Message, session: AsyncSession) -> None:
    items = await MatchRepo(session).list_candidate_applications(limit=30)
    if not items:
        await message.answer("Откликов пока нет.")
        return
    lines = []
    for match in items:
        company = match.vacancy.employer.company_name if match.vacancy.employer else "—"
        interview_status = match.interview.status if match.interview is not None else "нет"
        lines.append(
            f"match #{match.id} · {match.candidate.name} → {company} / {match.vacancy.position}\n"
            f"score={match.score} · candidate={match.candidate_reaction or '—'} · "
            f"employer={match.employer_reaction or '—'} · interview={interview_status}"
        )
    await message.answer("💚 <b>Заявки и интересы</b>\n\n" + "\n\n".join(lines))


@router.message(Command("subscribers"))
async def cmd_subscribers(message: Message, session: AsyncSession) -> None:
    users = UserRepo(session)
    active = await SubscriptionRepo(session).list_active(limit=30)
    payments = await PaymentRepo(session).list_success(limit=30)

    parts: list[str] = []
    if active:
        lines = []
        for sub in active:
            owner = await users.get_by_id(sub.user_id)
            tg = owner.tg_id if owner is not None else "?"
            lines.append(
                f"tg={tg} · {sub.tariff} · до {sub.expires_at:%Y-%m-%d} · viewed={sub.candidates_viewed}"
            )
        parts.append("💳 <b>Активные подписки</b>\n" + "\n".join(lines))
    if payments:
        lines = []
        for payment in payments[:15]:
            owner = await users.get_by_id(payment.user_id)
            tg = owner.tg_id if owner is not None else "?"
            lines.append(
                f"tg={tg} · {payment.tariff} · {payment.amount} ₸ · {payment.created_at:%Y-%m-%d %H:%M}"
            )
        parts.append("🧾 <b>Недавние успешные оплаты</b>\n" + "\n".join(lines))
    if not parts:
        await message.answer("Оплат и активных подписок пока нет.")
        return
    await message.answer("\n\n".join(parts))


@router.message(Command("logic"))
async def cmd_logic(message: Message) -> None:
    await message.answer(
        "<b>Где менять логику</b>\n"
        "Кандидат: app/handlers/candidate.py, app/states/candidate.py\n"
        "Работодатель: app/handlers/employer.py, app/states/employer.py\n"
        "Подписка и доступ: app/handlers/subscription.py, app/services/access_control.py, app/services/payments.py\n"
        "Подбор: app/services/matching.py, app/handlers/browse.py\n"
        "История и память: app/services/conversation.py, app/middlewares/conversation.py\n"
        "Админ-функции: app/handlers/admin.py"
    )


@router.message(Command("payouts"))
async def cmd_payouts(message: Message, session: AsyncSession) -> None:
    items = await WithdrawalRepo(session).list_pending()
    if not items:
        await message.answer("Активных заявок на вывод нет.")
        return
    lines = [
        f"#{r.id} · user={r.user_id} · {r.amount} ₸ → {r.kaspi_phone}" for r in items
    ]
    await message.answer("Заявки на вывод:\n" + "\n".join(lines))


@router.message(Command("paid"))
async def cmd_paid(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Использование: /paid <id>")
        return
    repo = WithdrawalRepo(session)
    req = next((r for r in await repo.list_pending() if r.id == int(parts[1])), None)
    if req is None:
        await message.answer("Заявка не найдена.")
        return
    await repo.set_status(req, WithdrawalStatus.PAID)
    await message.answer(f"✅ Заявка #{req.id} помечена как выплаченная.")


# ──────────────────── Подтверждение оплаты Kaspi (заявки) ───────────────────
@router.callback_query(PaymentClaimCB.filter(F.action == "approve"))
async def on_claim_approve(
    callback: CallbackQuery, callback_data: PaymentClaimCB, session: AsyncSession, user: User
) -> None:
    claims = PaymentClaimRepo(session)
    claim = await claims.get(callback_data.claim_id)
    if claim is None or claim.status != PaymentClaimStatus.PENDING:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    target = await UserRepo(session).get_by_id(claim.user_id)
    try:
        sub = await PaymentService(session).confirm_kaspi_claim(
            user_id=claim.user_id, tariff=Tariff(claim.tariff), claim_id=claim.id
        )
    except DuplicatePaymentError:
        await claims.set_status(claim, PaymentClaimStatus.APPROVED, admin_id=user.id)
        await callback.answer("Эта оплата уже была подтверждена.", show_alert=True)
        return

    await claims.set_status(claim, PaymentClaimStatus.APPROVED, admin_id=user.id)
    # Реферальный бонус — только за реальную оплату (Kaspi), здесь и начисляем.
    await ReferralService(session).grant_on_payment(claim.user_id)

    if target is not None:
        await NotificationService(callback.bot).send(  # type: ignore[arg-type]
            target.tg_id,
            RU["payment_confirmed_user"].format(until=sub.expires_at.strftime("%Y-%m-%d")),
        )
    await callback.answer("Оплата подтверждена ✅")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"✅ Оплата подтверждена для tg={target.tg_id if target else '?'}."
        )


@router.callback_query(PaymentClaimCB.filter(F.action == "reject"))
async def on_claim_reject(
    callback: CallbackQuery, callback_data: PaymentClaimCB, session: AsyncSession, user: User
) -> None:
    claims = PaymentClaimRepo(session)
    claim = await claims.get(callback_data.claim_id)
    if claim is None or claim.status != PaymentClaimStatus.PENDING:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    await claims.set_status(claim, PaymentClaimStatus.REJECTED, admin_id=user.id)
    target = await UserRepo(session).get_by_id(claim.user_id)
    if target is not None:
        await NotificationService(callback.bot).send(  # type: ignore[arg-type]
            target.tg_id, RU["payment_rejected_user"]
        )
    await callback.answer("Отклонено")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


# ──────────────────────────── Промокоды ─────────────────────────────────────
@router.message(Command("promo_new"))
async def cmd_promo_new(message: Message, session: AsyncSession) -> None:
    """/promo_new <tariff> <days> [max_uses]"""
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Использование: /promo_new <tariff> <days> [max_uses]\n"
            "tariff: candidate | employer_basic | employer_extended"
        )
        return
    try:
        tariff = Tariff(parts[1])
        days = int(parts[2])
        max_uses = int(parts[3]) if len(parts) >= 4 else None
    except (ValueError, KeyError):
        await message.answer("Неверный формат.")
        return
    code = secrets.token_hex(3).upper()
    promo = await PromoCodeRepo(session).create(
        code=code, tariff=tariff, duration_days=days, max_uses=max_uses
    )
    await message.answer(
        f"🎟 Промокод <code>{promo.code}</code>\n"
        f"Тариф: {tariff_info(tariff).label} · {days} дн · "
        f"лимит: {max_uses if max_uses is not None else '∞'}"
    )


@router.message(Command("promos"))
async def cmd_promos(message: Message, session: AsyncSession) -> None:
    items = await PromoCodeRepo(session).list_active()
    if not items:
        await message.answer("Активных промокодов нет.")
        return
    lines = [
        f"<code>{p.code}</code> · {p.tariff} · {p.duration_days} дн · "
        f"использован {p.used_count}/{p.max_uses if p.max_uses is not None else '∞'}"
        for p in items
    ]
    await message.answer("🎟 <b>Промокоды</b>\n\n" + "\n".join(lines))


# ──────────────────────────── Промоутеры ────────────────────────────────────
@router.message(Command("promoter_new"))
async def cmd_promoter_new(message: Message, session: AsyncSession) -> None:
    """/promoter_new <имя> [tg_id] — создаёт промоутера с повышенным бонусом."""
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /promoter_new <имя> [tg_id]")
        return
    name = parts[1]
    user_id: int | None = None
    if len(parts) >= 3 and parts[2].lstrip("-").isdigit():
        bound = await UserRepo(session).get_by_tg_id(int(parts[2]))
        if bound is None:
            await message.answer(
                "Этот tg_id ещё не писал боту. Пусть сотрудник нажмёт /start, "
                "или создайте без tg_id и привяжите позже."
            )
            return
        user_id = bound.id
    code = secrets.token_hex(4)
    promoter = await PromoterRepo(session).create(
        name=name,
        code=code,
        bonus_amount=settings.referral_bonus_promoter,
        user_id=user_id,
    )
    link = make_promoter_link(settings.bot_username, code)
    await message.answer(
        f"✅ Промоутер «{promoter.name}» создан.\n"
        f"Бонус за приглашённого: <b>{int(promoter.bonus_amount)} ₸</b>\n"
        f"{'Привязан к аккаунту.' if user_id else 'Без аккаунта — выплата вручную.'}\n\n"
        f"Промо-ссылка:\n<code>{link}</code>"
    )


@router.message(Command("promoters"))
async def cmd_promoters(message: Message, session: AsyncSession) -> None:
    promoters = await PromoterRepo(session).list_all()
    if not promoters:
        await message.answer("Промоутеров пока нет. Создайте — /promoter_new.")
        return
    refs = ReferralRepo(session)
    lines = []
    for p in promoters:
        total, granted = await refs.count_for_promoter(p.id)
        link = make_promoter_link(settings.bot_username, p.code)
        lines.append(
            f"#{p.id} <b>{p.name}</b> · бонус {int(p.bonus_amount)} ₸\n"
            f"привёл: {total} · оплатили: {granted} · заработал: {int(p.total_earned)} ₸\n"
            f"<code>{link}</code>"
        )
    await message.answer("👥 <b>Промоутеры</b>\n\n" + "\n\n".join(lines))


# ──────────────────── Отслеживание приглашений ──────────────────────────────
@router.message(Command("referrals"))
async def cmd_referrals(message: Message, session: AsyncSession) -> None:
    refs = ReferralRepo(session)
    users = UserRepo(session)
    top = await refs.top_referrers(limit=20)
    if not top:
        await message.answer("Приглашений от пользователей ещё нет.")
        return
    lines = []
    for referrer_id, total, granted in top:
        owner = await users.get_by_id(referrer_id)
        if owner is not None:
            who = f"tg={owner.tg_id}" + (f" @{owner.tg_username}" if owner.tg_username else "")
        else:
            who = f"id={referrer_id}"
        lines.append(f"{who}: привёл {total}, оплатили {granted}")
    await message.answer("👥 <b>Кто сколько привёл</b>\n\n" + "\n".join(lines))


@router.message(Command("invited_by"))
async def cmd_invited_by(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /invited_by <tg_id>")
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        await message.answer("Неверный формат.")
        return
    users = UserRepo(session)
    owner = await users.get_by_tg_id(tg_id)
    if owner is None:
        await message.answer("Пользователь не найден.")
        return
    items = await ReferralRepo(session).list_for_referrer(owner.id)
    if not items:
        await message.answer("Этот пользователь ещё никого не привёл.")
        return
    lines = []
    for ref in items:
        referee = await users.get_by_id(ref.referee_id)
        tg = referee.tg_id if referee is not None else "?"
        status = "✅ оплатил" if ref.status == ReferralStatus.GRANTED else "⏳ ждём оплаты"
        lines.append(f"tg={tg} · {status}")
    await message.answer(
        f"👤 Привёл tg={tg_id} (всего {len(items)}):\n\n" + "\n".join(lines)
    )
