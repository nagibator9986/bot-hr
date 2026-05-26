"""Reply-клавиатуры: главное меню (role-aware), запрос контакта, отмена."""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.core.constants import Role
from app.locales import RU

REMOVE = ReplyKeyboardRemove()


def main_menu(role: Role | None) -> ReplyKeyboardMarkup:
    """Постоянное меню под полем ввода. Зависит от роли пользователя."""
    builder = ReplyKeyboardBuilder()

    if role == Role.CANDIDATE:
        builder.button(text=RU["menu_search_vacancies"])
        builder.button(text=RU["menu_my_profile"])
        builder.button(text=RU["menu_edit_profile"])
        builder.button(text=RU["menu_matches"])
        builder.button(text=RU["menu_switch_role"])
        builder.button(text=RU["menu_invite"])
        builder.button(text=RU["menu_subscription"])
        builder.button(text=RU["menu_help"])
        builder.adjust(1, 2, 2, 2, 1)
    elif role == Role.EMPLOYER:
        builder.button(text=RU["menu_search_candidates"])
        builder.button(text=RU["menu_my_vacancies"])
        builder.button(text=RU["menu_new_vacancy"])
        builder.button(text=RU["menu_matches"])
        builder.button(text=RU["menu_switch_role"])
        builder.button(text=RU["menu_invite"])
        builder.button(text=RU["menu_subscription"])
        builder.button(text=RU["menu_help"])
        builder.adjust(1, 2, 2, 2, 1)
    else:
        builder.button(text=RU["btn_seek_job"])
        builder.button(text=RU["btn_seek_employee"])
        builder.adjust(1)

    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Одна кнопка «Отменить» — показывается во время заполнения форм."""
    builder = ReplyKeyboardBuilder()
    builder.button(text=RU["btn_cancel"])
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def request_contact_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка «Отправить мой номер» (Telegram отдаёт контакт без ручного ввода)."""
    builder = ReplyKeyboardBuilder()
    builder.button(text=RU["btn_share_contact"], request_contact=True)
    builder.button(text=RU["btn_cancel"])
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
