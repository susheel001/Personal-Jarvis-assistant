import datetime
import json
import os
import threading
import time
import tkinter as tk
from tkinter import font

import psutil
import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_PATH = os.path.join(BASE_DIR, "jarvis_status.json")
TASKS_PATH = os.path.join(BASE_DIR, "tasks.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

BG = "#0a0a0f"
PANEL_BG = "#101018"
CYAN = "#00d4ff"
CYAN_DIM = "#007c96"
ORANGE = "#ff6600"
RED = "#ff3333"
TEXT = "#c9f7ff"
MUTED = "#6fb8c9"


DEFAULT_STATUS = {
    "state": "Offline",
    "last_command": "",
    "last_response": "",
    "updated_at": "",
}

DEFAULT_TASKS = [
    {"title": "Review Jarvis status", "status": "pending"},
    {"title": "Add NEWSAPI_KEY to .env", "status": "pending"},
]


def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def safe_read_json(path, default_value):
    try:
        if not os.path.exists(path):
            safe_write_json(path, default_value)
            return default_value
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        safe_write_json(path, default_value)
        return default_value


def safe_write_json(path, value):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2)


class HudPanel(tk.Frame):
    def __init__(self, parent, title, height=None):
        super().__init__(
            parent,
            bg=PANEL_BG,
            highlightbackground=CYAN,
            highlightcolor=CYAN,
            highlightthickness=1,
            bd=0,
        )
        if height:
            self.configure(height=height)
            self.pack_propagate(False)

        header = tk.Label(
            self,
            text=f"[ {title} ]",
            bg=PANEL_BG,
            fg=ORANGE,
            font=("Courier New", 10, "bold"),
            anchor="w",
        )
        header.pack(fill="x", padx=10, pady=(7, 2))


class JarvisHud:
    def __init__(self):
        self.root = tk.Tk()
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", False)
        self.root.resizable(False, False)

        self.width = 400
        self.height = 800
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, screen_w - self.width - 16)
        y = max(0, int((screen_h - self.height) / 2))
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.on_move)

        self.news_items = ["NEWSAPI_KEY missing - add it to .env for live tech headlines"]
        self.news_index = 0
        self.news_offset = 0
        self.topmost = False
        self.pulse_on = False

        self.build_ui()
        self.schedule_updates()
        threading.Thread(target=self.refresh_news, daemon=True).start()

    def build_ui(self):
        self.container = tk.Frame(self.root, bg=BG)
        self.container.pack(fill="both", expand=True, padx=10, pady=10)

        self.build_header()
        self.build_clock()
        self.build_pc_status()
        self.build_jarvis_status()
        self.build_tasks()
        self.build_last_command()
        self.build_news()

    def build_header(self):
        panel = tk.Frame(self.container, bg=BG)
        panel.pack(fill="x", pady=(0, 8))

        title = tk.Label(
            panel,
            text="J.A.R.V.I.S",
            bg=BG,
            fg=CYAN,
            font=("Courier New", 28, "bold"),
        )
        title.pack(anchor="w")

        subtitle = tk.Label(
            panel,
            text="Just A Rather Very Intelligent System",
            bg=BG,
            fg=ORANGE,
            font=("Courier New", 9),
        )
        subtitle.pack(anchor="w")

        controls = tk.Frame(panel, bg=BG)
        controls.place(relx=1.0, y=0, anchor="ne")

        self.top_btn = tk.Button(
            controls,
            text="PIN",
            command=self.toggle_topmost,
            bg=PANEL_BG,
            fg=CYAN,
            activebackground=BG,
            activeforeground=ORANGE,
            relief="flat",
            font=("Courier New", 8, "bold"),
            width=5,
        )
        self.top_btn.pack(side="left", padx=(0, 4))

        close_btn = tk.Button(
            controls,
            text="X",
            command=self.root.destroy,
            bg=PANEL_BG,
            fg=RED,
            activebackground=BG,
            activeforeground=RED,
            relief="flat",
            font=("Courier New", 9, "bold"),
            width=3,
        )
        close_btn.pack(side="left")

    def build_clock(self):
        panel = HudPanel(self.container, "CLOCK", height=88)
        panel.pack(fill="x", pady=5)
        self.time_label = tk.Label(panel, bg=PANEL_BG, fg=CYAN, font=("Courier New", 22, "bold"))
        self.time_label.pack(anchor="w", padx=12)
        self.date_label = tk.Label(panel, bg=PANEL_BG, fg=TEXT, font=("Courier New", 10))
        self.date_label.pack(anchor="w", padx=12, pady=(0, 6))

    def build_pc_status(self):
        panel = HudPanel(self.container, "PC STATUS", height=100)
        panel.pack(fill="x", pady=5)
        self.cpu_label = tk.Label(panel, bg=PANEL_BG, fg=TEXT, font=("Courier New", 12), anchor="w")
        self.cpu_label.pack(fill="x", padx=12, pady=2)
        self.ram_label = tk.Label(panel, bg=PANEL_BG, fg=TEXT, font=("Courier New", 12), anchor="w")
        self.ram_label.pack(fill="x", padx=12, pady=2)

    def build_jarvis_status(self):
        panel = HudPanel(self.container, "JARVIS STATUS", height=112)
        panel.pack(fill="x", pady=5)
        row = tk.Frame(panel, bg=PANEL_BG)
        row.pack(fill="x", padx=12, pady=4)
        self.status_dot = tk.Canvas(row, width=18, height=18, bg=PANEL_BG, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status_label = tk.Label(row, bg=PANEL_BG, fg=CYAN, font=("Courier New", 14, "bold"), anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.updated_label = tk.Label(panel, bg=PANEL_BG, fg=MUTED, font=("Courier New", 9), anchor="w")
        self.updated_label.pack(fill="x", padx=12)

    def build_tasks(self):
        panel = HudPanel(self.container, "TASKS", height=150)
        panel.pack(fill="x", pady=5)
        self.tasks_label = tk.Label(
            panel,
            bg=PANEL_BG,
            fg=TEXT,
            font=("Courier New", 10),
            justify="left",
            anchor="nw",
        )
        self.tasks_label.pack(fill="both", expand=True, padx=12, pady=4)

    def build_last_command(self):
        panel = HudPanel(self.container, "LAST COMMAND", height=170)
        panel.pack(fill="x", pady=5)
        self.command_label = tk.Label(
            panel,
            bg=PANEL_BG,
            fg=CYAN,
            font=("Courier New", 10),
            justify="left",
            anchor="nw",
            wraplength=350,
        )
        self.command_label.pack(fill="x", padx=12, pady=3)
        self.response_label = tk.Label(
            panel,
            bg=PANEL_BG,
            fg=TEXT,
            font=("Courier New", 10),
            justify="left",
            anchor="nw",
            wraplength=350,
        )
        self.response_label.pack(fill="both", expand=True, padx=12, pady=3)

    def build_news(self):
        panel = HudPanel(self.container, "TECH NEWS FEED", height=92)
        panel.pack(fill="x", pady=5)
        self.news_label = tk.Label(
            panel,
            bg=PANEL_BG,
            fg=ORANGE,
            font=("Courier New", 10, "bold"),
            anchor="w",
        )
        self.news_label.pack(fill="x", padx=12, pady=12)

    def start_move(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def on_move(self, event):
        x = self.root.winfo_x() + event.x - self.drag_x
        y = self.root.winfo_y() + event.y - self.drag_y
        self.root.geometry(f"+{x}+{y}")

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.top_btn.configure(text="PIN*" if self.topmost else "PIN", fg=ORANGE if self.topmost else CYAN)

    def schedule_updates(self):
        self.update_clock()
        self.update_pc_status()
        self.update_status()
        self.update_tasks()
        self.animate_pulse()
        self.scroll_news()

    def update_clock(self):
        now = datetime.datetime.now()
        self.time_label.configure(text=now.strftime("%I:%M:%S %p"))
        self.date_label.configure(text=now.strftime("%A, %d %B %Y"))
        self.root.after(1000, self.update_clock)

    def update_pc_status(self):
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        self.cpu_label.configure(text=f"CPU LOAD : {cpu:5.1f}%")
        self.ram_label.configure(text=f"RAM USAGE: {ram.percent:5.1f}%  ({ram.used // (1024**3)} / {ram.total // (1024**3)} GB)")
        self.root.after(3000, self.update_pc_status)

    def update_status(self):
        status = safe_read_json(STATUS_PATH, DEFAULT_STATUS)
        state = status.get("state", "Offline")
        updated = status.get("updated_at", "")
        command = status.get("last_command", "")
        response = status.get("last_response", "")

        state_color = CYAN
        if state.lower() in ("error", "offline"):
            state_color = RED
        elif state.lower() in ("thinking", "speaking"):
            state_color = ORANGE

        self.status_label.configure(text=state.upper(), fg=state_color)
        self.updated_label.configure(text=f"UPDATED: {updated or 'waiting for signal'}")
        self.command_label.configure(text=f"> {command or 'No command captured yet'}")
        self.response_label.configure(text=f"< {response or 'No response yet'}")
        self.root.after(5000, self.update_status)

    def update_tasks(self):
        tasks = safe_read_json(TASKS_PATH, DEFAULT_TASKS)
        if not isinstance(tasks, list):
            tasks = DEFAULT_TASKS
            safe_write_json(TASKS_PATH, tasks)

        pending = []
        for item in tasks:
            if isinstance(item, dict):
                title = item.get("title", "")
                status = item.get("status", "pending")
                if status.lower() == "pending" and title:
                    when = item.get("date") or item.get("repeat", "daily")
                    remind_time = item.get("remind_time", "--:--")
                    pending.append(f"- {remind_time} {when}: {title}")
            elif isinstance(item, str):
                pending.append(f"- {item}")

        text = "\n".join(pending[:5]) if pending else "- No pending tasks"
        self.tasks_label.configure(text=text)
        self.root.after(5000, self.update_tasks)

    def animate_pulse(self):
        self.status_dot.delete("all")
        self.pulse_on = not self.pulse_on
        color = CYAN if self.pulse_on else CYAN_DIM
        size = 16 if self.pulse_on else 11
        offset = int((18 - size) / 2)
        self.status_dot.create_oval(offset, offset, offset + size, offset + size, outline=color, fill=color)
        self.root.after(650, self.animate_pulse)

    def refresh_news(self):
        env = load_env()
        key = env.get("NEWSAPI_KEY", "")
        if not key:
            self.news_items = ["NEWSAPI_KEY missing - add it to .env for live tech headlines"]
            self.root.after(30 * 60 * 1000, lambda: threading.Thread(target=self.refresh_news, daemon=True).start())
            return

        query = "Claude OR Anthropic OR OpenAI OR layoffs OR tech OR AI"
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 12,
            "apiKey": key,
        }
        try:
            response = requests.get(url, params=params, timeout=12)
            response.raise_for_status()
            data = response.json()
            headlines = []
            for article in data.get("articles", []):
                title = article.get("title")
                source = (article.get("source") or {}).get("name")
                if title and source:
                    headlines.append(f"{title} - {source}")
            self.news_items = headlines or ["No tech headlines returned by NewsAPI"]
        except Exception as e:
            self.news_items = [f"News feed offline: {e}"]
        finally:
            self.root.after(30 * 60 * 1000, lambda: threading.Thread(target=self.refresh_news, daemon=True).start())

    def scroll_news(self):
        item = self.news_items[self.news_index % len(self.news_items)]
        padded = "   " + item + "   "
        if self.news_offset >= len(padded):
            self.news_offset = 0
            self.news_index = (self.news_index + 1) % len(self.news_items)
        visible = (padded + padded)[self.news_offset:self.news_offset + 42]
        self.news_label.configure(text=visible)
        self.news_offset += 1
        self.root.after(180, self.scroll_news)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    safe_read_json(STATUS_PATH, DEFAULT_STATUS)
    safe_read_json(TASKS_PATH, DEFAULT_TASKS)
    JarvisHud().run()
