"""Фабрики inline-клавиатур. Чистые функции — никаких side-effects."""

from __future__ import annotations

from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.constants import HORECA_POSITIONS, Schedule, Tariff
from app.keyboards.callbacks import (
    AboutPolishCB,
    AdminMenuCB,
    BrowseCB,
    ConfirmCB,
    EditFieldCB,
    EmployerModerationCB,
    InterviewCB,
    InterviewSlotCB,
    PaymentCB,
    PaymentClaimCB,
    PositionCB,
    ReferralCB,
    RoleCB,
    ScheduleCB,
    SkipCB,
    SwipeCB,
    TariffCB,
    VacancyActionCB,
)
from app.locales import RU
from app.utils.time import format_dt


def role_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=RU["btn_seek_job"], callback_data=RoleCB(value="candidate"))
    builder.button(text=RU["btn_seek_employee"], callback_data=RoleCB(value="employer"))
    builder.adjust(1)
    return builder.as_markup()


def schedule_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = [
        (RU["schedule_shift"], Schedule.SHIFT),
        (RU["schedule_full_time"], Schedule.FULL_TIME),
        (RU["schedule_part_time"], Schedule.PART_TIME),
        (RU["schedule_flexible"], Schedule.FLEXIBLE),
    ]
    for label, value in items:
        builder.button(text=label, callback_data=ScheduleCB(value=value.value))
    builder.adjust(2)
    return builder.as_markup()


def position_keyboard() -> InlineKeyboardMarkup:
    """Пикер должностей HoReCa + «Другое» для свободного ввода."""
    builder = InlineKeyboardBuilder()
    for canonical, label in HORECA_POSITIONS.items():
        builder.button(text=label, callback_data=PositionCB(value=canonical))
    builder.button(text="✏️ Другое", callback_data=PositionCB(value="custom"))
    builder.adjust(2)
    return builder.as_markup()


def skip_keyboard(step: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=RU["btn_skip"], callback_data=SkipCB(step=step))
    return builder.as_markup()


def about_polish_keyboard() -> InlineKeyboardMarkup:
    """Выбор между AI-версией текста «о себе» и собственной."""
    builder = InlineKeyboardBuilder()
    builder.button(text=RU["btn_about_use_ai"], callback_data=AboutPolishCB(choice="ai"))
    builder.button(text=RU["btn_about_keep_mine"], callback_data=AboutPolishCB(choice="mine"))
    builder.adjust(1)
    return builder.as_markup()


def confirm_keyboard(target: str) -> InlineKeyboardMarkup:
    """target: 'candidate' | 'vacancy'."""
    builder = InlineKeyboardBuilder()
    builder.button(text=RU["btn_confirm"], callback_data=ConfirmCB(target=target, action="save"))
    builder.button(text=RU["btn_edit"], callback_data=ConfirmCB(target=target, action="edit"))
    builder.adjust(1)
    return builder.as_markup()


def edit_fields_keyboard() -> InlineKeyboardMarkup:
    """Меню выбора поля для редактирования анкеты кандидата."""
    builder = InlineKeyboardBuilder()
    fields = [
        ("Имя", "name"),
        ("Возраст", "age"),
        ("Город", "city"),
        ("Район / адрес", "preferred_area"),
        ("Должность", "position"),
        ("Опыт", "experience"),
        ("График", "schedule"),
        ("Зарплата", "salary"),
        ("О себе", "about"),
        ("Фото", "photo"),
        ("Контакт", "contact"),
    ]
    for label, field in fields:
        builder.button(text=label, callback_data=EditFieldCB(field=field))
    builder.adjust(2)
    return builder.as_markup()


def swipe_keyboard(match_id: int) -> InlineKeyboardMarkup:
    """Кнопки под карточкой в свайп-просмотре."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=RU["btn_like"], callback_data=SwipeCB(match_id=match_id, reaction="like")
    )
    builder.button(
        text=RU["btn_skip_card"], callback_data=SwipeCB(match_id=match_id, reaction="skip")
    )
    builder.button(text=RU["btn_stop_browse"], callback_data=BrowseCB(action="stop"))
    builder.adjust(2, 1)
    return builder.as_markup()


def tariff_keyboard(for_role: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if for_role == "candidate":
        builder.button(
            text=RU["tariff_candidate"], callback_data=TariffCB(value=Tariff.CANDIDATE.value)
        )
    else:
        builder.button(
            text=RU["tariff_employer_basic"],
            callback_data=TariffCB(value=Tariff.EMPLOYER_BASIC.value),
        )
        builder.button(
            text=RU["tariff_employer_extended"],
            callback_data=TariffCB(value=Tariff.EMPLOYER_EXTENDED.value),
        )
    builder.adjust(1)
    return builder.as_markup()


def pay_now_keyboard(tariff: Tariff, *, kaspi_url: str | None) -> InlineKeyboardMarkup:
    """Карточка тарифа: оплата через Kaspi → «Я оплатил» → или промокод."""
    builder = InlineKeyboardBuilder()
    if kaspi_url:
        builder.button(text=RU["pay_kaspi"], url=kaspi_url)
    builder.button(
        text=RU["pay_done"], callback_data=PaymentCB(tariff=tariff.value, action="claim")
    )
    builder.button(
        text=RU["pay_promo"], callback_data=PaymentCB(tariff=tariff.value, action="promo")
    )
    builder.adjust(1)
    return builder.as_markup()


def payment_claim_keyboard(claim_id: int) -> InlineKeyboardMarkup:
    """Кнопки админа под заявкой «Я оплатил»."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=RU["claim_approve"],
        callback_data=PaymentClaimCB(claim_id=claim_id, action="approve"),
    )
    builder.button(
        text=RU["claim_reject"],
        callback_data=PaymentClaimCB(claim_id=claim_id, action="reject"),
    )
    builder.adjust(2)
    return builder.as_markup()


def referral_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=RU["btn_balance"], callback_data=ReferralCB(action="balance"))
    builder.button(text=RU["btn_withdraw"], callback_data=ReferralCB(action="withdraw"))
    builder.adjust(2)
    return builder.as_markup()


def propose_interview_keyboard(match_id: int) -> InlineKeyboardMarkup:
    """Кнопка под сообщением о взаимном матче — работодатель предлагает время."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=RU["btn_propose_interview"],
        callback_data=InterviewCB(match_id=match_id),
    )
    return builder.as_markup()


def interview_slots_keyboard(
    interview_id: int, slots: list[datetime]
) -> InlineKeyboardMarkup:
    """Кнопки выбора слота собеседования для кандидата."""
    builder = InlineKeyboardBuilder()
    for idx, slot in enumerate(slots):
        builder.button(
            text=f"🕐 {format_dt(slot)}",
            callback_data=InterviewSlotCB(interview_id=interview_id, slot_index=idx),
        )
    builder.adjust(1)
    return builder.as_markup()


def vacancy_actions_keyboard(vacancy_id: int, *, is_closed: bool) -> InlineKeyboardMarkup:
    """Кнопка управления вакансией: закрыть либо открыть снова."""
    builder = InlineKeyboardBuilder()
    if is_closed:
        builder.button(
            text=RU["btn_reopen_vacancy"],
            callback_data=VacancyActionCB(vacancy_id=vacancy_id, action="reopen"),
        )
    else:
        builder.button(
            text=RU["btn_close_vacancy"],
            callback_data=VacancyActionCB(vacancy_id=vacancy_id, action="close"),
        )
    return builder.as_markup()


def employer_moderation_keyboard(employer_id: int) -> InlineKeyboardMarkup:
    """Кнопки одобрения/отклонения работодателя для админа."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=RU["admin_approve"],
        callback_data=EmployerModerationCB(employer_id=employer_id, action="approve"),
    )
    builder.button(
        text=RU["admin_reject"],
        callback_data=EmployerModerationCB(employer_id=employer_id, action="reject"),
    )
    builder.adjust(2)
    return builder.as_markup()


def url_button(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню админа: одна кнопка — одно действие."""
    builder = InlineKeyboardBuilder()
    items = [
        ("⏳ На модерации", "pending"),
        ("🟢 Активные вакансии", "vac_active"),
        ("⚪️ Закрытые вакансии", "vac_closed"),
        ("🧑‍🍳 Соискатели", "candidates"),
        ("💚 Отклики и матчи", "apps"),
        ("💳 Подписки и оплаты", "subs"),
        ("💸 Заявки на вывод", "payouts"),
        ("❓ Подсказка по командам", "help"),
    ]
    for label, action in items:
        builder.button(text=label, callback_data=AdminMenuCB(action=action))
    builder.adjust(1)
    return builder.as_markup()
