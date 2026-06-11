import datetime
import json
import os
import re
import time

import httpx


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TASKS_PATH = os.path.join(BASE_DIR, "tasks.json")


def load_tasks():
    try:
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_tasks(tasks):
    tmp_path = TASKS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)
    os.replace(tmp_path, TASKS_PATH)


def normalize_time(text, default_time="09:00"):
    text = (text or "").lower()
    match = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if not match:
        match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not match:
        return default_time

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = match.group(3) if len(match.groups()) >= 3 else None
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return default_time
    return f"{hour:02d}:{minute:02d}"


def strip_task_noise(text):
    text = (text or "").strip().lower()
    text = re.sub(r"\b(hey\s+jarvis|jarvis)\b", " ", text)
    text = re.sub(r"\b(at\s+)?\d{1,2}(:\d{2})?\s*(am|pm)\b", " ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)
    text = re.sub(r"\b(today|tomorrow|daily|everyday|every day|for tomorrow|for today)\b", " ", text)
    text = re.sub(r"\b(update|add|set|create|save)\b\s+((my|the|your)\s+)?tasks?\b", " ", text)
    text = re.sub(r"\b(remind me|reminder|tasks?|to do|todo)\b", " ", text)
    text = re.sub(r"\b(update|add|set|create|save)\b", " ", text)
    text = re.sub(r"\b(for|at|on|by|about|that|please|sir)\b", " ", text)
    text = re.sub(r"^\s*to\s+", " ", text)
    return " ".join(text.split())


def split_task_titles(text):
    text = text.strip(" .,:;-")
    if not text:
        return []
    parts = re.split(r"\s*(?:,|;|\n)\s*", text)
    if len(parts) == 1 and " and " in text and len(text.split()) >= 4:
        parts = re.split(r"\s+and\s+", text)
    return [part.strip(" .,:;-") for part in parts if part.strip(" .,:;-")]


def parse_natural_task_command(text, now=None):
    now = now or datetime.datetime.now()
    raw = (text or "").strip()
    lower = raw.lower()
    if not any(marker in lower for marker in ["task", "tasks", "remind me", "reminder", "todo", "to do"]):
        return []

    remind_time = normalize_time(lower)
    if "tomorrow" in lower:
        repeat = "once"
        due_date = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    elif "today" in lower:
        repeat = "once"
        due_date = now.strftime("%Y-%m-%d")
    elif any(marker in lower for marker in ["everyday", "every day", "daily"]):
        repeat = "daily"
        due_date = ""
    else:
        repeat = "daily"
        due_date = ""

    task_text = raw
    separator = re.search(r"(?<!\d):\s*(.+)$", task_text)
    if separator:
        task_text = separator.group(1)
    else:
        to_match = re.search(r"\bto\s+(.+)$", raw, flags=re.IGNORECASE)
        if to_match and "remind me" in lower:
            task_text = to_match.group(1)

    task_text = strip_task_noise(task_text)
    titles = split_task_titles(task_text)
    tasks = []
    for title in titles:
        if len(title) < 2:
            continue
        tasks.append({
            "title": title,
            "status": "pending",
            "repeat": repeat,
            "date": due_date,
            "remind_time": remind_time,
            "last_reminded": "",
        })
    return tasks


def add_tasks_from_text(text, now=None):
    new_tasks = parse_natural_task_command(text, now=now)
    if not new_tasks:
        return []
    tasks = load_tasks()
    tasks.extend(new_tasks)
    save_tasks(tasks)
    return new_tasks


def due_today(task, now):
    if not isinstance(task, dict):
        return False
    if task.get("status", "pending").lower() != "pending":
        return False

    remind_time = task.get("remind_time", "").strip()
    if not remind_time:
        return False

    try:
        due = datetime.datetime.strptime(remind_time, "%H:%M").time()
    except ValueError:
        return False

    today = now.strftime("%Y-%m-%d")
    if task.get("last_reminded") == today:
        return False

    repeat = task.get("repeat", "daily").lower()
    task_date = task.get("date", "")
    if repeat == "once" and task_date != today:
        return False
    if repeat not in ("daily", "once"):
        return False

    due_dt = datetime.datetime.combine(now.date(), due)
    return now >= due_dt


def send_telegram_reminder(token, chat_id, task):
    if not token or not chat_id:
        return False
    title = task.get("title", "Task reminder")
    message = f"Jarvis reminder\n\n{title}"
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=12,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"[Tasks] Telegram reminder failed: {e}")
        return False


def start_task_reminders(token="", chat_id="", status_writer=None, check_interval=30):
    print("[Tasks] Daily task reminder service started.")
    while True:
        try:
            now = datetime.datetime.now()
            tasks = load_tasks()
            changed = False

            for task in tasks:
                if not due_today(task, now):
                    continue

                title = task.get("title", "Task reminder")
                print(f"[Tasks] Reminder due: {title}")
                sent = send_telegram_reminder(token, chat_id, task)
                if status_writer:
                    status_writer("Reminder", last_response=f"Reminder: {title}")
                if sent or not token:
                    task["last_reminded"] = now.strftime("%Y-%m-%d")
                    changed = True

            if changed:
                save_tasks(tasks)
        except Exception as e:
            print(f"[Tasks] Reminder service error: {e}")

        time.sleep(check_interval)
