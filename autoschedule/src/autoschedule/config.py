"""Configuration management for CalDAV Scheduler."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def _get_secret(env_var: str) -> Optional[str]:
    """Get value from environment variable or Docker secret file.

    Supports both direct env vars and _FILE suffix pattern for Docker secrets.

    Args:
        env_var: Environment variable name (e.g., "CALDAV_PASSWORD")

    Returns:
        Value from env var or file, or None if not found
    """
    # First try direct environment variable
    value = os.getenv(env_var)
    if value:
        return value

    # Then try _FILE suffix (Docker secrets pattern)
    file_path = os.getenv(f"{env_var}_FILE")
    if file_path:
        file_path_obj = Path(file_path)
        if file_path_obj.exists():
            return file_path_obj.read_text().strip()

    return None


@dataclass
class Config:
    """Application configuration."""

    # Required fields (no defaults)
    caldav_url: str
    caldav_username: str
    caldav_password: str
    todo_dir_path: Path
    ai_api_key: str

    # Optional fields (with defaults)
    default_calendar: Optional[str] = None
    work_start_hour: int = 9
    work_end_hour: int = 17
    min_task_duration_minutes: int = 15
    max_task_duration_minutes: int = 240
    timezone: str = "UTC"
    default_reminder_minutes: Optional[int] = None  # Default reminder for tasks without explicit reminder
    default_duration_minutes: Optional[int] = None  # Default duration for tasks without explicit duration
    default_priority: str = "medium"  # Default priority for tasks without explicit priority
    default_time_preference: str = "anytime"  # Default time preference for tasks without explicit time
    claude_model: str = "claude-haiku-4-5"  # Claude model to use for scheduling

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Config":
        """Load configuration from environment variables.

        Args:
            env_file: Optional path to .env file. If None, looks for .env in current directory.

        Returns:
            Config instance

        Raises:
            ValueError: If required configuration is missing
        """
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

        # Required fields
        required_fields = {
            "CALDAV_URL": "CalDAV server URL",
            "CALDAV_USERNAME": "CalDAV username",
            "CALDAV_PASSWORD": "CalDAV password",
            "TODO_DIR_PATH": "Path to todo directory",
            "AI_API": "AI API key",
        }

        missing = []
        for env_var, description in required_fields.items():
            if not _get_secret(env_var):
                missing.append(f"{env_var} ({description})")

        if missing:
            raise ValueError(
                f"Missing required environment variables:\n" + "\n".join(f"  - {m}" for m in missing)
            )

        # Parse default reminder minutes (optional)
        default_reminder = _get_secret("DEFAULT_REMINDER_MINUTES")
        default_reminder_minutes = int(default_reminder) if default_reminder else None

        # Parse default duration minutes (optional)
        default_duration = _get_secret("DEFAULT_DURATION_MINUTES")
        default_duration_minutes = int(default_duration) if default_duration else None

        return cls(
            caldav_url=_get_secret("CALDAV_URL"),
            caldav_username=_get_secret("CALDAV_USERNAME"),
            caldav_password=_get_secret("CALDAV_PASSWORD"),
            default_calendar=_get_secret("DEFAULT_CALENDAR"),
            todo_dir_path=Path(_get_secret("TODO_DIR_PATH")),
            ai_api_key=_get_secret("AI_API"),
            work_start_hour=int(_get_secret("WORK_START_HOUR") or "9"),
            work_end_hour=int(_get_secret("WORK_END_HOUR") or "17"),
            min_task_duration_minutes=int(_get_secret("MIN_TASK_DURATION_MINUTES") or "15"),
            max_task_duration_minutes=int(_get_secret("MAX_TASK_DURATION_MINUTES") or "240"),
            timezone=_get_secret("TIMEZONE") or "UTC",
            default_reminder_minutes=default_reminder_minutes,
            default_duration_minutes=default_duration_minutes,
            default_priority=_get_secret("DEFAULT_PRIORITY") or "medium",
            default_time_preference=_get_secret("DEFAULT_TIME_PREFERENCE") or "anytime",
            claude_model=_get_secret("CLAUDE_MODEL") or "claude-haiku-4-5",
        )
