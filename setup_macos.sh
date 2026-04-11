#!/bin/bash
# ============================================================
#  Mark-XXXV — macOS Setup Script (Apple Silicon M3)
#  Run this once before launching for the first time.
# ============================================================

set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   MARK XXXV — macOS Setup               ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# 1. Check for Homebrew
if ! command -v brew &>/dev/null; then
    echo "📦 Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add Homebrew to PATH for Apple Silicon
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "✅ Homebrew found."
fi

# 2. Install PortAudio (required by PyAudio)
if ! brew list portaudio &>/dev/null; then
    echo "📦 Installing PortAudio..."
    brew install portaudio
else
    echo "✅ PortAudio found."
fi

# 3. Create virtual environment
if [ ! -d "venv" ]; then
    echo "🐍 Creating Python virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
echo "✅ Virtual environment active."

# 4. Install Python packages
echo ""
echo "📦 Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. Install Playwright browser
echo ""
echo "🌐 Installing Playwright browser (Chromium)..."
playwright install chromium

# 6. Create config directory if missing
mkdir -p config

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   ✅ Setup Complete!                     ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "⚠️  BEFORE RUNNING — Grant these permissions:"
echo "   System Settings → Privacy & Security:"
echo "   • Accessibility   → add Terminal"
echo "   • Screen Recording → add Terminal"
echo "   • Microphone       → add Terminal"
echo ""
echo "🚀 To run Mark-XXXV:"
echo "   source venv/bin/activate"
echo "   python main.py"
echo ""
