import ctypes
import json
import os
import re
import sqlite3
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tkinter import colorchooser, font, ttk
from urllib import error, request


APP_NAME = "Codex Usage"
RUNTIME_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SETTINGS_PATH = RUNTIME_DIR / "settings.json"
STATUS_PATH = RUNTIME_DIR / "quota_status.json"
CODEX_USAGE_URLS = (
    "https://chatgpt.com/backend-api/wham/usage",
    "https://chatgpt.com/api/codex/usage",
)
ICON_FONT_FAMILY = "Segoe MDL2 Assets"
ICON_LOCK = "\uE72E"
ICON_UNLOCK = "\uE785"
ICON_PIN = "\uE718"
ICON_UNPIN = "\uE77A"
ICON_REFRESH = "\uE72C"
ICON_CLOSE = "\uE8BB"

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
ERROR_ALREADY_EXISTS = 183
INSTANCE_MUTEX_NAME = "Local\\CodexUsagePopupSingleInstance"
CODEX_MISSING_LIMIT = 3
_INSTANCE_MUTEX_HANDLE = None


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]

DEFAULT_SETTINGS = {
    "geometry": "214x82+36+856",
    "background_color": "#121212",
    "foreground_color": "#D8D8D8",
    "muted_color": "#8A8A8A",
    "bar_color": "#6F6F6F",
    "bar_background": "#2A2A2A",
    "alpha": 0.58,
    "font_family": "Microsoft YaHei UI",
    "title_size": 9,
    "body_size": 9,
    "refresh_seconds": 20,
    "always_on_top": True,
    "hide_when_codex_closed": True,
    "exit_when_codex_closed": False,
    "borderless": True,
    "click_through": False,
    "locked": False,
    "openai_session_key": "",
}

@dataclass
class UsageItem:
    name: str
    remaining_percent: int | None
    reset: str


EMPTY_ITEMS = [
    UsageItem("5小时", None, "未获取"),
    UsageItem("1周", None, "未获取"),
]


def load_json(path: Path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged = default.copy()
                merged.update(data)
                return merged
    except Exception:
        pass
    return default.copy()


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def acquire_single_instance():
    global _INSTANCE_MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
    if not handle:
        return True
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX_HANDLE = handle
    return True


def is_codex_running():
    snapshot = None
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel32.Process32FirstW.argtypes = (ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W))
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = (ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W))
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            return False
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            if entry.szExeFile.lower() == "codex.exe":
                return True
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    except Exception:
        return False
    finally:
        if snapshot and snapshot != ctypes.c_void_p(-1).value:
            ctypes.windll.kernel32.CloseHandle(snapshot)


def clamp_percent(value):
    try:
        return max(0, min(100, int(round(float(value)))))
    except Exception:
        return 0


def format_reset(value):
    if not value:
        return ""
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz=timezone.utc).astimezone()
    else:
        text = str(value)
        if re.fullmatch(r"\d{1,2}:\d{2}", text) or "月" in text:
            return text
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone()
        except Exception:
            return text
    now = datetime.now().astimezone()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    return f"{dt.month}月{dt.day}日"


def normalize_usage_payload(data):
    if not isinstance(data, dict):
        return []
    usage = data.get("usage_limits") or data.get("rate_limits") or data
    if isinstance(usage, dict) and "model_limits" in usage:
        usage = usage.get("model_limits")
    if isinstance(usage, dict):
        candidates = []
        for key, label in [("primary", "5小时"), ("secondary", "1周"), ("five_hour", "5小时"), ("weekly", "1周")]:
            value = usage.get(key)
            if isinstance(value, dict):
                candidates.append((label, value))
        if not candidates:
            candidates = [(str(k), v) for k, v in usage.items() if isinstance(v, dict)]
    elif isinstance(usage, list):
        candidates = [("", v) for v in usage if isinstance(v, dict)]
    else:
        candidates = []

    items = []
    for label, value in candidates:
        name = value.get("name") or value.get("label") or value.get("window") or label
        percent = (
            value.get("remaining_percent")
            if "remaining_percent" in value
            else value.get("remainingPercentage", value.get("percent_remaining", value.get("remaining")))
        )
        reset = value.get("resets_at") or value.get("reset_at") or value.get("reset") or value.get("next_reset_at")
        if percent is not None:
            items.append(UsageItem(str(name or "额度"), clamp_percent(percent), format_reset(reset)))
    return items[:2]


def codex_auth_path():
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    return Path(codex_home) / "auth.json" if codex_home else Path.home() / ".codex" / "auth.json"


def read_codex_auth():
    try:
        with codex_auth_path().open("r", encoding="utf-8") as f:
            data = json.load(f)
        tokens = data.get("tokens", {})
        token = str(tokens.get("access_token", "")).strip()
        if not token:
            return "", ""
        return token, str(tokens.get("account_id", "")).strip()
    except Exception:
        return "", ""


def normalize_codex_usage(data):
    if not isinstance(data, dict):
        return []
    rate_limit = data.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return []

    primary = rate_limit.get("primary_window")
    secondary = rate_limit.get("secondary_window")
    plan_type = str(data.get("plan_type", "")).strip().lower()
    windows = []
    if isinstance(primary, dict):
        primary_seconds = int(primary.get("limit_window_seconds") or 0)
        primary_label = "1周" if plan_type == "free" or (not isinstance(secondary, dict) and primary_seconds >= 7 * 24 * 60 * 60) else "5小时"
        windows.append((primary_label, primary))
    if isinstance(secondary, dict):
        windows.append(("1周", secondary))

    items = []
    for name, value in windows:
        if "used_percent" not in value:
            continue
        remaining = 100 - float(value["used_percent"])
        items.append(UsageItem(name, clamp_percent(remaining), format_reset(value.get("reset_at"))))
    return items[:2]


def fetch_codex_usage():
    token, account_id = read_codex_auth()
    if not token:
        return []
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "CodexUsagePopup/2.0",
    }
    if account_id:
        headers["X-Account-Id"] = account_id
        headers["ChatGPT-Account-Id"] = account_id
        headers["ChatClaude-Account-Id"] = account_id
    for url in CODEX_USAGE_URLS:
        try:
            req = request.Request(url, headers=headers)
            with request.urlopen(req, timeout=8) as response:
                items = normalize_codex_usage(json.loads(response.read().decode("utf-8", "replace")))
                if items:
                    return items
        except error.HTTPError as exc:
            if exc.code != 404:
                return []
        except Exception:
            return []
    return []


def fetch_dashboard_usage(settings):
    session_key = (settings.get("openai_session_key") or os.environ.get("OPENAI_SESSION_KEY") or "").strip()
    if not session_key:
        return []
    req = request.Request(
        "https://api.openai.com/dashboard/rate_limits",
        headers={
            "Authorization": "Bearer " + session_key,
            "Accept": "application/json",
            "User-Agent": "CodexUsagePopup/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=8) as response:
            return normalize_usage_payload(json.loads(response.read().decode("utf-8", "replace")))
    except Exception:
        return []


def read_status_file():
    try:
        if STATUS_PATH.exists():
            with STATUS_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            items = normalize_usage_payload(data)
            if items:
                return items
            raw = data.get("items", [])
            parsed = []
            for item in raw:
                parsed.append(
                    UsageItem(
                        str(item.get("name", "额度")),
                        clamp_percent(item.get("remaining_percent", 0)),
                        format_reset(item.get("reset") or item.get("resets_at")),
                    )
                )
            return parsed[:2]
    except Exception:
        pass
    return []


def read_usage_from_logs():
    db_path = Path.home() / ".codex" / "logs_2.sqlite"
    if not db_path.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
        rows = con.execute(
            """
            select feedback_log_body
            from logs
            where feedback_log_body like '%remaining_percent%'
              and feedback_log_body like '%usage_limits%'
              and feedback_log_body not like '%select id,target,feedback_log_body%'
            order by id desc
            limit 20
            """
        ).fetchall()
        con.close()
    except Exception:
        return []
    for (body,) in rows:
        for match in re.finditer(r"\{[^{}]*usage_limits[^{}]*(?:\{[^{}]*\}[^{}]*)+\}", body):
            try:
                items = normalize_usage_payload(json.loads(match.group(0)))
                if items:
                    return items
            except Exception:
                continue
    return []


class UsagePopup:
    def __init__(self):
        self.settings = load_json(SETTINGS_PATH, DEFAULT_SETTINGS)
        self.drag_start = None
        self.resize_start = None
        self.rows = []
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry(self.settings["geometry"])
        self.root.minsize(194, 92)
        if self.settings["borderless"]:
            self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.settings["always_on_top"]))
        self.root.attributes("-alpha", float(self.settings["alpha"]))
        self.root.configure(bg=self.settings["background_color"])
        self.root.bind("<Button-3>", self.show_menu)
        self.root.bind("<Configure>", self.save_geometry_later)
        self.root.after(200, self.hide_from_taskbar)

        self.geometry_after_id = None
        self.refresh_after_id = None
        self.refresh_in_progress = False
        self.refresh_result = None
        self.codex_missing_count = 0
        self.build_ui()
        self.ensure_status_file()
        self.apply_style()
        self.refresh()
        self.root.mainloop()

    def hide_from_taskbar(self):
        try:
            hwnd = self.root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def ensure_status_file(self):
        if not STATUS_PATH.exists():
            save_json(
                STATUS_PATH,
                {
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "items": [],
                    "source": "manual",
                },
            )

    def build_ui(self):
        self.frame = tk.Frame(self.root, bd=0, highlightthickness=0)
        self.frame.pack(fill="both", expand=True, padx=8, pady=6)
        self.header = tk.Frame(self.frame, bd=0, highlightthickness=0)
        self.header.pack(fill="x")
        self.title_label = tk.Label(self.header, text="剩余用量", anchor="w")
        self.title_label.pack(side="left", fill="x", expand=True)
        self.controls = tk.Frame(self.header, bd=0, highlightthickness=0)
        self.controls.pack(side="right")
        self.lock_button = self.make_control_button(self.controls, self.toggle_lock)
        self.pin_button = self.make_control_button(self.controls, self.toggle_topmost)
        self.refresh_button = self.make_control_button(self.controls, self.refresh, ICON_REFRESH)
        self.close_button = self.make_control_button(self.controls, self.quit, ICON_CLOSE)
        self.lock_button.pack(side="left", padx=(0, 3))
        self.pin_button.pack(side="left", padx=(0, 3))
        self.refresh_button.pack(side="left", padx=(0, 3))
        self.close_button.pack(side="left")
        for _ in range(2):
            row = tk.Frame(self.frame, bd=0, highlightthickness=0)
            row.pack(fill="x", pady=(2, 0))
            name = tk.Label(row, width=5, anchor="w")
            name.pack(side="left")
            bar = tk.Canvas(row, height=5, width=58, bd=0, highlightthickness=0)
            bar.pack(side="left", fill="x", expand=True, padx=(2, 6))
            percent = tk.Label(row, width=4, anchor="e")
            percent.pack(side="left")
            reset = tk.Label(row, width=7, anchor="e")
            reset.pack(side="right")
            self.rows.append((row, name, bar, percent, reset))
        self.resize_handle = tk.Label(self.root, text="◢", bd=0, highlightthickness=0)
        self.resize_handle.place(relx=1.0, rely=1.0, anchor="se")
        self.resize_handle.bind("<ButtonPress-1>", self.start_resize)
        self.resize_handle.bind("<B1-Motion>", self.on_resize)
        self.bind_drag_widgets()
        self.update_control_state()

        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="设置", command=self.open_settings)
        self.menu.add_command(label="刷新", command=self.refresh)
        self.menu.add_command(label="打开数据文件", command=lambda: os.startfile(STATUS_PATH))
        self.menu.add_separator()
        self.menu.add_command(label="隐藏", command=self.root.withdraw)
        self.menu.add_command(label="退出", command=self.quit)

    def make_control_button(self, parent, command, text=""):
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=2,
            bd=0,
            relief="flat",
            highlightthickness=0,
            padx=0,
            pady=0,
            takefocus=False,
        )

    def bind_drag_widgets(self):
        widgets = [self.frame, self.header, self.title_label]
        for row, name, bar, percent, reset in self.rows:
            widgets.extend([row, name, bar, percent, reset])
        for widget in widgets:
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.on_drag)

    def apply_style(self):
        bg = self.settings["background_color"]
        fg = self.settings["foreground_color"]
        muted = self.settings["muted_color"]
        title_font = font.Font(family=self.settings["font_family"], size=int(self.settings["title_size"]), weight="bold")
        body_font = font.Font(family=self.settings["font_family"], size=int(self.settings["body_size"]), weight="bold")
        icon_font = font.Font(family=ICON_FONT_FAMILY, size=8)
        self.root.configure(bg=bg)
        self.frame.configure(bg=bg)
        self.header.configure(bg=bg)
        self.controls.configure(bg=bg)
        self.title_label.configure(bg=bg, fg=fg, font=title_font)
        for button in [self.lock_button, self.pin_button, self.refresh_button, self.close_button]:
            button.configure(
                bg=bg,
                activebackground=bg,
                fg=muted,
                activeforeground=fg,
                font=icon_font,
            )
        for row, name, bar, percent, reset in self.rows:
            row.configure(bg=bg)
            for widget in [name, percent]:
                widget.configure(bg=bg, fg=fg, font=body_font)
            reset.configure(bg=bg, fg=muted, font=body_font)
            bar.configure(bg=bg)
        self.resize_handle.configure(bg=bg, fg=muted, font=body_font)
        self.update_control_state()
        self.root.attributes("-alpha", float(self.settings["alpha"]))
        self.root.attributes("-topmost", bool(self.settings["always_on_top"]))

    def get_items(self):
        return fetch_codex_usage() or fetch_dashboard_usage(self.settings) or read_usage_from_logs() or read_status_file() or EMPTY_ITEMS

    def refresh(self):
        if self.refresh_after_id:
            self.root.after_cancel(self.refresh_after_id)
            self.refresh_after_id = None
        if self.refresh_in_progress:
            return
        self.refresh_in_progress = True
        self.refresh_result = None
        threading.Thread(target=self.load_refresh_data, daemon=True).start()
        self.root.after(25, self.poll_refresh_data)

    def load_refresh_data(self):
        running = is_codex_running()
        items = self.get_items() if running or not self.settings["hide_when_codex_closed"] else []
        self.refresh_result = (running, items)

    def poll_refresh_data(self):
        if self.refresh_result is None:
            if self.refresh_in_progress:
                self.root.after(25, self.poll_refresh_data)
            return
        running, items = self.refresh_result
        self.refresh_result = None
        self.apply_refresh_data(running, items)

    def apply_refresh_data(self, running, items):
        self.refresh_in_progress = False
        if running:
            self.codex_missing_count = 0
        else:
            self.codex_missing_count += 1
        if not running and self.settings["hide_when_codex_closed"]:
            if self.codex_missing_count < CODEX_MISSING_LIMIT:
                self.refresh_after_id = self.root.after(3000, self.refresh)
                return
            if self.settings["exit_when_codex_closed"]:
                self.quit()
                return
            self.root.withdraw()
            self.refresh_after_id = self.root.after(3000, self.refresh)
            return
        self.root.deiconify()
        self.hide_from_taskbar()
        for index, widgets in enumerate(self.rows):
            _row, name, bar, percent, reset = widgets
            item = items[index] if index < len(items) else UsageItem("", 0, "")
            name.configure(text=item.name)
            percent.configure(text="--" if item.remaining_percent is None else f"{item.remaining_percent}%")
            reset.configure(text=item.reset)
            self.draw_bar(bar, item.remaining_percent or 0)
        self.refresh_after_id = self.root.after(max(5, int(self.settings["refresh_seconds"])) * 1000, self.refresh)

    def draw_bar(self, canvas, percent):
        canvas.delete("all")
        width = max(canvas.winfo_width(), 58)
        height = max(canvas.winfo_height(), 5)
        fill = int(width * clamp_percent(percent) / 100)
        canvas.create_rectangle(0, 0, width, height, fill=self.settings["bar_background"], width=0)
        canvas.create_rectangle(0, 0, fill, height, fill=self.settings["bar_color"], width=0)

    def start_drag(self, event):
        if self.settings["locked"]:
            return "break"
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def on_drag(self, event):
        if self.settings["locked"] or not self.drag_start:
            return
        sx, sy, wx, wy = self.drag_start
        self.root.geometry(f"+{wx + event.x_root - sx}+{wy + event.y_root - sy}")

    def start_resize(self, event):
        if self.settings["locked"]:
            return "break"
        self.resize_start = (event.x_root, event.y_root, self.root.winfo_width(), self.root.winfo_height())
        return "break"

    def on_resize(self, event):
        if self.settings["locked"] or not self.resize_start:
            return "break"
        sx, sy, width, height = self.resize_start
        new_width = max(194, width + event.x_root - sx)
        new_height = max(92, height + event.y_root - sy)
        self.root.geometry(f"{new_width}x{new_height}")
        return "break"

    def update_control_state(self):
        locked = bool(self.settings["locked"])
        fg = self.settings["foreground_color"]
        muted = self.settings["muted_color"]
        self.lock_button.configure(text=ICON_LOCK if locked else ICON_UNLOCK, fg=fg if locked else muted)
        self.pin_button.configure(text=ICON_UNPIN if self.settings["always_on_top"] else ICON_PIN, fg=fg if self.settings["always_on_top"] else muted)
        self.resize_handle.configure(cursor="arrow" if locked else "size_nw_se", fg=muted if not locked else self.settings["background_color"])

    def toggle_lock(self):
        self.settings["locked"] = not bool(self.settings["locked"])
        self.drag_start = None
        self.resize_start = None
        self.update_control_state()
        save_json(SETTINGS_PATH, self.settings)

    def toggle_topmost(self):
        self.settings["always_on_top"] = not bool(self.settings["always_on_top"])
        self.root.attributes("-topmost", bool(self.settings["always_on_top"]))
        self.update_control_state()
        save_json(SETTINGS_PATH, self.settings)

    def show_menu(self, event):
        if self.settings["locked"]:
            return "break"
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def save_geometry_later(self, _event=None):
        if self.root.state() == "withdrawn":
            return
        if self.geometry_after_id:
            self.root.after_cancel(self.geometry_after_id)
        self.geometry_after_id = self.root.after(500, self.save_geometry)

    def save_geometry(self):
        self.settings["geometry"] = self.root.geometry()
        save_json(SETTINGS_PATH, self.settings)

    def open_settings(self):
        SettingsWindow(self)

    def quit(self):
        self.save_geometry()
        self.root.destroy()


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        self.vars = {}
        self.win = tk.Toplevel(app.root)
        self.win.title("设置")
        self.win.geometry("390x470")
        self.win.grab_set()
        self.build()

    def build(self):
        frame = ttk.Frame(self.win, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        row = 0
        for key, label in [
            ("background_color", "背景"),
            ("foreground_color", "文字"),
            ("muted_color", "时间"),
            ("bar_color", "进度"),
            ("bar_background", "进度底色"),
        ]:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            self.vars[key] = tk.StringVar(value=self.app.settings[key])
            ttk.Entry(frame, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", padx=6)
            ttk.Button(frame, text="选", width=4, command=lambda k=key: self.choose_color(k)).grid(row=row, column=2)
            row += 1
        ttk.Label(frame, text="透明度").grid(row=row, column=0, sticky="w", pady=5)
        self.vars["alpha"] = tk.DoubleVar(value=float(self.app.settings["alpha"]))
        ttk.Scale(frame, from_=0.25, to=1.0, variable=self.vars["alpha"], orient="horizontal").grid(row=row, column=1, columnspan=2, sticky="ew")
        row += 1
        ttk.Label(frame, text="字体").grid(row=row, column=0, sticky="w", pady=5)
        self.vars["font_family"] = tk.StringVar(value=self.app.settings["font_family"])
        ttk.Combobox(frame, textvariable=self.vars["font_family"], values=sorted(font.families())).grid(row=row, column=1, columnspan=2, sticky="ew")
        row += 1
        for key, label in [("title_size", "标题字号"), ("body_size", "内容字号"), ("refresh_seconds", "刷新秒数")]:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            self.vars[key] = tk.IntVar(value=int(self.app.settings[key]))
            ttk.Spinbox(frame, from_=5, to=60, textvariable=self.vars[key]).grid(row=row, column=1, columnspan=2, sticky="ew")
            row += 1
        self.vars["always_on_top"] = tk.BooleanVar(value=bool(self.app.settings["always_on_top"]))
        ttk.Checkbutton(frame, text="置顶", variable=self.vars["always_on_top"]).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self.vars["hide_when_codex_closed"] = tk.BooleanVar(value=bool(self.app.settings["hide_when_codex_closed"]))
        ttk.Checkbutton(frame, text="Codex 关闭时隐藏", variable=self.vars["hide_when_codex_closed"]).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        ttk.Button(buttons, text="保存", command=self.save).pack(side="right")
        ttk.Button(buttons, text="取消", command=self.win.destroy).pack(side="right", padx=6)

    def choose_color(self, key):
        color = colorchooser.askcolor(color=self.vars[key].get(), parent=self.win)[1]
        if color:
            self.vars[key].set(color)

    def save(self):
        for key, var in self.vars.items():
            self.app.settings[key] = var.get()
        save_json(SETTINGS_PATH, self.app.settings)
        self.app.apply_style()
        self.app.refresh()
        self.win.destroy()


if __name__ == "__main__" and acquire_single_instance():
    UsagePopup()
