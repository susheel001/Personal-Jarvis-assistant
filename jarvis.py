"""
JARVIS — Personal AI Assistant
Full Conversational Mode + Voice + Telegram
"""

import os
import sys
import json
import time
import threading
import argparse
import datetime
import re

BASE_DIR = os.path.dirname(__file__)

def setup_file_logging():
    """Allow pyw startup to stay hidden while still keeping readable logs."""
    if os.environ.get("JARVIS_LOG_TO_FILE") != "1":
        return
    out_path = os.path.join(BASE_DIR, "jarvis_runtime.out.log")
    err_path = os.path.join(BASE_DIR, "jarvis_runtime.err.log")
    sys.stdout = open(out_path, "a", buffering=1, encoding="utf-8", errors="replace")
    sys.stderr = open(err_path, "a", buffering=1, encoding="utf-8", errors="replace")
    print(f"\n[Jarvis] Hidden startup log attached at {datetime.datetime.now().isoformat(timespec='seconds')}")

setup_file_logging()

from voice import VoiceListener
from ai_brain import AIBrain
from task_manager import add_tasks_from_text
from actions import (
    execute_action,
    is_followup_video_command,
    get_last_unlock_message,
    open_media_command,
    parse_media_command,
    parse_browser_command,
    execute_operator_command,
    open_url_in_browser,
    save_password,
)
from speak import JarvisVoice

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

ENV_PATH = os.path.join(BASE_DIR, ".env")
STATUS_PATH = os.path.join(BASE_DIR, "jarvis_status.json")

DEFAULT_STATUS = {
    "state": "Offline",
    "last_command": "",
    "last_response": "",
    "updated_at": "",
}

def write_jarvis_status(state=None, last_command=None, last_response=None):
    data = DEFAULT_STATUS.copy()
    try:
        if os.path.exists(STATUS_PATH):
            with open(STATUS_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, dict):
                    data.update(existing)
    except Exception:
        pass

    if state is not None:
        data["state"] = state
    if last_command is not None:
        data["last_command"] = last_command
    if last_response is not None:
        data["last_response"] = last_response
    data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    tmp_path = STATUS_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, STATUS_PATH)
    except Exception as e:
        print(f"[Jarvis] Could not write UI status: {e}")

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

def save_env(data: dict):
    with open(ENV_PATH, "w") as f:
        for k, v in data.items():
            f.write(f"{k}={v}\n")

def prompt_env(env, key, prompt):
    value = input(prompt).strip()
    if value:
        env[key] = value

def setup():
    print("\n" + "="*55)
    print("  JARVIS SETUP — 2050 Edition")
    print("="*55)
    env = load_env()

    print("\n[1] GROQ API KEY — https://console.groq.com")
    env["GROQ_API_KEY"] = input("    Enter Groq API key: ").strip()

    print("\n[2] TELEGRAM BOT TOKEN — from @BotFather")
    env["TELEGRAM_BOT_TOKEN"] = input("    Enter Telegram Bot Token: ").strip()

    print("\n[3] YOUR TELEGRAM USER ID — from @userinfobot")
    env["TELEGRAM_USER_ID"] = input("    Enter your Telegram User ID: ").strip()

    print("\n[4] WHATSAPP CLOUD API (optional - press Enter to skip)")
    prompt_env(env, "WHATSAPP_ACCESS_TOKEN", "    Enter WhatsApp Access Token: ")
    prompt_env(env, "WHATSAPP_PHONE_NUMBER_ID", "    Enter WhatsApp Phone Number ID: ")
    prompt_env(env, "WHATSAPP_VERIFY_TOKEN", "    Enter WhatsApp Webhook Verify Token: ")
    prompt_env(env, "WHATSAPP_APP_SECRET", "    Enter WhatsApp App Secret: ")
    env.setdefault("WHATSAPP_AUTOREPLY_ENABLED", "true")

    print("\n[5] WINDOWS LOGIN PASSWORD (stored securely)")
    save_password(input("    Enter your Windows password: ").strip())

    save_env(env)
    print("\n✅ Setup complete! Run: py -3.11 jarvis.py\n")


# ── Conversation history for context ─────────────────────────────────────────

CONVERSATION_HISTORY = []
MAX_HISTORY = 10  # remember last 10 exchanges

def is_shutdown_request(text):
    text = (text or "").lower()
    return bool(re.search(r"\b(shutdown|shut down|turn off|power off)\b", text)) and not is_shutdown_cancel(text)

def is_shutdown_confirm(text):
    text = (text or "").lower().strip()
    return bool(re.search(r"\b(confirm shutdown|yes shutdown|shutdown now|confirm power off|yes power off)\b", text))

def is_shutdown_cancel(text):
    text = (text or "").lower()
    return bool(re.search(r"\b(cancel shutdown|abort shutdown|stop shutdown|cancel power off)\b", text))

def is_close_all_request(text):
    text = (text or "").lower()
    has_close = bool(re.search(r"\b(close|exit|quit)\b", text))
    has_all = bool(re.search(r"\b(all|everything)\b", text))
    has_target = bool(re.search(r"\b(tabs?|apps?|applications?|windows?)\b", text))
    return has_close and has_all and has_target

def extract_close_target(command_text):
    text = (command_text or "").lower().strip()
    text = re.sub(r"[?.!,]+$", "", text)
    if is_close_all_request(text):
        return ""
    match = re.search(r"\b(close|exit|quit)\s+(?:my\s+|the\s+|a\s+|an\s+)?(.+)$", text)
    if not match:
        return ""
    target = match.group(2).strip()
    target = re.sub(r"\b(app|application|window|tab|website|site|please|now)\b", " ", target)
    target = re.sub(r"\s+", " ", target).strip()
    return target

def is_unlock_request(text):
    text = (text or "").lower()
    return bool(re.search(r"\b(open password|open the password|unlock|login|log in|enter password)\b", text))

def extract_open_target(command_text):
    text = (command_text or "").lower().strip()
    text = re.sub(r"[?.!,]+$", "", text)
    match = re.search(r"\b(open|launch|start|run)\s+(?:my\s+|the\s+|a\s+|an\s+)?(.+)$", text)
    if not match:
        return ""

    target = match.group(2).strip()
    target = re.sub(r"\b(please|app|application|window)\b", " ", target)
    return " ".join(target.split())

JARVIS_SYSTEM_PROMPT = """You are Jarvis, a highly intelligent, witty, and loyal personal AI assistant — 
just like from Iron Man. You speak in a calm, professional British-butler style. 
You always call the user "sir". You are helpful, friendly, and occasionally witty.

You can do two things:
1. Have a natural conversation with the user
2. Execute PC commands

For PC commands, respond with JSON:
{"action": "wake_screen|unlock_screen|open_workspace|sleep_screen|shutdown_pc|cancel_shutdown|close_app|close_all_apps|screenshot|send_screenshot_telegram|open_telegram|open_app|focus_window", "target": "app or window name when needed", "response": "what you say out loud"}

For normal conversation (questions, chat, jokes, advice), respond naturally in plain text as Jarvis would.

Examples:
User: "how are you?" → "I am functioning at full capacity, sir. Thank you for asking. How may I assist you today?"
User: "tell me a joke" → "Why do programmers prefer dark mode? Because light attracts bugs, sir."
User: "what time is it?" → "It is currently [time], sir."
User: "open my workspace" → {"action": "open_workspace", "response": "Of course sir, opening your workspace right away."}
User: "lock the screen" → {"action": "sleep_screen", "response": "Locking your screen sir. Stay safe."}
User: "wake up" → {"action": "wake_screen", "response": "Waking up the screen sir."}

User: "shutdown laptop" -> {"action": "shutdown_pc", "response": "Shutting down now, sir."}
User: "cancel shutdown" -> {"action": "cancel_shutdown", "response": "Cancelling shutdown, sir."}
User: "close VS Code" -> {"action": "close_app", "target": "vs code", "response": "Closing VS Code, sir."}
User: "close YouTube" -> {"action": "close_app", "target": "youtube", "response": "Closing YouTube, sir."}
User: "close all tabs and apps" -> {"action": "close_all_apps", "response": "Closing browser tabs and open app windows, sir."}
User: "take a screenshot" -> {"action": "screenshot", "response": "Capturing the current screen, sir."}
User: "send screenshot to my Telegram" -> {"action": "send_screenshot_telegram", "response": "Sending the current screen to your Telegram, sir."}
User: "open Telegram" -> {"action": "open_telegram", "response": "Opening Telegram, sir."}
User: "open Chrome" -> {"action": "open_app", "target": "chrome", "response": "Opening Chrome, sir."}
User: "launch calculator" -> {"action": "open_app", "target": "calculator", "response": "Opening Calculator, sir."}

Always be concise, warm, and professional. Never break character."""


class ConversationalBrain:
    def __init__(self, groq_api_key, groq_model="llama-3.3-70b-versatile"):
        self.groq_api_key = self.normalize_api_key(groq_api_key)
        self.groq_model = groq_model
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"

    def normalize_api_key(self, api_key):
        api_key = (api_key or "").strip().strip('"').strip("'")
        if api_key.lower().startswith("bearer "):
            api_key = api_key.split(" ", 1)[1].strip()
        return api_key

    def is_online(self):
        import httpx
        try:
            httpx.get("https://api.groq.com", timeout=2)
            return True
        except:
            return False

    def chat(self, user_message):
        """Send message with full conversation history"""
        import httpx, json

        if not self.groq_api_key or not self.groq_api_key.startswith("gsk_"):
            return {"type": "speech", "text": "Your Groq API key looks invalid, sir. Please update it in the .env file."}

        if not self.is_online():
            return {"type": "speech", "text": "I am sorry sir, no internet connection right now."}

        # Add current time context
        now = datetime.datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
        system = JARVIS_SYSTEM_PROMPT + f"\n\nCurrent date and time: {now}"

        # Build messages with history
        messages = [{"role": "system", "content": system}]
        messages += CONVERSATION_HISTORY[-MAX_HISTORY:]
        messages.append({"role": "user", "content": user_message})

        try:
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.groq_model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 300
            }
            response = httpx.post(self.groq_url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()

            # Save to history
            CONVERSATION_HISTORY.append({"role": "user", "content": user_message})
            CONVERSATION_HISTORY.append({"role": "assistant", "content": content})

            # Check if it's a PC action (JSON) or conversation (text)
            try:
                # Try parsing as JSON action
                clean = content.strip().strip("```json").strip("```").strip()
                data = json.loads(clean)
                if "action" in data:
                    return {
                        "type": "action",
                        "action": data["action"],
                        "target": data.get("target") or data.get("app") or data.get("name"),
                        "text": data.get("response", "")
                    }
            except:
                pass

            # It's a normal conversation response
            return {"type": "speech", "text": content}

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (401, 403):
                print("[Brain] Groq authentication failed. Check GROQ_API_KEY in .env.")
                return {"type": "speech", "text": "Groq rejected my API key, sir. Please create a new Groq API key and update the .env file."}
            print(f"[Brain] HTTP error: {e}")
            return {"type": "speech", "text": "I had trouble reaching Groq, sir. Please try again."}
        except Exception as e:
            print(f"[Brain] Error: {e}")
            return {"type": "speech", "text": "I encountered an issue sir. Please try again."}


def run_voice_loop(brain, speaker):
    def speak_status(text, command=None, ready_after=True):
        write_jarvis_status("Speaking", last_command=command, last_response=text)
        speaker.speak(text)
        if ready_after:
            write_jarvis_status("Ready")

    write_jarvis_status("Starting")
    voice = VoiceListener(
        model_size=CONFIG.get("whisper_model", "tiny"),
        voice_config=CONFIG.get("voice", {})
    )

    # Startup
    speaker.startup_greeting()
    time.sleep(0.5)
    speaker.standby()
    write_jarvis_status("Ready", last_response="Jarvis is online and standing by.")
    voice_config = CONFIG.get("voice", {})
    wake_phrases = voice_config.get("wake_phrases") or [CONFIG.get("wake_word", "jarvis")]
    print(f"\n[Jarvis] Say one wake phrase to talk: {', '.join(wake_phrases)}\n")
    shutdown_pending_until = 0
    last_youtube_query = ""
    last_operator_target = ""

    while True:
        try:
            # Wait for wake word
            write_jarvis_status("Listening")
            wake_text = voice.listen_for_wake_word(wake_word=wake_phrases)
            speaker.wake_word_response()
            time.sleep(0.3)

            # If the wake phrase already included a command, use it directly.
            command_text = voice.command_from_wake_text(wake_text, wake_word=wake_phrases)
            if command_text:
                print(f"[Jarvis] Command from wake phrase: {command_text}")
            else:
                frames = voice.record_command()
                command_text = voice.transcribe(frames)

            if not command_text or len(command_text) < 2:
                write_jarvis_status("Speaking", last_response="I did not catch that.")
                speaker.not_understood()
                write_jarvis_status("Ready")
                continue

            print(f"[You] {command_text}")
            write_jarvis_status("Listening", last_command=command_text)

            if is_shutdown_cancel(command_text):
                execute_action("cancel_shutdown")
                speak_status("Shutdown cancelled, sir.", command_text)
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            if is_close_all_request(command_text):
                speak_status("Closing browser tabs and open apps now, sir.", command_text)
                execute_action("close_all_apps")
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            close_target = extract_close_target(command_text)
            if close_target:
                speak_status(f"Closing {close_target}, sir.", command_text)
                ok = execute_action("close_app", target=close_target)
                if not ok:
                    speak_status(f"I could not find {close_target} open, sir.", command_text)
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            if is_unlock_request(command_text):
                ok = execute_action("unlock_screen")
                if ok:
                    speak_status("Entered your saved Windows password, sir.", command_text)
                else:
                    speak_status(get_last_unlock_message(), command_text)
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            if is_shutdown_request(command_text):
                speak_status("Shutting down now, sir.", command_text)
                execute_action("shutdown_pc")
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            added_tasks = add_tasks_from_text(command_text)
            if added_tasks:
                count = len(added_tasks)
                first = added_tasks[0]
                when = first.get("remind_time", "09:00")
                if first.get("repeat") == "once" and first.get("date"):
                    response = f"Updated your tasks. I added {count} task for {first['date']} at {when}, sir."
                else:
                    response = f"Updated your daily tasks. I added {count} reminder at {when}, sir."
                speak_status(response, command_text)
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            if is_followup_video_command(command_text):
                if last_youtube_query:
                    speak_status(f"Opening the video search for {last_youtube_query} on YouTube, sir.", command_text)
                    open_media_command(f"play {last_youtube_query} on youtube")
                else:
                    speak_status("I do not have a recent YouTube video search yet, sir.", command_text)
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            operator_result = execute_operator_command(
                command_text,
                telegram_screenshot=True,
                context_target=last_operator_target
            )
            if operator_result:
                last_operator_target = operator_result.get("target") or last_operator_target
                speak_status(operator_result["response"], command_text)
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            media_command = parse_media_command(command_text)
            if media_command:
                service = media_command["service"]
                action = media_command["action"]
                query = media_command.get("query")
                if action == "open_app":
                    speak_status("Opening Spotify, sir.", command_text)
                elif action == "open_home":
                    speak_status("Opening YouTube, sir.", command_text)
                elif service == "youtube":
                    speak_status(f"Searching YouTube for {query}, sir.", command_text)
                elif service == "spotify":
                    speak_status(f"Searching Spotify for {query}, sir.", command_text)
                open_media_command(command_text)
                if service == "youtube" and query:
                    last_youtube_query = query
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            browser_command = parse_browser_command(command_text)
            if browser_command:
                speak_status(f"Opening {browser_command['target']} in {browser_command['browser']}, sir.", command_text)
                open_url_in_browser(browser_command["url"], browser_command["browser"])
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            open_target = extract_open_target(command_text)
            if open_target:
                speak_status(f"Opening {open_target}, sir.", command_text)
                execute_action("open_app", target=open_target)
                print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
                time.sleep(0.5)
                continue

            # Send to conversational brain
            write_jarvis_status("Thinking", last_command=command_text)
            result = brain.chat(command_text)

            if result["type"] == "action":
                # PC command
                speak_status(result["text"], command_text)
                action = result["action"]
                target = result.get("target")

                if action == "open_workspace":
                    execute_action(action)
                    time.sleep(3)
                    speaker.workspace_done()

                elif action == "unlock_screen":
                    ok = execute_action(action)
                    time.sleep(2)
                    if ok:
                        speaker.unlocked_done()
                    else:
                        speak_status(get_last_unlock_message(), command_text)

                elif action == "sleep_screen":
                    time.sleep(1)
                    execute_action(action)

                elif action == "shutdown_pc":
                    speak_status("Shutting down now, sir.", command_text)
                    execute_action(action)

                elif action == "cancel_shutdown":
                    execute_action(action)

                else:
                    execute_action(action, target=target)

            else:
                # Normal conversation — just speak
                speak_status(result["text"], command_text)

            print("\n[Jarvis] Ready. Say your wake phrase anytime.\n")
            write_jarvis_status("Ready")
            time.sleep(0.5)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[Voice] Error: {e}")
            write_jarvis_status("Error", last_response=str(e))
            time.sleep(1)


def main():
    print("\n" + "="*55)
    print("  JARVIS — Conversational AI Assistant")
    print("="*55 + "\n")

    env            = load_env()
    groq_key       = env.get("GROQ_API_KEY", "")
    telegram_token = env.get("TELEGRAM_BOT_TOKEN", "")
    telegram_user_id = env.get("TELEGRAM_USER_ID", "")

    if not groq_key:
        print("No Groq API key. Run: py -3.11 jarvis.py --setup\n")

    brain   = ConversationalBrain(groq_api_key=groq_key, groq_model=CONFIG.get("groq_model", "llama-3.3-70b-versatile"))
    speaker = JarvisVoice()

    if telegram_token:
        print("[Jarvis] Starting Telegram bot...")
        from telegram_bot import start_telegram_bot
        t = threading.Thread(target=start_telegram_bot, daemon=True)
        t.start()
        print("[Jarvis] Telegram bot running!\n")

        monitor_config = CONFIG.get("monitor", {})
        if monitor_config.get("enabled", False) and telegram_user_id:
            print("[Jarvis] Starting PC monitor...")
            from monitor import start_pc_monitor
            monitor_thread = threading.Thread(
                target=start_pc_monitor,
                kwargs={
                    "token": telegram_token,
                    "chat_id": telegram_user_id,
                    "send_screenshot_on_activity": monitor_config.get("send_screenshot_on_activity", True),
                    "activity_alert_cooldown": monitor_config.get("activity_alert_cooldown_seconds", 300),
                    "check_interval": monitor_config.get("check_interval_seconds", 5),
                },
                daemon=True
            )
            monitor_thread.start()
            print("[Jarvis] PC monitor running!\n")

        whatsapp_config = CONFIG.get("whatsapp", {})
        if whatsapp_config.get("enabled", False):
            print("[Jarvis] Starting WhatsApp webhook...")
            from whatsapp_bot import start_whatsapp_bot
            whatsapp_thread = threading.Thread(
                target=start_whatsapp_bot,
                kwargs={
                    "host": whatsapp_config.get("host", "0.0.0.0"),
                    "port": whatsapp_config.get("port", 5005),
                },
                daemon=True
            )
            whatsapp_thread.start()
            print("[Jarvis] WhatsApp webhook thread started!\n")

        print("[Jarvis] Starting task reminders...")
        from task_manager import start_task_reminders
        task_thread = threading.Thread(
            target=start_task_reminders,
            kwargs={
                "token": telegram_token,
                "chat_id": telegram_user_id,
                "status_writer": write_jarvis_status,
                "check_interval": 30,
            },
            daemon=True
        )
        task_thread.start()
        print("[Jarvis] Task reminders running!\n")
    else:
        print("[Jarvis] No Telegram token. Run --setup to enable.\n")

    try:
        run_voice_loop(brain, speaker)
    except KeyboardInterrupt:
        print("\n[Jarvis] Shutting down...")
        speaker.goodbye()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true")
    args = parser.parse_args()
    if args.setup:
        setup()
    else:
        main()
