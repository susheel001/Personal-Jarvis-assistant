# 🤖 JARVIS — Personal AI Assistant (Windows)

Your personal voice-controlled AI assistant with multi-bot support. Say **"Wakeup Jarvis"** and give commands.

---

## ✅ What Jarvis Can Do

| You Say | Jarvis Does |
|---|---|
| "Wakeup Jarvis, wake up the screen" | Wakes your screen from sleep |
| "Wakeup Jarvis, open the password" | Types your Windows password & logs in |
| "Wakeup Jarvis, open my workspace" | Opens VS Code, Chrome, Spotify, Claude.ai |
| "Wakeup Jarvis, lock the screen" | Locks your Windows screen |

---

## 🤖 Features

- **Voice Control** — Speech recognition with Vosk (local) + Whisper (accurate)
- **AI Brain** — Powered by Groq (online) or Ollama (offline)
- **Text-to-Speech** — Jarvis responds with voice via pyttsx3
- **Telegram Bot** — Remote control Jarvis from anywhere via Telegram
- **WhatsApp Bot** — Cloud API webhook integration for WhatsApp messages
- **Task Manager** — Schedule reminders and automate tasks with custom timing
- **PC Monitor** — Real-time CPU, RAM, battery monitoring & activity alerts
- **System Control** — Wake/lock screen, password autofill, app launcher

---

## 🧠 How It Works

```
Your Voice → Vosk/Whisper (hear) → Groq or Ollama (understand) → Python (act)
```

- **Online** → Uses **Groq** (fast, smart)
- **Offline** → Uses **Ollama** (local, private)
- Auto-switches automatically!

---

## 📦 Step 1 — Install Python

Download Python 3.10 or 3.11 from https://python.org  
✅ Check "Add Python to PATH" during install

---

## 📦 Step 2 — Install Dependencies

Open Command Prompt in the jarvis folder and run:

```bash
pip install -r requirements.txt
```

If PyAudio fails, install it manually:
```bash
pip install pipwin
pipwin install pyaudio
```

---

## 📦 Step 3 — Install Ollama (Offline AI)

1. Download from https://ollama.com
2. Install it
3. Open Command Prompt and run:
```bash
ollama pull llama3:8b
```
This downloads the ~4.7GB offline AI model (one time only).

---

## 🔑 Step 4 — Get Groq API Key (Free)

1. Go to https://console.groq.com
2. Sign up (free)
3. Go to API Keys → Create API Key
4. Copy your key

---

## ⚙️ Step 5 — First Time Setup

Run this once to save your Groq key and Windows password:

```bash
python jarvis.py --setup
```

Your password is stored **securely** in Windows Credential Manager (not in plain text).

---

## 🚀 Step 6 — Start Jarvis!

```bash
python jarvis.py
```

Then say: **"Wakeup Jarvis"** → wait for response → give your command!

---

## 🤖 Bot Features

### Telegram Bot
Remote control Jarvis from Telegram messages anywhere:
```bash
python telegram_bot.py
```
Send commands via Telegram and receive responses instantly.

### WhatsApp Bot
Cloud API webhook for WhatsApp integration:
- Enabled via `config.json`
- Responds to WhatsApp messages
- Auto-reply support
- Telegram logging integration

### Task Manager
Schedule reminders and tasks with custom timing:
- Edit `tasks.json` to add tasks
- Set repeat (daily, once) and remind times
- Jarvis will notify and execute tasks

### PC Monitor
Real-time system monitoring:
```bash
python monitor.py
```
- CPU, RAM, battery stats
- Activity detection
- Screenshot capture on activity
- Configurable cooldown alerts

---

## ⚙️ Configuration

### Wake Phrases
Edit `config.json` to customize wake phrases:
```json
"wake_phrases": [
  "wakeup jarvis",
  "wakeup daddy's home"
]
```

### Voice Settings
- **Wake Engine:** Vosk (local speech recognition)
- **Command Engine:** Whisper (high-accuracy speech-to-text)
- **Whisper Model:** Base (balanced speed/accuracy)
- **Groq Model:** llama-3.3-70b-versatile (latest)
- **Min Record:** 0.8 seconds
- **Max Command:** 8 seconds
- **Silence Duration:** 1.2 seconds

### Workspace Apps
Edit the `workspace` array in `config.json` to customize which apps open:
```json
"workspace": [
  {
    "name": "VS Code",
    "type": "app",
    "path": "C:\\Users\\%USERNAME%\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"
  },
  {
    "name": "Chrome",
    "type": "app",
    "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  }
]
```

### Monitor Settings
Enable/disable PC monitoring in `config.json`:
```json
"monitor": {
  "enabled": true,
  "send_screenshot_on_activity": true,
  "activity_alert_cooldown_seconds": 300,
  "check_interval_seconds": 5
}
```

### WhatsApp Settings
Configure Cloud API webhook:
```json
"whatsapp": {
  "enabled": true,
  "host": "0.0.0.0",
  "port": 5005,
  "graph_api_version": "v25.0",
  "autoreply_enabled": true,
  "telegram_logs_enabled": true
}
```

---

## 📦 Dependencies

All required packages are listed in `requirements.txt`:
- **Voice:** openai-whisper, pyaudio, vosk
- **AI:** groq, ollama, httpx, requests
- **System:** pyautogui, keyring, psutil
- **Bots:** python-telegram-bot (20.7), Flask
- **TTS:** pyttsx3
- **Utils:** numpy, Pillow, yt-dlp

---

## 🔧 Quick Start

### 1. Install Python
Download Python 3.10+ from https://python.org and add to PATH

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Download Vosk Model (Auto)
Model is pre-configured at: `models/vosk-model-small-en-us-0.15/`

### 4. Get Groq API Key (Free)
1. Visit https://console.groq.com
2. Sign up
3. Create API Key
4. Save it during setup

### 5. Setup (One-time)
```bash
python jarvis.py --setup
```
Saves Groq key and Windows password securely.

### 6. Run Jarvis
```bash
python jarvis.py
```
Say "Wakeup Jarvis" to activate!

---

## ❓ Troubleshooting

| Problem | Fix |
|---|---|
| PyAudio install fails | `pip install pipwin` then `pipwin install pyaudio` |
| Whisper not found | `pip install openai-whisper` |
| Ollama not responding | Make sure Ollama app is running |
| Password not working | Re-run `python jarvis.py --setup` |
| Wrong apps opening | Edit paths in `config.json` |
| Vosk not recognizing wake phrase | Check microphone device in `config.json` or use keyword filters |
| WhatsApp bot not responding | Verify webhook URL and API credentials in `config.json` |
| Task reminders not working | Check `tasks.json` format and remind_time values |

---

## 📁 File Structure

```
Jarvis/
├── jarvis.py              ← Main entry point (run this)
├── voice.py               ← Microphone + Vosk + Whisper
├── ai_brain.py            ← Groq + Ollama AI integration
├── actions.py             ← System control (wake, unlock, apps)
├── speak.py               ← Text-to-speech (pyttsx3)
├── task_manager.py        ← Task scheduling & reminders
├── monitor.py             ← PC monitoring (CPU, RAM, battery, screenshots)
├── telegram_bot.py        ← Telegram remote control bot
├── whatsapp_bot.py        ← WhatsApp Cloud API webhook handler
├── config.json            ← Voice, AI, monitor, WhatsApp, workspace settings
├── tasks.json             ← Scheduled tasks and reminders
├── requirements.txt       ← Python dependencies
├── jarvis.bat             ← Windows batch launcher
├── jarvis_ui.py           ← UI for Jarvis
├── jarvis_ui.bat          ← UI launcher
├── models/                ← Vosk speech model
│   └── vosk-model-small-en-us-0.15/
└── screenshots/           ← Monitor activity screenshots
```
