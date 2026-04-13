import json
import re
import sys
import os
os.environ.setdefault("GRPC_POLL_STRATEGY", "poll")
import time
import subprocess
import platform
import urllib.parse
import threading
from pathlib import Path

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


# ── Persistent Playwright browser ─────────────────────────────────────────
_pw_instance  = None
_pw_browser   = None
_pw_lock      = threading.Lock()


def _get_browser():
    """Return a persistent Playwright browser (creates once, reuses forever)."""
    global _pw_instance, _pw_browser
    with _pw_lock:
        if _pw_browser is None or not _pw_browser.is_connected():
            from playwright.sync_api import sync_playwright
            if _pw_instance:
                try: _pw_instance.stop()
                except Exception: pass
            _pw_instance = sync_playwright().start()
            _pw_browser  = _pw_instance.chromium.launch(
                headless=False,
                args=["--autoplay-policy=no-user-gesture-required",
                      "--disable-features=PreloadMediaEngagementData",
                      "--no-first-run"],
            )
            print("[YouTube] 🌐 Persistent browser started")
        return _pw_browser


def _play_with_playwright(query: str, use_music: bool = False) -> str:
    """
    Open YouTube / YT Music in a persistent browser and autoplay the first result.
    The browser stays open so every call is fast.
    """
    try:
        browser = _get_browser()
        ctx     = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=HEADERS["User-Agent"],
        )
        page = ctx.new_page()

        # ── YouTube Music ────────────────────────────────────────────
        if use_music:
            search_url = f"https://music.youtube.com/search?q={urllib.parse.quote(query)}"
            print(f"[YouTube] 🎵 YT Music: {search_url}")
            page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
            time.sleep(2.5)

            # Try clicking the first song in results
            music_selectors = [
                "ytmusic-responsive-list-item-renderer",
                "ytmusic-shelf-renderer ytmusic-responsive-list-item-renderer",
                ".ytmusic-responsive-list-item-renderer",
                "ytmusic-card-shelf-renderer ytmusic-responsive-list-item-renderer",
            ]
            for sel in music_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click()
                        print(f"[YouTube] ✅ YT Music clicked via '{sel}'")
                        time.sleep(1)
                        return f"Playing '{query}' on YouTube Music."
                except Exception:
                    continue

            # Fallback: press Enter on search
            try:
                page.keyboard.press("Enter")
                time.sleep(2)
                el = page.query_selector("ytmusic-responsive-list-item-renderer")
                if el:
                    el.click()
                    return f"Playing '{query}' on YouTube Music."
            except Exception:
                pass

            return f"Opened YouTube Music for: {query}"

        # ── YouTube.com ──────────────────────────────────────────────
        else:
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            print(f"[YouTube] ▶️  YT Search: {search_url}")
            page.goto(search_url, timeout=25000, wait_until="domcontentloaded")

            # Wait for video renderer elements to appear in DOM
            try:
                page.wait_for_selector("ytd-video-renderer", timeout=12000)
            except Exception:
                print("[YouTube] ⚠️ ytd-video-renderer timeout — trying anyway")

            time.sleep(1.5)

            # Priority selector list — try each until one works
            selectors = [
                # title text link of first video
                "ytd-video-renderer:first-of-type #video-title",
                # thumbnail link
                "ytd-video-renderer:first-of-type a#thumbnail",
                # any watch link
                "a#thumbnail[href^='/watch']",
                # broader fallback
                "#contents ytd-video-renderer #video-title",
                "#contents ytd-video-renderer a#thumbnail",
            ]

            for sel in selectors:
                try:
                    # Use query_selector_all and pick first visible one
                    els = page.query_selector_all(sel)
                    for el in els:
                        if el and el.is_visible():
                            el.scroll_into_view_if_needed()
                            el.click()
                            print(f"[YouTube] ✅ Clicked via '{sel}'")
                            time.sleep(1.5)
                            return f"Playing '{query}' on YouTube."
                except Exception as ex:
                    print(f"[YouTube] sel '{sel}' failed: {ex}")
                    continue

            # Nuclear fallback: evaluate JS to click first video title
            try:
                page.evaluate("""
                    () => {
                        const titles = document.querySelectorAll('ytd-video-renderer #video-title');
                        for (const t of titles) {
                            if (t.offsetParent !== null) { t.click(); break; }
                        }
                    }
                """)
                time.sleep(1.5)
                return f"Playing '{query}' on YouTube (JS click)."
            except Exception as e2:
                print(f"[YouTube] JS click failed: {e2}")

            return f"Opened YouTube search for: {query} — page loaded but could not auto-click"

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[YouTube] ❌ Playwright error: {e}")
        # Fallback: open in system browser
        url = (f"https://music.youtube.com/search?q={urllib.parse.quote(query)}"
               if use_music else
               f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}")
        _open_url_in_browser(url)
        return f"Opened YouTube in system browser for: {query}"


def _handle_play(parameters: dict, player=None) -> str:
    query     = (parameters.get("query") or "").strip()
    q_lower   = query.lower()
    url_lower = (parameters.get("url") or "").lower()
    # Detect YouTube Music request
    use_music = (
        "youtube music" in q_lower or
        "ytmusic" in q_lower or
        "music.youtube" in url_lower or
        "on music" in q_lower or
        "yt music" in q_lower
    )
    # Strip "on youtube music" / "on music" from query so search is clean
    for strip in ["on youtube music", "on yt music", "youtube music", "on music"]:
        query = query.replace(strip, "").replace(strip.title(), "").strip()
    if not query:
        query = (parameters.get("query") or "").strip()

    if not query:
        return "Please tell me what you'd like to play, sir."

    if player:
        player.write_log(f"[YouTube] Playing: {query}")

    print(f"[YouTube] ▶️  Play: '{query}'  music={use_music}")
    return _play_with_playwright(query, use_music=use_music)


def _extract_video_id(url: str):
    patterns = [r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})"]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def _is_valid_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))


def _ask_for_url(prompt_text: str = "YouTube video URL:"):
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
        url = simpledialog.askstring("J.A.R.V.I.S", prompt_text, parent=root)
        return url.strip() if url else None
    except Exception as e:
        print(f"[YouTube] ⚠️ URL dialog failed: {e}")
        return None


def _get_transcript(video_id: str):
    if not _TRANSCRIPT_OK:
        return None
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        try:
            transcript = transcript_list.find_manually_created_transcript(
                ["en", "tr", "de", "fr", "es", "it", "pt", "ru", "ja", "ko", "ar", "zh"]
            )
        except Exception:
            pass
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(
                    ["en", "tr", "de", "fr", "es", "it", "pt", "ru", "ja", "ko", "ar", "zh"]
                )
            except Exception:
                for t in transcript_list:
                    transcript = t
                    break
        if transcript is None:
            return None
        fetched = transcript.fetch()
        return " ".join(entry["text"] for entry in fetched)
    except Exception as e:
        print(f"[YouTube] ⚠️ Transcript fetch failed: {e}")
        return None


def _summarize_with_gemini(transcript: str, video_url: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=(
            "You are JARVIS, Tony Stark's AI assistant. "
            "Summarize YouTube video transcripts clearly and concisely. "
            "Structure: 1-sentence overview, then 3-5 key points. "
            "Be direct. Address the user as 'sir'. "
            "Match the language of the transcript."
        )
    )
    max_chars = 80000
    truncated = transcript[:max_chars] + ("..." if len(transcript) > max_chars else "")
    response  = model.generate_content(
        f"Please summarize this YouTube video transcript:\n\n{truncated}"
    )
    return response.text.strip()


def _save_summary(content: str, video_url: str) -> str:
    from datetime import datetime
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"youtube_summary_{ts}.txt"
    desktop  = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    filepath = desktop / filename
    header = (
        f"JARVIS — YouTube Summary\n"
        f"{'─' * 50}\n"
        f"URL    : {video_url}\n"
        f"Date   : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'─' * 50}\n\n"
    )
    filepath.write_text(header + content, encoding="utf-8")
    subprocess.Popen(["open", "-t", str(filepath)])
    return str(filepath)


def _scrape_video_info(video_id: str) -> dict:
    if not _REQUESTS_OK:
        return {}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        info = {}
        for key, pattern in [
            ("title",    r'"title":\{"runs":\[\{"text":"([^"]+)"'),
            ("channel",  r'"ownerChannelName":"([^"]+)"'),
            ("views",    r'"viewCount":"(\d+)"'),
            ("duration", r'"lengthSeconds":"(\d+)"'),
        ]:
            m = re.search(pattern, html)
            if m:
                val = m.group(1)
                if key == "views":
                    val = f"{int(val):,}"
                elif key == "duration":
                    secs = int(val)
                    val  = f"{secs // 60}:{secs % 60:02d}"
                info[key] = val
        return info
    except Exception as e:
        print(f"[YouTube] ⚠️ Info scrape failed: {e}")
        return {}


def _scrape_trending(region: str = "US", max_results: int = 8) -> list:
    if not _REQUESTS_OK:
        return []
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        r       = requests.get(url, headers=HEADERS, timeout=12)
        html    = r.text
        titles  = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]\}', html)
        channels= re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)
        results, seen = [], set()
        for i, title in enumerate(titles):
            if title in seen or len(title) < 5:
                continue
            seen.add(title)
            channel = channels[i] if i < len(channels) else "Unknown"
            results.append({"rank": len(results) + 1, "title": title, "channel": channel})
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"[YouTube] ⚠️ Trending scrape failed: {e}")
        return []


def _handle_summarize(parameters: dict, player=None, speak=None) -> str:
    if not _TRANSCRIPT_OK:
        return "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"
    url = _ask_for_url("Please paste the YouTube video URL:")
    if not url:
        return "No URL provided, sir. Summary cancelled."
    if not _is_valid_youtube_url(url):
        return "That doesn't appear to be a valid YouTube URL, sir."
    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from that URL, sir."
    if player:
        player.write_log(f"[YouTube] Summarizing: {url}")
    if speak:
        speak("Fetching the transcript now, sir. One moment.")
    transcript = _get_transcript(video_id)
    if not transcript:
        return "I couldn't retrieve a transcript for that video, sir."
    if speak:
        speak("Transcript retrieved. Generating summary now.")
    try:
        summary = _summarize_with_gemini(transcript, url)
    except Exception as e:
        return f"Summary generation failed, sir: {e}"
    if speak:
        speak(summary)
    if parameters.get("save"):
        saved = _save_summary(summary, url)
        return f"Summary complete and saved to Desktop: {saved}"
    return summary


def _handle_get_info(parameters: dict, player=None, speak=None) -> str:
    url = parameters.get("url", "").strip()
    if not url:
        url = _ask_for_url("Please paste the YouTube video URL:")
    if not url or not _is_valid_youtube_url(url):
        return "Please provide a valid YouTube URL, sir."
    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID, sir."
    if player:
        player.write_log(f"[YouTube] Getting info: {url}")
    info = _scrape_video_info(video_id)
    if not info:
        return "Could not retrieve video information, sir."
    lines = [f"{k.capitalize()}: {v}" for k, v in info.items()]
    result = "\n".join(lines)
    if speak:
        speak(f"Here is the video info, sir. {result.replace(chr(10), '. ')}")
    return result


def _handle_trending(parameters: dict, player=None, speak=None) -> str:
    region = parameters.get("region", "US").upper()
    if player:
        player.write_log(f"[YouTube] Trending: {region}")
    trending = _scrape_trending(region=region, max_results=8)
    if not trending:
        return f"Could not fetch trending videos for region {region}, sir."
    lines = [f"Top trending videos in {region}:"]
    for item in trending:
        lines.append(f"{item['rank']}. {item['title']} — {item['channel']}")
    result = "\n".join(lines)
    if speak:
        top3   = trending[:3]
        spoken = "Here are the top trending videos, sir. " + ". ".join(
            f"Number {v['rank']}: {v['title']} by {v['channel']}" for v in top3
        )
        speak(spoken)
    return result


_ACTION_MAP = {
    "play":      _handle_play,
    "summarize": _handle_summarize,
    "get_info":  _handle_get_info,
    "trending":  _handle_trending,
}


def youtube_video(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "play").lower().strip()

    if player:
        player.write_log(f"[YouTube] Action: {action}")
    print(f"[YouTube] ▶️ Action: {action}  Params: {params}")

    handler = _ACTION_MAP.get(action)
    if handler is None:
        return f"Unknown YouTube action: '{action}'. Available: play, summarize, get_info, trending."

    try:
        if action == "play":
            return handler(params, player) or "Done."
        return handler(params, player, speak) or "Done."
    except Exception as e:
        print(f"[YouTube] ❌ Error in {action}: {e}")
        import traceback; traceback.print_exc()
        return f"YouTube {action} failed, sir: {e}"
