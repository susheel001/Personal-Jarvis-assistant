"""
whatsapp_bot.py - WhatsApp Cloud API operator for Jarvis.

Run inside Jarvis and expose this local server with ngrok:
    ngrok http 5005

Meta webhook callback URL:
    https://<your-ngrok-domain>/webhook/whatsapp
"""

import datetime
import hashlib
import hmac
import json
import os
import sqlite3
import threading

import httpx
from flask import Flask, abort, jsonify, request


BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")
DB_PATH = os.path.join(BASE_DIR, "whatsapp_messages.db")

with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = json.load(f)

WHATSAPP_CONFIG = CONFIG.get("whatsapp", {})
GRAPH_API_VERSION = WHATSAPP_CONFIG.get("graph_api_version", "v25.0")
TELEGRAM_LOGS_ENABLED = WHATSAPP_CONFIG.get("telegram_logs_enabled", True)

app = Flask(__name__)
_db_lock = threading.Lock()


def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def normalize_api_key(api_key):
    api_key = (api_key or "").strip().strip('"').strip("'")
    if api_key.lower().startswith("bearer "):
        api_key = api_key.split(" ", 1)[1].strip()
    return api_key


def env_value(name, default=""):
    return load_env().get(name, default)


def bool_value(value, default=False):
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def autoreply_enabled():
    env = load_env()
    return bool_value(
        env.get("WHATSAPP_AUTOREPLY_ENABLED"),
        WHATSAPP_CONFIG.get("autoreply_enabled", True)
    )


def init_db():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                sender TEXT NOT NULL,
                sender_name TEXT,
                message_id TEXT,
                incoming_text TEXT,
                decision TEXT,
                reply_text TEXT,
                reason TEXT,
                status TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO whatsapp_state(key, value) VALUES('paused', 'false')"
        )
        conn.commit()
        conn.close()


def get_state(key, default=""):
    init_db()
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT value FROM whatsapp_state WHERE key = ?",
            (key,)
        ).fetchone()
        conn.close()
    return row[0] if row else default


def set_state(key, value):
    init_db()
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO whatsapp_state(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value)
        )
        conn.commit()
        conn.close()


def is_paused():
    return get_state("paused", "false") == "true"


def pause_autoreply():
    set_state("paused", "true")


def resume_autoreply():
    set_state("paused", "false")


def log_message(sender, sender_name, message_id, incoming_text, decision, reply_text, reason, status, error=""):
    init_db()
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO whatsapp_messages(
                created_at, sender, sender_name, message_id, incoming_text,
                decision, reply_text, reason, status, error
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.datetime.now().isoformat(timespec="seconds"),
                sender,
                sender_name,
                message_id,
                incoming_text,
                decision,
                reply_text,
                reason,
                status,
                error
            )
        )
        conn.commit()
        conn.close()


def get_recent_messages(limit=5):
    init_db()
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT created_at, sender, sender_name, incoming_text, decision, reply_text, status, error
            FROM whatsapp_messages
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        conn.close()
    return [dict(row) for row in rows]


def get_whatsapp_status():
    env = load_env()
    return {
        "configured": bool(env.get("WHATSAPP_ACCESS_TOKEN") and env.get("WHATSAPP_PHONE_NUMBER_ID") and env.get("WHATSAPP_VERIFY_TOKEN")),
        "paused": is_paused(),
        "autoreply_enabled": autoreply_enabled(),
        "telegram_logs_enabled": TELEGRAM_LOGS_ENABLED,
        "db_path": DB_PATH,
        "webhook_path": "/webhook/whatsapp",
        "port": WHATSAPP_CONFIG.get("port", 5005),
    }


def verify_signature(raw_body):
    app_secret = env_value("WHATSAPP_APP_SECRET")
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not app_secret:
        return True
    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    received = signature.split("=", 1)[1]
    return hmac.compare_digest(expected, received)


def send_telegram_log(message):
    if not TELEGRAM_LOGS_ENABLED:
        return

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_USER_ID", "")
    if not token or not chat_id:
        return

    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": message
            },
            timeout=15
        )
    except Exception as e:
        print(f"[WhatsApp] Telegram log failed: {e}")


def send_whatsapp_message(to_number, text):
    env = load_env()
    token = normalize_api_key(env.get("WHATSAPP_ACCESS_TOKEN", ""))
    phone_number_id = env.get("WHATSAPP_PHONE_NUMBER_ID", "")

    if not token or not phone_number_id:
        return False, "WhatsApp token or phone number ID is missing."

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text
        }
    }

    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=20
        )
        if response.status_code >= 400:
            return False, response.text[:500]
        return True, ""
    except Exception as e:
        return False, str(e)


def classify_message(sender, sender_name, text):
    env = load_env()
    groq_key = normalize_api_key(env.get("GROQ_API_KEY", ""))
    groq_model = CONFIG.get("groq_model", "llama-3.3-70b-versatile")

    if not groq_key:
        return {
            "decision": "needs-human",
            "reply": "I have received your message. I will get back to you shortly.",
            "reason": "Groq API key is missing."
        }

    system = """
You are Jarvis handling WhatsApp messages for Susheel.
Return ONLY valid JSON with:
{"decision":"auto-reply|urgent-alert|ignore|needs-human","reply":"message to send or empty","reason":"short reason"}

Rules:
- auto-reply: normal friendly messages, scheduling, simple questions.
- urgent-alert: emergencies, money/payment issues, family/health/work urgency.
- needs-human: sensitive, emotional, legal, private, unclear, or risky messages.
- ignore: spam, OTP, ads, obvious automated/promotional messages.
- Replies must be concise, natural, and polite.
- Never claim Susheel personally did something unless the message says so.
- For urgent-alert or needs-human, use a short holding reply saying Susheel has been notified.
"""
    user = f"Sender number: {sender}\nSender name: {sender_name or 'Unknown'}\nMessage: {text}"

    try:
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": groq_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "temperature": 0.2,
                "max_tokens": 250
            },
            timeout=20
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        content = content.strip().strip("```json").strip("```").strip()
        data = json.loads(content)
        decision = data.get("decision", "needs-human")
        if decision not in {"auto-reply", "urgent-alert", "ignore", "needs-human"}:
            decision = "needs-human"
        return {
            "decision": decision,
            "reply": data.get("reply", "").strip(),
            "reason": data.get("reason", "").strip()
        }
    except Exception as e:
        print(f"[WhatsApp] Classifier error: {e}")
        return {
            "decision": "needs-human",
            "reply": "I have received your message. I will get back to you shortly.",
            "reason": f"Classifier failed: {e}"
        }


def process_incoming_message(sender, sender_name, message_id, text):
    if is_paused() or not autoreply_enabled():
        decision = "needs-human"
        reply = ""
        reason = "WhatsApp auto-reply is paused or disabled."
        status = "paused"
        error = ""
        send_telegram_log(
            f"WhatsApp message while paused\n"
            f"From: {sender_name or sender}\n"
            f"Text: {text}"
        )
        log_message(sender, sender_name, message_id, text, decision, reply, reason, status, error)
        return

    result = classify_message(sender, sender_name, text)
    decision = result["decision"]
    reply = result["reply"]
    reason = result["reason"]
    status = "processed"
    error = ""

    if decision != "ignore" and reply:
        sent, error = send_whatsapp_message(sender, reply)
        status = "sent" if sent else "send_failed"
    elif decision == "ignore":
        status = "ignored"

    if decision in {"urgent-alert", "needs-human"} or status == "send_failed":
        send_telegram_log(
            f"WhatsApp {decision}\n"
            f"From: {sender_name or sender}\n"
            f"Text: {text}\n"
            f"Reply: {reply or '(none)'}\n"
            f"Status: {status}\n"
            f"Reason: {reason}"
        )
    else:
        send_telegram_log(
            f"WhatsApp auto-replied\n"
            f"From: {sender_name or sender}\n"
            f"Text: {text}\n"
            f"Reply: {reply}"
        )

    log_message(sender, sender_name, message_id, text, decision, reply, reason, status, error)


def extract_messages(payload):
    extracted = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {
                contact.get("wa_id"): contact.get("profile", {}).get("name", "")
                for contact in value.get("contacts", [])
            }
            for message in value.get("messages", []):
                sender = message.get("from", "")
                message_id = message.get("id", "")
                message_type = message.get("type", "")
                text = ""
                if message_type == "text":
                    text = message.get("text", {}).get("body", "")
                if sender and text:
                    extracted.append({
                        "sender": sender,
                        "sender_name": contacts.get(sender, ""),
                        "message_id": message_id,
                        "text": text
                    })
    return extracted


@app.get("/webhook/whatsapp")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    expected = env_value("WHATSAPP_VERIFY_TOKEN")
    if mode == "subscribe" and token and token == expected:
        print("[WhatsApp] Webhook verified.")
        return challenge or "", 200
    return "Forbidden", 403


@app.post("/webhook/whatsapp")
def receive_webhook():
    raw_body = request.get_data()
    if not verify_signature(raw_body):
        abort(403)

    payload = request.get_json(silent=True) or {}
    messages = extract_messages(payload)

    for item in messages:
        process_incoming_message(
            sender=item["sender"],
            sender_name=item["sender_name"],
            message_id=item["message_id"],
            text=item["text"]
        )

    return jsonify({"ok": True, "messages": len(messages)})


@app.get("/health/whatsapp")
def health():
    return jsonify(get_whatsapp_status())


def start_whatsapp_bot(host="0.0.0.0", port=5005):
    init_db()
    status = get_whatsapp_status()
    if not status["configured"]:
        print("[WhatsApp] Missing WhatsApp env values; webhook server not started.")
        print("[WhatsApp] Required: WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN")
        return

    print(f"[WhatsApp] Starting webhook server on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    start_whatsapp_bot(
        host=WHATSAPP_CONFIG.get("host", "0.0.0.0"),
        port=WHATSAPP_CONFIG.get("port", 5005)
    )
