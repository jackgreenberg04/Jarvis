# 🤖 MARK XXXV — macOS Edition (Apple Silicon M3)

This is a macOS-compatible port of Mark-XXXV by FatihMakes.
Original project: https://github.com/FatihMakes/Mark-XXXV

---

## 🚀 Quick Start

### Step 1 — Run the setup script (one time only)
```bash
chmod +x setup_macos.sh
./setup_macos.sh
```

This installs Homebrew, PortAudio, all Python packages, and Playwright.

### Step 2 — Grant macOS Permissions (REQUIRED)
Go to **System Settings → Privacy & Security** and enable these for **Terminal** (or your Python executable):

| Permission | Why |
|---|---|
| **Accessibility** | Keyboard control, window management |
| **Screen Recording** | Screen capture / visual awareness |
| **Microphone** | Voice input |

### Step 3 — Run
```bash
source venv/bin/activate
python main.py
```

Enter your free Gemini API key when prompted.  
Get one at: https://aistudio.google.com/apikey

---

## ✅ Features That Work on macOS

| Feature | Status |
|---|---|
| Voice interaction | ✅ Full |
| Browser control (Playwright) | ✅ Full |
| Web search | ✅ Full |
| Open apps (Spotlight / `open -a`) | ✅ Full |
| File management | ✅ Full |
| Screen capture & analysis | ✅ Full |
| Volume / brightness control | ✅ Full |
| Keyboard shortcuts | ✅ Full (Cmd instead of Ctrl) |
| Wallpaper change | ✅ Full |
| YouTube playback | ✅ Full |
| Weather | ✅ Full |
| Code helper / dev agent | ✅ Full |
| Memory system | ✅ Full |
| Reminders | ✅ Via background thread + macOS notification |
| Send messages (WhatsApp etc.) | ✅ Via Playwright / Spotlight |
| Steam game updates | ✅ Full (macOS Steam supported) |
| Epic Games | ⚠️ Limited (no macOS launcher) |
| Task scheduling | ✅ Via launchd (macOS native) |

---

## 🔧 macOS-Specific Changes Made

1. **`requirements.txt`** — Removed `comtypes`, `pycaw`, `win10toast`, `pywinauto` (Windows-only). Added `sounddevice`.
2. **`actions/reminder.py`** — Replaced Windows Task Scheduler (`schtasks`) with background thread + `osascript` notifications.
3. **`actions/game_updater.py`** — Replaced Windows Registry lookups with macOS filesystem paths (`~/Library/Application Support/Steam`). Schedule via `launchd` plist.
4. **`actions/send_message.py`** — Replaced Windows Search with `open -a` + Spotlight fallback.
5. **`actions/cmd_control.py`** — Replaced Windows commands (`wmic`, `ipconfig`, `tasklist`) with macOS equivalents (`df`, `ps`, `ifconfig`, `top`, etc.).
6. **`actions/desktop.py`** — Replaced `winreg` wallpaper getter with `osascript`.
7. **`agent/executor.py`** — Replaced Windows Registry Desktop path lookup with `Path.home() / "Desktop"`.

---

## ⚠️ Troubleshooting

**PyAudio install fails?**
```bash
brew install portaudio
pip install pyaudio
```

**`pyautogui` accessibility error?**
→ System Settings → Privacy & Security → Accessibility → add Terminal ✓

**Screen capture is black?**
→ System Settings → Privacy & Security → Screen Recording → add Terminal ✓

**Microphone not working?**
→ System Settings → Privacy & Security → Microphone → add Terminal ✓

**`playwright install` fails?**
```bash
pip install playwright
playwright install chromium


rm "config/api_keys.json"

```

# Install Python 3.12 with Tk included
brew install python@3.12
brew install python-tk@3.12

# Delete old venv and recreate with 3.12
deactivate
rm -rf venv
python3.12 -m venv venv
source venv/bin/activate

# Reinstall all packages
pip install -r requirements.txt
playwright install chromium

# Run
python main.py


pip install ytmusicapi yt-dlp python-vlc
brew install --cask vlc   # VLC app required for python-vlc

# Create a symlink to where the Python vlc module looks
sudo mkdir -p /usr/local/lib
sudo ln -s /Applications/VLC.app/Contents/MacOS/lib/libvlccore.dylib /usr/local/lib/libvlccore.dylib
sudo ln -s /Applications/VLC.app/Contents/MacOS/lib/libvlc.dylib /usr/local/lib/libvlc.dylib

Step 3: Install and link the correct libraries
After moving VLC to /Applications, create symlinks for the ARM64 libraries:

bash
# Verify the library is ARM64 (should show "arm64")
file /Applications/VLC.app/Contents/MacOS/lib/libvlccore.dylib

# Create symlinks (no sudo needed if /usr/local/lib exists)
mkdir -p /usr/local/lib
ln -sf /Applications/VLC.app/Contents/MacOS/lib/libvlccore.dylib /usr/local/lib/libvlccore.dylib
ln -sf /Applications/VLC.app/Contents/MacOS/lib/libvlc.dylib /usr/local/lib/libvlc.dylib
Step 4: Reinstall the Python binding and test
bash
pip uninstall python-vlc
pip install python-vlc
python -c "import vlc; print('Success! VLC loaded')"

