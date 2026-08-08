"""
nowhere_nobody - ariana grande
────────────────────
LYRICS format:
  Normal line:   (timestamp, "lyric line", hold, w, type_speed)
  Side-by-side:  (timestamp, [phrases], word_delay, hold, (w, h), y_offset, gap, keep_previous)
  Shout collage: (timestamp, {"shout": "text"}, hold)
  Linger:        (timestamp, {"linger": "text"}, hold)   # centered, slow, stays until next
  Slam:          (timestamp, {"slam": "text"}, hold)     # oversized centered payoff
  Tinker swarm:  (timestamp, {"tinker": "text"|[phrases]}, hold)
                 # bouncing chips that stay until the final slam closes

  - hold       : seconds window stays after typing finishes; None = forever
  - type_speed : seconds between each character appearing (default: TYPE_SPEED)
  - w          : just width now — height grows automatically with text

Run:  python nowhere_nobody.py
"""

import tkinter as tk
import threading
import time
import math
import random
import sys
import ctypes
import struct
import tempfile

# ══════════════════════════════════════════════════════════════════════════════
#  YOUR LYRICS
# ══════════════════════════════════════════════════════════════════════════════

LYRICS = [
    (0.00,  {"linger": "Deep breaths, honey"},                              None),

    (2.81,  "There's no more running",                                      None, 380, 0.060),

    (5.81,  {"linger": "And there's nowhere with nobody else that I'd rather be"}, None),
    (9.50,  {"tinker": "nowhere nobody"},                                   None),

    (12.03, "I'm taking you",                                               None, 300, 0.070),

    (13.23, {"linger": "Deep breaths, honey"},                              None),

    (15.95, "We've at least till morning",                                  None, 400, 0.055),

    (19.28, {"slam": "Then there's nowhere, nobody else that I'd rather be with"}, 7.6),

    (28.92, {"linger": "No, there's nowhere else"},                          None),
    (32.35, "And there's no more running",                                    None, 380, 0.060),
    (35.22, {"linger": "Nobody else that I'd rather be with"},                None),
]

# ── defaults
TYPE_SPEED  = 0.05
WORD_HOLD   = 2.5
FONT_NAME   = "Helvetica"
FONT_SIZE   = 18
LINE_PAD    = 18

# ── sentence window defaults
LINE_W = 400

# ── side-by-side defaults
SBS_W          = 260
SBS_H          = 160
SBS_HOLD       = 1.8
SBS_PAD        = 40
SBS_MIN_W      = 110
SBS_GAP        = 24
SBS_FRAME_PAD  = 8
SBS_TYPE_SPEED = 0.04

WINDOW_ICON_COLOR = "#7C949E"
SLIDE_DURATION_MS = 2000
SLIDE_FPS         = 120

# ── shout collage (many small boxes flooding the screen)
SHOUT_COUNT       = 50
SHOUT_INTERVAL_MS = 30
SHOUT_BATCH       = 5          # spawn this many per tick so all 50 land fast
SHOUT_W           = 280
SHOUT_H           = 72
SHOUT_FONT_SIZE   = 18

# ── tinker swarm (many small windows bouncing around)
TINKER_COUNT       = 10
TINKER_SPAWN_MS    = 40
TINKER_BATCH       = 5          # spawn this many per tick so all 40 land fast
TINKER_FPS         = 60
TINKER_W           = 200
TINKER_H           = 64
TINKER_FONT_SIZE   = 16
TINKER_SPEED_MIN   = 0.25
TINKER_SPEED_MAX   = 0.55
TINKER_KEEPOUT_W   = 720
TINKER_KEEPOUT_H   = 380

# ══════════════════════════════════════════════════════════════════════════════

# ── global window tracking ────────────────────────────────────────────────────
_active_sbs_windows      = []   # SideBySideWindow instances
_active_sentence_windows = []   # SentenceWindow instances
_active_shout_windows    = []   # ShoutTile instances
_active_tinker_windows   = []   # TinkerTile instances
_shout_spawn_id          = 0    # bumps to cancel pending collage spawns
_tinker_spawn_id         = 0    # bumps to cancel pending tinker spawns
_tinker_anim_id          = None # shared bounce loop after() id
_tinker_root             = None


def make_solid_icon(color, size=32):
    icon = tk.PhotoImage(width=size, height=size)
    icon.put(color, to=(0, 0, size, size))
    return icon


def make_solid_ico_path(hex_color, size=32):
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)

    row = bytes([b, g, r, 255] * size)
    xor = b"".join(reversed([row] * size))
    and_row_bytes = ((size + 31) // 32) * 4
    and_mask = b"\x00" * (and_row_bytes * size)
    bi_hdr = struct.pack(
        "<IIIHHIIIIII",
        40, size, size * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0,
    )
    image_data = bi_hdr + xor + and_mask
    header = struct.pack("<HHH", 0, 1, 1)
    entry  = struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image_data), 22)

    ico = tempfile.NamedTemporaryFile(suffix=".ico", delete=False)
    ico.write(header + entry + image_data)
    ico.close()
    return ico.name


def apply_window_style(win, title=""):
    win.title(title)
    win.update_idletasks()

    if sys.platform == "win32":
        try:
            ico_path = make_solid_ico_path(WINDOW_ICON_COLOR)
            win.iconbitmap(default=ico_path)
            win._ico_path = ico_path
        except tk.TclError:
            pass
    else:
        try:
            icon = make_solid_icon(WINDOW_ICON_COLOR)
            win.iconphoto(False, icon)
            win._window_icon = icon
        except tk.TclError:
            pass

    if sys.platform != "win32":
        return

    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        pref = ctypes.c_int(DWMWCP_DONOTROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref), ctypes.sizeof(pref),
        )
    except Exception:
        pass


def random_top_pos(root, w):
    """Scatter a window near the upper-middle of the screen."""
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    cx = (sw - w) // 2
    x  = cx + random.randint(-180, 180)
    y  = random.randint(80, max(81, sh // 3))
    return x, y


def centered_pos(root, w, h=None, y_frac=0.5):
    """Place a window at screen center (same spot for every main lyric)."""
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x  = (sw - w) // 2
    if h is not None:
        y = (sh - h) // 2
    else:
        y = int(sh * y_frac)
    return x, y


def measure_text_size(text, font_name, font_size):
    # Approximate metrics — never create a second Tk() (segfaults on macOS).
    avg = font_size * 0.58
    return max(1, int(len(text or " ") * avg)), int(font_size * 1.45)


def sbs_word_size(word, size=None):
    if size:
        return size
    tw, th = measure_text_size(word, FONT_NAME, FONT_SIZE)
    return max(tw + SBS_PAD, SBS_MIN_W), th + SBS_PAD


# ── typing helpers ────────────────────────────────────────────────────────────

def _type_chars(label, win, text, speed_ms, on_done=None):
    def step(i=0):
        label.config(text=text[:i])
        label.update_idletasks()
        lh = label.winfo_reqheight()
        win_w = max(win.winfo_width(), 1)
        new_h = lh + LINE_PAD * 2
        # Keep lyrics pinned to a fixed screen-centered anchor as height grows.
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - win_w) // 2
        y = (sh - new_h) // 2 + getattr(win, "_y_shift", 0)
        win._lock_x = x
        win._lock_y = y
        win.geometry(f"{win_w}x{new_h}+{x}+{y}")

        if i < len(text):
            label.after(speed_ms, lambda: step(i + 1))
        elif on_done:
            on_done()

    step()


# ── window classes ────────────────────────────────────────────────────────────

class SentenceWindow:
    """Floating window that types out a sentence and grows vertically."""

    def __init__(self, root, sentence, hold, w=LINE_W, type_speed=None,
                 centered=True, font_size=None, fg="#111111", y_shift=0):
        global _active_sentence_windows
        self.hold = hold
        self.win  = tk.Toplevel(root)
        self.win.configure(bg="white")
        self.win.resizable(False, False)

        fs = font_size or FONT_SIZE
        init_h = LINE_PAD * 2
        x, y = centered_pos(root, w, h=init_h)
        y += y_shift
        self.win._lock_x = x
        self.win._lock_y = y
        self.win._y_shift = y_shift
        self.win.geometry(f"{w}x{init_h}+{x}+{y}")

        self.label = tk.Label(
            self.win,
            text="",
            font=(FONT_NAME, fs, "bold"),
            fg=fg,
            bg="white",
            wraplength=w - LINE_PAD * 2,
            justify="center",
        )
        self.label.place(x=LINE_PAD, y=LINE_PAD, anchor="nw")

        apply_window_style(self.win)
        _active_sentence_windows.append(self)

        speed_ms = int((type_speed or TYPE_SPEED) * 1000)
        _type_chars(self.label, self.win, sentence, speed_ms, on_done=self._start_hold)

    def _start_hold(self):
        if self.hold is not None:
            self.win.after(int(self.hold * 1000), self.close)

    def close(self):
        global _active_sentence_windows
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self in _active_sentence_windows:
            _active_sentence_windows.remove(self)


class SideBySideWindow:
    """One panel in a side-by-side row — fixed size, types out its phrase."""

    def __init__(self, root, word, x, y, size, type_speed=None, on_typed=None):
        self._root = root
        self.win = tk.Toplevel(root)
        self.win.configure(bg="white")
        self.win.resizable(False, False)   # fixed size — no growing

        w, h = size
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        self.label = tk.Label(
            self.win,
            text="",
            font=(FONT_NAME, FONT_SIZE, "bold"),
            fg="#111111",
            bg="white",
            wraplength=w - LINE_PAD * 2,
            justify="left",
        )
        self.label.place(x=LINE_PAD, y=LINE_PAD, anchor="nw")

        apply_window_style(self.win)

        speed_ms = int((type_speed or SBS_TYPE_SPEED) * 1000)
        # Don't use _type_chars here — we want fixed window size, no resizing
        self._type_fixed(self.label, self.win, word, speed_ms, on_done=on_typed)

    def _type_fixed(self, label, win, text, speed_ms, on_done=None):
        """Type characters without resizing the window."""
        def step(i=0):
            label.config(text=text[:i])
            if i < len(text):
                label.after(speed_ms, lambda: step(i + 1))
            elif on_done:
                on_done()
        step()

    def cancel_hold(self):
        """Cancel any pending hold-timer so it can't close the window late."""
        if hasattr(self, "_hold_id") and self._hold_id is not None:
            try:
                self._root.after_cancel(self._hold_id)
            except Exception:
                pass
            self._hold_id = None

    def close(self):
        self.cancel_hold()
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class SlidingWindow:
    def __init__(self, root, text, w, h, y, screen_w):
        self.w        = w
        self.h        = h
        self.y        = y
        self.screen_w = screen_w
        self.win      = tk.Toplevel(root)
        self.win.configure(bg="white")
        self.win.resizable(False, False)

        tk.Label(
            self.win,
            text=text,
            font=(FONT_NAME, FONT_SIZE, "bold"),
            fg="#111111",
            bg="white",
        ).place(relx=0.5, rely=0.5, anchor="center")

        apply_window_style(self.win)

        self._step  = 0
        self._steps = max(1, int(SLIDE_DURATION_MS / (1000 / SLIDE_FPS)))
        self._tick()

    def _tick(self):
        t = self._step / self._steps
        x = int(-self.w + (self.screen_w + self.w) * t)
        self.win.geometry(f"{self.w}x{self.h}+{x}+{self.y}")
        self._step += 1
        if self._step > self._steps:
            self.close()
            return
        self.win.after(int(1000 / SLIDE_FPS), self._tick)

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class SlamWindow:
    """One oversized centered window — slow type, then holds. Payoff moment."""

    FONT_SIZE = 28
    WIDTH     = 640

    def __init__(self, root, text, hold, type_speed=0.08):
        global _active_sentence_windows
        self._root = root
        self.hold = hold
        self.win  = tk.Toplevel(root)
        self.win.configure(bg="white")
        self.win.resizable(False, False)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w  = self.WIDTH
        wrap = w - LINE_PAD * 2

        # Pre-size for the FULL text so typing never resizes (no jump).
        probe = tk.Label(
            self.win,
            text=text,
            font=(FONT_NAME, self.FONT_SIZE, "bold"),
            wraplength=wrap,
            justify="left",
        )
        probe.update_idletasks()
        h = max(probe.winfo_reqheight() + LINE_PAD * 2, 120)
        probe.destroy()

        x = (sw - w) // 2
        y = (sh - h) // 2
        self.win._lock_x = x
        self.win._lock_y = y
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        self.label = tk.Label(
            self.win,
            text="",
            font=(FONT_NAME, self.FONT_SIZE, "bold"),
            fg="#111111",
            bg="white",
            wraplength=wrap,
            justify="left",   # wrap long lines left — no center reflow jump
            anchor="nw",
        )
        self.label.place(x=LINE_PAD, y=LINE_PAD, anchor="nw")

        apply_window_style(self.win)
        # Re-assert lock after style (icon/DWM can nudge the window)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        _active_sentence_windows.append(self)

        speed_ms = int(type_speed * 1000)
        self._type_fixed(text, speed_ms)

    def _type_fixed(self, text, speed_ms):
        """Type without resizing — window size already fits the full lyric."""
        def step(i=0):
            try:
                self.label.config(text=text[:i])
            except tk.TclError:
                return
            if i < len(text):
                self.win.after(speed_ms, lambda: step(i + 1))
            else:
                self._start_hold()
        step()

    def _start_hold(self):
        if self.hold is not None:
            self.win.after(int(self.hold * 1000), self.close)

    def close(self):
        global _active_sentence_windows
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self in _active_sentence_windows:
            _active_sentence_windows.remove(self)
        close_all_tinkers(self._root)


class ShoutTile:
    """One small box in the shout collage — text appears instantly."""

    def __init__(self, root, text, x, y, w=SHOUT_W, h=SHOUT_H):
        global _active_shout_windows
        self.win = tk.Toplevel(root)
        self.win.configure(bg="white")
        self.win.resizable(False, False)
        # Skip apply_window_style — icon/DWM work is too slow for a flood of tiles
        if sys.platform == "darwin":
            try:
                self.win.overrideredirect(True)
            except tk.TclError:
                pass
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        tk.Label(
            self.win,
            text=text,
            font=(FONT_NAME, SHOUT_FONT_SIZE, "bold"),
            fg="#111111",
            bg="white",
            wraplength=w - 16,
            justify="center",
        ).place(relx=0.5, rely=0.5, anchor="center")

        _active_shout_windows.append(self)

    def close(self):
        global _active_shout_windows
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self in _active_shout_windows:
            _active_shout_windows.remove(self)


def show_shout_collage(root, text, hold=None):
    """
    Flood the screen with many small boxes of `text`, popping in batches
    until they form a dense collage. Pending spawns cancel when the next lyric
    closes all windows.
    """
    global _shout_spawn_id

    _shout_spawn_id += 1
    spawn_id = _shout_spawn_id

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    margin = 20
    max_x = max(margin, sw - SHOUT_W - margin)
    max_y = max(margin, sh - SHOUT_H - margin)

    def spawn(i=0):
        if spawn_id != _shout_spawn_id:
            return
        if i >= SHOUT_COUNT:
            return

        end = min(i + SHOUT_BATCH, SHOUT_COUNT)
        for _ in range(i, end):
            x = random.randint(margin, max_x)
            y = random.randint(margin, max_y)
            w = SHOUT_W + random.randint(-30, 40)
            h = SHOUT_H + random.randint(-10, 14)
            ShoutTile(root, text, x, y, w=w, h=h)

        root.after(SHOUT_INTERVAL_MS, lambda: spawn(end))

    spawn(0)


def tinker_keepout_rect(sw, sh):
    """Center rectangle reserved for the main lyric — tinkers stay outside."""
    kw = min(TINKER_KEEPOUT_W, sw - 80)
    kh = min(TINKER_KEEPOUT_H, sh - 80)
    left   = (sw - kw) // 2
    top    = (sh - kh) // 2
    return left, top, left + kw, top + kh


def tinker_random_pos(sw, sh, w, h, margin=20):
    """Pick a random position that does not overlap the center lyric zone."""
    k_l, k_t, k_r, k_b = tinker_keepout_rect(sw, sh)
    max_x = max(margin, sw - w - margin)
    max_y = max(margin, sh - h - margin)

    # Build safe bands: top, bottom, left, right of the keepout
    bands = []
    if k_t - margin > margin + h:
        bands.append(("top", margin, max_x, margin, max(margin, k_t - h)))
    if max_y > k_b:
        bands.append(("bottom", margin, max_x, k_b, max_y))
    if k_l - margin > margin + w:
        bands.append(("left", margin, max(margin, k_l - w), margin, max_y))
    if max_x > k_r:
        bands.append(("right", k_r, max_x, margin, max_y))

    if not bands:
        return random.randint(margin, max_x), random.randint(margin, max_y)

    _, x0, x1, y0, y1 = random.choice(bands)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return random.randint(x0, max(x0, x1)), random.randint(y0, max(y0, y1))


class TinkerTile:
    """Small lyric chip — position updated by the shared tinker animator."""

    def __init__(self, root, text, x, y, w, h, vx, vy, screen_w, screen_h):
        global _active_tinker_windows
        self._alive = True
        self.w = w
        self.h = h
        self.x = float(x)
        self.y = float(y)
        self.vx = vx
        self.vy = vy
        self.sw = screen_w
        self.sh = screen_h
        self.k_l, self.k_t, self.k_r, self.k_b = tinker_keepout_rect(screen_w, screen_h)
        self.win = tk.Toplevel(root)
        self.win.configure(bg="white")
        self.win.resizable(False, False)
        # Skip apply_window_style — update_idletasks + iconphoto per tile
        # stresses macOS Tk hard when many windows move.
        if sys.platform == "darwin":
            try:
                self.win.overrideredirect(True)
            except tk.TclError:
                pass
        self.win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")

        tk.Label(
            self.win,
            text=text,
            font=(FONT_NAME, TINKER_FONT_SIZE, "bold"),
            fg="#111111",
            bg="white",
            wraplength=w - 12,
            justify="center",
        ).place(relx=0.5, rely=0.5, anchor="center")

        _active_tinker_windows.append(self)

    def _overlaps_keepout(self, x, y):
        """True if tile rectangle intersects the center lyric keepout."""
        return not (
            x + self.w <= self.k_l
            or x >= self.k_r
            or y + self.h <= self.k_t
            or y >= self.k_b
        )

    def step(self):
        if not self._alive:
            return
        self.x += self.vx
        self.y += self.vy
        margin = 8
        max_x = max(margin, self.sw - self.w - margin)
        max_y = max(margin, self.sh - self.h - margin)

        if self.x <= margin:
            self.x = margin
            self.vx = abs(self.vx)
        elif self.x >= max_x:
            self.x = max_x
            self.vx = -abs(self.vx)

        if self.y <= margin:
            self.y = margin
            self.vy = abs(self.vy)
        elif self.y >= max_y:
            self.y = max_y
            self.vy = -abs(self.vy)

        if self._overlaps_keepout(self.x, self.y):
            cx = (self.k_l + self.k_r) / 2
            cy = (self.k_t + self.k_b) / 2
            tile_cx = self.x + self.w / 2
            tile_cy = self.y + self.h / 2
            # Push out along the stronger axis
            if abs(tile_cx - cx) * (self.k_b - self.k_t) > abs(tile_cy - cy) * (self.k_r - self.k_l):
                if tile_cx < cx:
                    self.x = self.k_l - self.w
                    self.vx = -abs(self.vx)
                else:
                    self.x = self.k_r
                    self.vx = abs(self.vx)
            else:
                if tile_cy < cy:
                    self.y = self.k_t - self.h
                    self.vy = -abs(self.vy)
                else:
                    self.y = self.k_b
                    self.vy = abs(self.vy)
            self.x = min(max(self.x, margin), max_x)
            self.y = min(max(self.y, margin), max_y)

        try:
            self.win.geometry(f"+{int(self.x)}+{int(self.y)}")
        except tk.TclError:
            self._alive = False

    def close(self):
        global _active_tinker_windows
        self._alive = False
        try:
            self.win.withdraw()
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self in _active_tinker_windows:
            _active_tinker_windows.remove(self)


def _stop_tinker_animator(root=None):
    global _tinker_anim_id, _tinker_root
    target = root or _tinker_root
    if _tinker_anim_id is not None and target is not None:
        try:
            target.after_cancel(_tinker_anim_id)
        except Exception:
            pass
    _tinker_anim_id = None


def _tinker_animate():
    """One shared bounce loop for every live tinker tile (macOS-safe)."""
    global _tinker_anim_id, _tinker_root
    if _tinker_root is None:
        _tinker_anim_id = None
        return

    alive = False
    for tile in list(_active_tinker_windows):
        if tile._alive:
            tile.step()
            alive = True

    if alive and _active_tinker_windows:
        _tinker_anim_id = _tinker_root.after(int(1000 / TINKER_FPS), _tinker_animate)
    else:
        _tinker_anim_id = None


def show_tinker_swarm(root, phrases, hold=None, count=None):
    """
    Spawn many small windows that bounce around the screen. Phrases cycle
    through the provided list (or a single string). Swarm runs until slam ends.
    """
    global _tinker_spawn_id, _tinker_root, _tinker_anim_id

    _stop_tinker_animator(root)
    _tinker_spawn_id += 1
    spawn_id = _tinker_spawn_id
    _tinker_root = root

    if isinstance(phrases, str):
        phrases = [phrases]
    if not phrases:
        phrases = ["…"]

    n = count if count is not None else TINKER_COUNT
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    margin = 20
    batch = TINKER_BATCH

    def spawn(i=0):
        global _tinker_anim_id
        if spawn_id != _tinker_spawn_id:
            return
        if i >= n:
            return

        end = min(i + batch, n)
        for j in range(i, end):
            text = phrases[j % len(phrases)]
            w = TINKER_W + random.randint(-30, 50)
            h = TINKER_H + random.randint(-8, 18)
            x, y = tinker_random_pos(sw, sh, w, h, margin=margin)
            speed = random.uniform(TINKER_SPEED_MIN, TINKER_SPEED_MAX)
            angle = random.uniform(0, math.tau)
            vx = speed * (1 if random.random() < 0.5 else -1) * max(0.35, abs(math.cos(angle)))
            vy = speed * (1 if random.random() < 0.5 else -1) * max(0.35, abs(math.sin(angle)))
            if abs(vx) < 0.15:
                vx = 0.15 if vx >= 0 else -0.15
            if abs(vy) < 0.15:
                vy = 0.15 if vy >= 0 else -0.15

            TinkerTile(root, text, x, y, w, h, vx, vy, sw, sh)

        if _tinker_anim_id is None and _active_tinker_windows:
            _tinker_anim_id = root.after(int(1000 / TINKER_FPS), _tinker_animate)

        root.after(TINKER_SPAWN_MS, lambda: spawn(end))

    spawn(0)


# ── close helpers ─────────────────────────────────────────────────────────────

def close_sbs_windows(root, windows):
    for win in windows:
        win.cancel_hold()
        win.close()          # destroy immediately, not via after()


def close_all_sbs(root):
    global _active_sbs_windows
    to_close = list(_active_sbs_windows)
    _active_sbs_windows = []
    close_sbs_windows(root, to_close)


def close_all_sentences(root):
    global _active_sentence_windows
    to_close = list(_active_sentence_windows)
    _active_sentence_windows = []
    for win in to_close:
        win.close()          # destroy immediately, not via after()


def close_all_shouts(root):
    global _active_shout_windows, _shout_spawn_id
    _shout_spawn_id += 1   # cancel any pending collage spawns
    to_close = list(_active_shout_windows)
    _active_shout_windows = []
    for win in to_close:
        win.close()


def close_all_tinkers(root):
    """Stop animation first, then withdraw/destroy — avoids macOS Tk segfaults."""
    global _active_tinker_windows, _tinker_spawn_id
    _tinker_spawn_id += 1  # cancel any pending tinker spawns
    _stop_tinker_animator(root)

    to_close = list(_active_tinker_windows)
    _active_tinker_windows = []
    if not to_close:
        return

    for tile in to_close:
        tile._alive = False
        try:
            tile.win.withdraw()
        except tk.TclError:
            pass

    try:
        root.update_idletasks()
    except tk.TclError:
        pass

    # Destroy one-by-one on the next idle passes so Aqua isn't hit all at once
    def _destroy_next(i=0):
        if i >= len(to_close):
            return
        try:
            to_close[i].win.destroy()
        except tk.TclError:
            pass
        root.after(20, lambda: _destroy_next(i + 1))

    _destroy_next(0)


def close_all_windows(root, include_tinkers=False):
    """Close lyric windows. Tinkers stay up unless include_tinkers=True."""
    close_all_sbs(root)
    close_all_sentences(root)
    close_all_shouts(root)
    if include_tinkers:
        close_all_tinkers(root)


# ── sbs orchestration ─────────────────────────────────────────────────────────

def show_side_by_side(root, words, delay, hold, size=None, y_offset=0,
                      gap=None, keep_previous=False, type_speed=None):
    """
    Opens each panel one-by-one: next panel appears only after the previous
    finishes typing (plus `delay` seconds pause). All panels share the same
    fixed size so they look uniform.
    """
    global _active_sbs_windows

    setup_start = time.time()  # track time spent in setup so sleep stays accurate

    if not keep_previous:
        close_all_sbs(root)

    if gap is None:
        gap = SBS_GAP

    ts = type_speed or SBS_TYPE_SPEED

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    # Always measure every phrase so all panels match the biggest one.
    # The explicit `size` tuple (if given) acts as a minimum floor.
    # NOTE: sbs_word_size spins up a temp Tk window — do it all up front so
    # the time is accounted for before we calculate the sleep duration.
    measured = [sbs_word_size(word) for word in words]
    max_w = max(w for w, _ in measured)
    max_h = max(h for _, h in measured)
    if size:
        floor_w, floor_h = size
        max_w = max(max_w, floor_w)
        max_h = max(max_h, floor_h)
    panel_size = (max_w, max_h)

    pw, ph = panel_size
    layout_w = pw + SBS_FRAME_PAD

    total   = layout_w * len(words) + gap * (len(words) - 1)
    start_x = (sw - total) // 2

    x_positions = [start_x + i * (layout_w + gap) for i in range(len(words))]

    windows = []

    def open_panel(i):
        if i >= len(words):
            if hold is not None:
                # Store the after-id on each window so cancel_hold() can kill it
                hold_id = root.after(int(hold * 1000), lambda: close_sbs_windows(root, list(windows)))
                for w in windows:
                    w._hold_id = hold_id
            return

        word = words[i]
        wx   = x_positions[i]
        y    = (sh - ph) // 2 + y_offset

        def on_typed(idx=i):
            root.after(int(delay * 1000), lambda: open_panel(idx + 1))

        win = SideBySideWindow(root, word, wx, y, size=panel_size,
                               type_speed=ts, on_typed=on_typed)
        windows.append(win)
        _active_sbs_windows.append(win)

    root.after(0, lambda: open_panel(0))

    # How long the animation will actually take
    total_typing_s = sum(len(w) * ts for w in words)
    total_delay_s  = delay * (len(words) - 1)
    total_hold_s   = hold if hold is not None else 0
    needed_s       = total_typing_s + total_delay_s + total_hold_s

    # Subtract time already spent in setup (measuring, etc.) so the next
    # lyric line fires on schedule rather than late
    elapsed = time.time() - setup_start
    sleep_s = max(0.0, needed_s - elapsed)
    time.sleep(sleep_s)

    for win in list(windows):
        if win in _active_sbs_windows:
            _active_sbs_windows.remove(win)


# ── main scheduler ────────────────────────────────────────────────────────────

def run_lyrics(root):
    start = time.time()

    def worker():
        for i, entry in enumerate(LYRICS):
            ts   = entry[0]
            line = entry[1]

            now  = time.time() - start
            wait = ts - now
            if wait > 0:
                time.sleep(wait)
            is_tinker = isinstance(line, dict) and "tinker" in line
            if not is_tinker:
                closed = threading.Event()
                def _close_and_signal():
                    close_all_windows(root)  # leaves tinkers alone
                    closed.set()
                root.after(0, _close_and_signal)
                closed.wait(timeout=1.0)
                time.sleep(0.08)

            next_ts = LYRICS[i + 1][0] if i + 1 < len(LYRICS) else None
            gap_to_next = (next_ts - ts) if next_ts is not None else None

            if isinstance(line, dict) and "shout" in line:
                hold = entry[2] if len(entry) > 2 else WORD_HOLD
                def show(s=line["shout"], h=hold):
                    show_shout_collage(root, s, h)
                root.after(0, show)

            elif isinstance(line, dict) and "linger" in line:
                hold = entry[2] if len(entry) > 2 else None
                def show(s=line["linger"], h=hold):
                    SentenceWindow(root, s, h, w=520, type_speed=0.07,
                                   centered=True, font_size=28)
                root.after(0, show)

            elif isinstance(line, dict) and "slam" in line:
                hold = entry[2] if len(entry) > 2 else 3.5
                def show(s=line["slam"], h=hold):
                    SlamWindow(root, s, h, type_speed=0.085)
                root.after(0, show)

            elif isinstance(line, dict) and "tinker" in line:
                hold = entry[2] if len(entry) > 2 else None
                count = entry[3] if len(entry) > 3 else None
                def show(p=line["tinker"], h=hold, c=count):
                    show_tinker_swarm(root, p, h, count=c)
                root.after(0, show)

            elif isinstance(line, list):
                delay      = entry[2] if len(entry) > 2 else 0.3
                hold       = entry[3] if len(entry) > 3 else SBS_HOLD
                size       = entry[4] if len(entry) > 4 else None
                y_off      = entry[5] if len(entry) > 5 else 0
                sbs_gap    = entry[6] if len(entry) > 6 else None
                keep_prev  = entry[7] if len(entry) > 7 else False
                type_speed = entry[8] if len(entry) > 8 else SBS_TYPE_SPEED

                # Auto-fit hold so the whole SBS sequence (typing + inter-panel
                # delays + hold) fills exactly the gap to the next timestamp.
                # The hold value in the tuple is ignored when a next line exists.
                if gap_to_next is not None:
                    ts_used  = type_speed or SBS_TYPE_SPEED
                    typing_s = sum(len(w) * ts_used for w in line)
                    delays_s = delay * (len(line) - 1)
                    hold     = max(0.0, gap_to_next - typing_s - delays_s)

                show_side_by_side(root, line, delay, hold, size, y_off,
                                  sbs_gap, keep_prev, type_speed)
            else:
                hold       = entry[2] if len(entry) > 2 else WORD_HOLD
                w          = entry[3] if len(entry) > 3 else LINE_W
                type_speed = entry[4] if len(entry) > 4 else TYPE_SPEED

                def show(s=line, h=hold, ww=w, ts=type_speed):
                    SentenceWindow(root, s, h, w=ww, type_speed=ts)
                root.after(0, show)

    t = threading.Thread(target=worker, daemon=True)
    t.start()


def main():
    root = tk.Tk()
    apply_window_style(root, title="stupid song")
    root.withdraw()
    run_lyrics(root)
    root.mainloop()


if __name__ == "__main__":
    main()
