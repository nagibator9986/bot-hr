"""Верификация работодателя (HR-проверка).

Уровни проверки:
  1. БИН компании (12 цифр) — формат проверяется при вводе.
  2. Телефон подтверждён через Telegram-контакт (номер принадлежит аккаунту).
  3. Модерация админом — если в настройках заданы ADMIN_IDS.

Если админы не настроены — работодатель авто-одобряется на основании п.1-2.
"""

from __future__ import annotations

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.constants import VacancyStatus, VerificationStatus
from app.core.logger import get_logger
from app.db.models.employer import Employer
from app.db.models.user import User
from app.db.models.vacancy import Vacancy
from app.locales import RU
from app.services.notifications import NotificationService, announce_new_vacancy
from app.services.profile import position_label
from app.utils.time import utcnow

log = get_logger("verification")


class VerificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _employer_tg_id(self, employer: Employer) -> int | None:
        stmt = select(User.tg_id).where(User.id == employer.user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _pending_vacancies(self, employer_id: int) -> list[Vacancy]:
        stmt = select(Vacancy).where(
            Vacancy.employer_id == employer_id,
            Vacancy.status == VacancyStatus.IN_PROGRESS,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def route_after_registration(
        self, bot: Bot, employer: Employer, vacancy: Vacancy
    ) -> bool:
        """Решает судьбу новой компании. Возвращает True, если одобрена сразу."""
        if settings.admin_ids:
            employer.verification_status = VerificationStatus.PENDING
            await self.session.flush()
            await self._notify_admins(bot, employer, vacancy)
            return False
        # Админов нет — авто-одобрение на основании БИН + подтверждённого телефона.
        await self._approve_internal(bot, employer, announce=True)
        return True

    async def _notify_admins(self, bot: Bot, employer: Employer, vacancy: Vacancy) -> None:
        from app.keyboards.inline import employer_moderation_keyboard

        notifier = NotificationService(bot)
        text = RU["admin_new_employer"].format(
            company=employer.company_name,
            bin=employer.bin or "—",
            city=employer.city,
            contact_person=employer.contact_person,
            phone=employer.phone,
            phone_badge="✅" if employer.phone_verified else "⚠️ не подтверждён",
            position=position_label(vacancy.position_normalized, vacancy.position),
        )
        kb = employer_moderation_keyboard(employer.id)
        delivered = 0
        for admin_id in settings.admin_ids:
            if await notifier.send(admin_id, text, reply_markup=kb):
                delivered += 1
        if delivered == 0:
            # Ни один админ не получил заявку — почти всегда потому, что админы
            # не нажимали Start у бота (Telegram не даёт боту писать первым).
            # Заявка всё равно лежит в БД и видна по /pending.
            log.error(
                "admin_notify_failed",
                employer_id=employer.id,
                admins=len(settings.admin_ids),
                hint="admins must press Start in the bot; queue still visible via /pending",
            )

    async def approve(self, bot: Bot, employer: Employer) -> None:
        await self._approve_internal(bot, employer, announce=True)
        tg_id = await self._employer_tg_id(employer)
        if tg_id is not None:
            await NotificationService(bot).send(
                tg_id, RU["employer_approved_notify"].format(company=employer.company_name)
            )

    async def _approve_internal(
        self, bot: Bot, employer: Employer, *, announce: bool
    ) -> None:
        employer.verification_status = VerificationStatus.APPROVED
        employer.verified_at = utcnow()
        await self.session.flush()
        # Публикуем все «скрытые» вакансии этой компании.
        for vacancy in await self._pending_vacancies(employer.id):
            vacancy.status = VacancyStatus.ACTIVE
            await self.session.flush()
            if announce:
                await announce_new_vacancy(bot, self.session, vacancy)

    async def reject(self, bot: Bot, employer: Employer, reason: str) -> None:
        employer.verification_status = VerificationStatus.REJECTED
        employer.verification_note = reason
        await self.session.flush()
        tg_id = await self._employer_tg_id(employer)
        if tg_id is not None:
            await NotificationService(bot).send(
                tg_id,
                RU["employer_rejected_notify"].format(
                    company=employer.company_name, reason=reason
                ),
            )
