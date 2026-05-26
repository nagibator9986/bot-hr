"""FSM-состояния работодателя.

Два блока:
  • регистрация компании (один раз) — company, bin, contact_person, phone;
  • создание вакансии — city … photo, confirm.
Возвращающийся работодатель начинает сразу с блока вакансии.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EmployerForm(StatesGroup):
    # регистрация компании
    company = State()
    contact_person = State()
    phone = State()
    # вакансия
    city = State()
    position = State()
    position_custom = State()
    requirements = State()
    conditions = State()
    salary_min = State()
    salary_max = State()
    schedule = State()
    address = State()
    photo = State()
    confirm = State()


class RejectReason(StatesGroup):
    """Админ вводит причину отклонения работодателя."""

    waiting = State()
