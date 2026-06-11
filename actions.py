import subprocess
import os
import time
import ctypes
import keyring
import webbrowser
import json
import pyautogui
import io
import datetime
import httpx
import re
from urllib.parse import quote, quote_plus

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

try:
    import yt_dlp
except Exception:
    yt_dlp = None

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
OPERATOR_STATE_PATH = os.path.join(os.path.dirname(__file__), "operator_state.json")

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

def load_operator_state():
    try:
        with open(OPERATOR_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_operator_state(target="", command_type=""):
    data = {
        "last_target": normalize_operator_target(target),
        "last_command_type": command_type,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        tmp_path = OPERATOR_STATE_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, OPERATOR_STATE_PATH)
    except Exception as e:
        print(f"[Jarvis] Could not save operator state: {e}")

# ─── Password Management ─────────────────────────────────────────────────────

SERVICE_NAME = "jarvis_laptop"
USERNAME = "laptop_user"
LAST_UNLOCK_MESSAGE = ""

def save_password(password):
    """Save your Windows password securely (run once during setup)"""
    keyring.set_password(SERVICE_NAME, USERNAME, password)
    print("[Jarvis] Password saved securely.")

def get_password():
    """Retrieve saved password"""
    return keyring.get_password(SERVICE_NAME, USERNAME)

def get_last_unlock_message():
    return LAST_UNLOCK_MESSAGE or "Unlock command could not complete."

# ─── Screen Control ───────────────────────────────────────────────────────────

def wake_screen():
    """Wake up the screen on Windows"""
    print("[Jarvis] Waking up screen...")
    # Move mouse slightly to wake screen
    pyautogui.moveRel(1, 0)
    time.sleep(0.1)
    pyautogui.moveRel(-1, 0)
    # Press a key to ensure screen wakes
    pyautogui.press('shift')
    time.sleep(0.5)
    print("[Jarvis] Screen should be awake.")

def sleep_screen():
    """Lock the Windows screen"""
    print("[Jarvis] Locking screen...")
    # Windows key + L = lock screen
    ctypes.windll.user32.LockWorkStation()

def shutdown_pc(delay_seconds=0):
    """Shut down Windows after a short delay."""
    delay = str(max(0, int(delay_seconds)))
    print(f"[Jarvis] Shutting down PC in {delay} seconds...")
    subprocess.Popen(["shutdown", "/s", "/t", delay])
    return True

def restart_pc(delay_seconds=5):
    """Restart Windows after a short delay."""
    delay = str(max(0, int(delay_seconds)))
    print(f"[Jarvis] Restarting PC in {delay} seconds...")
    subprocess.Popen(["shutdown", "/r", "/t", delay])
    return True

def cancel_shutdown():
    """Cancel a pending Windows shutdown or restart."""
    print("[Jarvis] Cancelling pending shutdown/restart...")
    subprocess.Popen(["shutdown", "/a"])
    return True

def close_all_tabs_and_apps():
    """Close browser tabs and visible user app windows without closing Jarvis itself."""
    print("[Jarvis] Closing browser tabs and user app windows...")
    protected_title_words = {
        "jarvis",
        "command prompt",
        "windows powershell",
        "powershell",
        "terminal",
    }
    closed = 0

    # Browser tabs/windows first.
    for process_name in ["chrome.exe", "msedge.exe", "firefox.exe"]:
        try:
            subprocess.run(
                ["taskkill", "/IM", process_name, "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception as e:
            print(f"[Jarvis] Could not close {process_name}: {e}")

    time.sleep(0.5)

    # Then close other visible windows gracefully.
    try:
        for window in pyautogui.getAllWindows():
            title = (window.title or "").strip()
            if not title:
                continue
            lower_title = title.lower()
            if any(word in lower_title for word in protected_title_words):
                continue
            try:
                if window.isMinimized:
                    window.restore()
                window.close()
                closed += 1
                time.sleep(0.15)
            except Exception:
                continue
    except Exception as e:
        print(f"[Jarvis] Could not enumerate windows to close: {e}")

    print(f"[Jarvis] Close command completed. Windows closed: {closed}")
    return True

def close_target(target):
    """Close one app window or browser tab/window by title target."""
    target = clean_web_target(target) or clean_app_name(target)
    if not target:
        print("[Jarvis] No close target provided.")
        return False

    if target in {"all", "everything", "all apps", "all tabs", "all windows"}:
        return close_all_tabs_and_apps()

    title_candidates = []
    title_candidates.extend(operator_window_titles(target))
    title_candidates.append(target)

    # Known browser-site targets should close only the matching tab/window.
    site_targets = set(site_urls().keys()) | {
        "claude",
        "claude ai",
        "chatgpt",
        "chat gpt",
        "gemini",
        "youtube",
        "you tube",
        "gmail",
        "whatsapp",
        "whatsapp web",
        "instagram",
        "telegram",
    }
    browser_like = target in site_targets

    try:
        seen = set()
        for title in title_candidates:
            if not title:
                continue
            for window in pyautogui.getWindowsWithTitle(title):
                if not window.title or window._hWnd in seen:
                    continue
                seen.add(window._hWnd)
                lower_title = window.title.lower()
                if "jarvis" in lower_title:
                    continue
                if window.isMinimized:
                    window.restore()
                window.activate()
                time.sleep(0.4)
                if browser_like and any(browser in lower_title for browser in ["chrome", "edge", "firefox", "youtube", "gmail", "claude"]):
                    pyautogui.hotkey("ctrl", "w")
                else:
                    window.close()
                print(f"[Jarvis] Closed target {target}: {window.title}")
                return True
    except Exception as e:
        print(f"[Jarvis] Window close failed for {target}: {e}")

    if browser_like and target not in {"chrome", "google chrome", "edge", "microsoft edge", "firefox"}:
        browser_focused = (
            focus_existing_window("Google Chrome")
            or focus_existing_window("Microsoft Edge")
            or focus_existing_window("Mozilla Firefox")
        )
        if browser_focused:
            try:
                time.sleep(0.3)
                pyautogui.hotkey("ctrl", "shift", "a")
                time.sleep(0.4)
                paste_text(target, press_enter=True)
                time.sleep(0.5)
                pyautogui.hotkey("ctrl", "w")
                print(f"[Jarvis] Tried closing browser tab for {target} using tab search.")
                return True
            except Exception as e:
                print(f"[Jarvis] Browser tab-search close failed for {target}: {e}")

    # Fall back to process kill for explicit app names only.
    process_names = {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "firefox": "firefox.exe",
        "spotify": "Spotify.exe",
        "vs code": "Code.exe",
        "vscode": "Code.exe",
        "visual studio code": "Code.exe",
        "notepad": "notepad.exe",
        "telegram": "Telegram.exe",
        "calculator": "CalculatorApp.exe",
    }
    process_name = process_names.get(target)
    if process_name:
        try:
            subprocess.run(
                ["taskkill", "/IM", process_name, "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            print(f"[Jarvis] Closed process for {target}.")
            return True
        except Exception as e:
            print(f"[Jarvis] Could not close process for {target}: {e}")

    print(f"[Jarvis] Could not find anything open for: {target}")
    return False

def is_screen_locked():
    """Check if the screen/workstation is locked"""
    # This is a heuristic — checks if desktop is accessible
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return hwnd == 0

def is_secure_desktop_active():
    """Return True when Windows is on the lock/UAC secure desktop."""
    DESKTOP_SWITCHDESKTOP = 0x0100
    user32 = ctypes.windll.user32
    h_desktop = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not h_desktop:
        return True
    try:
        return user32.SwitchDesktop(h_desktop) == 0
    finally:
        user32.CloseDesktop(h_desktop)

# ─── Unlock / Password Entry ──────────────────────────────────────────────────

def unlock_screen():
    """Wake screen and enter password"""
    global LAST_UNLOCK_MESSAGE
    print("[Jarvis] Attempting to unlock screen...")
    password = get_password()

    if not password:
        LAST_UNLOCK_MESSAGE = "No saved Windows password found. Run Jarvis setup and save the password first."
        print("[Jarvis] ⚠ No password saved! Run setup first.")
        print("[Jarvis] Run: python jarvis.py --setup")
        return False

    if is_secure_desktop_active():
        LAST_UNLOCK_MESSAGE = "Windows is on the secure lock screen. Normal apps like Jarvis cannot type the password there."
        print("[Jarvis] Windows secure desktop is active; normal apps cannot type the lock-screen password.")
        return False

    # Step 1: Wake screen
    wake_screen()
    time.sleep(1)

    # Step 2: Press keys/click to show password field on the lock screen.
    pyautogui.press('space')
    time.sleep(0.3)
    pyautogui.press('enter')
    time.sleep(0.3)
    pyautogui.click(pyautogui.size().width // 2, pyautogui.size().height // 2)
    time.sleep(0.8)

    # Step 3: Type password
    pyautogui.typewrite(password, interval=0.05)
    time.sleep(0.3)

    # Step 4: Press Enter to login
    pyautogui.press('enter')
    time.sleep(1.5)
    LAST_UNLOCK_MESSAGE = "Password entered."
    print("[Jarvis] Password entered.")
    return True

# ─── Workspace Launcher ───────────────────────────────────────────────────────

def open_workspace():
    """Open all workspace apps from config"""
    print("[Jarvis] Opening workspace...")
    apps = CONFIG.get("workspace", [])

    for app in apps:
        name = app.get("name")
        app_type = app.get("type")

        try:
            if app_type == "url":
                print(f"[Jarvis] Opening {name} in browser...")
                webbrowser.open(app.get("url"))
                time.sleep(1)

            elif app_type == "app":
                path = os.path.expandvars(app.get("path", ""))
                if os.path.exists(path):
                    print(f"[Jarvis] Launching {name}...")
                    subprocess.Popen([path])
                    time.sleep(1.5)
                else:
                    # Try opening by name as fallback
                    print(f"[Jarvis] Path not found for {name}, trying by name...")
                    os.startfile(name) if hasattr(os, 'startfile') else None

        except Exception as e:
            print(f"[Jarvis] Could not open {name}: {e}")

    print("[Jarvis] Workspace opened!")

def take_screenshot():
    """Capture the current screen and save it locally."""
    screenshots_dir = os.path.join(os.path.dirname(__file__), "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(screenshots_dir, f"screenshot_{timestamp}.png")
    pyautogui.screenshot().save(path)
    print(f"[Jarvis] Screenshot saved: {path}")
    return path

def send_screenshot_to_telegram():
    """Capture the screen and send it to the configured Telegram user."""
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_USER_ID", "")

    if not token or not chat_id:
        print("[Jarvis] Telegram token or user ID missing; cannot send screenshot.")
        return False

    screenshot = pyautogui.screenshot()
    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    buf.seek(0)

    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": "Jarvis current screen"},
            files={"photo": ("screenshot.png", buf, "image/png")},
            timeout=20,
        )
        response.raise_for_status()
        print("[Jarvis] Screenshot sent to Telegram.")
        return True
    except Exception as e:
        print(f"[Jarvis] Could not send screenshot to Telegram: {e}")
        return False

def open_telegram():
    """Open Telegram Desktop if available, otherwise open Telegram Web."""
    known_paths = [
        os.path.expandvars(r"%APPDATA%\Telegram Desktop\Telegram.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Telegram Desktop\Telegram.exe"),
    ]

    for path in known_paths:
        if os.path.exists(path):
            subprocess.Popen([path])
            print("[Jarvis] Opened Telegram Desktop.")
            return True

    webbrowser.open("https://web.telegram.org/")
    print("[Jarvis] Opened Telegram Web.")
    return True

def focus_existing_window(target):
    """Bring an already-open window to the front when its title matches."""
    try:
        for window in pyautogui.getWindowsWithTitle(target):
            if not window.title:
                continue
            if window.isMinimized:
                window.restore()
            window.activate()
            print(f"[Jarvis] Focused existing window: {window.title}")
            return True
    except Exception as e:
        print(f"[Jarvis] Could not focus existing window for {target}: {e}")
    return False

def operator_window_titles(target):
    target = normalize_operator_target(target)
    titles = {
        "claude": ["Claude", "claude.ai"],
        "claude ai": ["Claude", "claude.ai"],
        "chatgpt": ["ChatGPT", "chatgpt.com"],
        "chat gpt": ["ChatGPT", "chatgpt.com"],
        "codex": ["Codex", "ChatGPT", "chatgpt.com"],
        "openai codex": ["Codex", "ChatGPT", "chatgpt.com"],
        "gemini": ["Gemini", "gemini.google.com"],
        "youtube": ["YouTube"],
        "you tube": ["YouTube"],
        "google": ["Google"],
        "gmail": ["Gmail"],
        "whatsapp": ["WhatsApp"],
        "whatsapp web": ["WhatsApp"],
        "spotify": ["Spotify"],
        "notepad": ["Notepad"],
        "vs code": ["Visual Studio Code", "Code"],
        "vscode": ["Visual Studio Code", "Code"],
    }
    return titles.get(target, [target])

def browser_tab_search_term(target):
    target = normalize_operator_target(target)
    terms = {
        "claude": "claude",
        "claude ai": "claude",
        "chatgpt": "chatgpt",
        "chat gpt": "chatgpt",
        "codex": "codex",
        "openai codex": "codex",
        "gemini": "gemini",
        "google gemini": "gemini",
        "youtube": "youtube",
        "you tube": "youtube",
        "gmail": "gmail",
        "whatsapp": "whatsapp",
        "whatsapp web": "whatsapp",
    }
    return terms.get(target, "")

def focus_browser_window():
    return (
        focus_existing_window("Google Chrome")
        or focus_existing_window("Microsoft Edge")
        or focus_existing_window("Mozilla Firefox")
    )

def active_window_title():
    try:
        window = pyautogui.getActiveWindow()
        return (window.title or "") if window else ""
    except Exception:
        return ""

def focus_browser_tab(target):
    """Use browser tab search so follow-up commands stay in the same web app tab."""
    term = browser_tab_search_term(target)
    if not term or not focus_browser_window():
        return False
    try:
        pyautogui.hotkey("ctrl", "shift", "a")
        time.sleep(0.5)
        paste_text(term, press_enter=True)
        time.sleep(1.0)
        title = active_window_title().lower()
        title_words = [word.lower() for word in operator_window_titles(target)]
        if term in title or any(word in title for word in title_words):
            print(f"[Jarvis] Focused browser tab for {target}: {active_window_title()}")
            return True
        print(f"[Jarvis] Browser tab search did not confirm {target}. Active: {active_window_title()}")
    except Exception as e:
        print(f"[Jarvis] Browser tab search failed for {target}: {e}")
    return False

def focus_operator_target(target):
    for title in operator_window_titles(target):
        if focus_existing_window(title):
            time.sleep(0.5)
            return True
    if focus_browser_tab(target):
        time.sleep(0.5)
        return True
    return False

def clean_app_name(app_name):
    app_name = (app_name or "").lower().strip()
    app_name = re.sub(r"[?.!,]+$", "", app_name)
    app_name = re.sub(r"^(open|launch|start|run)\s+", "", app_name)
    app_name = re.sub(r"\b(please|app|application|window)\b", " ", app_name)
    app_name = re.sub(r"\b(my|the|a|an)\b", " ", app_name)
    return " ".join(app_name.split())

def start_menu_dirs():
    return [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
    ]

def find_start_menu_shortcut(target):
    target = clean_app_name(target)
    if not target:
        return ""
    target_words = set(target.split())
    best = ("", 0)
    for base in start_menu_dirs():
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for filename in files:
                if not filename.lower().endswith((".lnk", ".url", ".appref-ms")):
                    continue
                name = os.path.splitext(filename)[0].lower()
                clean_name = clean_app_name(name)
                score = 0
                if clean_name == target:
                    score = 100
                elif target in clean_name:
                    score = 80
                else:
                    words = set(clean_name.split())
                    overlap = len(target_words & words)
                    if overlap:
                        score = overlap * 20
                if score > best[1]:
                    best = (os.path.join(root, filename), score)
    return best[0] if best[1] >= 20 else ""

def browser_commands():
    return {
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "microsoft edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
        "mozilla firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    }

def site_urls():
    return {
        "youtube": "https://www.youtube.com",
        "you tube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "instagram": "https://www.instagram.com",
        "whatsapp": "https://web.whatsapp.com",
        "whatsapp web": "https://web.whatsapp.com",
        "telegram": "https://web.telegram.org",
        "telegram web": "https://web.telegram.org",
        "facebook": "https://www.facebook.com",
        "x": "https://x.com",
        "twitter": "https://x.com",
        "github": "https://github.com",
        "chatgpt": "https://chatgpt.com",
        "claude": "https://claude.ai",
        "codex": "https://chatgpt.com/codex",
        "netflix": "https://www.netflix.com",
        "amazon": "https://www.amazon.in",
        "flipkart": "https://www.flipkart.com",
    }

def clean_web_target(target):
    target = (target or "").lower().strip()
    target = re.sub(r"[?.!,]+$", "", target)
    target = re.sub(r"\b(please|website|site|page|browser|tab)\b", " ", target)
    target = re.sub(r"\b(my|the|a|an)\b", " ", target)
    return " ".join(target.split())

def target_to_url(target, search=False):
    target = clean_web_target(target)
    if not target:
        return ""

    urls = site_urls()
    if not search and target in urls:
        return urls[target]

    if re.match(r"^https?://", target):
        return target

    if not search and "." in target and " " not in target:
        return "https://" + target

    return "https://www.google.com/search?q=" + quote_plus(target)

def clean_media_query(query):
    query = (query or "").lower().strip()
    query = re.sub(r"[?.!,]+$", "", query)
    query = re.sub(r"\b(please|the|a|an|that|this)\b", " ", query)
    query = re.sub(r"\b(song|track|music|video)\b$", " ", query)
    return " ".join(query.split())

def youtube_search_url(query):
    return "https://www.youtube.com/results?search_query=" + quote_plus(query)

def resolve_youtube_video_url(query):
    if yt_dlp is None:
        return ""
    try:
        opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = info.get("entries") or []
        if not entries:
            return ""
        entry = entries[0]
        video_id = entry.get("id")
        if video_id:
            return "https://www.youtube.com/watch?v=" + video_id
        return entry.get("webpage_url") or entry.get("url") or ""
    except Exception as e:
        print(f"[Jarvis] Could not resolve YouTube video for {query}: {e}")
        return ""

def spotify_search_uri(query):
    return "spotify:search:" + quote_plus(query)

def spotify_search_url(query):
    return "https://open.spotify.com/search/" + quote_plus(query)

def is_followup_video_command(command_text):
    text = (command_text or "").lower().strip()
    return bool(re.search(r"\b(open|play)\b.*\b(that|this)\b.*\bvideo\b", text))

def parse_media_command(command_text):
    """Parse YouTube/Spotify media commands before generic open/search handling."""
    text = (command_text or "").lower().strip()
    text = re.sub(r"[?.!,]+$", "", text)
    text = re.sub(r"\s+", " ", text)

    if not text:
        return None

    if re.fullmatch(r"(open|launch|start)\s+(spotify|the spotify app)", text):
        return {"service": "spotify", "action": "open_app", "query": "", "url": ""}

    if re.fullmatch(r"(open|launch|start)\s+(youtube|you tube)", text):
        return {"service": "youtube", "action": "open_home", "query": "", "url": site_urls()["youtube"]}

    youtube_patterns = [
        r"\b(?:search|find)\s+(.+?)\s+(?:in|on)\s+(?:youtube|you tube)\b",
        r"\b(?:open|play)\s+(.+?)\s+(?:in|on)\s+(?:youtube|you tube)\b",
        r"\b(?:youtube|you tube)\s+(?:search|find|play|open)\s+(.+)$",
        r"\bplay\s+(.+?)\s+video\b",
    ]
    for index, pattern in enumerate(youtube_patterns):
        match = re.search(pattern, text)
        if match:
            query = clean_media_query(match.group(1))
            if query:
                action = "search" if index == 0 else "play"
                return {
                    "service": "youtube",
                    "action": action,
                    "query": query,
                    "url": youtube_search_url(query),
                }

    spotify_patterns = [
        r"\b(?:play|search|find)\s+(.+?)\s+(?:in|on)\s+spotify\b",
        r"\bspotify\s+(?:play|search|find)\s+(.+)$",
        r"\bplay\s+(.+?)\s+(?:song|track|music)\b",
    ]
    for pattern in spotify_patterns:
        match = re.search(pattern, text)
        if match:
            query = clean_media_query(match.group(1))
            if query:
                return {
                    "service": "spotify",
                    "action": "search",
                    "query": query,
                    "url": spotify_search_url(query),
                    "uri": spotify_search_uri(query),
                }

    return None

def open_media_command(command_text):
    parsed = parse_media_command(command_text)
    if not parsed:
        return None

    service = parsed["service"]
    action = parsed["action"]

    if service == "spotify" and action == "open_app":
        open_app("spotify")
        return parsed

    if service == "youtube" and action == "open_home":
        open_url_in_browser(parsed["url"], "chrome")
        return parsed

    if service == "youtube":
        url = parsed["url"]
        if parsed["action"] == "play":
            url = resolve_youtube_video_url(parsed["query"]) or url
        open_url_in_browser(url, "chrome")
        return parsed

    if service == "spotify":
        try:
            os.startfile(parsed["uri"])
        except Exception:
            open_url_in_browser(parsed["url"], "chrome")
        return parsed

    return parsed

# Universal local operator

def set_clipboard_text(text):
    """Put text on the Windows clipboard for reliable paste automation."""
    text = "" if text is None else str(text)
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception as e:
        print(f"[Jarvis] Clipboard set failed: {e}")
        return False

def paste_text(text, press_enter=False):
    if not set_clipboard_text(text):
        pyautogui.write(text, interval=0.01)
    else:
        pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)
    if press_enter:
        pyautogui.press("enter")

def click_screen_fraction(x_fraction, y_fraction):
    width, height = pyautogui.size()
    pyautogui.click(int(width * x_fraction), int(height * y_fraction))

def click_active_window_fraction(x_fraction, y_fraction):
    try:
        window = pyautogui.getActiveWindow()
        if window and window.width > 200 and window.height > 150:
            if window.isMinimized:
                window.restore()
            window.activate()
            time.sleep(0.2)
            x = window.left + int(window.width * x_fraction)
            y = window.top + int(window.height * y_fraction)
            pyautogui.click(x, y)
            return True
    except Exception as e:
        print(f"[Jarvis] Active-window click failed: {e}")
    click_screen_fraction(x_fraction, y_fraction)
    return False

def maximize_active_window():
    try:
        window = pyautogui.getActiveWindow()
        if window and window.width > 200 and window.height > 150:
            if window.isMinimized:
                window.restore()
            window.activate()
            time.sleep(0.2)
            if not getattr(window, "isMaximized", False):
                window.maximize()
                time.sleep(0.5)
            return True
    except Exception as e:
        print(f"[Jarvis] Could not maximize active window: {e}")
    return False

def screenshot_bytes():
    screenshot = pyautogui.screenshot()
    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    buf.seek(0)
    return buf

def normalize_operator_target(target):
    target = (target or "").lower().strip()
    target = re.sub(r"[?.!,]+$", "", target)
    target = re.sub(r"\b(the|my|app|website|site|browser)\b", " ", target)
    target = " ".join(target.split())
    aliases = {
        "cloud": "claude",
        "cloud ai": "claude",
        "claud": "claude",
        "clawed": "claude",
        "clode": "claude",
        "chat gpt": "chatgpt",
        "chat gpt ai": "chatgpt",
        "open ai codex": "codex",
        "openai codex": "codex",
        "code x": "codex",
        "kodex": "codex",
    }
    return aliases.get(target, target)

def operator_site_url(target):
    target = normalize_operator_target(target)
    urls = site_urls()
    extra = {
        "claude ai": "https://claude.ai",
        "claude.ai": "https://claude.ai",
        "chat gpt": "https://chatgpt.com",
        "codex": "https://chatgpt.com/codex",
        "openai codex": "https://chatgpt.com/codex",
        "gemini": "https://gemini.google.com",
        "google gemini": "https://gemini.google.com",
        "spotify web": "https://open.spotify.com",
    }
    urls.update(extra)
    return urls.get(target, "")

def parse_gmail_operator(text):
    pattern = (
        r"\bopen\s+gmail\s+and\s+compose\s+email\s+to\s+(.+?)"
        r"(?:\s+subject\s*:\s*|\s+subject\s+)(.+?)"
        r"(?:\s+body\s*:\s*|\s+body\s+)(.+)$"
    )
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return {
        "type": "gmail_compose",
        "target": "gmail",
        "to": match.group(1).strip(),
        "subject": match.group(2).strip(),
        "body": match.group(3).strip(),
    }

def parse_operator_command(command_text, context_target=None):
    raw = (command_text or "").strip()
    if not raw:
        return None
    remembered_target = normalize_operator_target(context_target or load_operator_state().get("last_target", ""))

    gmail = parse_gmail_operator(raw)
    if gmail:
        return gmail

    patterns = [
        (
            "generic_type",
            r"\bopen\s+(.+?)\s+(?:and\s+)?(?:in|inside|on)\s+(?:the\s+)?(?:.+?)\s+(?:type|send|write)\s*:?\s*(.+)$",
            ("target", "text"),
        ),
        (
            "generic_search",
            r"\bopen\s+(.+?)\s+(?:and\s+)?(?:in|inside|on)\s+(?:the\s+)?(?:.+?)\s+(?:search|find)\s*:?\s*(.+)$",
            ("target", "query"),
        ),
        (
            "generic_type_existing",
            r"\b(?:in|inside|on)\s+(.+?)\s+(?:type|send|write)\s*:?\s*(.+)$",
            ("target", "text"),
        ),
        (
            "generic_search_existing",
            r"\b(?:in|inside|on)\s+(.+?)\s+(?:search|find)\s*:?\s*(.+)$",
            ("target", "query"),
        ),
        (
            "generic_type_followup",
            r"^(?:type|send|write)\s*:?\s*(.+)$",
            ("text",),
        ),
        (
            "generic_search_followup",
            r"^(?:search|find)\s*:?\s*(.+)$",
            ("query",),
        ),
        (
            "whatsapp_message",
            r"\bopen\s+whatsapp(?:\s+web)?\s+and\s+send\s+message\s+to\s+(.+?)\s*:\s*(.+)$",
            ("contact", "message"),
        ),
        (
            "youtube_play",
            r"\bopen\s+(?:youtube|you tube)\s+and\s+play\s+(.+)$",
            ("query",),
        ),
        (
            "google_search",
            r"\bopen\s+google\s+and\s+search\s*:?\s*(.+)$",
            ("query",),
        ),
        (
            "vscode_folder",
            r"\bopen\s+(?:vs\s+code|vscode|visual\s+studio\s+code)\s+and\s+open\s+folder\s+(.+)$",
            ("folder",),
        ),
        (
            "spotify_play",
            r"\bopen\s+spotify(?:\s+(?:on|in)\s+chrome)?\s+and\s+play\s+(.+)$",
            ("query",),
        ),
        (
            "generic_type",
            r"\bopen\s+(.+?)\s+(?:and\s+)?type\s*:?\s*(.+)$",
            ("target", "text"),
        ),
        (
            "generic_search",
            r"\bopen\s+(.+?)\s+(?:and\s+)?search\s*:?\s*(.+)$",
            ("target", "query"),
        ),
    ]

    for command_type, pattern, fields in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        parsed = {"type": command_type}
        for index, field in enumerate(fields, start=1):
            parsed[field] = match.group(index).strip()
        if parsed.get("target"):
            parsed["target"] = normalize_operator_target(parsed["target"])
        if command_type.endswith("_followup"):
            if not remembered_target:
                return None
            parsed["target"] = remembered_target
            parsed["existing"] = True
        if command_type.endswith("_existing"):
            parsed["existing"] = True
        if "target" not in parsed:
            if command_type.startswith("youtube"):
                parsed["target"] = "youtube"
            elif command_type.startswith("google"):
                parsed["target"] = "google"
            elif command_type.startswith("spotify"):
                parsed["target"] = "spotify"
            elif command_type.startswith("whatsapp"):
                parsed["target"] = "whatsapp"
        return parsed

    return None

def open_operator_target(target):
    target_clean = normalize_operator_target(target)
    url = operator_site_url(target_clean)
    if url:
        open_url_in_browser(url, "chrome")
        return "web"
    open_app(target_clean)
    return "app"

def focus_likely_input(target):
    target = normalize_operator_target(target)
    if target in {"claude", "chatgpt", "codex", "gemini", "google gemini"}:
        maximize_active_window()
        pyautogui.press("esc")
        time.sleep(0.2)
        click_active_window_fraction(0.50, 0.92)
        time.sleep(0.15)
        pyautogui.click()
        return
    if target in {"youtube", "you tube", "google"}:
        pyautogui.hotkey("ctrl", "l")
        return
    if target in {"notepad"}:
        click_active_window_fraction(0.45, 0.45)
        return
    click_active_window_fraction(0.50, 0.55)

def type_into_target(target, text, submit=False):
    target = normalize_operator_target(target)
    ai_targets = {"claude", "chatgpt", "codex", "gemini", "google gemini"}
    if target in ai_targets:
        focus_likely_input(target)
        time.sleep(0.25)
        # AI chat boxes move around between layouts. Click a few safe prompt-zone
        # positions, then paste once after the final click.
        for y_fraction in (0.92, 0.86):
            click_active_window_fraction(0.50, y_fraction)
            time.sleep(0.15)
        paste_text(text, press_enter=False)
    else:
        focus_likely_input(target)
        time.sleep(0.25)
        paste_text(text, press_enter=False)
    time.sleep(0.25)
    if submit:
        pyautogui.press("enter")

def execute_operator_command(command_text, telegram_screenshot=False, context_target=None):
    parsed = parse_operator_command(command_text, context_target=context_target)
    if not parsed:
        return None

    command_type = parsed["type"]
    response = "Done, sir."
    wait_after = 2.0

    if command_type == "gmail_compose":
        to = parsed["to"]
        subject = parsed["subject"]
        body = parsed["body"]
        url = (
            "https://mail.google.com/mail/?view=cm&fs=1"
            f"&to={quote(to)}&su={quote(subject)}&body={quote(body)}"
        )
        open_url_in_browser(url, "chrome")
        response = f"Opening Gmail compose to {to}, sir."
        wait_after = 5.0

    elif command_type == "whatsapp_message":
        contact = parsed["contact"]
        message = parsed["message"]
        open_url_in_browser("https://web.whatsapp.com", "chrome")
        time.sleep(8)
        click_screen_fraction(0.16, 0.16)
        paste_text(contact, press_enter=True)
        time.sleep(2)
        paste_text(message, press_enter=True)
        response = f"Opened WhatsApp and tried sending the message to {contact}, sir."
        wait_after = 2.0

    elif command_type == "youtube_play":
        query = parsed["query"]
        url = resolve_youtube_video_url(query) or youtube_search_url(query)
        open_url_in_browser(url, "chrome")
        response = f"Playing YouTube result for {query}, sir."
        wait_after = 4.0

    elif command_type == "google_search":
        query = parsed["query"]
        open_url_in_browser("https://www.google.com/search?q=" + quote_plus(query), "chrome")
        response = f"Searching Google for {query}, sir."
        wait_after = 3.0

    elif command_type == "vscode_folder":
        folder = os.path.expandvars(parsed["folder"].strip('"'))
        code_path = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")
        try:
            if os.path.exists(code_path):
                subprocess.Popen([code_path, folder])
            else:
                subprocess.Popen(["cmd", "/c", "start", "", "code", folder])
            response = f"Opening folder {folder} in VS Code, sir."
        except Exception as e:
            print(f"[Jarvis] VS Code folder open failed: {e}")
            open_app("vs code")
            response = "I opened VS Code, but could not pass the folder path, sir."
        wait_after = 3.0

    elif command_type == "spotify_play":
        query = parsed["query"]
        use_chrome = "chrome" in command_text.lower()
        if use_chrome:
            open_url_in_browser(spotify_search_url(query), "chrome")
        else:
            try:
                os.startfile(spotify_search_uri(query))
            except Exception:
                open_url_in_browser(spotify_search_url(query), "chrome")
        response = f"Opening Spotify search for {query}, sir."
        wait_after = 4.0

    elif command_type in ("generic_search", "generic_search_existing", "generic_search_followup"):
        target = parsed["target"]
        query = parsed["query"]
        target_clean = normalize_operator_target(target)
        search_url = ""
        if target_clean in {"youtube", "you tube"}:
            search_url = youtube_search_url(query)
        elif target_clean in {"google"}:
            search_url = "https://www.google.com/search?q=" + quote_plus(query)
        if search_url:
            if parsed.get("existing"):
                if focus_operator_target(target):
                    pyautogui.hotkey("ctrl", "l")
                    paste_text(search_url, press_enter=True)
                else:
                    response = f"I could not find {target} already open, sir."
                    wait_after = 0.5
            else:
                open_url_in_browser(search_url, "chrome")
        else:
            if parsed.get("existing"):
                if not focus_operator_target(target):
                    response = f"I could not find {target} already open, sir."
                    wait_after = 0.5
                else:
                    time.sleep(0.8)
                    type_into_target(target, query, submit=True)
            else:
                open_operator_target(target)
                time.sleep(4)
                type_into_target(target, query, submit=True)
        if "could not find" not in response.lower():
            response = f"Searching {target} for {query}, sir."
            wait_after = 4.0

    elif command_type in ("generic_type", "generic_type_existing", "generic_type_followup"):
        target = parsed["target"]
        text = parsed["text"]
        target_clean = normalize_operator_target(target)
        if parsed.get("existing"):
            if not focus_operator_target(target_clean):
                response = f"I could not find {target} already open, sir."
                wait_after = 0.5
            else:
                time.sleep(0.8)
                submit_targets = {"claude", "chatgpt", "codex", "gemini", "google gemini"}
                type_into_target(target_clean, text, submit=target_clean in submit_targets)
                response = f"Typed your text in {target}, sir."
                wait_after = 8.0 if target_clean in submit_targets else 2.0
        else:
            open_operator_target(target)
            time.sleep(7 if operator_site_url(target_clean) else 2)
            focus_operator_target(target_clean)
            submit_targets = {"claude", "chatgpt", "codex", "gemini", "google gemini"}
            type_into_target(target_clean, text, submit=target_clean in submit_targets)
            response = f"Opened {target} and typed your text, sir."
            wait_after = 8.0 if target_clean in submit_targets else 2.0

    time.sleep(wait_after)
    screenshot = screenshot_bytes()
    if telegram_screenshot:
        send_screenshot_to_telegram()

    if parsed.get("target"):
        save_operator_state(parsed.get("target"), command_type)

    return {
        "success": True,
        "response": response,
        "parsed": parsed,
        "target": normalize_operator_target(parsed.get("target", "")),
        "screenshot": screenshot,
    }

def parse_browser_command(command_text, default_browser="chrome"):
    """Return browser + URL for commands like 'open chrome and open youtube'."""
    text = (command_text or "").lower().strip()
    text = re.sub(r"[?.!,]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    if not any(word in text for word in ["open", "launch", "start", "search", "google"]):
        return None

    browsers = browser_commands()
    browser = default_browser
    for name in sorted(browsers, key=len, reverse=True):
        if re.search(rf"\b{name}\b", text):
            browser = name
            break

    # Keep plain app-only commands as app commands.
    plain_app = re.fullmatch(r"(open|launch|start|run)\s+(?:the\s+|my\s+)?(chrome|google chrome|edge|microsoft edge|firefox|mozilla firefox)", text)
    if plain_app:
        return None

    target = ""
    search = False

    patterns = [
        rf"\b(?:open|launch|start)\s+(.+?)\s+\bin\s+(?:the\s+)?({ '|'.join(re.escape(b) for b in browsers) })\b",
        rf"\b(?:open|launch|start)\s+(?:{ '|'.join(re.escape(b) for b in browsers) })\b\s*(?:and\s*)?(?:inside\s+it\s*)?(?:open|launch|start)\s+(.+)$",
        rf"\b(?:open|launch|start)\s+(?:{ '|'.join(re.escape(b) for b in browsers) })\b\s*(?:and\s*)?(?:search|google)\s+(.+)$",
        r"\b(?:open|launch|start)\s+(.+)$",
        r"\b(?:search|google)\s+(.+)$",
    ]

    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text)
        if not match:
            continue
        if index == 0:
            target = match.group(1)
        else:
            target = match.group(1)
        search = index in (2, 4)
        break

    if not target:
        return None

    target = clean_web_target(target)
    target = re.sub(r"^(open|launch|start|run|search|google)\s+", "", target).strip()
    target = re.sub(r"^(inside it\s+)?(open|launch|start)\s+", "", target).strip()

    if target in browsers:
        return None

    known_site = target in site_urls()
    looks_like_url = bool(re.match(r"^https?://", target)) or ("." in target and " " not in target)
    browser_named = browser != default_browser
    if not (search or known_site or looks_like_url or browser_named):
        return None

    url = target_to_url(target, search=search)
    if not url:
        return None

    return {"browser": browser, "target": target, "url": url, "search": search}

def open_url_in_browser(url, browser="chrome"):
    browser = clean_web_target(browser) or "chrome"
    command = browser_commands().get(browser)

    try:
        if command and os.path.exists(command):
            subprocess.Popen([command, url])
        elif browser in ("edge", "microsoft edge"):
            subprocess.Popen(["cmd", "/c", "start", "", "msedge", url])
        elif browser in ("firefox", "mozilla firefox"):
            subprocess.Popen(["cmd", "/c", "start", "", "firefox", url])
        elif browser in ("chrome", "google chrome"):
            subprocess.Popen(["cmd", "/c", "start", "", "chrome", url])
        else:
            webbrowser.open(url)
        print(f"[Jarvis] Opened {url} in {browser}.")
        return True
    except Exception as e:
        print(f"[Jarvis] Browser open failed, using default browser: {e}")
        webbrowser.open(url)
        return True

def open_browser_command(command_text, default_browser="chrome"):
    parsed = parse_browser_command(command_text, default_browser=default_browser)
    if not parsed:
        return False
    return open_url_in_browser(parsed["url"], parsed["browser"])

def open_app(app_name):
    """Open any requested Windows app using known paths first, then Start search."""
    target = clean_app_name(app_name)
    if not target:
        print("[Jarvis] No app name provided.")
        return False

    if target in ("workspace", "work space"):
        open_workspace()
        return True

    if "telegram" in target:
        return open_telegram()

    if focus_existing_window(target):
        return True

    aliases = {
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "microsoft edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "vs code": os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        "vscode": os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        "visual studio code": os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        "spotify": os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "settings": "ms-settings:",
        "whatsapp": "whatsapp:",
        "phone link": "ms-phone:",
        "camera": "microsoft.windows.camera:",
        "paint": "mspaint.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "terminal": "wt.exe",
        "powershell": "powershell.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
        "task manager": "taskmgr.exe",
        "control panel": "control.exe",
        "word": "winword.exe",
        "microsoft word": "winword.exe",
        "excel": "excel.exe",
        "microsoft excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "microsoft powerpoint": "powerpnt.exe",
        "outlook": "outlook.exe",
        "microsoft outlook": "outlook.exe",
        "teams": "ms-teams:",
        "microsoft teams": "ms-teams:",
    }

    command = aliases.get(target, target)

    try:
        if command.startswith(("http://", "https://")):
            webbrowser.open(command)
        elif command.endswith(":"):
            os.startfile(command)
        elif os.path.exists(command):
            subprocess.Popen([command])
        else:
            subprocess.Popen(command, shell=True)
        print(f"[Jarvis] Opened {target}.")
        return True
    except Exception as direct_error:
        print(f"[Jarvis] Direct open failed for {target}: {direct_error}")

    shortcut = find_start_menu_shortcut(target)
    if shortcut:
        try:
            print(f"[Jarvis] Opening Start Menu shortcut: {shortcut}")
            os.startfile(shortcut)
            return True
        except Exception as shortcut_error:
            print(f"[Jarvis] Shortcut open failed for {target}: {shortcut_error}")

    try:
        print(f"[Jarvis] Trying Windows shell open for {target}...")
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        return True
    except Exception as shell_error:
        print(f"[Jarvis] Shell open failed for {target}: {shell_error}")

    try:
        print(f"[Jarvis] Searching Start menu for {target}...")
        pyautogui.hotkey("win")
        time.sleep(0.5)
        pyautogui.write(target, interval=0.02)
        time.sleep(0.7)
        pyautogui.press("enter")
        print(f"[Jarvis] Tried opening {target} from Start search.")
        return True
    except Exception as search_error:
        print(f"[Jarvis] Could not open {target}: {search_error}")
        return False

# ─── Action Dispatcher ────────────────────────────────────────────────────────

def execute_action(action, target=None):
    """Execute the action returned by AI brain"""
    if isinstance(action, dict):
        target = action.get("target") or action.get("app") or action.get("name")
        action = action.get("action")

    actions = {
        "wake_screen": wake_screen,
        "unlock_screen": unlock_screen,
        "open_workspace": open_workspace,
        "sleep_screen": sleep_screen,
        "screenshot": take_screenshot,
        "take_screenshot": take_screenshot,
        "send_screenshot_telegram": send_screenshot_to_telegram,
        "send_screenshot_to_telegram": send_screenshot_to_telegram,
        "telegram_screenshot": send_screenshot_to_telegram,
        "open_telegram": open_telegram,
        "open_app": lambda: open_app(target),
        "open_window": lambda: open_app(target),
        "focus_window": lambda: open_app(target),
        "close_app": lambda: close_target(target),
        "close_window": lambda: close_target(target),
        "close_tab": lambda: close_target(target),
        "close_all_apps": close_all_tabs_and_apps,
        "close_all_tabs": close_all_tabs_and_apps,
        "shutdown_pc": shutdown_pc,
        "restart_pc": restart_pc,
        "cancel_shutdown": cancel_shutdown,
    }

    func = actions.get(action)
    if func:
        result = func()
        return True if result is None else bool(result)
    else:
        print(f"[Jarvis] Unknown action: {action}")
        return False
