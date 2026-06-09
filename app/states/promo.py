"""FSM-состояния ввода промокода."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class PromoForm(StatesGroup):
    waiting_code = State()
