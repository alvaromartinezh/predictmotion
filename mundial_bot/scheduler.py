"""Configura APScheduler: polling en vivo + ventanas horarias de resúmenes."""

from __future__ import annotations
from typing import Callable

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import config


def build_scheduler(
    on_live_tick: Callable,
    on_morning_window: Callable,
    on_evening_window: Callable,
) -> BlockingScheduler:
    tz = pytz.timezone(config.TIMEZONE)
    sched = BlockingScheduler(timezone=tz)

    # Polling de partidos en vivo cada N segundos
    sched.add_job(
        on_live_tick,
        IntervalTrigger(seconds=config.POLL_INTERVAL),
        id="live_tick",
        max_instances=1,
        coalesce=True,
    )

    # Ventana matutina: cada 20 min dentro del rango configurado
    sched.add_job(
        on_morning_window,
        CronTrigger(
            hour=f"{config.MORNING_HOUR_START}-{config.MORNING_HOUR_END - 1}",
            minute="*/20",
            timezone=tz,
        ),
        id="morning_window",
        max_instances=1,
        coalesce=True,
    )

    # Ventana vespertina: cada 20 min dentro del rango configurado
    sched.add_job(
        on_evening_window,
        CronTrigger(
            hour=f"{config.EVENING_HOUR_START}-{config.EVENING_HOUR_END - 1}",
            minute="*/20",
            timezone=tz,
        ),
        id="evening_window",
        max_instances=1,
        coalesce=True,
    )

    return sched
