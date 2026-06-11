import httpx
import json

SYSTEM_PROMPT = """You are Jarvis, a personal assistant that controls a Windows laptop.
Your job is to understand voice commands and return ONLY a JSON action object.

Available actions:
- wake_screen     : Wake up / turn on the screen
- unlock_screen   : Type the password and unlock the laptop  
- open_workspace  : Open VS Code, Chrome, Spotify, and Claude.ai
- sleep_screen    : Lock or put the screen to sleep
- shutdown_pc    : Shut down the laptop immediately
- cancel_shutdown: Cancel a pending shutdown or restart
- close_all_apps : Close browser tabs and visible user app windows
- screenshot      : Save a screenshot of the current laptop screen
- send_screenshot_telegram : Send the current laptop screenshot to the owner's Telegram
- open_telegram   : Open Telegram on the laptop
- open_app        : Open any named Windows app or window. Include "target".
- focus_window    : Bring an already-open window to the front. Include "target".
- close_app       : Close one named app, browser tab, or window. Include "target".
- unknown         : Command not recognized

ALWAYS respond with ONLY this JSON format, nothing else:
{"action": "action_name", "target": "app name if needed", "confidence": 0.9, "response": "What Jarvis says out loud"}

Examples:
User: "wake up the screen" → {"action": "wake_screen", "confidence": 0.95, "response": "Waking up the screen now."}
User: "open the password" → {"action": "unlock_screen", "confidence": 0.95, "response": "Entering your password."}
User: "open my workspace" → {"action": "open_workspace", "confidence": 0.95, "response": "Opening your workspace."}
User: "lock the screen" → {"action": "sleep_screen", "confidence": 0.9, "response": "Locking the screen."}
User: "shutdown laptop" -> {"action": "shutdown_pc", "confidence": 0.95, "response": "Shutting down now."}
User: "cancel shutdown" -> {"action": "cancel_shutdown", "confidence": 0.95, "response": "Cancelling the pending shutdown."}
User: "close all tabs and apps" -> {"action": "close_all_apps", "confidence": 0.95, "response": "Closing browser tabs and open app windows."}
User: "take a screenshot" -> {"action": "screenshot", "confidence": 0.95, "response": "Capturing the current screen."}
User: "send me the current screenshot" -> {"action": "send_screenshot_telegram", "confidence": 0.95, "response": "Sending the current screen to your Telegram."}
User: "open Telegram" -> {"action": "open_telegram", "confidence": 0.95, "response": "Opening Telegram."}
User: "open Chrome" -> {"action": "open_app", "target": "chrome", "confidence": 0.95, "response": "Opening Chrome."}
User: "launch calculator" -> {"action": "open_app", "target": "calculator", "confidence": 0.95, "response": "Opening Calculator."}
User: "close VS Code" -> {"action": "close_app", "target": "vs code", "confidence": 0.95, "response": "Closing VS Code."}
User: "close YouTube" -> {"action": "close_app", "target": "youtube", "confidence": 0.95, "response": "Closing YouTube."}
"""

class AIBrain:
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
        """Check if internet is available"""
        try:
            httpx.get("https://api.groq.com", timeout=2)
            return True
        except:
            return False

    def ask_groq(self, command):
        """Send command to Groq API"""
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": command}
            ],
            "temperature": 0.1,
            "max_tokens": 150
        }
        response = httpx.post(self.groq_url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def understand(self, command):
        """Understand a command using Groq"""
        if not self.groq_api_key or not self.groq_api_key.startswith("gsk_"):
            print("[Jarvis] Groq API key is missing or invalid.")
            return {
                "action": "unknown",
                "confidence": 0,
                "response": "Your Groq API key looks invalid. Please update it in the .env file."
            }
        if not self.is_online():
            print("[Jarvis] ⚠ No internet connection.")
            return {
                "action": "unknown",
                "confidence": 0,
                "response": "I need internet to understand commands. Please connect and try again."
            }
        try:
            print("[Jarvis] Sending to Groq...")
            return self.ask_groq(command)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                print("[Jarvis] Groq authentication failed. Check GROQ_API_KEY in .env.")
                return {
                    "action": "unknown",
                    "confidence": 0,
                    "response": "Groq rejected my API key. Please create a new Groq API key and update the .env file."
                }
            print(f"[Jarvis] Groq HTTP error: {e}")
            return {
                "action": "unknown",
                "confidence": 0,
                "response": "Sorry, I had trouble connecting to my brain. Please try again."
            }
        except Exception as e:
            print(f"[Jarvis] Groq error: {e}")
            return {
                "action": "unknown",
                "confidence": 0,
                "response": "Sorry, I had trouble connecting to my brain. Please try again."
            }
