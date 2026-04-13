# actions/reminder.py — macOS version

import subprocess
import threading
import time
from datetime import datetime


def _show_macos_notification(title: str, message: str) -> None:
    """Display a native macOS notification using osascript."""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Ping"'
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception as e:
        print(f"[Reminder] ⚠️ Notification error: {e}")


def _reminder_thread(delay_seconds: float, message: str, title: str, speak=None, player=None) -> None:
    """Background thread: waits, then fires notification AND speaks via JARVIS."""
    time.sleep(delay_seconds)

    # 1. macOS system notification (shows in notification centre)
    _show_macos_notification(title, message)

    # 2. JARVIS speaks the reminder out loud
    if speak:
        try:
            speak(f"Repeat sentence: Sir, reminder: {message}")
        except Exception as e:
            print(f"[Reminder] ⚠️ speak failed: {e}")

    # 3. Log to UI
    if player:
        try:
            player.write_log(f"🔔 Reminder: {message}")
        except Exception:
            pass

    print(f"[Reminder] 🔔 Fired: {message}")


def reminder(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Sets a timed reminder on macOS.
    Fires a macOS notification AND makes JARVIS speak the reminder aloud.

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
            args=(delay_seconds, safe_message, "J.A.R.V.I.S Reminder"),
            kwargs={"speak": speak, "player": player},
            daemon=False,
        )
        t.start()

        if player:
            player.write_log(f"[reminder] set for {date_str} {time_str}")

        return f"Reminder set for {target_dt.strftime('%B %d at %I:%M %p')}."

    except ValueError:
        return "I couldn't understand that date or time format."
    except Exception as e:
        return f"Something went wrong while scheduling the reminder: {str(e)[:80]}"
