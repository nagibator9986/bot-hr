"""FSM-состояния согласования собеседования.

Работодатель вводит слоты текстом; кандидат выбирает слот кнопкой (без FSM).
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class InterviewScheduling(StatesGroup):
    employer_proposes_slots = State()
