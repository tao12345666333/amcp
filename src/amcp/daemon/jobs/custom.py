"""Custom job helpers — support user-defined cron jobs."""

from __future__ import annotations

from ..scheduler import CronJob


def create_custom_job(
    name: str,
    schedule: str,
    command: str,
    *,
    skill: str | None = None,
    notify: bool = True,
    timeout: int = 300,
    work_dir: str | None = None,
    tags: list[str] | None = None,
) -> CronJob:
    """Create a CronJob from user parameters.

    This is a convenience wrapper used by the CLI ``amcp cron add`` command.
    """
    from ..scheduler import _expand_schedule

    return CronJob(
        name=name,
        schedule=_expand_schedule(schedule),
        command=command,
        skill=skill,
        notify=notify,
        timeout=timeout,
        work_dir=work_dir,
        tags=tags or [],
    )
