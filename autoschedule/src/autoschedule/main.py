"""Main entry point for CalDAV Scheduler."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz

from .config import Config
from .markdown_parser import DirectoryParser
from .dependency_resolver import DependencyResolver
from .caldav_client import CalDAVClient
from .scheduler import AIScheduler


def main():
    """Main application entry point."""
    print("CalDAV Scheduler - AI-powered task scheduling\n")

    # Load configuration
    try:
        config = Config.from_env()
    except ValueError as e:
        print(f"Configuration error: {e}")
        print("\nPlease create a .env file based on .env.example")
        return 1

    # Parse todos from directory
    print(f"Reading todos from: {config.todo_dir_path}")
    try:
        parser = DirectoryParser(
            config.todo_dir_path,
            config.default_reminder_minutes,
            config.default_duration_minutes,
            config.default_priority,
            config.default_time_preference,
        )
        todos = parser.parse()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    if not todos:
        print("No todo files found in the directory.")
        print("\nExpected: .md files with duration field (dur: 2h)")
        return 0

    print(f"Found {len(todos)} todo file(s):")
    for todo in todos:
        priority_str = f" [{todo.priority}]" if todo.priority else ""
        calendar_str = f" [cal: {todo.calendar}]" if todo.calendar else ""
        date_str = f" [date: {todo.target_date}]" if todo.target_date else ""
        time_str = f" [time: {todo.time_preference}]"
        deps_str = f" [depends: {', '.join(todo.dependencies)}]" if todo.dependencies else ""
        print(f"  - {todo.title} ({todo.duration_minutes}m){priority_str}{calendar_str}{date_str}{time_str}{deps_str}")

    # Resolve dependencies
    print("\nResolving dependencies...")
    try:
        resolver = DependencyResolver(todos)
        sorted_todos = resolver.resolve_dependencies()
        dependency_info = resolver.get_dependency_info()
        print(f"Dependency resolution successful (topological order established)")
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Connect to CalDAV
    print(f"\nConnecting to CalDAV server: {config.caldav_url}")
    client = CalDAVClient(
        url=config.caldav_url,
        username=config.caldav_username,
        password=config.caldav_password,
        default_calendar=config.default_calendar,
    )

    try:
        client.connect()
        print("Connected successfully!")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return 1

    # List available calendars
    calendars = client.list_calendars()
    print(f"Available calendars: {', '.join(calendars)}")

    # Validate that all requested calendars exist
    requested_calendars = set(todo.calendar for todo in sorted_todos if todo.calendar)
    for cal_name in requested_calendars:
        try:
            client.get_calendar(cal_name)
        except ValueError as e:
            print(f"\nError: {e}")
            return 1

    # Get timezone
    tz = pytz.timezone(config.timezone)

    # Define search range (today + next 7 days) - do this earlier to check for existing events
    start_date = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date + timedelta(days=7)

    # Get existing events to check for duplicates
    print("\nChecking for existing events...")
    all_events = []
    for cal_name in calendars:
        try:
            cal_events = client.get_events(start_date, end_date, cal_name)
            all_events.extend(cal_events)
        except Exception as e:
            print(f"Warning: Could not get events from calendar '{cal_name}': {e}")

    # Filter out tasks that already have events
    existing_event_titles = {event.summary.lower().strip() for event in all_events if hasattr(event, 'summary') and event.summary}
    todos_to_schedule = []
    skipped_existing = []

    for todo in sorted_todos:
        if todo.title.lower().strip() in existing_event_titles:
            skipped_existing.append(todo.title)
        else:
            todos_to_schedule.append(todo)

    if skipped_existing:
        print(f"Skipping {len(skipped_existing)} task(s) with existing events:")
        for title in skipped_existing:
            print(f"  - {title}")

    if not todos_to_schedule:
        print("\nAll tasks already have calendar events. Nothing to schedule.")
        return 0

    print(f"\n{len(todos_to_schedule)} task(s) remaining to schedule")

    # Re-resolve dependencies with filtered todos
    if todos_to_schedule != sorted_todos:
        print("Re-resolving dependencies after filtering...")
        try:
            resolver = DependencyResolver(todos_to_schedule)
            sorted_todos = resolver.resolve_dependencies()
            dependency_info = resolver.get_dependency_info()
            print("Dependency resolution successful (topological order established)")
        except ValueError as e:
            print(f"Dependency error after filtering: {e}")
            return 1

    print(f"\nSearching for free slots from {start_date.date()} to {end_date.date()}...")

    # Find free slots across all calendars using all events
    free_slots = client.find_free_slots_from_events(
        events=all_events,
        start_date=start_date,
        end_date=end_date,
        work_start_hour=config.work_start_hour,
        work_end_hour=config.work_end_hour,
        min_duration_minutes=config.min_task_duration_minutes,
    )

    if not free_slots:
        print("No free slots found in the specified range.")
        return 0

    print(f"Found {len(free_slots)} free slot(s)")

    # Debug: Show first few slots with dates
    print("First few available slots:")
    for i, slot in enumerate(free_slots[:5]):
        slot_date = slot.start.strftime("%a %b %d")
        slot_time = f"{slot.start.strftime('%I:%M %p')} - {slot.end.strftime('%I:%M %p')}"
        print(f"  {i+1}. {slot_date}: {slot_time} ({slot.duration_minutes}m)")
    if len(free_slots) > 5:
        print(f"  ... and {len(free_slots) - 5} more slots")

    # Use all events for scheduling context
    existing_events = all_events

    # Schedule tasks using AI with dependency info
    print(f"\nUsing AI to schedule tasks (model: {config.claude_model})...")
    scheduler = AIScheduler(api_key=config.ai_api_key, model=config.claude_model)

    try:
        scheduled_tasks = scheduler.schedule_tasks(
            todos=sorted_todos,  # Use topologically sorted tasks
            free_slots=free_slots,
            existing_events=existing_events,
            dependency_info=dependency_info,  # Pass dependency information
        )
    except Exception as e:
        print(f"Scheduling failed: {e}")
        return 1

    if not scheduled_tasks:
        print("No tasks could be scheduled.")
        return 0

    # Map scheduled tasks back to original todos to get calendar info
    todo_map = {todo.title: todo for todo in sorted_todos}

    # Display scheduled tasks
    print(f"\nScheduled {len([t for t in scheduled_tasks if not t.get('skipped')])} task(s):")
    print()

    skipped_tasks = []
    for task in scheduled_tasks:
        if task.get("skipped"):
            skipped_tasks.append(task)
            continue

        # Get calendar from original todo
        original_todo = todo_map.get(task['title'])
        calendar_name = original_todo.calendar if original_todo else None
        calendar_str = f" → {calendar_name}" if calendar_name else ""

        print(f"  ✓ {task['title']}{calendar_str}")
        print(f"    Time: {task['start'].strftime('%a %b %d, %I:%M %p')} - {task['end'].strftime('%I:%M %p')}")
        print(f"    Duration: {task['duration_minutes']}m")
        print(f"    Reason: {task['reason']}")
        print()

    if skipped_tasks:
        print(f"\nSkipped {len(skipped_tasks)} task(s):")
        for task in skipped_tasks:
            print(f"  ✗ {task['title']}: {task['reason']}")
        print()

    # Ask for confirmation (unless auto-confirm is enabled)
    auto_confirm = os.environ.get("AUTO_CONFIRM", "false").lower() in ["true", "1", "yes"]

    if auto_confirm:
        print("Auto-confirm enabled, creating events...")
    else:
        response = input("Create these calendar events? (yes/no): ").strip().lower()
        if response not in ["yes", "y"]:
            print("Cancelled. No events created.")
            return 0

    # Create calendar events
    print("\nCreating calendar events...")
    created_count = 0

    for task in scheduled_tasks:
        if task.get("skipped"):
            continue

        # Get calendar, reminder, and link from original todo
        original_todo = todo_map.get(task['title'])
        calendar_name = original_todo.calendar if original_todo else None
        reminder_minutes = original_todo.reminder_minutes if original_todo else None
        link = original_todo.link if original_todo else None

        try:
            client.create_event(
                summary=task["title"],
                start=task["start"],
                end=task["end"],
                description=f"Scheduled by CalDAV Scheduler\n\n{task['reason']}",
                calendar_name=calendar_name,
                reminder_minutes=reminder_minutes,
                link=link,
            )
            calendar_str = f" → {calendar_name}" if calendar_name else ""
            print(f"  ✓ Created: {task['title']}{calendar_str}")
            created_count += 1
        except Exception as e:
            print(f"  ✗ Failed to create {task['title']}: {e}")

    print(f"\nSuccessfully created {created_count} calendar event(s)!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
