"""FSM-состояния заявки на вывод реф-бонуса."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class WithdrawalForm(StatesGroup):
    kaspi_phone = State()
    confirm = State()
