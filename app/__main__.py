"""Точка входа: python -m app."""

from __future__ import annotations

import asyncio
import signal

from redis.asyncio import Redis

from app.bot import build_bot, build_dispatcher, setup_bot_commands
from app.config import settings
from app.core.logger import configure_logging, get_logger
from app.db.session import dispose_engine, engine
from app.services.gemini import gemini
from app.services.scheduler import (
    build_scheduler,
    register_periodic_jobs,
    shutdown_scheduler,
)


async def _run() -> None:
    configure_logging()
    log = get_logger("bootstrap")
    log.info(
        "starting",
        env=settings.environment,
        bot=settings.bot_username,
        ai_enabled=settings.ai_available,
        ai_model=settings.gemini_model if settings.ai_available else None,
    )

    redis = Redis.from_url(str(settings.redis_url), decode_responses=True)
    bot = build_bot()
    dp = build_dispatcher(redis)
    scheduler = build_scheduler(bot)
    register_periodic_jobs(scheduler)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    scheduler.start()
    log.info("scheduler started")

    await setup_bot_commands(bot)

    polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    )

    try:
        await stop_event.wait()
    finally:
        log.info("shutdown initiated")
        polling_task.cancel()
        await asyncio.gather(polling_task, return_exceptions=True)
        await shutdown_scheduler(scheduler)
        await gemini.aclose()
        await bot.session.close()
        await redis.aclose()
        await dispose_engine(engine)
        log.info("shutdown complete")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
