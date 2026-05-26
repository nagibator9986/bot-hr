"""Отправка сообщений по доменным событиям + авто-уведомления о совпадениях.

Сервис не знает про FSM/Router'ы — только что и куда написать.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.db.models.candidate import Candidate
from app.db.models.employer import Employer
from app.db.models.user import User
from app.db.models.vacancy import Vacancy
from app.locales import RU
from app.services.matching import MatchingService
from app.services.profile import fmt_salary_range, position_label

log = get_logger("notifications")

# Сколько противоположных сторон уведомлять при появлении новой анкеты/вакансии.
_NOTIFY_LIMIT = 10


class NotificationService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, tg_id: int, text: str, **kwargs: object) -> bool:
        try:
            await self.bot.send_message(chat_id=tg_id, text=text, **kwargs)  # type: ignore[arg-type]
            return True
        except TelegramAPIError as e:
            log.warning("send_failed", tg_id=tg_id, error=str(e))
            return False

    async def notify_admins(self, admin_ids: list[int], text: str) -> None:
        for admin_id in admin_ids:
            await self.send(admin_id, text)


async def _employer_tg_id(session: AsyncSession, vacancy_id: int) -> int | None:
    stmt = (
        select(User.tg_id)
        .join(Employer, Employer.user_id == User.id)
        .join(Vacancy, Vacancy.employer_id == Employer.id)
        .where(Vacancy.id == vacancy_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _candidate_tg_id(session: AsyncSession, candidate: Candidate) -> int | None:
    stmt = select(User.tg_id).where(User.id == candidate.user_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def announce_new_candidate(
    bot: Bot, session: AsyncSession, candidate: Candidate
) -> int:
    """Новая анкета → создаём матчи и уведомляем работодателей. Возвращает кол-во матчей."""
    matching = MatchingService(session)
    notifier = NotificationService(bot)
    scored = await matching.find_vacancies_for_candidate(candidate)

    notified = 0
    for vacancy, score in scored:
        await matching.persist_match(
            candidate_id=candidate.id, vacancy_id=vacancy.id, score=score
        )
        if notified >= _NOTIFY_LIMIT:
            continue
        tg_id = await _employer_tg_id(session, vacancy.id)
        if tg_id is None:
            continue
        text = RU["new_match_notify_employer"].format(
            position=position_label(candidate.position_normalized, candidate.desired_position)
        )
        if await notifier.send(tg_id, text):
            notified += 1
    return len(scored)


async def announce_new_vacancy(
    bot: Bot, session: AsyncSession, vacancy: Vacancy
) -> int:
    """Новая вакансия → создаём матчи и уведомляем кандидатов. Возвращает кол-во матчей."""
    matching = MatchingService(session)
    notifier = NotificationService(bot)
    scored = await matching.find_candidates_for_vacancy(vacancy.id)

    notified = 0
    for candidate, score in scored:
        await matching.persist_match(
            candidate_id=candidate.id, vacancy_id=vacancy.id, score=score
        )
        if notified >= _NOTIFY_LIMIT:
            continue
        tg_id = await _candidate_tg_id(session, candidate)
        if tg_id is None:
            continue
        text = RU["new_match_notify_candidate"].format(
            position=position_label(vacancy.position_normalized, vacancy.position),
            salary=fmt_salary_range(vacancy),
        )
        if await notifier.send(tg_id, text):
            notified += 1
    return len(scored)
