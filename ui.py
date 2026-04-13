import os, json, time, math, random, threading
import tkinter as tk
from tkinter import ttk
from collections import deque
from PIL import Image, ImageTk, ImageDraw
import sys
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "MARK XXXV"

C_BG     = "#000000"
C_PRI    = "#00d4ff"
C_MID    = "#007a99"
C_DIM    = "#003344"
C_DIMMER = "#001520"
C_ACC    = "#ff6600"
C_ACC2   = "#ffcc00"
C_TEXT   = "#8ffcff"
C_PANEL  = "#010c10"
C_GREEN  = "#00ff88"
C_RED    = "#ff3333"
C_MUTED  = "#ff3366"
C_MUSIC  = "#aa44ff"


class JarvisUI:
    def __init__(self, face_path, size=None):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S — MARK XXXV")
        self.root.resizable(False, False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        W  = min(sw, 984)
        H  = min(sh, 816)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.root.configure(bg=C_BG)

        self.W = W
        self.H = H

        self.FACE_SZ = min(int(H * 0.50), 380)
        self.FCX     = W // 2
        self.FCY     = int(H * 0.13) + self.FACE_SZ // 2

        # State
        self.speaking     = False
        self.muted        = False
        self.scale        = 1.0
        self.target_scale = 1.0
        self.halo_a       = 60.0
        self.target_halo  = 60.0
        self.last_t       = time.time()
        self.tick         = 0
        self.scan_angle   = 0.0
        self.scan2_angle  = 180.0
        self.rings_spin   = [0.0, 120.0, 240.0]
        self.pulse_r      = [0.0, self.FACE_SZ * 0.26, self.FACE_SZ * 0.52]
        self.status_text  = "INITIALISING"
        self.status_blink = True
        self._jarvis_state = "INITIALISING"

        self.typing_queue    = deque()
        self.is_typing       = False
        self.on_text_command = None

        self._face_pil         = None
        self._has_face         = False
        self._face_scale_cache = None
        self._load_face(face_path)

        # Main canvas
        self.bg = tk.Canvas(self.root, width=W, height=H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)

        # Log area
        LW    = int(W * 0.62)
        LH    = 100
        LOG_Y = H - LH - 78
        self.log_frame = tk.Frame(self.root, bg=C_PANEL,
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=(W - LW) // 2, y=LOG_Y, width=LW, height=LH)
        self.log_text = tk.Text(self.log_frame, fg=C_TEXT, bg=C_PANEL,
                                insertbackground=C_TEXT, borderwidth=0,
                                wrap="word", font=("Courier", 10), padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#e8e8e8")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_ACC2)
        self.log_text.tag_config("err", foreground=C_RED)

        # Input bar
        INPUT_Y = LOG_Y + LH + 6
        self._build_input_bar(LW, INPUT_Y)

        # Mute button
        self._build_mute_button()

        # Music panel (improved seek bar)
        self._build_music_panel()

        # F4 shortcut
        self.root.bind("<F4>", lambda e: self._toggle_mute())

        # API key
        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))

    # ----------------------------------------------------------------------
    # Mute button
    # ----------------------------------------------------------------------
    def _build_mute_button(self):
        BTN_W, BTN_H = 110, 30
        BTN_X = 18
        BTN_Y = self.H - 66
        self._mute_canvas = tk.Canvas(
            self.root, width=BTN_W, height=BTN_H,
            bg=C_BG, highlightthickness=0, cursor="hand2"
        )
        self._mute_canvas.place(x=BTN_X, y=BTN_Y)
        self._mute_canvas.bind("<Button-1>", lambda e: self._toggle_mute())
        self._draw_mute_button()

    def _draw_mute_button(self):
        c = self._mute_canvas
        c.delete("all")
        if self.muted:
            border, fill, icon, label, fg = C_MUTED, "#1a0008", "🔇", " MUTED", C_MUTED
        else:
            border, fill, icon, label, fg = C_MID, C_PANEL, "🎙", " LIVE", C_GREEN
        c.create_rectangle(0, 0, 110, 30, outline=border, fill=fill, width=1)
        c.create_text(55, 15, text=f"{icon}{label}",
                      fill=fg, font=("Courier", 10, "bold"))

    def _toggle_mute(self):
        self.muted = not self.muted
        self._draw_mute_button()
        if self.muted:
            self.set_state("MUTED")
            self.write_log("SYS: Microphone muted.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: Microphone active.")

    # ----------------------------------------------------------------------
    # Input bar
    # ----------------------------------------------------------------------
    def _build_input_bar(self, lw: int, y: int):
        x0    = (self.W - lw) // 2
        BTN_W = 70
        INP_W = lw - BTN_W - 4
        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            self.root, textvariable=self._input_var,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=("Courier", 10),
            highlightthickness=1, highlightbackground=C_DIM, highlightcolor=C_PRI,
        )
        self._input_entry.place(x=x0, y=y, width=INP_W, height=28)
        self._input_entry.bind("<Return>",   self._on_input_submit)
        self._input_entry.bind("<KP_Enter>", self._on_input_submit)
        self._send_btn = tk.Button(
            self.root, text="SEND ▸", command=self._on_input_submit,
            fg=C_PRI, bg=C_PANEL,
            activeforeground=C_BG, activebackground=C_PRI,
            font=("Courier", 9, "bold"), borderwidth=0, cursor="hand2",
            highlightthickness=1, highlightbackground=C_MID,
        )
        self._send_btn.place(x=x0 + INP_W + 4, y=y, width=BTN_W, height=28)

    def _on_input_submit(self, event=None):
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")
        self.write_log(f"You: {text}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()

    # ----------------------------------------------------------------------
    # Music panel – IMPROVED SEEK BAR
    # ----------------------------------------------------------------------
    def _build_music_panel(self):
        PW  = 220
        PH  = 520
        PX  = self.W - PW - 12
        PY  = 68

        self._music_frame = tk.Frame(
            self.root, bg="#00050a",
            highlightbackground=C_MUSIC, highlightthickness=1
        )
        self._music_frame.place(x=PX, y=PY, width=PW, height=PH)

        # Header
        header = tk.Label(
            self._music_frame, text="♪  MUSIC PLAYER",
            fg=C_MUSIC, bg="#00050a", font=("Courier", 10, "bold")
        )
        header.pack(pady=(8, 4))

        # Now playing
        self._now_playing_var = tk.StringVar(value="— Not Playing —")
        now_label = tk.Label(
            self._music_frame, textvariable=self._now_playing_var,
            fg=C_PRI, bg="#00050a", font=("Courier", 9, "bold"),
            wraplength=200, justify="center"
        )
        now_label.pack(padx=6, pady=(2, 6))

        # ---- Seek slider + time labels (improved) ----
        seek_frame = tk.Frame(self._music_frame, bg="#00050a")
        seek_frame.pack(fill="x", padx=10, pady=(0, 4))

        # Variable to store current position (seconds)
        self._seek_var = tk.DoubleVar(value=0)
        self._seek_slider = tk.Scale(
            seek_frame, variable=self._seek_var, from_=0, to=100,
            orient="horizontal", bg="#00050a", fg=C_MUSIC,
            troughcolor="#001020", highlightthickness=0,
            sliderlength=14, length=PW-20,
            command=self._on_seek
        )
        self._seek_slider.pack(fill="x", pady=(0, 2))

        # Flags to avoid feedback while user drags
        self._seeking = False
        self._seek_update_pending = False

        time_frame = tk.Frame(self._music_frame, bg="#00050a")
        time_frame.pack(fill="x", padx=10, pady=(0, 8))

        self._current_time_var = tk.StringVar(value="0:00")
        self._total_time_var   = tk.StringVar(value="0:00")

        tk.Label(time_frame, textvariable=self._current_time_var,
                 fg=C_DIM, bg="#00050a", font=("Courier", 8)).pack(side="left")
        tk.Label(time_frame, textvariable=self._total_time_var,
                 fg=C_DIM, bg="#00050a", font=("Courier", 8)).pack(side="right")

        # Search box
        search_row = tk.Frame(self._music_frame, bg="#00050a")
        search_row.pack(fill="x", padx=8, pady=(0, 2))

        self._music_search_var = tk.StringVar()
        self._music_search_entry = tk.Entry(
            search_row, textvariable=self._music_search_var,
            fg=C_TEXT, bg="#000812", insertbackground=C_TEXT,
            borderwidth=0, font=("Courier", 9),
            highlightthickness=1, highlightbackground=C_DIM
        )
        self._music_search_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self._music_search_entry.bind("<Return>", self._on_music_search)

        tk.Button(
            search_row, text="🔍", command=self._on_music_search,
            fg=C_MUSIC, bg="#000812", font=("Courier", 9),
            borderwidth=0, cursor="hand2", padx=4
        ).pack(side="left", padx=(2, 0))

        # Search results
        tk.Label(self._music_frame, text="SEARCH RESULTS",
                 fg=C_DIM, bg="#00050a", font=("Courier", 7)).pack(pady=(4, 0))

        results_frame = tk.Frame(self._music_frame, bg="#00050a")
        results_frame.pack(fill="x", padx=8, pady=(2, 6))

        results_scroll = tk.Scrollbar(results_frame, orient="vertical")
        self._results_listbox = tk.Listbox(
            results_frame, height=4,
            fg=C_TEXT, bg="#000510", selectbackground=C_MUSIC,
            selectforeground=C_BG, font=("Courier", 8),
            borderwidth=0, highlightthickness=0,
            yscrollcommand=results_scroll.set, activestyle="none"
        )
        results_scroll.config(command=self._results_listbox.yview)
        self._results_listbox.pack(side="left", fill="x", expand=True)
        results_scroll.pack(side="right", fill="y")
        self._results_listbox.bind("<Double-Button-1>", self._on_play_result)
        self._results_listbox.bind("<Return>", self._on_play_result)

        self._search_results = []

        # Transport controls
        ctrl_row = tk.Frame(self._music_frame, bg="#00050a")
        ctrl_row.pack(pady=(4, 6))

        btn_cfg = dict(bg="#000812", fg=C_MUSIC, font=("Courier", 12),
                       borderwidth=0, cursor="hand2", padx=6, pady=2)

        tk.Button(ctrl_row, text="⏮", command=self._on_prev, **btn_cfg).pack(side="left", padx=2)
        self._play_btn = tk.Button(ctrl_row, text="▶", command=self._on_play_pause, **btn_cfg)
        self._play_btn.pack(side="left", padx=2)
        tk.Button(ctrl_row, text="⏭", command=self._on_next, **btn_cfg).pack(side="left", padx=2)
        tk.Button(ctrl_row, text="⏹", command=self._on_stop, **btn_cfg).pack(side="left", padx=2)

        # Volume slider
        vol_row = tk.Frame(self._music_frame, bg="#00050a")
        vol_row.pack(fill="x", padx=10, pady=(0, 6))

        tk.Label(vol_row, text="🔉", fg=C_DIM, bg="#00050a",
                 font=("Courier", 10)).pack(side="left", padx=(0, 4))

        self._vol_var = tk.IntVar(value=70)
        vol_slider = tk.Scale(
            vol_row, variable=self._vol_var, from_=0, to=100,
            orient="horizontal", bg="#00050a", fg=C_MUSIC,
            troughcolor="#001020", highlightthickness=0,
            showvalue=False, sliderlength=12, length=140,
            command=self._on_volume_change
        )
        vol_slider.pack(side="left", fill="x", expand=True)

        # Playlist
        tk.Label(self._music_frame, text="— PLAYLIST —",
                 fg=C_DIM, bg="#00050a", font=("Courier", 7)).pack(pady=(4, 2))

        playlist_frame = tk.Frame(self._music_frame, bg="#00050a")
        playlist_frame.pack(fill="x", padx=8, pady=(0, 4))

        pl_scroll = tk.Scrollbar(playlist_frame, orient="vertical")
        self._playlist_listbox = tk.Listbox(
            playlist_frame, height=4,
            fg=C_TEXT, bg="#000510", selectbackground="#5500aa",
            selectforeground=C_BG, font=("Courier", 8),
            borderwidth=0, highlightthickness=0,
            yscrollcommand=pl_scroll.set, activestyle="none"
        )
        pl_scroll.config(command=self._playlist_listbox.yview)
        self._playlist_listbox.pack(side="left", fill="x", expand=True)
        pl_scroll.pack(side="right", fill="y")
        self._playlist_listbox.bind("<Double-Button-1>", self._on_play_from_playlist)

        pl_btn_row = tk.Frame(self._music_frame, bg="#00050a")
        pl_btn_row.pack(fill="x", padx=8, pady=(0, 8))

        pl_btn = dict(bg="#001020", fg=C_MUSIC, font=("Courier", 8),
                      borderwidth=0, cursor="hand2", pady=2)

        tk.Button(pl_btn_row, text="+ Add",   command=self._on_add_to_playlist, **pl_btn).pack(side="left", expand=True, fill="x")
        tk.Button(pl_btn_row, text="▶ Play",  command=self._on_play_playlist,   **pl_btn).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(pl_btn_row, text="✕ Clear", command=self._on_clear_playlist,  **pl_btn).pack(side="left", expand=True, fill="x")

        self._playlist_tracks = []
        self._playlist_idx = 0

        # Start position update loop
        self._position_update_id = None
        self._schedule_position_update()

        # Wire music player callbacks
        self._wire_music_callbacks()

    def _wire_music_callbacks(self):
        try:
            from actions.music_player import get_player
            p = get_player()
            p.on_track_change = self._on_track_changed
            p.on_state_change = self._on_player_state_changed
        except Exception as e:
            print(f"[MusicUI] ⚠️ Could not wire player: {e}")

    def _schedule_position_update(self):
        """Periodically update seek slider and time labels."""
        if self._position_update_id:
            self.root.after_cancel(self._position_update_id)
        self._update_seek_slider()
        self._position_update_id = self.root.after(500, self._schedule_position_update)

    def _update_seek_slider(self):
        """Poll player for current position and duration, update UI (unless seeking)."""
        if self._seeking:
            # Skip automatic updates while user is dragging the slider
            self._seek_update_pending = True
            return

        try:
            from actions.music_player import get_player
            p = get_player()
            pos = getattr(p, 'get_position', lambda: 0)()
            dur = getattr(p, 'get_duration', lambda: 0)()

            # Update total time and slider range if duration changed
            if dur and dur > 0:
                current_max = self._seek_slider.cget('to')
                # Avoid frequent reconfigurations – only if different
                if abs(float(current_max) - dur) > 0.5:
                    self._seek_slider.config(to=dur)
                    self._total_time_var.set(self._format_time(dur))

            # Update current position (no command triggered because we set variable)
            if dur and dur > 0:
                # Clamp pos to [0, dur]
                pos = max(0, min(pos, dur))
                self._seek_var.set(pos)
                self._current_time_var.set(self._format_time(pos))
            else:
                # No valid duration – keep slider at 0
                self._seek_var.set(0)
                self._current_time_var.set("0:00")
                # Optionally set total to "0:00"
                self._total_time_var.set("0:00")
        except Exception:
            pass

    def _on_seek(self, value):
        """User dragged the seek slider – seek to new position."""
        try:
            from actions.music_player import get_player
            p = get_player()
            new_pos = float(value)
            # Tell the player to seek
            if hasattr(p, 'seek'):
                p.seek(new_pos)
            # Briefly disable automatic updates to avoid fighting the user
            self._seeking = True
            # Re-enable updates after a short delay (e.g., 300 ms after last drag)
            if hasattr(self, '_seek_after_id'):
                self.root.after_cancel(self._seek_after_id)
            self._seek_after_id = self.root.after(300, self._release_seek)
        except Exception as e:
            print(f"[MusicUI] Seek error: {e}")

    def _release_seek(self):
        """Re‑enable automatic slider updates after user finishes seeking."""
        self._seeking = False
        if self._seek_update_pending:
            self._seek_update_pending = False
            self._update_seek_slider()

    def _format_time(self, seconds):
        """Convert seconds to mm:ss format."""
        if seconds is None or seconds < 0:
            return "0:00"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}:{secs:02d}"

    # ----------------------------------------------------------------------
    # Music panel actions (unchanged, but callbacks improved)
    # ----------------------------------------------------------------------
    def _on_music_search(self, event=None):
        query = self._music_search_var.get().strip()
        if not query:
            return
        self._results_listbox.delete(0, tk.END)
        self._results_listbox.insert(tk.END, "Searching...")
        self.root.update_idletasks()

        def _search():
            try:
                from actions.music_player import search_songs
                results = search_songs(query, limit=5)
                self._search_results = results
                self.root.after(0, self._update_results_listbox, results)
            except Exception as e:
                self.root.after(0, lambda: (
                    self._results_listbox.delete(0, tk.END),
                    self._results_listbox.insert(tk.END, f"Error: {e}")
                ))

        threading.Thread(target=_search, daemon=True).start()

    def _update_results_listbox(self, results):
        self._results_listbox.delete(0, tk.END)
        if not results:
            self._results_listbox.insert(tk.END, "No results found")
            return
        for r in results:
            self._results_listbox.insert(tk.END, f"{r['title']} — {r['artist']}")

    def _on_play_result(self, event=None):
        sel = self._results_listbox.curselection()
        if not sel or not self._search_results:
            return
        idx   = sel[0]
        if idx >= len(self._search_results):
            return
        track = self._search_results[idx]
        self._now_playing_var.set(f"Loading: {track['title']}...")

        def _play():
            try:
                from actions.music_player import get_player
                get_player().play_track(track)
            except Exception as e:
                print(f"[MusicUI] Play error: {e}")

        threading.Thread(target=_play, daemon=True).start()

    def _on_play_pause(self):
        try:
            from actions.music_player import get_player
            p = get_player()
            if p.is_playing:
                result = p.pause_resume()
                self._play_btn.config(text="▶" if p.is_paused else "⏸")
            elif p.is_paused:
                result = p.pause_resume()
                self._play_btn.config(text="⏸")
            else:
                query = self._music_search_var.get().strip()
                if query:
                    self._play_query_direct(query)
        except Exception as e:
            print(f"[MusicUI] Play/pause error: {e}")

    def _play_query_direct(self, query: str):
        self._now_playing_var.set(f"Searching: {query}...")

        def _go():
            try:
                from actions.music_player import get_player
                get_player().play_query(query)
            except Exception as e:
                print(f"[MusicUI] Play query error: {e}")

        threading.Thread(target=_go, daemon=True).start()

    def _on_stop(self):
        try:
            from actions.music_player import get_player
            get_player().stop()
            self._play_btn.config(text="▶")
            self._now_playing_var.set("— Stopped —")
        except Exception as e:
            print(f"[MusicUI] Stop error: {e}")

    def _on_next(self):
        try:
            from actions.music_player import get_player
            p = get_player()
            if self._playlist_tracks:
                self._playlist_idx = (self._playlist_idx + 1) % len(self._playlist_tracks)
                track = self._playlist_tracks[self._playlist_idx]
                self._now_playing_var.set(f"Loading: {track['title']}...")
                threading.Thread(target=p.play_track, args=(track,), daemon=True).start()
                self._playlist_listbox.selection_clear(0, tk.END)
                self._playlist_listbox.selection_set(self._playlist_idx)
                self._playlist_listbox.see(self._playlist_idx)
            else:
                p.next_track()
        except Exception as e:
            print(f"[MusicUI] Next error: {e}")

    def _on_prev(self):
        try:
            from actions.music_player import get_player
            p = get_player()
            if self._playlist_tracks:
                self._playlist_idx = max(0, self._playlist_idx - 1)
                track = self._playlist_tracks[self._playlist_idx]
                self._now_playing_var.set(f"Loading: {track['title']}...")
                threading.Thread(target=p.play_track, args=(track,), daemon=True).start()
                self._playlist_listbox.selection_clear(0, tk.END)
                self._playlist_listbox.selection_set(self._playlist_idx)
                self._playlist_listbox.see(self._playlist_idx)
            else:
                p.prev_track()
        except Exception as e:
            print(f"[MusicUI] Prev error: {e}")

    def _on_volume_change(self, val):
        try:
            from actions.music_player import get_player
            get_player().set_volume(int(float(val)))
        except Exception:
            pass

    def _on_add_to_playlist(self):
        sel = self._results_listbox.curselection()
        if not sel or not self._search_results:
            return
        idx   = sel[0]
        if idx >= len(self._search_results):
            return
        track = self._search_results[idx]
        self._playlist_tracks.append(track)
        self._playlist_listbox.insert(tk.END, f"{track['title']} — {track['artist']}")

    def _on_play_playlist(self):
        if not self._playlist_tracks:
            return
        self._playlist_idx = 0
        track = self._playlist_tracks[0]
        self._now_playing_var.set(f"Loading: {track['title']}...")
        try:
            from actions.music_player import get_player
            p = get_player()
            p.set_playlist(self._playlist_tracks)
            threading.Thread(target=p.play_track, args=(track,), daemon=True).start()
        except Exception as e:
            print(f"[MusicUI] Play playlist error: {e}")
        self._playlist_listbox.selection_clear(0, tk.END)
        self._playlist_listbox.selection_set(0)

    def _on_clear_playlist(self):
        self._playlist_tracks = []
        self._playlist_idx    = 0
        self._playlist_listbox.delete(0, tk.END)

    def _on_play_from_playlist(self, event=None):
        sel = self._playlist_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._playlist_tracks):
            return
        self._playlist_idx = idx
        track = self._playlist_tracks[idx]
        self._now_playing_var.set(f"Loading: {track['title']}...")
        try:
            from actions.music_player import get_player
            threading.Thread(target=get_player().play_track, args=(track,), daemon=True).start()
        except Exception as e:
            print(f"[MusicUI] Play from playlist error: {e}")

    # ----------------------------------------------------------------------
    # Music player callbacks
    # ----------------------------------------------------------------------
    def _on_track_changed(self, meta: dict):
        """Update now playing label and reset seek slider range."""
        title  = meta.get("title", "Unknown")
        artist = meta.get("artist", "")
        text   = f"{title}\n{artist}" if artist else title
        self.root.after(0, lambda: self._now_playing_var.set(text))
        self.root.after(0, lambda: self._play_btn.config(text="⏸"))

        # Reset seek slider maximum to the new track's duration (if known)
        dur = meta.get("duration", 0)
        if dur and dur > 0:
            self.root.after(0, lambda: self._seek_slider.config(to=dur))
            self.root.after(0, lambda: self._total_time_var.set(self._format_time(dur)))
        else:
            # Unknown duration – keep a high temporary value (will be corrected by polling)
            self.root.after(0, lambda: self._seek_slider.config(to=100))

    def _on_player_state_changed(self, is_playing: bool, is_paused: bool):
        if is_playing and not is_paused:
            icon = "⏸"
        else:
            icon = "▶"
        self.root.after(0, lambda: self._play_btn.config(text=icon))

    # ----------------------------------------------------------------------
    # Public helpers
    # ----------------------------------------------------------------------
    def update_now_playing(self, title: str, artist: str = ""):
        text = title + (f"\n{artist}" if artist else "")
        self.root.after(0, lambda: self._now_playing_var.set(text))

    # ----------------------------------------------------------------------
    # State management
    # ----------------------------------------------------------------------
    def set_state(self, state: str):
        self._jarvis_state = state
        if state == "SPEAKING":
            self.speaking = True
        elif state in ("LISTENING", "THINKING", "PROCESSING", "MUTED"):
            self.speaking = False
        elif state == "ONLINE":
            self.speaking = False

    # ----------------------------------------------------------------------
    # Face loader
    # ----------------------------------------------------------------------
    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            img  = Image.open(path).convert("RGBA").resize((FW, FW), Image.LANCZOS)
            mask = Image.new("L", (FW, FW), 0)
            ImageDraw.Draw(mask).ellipse((2, 2, FW - 2, FW - 2), fill=255)
            img.putalpha(mask)
            self._face_pil = img
            self._has_face = True
        except Exception:
            self._has_face = False

    @staticmethod
    def _ac(r, g, b, a):
        f = a / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    # ----------------------------------------------------------------------
    # Animation loop
    # ----------------------------------------------------------------------
    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        if now - self.last_t > (0.14 if self.speaking else 0.55):
            if self.speaking:
                self.target_scale = random.uniform(1.05, 1.11)
                self.target_halo  = random.uniform(138, 182)
            elif self.muted:
                self.target_scale = random.uniform(0.998, 1.001)
                self.target_halo  = random.uniform(20, 32)
            else:
                self.target_scale = random.uniform(1.001, 1.007)
                self.target_halo  = random.uniform(50, 68)
            self.last_t = now

        sp = 0.35 if self.speaking else 0.16
        self.scale  += (self.target_scale - self.scale)  * sp
        self.halo_a += (self.target_halo  - self.halo_a) * sp

        for i, spd in enumerate([1.2, -0.8, 1.9] if self.speaking else [0.5, -0.3, 0.82]):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        self.scan_angle  = (self.scan_angle  + (2.8 if self.speaking else 1.2)) % 360
        self.scan2_angle = (self.scan2_angle + (-1.7 if self.speaking else -0.68)) % 360

        pspd  = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.72
        new_p = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(new_p) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            new_p.append(0.0)
        self.pulse_r = new_p

        if t % 40 == 0:
            self.status_blink = not self.status_blink

        self._draw()
        self.root.after(16, self._animate)

    # ----------------------------------------------------------------------
    # Drawing (unchanged)
    # ----------------------------------------------------------------------
    def _draw(self):
        c    = self.bg
        W, H = self.W, self.H
        t    = self.tick
        FCX  = self.FCX
        FCY  = self.FCY
        FW   = self.FACE_SZ
        c.delete("all")

        # Background grid
        for x in range(0, W, 44):
            for y in range(0, H, 44):
                c.create_rectangle(x, y, x+1, y+1, fill=C_DIMMER, outline="")

        # Halo rings
        for r in range(int(FW * 0.54), int(FW * 0.28), -22):
            frac = 1.0 - (r - FW * 0.28) / (FW * 0.26)
            ga   = max(0, min(255, int(self.halo_a * 0.09 * frac)))
            gh   = f"{ga:02x}"
            if self.muted:
                c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r, outline=f"#{gh}0011", width=2)
            else:
                c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r, outline=f"#00{gh}ff", width=2)

        # Pulse waves
        for pr in self.pulse_r:
            pa = max(0, int(220 * (1.0 - pr / (FW * 0.72))))
            r  = int(pr)
            if self.muted:
                c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                              outline=self._ac(255, 30, 80, pa // 3), width=2)
            else:
                c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                              outline=self._ac(0, 212, 255, pa), width=2)

        # Spinning rings
        for idx, (r_frac, w_ring, arc_l, gap) in enumerate([
                (0.47, 3, 110, 75), (0.39, 2, 75, 55), (0.31, 1, 55, 38)]):
            ring_r = int(FW * r_frac)
            base_a = self.rings_spin[idx]
            a_val  = max(0, min(255, int(self.halo_a * (1.0 - idx * 0.18))))
            col    = self._ac(255, 30, 80, a_val) if self.muted else self._ac(0, 212, 255, a_val)
            for s in range(360 // (arc_l + gap)):
                start = (base_a + s * (arc_l + gap)) % 360
                c.create_arc(FCX-ring_r, FCY-ring_r, FCX+ring_r, FCY+ring_r,
                             start=start, extent=arc_l,
                             outline=col, width=w_ring, style="arc")

        # Scan arcs
        sr      = int(FW * 0.49)
        scan_a  = min(255, int(self.halo_a * 1.4))
        arc_ext = 70 if self.speaking else 42
        scan_col = self._ac(255, 30, 80, scan_a) if self.muted else self._ac(0, 212, 255, scan_a)
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan_angle, extent=arc_ext,
                     outline=scan_col, width=3, style="arc")
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan2_angle, extent=arc_ext,
                     outline=self._ac(255, 100, 0, scan_a // 2), width=2, style="arc")

        # Degree tick marks
        t_out = int(FW * 0.495)
        t_in  = int(FW * 0.472)
        a_mk  = self._ac(0, 212, 255, 155)
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 5
            c.create_line(FCX + t_out * math.cos(rad), FCY - t_out * math.sin(rad),
                          FCX + inn  * math.cos(rad), FCY - inn  * math.sin(rad),
                          fill=a_mk, width=1)

        # Crosshair
        ch_r = int(FW * 0.50)
        gap  = int(FW * 0.15)
        ch_a = self._ac(0, 212, 255, int(self.halo_a * 0.55))
        for x1, y1, x2, y2 in [
                (FCX - ch_r, FCY, FCX - gap, FCY), (FCX + gap, FCY, FCX + ch_r, FCY),
                (FCX, FCY - ch_r, FCX, FCY - gap), (FCX, FCY + gap, FCX, FCY + ch_r)]:
            c.create_line(x1, y1, x2, y2, fill=ch_a, width=1)

        # Corner brackets
        blen = 22
        bc   = self._ac(0, 212, 255, 200)
        hl = FCX - FW // 2; hr = FCX + FW // 2
        ht = FCY - FW // 2; hb = FCY + FW // 2
        for bx, by, sdx, sdy in [(hl, ht, 1, 1), (hr, ht, -1, 1),
                                   (hl, hb, 1, -1), (hr, hb, -1, -1)]:
            c.create_line(bx, by, bx + sdx * blen, by,            fill=bc, width=2)
            c.create_line(bx, by, bx,               by + sdy * blen, fill=bc, width=2)

        # Face / orb
        if self._has_face:
            fw = int(FW * self.scale)
            if (self._face_scale_cache is None or
                    abs(self._face_scale_cache[0] - self.scale) > 0.004):
                scaled = self._face_pil.resize((fw, fw), Image.BILINEAR)
                tk_img = ImageTk.PhotoImage(scaled)
                self._face_scale_cache = (self.scale, tk_img)
            c.create_image(FCX, FCY, image=self._face_scale_cache[1])
        else:
            orb_r     = int(FW * 0.27 * self.scale)
            orb_color = (255, 30, 80) if self.muted else (0, 65, 120)
            for i in range(7, 0, -1):
                r2   = int(orb_r * i / 7)
                frac = i / 7
                ga   = max(0, min(255, int(self.halo_a * 1.1 * frac)))
                c.create_oval(FCX-r2, FCY-r2, FCX+r2, FCY+r2,
                              fill=self._ac(int(orb_color[0]*frac),
                                            int(orb_color[1]*frac),
                                            int(orb_color[2]*frac), ga),
                              outline="")
            c.create_text(FCX, FCY, text=SYSTEM_NAME,
                          fill=self._ac(0, 212, 255, min(255, int(self.halo_a * 2))),
                          font=("Courier", 14, "bold"))

        # Header
        HDR = 62
        c.create_rectangle(0, 0, W, HDR, fill="#00080d", outline="")
        c.create_line(0, HDR, W, HDR, fill=C_MID, width=1)
        c.create_text(W // 2, 22, text=SYSTEM_NAME,
                      fill=C_PRI, font=("Courier", 18, "bold"))
        c.create_text(W // 2, 44, text="Just A Rather Very Intelligent System",
                      fill=C_MID, font=("Courier", 9))
        c.create_text(16, 31, text=MODEL_BADGE,
                      fill=C_DIM, font=("Courier", 9), anchor="w")
        c.create_text(W - 16, 31, text=time.strftime("%H:%M:%S"),
                      fill=C_PRI, font=("Courier", 14, "bold"), anchor="e")

        # Status indicator
        sy = FCY + FW // 2 + 40
        if self.muted:
            stat, sc = "⊘ MUTED", C_MUTED
        elif self.speaking:
            stat, sc = "● SPEAKING", C_ACC
        elif self._jarvis_state == "THINKING":
            sym  = "◈" if self.status_blink else "◇"
            stat, sc = f"{sym} THINKING", C_ACC2
        elif self._jarvis_state == "PROCESSING":
            sym  = "▷" if self.status_blink else "▶"
            stat, sc = f"{sym} PROCESSING", C_ACC2
        elif self._jarvis_state == "LISTENING":
            sym  = "●" if self.status_blink else "○"
            stat, sc = f"{sym} LISTENING", C_GREEN
        else:
            sym  = "●" if self.status_blink else "○"
            stat, sc = f"{sym} {self.status_text}", C_PRI
        c.create_text(W // 2, sy, text=stat, fill=sc, font=("Courier", 11, "bold"))

        # Waveform bars
        wy = sy + 22
        N  = 28
        BH = 16
        bw = 8
        total_w = N * bw
        wx0 = (W - total_w) // 2
        for i in range(N):
            if self.muted:
                hb, col = 2, C_MUTED
            elif self.speaking:
                hb  = random.randint(3, BH)
                col = C_PRI if hb > BH * 0.6 else C_MID
            else:
                hb  = int(3 + 2 * math.sin(t * 0.08 + i * 0.55))
                col = C_DIM
            bx = wx0 + i * bw
            c.create_rectangle(bx, wy + BH - hb, bx + bw - 1, wy + BH,
                                fill=col, outline="")

        # Footer
        c.create_rectangle(0, H - 28, W, H, fill="#00080d", outline="")
        c.create_line(0, H - 28, W, H - 28, fill=C_DIM, width=1)
        c.create_text(W - 16, H - 14, fill=C_DIM, font=("Courier", 8),
                      text="[F4] MUTE", anchor="e")
        c.create_text(W // 2, H - 14, fill=C_DIM, font=("Courier", 8),
                      text="FatihMakes Industries  ·  CLASSIFIED  ·  MARK XXXV")

    # ----------------------------------------------------------------------
    # Log
    # ----------------------------------------------------------------------
    def write_log(self, text: str):
        self.typing_queue.append(text)
        tl = text.lower()
        if tl.startswith("you:"):
            self.set_state("PROCESSING")
        elif tl.startswith("jarvis:") or tl.startswith("ai:"):
            self.set_state("SPEAKING")
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if not self.speaking and not self.muted:
                self.set_state("LISTENING")
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        if tl.startswith("you:"):
            tag = "you"
        elif tl.startswith("jarvis:") or tl.startswith("ai:"):
            tag = "ai"
        elif tl.startswith("err:") or "error" in tl or "failed" in tl:
            tag = "err"
        else:
            tag = "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(8, self._type_char, text, i + 1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(25, self._start_typing)

    # ----------------------------------------------------------------------
    # API key handling
    # ----------------------------------------------------------------------
    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def _api_keys_exist(self):
        return API_FILE.exists()

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self):
        self.setup_frame = tk.Frame(
            self.root, bg="#00080d",
            highlightbackground=C_PRI, highlightthickness=1
        )
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(self.setup_frame, text="◈  INITIALISATION REQUIRED",
                 fg=C_PRI, bg="#00080d", font=("Courier", 13, "bold")).pack(pady=(18, 4))
        tk.Label(self.setup_frame,
                 text="Enter your Gemini API key to boot J.A.R.V.I.S.",
                 fg=C_MID, bg="#00080d", font=("Courier", 9)).pack(pady=(0, 10))

        tk.Label(self.setup_frame, text="GEMINI API KEY",
                 fg=C_DIM, bg="#00080d", font=("Courier", 9)).pack(pady=(8, 2))
        self.gemini_entry = tk.Entry(
            self.setup_frame, width=52, fg=C_TEXT, bg="#000d12",
            insertbackground=C_TEXT, borderwidth=0,
            font=("Courier", 10), show="*"
        )
        self.gemini_entry.pack(pady=(0, 4))

        tk.Button(
            self.setup_frame, text="▸  INITIALISE SYSTEMS",
            command=self._save_api_keys, bg=C_BG, fg=C_PRI,
            activebackground="#003344", font=("Courier", 10),
            borderwidth=0, pady=8
        ).pack(pady=14)

    def _save_api_keys(self):
        gemini = self.gemini_entry.get().strip()
        if not gemini:
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(API_FILE, "w", encoding="utf-8") as f:
            json.dump({"gemini_api_key": gemini}, f, indent=4)
        self.setup_frame.destroy()
        self._api_key_ready = True
        self.set_state("LISTENING")
        self.write_log("SYS: Systems initialised. JARVIS online.")