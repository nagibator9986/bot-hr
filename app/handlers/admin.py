"""Команды администратора: вручную подтвердить платёж, обработать вывод (MVP)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import Tariff, VacancyStatus, VerificationStatus, WithdrawalStatus
from app.db.models.employer import Employer
from app.keyboards.callbacks import EmployerModerationCB
from app.repositories.candidate import CandidateRepo
from app.repositories.match import MatchRepo
from app.repositories.referral import WithdrawalRepo
from app.repositories.subscription import PaymentRepo, SubscriptionRepo
from app.repositories.user import UserRepo
from app.repositories.vacancy import EmployerRepo, VacancyRepo
from app.services.conversation import ConversationService
from app.services.payments import PaymentService
from app.services.referrals import ReferralService
from app.services.verification import VerificationService
from app.states.employer import RejectReason
from app.utils.validators import clean_text

router = Router(name="admin")
_ADMIN_IDS = set(settings.admin_ids)
router.message.filter(F.from_user.id.in_(_ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(_ADMIN_IDS))


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer(
        "<b>Админ-команды:</b>\n"
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
        "/paid <code>&lt;id&gt;</code> — пометить заявку выплаченной"
    )


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
