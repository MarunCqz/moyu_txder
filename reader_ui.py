"""Reader UI v3 – system tray, clickable transparency, native-feel resize."""

import os
import sys
import json
import glob
import traceback
import tkinter as tk
from tkinter import filedialog, colorchooser, messagebox, simpledialog
from datetime import datetime

from file_handler import FileHandler

# ── Paths ──────────────────────────────────────────────────────

def _app_dir():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    os.makedirs(d, exist_ok=True)
    return d

PROGRESS_FILE = os.path.join(_app_dir(), 'progress.json')
TRANS = '#010203'   # sentinel colour for transparent-background pixels

# ── System Tray (Windows only, ctypes) ─────────────────────────

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes

    # WPARAM / LPARAM are pointer-sized unsigned / signed ints
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _WPARAM = ctypes.c_ulonglong
        _LPARAM = ctypes.c_longlong
    else:
        _WPARAM = ctypes.c_ulong
        _LPARAM = ctypes.c_long

    _WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
        _WPARAM, _LPARAM)

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [
            ('cbSize',           wintypes.DWORD),
            ('hWnd',             wintypes.HWND),
            ('uID',              wintypes.UINT),
            ('uFlags',           wintypes.UINT),
            ('uCallbackMessage', wintypes.UINT),
            ('hIcon',            wintypes.HICON),
            ('szTip',            ctypes.c_wchar * 128),
            ('dwState',          wintypes.DWORD),
            ('dwStateMask',      wintypes.DWORD),
            ('szInfo',           ctypes.c_wchar * 256),
            ('uTimeoutOrVersion', wintypes.UINT),
            ('szInfoTitle',      ctypes.c_wchar * 64),
            ('dwInfoFlags',      wintypes.DWORD),
        ]

    NIM_ADD      = 0x00000000
    NIM_DELETE   = 0x00000002
    NIF_MESSAGE  = 0x00000001
    NIF_ICON     = 0x00000002
    NIF_TIP      = 0x00000004
    NIF_STATE    = 0x00000008
    NIS_HIDDEN   = 0x00000001

    WM_USER      = 0x0400
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONUP = 0x0205

    GWL_WNDPROC  = -4
    GWL_EXSTYLE  = -20
    WS_EX_TRANSPARENT = 0x00000020
    WM_NCHITTEST = 0x0084
    HTCLIENT     = 1


class SystemTrayIcon:
    """Minimal system-tray icon via Shell_NotifyIcon (Windows only).

    Falls back silently on non-Windows or if anything fails.
    """

    def __init__(self, root, title='TXT Reader'):
        self.root = root
        self.title = title
        self._nid = None
        self._old_wndproc = None
        self._new_wndproc_ref = None
        self._clicked = False
        self._rclicked = False
        self._visible = False

    # ── public API ──────────────────────────────────────────────

    def show(self, on_left_click=None, on_right_click=None):
        """Add the tray icon.  Callbacks receive no arguments."""
        if sys.platform != 'win32':
            return
        self._on_left = on_left_click
        self._on_right = on_right_click
        try:
            self._add_icon()
            self.root.after(300, self._poll)
            self._visible = True
        except Exception:
            pass

    def hide(self):
        """Remove the tray icon."""
        if not self._visible:
            return
        try:
            self._del_icon()
            self._restore_wndproc()
        except Exception:
            pass
        self._visible = False

    # ── internals ───────────────────────────────────────────────

    def _add_icon(self):
        hwnd = self.root.winfo_id()
        self._uid = 1
        self._cb_msg = WM_USER + 0x200

        # load default application icon
        IDI_APPLICATION = 32512
        LR_SHARED = 0x00008000
        hicon = ctypes.windll.user32.LoadImageW(0, IDI_APPLICATION,
                                                 1, 16, 16, LR_SHARED)

        # subclass window proc
        self._old_wndproc = ctypes.windll.user32.GetWindowLongW(
            hwnd, GWL_WNDPROC)
        self._new_wndproc_ref = _WNDPROC(self._wnd_proc)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_WNDPROC, self._new_wndproc_ref)

        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = hwnd
        nid.uID = self._uid
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self._cb_msg
        nid.hIcon = hicon
        nid.szTip = self.title
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._nid = nid

    def _del_icon(self):
        if self._nid:
            ctypes.windll.shell32.Shell_NotifyIconW(
                NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None

    def _restore_wndproc(self):
        if self._old_wndproc is not None:
            hwnd = self.root.winfo_id()
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_WNDPROC, self._old_wndproc)
            self._old_wndproc = None
            self._new_wndproc_ref = None

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == self._cb_msg:
            if lparam == WM_LBUTTONUP:
                self._clicked = True
            elif lparam == WM_RBUTTONUP:
                self._rclicked = True
            return 0
        return ctypes.windll.user32.CallWindowProcW(
            self._old_wndproc, hwnd, msg, wparam, lparam)

    def _poll(self):
        if not self._visible:
            return
        if self._clicked:
            self._clicked = False
            if self._on_left:
                self._on_left()
        if self._rclicked:
            self._rclicked = False
            if self._on_right:
                self._on_right()
        self.root.after(300, self._poll)


# ── Progress Manager ───────────────────────────────────────────

class ProgressManager:
    """Persists reading progress to a JSON file."""

    def __init__(self):
        self._path = PROGRESS_FILE
        self.data = self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save(self):
        try:
            with open(self._path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_last_session(self):
        return self.data.get('_last_session')

    def set_last_session(self, filepath, byte_offset):
        self.data['_last_session'] = {
            'filepath': filepath,
            'byte_offset': byte_offset,
        }
        self._save()

    def get_saves(self, filepath):
        return self.data.get(os.path.abspath(filepath), [])

    def add_save(self, filepath, byte_offset, name=''):
        key = os.path.abspath(filepath)
        entry = {
            'byte_offset': byte_offset,
            'timestamp': datetime.now().isoformat(),
            'name': name,
        }
        self.data.setdefault(key, []).append(entry)
        self.set_last_session(filepath, byte_offset)
        return entry

    def delete_save(self, filepath, index):
        key = os.path.abspath(filepath)
        if key in self.data and 0 <= index < len(self.data[key]):
            del self.data[key][index]
            self._save()


# ── Reader Application ─────────────────────────────────────────

class ReaderApp:
    """Borderless text reader with system-tray minimise and clickable
    transparent background."""

    EDGE = 8          # px — invisible resize border width

    def __init__(self):
        self.fh = FileHandler()
        self.pm = ProgressManager()

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.configure(bg=TRANS)
        self.root.attributes('-transparentcolor', TRANS)
        self.root.attributes('-alpha', 1.0)

        # ── state ───────────────────────────────────────────────
        self.top_line = 0
        self.font_color = '#FFFFFF'
        self.bg_color = '#000000'
        self.font_family = 'SimHei'
        self.font_fallback = 'Microsoft YaHei'
        self.font_size = 14
        self.line_height = 22
        self._hovering = False
        self._controls_up = False
        self._info_up = False
        self._on_top = False

        # system tray
        self.tray = SystemTrayIcon(self.root, 'TXT Reader')

        # global exception handler — critical for pyinstaller -w builds
        self.root.report_callback_exception = self._on_unhandled_error

        self._calc_line_height()
        self._build_ui()
        self._build_context_menu()
        self._bind_events()

        # fix click-through & apply borderless
        self.root.after(50, self._apply_borderless_style)
        self.root.after(100, self._load_last_session)

    # ── helpers ─────────────────────────────────────────────────

    def _calc_line_height(self):
        self.line_height = max(16, int(self.font_size * 1.55))

    # ── UI Construction ─────────────────────────────────────────

    def _build_ui(self):
        self.canvas = tk.Canvas(
            self.root, bg=TRANS, highlightthickness=0, bd=0, cursor='xterm')
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # control overlay (top, placed on hover)
        self._ctrl_h = 34
        self.ctrl_frame = tk.Frame(self.root, bg='#2d2d2d', height=self._ctrl_h)
        self.ctrl_frame.pack_propagate(False)
        self._build_control_bar()

        # info overlay (bottom, placed on hover)
        self._info_h = 24
        self.info_frame = tk.Frame(self.root, bg='#252525', height=self._info_h)
        self.info_frame.pack_propagate(False)
        self.info_var = tk.StringVar(value='')
        self.info_lbl = tk.Label(
            self.info_frame, textvariable=self.info_var,
            bg='#252525', fg='#999999',
            font=('Microsoft YaHei', 9), anchor=tk.W)
        self.info_lbl.pack(fill=tk.BOTH, expand=True, padx=8)

    def _build_control_bar(self):
        B = {
            'bg': '#3d3d3d', 'fg': '#cccccc', 'relief': tk.FLAT,
            'font': ('Microsoft YaHei', 9), 'padx': 8, 'pady': 2,
            'activebackground': '#555555', 'activeforeground': '#ffffff',
            'cursor': 'hand2', 'bd': 0,
        }
        self.btn_open = tk.Button(self.ctrl_frame, text='Open', command=self._on_open, **B)
        self.btn_open.pack(side=tk.LEFT, padx=(6, 1), pady=4)
        self.btn_save = tk.Button(self.ctrl_frame, text='Save', command=self._on_save, **B)
        self.btn_save.pack(side=tk.LEFT, padx=1, pady=4)
        self.btn_load = tk.Button(self.ctrl_frame, text='Progress', command=self._on_load_progress, **B)
        self.btn_load.pack(side=tk.LEFT, padx=1, pady=4)

        tk.Label(self.ctrl_frame, text='  Font:', bg='#2d2d2d', fg='#999999',
                 font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(10, 0))
        self.btn_font = tk.Button(self.ctrl_frame, text='Color', command=self._on_font_color, **B)
        self.btn_font.pack(side=tk.LEFT, padx=1, pady=4)
        tk.Label(self.ctrl_frame, text='BG:', bg='#2d2d2d', fg='#999999',
                 font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(6, 0))
        self.btn_bg = tk.Button(self.ctrl_frame, text='Color', command=self._on_bg_color, **B)
        self.btn_bg.pack(side=tk.LEFT, padx=1, pady=4)
        self.btn_bg_trans = tk.Button(self.ctrl_frame, text='Transparent',
                                      command=self._on_bg_transparent, **B)
        self.btn_bg_trans.pack(side=tk.LEFT, padx=1, pady=4)
        tk.Label(self.ctrl_frame, text='Size:', bg='#2d2d2d', fg='#999999',
                 font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(8, 0))
        self.size_var = tk.IntVar(value=self.font_size)
        self.size_spin = tk.Spinbox(
            self.ctrl_frame, from_=8, to=48, width=3,
            textvariable=self.size_var, command=self._on_font_change,
            bg='#3d3d3d', fg='#cccccc', buttonbackground='#4d4d4d',
            relief=tk.FLAT, font=('Consolas', 10), bd=0)
        self.size_spin.pack(side=tk.LEFT, padx=3, pady=4)

        self.top_var = tk.BooleanVar(value=False)
        self.btn_top = tk.Button(self.ctrl_frame, text='Pin', command=self._on_toggle_top, **B)
        self.btn_top.pack(side=tk.RIGHT, padx=1, pady=4)
        self.btn_close = tk.Button(
            self.ctrl_frame, text='X', command=self._on_close,
            bg='#3d3d3d', fg='#cc8888', relief=tk.FLAT,
            font=('Microsoft YaHei', 10, 'bold'), padx=10, pady=2,
            activebackground='#883333', activeforeground='#ffffff',
            cursor='hand2', bd=0)
        self.btn_close.pack(side=tk.RIGHT, padx=(0, 4), pady=4)

    # ── Context menu ────────────────────────────────────────────

    def _build_context_menu(self):
        self.ctx_menu = tk.Menu(self.root, tearoff=0, bg='#2d2d2d', fg='#cccccc',
                                activebackground='#4a6a8a', activeforeground='#ffffff',
                                font=('Microsoft YaHei', 10))
        self.ctx_menu.add_command(label='Open', command=self._on_open)
        self.ctx_menu.add_command(label='Save Progress', command=self._on_save)
        self.ctx_menu.add_command(label='Load Progress', command=self._on_load_progress)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label='Font Color', command=self._on_font_color)
        self.ctx_menu.add_command(label='Background Color', command=self._on_bg_color)
        self.ctx_menu.add_command(label='Background Transparent', command=self._on_bg_transparent)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_checkbutton(label='Always on Top', variable=self.top_var,
                                      command=self._on_toggle_top)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label='Minimize to Tray', command=self._on_minimize)
        self.ctx_menu.add_command(label='Close', command=self._on_close)

    # ── Overlay show / hide ─────────────────────────────────────

    def _show_overlays(self):
        w = self.root.winfo_width()
        if not self._controls_up:
            self.ctrl_frame.place(x=0, y=0, width=w, height=self._ctrl_h)
            self._controls_up = True
        if not self._info_up:
            h = self.root.winfo_height()
            self.info_frame.place(x=0, y=h - self._info_h, width=w, height=self._info_h)
            self._info_up = True

    def _hide_overlays(self):
        if self._controls_up:
            self.ctrl_frame.place_forget()
            self._controls_up = False
        if self._info_up:
            self.info_frame.place_forget()
            self._info_up = False

    # ── Event Binding ───────────────────────────────────────────

    def _bind_events(self):
        self.root.bind('<Enter>', self._on_enter)
        self.root.bind('<Leave>', self._on_leave)

        # scroll
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind('<Button-4>', lambda e: self._scroll(-3))
        self.canvas.bind('<Button-5>', lambda e: self._scroll(3))
        self.canvas.bind('<Configure>', self._on_resize)

        # window drag / resize — bound to ROOT so events fire even
        # when the mouse leaves the canvas (critical for edge-resize).
        self.root.bind('<Button-1>', self._drag_start)
        self.root.bind('<B1-Motion>', self._drag_motion)
        self.root.bind('<ButtonRelease-1>', self._drag_stop)

        # right-click
        self.canvas.bind('<Button-3>', self._on_right_click)

        # keyboard
        self.root.bind('<Up>', lambda e: self._scroll(-1))
        self.root.bind('<Down>', lambda e: self._scroll(1))
        self.root.bind('<Prior>', lambda e: self._page(-1))
        self.root.bind('<Next>', lambda e: self._page(1))
        self.root.bind('<Home>', lambda e: self._go_start())
        self.root.bind('<End>', lambda e: self._go_end())
        self.root.bind('<Control-o>', lambda e: self._on_open())
        self.root.bind('<Control-s>', lambda e: self._on_save())
        self.root.bind('<Control-l>', lambda e: self._on_load_progress())
        self.root.bind('<Escape>', lambda e: self._on_minimize())
        self.root.bind('<Control-q>', lambda e: self._on_close())

    def _on_enter(self, event):
        self._hovering = True
        self._show_overlays()

    def _on_leave(self, event):
        x, y = self.root.winfo_pointerxy()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        if not (rx <= x <= rx + rw and ry <= y <= ry + rh):
            self._hovering = False
            self._hide_overlays()

    def _on_mousewheel(self, event):
        self._scroll(-1 if event.delta > 0 else 1)

    # ── window drag / resize (screen-coordinate based) ──────────

    def _drag_start(self, event):
        x, y = event.x, event.y
        w, h = self.root.winfo_width(), self.root.winfo_height()
        e = self.EDGE

        # work out which edge(s) the click landed on
        L, R, T, B = x < e, x > w - e, y < e, y > h - e

        self._drag_mode = 'move'
        if R: self._drag_mode = 'e'
        if L: self._drag_mode = 'w'
        if B: self._drag_mode = 's' if not (L or R) else self._drag_mode + 's'
        if T: self._drag_mode = 'n' if not (L or R) else self._drag_mode + 'n'

        # record origin (screen coords for robustness)
        self._d_ox = event.x_root
        self._d_oy = event.y_root
        self._d_x0 = self.root.winfo_x()
        self._d_y0 = self.root.winfo_y()
        self._d_w0 = w
        self._d_h0 = h

    def _drag_motion(self, event):
        if not hasattr(self, '_drag_mode'):
            return
        dx = event.x_root - self._d_ox
        dy = event.y_root - self._d_oy
        mode = self._drag_mode
        min_w, min_h = 320, 200

        if mode == 'move':
            self.root.geometry(
                f'+{self._d_x0 + dx}+{self._d_y0 + dy}')
            return

        new_w, new_h = self._d_w0, self._d_h0
        new_x, new_y = self._d_x0, self._d_y0

        if 'e' in mode:
            new_w = max(min_w, self._d_w0 + dx)
        elif 'w' in mode:
            new_w = max(min_w, self._d_w0 - dx)
            new_x = self._d_x0 + (self._d_w0 - new_w)
        if 's' in mode:
            new_h = max(min_h, self._d_h0 + dy)
        elif 'n' in mode:
            new_h = max(min_h, self._d_h0 - dy)
            new_y = self._d_y0 + (self._d_h0 - new_h)

        self.root.geometry(f'{new_w}x{new_h}+{new_x}+{new_y}')

    def _drag_stop(self, event):
        self._drag_mode = 'move'

    def _on_resize(self, event):
        if event.widget == self.canvas:
            self._render()
            self._reposition_overlays()

    def _reposition_overlays(self):
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if self._controls_up:
            self.ctrl_frame.place(x=0, y=0, width=w, height=self._ctrl_h)
        if self._info_up:
            self.info_frame.place(x=0, y=h - self._info_h, width=w, height=self._info_h)

    # ── right-click ─────────────────────────────────────────────

    def _on_right_click(self, event):
        self.ctx_menu.tk_popup(event.x_root, event.y_root)

    # ── Navigation ──────────────────────────────────────────────

    def _visible(self):
        return max(1, (self.canvas.winfo_height() - 4) // self.line_height)

    def _scroll(self, delta):
        if self.fh.line_count == 0:
            return
        limit = max(0, self.fh.line_count - self._visible())
        self.top_line = max(0, min(self.top_line + delta, limit))
        self._render()

    def _page(self, direction):
        self._scroll(direction * self._visible())

    def _go_start(self):
        self.top_line = 0; self._render()

    def _go_end(self):
        self.top_line = max(0, self.fh.line_count - self._visible())
        self._render()

    def _go_to_offset(self, byte_offset):
        line = self.fh.offset_to_line(byte_offset)
        self.top_line = max(0, line - self._visible() // 4)
        self._render()

    # ── Rendering ───────────────────────────────────────────────

    def _render(self):
        self.canvas.delete('all')
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()

        if self.bg_color != TRANS and w > 0 and h > 0:
            self.canvas.create_rectangle(0, 0, w, h, fill=self.bg_color,
                                         outline='', width=0)

        if not self.fh.filepath or self.fh.line_count == 0:
            self._draw_welcome()
            self._update_info()
            return

        visible = self._visible()
        lines = self.fh.get_lines(self.top_line, visible + 2)
        if not lines:
            self._update_info()
            return

        if self.bg_color == TRANS:
            self._render_transparent(lines, w, h)
        else:
            self._render_solid(lines)

        self._update_info()

    # ── Render: solid background ──────────────────────────────────

    def _render_solid(self, lines):
        """Per-line rendering — no anti-aliasing artefacts on opaque bg."""
        y = 2
        limit = 2000
        font = (self.font_family, self.font_size)
        for text in lines:
            display = text.replace('\t', '    ')
            if len(display) > limit:
                display = display[:limit]
            self.canvas.create_text(6, y, text=display, anchor=tk.NW,
                                    fill=self.font_color, font=font)
            y += self.line_height

    # ── Render: transparent background ────────────────────────────

    def _render_transparent(self, lines, w, h):
        """Try PIL for proper alpha rendering; fall back to batched text."""
        try:
            self._render_with_pil(lines, w, h)
        except ImportError:
            self._render_transparent_fallback(lines)

    def _render_with_pil(self, lines, w, h):
        """Render text with Pillow for clean anti-aliasing on transparent bg."""
        from PIL import Image, ImageDraw, ImageFont, ImageTk

        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = self._get_pil_font()

        y = 2
        limit = 2000
        for text in lines:
            display = text.replace('\t', '    ')
            if len(display) > limit:
                display = display[:limit]
            draw.text((6, y), display, fill=self.font_color, font=font)
            y += self.line_height

        self._pil_photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, image=self._pil_photo, anchor=tk.NW)

    def _render_transparent_fallback(self, lines):
        """Single multi-line create_text — fewer artefacts than per-line."""
        processed = []
        limit = 2000
        for text in lines:
            display = text.replace('\t', '    ')
            if len(display) > limit:
                display = display[:limit]
            processed.append(display)
        combined = '\n'.join(processed)
        self.canvas.create_text(6, 2, text=combined, anchor=tk.NW,
                                fill=self.font_color,
                                font=(self.font_family, self.font_size))

    def _get_pil_font(self):
        """Locate a TTF for the current font family, falling back to default."""
        from PIL import ImageFont

        size = self.font_size
        font_name = self.font_family

        # Font family → Windows filename mapping
        name_map = {
            'SimHei':           ['simhei.ttf'],
            'Microsoft YaHei':  ['msyh.ttf', 'msyh.ttc', 'msyhbd.ttf'],
            'SimSun':           ['simsun.ttc', 'simsun.ttf'],
            'KaiTi':            ['kaiti.ttf'],
            'FangSong':         ['fangsong.ttf'],
            'Consolas':         ['consola.ttf', 'consolab.ttf'],
            'Arial':            ['arial.ttf'],
            'Courier New':      ['cour.ttf', 'courbd.ttf'],
        }

        candidates = name_map.get(font_name, [
            font_name + '.ttf',
            font_name + '.ttc',
            font_name.lower() + '.ttf',
        ])

        fonts_dir = os.path.join(
            os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')

        if os.path.isdir(fonts_dir):
            # Try exact matches first
            for cand in candidates:
                path = os.path.join(fonts_dir, cand)
                if os.path.exists(path):
                    return ImageFont.truetype(path, size)

            # Fallback: glob for partial matches
            for cand in candidates:
                base = os.path.splitext(cand)[0].lower()
                pattern = os.path.join(fonts_dir, base + '.*')
                matches = glob.glob(pattern)
                if matches:
                    return ImageFont.truetype(matches[0], size)

            # Broad sweep — try any font containing the family name
            try:
                for entry in os.listdir(fonts_dir):
                    low = entry.lower()
                    if (low.endswith(('.ttf', '.ttc')) and
                            font_name.lower().replace(' ', '') in low.replace(' ', '')):
                        return ImageFont.truetype(
                            os.path.join(fonts_dir, entry), size)
            except Exception:
                pass

        # Last resort: arial.ttf on Windows, or PIL default
        arial = os.path.join(fonts_dir, 'arial.ttf')
        if os.path.exists(arial):
            return ImageFont.truetype(arial, size)

        return ImageFont.load_default()

    def _draw_welcome(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w > 50 and h > 50:
            # visible colour against the current background
            if self.bg_color == TRANS:
                color = '#AAAAAA'
            elif self._is_light_bg():
                color = '#222222'
            else:
                color = '#CCCCCC'
            self.canvas.create_text(
                w // 2, h // 2,
                text=('No file loaded.\n\n'
                      'Ctrl+O  Open    Ctrl+S  Save\n'
                      'Ctrl+L  Progress\n'
                      'Right-click for menu\n\n'
                      '未加载文件'),
                fill=color, font=(self.font_family, 12), justify=tk.CENTER)

    def _is_light_bg(self):
        try:
            r = int(self.bg_color[1:3], 16)
            g = int(self.bg_color[3:5], 16)
            b = int(self.bg_color[5:7], 16)
            return (r * 299 + g * 587 + b * 114) / 1000 > 128
        except Exception:
            return False

    def _update_info(self):
        if not self.fh.filepath:
            self.info_var.set('No file loaded')
            return
        total = self.fh.line_count
        offset = self.fh.line_to_offset(self.top_line)
        pct = self.fh.progress_percent(offset)
        fname = os.path.basename(self.fh.filepath)
        self.info_var.set(
            f'  Ln {self.top_line + 1:,} / {total:,}  |  {pct:.1f}%  |  {fname}')

    # ── File Operations ─────────────────────────────────────────

    def _load_file(self, filepath):
        try:
            self.root.config(cursor='watch')
            self.root.update()
            self.fh.load_file(filepath)
            self.top_line = 0
            self._render()
            self.pm.set_last_session(filepath, 0)
        except Exception as e:
            messagebox.showerror('Error', f'Failed to open file:\n{e}')
        finally:
            self.root.config(cursor='')

    def _load_last_session(self):
        last = self.pm.get_last_session()
        if last and os.path.exists(last['filepath']):
            self._load_file(last['filepath'])
            offset = last.get('byte_offset', 0)
            if offset > 0:
                self.root.after(200, lambda: self._go_to_offset(offset))
        else:
            self._render()

    def _on_open(self):
        path = filedialog.askopenfilename(
            title='Open Text File',
            filetypes=[('Text Files', '*.txt'), ('All Files', '*.*')])
        if path and os.path.exists(path):
            self._load_file(path)

    def _on_close(self):
        if self.fh.filepath:
            offset = self.fh.line_to_offset(self.top_line)
            self.pm.set_last_session(self.fh.filepath, offset)
        self.tray.hide()
        # Restore the original window procedure before destroying
        if sys.platform == 'win32' and hasattr(self, '_old_wndproc'):
            try:
                hwnd = self.root.winfo_id()
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_WNDPROC, self._old_wndproc)
            except Exception:
                pass
        self.root.destroy()

    # ── Borderless + click-through fix ─────────────────────────

    def _apply_borderless_style(self):
        """Strip WS_EX_TRANSPARENT so transparent-colour pixels still
        receive mouse events, and subclass the window procedure to
        return HTCLIENT for every WM_NCHITTEST — this guarantees clicks
        land on the window even over colour-keyed regions."""
        self.root.update_idletasks()
        if sys.platform != 'win32':
            return
        try:
            hwnd = self.root.winfo_id()

            # ── strip WS_EX_TRANSPARENT ───────────────────────────
            exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            exstyle &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)

            # ── WM_NCHITTEST subclass ─────────────────────────────
            self._old_wndproc = ctypes.windll.user32.GetWindowLongW(
                hwnd, GWL_WNDPROC)

            def hit_test_proc(hwnd, msg, wparam, lparam):
                if msg == WM_NCHITTEST:
                    return HTCLIENT
                return ctypes.windll.user32.CallWindowProcW(
                    self._old_wndproc, hwnd, msg, wparam, lparam)

            self._hit_wndproc_ref = _WNDPROC(hit_test_proc)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_WNDPROC, self._hit_wndproc_ref)
        except Exception:
            pass

    # ── System tray minimize ────────────────────────────────────

    def _on_minimize(self):
        """Minimise to system tray instead of taskbar."""
        if sys.platform != 'win32':
            try:
                self.root.iconify()
            except Exception:
                self.root.withdraw()
            return
        self.root.withdraw()
        self.tray.show(on_left_click=self._restore_from_tray,
                       on_right_click=self._tray_right_click)

    def _restore_from_tray(self):
        self.tray.hide()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _tray_right_click(self):
        """Pop a small menu at the cursor for tray right-click."""
        menu = tk.Menu(self.root, tearoff=0, bg='#2d2d2d', fg='#cccccc',
                       font=('Microsoft YaHei', 10))
        menu.add_command(label='Restore', command=self._restore_from_tray)
        menu.add_command(label='Close', command=self._on_close)
        menu.tk_popup(*self.root.winfo_pointerxy())

    # ── Error handler ───────────────────────────────────────────

    def _on_unhandled_error(self, exc, val, tb):
        msg = ''.join(traceback.format_exception(exc, val, tb))
        try:
            with open(os.path.join(_app_dir(), 'error.log'), 'a', encoding='utf-8') as f:
                f.write(f'[{datetime.now().isoformat()}] {msg}\n')
        except Exception:
            pass
        try:
            messagebox.showerror(
                'TXT Reader Error',
                f'An unexpected error occurred:\n\n{val}\n\n'
                f'Details written to data/error.log')
        except Exception:
            pass

    # ── Appearance ──────────────────────────────────────────────

    def _on_font_color(self):
        result = colorchooser.askcolor(color=self.font_color, title='Choose Font Color')
        if result and result[1]:
            self.font_color = result[1]
            self._render()

    def _on_bg_color(self):
        initial = self.bg_color if self.bg_color != TRANS else '#1e1e1e'
        result = colorchooser.askcolor(color=initial, title='Choose Background Color')
        if result and result[1]:
            self.bg_color = result[1]
            self._render()

    def _on_bg_transparent(self):
        self.bg_color = TRANS
        self._render()

    def _on_font_change(self):
        try:
            self.font_size = self.size_var.get()
            self._calc_line_height()
            self._render()
        except Exception:
            pass

    def _on_toggle_top(self):
        self._on_top = not self._on_top
        self.top_var.set(self._on_top)
        self.root.attributes('-topmost', self._on_top)

    # ── Progress Management ─────────────────────────────────────

    def _on_save(self):
        if not self.fh.filepath:
            messagebox.showinfo('Info', 'Please open a file first.')
            return
        offset = self.fh.line_to_offset(self.top_line)
        line_num = self.top_line + 1
        pct = self.fh.progress_percent(offset)
        name = simpledialog.askstring(
            'Save Progress',
            f'Saving at line {line_num:,} ({pct:.1f}%)\n\nLabel (optional):',
            parent=self.root)
        self.pm.add_save(self.fh.filepath, offset, name or '')
        messagebox.showinfo('Saved', f'Progress saved.\nLine: {line_num:,}  ({pct:.1f}%)')

    def _on_load_progress(self):
        if not self.fh.filepath:
            messagebox.showinfo('Info', 'Please open a file first.')
            return
        saves = self.pm.get_saves(self.fh.filepath)
        if not saves:
            messagebox.showinfo('No Progress',
                                'No saved progress for this file.\n'
                                'Use "Save Progress" to create save points.')
            return
        self._show_progress_dialog(saves)

    def _show_progress_dialog(self, saves):
        dlg = tk.Toplevel(self.root)
        dlg.title('Select Progress')
        dlg.geometry('500x360')
        dlg.configure(bg='#2b2b2b')
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.update_idletasks()
        px = self.root.winfo_rootx() + (self.root.winfo_width() - 500) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - 360) // 2
        dlg.geometry(f'+{px}+{py}')

        tk.Label(dlg, text='Saved Reading Progress', bg='#2b2b2b', fg='#cccccc',
                 font=('Microsoft YaHei', 12, 'bold')).pack(pady=(12, 8))

        frame = tk.Frame(dlg, bg='#2b2b2b')
        frame.pack(fill=tk.BOTH, expand=True, padx=12)
        lb = tk.Listbox(frame, bg='#1e1e1e', fg='#cccccc',
                        selectbackground='#3a5a7a', selectforeground='#ffffff',
                        font=('Consolas', 10), activestyle='none', bd=1, relief=tk.SOLID)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(frame, orient=tk.VERTICAL, command=lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.configure(yscrollcommand=sb.set)

        for i, s in enumerate(reversed(saves)):
            real_idx = len(saves) - 1 - i
            line = self.fh.offset_to_line(s['byte_offset'])
            pct = self.fh.progress_percent(s['byte_offset'])
            ts = s.get('timestamp', '')[:19].replace('T', ' ')
            name = s.get('name', '')
            label = f"#{real_idx + 1}  Ln {line + 1:,}  ({pct:.1f}%)  {ts}"
            if name:
                label += f'  [{name}]'
            lb.insert(tk.END, label)

        btn_frame = tk.Frame(dlg, bg='#2b2b2b')
        btn_frame.pack(pady=10)
        BC = {'bg': '#3a3a3a', 'fg': '#cccccc', 'relief': tk.FLAT,
              'font': ('Microsoft YaHei', 10), 'padx': 16, 'pady': 4,
              'activebackground': '#555555', 'cursor': 'hand2'}

        def go():
            sel = lb.curselection()
            if sel:
                idx = len(saves) - 1 - sel[0]
                self._go_to_offset(saves[idx]['byte_offset'])
                dlg.destroy()

        def delete():
            sel = lb.curselection()
            if sel and messagebox.askyesno('Confirm', 'Delete this save point?', parent=dlg):
                idx = len(saves) - 1 - sel[0]
                self.pm.delete_save(self.fh.filepath, idx)
                dlg.destroy()
                updated = self.pm.get_saves(self.fh.filepath)
                if updated:
                    self._show_progress_dialog(updated)

        tk.Button(btn_frame, text='Go to Position', command=go, **BC).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text='Delete', command=delete,
                  bg='#553333', fg='#cc8888', relief=tk.FLAT,
                  font=('Microsoft YaHei', 10), padx=16, pady=4,
                  activebackground='#774444', cursor='hand2').pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text='Cancel', command=dlg.destroy, **BC).pack(side=tk.LEFT, padx=4)

    # ── Entry ───────────────────────────────────────────────────

    def run(self):
        self.root.geometry('900x650')
        self.root.minsize(320, 200)
        self.root.after(50, self._render)
        self.root.mainloop()
