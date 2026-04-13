"""
screen_processor.py — macOS version
• Uses gemini-2.0-flash-live-001 (high-quota live model)
• Camera capture: plain cv2.VideoCapture (no CAP_DSHOW)
• Persistent camera mode: keeps cam open for follow-up questions
• Screen capture via mss
"""
import asyncio
import base64
import io
import json
import re
import os
os.environ["OPENCV_AVFOUNDATION_SKIP_AUTH"] = "1"
import sys
import time
import threading
import cv2
import mss
import mss.tools
import sounddevice as sd
import numpy as np
from pathlib import Path

try:
    import PIL.Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from google import genai
from google.genai import types

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

IMG_MAX_W = 640
IMG_MAX_H = 360
JPEG_Q    = 55

SYSTEM_PROMPT = (
    "You are JARVIS from Iron Man movies. "
    "Analyze images with technical precision and intelligence. "
    "Help the user understand what they see — be clear, smart, and practical. "
    "If the user shows you a problem (code, math, error, object), give a solution. "
    "Be concise. Address the user as 'sir'. "
    "If asked a follow-up question about the same scene, remember context."
)


def _get_api_key() -> str:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            keys = json.load(f)
        key = keys.get("gemini_api_key", "")
        if not key:
            raise ValueError("gemini_api_key not found")
        return key
    except Exception as e:
        raise RuntimeError(f"Could not load API key: {e}")


def _get_camera_index() -> int:
    """Detect best camera index on macOS (no CAP_DSHOW)."""
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "camera_index" in cfg:
            return int(cfg["camera_index"])
    except Exception:
        pass

    print("[Camera] 🔍 Auto-detecting camera...")
    found_index = None

    for idx in range(4):
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            cap.release()
            continue
        # Warm up: read a few frames
        for _ in range(5):
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None and frame.mean() > 5:
            found_index = idx
            print(f"[Camera] ✅ Camera found at index {idx}")
            break
        else:
            print(f"[Camera] ⚠️  Index {idx}: no valid frame")

    if found_index is None:
        raise RuntimeError(
            "No camera found. Please go to System Settings → Privacy & Security → Camera "
            "and grant access to Terminal (or your Python runner), then restart."
        )

    # Save to config only on success
    try:
        cfg = {}
        if API_CONFIG_PATH.exists():
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["camera_index"] = found_index
        with open(API_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        print(f"[Camera] 💾 Saved camera index {found_index}")
    except Exception as e:
        print(f"[Camera] ⚠️  Could not save camera index: {e}")

    return found_index


def _to_jpeg(img_bytes: bytes) -> bytes:
    if not _PIL_OK:
        return img_bytes
    img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
    return buf.getvalue()


def _capture_screenshot() -> bytes:
    with mss.mss() as sct:
        shot      = sct.grab(sct.monitors[1])
        png_bytes = mss.tools.to_png(shot.rgb, shot.size)
    return _to_jpeg(png_bytes)


# ── Persistent camera instance ──────────────────────────────────────────────
_camera_cap        = None
_camera_cap_lock   = threading.Lock()
_camera_index      = None


def _get_open_camera() -> cv2.VideoCapture:
    """Return a persistent, already-open camera instance (macOS-safe)."""
    global _camera_cap, _camera_index
    with _camera_cap_lock:
        if _camera_cap is None or not _camera_cap.isOpened():
            _camera_index = _get_camera_index()
            _camera_cap   = cv2.VideoCapture(_camera_index)  # no CAP_DSHOW on macOS
            if not _camera_cap.isOpened():
                raise RuntimeError(f"Camera index {_camera_index} could not be opened.")
            # Warm up
            for _ in range(6):
                _camera_cap.read()
            print(f"[Camera] 📷 Camera {_camera_index} opened (persistent)")
        return _camera_cap


def _capture_camera() -> bytes:
    """Capture one frame from the persistent camera."""
    cap = _get_open_camera()
    with _camera_cap_lock:
        ret, frame = cap.read()
    if not ret or frame is None:
        # Try re-opening once
        with _camera_cap_lock:
            global _camera_cap
            _camera_cap = None
        cap = _get_open_camera()
        with _camera_cap_lock:
            ret, frame = cap.read()
        if not ret or frame is None:
            raise RuntimeError("Could not capture camera frame.")

    if _PIL_OK:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_Q)
        return buf.getvalue()
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    return buf.tobytes()


# ── Live Gemini session for vision Q&A ─────────────────────────────────────

class _LiveSession:

    def __init__(self):
        self._loop:      asyncio.AbstractEventLoop | None = None
        self._thread:    threading.Thread | None          = None
        self._session                                     = None
        self._out_queue: asyncio.Queue | None             = None
        self._audio_in:  asyncio.Queue | None             = None
        self._ready:     threading.Event                  = threading.Event()
        self._player                                      = None
        self._send_lock: asyncio.Lock | None              = None

    def start(self, player=None):
        if self._thread and self._thread.is_alive():
            return
        self._player = player
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="VisionSessionThread"
        )
        self._thread.start()
        ok = self._ready.wait(timeout=20)
        if not ok:
            raise RuntimeError("Vision session did not start within 20s.")
        print("[ScreenProcess] ✅ Vision session ready")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        self._out_queue = asyncio.Queue(maxsize=30)
        self._audio_in  = asyncio.Queue()
        self._send_lock = asyncio.Lock()

        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            system_instruction=SYSTEM_PROMPT,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

        while True:
            try:
                print("[ScreenProcess] 🔌 Vision session connecting...")
                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    self._session = session
                    self._ready.set()
                    print("[ScreenProcess] ✅ Vision session connected")
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._send_loop())
                        tg.create_task(self._recv_loop())
                        tg.create_task(self._play_loop())
            except Exception as e:
                print(f"[ScreenProcess] ⚠️ Disconnected: {e} — reconnecting in 2s...")
                self._session = None
                self._ready.clear()
                await asyncio.sleep(2)
                self._ready.set()

    async def _send_loop(self):
        while True:
            item = await self._out_queue.get()
            if self._session:
                image_bytes, mime_type, user_text = item
                try:
                    b64 = base64.b64encode(image_bytes).decode("utf-8")
                    await self._session.send_client_content(
                        turns={
                            "parts": [
                                {"inline_data": {"mime_type": mime_type, "data": b64}},
                                {"text": user_text}
                            ]
                        },
                        turn_complete=True
                    )
                    print("[ScreenProcess] ✅ Image+question sent")
                except Exception as e:
                    print(f"[ScreenProcess] ⚠️ Send error: {e}")

    async def _recv_loop(self):
        transcript_buf: list[str] = []
        try:
            async for response in self._session.receive():
                if response.data:
                    await self._audio_in.put(response.data)
                sc = response.server_content
                if not sc:
                    continue
                if sc.output_transcription and sc.output_transcription.text:
                    chunk = sc.output_transcription.text.strip()
                    if chunk:
                        transcript_buf.append(chunk)
                if sc.turn_complete:
                    if transcript_buf and self._player:
                        full = re.sub(r'\s+', ' ', " ".join(transcript_buf)).strip()
                        if full:
                            self._player.write_log(f"Jarvis: {full}")
                            print(f"[ScreenProcess] 💬 {full}")
                    transcript_buf = []
        except Exception as e:
            print(f"[ScreenProcess] ⚠️ Recv error: {e}")
            transcript_buf = []
            await asyncio.sleep(0.3)

    async def _play_loop(self):
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                chunk = await self._audio_in.get()
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[ScreenProcess] ❌ Play error: {e}")
            raise
        finally:
            stream.stop()
            stream.close()

    def analyze(self, image_bytes: bytes, mime_type: str, user_text: str):
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(
            self._out_queue.put((image_bytes, mime_type, user_text)),
            self._loop
        )

    def is_ready(self) -> bool:
        return self._session is not None


_live       = _LiveSession()
_started    = False
_start_lock = threading.Lock()


def _ensure_started(player=None):
    global _started
    with _start_lock:
        if not _started:
            _live.start(player=player)
            _started = True
        elif player is not None:
            _live._player = player


def screen_process(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> bool:
    """
    Capture screen or camera and send to Gemini vision for spoken analysis.

    parameters:
        angle  : "screen" | "camera"  (default: "screen")
        text   : the user's question about the image
    """
    user_text = (parameters or {}).get("text") or (parameters or {}).get("user_text", "")
    user_text = (user_text or "").strip()
    if not user_text:
        user_text = "What do you see? Describe it concisely."

    angle = (parameters or {}).get("angle", "screen").lower().strip()
    print(f"[ScreenProcess] angle={angle!r}  text={user_text!r}")

    _ensure_started(player=player)

    try:
        if angle == "camera":
            image_bytes = _capture_camera()
            mime_type   = "image/jpeg"
            print(f"[ScreenProcess] 📷 Camera captured ({len(image_bytes)} bytes)")
        else:
            image_bytes = _capture_screenshot()
            mime_type   = "image/jpeg" if _PIL_OK else "image/png"
            print(f"[ScreenProcess] 🖥️ Screen captured ({len(image_bytes)} bytes)")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[ScreenProcess] ❌ Capture error: {e}")
        if player:
            player.write_log(f"ERR: Camera/screen capture failed: {e}")
        return False

    _live.analyze(image_bytes, mime_type, user_text)
    return True


def warmup_session(player=None):
    try:
        _ensure_started(player=player)
    except Exception as e:
        print(f"[ScreenProcess] ⚠️ Warmup error: {e}")
