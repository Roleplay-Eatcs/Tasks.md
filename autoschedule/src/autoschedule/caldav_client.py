"""CalDAV client for interacting with calendar servers."""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass

import caldav
from caldav.elements import dav, cdav
import pytz
import requests
from requests.auth import HTTPDigestAuth


@dataclass
class CalendarEvent:
    """Represents a calendar event."""

    uid: str
    summary: str
    start: datetime
    end: datetime
    description: Optional[str] = None

    def __str__(self):
        return f"{self.summary} ({self.start} - {self.end})"


@dataclass
class FreeSlot:
    """Represents a free time slot in the calendar."""

    start: datetime
    end: datetime

    @property
    def duration_minutes(self) -> int:
        """Get duration of slot in minutes."""
        return int((self.end - self.start).total_seconds() / 60)

    def __str__(self):
        return f"{self.start} - {self.end} ({self.duration_minutes}m)"


class CalDAVClient:
    """Client for interacting with CalDAV servers."""

    def __init__(self, url: str, username: str, password: str, default_calendar: Optional[str] = None):
        """Initialize CalDAV client.

        Args:
            url: CalDAV server URL (principal URL or specific calendar URL)
            username: CalDAV username
            password: CalDAV password
            default_calendar: Optional default calendar name for tasks without calendar specified
        """
        self.url = url
        self.username = username
        self.password = password
        self.default_calendar = default_calendar
        self._client = None
        self._principal = None
        self._calendars: Dict[str, caldav.Calendar] = {}

    def connect(self):
        """Connect to CalDAV server and discover calendars."""
        from requests.auth import HTTPDigestAuth, HTTPBasicAuth

        # First, probe to see which auth method is required
        print("  Detecting authentication method...")
        probe_response = requests.head(self.url)

        auth_header = probe_response.headers.get('WWW-Authenticate', '')

        # Create a session with the appropriate auth
        session = requests.Session()

        if 'Digest' in auth_header:
            print("  Using Digest authentication")
            session.auth = HTTPDigestAuth(self.username, self.password)
        else:
            print("  Using Basic authentication")
            session.auth = HTTPBasicAuth(self.username, self.password)

        # Create DAVClient with the session
        # Note: caldav library will use this session for all requests
        self._client = caldav.DAVClient(
            url=self.url,
            username=self.username,
            password=self.password
        )
        # Replace the client's session with our configured one
        self._client.session = session

        # Test authentication first
        print("  Testing authentication...")
        try:
            # Try to access the principal to verify credentials
            self._principal = self._client.principal()
            print("  ✓ Authentication successful")
        except Exception as auth_error:
            error_msg = str(auth_error)
            if "Unauthorized" in error_msg or "401" in error_msg:
                raise ValueError(
                    f"Authentication failed. Please check your username and password.\n"
                    f"  URL: {self.url}\n"
                    f"  Username: {self.username}\n"
                    f"  Error: {auth_error}"
                )
            elif "Not Found" in error_msg or "404" in error_msg:
                raise ValueError(
                    f"CalDAV endpoint not found. Please check your URL.\n"
                    f"  URL: {self.url}\n"
                    f"  Error: {auth_error}"
                )
            else:
                raise ValueError(f"Connection failed: {auth_error}")

        # Discover calendars
        print("  Discovering calendars...")
        try:
            calendars = self._principal.calendars()

            # Store calendars by name (case-insensitive)
            for cal in calendars:
                try:
                    # Try multiple ways to get calendar name
                    cal_name = None

                    # Method 1: Try display name property
                    try:
                        if hasattr(cal, 'get_properties'):
                            props = cal.get_properties([dav.DisplayName()])
                            if props and dav.DisplayName() in props:
                                cal_name = str(props[dav.DisplayName()])
                    except Exception:
                        pass

                    # Method 2: Try the name attribute
                    if not cal_name:
                        try:
                            cal_name = cal.name
                        except Exception:
                            pass

                    # Method 3: Extract from URL path
                    if not cal_name:
                        try:
                            # Get the last part of the calendar URL path
                            url_path = str(cal.url).rstrip('/')
                            cal_name = url_path.split('/')[-1]
                        except Exception:
                            pass

                    # Store calendar if we got a name
                    if cal_name and cal_name.strip():
                        self._calendars[cal_name.lower().strip()] = cal
                        print(f"  Found calendar: {cal_name}")
                    else:
                        print(f"  Warning: Calendar with no name found at {cal.url}")

                except Exception as e:
                    print(f"  Warning: Could not process calendar: {e}")
                    continue

            # If no calendars found, add a default one
            if not self._calendars:
                print("  Warning: No calendars discovered, using URL as default calendar")
                calendar = caldav.Calendar(client=self._client, url=self.url)
                self._calendars["default"] = calendar

        except Exception as e:
            # If we can't get principal, try to access calendars directly
            print(f"  Could not discover calendars via principal ({e})")
            print(f"  Attempting direct calendar access...")

            # Try to list calendars by making a PROPFIND request to the base URL
            try:
                # The URL might be a calendars collection, try to list them
                # Try Digest auth first, then Basic
                for auth_type, auth_name in [
                    (HTTPDigestAuth(self.username, self.password), "Digest"),
                    (HTTPBasicAuth(self.username, self.password), "Basic")
                ]:
                    response = requests.request(
                        'PROPFIND',
                        self.url,
                        auth=auth_type,
                        headers={'Depth': '1'},
                        timeout=10
                    )
                    if response.status_code == 207:
                        print(f"  ✓ Successfully accessed with {auth_name} auth")
                        print(f"  ✓ Successfully accessed calendar collection")
                        # Parse the response to find calendars
                        # For now, create a default calendar from this URL
                        calendar = caldav.Calendar(client=self._client, url=self.url)
                        self._calendars["default"] = calendar
                        print(f"  Found calendar: default (collection at {self.url})")
                        break
                else:
                    raise Exception(f"HTTP {response.status_code}")

            except Exception as direct_error:
                print(f"  Warning: Direct calendar access also failed: {direct_error}")
                print(f"  Creating fallback default calendar")
                calendar = caldav.Calendar(client=self._client, url=self.url)
                self._calendars["default"] = calendar

    def list_calendars(self) -> List[str]:
        """List all available calendar names.

        Returns:
            List of calendar names
        """
        if not self._calendars:
            self.connect()
        return sorted(self._calendars.keys())

    def get_calendar(self, calendar_name: Optional[str] = None) -> caldav.Calendar:
        """Get a specific calendar by name.

        Args:
            calendar_name: Calendar name (case-insensitive). If None, uses default.

        Returns:
            Calendar object

        Raises:
            ValueError: If calendar doesn't exist
        """
        if not self._calendars:
            self.connect()

        # Use default calendar if no name specified
        if calendar_name is None:
            calendar_name = self.default_calendar or next(iter(self._calendars.keys()))

        # Normalize calendar name (case-insensitive)
        calendar_name_lower = calendar_name.lower()

        if calendar_name_lower not in self._calendars:
            available = ", ".join(self._calendars.keys())
            raise ValueError(
                f"Calendar '{calendar_name}' not found. Available calendars: {available}"
            )

        return self._calendars[calendar_name_lower]

    def get_events(
        self, start_date: datetime, end_date: datetime, calendar_name: Optional[str] = None
    ) -> List[CalendarEvent]:
        """Get all events in date range.

        Args:
            start_date: Start of date range
            end_date: End of date range
            calendar_name: Optional calendar name (case-insensitive)

        Returns:
            List of CalendarEvent objects
        """
        calendar = self.get_calendar(calendar_name)

        events = []
        cal_events = calendar.date_search(start=start_date, end=end_date)

        for event in cal_events:
            try:
                ical = event.icalendar_component

                # Skip if not an event
                if ical.name != "VEVENT":
                    continue

                summary = str(ical.get("SUMMARY", "Untitled"))
                uid = str(ical.get("UID", ""))
                description = str(ical.get("DESCRIPTION", "")) if ical.get("DESCRIPTION") else None

                # Get start and end times
                dtstart = ical.get("DTSTART").dt
                dtend = ical.get("DTEND").dt if ical.get("DTEND") else None

                # Handle all-day events
                if not isinstance(dtstart, datetime):
                    continue

                if not dtend:
                    dtend = dtstart + timedelta(hours=1)

                # Ensure timezone-aware datetimes
                if dtstart.tzinfo is None:
                    dtstart = pytz.UTC.localize(dtstart)
                if dtend.tzinfo is None:
                    dtend = pytz.UTC.localize(dtend)

                events.append(
                    CalendarEvent(
                        uid=uid,
                        summary=summary,
                        start=dtstart,
                        end=dtend,
                        description=description,
                    )
                )
            except Exception as e:
                print(f"Warning: Failed to parse event: {e}")
                continue

        return sorted(events, key=lambda e: e.start)

    def find_free_slots_from_events(
        self,
        events: List[CalendarEvent],
        start_date: datetime,
        end_date: datetime,
        work_start_hour: int = 9,
        work_end_hour: int = 17,
        min_duration_minutes: int = 15,
    ) -> List[FreeSlot]:
        """Find free time slots from a given list of events.

        Args:
            events: List of calendar events to consider
            start_date: Start of date range to search
            end_date: End of date range to search
            work_start_hour: Start of work day (24h format)
            work_end_hour: End of work day (24h format)
            min_duration_minutes: Minimum slot duration in minutes

        Returns:
            List of FreeSlot objects
        """
        free_slots = []

        # Get timezone from start_date
        tz = start_date.tzinfo if start_date.tzinfo else pytz.UTC
        now = datetime.now(tz)

        current_date = start_date.date()
        end_search_date = end_date.date()

        while current_date <= end_search_date:
            # Define work day boundaries
            work_start = datetime.combine(
                current_date, datetime.min.time()
            ).replace(hour=work_start_hour, tzinfo=tz)
            work_end = datetime.combine(
                current_date, datetime.min.time()
            ).replace(hour=work_end_hour, tzinfo=tz)

            # For today, start from current time instead of work_start
            # This prevents creating slots in the past
            is_today = current_date == now.date()
            if is_today:
                original_work_start = work_start
                work_start = max(work_start, now)
                # Debug: This should prevent past slots from being created
                # print(f"[DEBUG] Today: adjusted work_start from {original_work_start.strftime('%I:%M %p')} to {work_start.strftime('%I:%M %p')}")

            # Skip if work day has already ended
            if work_start >= work_end:
                current_date += timedelta(days=1)
                continue

            # Get events for this day
            day_events = [
                e for e in events
                if e.start.date() == current_date or e.end.date() == current_date
            ]

            # Sort events by start time
            day_events.sort(key=lambda e: e.start)

            # Find gaps between events
            current_time = work_start

            for event in day_events:
                event_start = max(event.start, work_start)
                event_end = min(event.end, work_end)

                # Skip events outside work hours
                if event_end <= work_start or event_start >= work_end:
                    continue

                # If there's a gap before this event
                if current_time < event_start:
                    slot_duration = (event_start - current_time).total_seconds() / 60
                    if slot_duration >= min_duration_minutes:
                        free_slots.append(FreeSlot(start=current_time, end=event_start))

                # Move current time to end of event
                current_time = max(current_time, event_end)

            # Check for free time after last event
            if current_time < work_end:
                slot_duration = (work_end - current_time).total_seconds() / 60
                if slot_duration >= min_duration_minutes:
                    free_slots.append(FreeSlot(start=current_time, end=work_end))

            current_date += timedelta(days=1)

        # Filter out slots that have already passed (start time is in the past)
        # Use the now we calculated at the start to avoid timing issues
        free_slots = [slot for slot in free_slots if slot.start >= now]

        return free_slots

    def find_free_slots(
        self,
        start_date: datetime,
        end_date: datetime,
        work_start_hour: int = 9,
        work_end_hour: int = 17,
        min_duration_minutes: int = 15,
        calendar_name: Optional[str] = None,
    ) -> List[FreeSlot]:
        """Find free time slots in the calendar.

        Args:
            start_date: Start of date range to search
            end_date: End of date range to search
            work_start_hour: Start of work day (24h format)
            work_end_hour: End of work day (24h format)
            min_duration_minutes: Minimum slot duration in minutes
            calendar_name: Optional calendar name (case-insensitive)

        Returns:
            List of FreeSlot objects
        """
        events = self.get_events(start_date, end_date, calendar_name)
        return self.find_free_slots_from_events(
            events, start_date, end_date, work_start_hour, work_end_hour, min_duration_minutes
        )

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        description: Optional[str] = None,
        calendar_name: Optional[str] = None,
        reminder_minutes: Optional[int] = None,
        link: Optional[str] = None,
    ) -> CalendarEvent:
        """Create a new calendar event.

        Args:
            summary: Event title
            start: Event start time
            end: Event end time
            description: Optional event description
            calendar_name: Optional calendar name (case-insensitive)
            reminder_minutes: Optional reminder time in minutes before event
            link: Optional URL for online meetings, resources, etc.

        Returns:
            Created CalendarEvent

        Raises:
            ValueError: If calendar doesn't exist
        """
        calendar = self.get_calendar(calendar_name)

        # Convert times to UTC for consistent iCalendar format
        start_utc = start.astimezone(pytz.UTC)
        end_utc = end.astimezone(pytz.UTC)

        # Create iCalendar event with proper UTC timestamps
        event_str = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CalDAV Scheduler//EN
BEGIN:VEVENT
UID:{datetime.now().timestamp()}@caldav-scheduler
DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}
DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}
SUMMARY:{summary}
"""
        if description:
            event_str += f"DESCRIPTION:{description}\n"

        # Add URL/link if specified (for online meetings, etc.)
        if link:
            event_str += f"URL:{link}\n"

        # Add reminder (VALARM) if specified
        if reminder_minutes:
            # Format as ISO 8601 duration (e.g., PT15M for 15 minutes, PT1H for 1 hour)
            if reminder_minutes >= 60 and reminder_minutes % 60 == 0:
                hours = reminder_minutes // 60
                duration = f"PT{hours}H"
            else:
                duration = f"PT{reminder_minutes}M"

            event_str += f"""BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder
TRIGGER:-{duration}
END:VALARM
"""

        event_str += """END:VEVENT
END:VCALENDAR
"""

        # Add event to calendar
        calendar.save_event(event_str)

        return CalendarEvent(
            uid=f"{datetime.now().timestamp()}@caldav-scheduler",
            summary=summary,
            start=start,
            end=end,
            description=description,
        )
