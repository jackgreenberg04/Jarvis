# actions/game_updater.py — macOS version
# Steam on macOS is fully supported; Epic Games has limited macOS support.
# winreg is replaced with filesystem/plist lookups.

import os
import re
import sys
import json
import time
import subprocess
import threading
from pathlib import Path
from datetime import datetime


def _find_steam_path() -> Path | None:
    """Locate Steam installation on macOS."""
    candidates = [
        Path.home() / "Library" / "Application Support" / "Steam",
        Path("/Applications/Steam.app/Contents/MacOS"),
        Path.home() / "Applications" / "Steam.app" / "Contents" / "MacOS",
    ]
    for p in candidates:
        if p.exists():
            # Check for steam binary or the steamapps folder
            if (p / "steam_osx").exists() or (p / "steamapps").exists():
                return p
    return None


def _get_steam_exe(steam_path: Path) -> Path | None:
    """Return the Steam executable on macOS."""
    # The actual app bundle
    app = Path("/Applications/Steam.app")
    if app.exists():
        return app
    app = Path.home() / "Applications" / "Steam.app"
    if app.exists():
        return app
    return None


def _get_steam_libraries(steam_path: Path) -> list[Path]:
    libraries = [steam_path / "steamapps"]
    vdf_path  = steam_path / "steamapps" / "libraryfolders.vdf"
    if not vdf_path.exists():
        return libraries
    try:
        content = vdf_path.read_text(encoding="utf-8", errors="ignore")
        for raw_path in re.findall(r'"path"\s+"([^"]+)"', content):
            lib = Path(raw_path.replace("\\\\", "/")) / "steamapps"
            if lib.exists() and lib not in libraries:
                libraries.append(lib)
    except Exception:
        pass
    return libraries


def _get_steam_games(steam_path: Path) -> list[dict]:
    games = []
    for lib in _get_steam_libraries(steam_path):
        for acf in lib.glob("appmanifest_*.acf"):
            try:
                content = acf.read_text(encoding="utf-8", errors="ignore")
                app_id  = re.search(r'"appid"\s+"(\d+)"',     content)
                name    = re.search(r'"name"\s+"([^"]+)"',     content)
                state   = re.search(r'"StateFlags"\s+"(\d+)"', content)
                size    = re.search(r'"SizeOnDisk"\s+"(\d+)"', content)
                if app_id and name:
                    games.append({
                        "id":    app_id.group(1),
                        "name":  name.group(1),
                        "state": int(state.group(1)) if state else 0,
                        "size":  int(size.group(1))  if size  else 0,
                        "lib":   str(lib),
                    })
            except Exception:
                continue
    return games


def _is_steam_running() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-x", "steam_osx"],
            capture_output=True, text=True
        ).stdout.strip()
        return bool(out)
    except Exception:
        return False


def _ensure_steam_running(steam_path: Path) -> bool:
    if _is_steam_running():
        return True
    app = _get_steam_exe(steam_path)
    if not app:
        print("[GameUpdater] ❌ Steam.app not found")
        return False
    print("[GameUpdater] 🚀 Starting Steam...")
    subprocess.Popen(["open", str(app)])
    for _ in range(20):
        time.sleep(1)
        if _is_steam_running():
            print("[GameUpdater] ✅ Steam running")
            time.sleep(4)
            return True
    print("[GameUpdater] ⚠️ Steam did not start in time")
    return False


def _launch_steam_url(steam_path: Path, url: str) -> None:
    """Open a steam:// URL on macOS."""
    subprocess.Popen(["open", url])


def _update_steam_games(steam_path: Path, game_name: str = None) -> str:
    if not _ensure_steam_running(steam_path):
        return "Could not start Steam."

    games = _get_steam_games(steam_path)
    if not games:
        return "No Steam games found."

    if game_name:
        name_lower = game_name.lower()
        matched    = [g for g in games if name_lower in g["name"].lower()]
        if not matched:
            available = ", ".join(g["name"] for g in games[:5])
            return f"Game '{game_name}' not found. Installed: {available}..."
        targets = matched
    else:
        targets = games

    already_updated, already_running, update_started, errors = [], [], [], []

    for game in targets:
        state = game["state"]
        name  = game["name"]
        if state == 4:
            already_updated.append(name)
        elif state == 1026:
            already_running.append(name)
        else:
            try:
                _launch_steam_url(steam_path, f"steam://update/{game['id']}")
                update_started.append(name)
                time.sleep(0.3)
            except Exception as e:
                errors.append(f"{name}: {e}")

    parts = []
    if update_started:
        names  = ", ".join(update_started[:3])
        suffix = f" and {len(update_started) - 3} more" if len(update_started) > 3 else ""
        parts.append(f"Update started for: {names}{suffix}.")
    if already_running:
        parts.append(f"Already updating: {', '.join(already_running)}.")
    if already_updated:
        parts.append(
            f"{already_updated[0]} is already up to date."
            if game_name else
            f"{len(already_updated)} game(s) already up to date."
        )
    if errors:
        parts.append(f"Errors: {'; '.join(errors)}.")
    return " ".join(parts) if parts else "No games to update."


_KNOWN_APPIDS: dict[str, tuple[str, str]] = {
    "pubg":                ("578080",  "PUBG: Battlegrounds"),
    "gta5":                ("271590",  "Grand Theft Auto V"),
    "cs2":                 ("730",     "Counter-Strike 2"),
    "dota2":               ("570",     "Dota 2"),
    "dota 2":              ("570",     "Dota 2"),
    "rust":                ("252490",  "Rust"),
    "valheim":             ("892970",  "Valheim"),
    "cyberpunk 2077":      ("1091500", "Cyberpunk 2077"),
    "elden ring":          ("1245620", "ELDEN RING"),
    "minecraft":           ("1672970", "Minecraft Launcher"),
    "apex legends":        ("1172470", "Apex Legends"),
    "apex":                ("1172470", "Apex Legends"),
    "fall guys":           ("1097150", "Fall Guys"),
    "rocket league":       ("252950",  "Rocket League"),
    "destiny 2":           ("1085660", "Destiny 2"),
    "team fortress 2":     ("440",     "Team Fortress 2"),
    "tf2":                 ("440",     "Team Fortress 2"),
}


def _search_steam_appid(game_name: str) -> tuple[str | None, str | None]:
    name_lower = game_name.lower().strip()
    steam_path = _find_steam_path()
    if steam_path:
        for g in _get_steam_games(steam_path):
            if name_lower in g["name"].lower():
                return g["id"], g["name"]
    if name_lower in _KNOWN_APPIDS:
        app_id, canonical = _KNOWN_APPIDS[name_lower]
        return app_id, canonical
    for key, (app_id, canonical) in _KNOWN_APPIDS.items():
        if name_lower in key or key in name_lower:
            return app_id, canonical
    try:
        import urllib.request, urllib.parse
        query = urllib.parse.quote(game_name)
        url   = f"https://store.steampowered.com/api/storesearch/?term={query}&l=english&cc=US"
        req   = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            items = json.loads(resp.read().decode()).get("items", [])
        if items:
            best = items[0]
            return str(best["id"]), best["name"]
    except Exception as e:
        print(f"[GameUpdater] ⚠️ AppID search failed: {e}")
    return None, None


def _install_steam_game(steam_path: Path, game_name: str = None, app_id: str = None) -> str:
    if not _ensure_steam_running(steam_path):
        return "Could not start Steam."

    installed_games = _get_steam_games(steam_path)
    already = None
    if app_id:
        already = next((g for g in installed_games if g["id"] == str(app_id)), None)
    elif game_name:
        name_lower = game_name.lower()
        already    = next((g for g in installed_games if name_lower in g["name"].lower()), None)
    else:
        return "Please specify a game name or AppID."

    if already:
        state = already["state"]
        name  = already["name"]
        if state == 4:
            return f"'{name}' is already installed and up to date."
        if state == 1026:
            return f"'{name}' is currently downloading or updating."
        return f"'{name}' is already installed."

    if not app_id and game_name:
        found_id, found_name = _search_steam_appid(game_name)
        if not found_id:
            return f"Could not find '{game_name}' on Steam."
        app_id    = found_id
        game_name = found_name or game_name

    try:
        _launch_steam_url(steam_path, f"steam://install/{app_id}")
        return f"Install started for '{game_name}'. Please confirm in Steam."
    except Exception as e:
        return f"Install failed: {e}"


def _get_download_status(steam_path: Path) -> str:
    games   = _get_steam_games(steam_path)
    active  = [g for g in games if g["state"] == 1026]
    pending = [g for g in games if g["state"] in (6, 516)]
    lines   = []
    if active:
        lines.append(f"Downloading: {', '.join(g['name'] for g in active)}.")
    if pending:
        names  = ", ".join(g["name"] for g in pending[:5])
        suffix = f" and {len(pending) - 5} more" if len(pending) > 5 else ""
        lines.append(f"Pending updates: {names}{suffix}.")
    return " ".join(lines) if lines else "No active downloads or pending updates."


def _watch_and_shutdown(steam_path: Path, speak=None, check_interval: int = 30, timeout_hours: int = 12):
    print("[GameUpdater] 👁️ Watching downloads for shutdown...")
    deadline = time.time() + timeout_hours * 3600
    for _ in range(24):
        time.sleep(5)
        active = [g for g in _get_steam_games(steam_path) if g["state"] == 1026]
        if active:
            names = ", ".join(g["name"] for g in active)
            if speak: speak(f"Download started for {names}. I'll shut down when done.")
            break
    else:
        return
    while time.time() < deadline:
        time.sleep(check_interval)
        if not any(g["state"] == 1026 for g in _get_steam_games(steam_path)):
            if speak: speak("Download complete. Shutting down now.")
            time.sleep(5)
            subprocess.run(["osascript", "-e", 'tell application "System Events" to shut down'])
            return
    if speak: speak("Download taking too long. Cancelling auto-shutdown.")


def _schedule_daily_update(hour: int = 3, minute: int = 0) -> str:
    """Schedule via launchd plist on macOS."""
    label       = "com.mark.gameupdater"
    plist_path  = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    script_path = Path(__file__).resolve()

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>{script_path}</string>
    <string>--scheduled</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>{hour}</integer>
    <key>Minute</key>
    <integer>{minute}</integer>
  </dict>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>"""

    try:
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist)
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        subprocess.run(["launchctl", "load",   str(plist_path)], check=True, capture_output=True)
        return f"Daily game update scheduled at {hour:02d}:{minute:02d}."
    except Exception as e:
        return f"Scheduling failed: {e}"


def _cancel_scheduled_update() -> str:
    label      = "com.mark.gameupdater"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    try:
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        plist_path.unlink(missing_ok=True)
        return "Scheduled update cancelled."
    except Exception:
        return "No scheduled update found."


def _get_schedule_status() -> str:
    label = "com.mark.gameupdater"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if plist.exists():
        return "Game update is scheduled via launchd."
    return "No scheduled game update found."


def game_updater(parameters: dict, player=None, speak=None) -> str:
    p         = parameters or {}
    action    = p.get("action",    "update").lower().strip()
    platform  = p.get("platform",  "both").lower().strip()
    game_name = (p.get("game_name") or "").strip() or None
    app_id    = (p.get("app_id")    or "").strip() or None
    hour      = int(p.get("hour",   3))
    minute    = int(p.get("minute", 0))
    shutdown  = str(p.get("shutdown_when_done", "false")).lower() == "true"

    results = []

    if action == "schedule":        return _schedule_daily_update(hour=hour, minute=minute)
    if action == "cancel_schedule": return _cancel_scheduled_update()
    if action == "schedule_status": return _get_schedule_status()

    if action == "list":
        if platform in ("steam", "both"):
            steam_path = _find_steam_path()
            if steam_path:
                games = _get_steam_games(steam_path)
                if games:
                    names  = ", ".join(g["name"] for g in games[:8])
                    suffix = f" and {len(games) - 8} more" if len(games) > 8 else ""
                    results.append(f"Steam ({len(games)} games): {names}{suffix}.")
                else:
                    results.append("Steam: No games found.")
            else:
                results.append("Steam: Not installed.")
        if platform in ("epic", "both"):
            results.append("Epic Games: Limited macOS support. Please open the Epic launcher manually.")
        return " | ".join(results) or "No platforms found."

    if action == "download_status":
        if platform in ("steam", "both"):
            steam_path = _find_steam_path()
            results.append(_get_download_status(steam_path) if steam_path else "Steam: Not installed.")
        return " ".join(results)

    if action in ("install", "update"):
        if platform in ("steam", "both"):
            steam_path = _find_steam_path()
            if not steam_path:
                results.append("Steam: Not installed.")
            else:
                if game_name:
                    installed    = _get_steam_games(steam_path)
                    name_lower   = game_name.lower()
                    is_installed = any(name_lower in g["name"].lower() for g in installed)
                    if not is_installed:
                        msg = _install_steam_game(steam_path, game_name=game_name, app_id=app_id)
                        if shutdown:
                            threading.Thread(target=_watch_and_shutdown,
                                             kwargs={"steam_path": steam_path, "speak": speak},
                                             daemon=True).start()
                            msg += " Auto-shutdown enabled."
                        if player: player.write_log(f"[GameUpdater] {msg[:100]}")
                        if speak:  speak(msg)
                        return msg
                    else:
                        results.append(f"Steam: {_update_steam_games(steam_path, game_name=game_name)}")
                else:
                    if action == "install":
                        results.append("Steam: Please specify a game name to install.")
                    else:
                        results.append(f"Steam: {_update_steam_games(steam_path)}")

                if shutdown:
                    threading.Thread(target=_watch_and_shutdown,
                                     kwargs={"steam_path": steam_path, "speak": speak},
                                     daemon=True).start()
                    results.append("Auto-shutdown enabled.")

        if platform in ("epic", "both"):
            results.append("Epic Games: Limited macOS support. Please open the Epic launcher manually.")

        output = " | ".join(results) or "Nothing to do."
        if player: player.write_log(f"[GameUpdater] {output[:100]}")
        if speak:  speak(output)
        return output

    return f"Unknown action: '{action}'."


if __name__ == "__main__":
    if "--scheduled" in sys.argv:
        print(f"[GameUpdater] 🕐 Scheduled run at {datetime.now().strftime('%H:%M')}")
        print(f"[GameUpdater] ✅ {game_updater({'action': 'update', 'platform': 'steam'})}")
