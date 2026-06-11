"""
monitor.py - Watches your PC and sends activity alerts to Telegram.
"""

import asyncio
import datetime
import io
import json
import os
import time

import pyautogui
from telegram import Bot
from telegram.error import TelegramError


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MONITOR_STATE_PATH = os.path.join(BASE_DIR, "monitor_state.json")
DEFAULT_MONITOR_STATE = {
    "activity_screenshots_paused": False,
    "updated_at": "",
    "reason": "",
}


def load_monitor_state():
    try:
        with open(MONITOR_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            state = DEFAULT_MONITOR_STATE.copy()
            state.update(data)
            return state
    except Exception:
        pass
    return DEFAULT_MONITOR_STATE.copy()


def save_monitor_state(state):
    state = DEFAULT_MONITOR_STATE.copy() | (state or {})
    tmp_path = MONITOR_STATE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, MONITOR_STATE_PATH)


def set_activity_screenshots_paused(paused, reason=""):
    state = load_monitor_state()
    state["activity_screenshots_paused"] = bool(paused)
    state["reason"] = reason
    state["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_monitor_state(state)
    return state


def activity_screenshots_paused():
    return bool(load_monitor_state().get("activity_screenshots_paused", False))


class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.bot = Bot(token=token)
        self.chat_id = chat_id

    async def send(self, message):
        await self.bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode="Markdown"
        )

    async def send_photo(self, photo, caption=""):
        await self.bot.send_photo(
            chat_id=self.chat_id,
            photo=photo,
            caption=caption
        )


class PCMonitor:
    def __init__(
        self,
        notifier,
        send_screenshot_on_activity=True,
        activity_alert_cooldown=300,
        check_interval=5
    ):
        self.notifier = notifier
        self.send_screenshot = send_screenshot_on_activity
        self.activity_alert_cooldown = activity_alert_cooldown
        self.check_interval = check_interval
        self.last_mouse_pos = pyautogui.position()
        self.last_alert_time = 0
        self.monitoring = True

    def take_screenshot_bytes(self):
        screenshot = pyautogui.screenshot()
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        buf.seek(0)
        return buf

    async def send_startup_alert(self):
        started = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await self.notifier.send(
            f"*Jarvis monitor is active.*\n"
            f"Started at {started}"
        )

    async def check_activity(self):
        current_pos = pyautogui.position()
        now = time.time()

        if current_pos == self.last_mouse_pos:
            return

        self.last_mouse_pos = current_pos

        if now - self.last_alert_time < self.activity_alert_cooldown:
            return

        self.last_alert_time = now
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        await self.notifier.send(
            f"*Activity detected on your PC!*\n"
            f"Time: {timestamp}\n"
            f"Someone moved the mouse or used the computer."
        )

        if self.send_screenshot and not activity_screenshots_paused():
            buf = self.take_screenshot_bytes()
            await self.notifier.send_photo(
                buf,
                caption="Screenshot at time of activity"
            )
        elif self.send_screenshot:
            print("[Monitor] Activity screenshot skipped because owner paused screenshots.")

    async def monitor_loop(self):
        print("[Monitor] PC activity monitoring started...")

        try:
            await self.send_startup_alert()
        except TelegramError as e:
            print(f"[Monitor] Could not send startup alert: {e}")

        while self.monitoring:
            try:
                await self.check_activity()
            except Exception as e:
                print(f"[Monitor] Error: {e}")
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self.monitoring = False
        print("[Monitor] Stopped.")


def start_pc_monitor(
    token,
    chat_id,
    send_screenshot_on_activity=True,
    activity_alert_cooldown=300,
    check_interval=5
):
    """Start PC activity monitoring in its own asyncio loop."""
    if not token or not chat_id:
        print("[Monitor] Missing Telegram token or chat ID; monitor not started.")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    notifier = TelegramNotifier(token=token, chat_id=chat_id)
    monitor = PCMonitor(
        notifier=notifier,
        send_screenshot_on_activity=send_screenshot_on_activity,
        activity_alert_cooldown=activity_alert_cooldown,
        check_interval=check_interval
    )

    try:
        loop.run_until_complete(monitor.monitor_loop())
    except Exception as e:
        print(f"[Monitor] Fatal error: {e}")
    finally:
        loop.close()
