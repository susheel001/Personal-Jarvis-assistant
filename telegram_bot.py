"""
telegram_bot.py â€” Remote control Jarvis from anywhere via Telegram
"""

import os
import io
import json
import psutil
import asyncio
import datetime
import threading
import subprocess
import pyautogui
import webbrowser
import ctypes
import time
import logging
import re
import tempfile

from telegram import Update, Bot
from telegram.error import BadRequest, Conflict
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from ai_brain import AIBrain
from actions import (
    cancel_shutdown,
    close_all_tabs_and_apps,
    close_target,
    get_last_unlock_message,
    is_followup_video_command,
    open_app as open_windows_app,
    open_browser_command,
    execute_operator_command,
    open_media_command,
    parse_browser_command,
    parse_media_command,
    shutdown_pc,
    unlock_screen,
)
from whatsapp_bot import (
    get_recent_messages,
    get_whatsapp_status,
    pause_autoreply,
    resume_autoreply,
)
from monitor import set_activity_screenshots_paused
from task_manager import add_tasks_from_text, load_tasks, save_tasks

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
TELEGRAM_LOG_PATH = os.path.join(os.path.dirname(__file__), "telegram_bot_runtime.log")

def telegram_log(message):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}"
    print(line)
    try:
        with open(TELEGRAM_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

ENV = load_env()
TELEGRAM_TOKEN = ENV.get("TELEGRAM_BOT_TOKEN", "")
AUTHORIZED_ID  = ENV.get("TELEGRAM_USER_ID", "")
GROQ_API_KEY   = ENV.get("GROQ_API_KEY", "")

brain = AIBrain(groq_api_key=GROQ_API_KEY)
_telegram_conflict_reported = False
_telegram_whisper_model = None
_telegram_whisper_lock = threading.Lock()
SHUTDOWN_CONFIRM_SECONDS = 60

async def safe_reply_photo(update: Update, photo, caption=""):
    try:
        await update.message.reply_photo(photo=photo, caption=caption)
        return True
    except Exception as e:
        telegram_log(f"[Telegram] Could not send photo reply: {e}")
        try:
            await update.message.reply_text("Command ran, but Telegram timed out while sending the screenshot.")
        except Exception:
            pass
        return False

def is_authorized(update: Update) -> bool:
    if not AUTHORIZED_ID:
        return True
    return str(update.effective_user.id) == str(AUTHORIZED_ID)

def unauthorized_msg():
    return "ðŸ”’ Unauthorized. This is a private Jarvis instance."

def is_shutdown_text(text: str) -> bool:
    text = (text or "").lower()
    return any(phrase in text for phrase in ["shutdown", "shut down", "turn off", "power off"]) and "cancel" not in text

def is_cancel_shutdown_text(text: str) -> bool:
    text = (text or "").lower()
    return any(phrase in text for phrase in ["cancel shutdown", "abort shutdown", "stop shutdown", "cancel power off"])

def is_close_all_text(text: str) -> bool:
    text = (text or "").lower()
    return (
        any(word in text for word in ["close", "exit", "quit"])
        and any(word in text for word in ["all", "everything"])
        and any(word in text for word in ["tab", "tabs", "app", "apps", "application", "applications", "window", "windows"])
    )

def extract_close_target_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[?.!,]+$", "", text)
    if is_close_all_text(text):
        return ""
    match = re.search(r"\b(close|exit|quit)\s+(?:my\s+|the\s+|a\s+|an\s+)?(.+)$", text)
    if not match:
        return ""
    target = match.group(2).strip()
    target = re.sub(r"\b(app|application|window|tab|website|site|please|now)\b", " ", target)
    target = re.sub(r"\s+", " ", target).strip()
    return target

def is_unlock_text(text: str) -> bool:
    text = (text or "").lower()
    return any(phrase in text for phrase in ["open password", "open the password", "unlock", "login", "log in", "enter password"])

def is_owner_activity_screenshot_pause_text(text: str) -> bool:
    text = re.sub(r"\s+", " ", (text or "").lower()).strip()
    owner_confirmed = (
        "i am" in text
        or "i'm" in text
        or "yes" in text
    )
    controlling_pc = (
        "controlling" in text
        or "using" in text
        or "operating" in text
    ) and any(word in text for word in ["pc", "computer", "laptop"])
    stop_screenshots = (
        "stop" in text
        and any(word in text for word in ["screenshot", "screenshots", "screen shots"])
    )
    return owner_confirmed and controlling_pc and stop_screenshots

def is_activity_screenshot_resume_text(text: str) -> bool:
    text = re.sub(r"\s+", " ", (text or "").lower()).strip()
    return (
        any(word in text for word in ["resume", "start", "enable"])
        and any(word in text for word in ["screenshot", "screenshots", "screen shots"])
        and any(word in text for word in ["activity", "monitor", "mouse"])
    )

def normalize_telegram_command_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = re.sub(
        r"^(hey\s+jarvis|jarvis|wake\s*up\s+jarvis|wakeup\s+jarvis|wake\s*up\s+daddy(?:'s|s| is)\s+home|wakeup\s+daddy(?:'s|s| is)\s+home)[,:\s-]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()

def get_pc_status() -> str:
    cpu     = psutil.cpu_percent(interval=1)
    ram     = psutil.virtual_memory()
    disk    = psutil.disk_usage('C:\\')
    battery = psutil.sensors_battery()

    battery_str = "ðŸ”Œ Plugged in"
    if battery:
        charging = "ðŸ”Œ Charging" if battery.power_plugged else "ðŸ”‹ On battery"
        battery_str = f"{charging} â€” {battery.percent:.0f}%"

    now = datetime.datetime.now().strftime("%H:%M:%S")
    return (
        f"ðŸ–¥ *Jarvis PC Status* â€” {now}\n\n"
        f"âš¡ CPU: `{cpu}%`\n"
        f"ðŸ§  RAM: `{ram.used/(1024**3):.1f} / {ram.total/(1024**3):.1f} GB` ({ram.percent}%)\n"
        f"ðŸ’¾ Disk: `{disk.free/(1024**3):.1f} GB free`\n"
        f"{battery_str}\n"
    )

def take_screenshot() -> io.BytesIO:
    screenshot = pyautogui.screenshot()
    buf = io.BytesIO()
    screenshot.save(buf, format='PNG')
    buf.seek(0)
    return buf

def open_any_app(app_name: str) -> str:
    media_command = parse_media_command(app_name)
    if media_command:
        opened = open_media_command(app_name)
        if opened:
            query = media_command.get("query")
            if query:
                return f"Opened {media_command['service']} search for {query}"
            return f"Opened {media_command['service']}"
        return "Could not open media command"

    browser_command = parse_browser_command(app_name)
    if browser_command:
        if open_browser_command(app_name):
            return f"Opened {browser_command['target']} in {browser_command['browser']}"
        return f"Could not open {browser_command['target']}"

    app_name_lower = app_name.lower().strip()
    known_apps = {
        "chrome":   "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "vscode":   os.path.expandvars("%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe"),
        "vs code":  os.path.expandvars("%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe"),
        "spotify":  os.path.expandvars("%APPDATA%\\Spotify\\Spotify.exe"),
        "telegram": os.path.expandvars("%APPDATA%\\Telegram Desktop\\Telegram.exe"),
        "notepad":  "notepad.exe",
        "calculator": "calc.exe",
        "terminal": "cmd.exe",
        "claude":   None,
    }
    if app_name_lower == "claude":
        webbrowser.open("https://claude.ai")
        return "âœ… Opened Claude.ai"
    if app_name_lower in ("telegram web", "web telegram"):
        webbrowser.open("https://web.telegram.org/")
        return "Opened Telegram Web"
    if app_name_lower in known_apps:
        path = known_apps[app_name_lower]
        if path:
            try:
                if os.path.exists(path):
                    subprocess.Popen(path, shell=True)
                elif app_name_lower == "telegram":
                    webbrowser.open("https://web.telegram.org/")
                else:
                    subprocess.Popen(path, shell=True)
                return f"âœ… Opened {app_name}"
            except Exception as e:
                return f"âŒ Could not open {app_name}: {e}"
    try:
        if open_windows_app(app_name):
            return f"Opened {app_name}"
        return f"Could not open {app_name}"
    except Exception as e:
        return f"âŒ Failed: {e}"

def open_workspace() -> str:
    apps = CONFIG.get("workspace", [])
    opened = []
    for app in apps:
        try:
            if app["type"] == "url":
                webbrowser.open(app["url"])
                opened.append(app["name"])
                time.sleep(0.5)
            elif app["type"] == "app":
                path = os.path.expandvars(app["path"])
                if os.path.exists(path):
                    subprocess.Popen([path])
                    opened.append(app["name"])
                    time.sleep(1)
        except:
            opened.append(f"{app['name']} (failed)")
    return f"âœ… Workspace opened: {', '.join(opened)}"

def lock_screen() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "ðŸ”’ Screen locked."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    msg = (
        "ðŸ¤– *Jarvis Remote Control*\n\n"
        "/status â€” CPU, RAM, battery\n"
        "/screenshot â€” Take screenshot\n"
        "/workspace â€” Open workspace\n"
        "/lock â€” Lock screen\n"
        "/shutdown â€” Shut down laptop immediately\n"
        "/cancel_shutdown â€” Cancel pending shutdown\n"
        "close all tabs and apps â€” Close browser tabs and open app windows\n"
        "/open <app/site> â€” Open any app or website\n"
        "Operator: open Claude and type: how are you\n"
        "Operator: open Gmail and compose email to john@gmail.com subject: Meeting body: See you tomorrow\n"
        "Voice note: send any command as Telegram voice/audio\n"
        "/tasks â€” Show pending tasks\n"
        "/task_add HH:MM task text â€” Add daily task\n"
        "Natural task text: update tasks for tomorrow call mom and submit report\n"
        "Natural reminder: remind me every day at 8 pm to drink water\n"
        "/task_done number â€” Mark task done\n"
        "/wa_status â€” WhatsApp automation status\n"
        "/wa_recent â€” Recent WhatsApp messages\n"
        "/wa_pause â€” Pause WhatsApp auto-replies\n"
        "/wa_resume â€” Resume WhatsApp auto-replies\n"
        "/help â€” This menu\n\n"
        "Or just type naturally!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    await update.message.reply_text(get_pc_status(), parse_mode="Markdown")

async def screenshot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    await update.message.reply_text("ðŸ“¸ Taking screenshot...")
    buf = take_screenshot()
    await safe_reply_photo(update, buf, caption="Your PC screen")

async def workspace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    await update.message.reply_text("ðŸš€ Opening workspace...")
    result = open_workspace()
    await update.message.reply_text(result)

async def lock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    result = lock_screen()
    await update.message.reply_text(result)

async def shutdown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    await update.message.reply_text("Shutting down this laptop now.")
    shutdown_pc(delay_seconds=0)

async def confirm_shutdown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    pending_until = context.bot_data.get("shutdown_pending_until", 0)
    if time.time() > pending_until:
        await update.message.reply_text("No active shutdown request. Send /shutdown first.")
        return
    context.bot_data["shutdown_pending_until"] = 0
    await update.message.reply_text("Confirmed. Shutting down this laptop in 5 seconds.")
    shutdown_pc()

async def cancel_shutdown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    context.bot_data["shutdown_pending_until"] = 0
    cancel_shutdown()
    await update.message.reply_text("Shutdown cancelled.")

async def open_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    app_name = " ".join(context.args)
    if not app_name:
        await update.message.reply_text("Usage: /open <appname>")
        return
    try:
        operator_result = await asyncio.to_thread(
            execute_operator_command,
            app_name,
            False,
            context.bot_data.get("operator_target", "")
        )
    except Exception as e:
        telegram_log(f"[Telegram] /open operator command failed: {e}")
        await update.message.reply_text(f"Jarvis could not execute that laptop command: {e}")
        return
    if operator_result:
        context.bot_data["operator_target"] = operator_result.get("target") or context.bot_data.get("operator_target", "")
        telegram_log(f"[Telegram] Operator executed: {operator_result.get('parsed')}")
        await update.message.reply_text(operator_result["response"])
        screenshot = operator_result.get("screenshot")
        if screenshot:
            await safe_reply_photo(update, screenshot, caption="Jarvis operator result")
        return
    result = open_any_app(app_name)
    await update.message.reply_text(result)

async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    tasks = load_tasks()
    pending = [task for task in tasks if isinstance(task, dict) and task.get("status", "pending").lower() == "pending"]
    if not pending:
        await update.message.reply_text("No pending tasks.")
        return
    lines = ["Pending tasks:"]
    for index, task in enumerate(pending, start=1):
        remind_time = task.get("remind_time", "--:--")
        date = task.get("date") or task.get("repeat", "daily")
        lines.append(f"{index}. {date} {remind_time} - {task.get('title', 'Untitled task')}")
    await update.message.reply_text("\n".join(lines))

async def task_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    text = " ".join(context.args).strip()
    match = re.match(r"^(\d{2}:\d{2})\s+(.+)$", text)
    if not match:
        await update.message.reply_text("Usage: /task_add HH:MM task text\nExample: /task_add 09:00 Drink water")
        return
    remind_time, title = match.groups()
    tasks = load_tasks()
    tasks.append({
        "title": title.strip(),
        "status": "pending",
        "repeat": "daily",
        "remind_time": remind_time,
        "last_reminded": "",
    })
    save_tasks(tasks)
    await update.message.reply_text(f"Added daily task at {remind_time}: {title.strip()}")

async def task_done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /task_done number\nCheck numbers with /tasks")
        return
    target_index = int(context.args[0])
    tasks = load_tasks()
    pending_positions = [
        index for index, task in enumerate(tasks)
        if isinstance(task, dict) and task.get("status", "pending").lower() == "pending"
    ]
    if target_index < 1 or target_index > len(pending_positions):
        await update.message.reply_text("That task number was not found. Check /tasks.")
        return
    task = tasks[pending_positions[target_index - 1]]
    task["status"] = "done"
    save_tasks(tasks)
    await update.message.reply_text(f"Marked done: {task.get('title', 'Untitled task')}")

async def wa_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    status = get_whatsapp_status()
    msg = (
        "*WhatsApp Jarvis Status*\n\n"
        f"Configured: `{status['configured']}`\n"
        f"Paused: `{status['paused']}`\n"
        f"Autoreply enabled: `{status['autoreply_enabled']}`\n"
        f"Telegram logs: `{status['telegram_logs_enabled']}`\n"
        f"Webhook path: `{status['webhook_path']}`\n"
        f"Local port: `{status['port']}`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def wa_recent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    rows = get_recent_messages(limit=5)
    if not rows:
        await update.message.reply_text("No WhatsApp messages logged yet.")
        return

    parts = ["Recent WhatsApp Messages"]
    for row in rows:
        sender = row.get("sender_name") or row.get("sender")
        parts.append(
            "\n"
            f"{row.get('created_at')} - {sender}\n"
            f"Text: {row.get('incoming_text') or '(empty)'}\n"
            f"Decision: {row.get('decision')} / {row.get('status')}\n"
            f"Reply: {row.get('reply_text') or '(none)'}"
        )
    await update.message.reply_text("\n".join(parts))

async def wa_pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    pause_autoreply()
    await update.message.reply_text("WhatsApp auto-replies paused.")

async def wa_resume_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    resume_autoreply()
    await update.message.reply_text("WhatsApp auto-replies resumed.")

async def handle_text_command(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    text = normalize_telegram_command_text(text)
    if not text:
        await update.message.reply_text("I could not understand that command.")
        return
    lower_text = text.lower()

    if is_owner_activity_screenshot_pause_text(text):
        set_activity_screenshots_paused(True, reason="Owner confirmed they are controlling the PC from Telegram.")
        await update.message.reply_text(
            "Confirmed. I will stop sending activity screenshots while you are controlling the PC. Manual /screenshot still works."
        )
        return

    if is_activity_screenshot_resume_text(text):
        set_activity_screenshots_paused(False, reason="Owner resumed activity screenshots from Telegram.")
        await update.message.reply_text("Activity screenshots are enabled again.")
        return

    if "screenshot" in lower_text or "screen shot" in lower_text or "current screen" in lower_text:
        await update.message.reply_text("Taking your current laptop screenshot...")
        buf = take_screenshot()
        await safe_reply_photo(update, buf, caption="Your current PC screen")
        return

    if is_cancel_shutdown_text(lower_text):
        context.bot_data["shutdown_pending_until"] = 0
        cancel_shutdown()
        await update.message.reply_text("Shutdown cancelled.")
        return

    if is_close_all_text(lower_text):
        await update.message.reply_text("Closing browser tabs and open app windows now.")
        await asyncio.to_thread(close_all_tabs_and_apps)
        await update.message.reply_text("Close command completed.")
        return

    close_target_name = extract_close_target_text(lower_text)
    if close_target_name:
        await update.message.reply_text(f"Closing {close_target_name}...")
        closed = await asyncio.to_thread(close_target, close_target_name)
        if closed:
            await update.message.reply_text(f"Closed {close_target_name}.")
        else:
            await update.message.reply_text(f"I could not find {close_target_name} open.")
        return

    if is_unlock_text(lower_text):
        await update.message.reply_text("Trying to enter the saved Windows password.")
        ok = await asyncio.to_thread(unlock_screen)
        if ok:
            await update.message.reply_text("Unlock command completed.")
        else:
            await update.message.reply_text(get_last_unlock_message())
        return

    if is_shutdown_text(lower_text):
        await update.message.reply_text("Shutting down this laptop now.")
        shutdown_pc(delay_seconds=0)
        return

    added_tasks = add_tasks_from_text(text)
    if added_tasks:
        first = added_tasks[0]
        when = first.get("remind_time", "09:00")
        if first.get("repeat") == "once" and first.get("date"):
            await update.message.reply_text(f"Updated tasks: added {len(added_tasks)} task(s) for {first['date']} at {when}.")
        else:
            await update.message.reply_text(f"Updated daily tasks: added {len(added_tasks)} reminder(s) at {when}.")
        return

    if "telegram" in lower_text and any(word in lower_text for word in ["open", "launch", "start"]):
        await update.message.reply_text(open_any_app("telegram"))
        return

    try:
        operator_result = await asyncio.to_thread(
            execute_operator_command,
            text,
            False,
            context.bot_data.get("operator_target", "")
        )
    except Exception as e:
        telegram_log(f"[Telegram] Operator command failed: {e}")
        await update.message.reply_text(f"Jarvis could not execute that laptop command: {e}")
        return
    if operator_result:
        context.bot_data["operator_target"] = operator_result.get("target") or context.bot_data.get("operator_target", "")
        telegram_log(f"[Telegram] Operator executed: {operator_result.get('parsed')}")
        await update.message.reply_text(operator_result["response"])
        screenshot = operator_result.get("screenshot")
        if screenshot:
            await safe_reply_photo(update, screenshot, caption="Jarvis operator result")
        return

    if is_followup_video_command(text):
        last_query = context.bot_data.get("last_youtube_query", "")
        if last_query:
            await update.message.reply_text(f"Opening YouTube search for {last_query}...")
            open_media_command(f"play {last_query} on youtube")
        else:
            await update.message.reply_text("I do not have a recent YouTube video search yet.")
        return

    media_command = parse_media_command(text)
    if media_command:
        query = media_command.get("query")
        if query:
            await update.message.reply_text(f"Opening {media_command['service']} search for {query}...")
        else:
            await update.message.reply_text(f"Opening {media_command['service']}...")
        open_media_command(text)
        if media_command["service"] == "youtube" and query:
            context.bot_data["last_youtube_query"] = query
        return

    browser_command = parse_browser_command(text)
    if browser_command:
        await update.message.reply_text(f"Opening {browser_command['target']} in {browser_command['browser']}...")
        open_browser_command(text)
        return

    await update.message.reply_text("ðŸ§  Thinking...")
    result = brain.understand(text)
    action = result.get("action", "unknown")
    response = result.get("response", "")
    if action == "open_workspace":
        await update.message.reply_text(response)
        await update.message.reply_text(open_workspace())
    elif action == "sleep_screen":
        await update.message.reply_text(response)
        await update.message.reply_text(lock_screen())
    elif action == "wake_screen":
        pyautogui.moveRel(1, 0)
        time.sleep(0.1)
        pyautogui.moveRel(-1, 0)
        await update.message.reply_text("âœ… " + response)
    elif action == "unlock_screen":
        await update.message.reply_text(response or "Trying to enter the saved Windows password.")
        ok = await asyncio.to_thread(unlock_screen)
        if ok:
            await update.message.reply_text("Unlock command completed.")
        else:
            await update.message.reply_text(get_last_unlock_message())
    elif action in ("close_all_apps", "close_all_tabs"):
        await update.message.reply_text(response or "Closing browser tabs and open app windows.")
        await asyncio.to_thread(close_all_tabs_and_apps)
        await update.message.reply_text("Close command completed.")
    elif action in ("screenshot", "send_screenshot_telegram", "send_screenshot_to_telegram"):
        await update.message.reply_text(response or "Taking your current laptop screenshot...")
        buf = take_screenshot()
        await safe_reply_photo(update, buf, caption="Your current PC screen")
    elif action == "open_telegram":
        await update.message.reply_text(response or "Opening Telegram.")
        await update.message.reply_text(open_any_app("telegram"))
    elif action == "open_app":
        target = result.get("target") or result.get("app") or result.get("name")
        await update.message.reply_text(response or f"Opening {target}.")
        await update.message.reply_text(open_any_app(target or ""))
    elif action == "shutdown_pc":
        await update.message.reply_text(response or "Shutting down this laptop now.")
        shutdown_pc(delay_seconds=0)
    elif action == "cancel_shutdown":
        context.bot_data["shutdown_pending_until"] = 0
        cancel_shutdown()
        await update.message.reply_text(response or "Shutdown cancelled.")
    else:
        if any(w in text.lower() for w in ["open", "launch", "start"]):
            words = text.lower().replace("open","").replace("launch","").replace("start","").strip()
            await update.message.reply_text(open_any_app(words))
        else:
            await update.message.reply_text(f"ðŸ¤– {response}\n\nTry /help for commands.")

async def natural_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return
    preview = re.sub(r"\s+", " ", update.message.text or "").strip()[:160]
    telegram_log(f"[Telegram] Text message received from {update.effective_user.id}: {preview}")
    await handle_text_command(update, context, update.message.text)

def get_telegram_whisper_model():
    global _telegram_whisper_model
    with _telegram_whisper_lock:
        if _telegram_whisper_model is None:
            import whisper
            model_size = CONFIG.get("whisper_model", "base")
            print(f"[Telegram] Loading Whisper model for voice notes: {model_size}")
            _telegram_whisper_model = whisper.load_model(model_size)
        return _telegram_whisper_model

def transcribe_telegram_audio(path):
    model = get_telegram_whisper_model()
    result = model.transcribe(
        path,
        language="en",
        fp16=False,
        initial_prompt="The user is giving a short Jarvis command for controlling a Windows laptop.",
    )
    text = (result.get("text") or "").strip()
    segments = result.get("segments") or []
    no_speech_prob = segments[0].get("no_speech_prob", 0) if segments else 0
    if no_speech_prob and no_speech_prob > 0.75:
        print(f"[Telegram] Voice note rejected as silence/noise (no_speech_prob={no_speech_prob:.2f}).")
        return ""
    return text

async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text(unauthorized_msg())
        return

    telegram_log(f"[Telegram] Voice/audio message received from {update.effective_user.id}")
    message = update.message
    media = message.voice or message.audio or message.video_note
    if not media:
        await update.message.reply_text("I could not find audio in that message.")
        return

    duration = getattr(media, "duration", 0) or 0
    if duration > 120:
        await update.message.reply_text("That voice message is too long. Please keep Jarvis voice commands under 2 minutes.")
        return

    await update.message.reply_text("Listening to your voice command...")
    if message.voice:
        suffix = ".ogg"
    elif message.video_note:
        suffix = ".mp4"
    else:
        suffix = os.path.splitext(message.audio.file_name or "")[1] or ".ogg"
    tmp_path = ""
    try:
        tg_file = await context.bot.get_file(media.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(custom_path=tmp_path)
        transcript = await asyncio.to_thread(transcribe_telegram_audio, tmp_path)
        transcript = transcript.strip()
        if not transcript:
            await update.message.reply_text("I could not understand the voice note. Please try again clearly.")
            return
        telegram_log(f"[Telegram] Voice transcript: {transcript}")
        await update.message.reply_text(f"Heard: {transcript}")
        await handle_text_command(update, context, transcript)
    except Exception as e:
        print(f"[Telegram] Voice note processing failed: {e}")
        await update.message.reply_text(f"I could not process that voice note: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

async def notify_startup(app: Application):
    """Send a startup notification after the Telegram app is initialized."""
    if not AUTHORIZED_ID:
        return

    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await app.bot.send_message(
            chat_id=AUTHORIZED_ID,
            text=f"Jarvis is online!\nPC started at {now}",
            parse_mode="Markdown"
        )
    except BadRequest as e:
        if "chat not found" in str(e).lower():
            telegram_log("[Telegram] Could not send startup message: chat not found. Open your bot in Telegram, send /start, and check TELEGRAM_USER_ID.")
        else:
            telegram_log(f"[Telegram] Could not send startup message: {e}")
    except Exception as e:
        telegram_log(f"[Telegram] Could not send startup message: {e}")

async def telegram_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log Telegram polling errors without noisy tracebacks."""
    global _telegram_conflict_reported

    error = context.error
    if isinstance(error, Conflict):
        if not _telegram_conflict_reported:
            telegram_log("[Telegram] Polling conflict: another Jarvis/bot instance is already running for this bot token.")
            _telegram_conflict_reported = True
        return

    telegram_log(f"[Telegram] Error: {error}")

def run_bot():
    if not TELEGRAM_TOKEN:
        telegram_log("[Telegram] No bot token found.")
        return "fatal"

    logging.getLogger("telegram").setLevel(logging.CRITICAL)

    telegram_log("[Telegram] Starting Telegram bot...")
    builder = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .connect_timeout(20)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
    )
    if AUTHORIZED_ID:
        builder = builder.post_init(notify_startup)
    app = builder.build()
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("help",       start))
    app.add_handler(CommandHandler("status",     status_cmd))
    app.add_handler(CommandHandler("screenshot", screenshot_cmd))
    app.add_handler(CommandHandler("workspace",  workspace_cmd))
    app.add_handler(CommandHandler("lock",       lock_cmd))
    app.add_handler(CommandHandler("shutdown",   shutdown_cmd))
    app.add_handler(CommandHandler("confirm_shutdown", confirm_shutdown_cmd))
    app.add_handler(CommandHandler("cancel_shutdown",  cancel_shutdown_cmd))
    app.add_handler(CommandHandler("open",       open_cmd))
    app.add_handler(CommandHandler("tasks",      tasks_cmd))
    app.add_handler(CommandHandler("task_add",   task_add_cmd))
    app.add_handler(CommandHandler("task_done",  task_done_cmd))
    app.add_handler(CommandHandler("wa_status",  wa_status_cmd))
    app.add_handler(CommandHandler("wa_recent",  wa_recent_cmd))
    app.add_handler(CommandHandler("wa_pause",   wa_pause_cmd))
    app.add_handler(CommandHandler("wa_resume",  wa_resume_cmd))
    app.add_handler(MessageHandler((filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE) & ~filters.COMMAND, voice_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, natural_message))
    app.add_error_handler(telegram_error)

    telegram_log("[Telegram] Bot running!")
    try:
        app.run_polling(drop_pending_updates=True, close_loop=False)
    except Conflict:
        telegram_log("[Telegram] Could not start polling because another bot instance is already running.")
        return "conflict"
    return "stopped"

def start_telegram_bot():
    """Run bot safely in its own event loop thread and recover from network exits."""
    if not TELEGRAM_TOKEN:
        telegram_log("[Telegram] No bot token found.")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    retry_seconds = 5
    try:
        while True:
            try:
                result = run_bot()
                if result == "fatal":
                    return
                telegram_log(f"[Telegram] Polling stopped ({result}). Restarting in {retry_seconds}s...")
            except Exception as e:
                telegram_log(f"[Telegram] Polling crashed: {type(e).__name__}: {e}. Restarting in {retry_seconds}s...")
            time.sleep(retry_seconds)
            retry_seconds = min(retry_seconds * 2, 60)
    finally:
        loop.close()
