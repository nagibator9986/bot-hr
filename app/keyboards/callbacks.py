"""Type-safe callback_data через aiogram CallbackData."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class RoleCB(CallbackData, prefix="role"):
    value: str  # "candidate" | "employer"


class MenuCB(CallbackData, prefix="menu"):
    action: str


class ScheduleCB(CallbackData, prefix="sch"):
    value: str  # Schedule.value


class PositionCB(CallbackData, prefix="pos"):
    value: str  # канонич. должность HoReCa или "custom"


class SkipCB(CallbackData, prefix="skip"):
    step: str  # имя шага, который пропускаем


class ConfirmCB(CallbackData, prefix="cfm"):
    target: str   # "candidate" | "vacancy"
    action: str   # "save" | "edit"


class EditFieldCB(CallbackData, prefix="edit"):
    field: str  # имя редактируемого поля


class AboutPolishCB(CallbackData, prefix="abpol"):
    choice: str  # "ai" — взять версию AI | "mine" — оставить свой текст


class SwipeCB(CallbackData, prefix="sw"):
    match_id: int
    reaction: str  # "like" | "skip"


class BrowseCB(CallbackData, prefix="brw"):
    action: str  # "next" | "stop"


class InterviewCB(CallbackData, prefix="iv"):
    match_id: int


class InterviewSlotCB(CallbackData, prefix="ivslot"):
    interview_id: int
    slot_index: int


class VacancyActionCB(CallbackData, prefix="vac"):
    vacancy_id: int
    action: str  # "close" | "reopen"


class TariffCB(CallbackData, prefix="tariff"):
    value: str  # Tariff.value


class PaymentCB(CallbackData, prefix="pay"):
    tariff: str
    action: str  # "claim" (я оплатил Kaspi) | "promo" (ввести промокод)


class PaymentClaimCB(CallbackData, prefix="paycl"):
    claim_id: int
    action: str  # "approve" | "reject"


class ReferralCB(CallbackData, prefix="ref"):
    action: str  # "share" | "balance" | "withdraw"


class EmployerModerationCB(CallbackData, prefix="mod"):
    employer_id: int
    action: str  # "approve" | "reject"


class AdminMenuCB(CallbackData, prefix="adm"):
    action: str  # "pending" | "candidates" | "vac_active" | "vac_closed" | "apps" | "subs" | "payouts" | "help"
