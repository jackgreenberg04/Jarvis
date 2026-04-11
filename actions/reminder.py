# actions/reminder.py — macOS version
# Uses 'at' command (or launchd plist) for macOS scheduling
# Falls back to a background thread for simple reminders

import subprocess
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


def _show_macos_notification(title: str, message: str) -> None:
    """Display a native macOS notification using osascript."""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Ping"'
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception as e:
        print(f"[Reminder] ⚠️ Notification error: {e}")


def _reminder_thread(delay_seconds: float, message: str, title: str) -> None:
    """Background thread that waits then fires the reminder."""
    time.sleep(delay_seconds)
    _show_macos_notification(title, message)
    print(f"[Reminder] 🔔 Fired: {message}")


def reminder(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None
) -> str:
    """
    Sets a timed reminder on macOS using a background thread + osascript notification.

    parameters:
        - date    (str) YYYY-MM-DD
        - time    (str) HH:MM
        - message (str)
    """
    date_str = parameters.get("date")
    time_str = parameters.get("time")
    message  = parameters.get("message", "Reminder")

    if not date_str or not time_str:
        return "I need both a date and a time to set a reminder."

    try:
        target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

        if target_dt <= datetime.now():
            return "That time is already in the past."

        delay_seconds = (target_dt - datetime.now()).total_seconds()
        safe_message  = message.replace('"', '').replace("'", "").strip()[:200]

        t = threading.Thread(
            target=_reminder_thread,
            args=(delay_seconds, safe_message, "MARK Reminder"),
            daemon=True
        )
        t.start()

        if player:
            player.write_log(f"[reminder] set for {date_str} {time_str}")

        return f"Reminder set for {target_dt.strftime('%B %d at %I:%M %p')}."

    except ValueError:
        return "I couldn't understand that date or time format."
    except Exception as e:
        return f"Something went wrong while scheduling the reminder: {str(e)[:80]}"
