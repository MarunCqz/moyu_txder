"""Reader UI: virtual text rendering, progress management, transparency effects."""

import os
import json
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
        key = os.path.abspath(filepath)
        return self.data.get(key, [])

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
    """Main reader window with virtual text rendering."""

    def __init__(self):
        self.fh = FileHandler()
        self.pm = ProgressManager()

        self.root = tk.Tk()
        self.root.title('TXT Reader')

        # Display state
        self.top_line = 0
        self.font_color = '#D4D4D4'
        self.font_family = 'Microsoft YaHei'
        self.font_size = 14
        self.line_height = 22

        # Transparency state
        self._hovering = False

        self.root.configure(bg='#1e1e1e')
        self.root.attributes('-alpha', 0.55)

        self._calc_line_height()
        self._build_ui()
        self._bind_events()

        # Auto-load last file after UI settles
        self.root.after(100, self._load_last_session)

    # ── Layout constants ────────────────────────────────────────

    def _calc_line_height(self):
        self.line_height = max(16, int(self.font_size * 1.55))

    # ── UI Construction ─────────────────────────────────────────

    def _build_ui(self):
        self.outer = tk.Frame(self.root, bg='#1e1e1e')
        self.outer.pack(fill=tk.BOTH, expand=True)

        # Control bar
        self._build_control_bar()

        # Content area: canvas + scrollbar
        self.content = tk.Frame(self.outer, bg='#1e1e1e')
        self.content.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            self.content, bg='#1e1e1e', highlightthickness=0,
            bd=0, cursor='xterm',
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbar as a draggable Scale
        self.scroll_var = tk.DoubleVar(value=0)
        self.scrollbar = tk.Scale(
            self.content, from_=100, to=0, orient=tk.VERTICAL,
            variable=self.scroll_var, command=self._on_scrollbar_drag,
            bg='#2a2a2a', fg='#666666', troughcolor='#333333',
            highlightthickness=0, bd=0, showvalue=False,
            width=10, sliderlength=30, sliderrelief=tk.FLAT,
        )
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Info bar at the bottom
        self.info_var = tk.StringVar(value='')
        self.info_label = tk.Label(
            self.outer, textvariable=self.info_var,
            bg='#252525', fg='#777777',
            font=('Microsoft YaHei', 9), anchor=tk.W, padx=8, pady=2,
        )
        self.info_label.pack(fill=tk.X, side=tk.BOTTOM)

        # Start with controls hidden
        self._hide_controls()

    def _build_control_bar(self):
        self.control_bar = tk.Frame(self.outer, bg='#2a2a2a', height=34)
        self.control_bar.pack_propagate(False)

        B = {
            'bg': '#3a3a3a', 'fg': '#cccccc', 'relief': tk.FLAT,
            'font': ('Microsoft YaHei', 9), 'padx': 10, 'pady': 3,
            'activebackground': '#555555', 'activeforeground': '#ffffff',
            'cursor': 'hand2',
        }

        self.btn_open = tk.Button(self.control_bar, text='Open', command=self._on_open, **B)
        self.btn_open.pack(side=tk.LEFT, padx=(8, 2), pady=4)

        self.btn_color = tk.Button(self.control_bar, text='Font Color', command=self._on_color, **B)
        self.btn_color.pack(side=tk.LEFT, padx=2, pady=4)

        self.btn_save = tk.Button(self.control_bar, text='Save Progress', command=self._on_save, **B)
        self.btn_save.pack(side=tk.LEFT, padx=2, pady=4)

        self.btn_load = tk.Button(self.control_bar, text='Load Progress', command=self._on_load_progress, **B)
        self.btn_load.pack(side=tk.LEFT, padx=2, pady=4)

        tk.Label(
            self.control_bar, text='  Size:', bg='#2a2a2a', fg='#999999',
            font=('Microsoft YaHei', 9),
        ).pack(side=tk.LEFT, padx=(12, 0))

        self.size_var = tk.IntVar(value=self.font_size)
        self.size_spin = tk.Spinbox(
            self.control_bar, from_=8, to=48, width=3,
            textvariable=self.size_var, command=self._on_font_change,
            bg='#3a3a3a', fg='#cccccc', buttonbackground='#4a4a4a',
            relief=tk.FLAT, font=('Consolas', 10),
        )
        self.size_spin.pack(side=tk.LEFT, padx=4, pady=4)

    def _show_controls(self):
        if not getattr(self, '_controls_visible', False):
            self.control_bar.pack(before=self.content, fill=tk.X)
            self._controls_visible = True

    def _hide_controls(self):
        if getattr(self, '_controls_visible', False):
            self.control_bar.pack_forget()
            self._controls_visible = False

    # ── Event Binding ───────────────────────────────────────────

    def _bind_events(self):
        self.root.bind('<Enter>', self._on_enter)
        self.root.bind('<Leave>', self._on_leave)
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind('<Button-4>', lambda e: self._scroll(-3))
        self.canvas.bind('<Button-5>', lambda e: self._scroll(3))
        self.canvas.bind('<Configure>', self._on_resize)

        self.root.bind('<Up>', lambda e: self._scroll(-1))
        self.root.bind('<Down>', lambda e: self._scroll(1))
        self.root.bind('<Prior>', lambda e: self._page(-1))
        self.root.bind('<Next>', lambda e: self._page(1))
        self.root.bind('<Home>', lambda e: self._go(0))
        self.root.bind('<End>', lambda e: self._go(-1))
        self.root.bind('<Control-o>', lambda e: self._on_open())
        self.root.bind('<Control-s>', lambda e: self._on_save())
        self.root.bind('<Control-l>', lambda e: self._on_load_progress())
        self.root.bind('<Escape>', lambda e: self.root.iconify())
        self.root.bind('<Control-q>', lambda e: self._on_close())

        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _on_enter(self, event):
        self._hovering = True
        self.root.attributes('-alpha', 0.92)
        self._show_controls()

    def _on_leave(self, event):
        x, y = self.root.winfo_pointerxy()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        if not (rx <= x <= rx + rw and ry <= y <= ry + rh):
            self._hovering = False
            self.root.attributes('-alpha', 0.55)
            self._hide_controls()

    def _on_mousewheel(self, event):
        self._scroll(-1 if event.delta > 0 else 1)

    def _on_resize(self, event):
        if event.widget == self.canvas:
            self._render()

    def _on_scrollbar_drag(self, value):
        pct = float(value)
        if self.fh.line_count > 0:
            self.top_line = int((pct / 100.0) * max(0, self.fh.line_count - self._visible()))
            self._render()

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

    def _go(self, pos):
        if pos == 0:
            self.top_line = 0
        else:
            self.top_line = max(0, self.fh.line_count - self._visible())
        self._render()

    def _go_to_offset(self, byte_offset):
        line = self.fh.offset_to_line(byte_offset)
        self.top_line = max(0, line - self._visible() // 4)
        self._render()

    # ── Rendering ───────────────────────────────────────────────

    def _render(self):
        self.canvas.delete('all')

        if not self.fh.filepath or self.fh.line_count == 0:
            self._draw_welcome()
            self._update_info()
            return

        visible = self._visible()
        lines = self.fh.get_lines(self.top_line, visible + 2)

        if not lines:
            self._update_info()
            return

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

        self._update_info()
        self._update_scrollbar()

    def _draw_welcome(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w > 50 and h > 50:
            self.canvas.create_text(
                w // 2, h // 2,
                text=(
                    'No file loaded.\n\n'
                    'Ctrl+O  Open a text file\n'
                    'Ctrl+S  Save progress\n'
                    'Ctrl+L  Load progress\n'
                    '\n'
                    '未加载文件。\n'
                    'Ctrl+O  打开文件  Ctrl+S  保存进度'
                ),
                fill='#555555', font=(self.font_family, 12), justify=tk.CENTER,
            )

    def _update_info(self):
        if not self.fh.filepath:
            self.info_var.set('No file loaded')
            return

        total = self.fh.line_count
        offset = self.fh.line_to_offset(self.top_line)
        pct = self.fh.progress_percent(offset)
        fname = os.path.basename(self.fh.filepath)
        self.info_var.set(
            f'  Ln {self.top_line + 1:,} / {total:,}  |  {pct:.1f}%  |  {fname}'
        )

    def _update_scrollbar(self):
        if self.fh.line_count > 0:
            pct = (self.top_line / max(1, self.fh.line_count - self._visible())) * 100
            self.scroll_var.set(pct)

    # ── File Operations ─────────────────────────────────────────

    def _load_file(self, filepath):
        try:
            self.root.config(cursor='watch')
            self.root.update()
            self.fh.load_file(filepath)
            self.top_line = 0
            self.root.title(f'TXT Reader - {os.path.basename(filepath)}')
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
            filetypes=[('Text Files', '*.txt'), ('All Files', '*.*')],
        )
        if path and os.path.exists(path):
            self._load_file(path)

    def _on_close(self):
        if self.fh.filepath:
            offset = self.fh.line_to_offset(self.top_line)
            self.pm.set_last_session(self.fh.filepath, offset)
        self.root.destroy()

    # ── Appearance ──────────────────────────────────────────────

    def _on_color(self):
        result = colorchooser.askcolor(color=self.font_color, title='Choose Font Color')
        if result and result[1]:
            self.font_color = result[1]
            self._render()

    def _on_font_change(self):
        try:
            self.font_size = self.size_var.get()
            self._calc_line_height()
            self._render()
        except Exception:
            pass

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
            parent=self.root,
        )

        self.pm.add_save(self.fh.filepath, offset, name or '')
        messagebox.showinfo(
            'Saved', f'Progress saved.\nLine: {line_num:,}  ({pct:.1f}%)'
        )

    def _on_load_progress(self):
        if not self.fh.filepath:
            messagebox.showinfo('Info', 'Please open a file first.')
            return

        saves = self.pm.get_saves(self.fh.filepath)
        if not saves:
            messagebox.showinfo(
                'No Progress',
                'No saved progress for this file.\nUse "Save Progress" to create save points.',
            )
            return

        self._show_progress_dialog(saves)

    def _show_progress_dialog(self, saves):
        dlg = tk.Toplevel(self.root)
        dlg.title('Select Progress')
        dlg.geometry('500x360')
        dlg.configure(bg='#2b2b2b')
        dlg.transient(self.root)
        dlg.grab_set()

        # Center
        dlg.update_idletasks()
        px = self.root.winfo_rootx() + (self.root.winfo_width() - 500) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - 360) // 2
        dlg.geometry(f'+{px}+{py}')

        tk.Label(
            dlg, text='Saved Reading Progress', bg='#2b2b2b', fg='#cccccc',
            font=('Microsoft YaHei', 12, 'bold'),
        ).pack(pady=(12, 8))

        frame = tk.Frame(dlg, bg='#2b2b2b')
        frame.pack(fill=tk.BOTH, expand=True, padx=12)

        lb = tk.Listbox(
            frame, bg='#1e1e1e', fg='#cccccc',
            selectbackground='#3a5a7a', selectforeground='#ffffff',
            font=('Consolas', 10), activestyle='none', bd=1, relief=tk.SOLID,
        )
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

        BC = {
            'bg': '#3a3a3a', 'fg': '#cccccc', 'relief': tk.FLAT,
            'font': ('Microsoft YaHei', 10), 'padx': 16, 'pady': 4,
            'activebackground': '#555555', 'cursor': 'hand2',
        }

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
        tk.Button(
            btn_frame, text='Delete', command=delete,
            bg='#553333', fg='#cc8888', relief=tk.FLAT,
            font=('Microsoft YaHei', 10), padx=16, pady=4,
            activebackground='#774444', cursor='hand2',
        ).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text='Cancel', command=dlg.destroy, **BC).pack(side=tk.LEFT, padx=4)

    # ── Entry ───────────────────────────────────────────────────

    def run(self):
        self.root.geometry('900x650')
        self.root.minsize(350, 250)
        self.root.after(50, self._render)
        self.root.mainloop()
