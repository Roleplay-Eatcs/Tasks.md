"""Parse todo items from directory of markdown files."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from datetime import date, timedelta
from dateutil import parser as date_parser


@dataclass
class TodoItem:
    """Represents a todo item from a file."""

    title: str  # From filename (without .md)
    duration_minutes: int
    duration_range: Optional[tuple[int, int]] = None  # (min, max) for flexible duration
    priority: Optional[str] = None
    calendar: Optional[str] = None
    target_date: Optional[date] = None
    reminder_minutes: Optional[int] = None
    time_preference: str = "anytime"  # morning/afternoon/evening/anytime
    dependencies: List[str] = field(default_factory=list)  # List of task names this depends on
    link: Optional[str] = None  # URL for online meetings, resources, etc.
    raw_content: str = ""  # File content
    file_path: str = ""  # Full file path

    def __str__(self):
        cal_str = f" [cal: {self.calendar}]" if self.calendar else ""
        date_str = f" [date: {self.target_date}]" if self.target_date else ""
        reminder_str = f" [reminder: {self.reminder_minutes}m]" if self.reminder_minutes else ""
        time_str = f" [time: {self.time_preference}]"
        deps_str = f" [depends: {', '.join(self.dependencies)}]" if self.dependencies else ""
        link_str = f" [link: {self.link}]" if self.link else ""
        return f"{self.title} ({self.duration_minutes}m){cal_str}{date_str}{reminder_str}{time_str}{deps_str}{link_str}"


class DirectoryParser:
    """Parse todo items from directory of markdown files.

    Each .md file in the directory represents one task.
    The filename (without .md) becomes the task title.

    Supported formats:
    Structured:
        c: calendar-name
        r: 30m
        p: high
        t: morning
        d: Task name
        dur: 2h or 2-4h
        l: https://zoom.us/j/123456

    Natural language:
        morning, remind 30m, cal work, depends on Task name, duration 2h, link https://zoom.us/j/123456

    Mixed format is also supported.
    """

    STRUCTURED_PATTERNS = {
        'calendar': r'c:\s*([a-zA-Z0-9_-]+)',
        'reminder': r'r:\s*([\d\s,hm.]+)',
        'priority': r'p:\s*(high|medium|low)',
        'time': r't:\s*(morning|afternoon|evening|anytime)',
        'depends': r'd:\s*(.+)',
        'duration': r'dur:\s*(.+)',
        'link': r'l:\s*(https?://[^\s,]+)',
    }

    NATURAL_PATTERNS = {
        'calendar': r'cal\s+([a-zA-Z0-9_-]+)',
        'reminder': r'remind\s+([\d\s,hrandm]+)',
        'priority': r'\b(high|medium|low)(?:\s+priority)?\b',  # Priority keyword is optional
        'time': r'\b(morning|afternoon|evening|anytime)\b',
        'depends': r'depends\s+on\s+(.+?)(?:,|$|\n)',
        'duration': r'time\s+(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?[hm])\b',  # Requires "time" keyword to avoid confusion with "remind"
        'link': r'(?:link\s+)?(https?://[^\s,]+)',  # Match URLs with or without "link" keyword
    }

    def __init__(
        self,
        dir_path: Path,
        default_reminder_minutes: Optional[int] = None,
        default_duration_minutes: Optional[int] = None,
        default_priority: str = "medium",
        default_time_preference: str = "anytime",
    ):
        """Initialize parser with directory path and defaults.

        Args:
            dir_path: Path to directory containing .md task files
            default_reminder_minutes: Default reminder time in minutes for tasks without explicit reminder
            default_duration_minutes: Default duration in minutes for tasks without explicit duration
            default_priority: Default priority for tasks without explicit priority (high/medium/low)
            default_time_preference: Default time preference for tasks without explicit time (morning/afternoon/evening/anytime)
        """
        self.dir_path = dir_path
        self.default_reminder_minutes = default_reminder_minutes
        self.default_duration_minutes = default_duration_minutes
        self.default_priority = default_priority
        self.default_time_preference = default_time_preference

    def parse(self) -> List[TodoItem]:
        """Parse all .md files in directory.

        Returns:
            List of TodoItem objects

        Raises:
            FileNotFoundError: If directory doesn't exist
        """
        if not self.dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {self.dir_path}")

        if not self.dir_path.is_dir():
            raise ValueError(f"Path is not a directory: {self.dir_path}")

        todos = []
        for file_path in sorted(self.dir_path.glob("*.md")):
            todo = self._parse_file(file_path)
            if todo:
                todos.append(todo)

        return todos

    def _parse_file(self, file_path: Path) -> Optional[TodoItem]:
        """Parse single file into TodoItem.

        Args:
            file_path: Path to .md file

        Returns:
            TodoItem if successfully parsed, None if skipped
        """
        title = file_path.stem  # Filename without .md
        content = file_path.read_text(encoding='utf-8').strip()

        # Extract metadata
        calendar = self._extract_field(content, 'calendar')
        reminder_str = self._extract_field(content, 'reminder')
        priority = self._extract_field(content, 'priority')
        time_pref = self._extract_field(content, 'time')
        depends_str = self._extract_field(content, 'depends')
        duration_str = self._extract_field(content, 'duration')
        link = self._extract_field(content, 'link')

        # Parse duration (optional with default)
        duration_minutes = None
        duration_range = None

        if duration_str:
            duration_minutes, duration_range = self._parse_duration(duration_str)
            if not duration_minutes:
                print(f"Warning: {file_path.name} has invalid duration '{duration_str}', using default")

        # Use default duration if not specified or invalid
        if not duration_minutes:
            if self.default_duration_minutes:
                duration_minutes = self.default_duration_minutes
            else:
                print(f"Warning: {file_path.name} missing duration and no default configured, skipping")
                return None

        # Parse reminder
        reminder_minutes = self.parse_reminder_string(reminder_str) if reminder_str else None
        if reminder_minutes is None and self.default_reminder_minutes:
            reminder_minutes = self.default_reminder_minutes

        # Parse dependencies (can be comma-separated)
        dependencies = []
        if depends_str:
            # Split by comma and clean up each dependency name
            dependencies = [d.strip() for d in depends_str.split(',') if d.strip()]

        return TodoItem(
            title=title,
            duration_minutes=duration_minutes,
            duration_range=duration_range,
            priority=(priority or self.default_priority).lower(),
            calendar=calendar.lower() if calendar else None,
            time_preference=(time_pref or self.default_time_preference).lower(),
            dependencies=dependencies,
            reminder_minutes=reminder_minutes,
            link=link,
            raw_content=content,
            file_path=str(file_path),
        )

    def _extract_field(self, content: str, field: str) -> Optional[str]:
        """Extract field using both structured and natural patterns.

        Args:
            content: File content
            field: Field name (calendar, reminder, priority, time, depends, duration)

        Returns:
            Field value or None if not found
        """
        # Try structured format first (c:, r:, etc.)
        if field in self.STRUCTURED_PATTERNS:
            match = re.search(self.STRUCTURED_PATTERNS[field], content, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # Try natural language format
        if field in self.NATURAL_PATTERNS:
            match = re.search(self.NATURAL_PATTERNS[field], content, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _parse_duration(self, duration_str: str) -> tuple[Optional[int], Optional[tuple[int, int]]]:
        """Parse duration string into minutes and optional range.

        Args:
            duration_str: Duration string like "2h", "120m", "2-4h", "120-240m"

        Returns:
            Tuple of (duration_minutes, duration_range)
            - duration_minutes: minimum duration
            - duration_range: (min, max) tuple for flexible duration, or None for fixed
        """
        # Check for range: "2-4h" or "120-240m"
        range_match = re.match(r'(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\s*([hm])', duration_str.strip(), re.IGNORECASE)
        if range_match:
            min_val = float(range_match.group(1))
            max_val = float(range_match.group(2))
            unit = range_match.group(3).lower()

            if unit == 'h':
                min_minutes = int(min_val * 60)
                max_minutes = int(max_val * 60)
            else:
                min_minutes = int(min_val)
                max_minutes = int(max_val)

            return min_minutes, (min_minutes, max_minutes)

        # Check for fixed: "2h" or "120m"
        fixed_match = re.match(r'(\d+(?:\.\d+)?)\s*([hm])', duration_str.strip(), re.IGNORECASE)
        if fixed_match:
            val = float(fixed_match.group(1))
            unit = fixed_match.group(2).lower()

            minutes = int(val * 60) if unit == 'h' else int(val)
            return minutes, None

        return None, None

    @staticmethod
    def parse_reminder_string(reminder_str: str) -> Optional[int]:
        """Parse reminder string into minutes.

        Supports formats like:
        - "30m" → 30 minutes
        - "2h" → 120 minutes
        - "1h, 30m" → first value only (60 minutes)
        - "1hr and 30m" → first value only (60 minutes)

        Args:
            reminder_str: Reminder time string

        Returns:
            Minutes before event, or None if parsing fails
        """
        if not reminder_str:
            return None

        # For now, take the first value before comma or "and"
        first_value = re.split(r',|and', reminder_str)[0].strip()

        # Match hours: "2h", "2hr", or "2 hours"
        hour_match = re.search(r'(\d+(?:\.\d+)?)\s*h(?:ours?|r)?', first_value, re.IGNORECASE)
        if hour_match:
            return int(float(hour_match.group(1)) * 60)

        # Match minutes: "30m" or "30 minutes"
        minute_match = re.search(r'(\d+)\s*m(?:in(?:utes?)?)?', first_value, re.IGNORECASE)
        if minute_match:
            return int(minute_match.group(1))

        return None


def parse_todos(
    dir_path: Path,
    default_reminder_minutes: Optional[int] = None,
    default_duration_minutes: Optional[int] = None,
    default_priority: str = "medium",
    default_time_preference: str = "anytime",
) -> List[TodoItem]:
    """Convenience function to parse todos from a directory.

    Args:
        dir_path: Path to directory containing .md task files
        default_reminder_minutes: Default reminder time in minutes for tasks without explicit reminder
        default_duration_minutes: Default duration in minutes for tasks without explicit duration
        default_priority: Default priority for tasks without explicit priority (high/medium/low)
        default_time_preference: Default time preference for tasks without explicit time (morning/afternoon/evening/anytime)

    Returns:
        List of TodoItem objects
    """
    parser = DirectoryParser(
        dir_path,
        default_reminder_minutes,
        default_duration_minutes,
        default_priority,
        default_time_preference,
    )
    return parser.parse()
