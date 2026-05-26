"""APScheduler: напоминания о собеседовании (ТЗ §6.1), окончание подписки (§10.9).

Хранилище job'ов — SQLAlchemyJobStore (PostgreSQL, sync driver), чтобы job'ы
переживали рестарт. Bot хранится модульным singleton'ом — APScheduler не может
сериализовать `Bot` в args, поэтому передавать его через args нельзя.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.constants import INTERVIEW_REMINDERS_HOURS, InterviewStatus
from app.core.logger import get_logger
from app.db.models.candidate import Candidate
from app.db.models.employer import Employer
from app.db.models.interview import Interview
from app.db.models.match import Match
from app.db.models.vacancy import Vacancy
from app.db.session import SessionFactory
from app.services.notifications import NotificationService
from app.utils.time import format_dt, utcnow

log = get_logger("scheduler")

# Module-level singletons, выставляются build_scheduler(). Job-функции и хендлеры
# читают их, т.к. APScheduler не сериализует Bot/Scheduler в args job'ов.
_bot: Bot | None = None
_scheduler: AsyncIOScheduler | None = None


def _job_store_url() -> str:
    """sync psycopg2 URL для APScheduler (он синхронный)."""
    return settings.sync_db_url


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    global _bot, _scheduler
    _bot = bot
    _scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=_job_store_url())},
        timezone=settings.timezone,
    )
    return _scheduler


async def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    scheduler.shutdown(wait=False)


# ── Job functions ────────────────────────────────────────────────────────────
async def send_interview_reminder(interview_id: int, hours_before: int) -> None:
    """Job напоминания. Идемпотентен по InterviewStatus."""
    if _bot is None:
        log.error("reminder_no_bot", interview_id=interview_id)
        return

    notifier = NotificationService(_bot)

    async with SessionFactory() as session:
        stmt = (
            select(Interview)
            .where(Interview.id == interview_id)
            .options(
                selectinload(Interview.match)
                .selectinload(Match.candidate)
                .selectinload(Candidate.user),
                selectinload(Interview.match)
                .selectinload(Match.vacancy)
                .selectinload(Vacancy.employer)
                .selectinload(Employer.user),
            )
        )
        interview = (await session.execute(stmt)).scalar_one_or_none()
        if interview is None:
            log.warning("reminder_skipped_not_found", interview_id=interview_id)
            return
        if interview.status in (InterviewStatus.CANCELLED, InterviewStatus.COMPLETED):
            return

        target_status = (
            InterviewStatus.REMINDED_24H
            if hours_before >= 24
            else InterviewStatus.REMINDED_2H
        )
        if interview.status == target_status:
            return  # уже отправляли
        if interview.scheduled_at is None:
            log.warning("reminder_skipped_missing_time", interview_id=interview_id)
            return

        text = (
            f"⏰ Через {hours_before} ч. собеседование.\n"
            f"📍 {interview.address}\n"
            f"🕐 {format_dt(interview.scheduled_at)}"
        )

        candidate_user = interview.match.candidate.user
        employer_user = interview.match.vacancy.employer.user
        await notifier.send(candidate_user.tg_id, text)
        await notifier.send(employer_user.tg_id, text)

        interview.status = target_status
        await session.commit()


def schedule_interview_reminders(*, interview_id: int, scheduled_at: datetime) -> None:
    """Ставит job'ы напоминаний (за 24 ч и за 2 ч) для назначенного собеседования.

    Использует модульный планировщник — хендлеру не нужно его прокидывать.
    """
    if _scheduler is None:
        log.error("schedule_reminders_no_scheduler", interview_id=interview_id)
        return
    now = utcnow()
    for hours in INTERVIEW_REMINDERS_HOURS:
        run_at = scheduled_at - timedelta(hours=hours)
        if run_at <= now:
            continue
        _scheduler.add_job(
            send_interview_reminder,
            "date",
            run_date=run_at,
            args=[interview_id, hours],
            id=f"interview:{interview_id}:reminder:{hours}h",
            replace_existing=True,
        )


# ── Подписки ────────────────────────────────────────────────────────────────
async def check_subscription_expiries() -> None:
    """Уведомления об окончании подписки (ТЗ §10.9). MVP — каркас, шлёт всем
    подпискам, которым осталось ≤ 3 дней или ровно 0.
    """
    if _bot is None:
        return
    # TODO: полная реализация в фазе 4. Сейчас — no-op заглушка с логом.
    log.debug("subscription_expiry_check_tick")


def register_periodic_jobs(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        check_subscription_expiries,
        "interval",
        hours=1,
        id="subscription:expiry_check",
        replace_existing=True,
    )
