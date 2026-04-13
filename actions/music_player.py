"""
music_player.py — MARK XXXV Streaming Music Player
====================================================
• Searches YouTube Music (ytmusicapi) — completely free, no ads
• Streams audio via yt-dlp (no download, direct URL extraction)
• Plays via VLC (python-vlc) — best macOS streaming support
• Top-5 live suggestions as you type
• Integrates with JARVIS voice commands
"""
import json
import threading
import time
import traceback
from typing import Callable

# ── Dependency checks ────────────────────────────────────────────────
try:
    from ytmusicapi import YTMusic
    _YTMUSIC_OK = True
except ImportError:
    _YTMUSIC_OK = False
    print("[Music] ⚠️  ytmusicapi not installed — run: pip install ytmusicapi")

try:
    import yt_dlp
    _YTDLP_OK = True
except ImportError:
    _YTDLP_OK = False
    print("[Music] ⚠️  yt-dlp not installed — run: pip install yt-dlp")

try:
    import vlc as _vlc
    _VLC_OK = True
except ImportError:
    _VLC_OK = False
    # VLC needs the VLC app installed: brew install --cask vlc
    print("[Music] ⚠️  python-vlc not installed — run: pip install python-vlc")


# ── YTMusic singleton ────────────────────────────────────────────────
_ytmusic: "YTMusic | None" = None
_ytmusic_lock = threading.Lock()

def _get_ytmusic() -> "YTMusic":
    global _ytmusic
    with _ytmusic_lock:
        if _ytmusic is None:
            _ytmusic = YTMusic()   # unauthenticated — free searches
    return _ytmusic


# ── Search ───────────────────────────────────────────────────────────

def search_songs(query: str, limit: int = 5) -> list[dict]:
    """
    Search YouTube Music for songs. Returns list of:
      {video_id, title, artist, album, duration_sec, thumbnail}
    """
    if not _YTMUSIC_OK or not query.strip():
        return []
    try:
        yt = _get_ytmusic()
        results = yt.search(query.strip(), filter="songs", limit=limit)
        out = []
        for r in results[:limit]:
            vid    = r.get("videoId", "")
            title  = r.get("title", "Unknown")
            artists= r.get("artists", [{}])
            artist = artists[0].get("name", "Unknown") if artists else "Unknown"
            album  = (r.get("album") or {}).get("name", "")
            dur    = r.get("duration_seconds") or 0
            thumb  = ""
            thumbs = r.get("thumbnails", [])
            if thumbs:
                thumb = thumbs[-1].get("url", "")
            if vid:
                out.append({
                    "video_id":    vid,
                    "title":       title,
                    "artist":      artist,
                    "album":       album,
                    "duration_sec":int(dur),
                    "thumbnail":   thumb,
                })
        return out
    except Exception as e:
        print(f"[Music] ⚠️  search error: {e}")
        return []


def get_stream_url(video_id: str) -> dict:
    """
    Extract direct audio stream URL using yt-dlp (no download).
    Returns {url, title, artist, ext} or {error}.
    """
    if not _YTDLP_OK:
        return {"error": "yt-dlp not installed"}

    ydl_opts = {
        "format":       "bestaudio[ext=webm]/bestaudio/best",
        "quiet":        True,
        "no_warnings":  True,
        "extract_flat": False,
        # Force skipping geo-restricted content gracefully
        "geo_bypass":   True,
    }
    try:
        yt_url = f"https://music.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)

        # Find best audio-only URL
        audio_url = None
        ext       = "webm"

        if "url" in info:
            audio_url = info["url"]
            ext       = info.get("ext", "webm")
        elif "formats" in info:
            # Prefer audio-only formats (vcodec=none)
            audio_fmts = [
                f for f in info["formats"]
                if f.get("acodec", "none") != "none"
                and f.get("vcodec", "none") == "none"
                and f.get("url")
            ]
            if not audio_fmts:
                audio_fmts = [f for f in info["formats"] if f.get("url")]
            if audio_fmts:
                # Sort by audio bitrate descending
                audio_fmts.sort(key=lambda f: f.get("abr") or 0, reverse=True)
                best = audio_fmts[0]
                audio_url = best["url"]
                ext       = best.get("ext", "webm")

        if not audio_url:
            return {"error": "Could not extract audio URL"}

        return {
            "url":    audio_url,
            "title":  info.get("title", ""),
            "artist": info.get("artist") or info.get("uploader", ""),
            "ext":    ext,
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)[:120]}


# ── VLC Player ───────────────────────────────────────────────────────

class StreamPlayer:
    """
    Thin wrapper around python-vlc for streaming audio.
    Falls back to subprocess afplay for simple cases if VLC unavailable.
    """

    def __init__(self):
        self._instance   = None
        self._player     = None
        self._lock       = threading.Lock()
        self._volume     = 70          # 0-100
        self._is_playing = False
        self._is_paused  = False
        self._current:   dict | None = None

        # Callbacks wired by UI
        self.on_track_change: Callable | None = None
        self.on_state_change: Callable | None = None
        self.on_end:          Callable | None = None

        if _VLC_OK:
            try:
                self._instance = _vlc.Instance("--no-video", "--quiet")
                self._player   = self._instance.media_player_new()
                em = self._player.event_manager()
                em.event_attach(_vlc.EventType.MediaPlayerEndReached,
                                 self._on_vlc_end)
                print("[Music] ✅ VLC player ready")
            except Exception as e:
                print(f"[Music] ⚠️  VLC init failed: {e}")
                self._instance = None
                self._player   = None

    def _on_vlc_end(self, event):
        self._is_playing = False
        if self.on_end:
            threading.Thread(target=self.on_end, daemon=True).start()

    def play_url(self, url: str, meta: dict) -> str:
        """Stream audio from a direct URL."""
        with self._lock:
            if self._player:
                media = self._instance.media_new(url)
                self._player.set_media(media)
                self._player.audio_set_volume(self._volume)
                self._player.play()
                self._is_playing = True
                self._is_paused  = False
                self._current    = meta
            else:
                # Fallback: macOS afplay (supports http streams)
                import subprocess
                subprocess.Popen(["afplay", url])
                self._is_playing = True
                self._current    = meta

        if self.on_track_change:
            threading.Thread(target=self.on_track_change, args=(meta,), daemon=True).start()
        if self.on_state_change:
            threading.Thread(target=self.on_state_change, args=(True, False), daemon=True).start()
        return f"Playing: {meta.get('title','?')} — {meta.get('artist','?')}"

    def pause_resume(self) -> str:
        with self._lock:
            if not self._player:
                return "No player available"
            if self._is_paused:
                self._player.play()
                self._is_paused  = False
                self._is_playing = True
                state = "Resumed"
            else:
                self._player.pause()
                self._is_paused  = True
                state = "Paused"
        if self.on_state_change:
            threading.Thread(target=self.on_state_change,
                             args=(self._is_playing, self._is_paused), daemon=True).start()
        return state

    def stop(self) -> str:
        with self._lock:
            if self._player:
                self._player.stop()
            self._is_playing = False
            self._is_paused  = False
        if self.on_state_change:
            threading.Thread(target=self.on_state_change, args=(False, False), daemon=True).start()
        return "Stopped."

    def set_volume(self, vol: int):
        """vol: 0-100"""
        self._volume = max(0, min(100, vol))
        with self._lock:
            if self._player:
                self._player.audio_set_volume(self._volume)

    def get_position(self) -> tuple[float, float]:
        """Returns (position_sec, duration_sec)"""
        with self._lock:
            if self._player and self._is_playing:
                pos = self._player.get_time() / 1000.0   # ms → sec
                dur = self._player.get_length() / 1000.0
                return max(0, pos), max(0, dur)
        return 0.0, 0.0

    def seek(self, seconds: float):
        with self._lock:
            if self._player:
                self._player.set_time(int(seconds * 1000))

    @property
    def is_playing(self): return self._is_playing and not self._is_paused
    @property
    def is_paused(self):  return self._is_paused
    @property
    def current(self):    return self._current


# ── Playlist manager ─────────────────────────────────────────────────

class MusicPlayer:
    """High-level player: search → stream → playlist."""

    def __init__(self):
        self._stream     = StreamPlayer()
        self._playlist:  list[dict] = []  # list of search result dicts
        self._idx:       int        = 0
        self._lock       = threading.Lock()

        # Wire end-of-track to auto-next
        self._stream.on_end = self._on_track_end

    def _on_track_end(self):
        self._next(auto=True)

    def play_query(self, query: str,
                   on_searching: Callable | None = None,
                   on_done: Callable | None = None) -> None:
        """
        Search + stream in background thread.
        Calls on_searching() before search, on_done(result_str) when done.
        """
        def _worker():
            if on_searching:
                on_searching()
            results = search_songs(query, limit=1)
            if not results:
                if on_done:
                    on_done(f"No results found for '{query}'.")
                return
            track = results[0]
            result = self._stream_track(track)
            if on_done:
                on_done(result)

        threading.Thread(target=_worker, daemon=True).start()

    def play_track(self, track: dict,
                   on_done: Callable | None = None) -> None:
        """Stream a specific track dict from search results."""
        def _worker():
            result = self._stream_track(track)
            if on_done:
                on_done(result)
        threading.Thread(target=_worker, daemon=True).start()

    def _stream_track(self, track: dict) -> str:
        vid = track.get("video_id", "")
        if not vid:
            return "Invalid track — no video ID."
        info = get_stream_url(vid)
        if "error" in info:
            return f"Stream error: {info['error']}"
        meta = {
            "title":    track.get("title",  info.get("title",  "Unknown")),
            "artist":   track.get("artist", info.get("artist", "Unknown")),
            "album":    track.get("album",  ""),
            "video_id": vid,
            "duration": track.get("duration_sec", 0),
        }
        return self._stream.play_url(info["url"], meta)

    def pause_resume(self) -> str:
        return self._stream.pause_resume()

    def stop(self) -> str:
        return self._stream.stop()

    def _next(self, auto=False) -> str:
        with self._lock:
            if not self._playlist:
                return "No playlist."
            self._idx = (self._idx + 1) % len(self._playlist)
            track = self._playlist[self._idx]
        def _w():
            self._stream_track(track)
        threading.Thread(target=_w, daemon=True).start()
        return f"Loading next: {track.get('title','?')}"

    def next_track(self) -> str:
        return self._next()

    def prev_track(self) -> str:
        with self._lock:
            if not self._playlist:
                return "No playlist."
            self._idx = max(0, self._idx - 1)
            track = self._playlist[self._idx]
        def _w():
            self._stream_track(track)
        threading.Thread(target=_w, daemon=True).start()
        return f"Loading: {track.get('title','?')}"

    def set_volume(self, vol: int):
        self._stream.set_volume(vol)

    def set_playlist(self, tracks: list[dict]):
        with self._lock:
            self._playlist = tracks
            self._idx      = 0

    def get_position(self):
        return self._stream.get_position()

    def seek(self, sec: float):
        self._stream.seek(sec)

    # Expose stream callbacks
    @property
    def on_track_change(self):
        return self._stream.on_track_change
    @on_track_change.setter
    def on_track_change(self, v):
        self._stream.on_track_change = v

    @property
    def on_state_change(self):
        return self._stream.on_state_change
    @on_state_change.setter
    def on_state_change(self, v):
        self._stream.on_state_change = v

    @property
    def current(self):
        return self._stream.current

    @property
    def is_playing(self):
        return self._stream.is_playing

    @property
    def is_paused(self):
        return self._stream.is_paused


# ── Singleton ─────────────────────────────────────────────────────────
_player = MusicPlayer()

def get_player() -> MusicPlayer:
    return _player


# ── JARVIS tool function ──────────────────────────────────────────────

def music_control(parameters: dict, player=None, speak: Callable | None = None) -> str:
    """
    Called by JARVIS tool dispatcher.
    actions: play | pause | stop | next | prev | volume | search
    """
    action = (parameters.get("action") or "play").lower().strip()
    query  =  parameters.get("query",  "").strip()
    vol    =  parameters.get("volume")

    p = get_player()

    def _say(msg):
        if speak:
            try:
                speak(msg)
            except Exception:
                pass
        if player:
            try:
                player.write_log(f"SYS: {msg}")
            except Exception:
                pass

    if action in ("play", "search_and_play"):
        if not query:
            return "Please tell me what song to play, sir."
        _say(f"Searching for {query}...")
        # Update UI now-playing label
        if player and hasattr(player, "update_now_playing"):
            player.update_now_playing(f"Searching: {query}...")
        def _on_done(r):
            _say(r)
        p.play_query(
            query,
            on_searching=lambda: _say(f"Finding {query} on YouTube Music..."),
            on_done=_on_done,
        )
        return f"Searching and streaming '{query}'."

    if action in ("pause", "resume", "toggle"):
        result = p.pause_resume()
        return result

    if action == "stop":
        return p.stop()

    if action == "next":
        return p.next_track()

    if action in ("prev", "previous"):
        return p.prev_track()

    if action == "volume" and vol is not None:
        p.set_volume(int(vol))
        return f"Volume set to {vol}%."

    if action == "search":
        if not query:
            return "What song are you looking for, sir?"
        results = search_songs(query, limit=5)
        if not results:
            return f"No results for '{query}'."
        lines = [f"{i+1}. {r['title']} — {r['artist']}" for i, r in enumerate(results)]
        return "Top results:\n" + "\n".join(lines)

    if action == "add_to_playlist":
        if not query:
            return "What song shall I add to the playlist, sir?"
        results = search_songs(query, limit=1)
        if not results:
            return f"Could not find '{query}' to add."
        track = results[0]
        if player and hasattr(player, "_playlist_tracks"):
            try:
                player._playlist_tracks.append(track)
                player._playlist_listbox.insert("end", f"{track['title']} — {track['artist']}")
            except Exception:
                pass
        return f"Added '{track['title']}' by {track['artist']} to playlist."

    if action == "show_playlist":
        if player and hasattr(player, "_playlist_tracks"):
            tracks = player._playlist_tracks
            if not tracks:
                return "The playlist is empty, sir."
            lines = [f"{i+1}. {t['title']} — {t['artist']}" for i, t in enumerate(tracks)]
            return "Current playlist:\n" + "\n".join(lines)
        return "Playlist not available."

    if action == "clear_playlist":
        if player and hasattr(player, "_playlist_tracks"):
            try:
                player._playlist_tracks = []
                player._playlist_listbox.delete(0, "end")
            except Exception:
                pass
        return "Playlist cleared, sir."

    if action == "play_playlist":
        if player and hasattr(player, "_on_play_playlist"):
            try:
                player.root.after(0, player._on_play_playlist)
                return "Playing playlist, sir."
            except Exception as e:
                return f"Could not play playlist: {e}"
        return "Playlist not available."

    return f"Unknown music action: '{action}'"
