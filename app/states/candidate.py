"""FSM-состояния анкеты соискателя (ТЗ §2.1 + улучшения: район, фото, о себе)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CandidateForm(StatesGroup):
    name = State()
    age = State()
    city = State()
    preferred_area = State()
    desired_position = State()
    desired_position_custom = State()  # ввод должности текстом, если «Другое»
    experience = State()
    previous_jobs = State()
    schedule = State()
    salary = State()
    about = State()
    photo = State()
    contact = State()
    confirm = State()


class CandidateEdit(StatesGroup):
    """Точечное редактирование одного поля готовой анкеты."""

    choosing_field = State()
    name = State()
    age = State()
    city = State()
    preferred_area = State()
    position = State()
    experience = State()
    schedule = State()
    salary = State()
    about = State()
    photo = State()
    contact = State()
