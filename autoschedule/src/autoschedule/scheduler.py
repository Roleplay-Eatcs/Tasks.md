"""AI-powered task scheduler using Claude."""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from anthropic import Anthropic

from .markdown_parser import TodoItem
from .caldav_client import FreeSlot, CalendarEvent


class AIScheduler:
    """AI-powered scheduler that uses Claude to intelligently schedule tasks."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-20250514"):
        """Initialize scheduler with Anthropic API key.

        Args:
            api_key: Anthropic API key
            model: Claude model to use (default: claude-haiku-4-20250514)
        """
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def schedule_tasks(
        self,
        todos: List[TodoItem],
        free_slots: List[FreeSlot],
        existing_events: Optional[List[CalendarEvent]] = None,
        dependency_info: Optional[Dict] = None,
    ) -> List[Dict]:
        """Schedule tasks into free slots using AI.

        Args:
            todos: List of todo items to schedule
            free_slots: Available free time slots
            existing_events: Optional list of existing events for context
            dependency_info: Optional dependency information from DependencyResolver

        Returns:
            List of scheduled tasks with start/end times
        """
        if not todos:
            return []

        if not free_slots:
            raise ValueError("No free slots available for scheduling")

        # Prepare data for Claude with dependencies and time preferences
        todos_data = [
            {
                "title": todo.title,
                "duration_minutes": todo.duration_minutes,
                "duration_range": todo.duration_range,  # (min, max) or None
                "max_duration_minutes": todo.duration_range[1] if todo.duration_range else None,
                "priority": todo.priority or "medium",
                "target_date": todo.target_date.isoformat() if todo.target_date else None,
                "time_preference": todo.time_preference,  # NEW
                "dependencies": dependency_info.get(todo.title, {}).get('dependencies', []) if dependency_info else [],  # NEW
                "must_schedule_after_tasks": dependency_info.get(todo.title, {}).get('must_schedule_after', []) if dependency_info else [],  # NEW
            }
            for todo in todos
        ]

        slots_data = [
            {
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
                "duration_minutes": slot.duration_minutes,
            }
            for slot in free_slots
        ]

        # Categorize slots by time preference
        slots_by_preference = self._categorize_slots_by_time(free_slots)

        # Build prompt for Claude with dependencies and time preferences
        prompt = self._build_scheduling_prompt(todos_data, slots_data, existing_events, slots_by_preference)

        # Call Claude API
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        response_text = message.content[0].text

        # Extract JSON from response
        try:
            # Find JSON in response (it might be wrapped in markdown code blocks)
            json_start = response_text.find('[')
            json_end = response_text.rfind(']') + 1

            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON array found in response")

            json_str = response_text[json_start:json_end]
            scheduled_tasks = json.loads(json_str)

            # Convert ISO strings back to datetime objects
            for task in scheduled_tasks:
                if not task.get("skipped"):
                    task["start"] = datetime.fromisoformat(task["start"])
                    task["end"] = datetime.fromisoformat(task["end"])

            # Validate schedules fit within free slots
            validated_tasks = self._validate_schedules(scheduled_tasks, free_slots, existing_events)

            return validated_tasks

        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Failed to parse scheduling response: {e}\nResponse: {response_text}")

    def _validate_schedules(
        self,
        scheduled_tasks: List[Dict],
        free_slots: List[FreeSlot],
        existing_events: Optional[List[CalendarEvent]] = None,
    ) -> List[Dict]:
        """Validate that scheduled tasks fit within free slots and don't overlap with existing events.

        Args:
            scheduled_tasks: List of tasks scheduled by AI
            free_slots: Available free time slots
            existing_events: Optional existing calendar events

        Returns:
            List of validated tasks (invalid ones marked as skipped)
        """
        validated = []

        for task in scheduled_tasks:
            if task.get("skipped"):
                validated.append(task)
                continue

            task_start = task["start"]
            task_end = task["end"]
            task_valid = False

            # Check if task fits within any free slot
            for slot in free_slots:
                if task_start >= slot.start and task_end <= slot.end:
                    task_valid = True
                    break

            if not task_valid:
                # Task doesn't fit in any free slot - mark as skipped
                task["skipped"] = True
                task["reason"] = f"VALIDATION ERROR: Task scheduled outside of free slots ({task_start} - {task_end}). Original reason: {task.get('reason', 'N/A')}"
                print(f"Warning: Task '{task['title']}' scheduled outside free slots, marking as skipped")

            # Check for overlaps with existing events
            if task_valid and existing_events:
                for event in existing_events:
                    # Check if task overlaps with existing event
                    if (task_start < event.end and task_end > event.start):
                        task["skipped"] = True
                        task["reason"] = f"VALIDATION ERROR: Task overlaps with existing event '{event.summary}' ({event.start} - {event.end})"
                        task_valid = False
                        print(f"Warning: Task '{task['title']}' overlaps with event '{event.summary}', marking as skipped")
                        break

            validated.append(task)

        return validated

    def _categorize_slots_by_time(self, slots: List[FreeSlot]) -> Dict[str, List[Dict]]:
        """Categorize slots by time of day.

        Args:
            slots: List of free slots

        Returns:
            Dict mapping time categories to slot data
        """
        categorized = {
            'morning': [],
            'afternoon': [],
            'evening': [],
            'anytime': []
        }

        for slot in slots:
            hour = slot.start.hour
            slot_data = {
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
                "duration_minutes": slot.duration_minutes,
            }

            # Morning: before 12:00
            if hour < 12:
                slot_data_with_cat = dict(slot_data, time_category="morning")
                categorized['morning'].append(slot_data_with_cat)
            # Afternoon: 12:00 to 17:00
            elif hour < 17:
                slot_data_with_cat = dict(slot_data, time_category="afternoon")
                categorized['afternoon'].append(slot_data_with_cat)
            # Evening: after 17:00
            else:
                slot_data_with_cat = dict(slot_data, time_category="evening")
                categorized['evening'].append(slot_data_with_cat)

            # All slots also go in anytime
            slot_data_with_cat = dict(slot_data, time_category="anytime")
            categorized['anytime'].append(slot_data_with_cat)

        return categorized

    def _build_scheduling_prompt(
        self,
        todos: List[Dict],
        slots: List[Dict],
        existing_events: Optional[List[CalendarEvent]] = None,
        slots_by_preference: Optional[Dict[str, List[Dict]]] = None,
    ) -> str:
        """Build prompt for Claude to schedule tasks with dependency and time preference support.

        Args:
            todos: Todo items data
            slots: Free slot data
            existing_events: Optional existing events
            slots_by_preference: Optional slots categorized by time of day

        Returns:
            Prompt string
        """
        prompt = f"""You are a scheduling assistant. I need you to schedule the following tasks into available time slots.

TASKS TO SCHEDULE:
{json.dumps(todos, indent=2)}

AVAILABLE TIME SLOTS (These are the ONLY valid times - these slots are already calculated to avoid existing calendar events):
{json.dumps(slots, indent=2)}

TIME SLOTS BY PREFERENCE:
{json.dumps(slots_by_preference, indent=2) if slots_by_preference else 'N/A'}

CRITICAL CONSTRAINTS:
- You MUST ONLY use the time slots listed in "AVAILABLE TIME SLOTS" above
- DO NOT schedule tasks outside of these slots under any circumstances
- These slots are already calculated to avoid conflicts with existing events
- If a task doesn't fit in any available slot, skip it with "skipped": true
- SCHEDULE TASKS AS EARLY AS POSSIBLE: Always use the earliest available time slot that fits the task
- MULTIPLE TASKS CAN FIT IN THE SAME SLOT: A time slot can contain multiple tasks as long as they don't overlap
  - Example: A 9:00-12:00 slot (180 minutes) can fit a 60-minute task at 9:00-10:00 AND another 90-minute task at 10:00-11:30
  - Track already-scheduled tasks and treat them as obstacles within slots
  - When scheduling a new task, check if it overlaps with any already-scheduled task in that slot
  - Fill gaps: If a task doesn't fit at the start of a slot due to an already-scheduled task, check if it fits after that task
- PRIORITY ORDERING WITH SMART SLOT FILLING:
  - PREFER high priority tasks over lower priority tasks when multiple tasks could fit in the same slot
  - However, use lower priority tasks to fill slots where higher priority tasks cannot fit
  - Algorithm: For each available time slot (or portion of a slot):
    1. First try to fit the highest priority unscheduled task that hasn't been tried in this slot
    2. If no high priority tasks fit, try medium priority tasks
    3. If no medium priority tasks fit, try low priority tasks
    4. This ensures slots aren't wasted while still prioritizing important tasks
  - Example: If a 30-minute slot exists and you have:
    * High priority task needing 60 minutes (doesn't fit)
    * Low priority task needing 20 minutes (fits)
    → Schedule the low priority task in the 30-minute slot, don't waste it
  - Exception: Dependencies may require scheduling a lower priority task before a higher priority one

INSTRUCTIONS:
1. CRITICAL - SCHEDULING APPROACH:
   - Process slots chronologically (earliest first)
   - For each slot or available time within a slot, try to fit the best task:
     a. Check all high priority tasks - can any fit? Pick the best match (considering time preference, dependencies)
     b. If no high priority tasks fit, check medium priority tasks
     c. If no medium priority tasks fit, check low priority tasks
   - This maximizes slot utilization while respecting priority when possible
   - Track what times are already occupied by previously-scheduled tasks
   - Example scheduling sequence in a 9:00-12:00 slot with tasks:
     * High priority 90min task → 9:00-10:30
     * High priority 120min task → won't fit in remaining 90min
     * Low priority 60min task → 10:30-11:30 (fits in remaining space)
     * Medium priority 30min task → 11:30-12:00 (fills last gap)
2. For tasks with fixed duration (no duration_range):
   - Respect task durations exactly
3. For tasks with flexible duration (duration_range field is present):
   - Schedule at least the minimum duration (duration_minutes)
   - Maximize duration up to max_duration_minutes if the available time in the slot allows (considering already-scheduled tasks)
   - Prefer extending high-priority tasks over low-priority ones
   - Example: Task with 120-240min range with 240min available should get 240min
   - Example: Task with 60-120min range with only 90min available should get 90min
4. CRITICAL - DEPENDENCIES:
   - If a task has dependencies (dependencies field), it MUST be scheduled AFTER all its prerequisite tasks
   - Check must_schedule_after_tasks for the list of task titles that must complete first
   - A dependent task can start immediately after its prerequisites end (no gap required)
   - If prerequisites cannot be scheduled, skip the dependent task too
5. CRITICAL - TIME PREFERENCES:
   - Time preferences are SOFT preferences (use if available, but priority and earliest scheduling take precedence)
   - If a task has time_preference='morning', prefer morning slots (before 12:00 PM) if available
   - If time_preference='afternoon', prefer afternoon slots (12:00 PM - 5:00 PM) if available
   - If time_preference='evening', prefer evening slots (after 5:00 PM) if available
   - If time_preference='anytime' or not specified, use any available slot
   - IMPORTANT: Do NOT delay a high-priority task just to match time preference - priority and earliest scheduling come first
6. If a task has a target_date, it MUST be scheduled on that specific date. Only use time slots that match the target date.
7. Don't split tasks across multiple slots
8. If a task doesn't fit or dependencies cannot be satisfied, skip it and explain why

"""

        if existing_events:
            events_summary = "\n".join([f"- {e.summary} ({e.start} - {e.end})" for e in existing_events[:5]])
            prompt += f"""CONTEXT (Existing events for reference):
{events_summary}

"""

        prompt += """Return your response as a JSON array of scheduled tasks. For each scheduled task, include:
- title: Task title (string)
- start: Start time in ISO format (string)
- end: End time in ISO format (string)
- duration_minutes: Actual scheduled duration in minutes (integer)
- reason: Brief explanation including dependency satisfaction and time preference matching (string)

For any tasks that couldn't be scheduled, include them with "skipped": true and explain why (e.g., "Dependencies not satisfied" or "No suitable slots").

Example format:
[
  {
    "title": "Prepare test task",
    "start": "2025-12-04T09:00:00",
    "end": "2025-12-04T10:00:00",
    "duration_minutes": 60,
    "reason": "Medium priority task with morning preference, scheduled in morning slot"
  },
  {
    "title": "Test task 1",
    "start": "2025-12-04T13:00:00",
    "end": "2025-12-04T14:30:00",
    "duration_minutes": 90,
    "reason": "High priority task scheduled after dependency 'Prepare test task', afternoon preference matched"
  },
  {
    "title": "Test task 2",
    "skipped": true,
    "reason": "Dependency 'Test task 1' could not be scheduled"
  }
]

Return ONLY the JSON array, no other text or markdown formatting.
"""

        return prompt


def schedule_todos(
    todos: List[TodoItem],
    free_slots: List[FreeSlot],
    api_key: str,
    existing_events: Optional[List[CalendarEvent]] = None,
) -> List[Dict]:
    """Convenience function to schedule todos.

    Args:
        todos: List of todo items
        free_slots: Available free slots
        api_key: Anthropic API key
        existing_events: Optional existing events

    Returns:
        List of scheduled tasks
    """
    scheduler = AIScheduler(api_key)
    return scheduler.schedule_tasks(todos, free_slots, existing_events)
