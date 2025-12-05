#!/usr/bin/env python3
"""Periodic scheduler runner for Docker Swarm deployment."""

import os
import sys
import time
import traceback
from datetime import datetime

from .main import main


def run_periodic():
    """Run the scheduler periodically based on SCHEDULE_INTERVAL_MINUTES."""
    # Get interval from environment variable (default: 15 minutes)
    interval_minutes = int(os.environ.get("SCHEDULE_INTERVAL_MINUTES", "15"))
    interval_seconds = interval_minutes * 60

    # Auto-enable AUTO_CONFIRM if not set
    if "AUTO_CONFIRM" not in os.environ:
        os.environ["AUTO_CONFIRM"] = "true"
        print("Note: AUTO_CONFIRM not set, enabling by default for periodic runs\n")

    print(f"CalDAV Scheduler - Periodic Runner")
    print(f"Running every {interval_minutes} minute(s)")
    print(f"Auto-confirm: {os.environ.get('AUTO_CONFIRM', 'false')}")
    print(f"Timezone: {os.environ.get('TIMEZONE', 'UTC')}")
    print("-" * 60)

    run_count = 0

    while True:
        run_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'=' * 60}")
        print(f"Run #{run_count} - {timestamp}")
        print(f"{'=' * 60}\n")

        try:
            # Run the main scheduler
            exit_code = main()

            if exit_code != 0:
                print(f"\nWarning: Scheduler exited with code {exit_code}")
        except KeyboardInterrupt:
            print("\n\nReceived interrupt signal. Shutting down gracefully...")
            sys.exit(0)
        except Exception as e:
            print(f"\nError during scheduler run: {e}")
            traceback.print_exc()

        # Wait for next interval
        print(f"\n{'=' * 60}")
        print(f"Next run in {interval_minutes} minute(s)...")
        print(f"{'=' * 60}")

        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\n\nReceived interrupt signal. Shutting down gracefully...")
            sys.exit(0)


if __name__ == "__main__":
    run_periodic()
