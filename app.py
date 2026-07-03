from flask import Flask, request, jsonify
import httpx
import os
import sqlite3
import json
from datetime import datetime

TOKEN = os.getenv("MAX_TOKEN")
BASE_URL = f"https://api.max.ru/bot{TOKEN}"

app = Flask(__name__)

# ========== БАЗА ДАННЫХ ==========
def get_db():
    conn = sqlite3.connect('pain_bot.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                role TEXT CHECK(role IN ('patient', 'doctor')),
                registered_at TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS pain_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                pain_level INTEGER,
                note TEXT,
                created_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS patient_doctor (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER,
                doctor_id INTEGER,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                FOREIGN KEY(patient_id) REFERENCES users(user_id),
                FOREIGN KEY(doctor_id) REFERENCES users(user_id)
            )
        ''')
        conn.commit()
        print("✅ База данных инициализирована")

def register_user(user_id, full_name, role):
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute('''
            INSERT INTO users (user_id, full_name, role, registered_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name = excluded.full_name,
                role = excluded.role
        ''', (user_id, full_name, role, now))
        conn.commit()

def get_user(user_id):
    with get_db() as conn:
        cur = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return cur.fetchone()

def save_pain_entry(user_id, pain_level, note=""):
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute('''
            INSERT INTO pain_entries (user_id, pain_level, note, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, pain_level, note, now))
        conn.commit()

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========
def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    try:
        httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def handle_start(chat_id, user_id, full_name):
    user = get_user(user_id)
    if user:
        reply = f"👋 С возвращением, {user['full_name']}!\nВаша роль: {user['role']}.\nИспользуйте /help для списка команд."
    else:
        # Пока просто регистрируем как пациента (можно будет выбрать роль позже)
        register_user(user_id, full_name, "patient")
        reply = "👋 Добро пожаловать! Вы зарегистрированы как пациент. Используйте /help для списка команд."
    send_message(chat_id, reply)

def handle_help(chat_id):
    reply = (
        "📋 Доступные команды:\n"
        "/start — начать\n"
        "/help — справка\n"
        "/today — записать сегодняшнюю боль (от 0 до 10)\n"
        "/stats — посмотреть статистику"
    )
    send_message(chat_id, reply)

def handle_today(chat_id, user_id, text):
    # Парсим уровень боли: /today 7  или /today 7 головная боль
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        send_message(chat_id, "❌ Укажите уровень боли от 0 до 10.\nПример: /today 7")
        return
    try:
        pain_level = int(parts[0].strip())
        if pain_level < 0 or pain_level > 10:
            send_message(chat_id, "❌ Уровень боли должен быть от 0 до 10.")
            return
    except ValueError:
        send_message(chat_id, "❌ Введите число от 0 до 10.\nПример: /today 7")
        return

    note = parts[1] if len(parts) > 1 else ""
    save_pain_entry(user_id, pain_level, note)
    send_message(chat_id, f"✅ Записано: боль {pain_level}/10.\nПримечание: {note if note else '—'}")

def handle_stats(chat_id, user_id):
    with get_db() as conn:
        cur = conn.execute('''
            SELECT pain_level, note, created_at FROM pain_entries
            WHERE user_id = ? ORDER BY created_at DESC LIMIT 5
        ''', (user_id,))
        rows = cur.fetchall()
    if not rows:
        send_message(chat_id, "📊 У вас пока нет записей о боли.")
        return
    lines = ["📊 Последние 5 записей:"]
    for row in rows:
        dt = row['created_at'][:10]
        note = f" ({row['note']})" if row['note'] else ""
        lines.append(f"• {dt}: {row['pain_level']}/10{note}")
    send_message(chat_id, "\n".join(lines))

# ========== ВЕБХУК ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False}), 400

    if 'message' in data:
        msg = data['message']
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        full_name = msg['from'].get('first_name', 'Пользователь')
        text = msg.get('text', '')

        if text.startswith('/start'):
            handle_start(chat_id, user_id, full_name)
        elif text.startswith('/help'):
            handle_help(chat_id)
        elif text.startswith('/today'):
            handle_today(chat_id, user_id, text.split(maxsplit=1)[0])  # передаём только команду
        elif text.startswith('/stats'):
            handle_stats(chat_id, user_id)
        else:
            send_message(chat_id, f"Вы написали: «{text}»\nОтправьте /help для списка команд.")

    return jsonify({"ok": True})

@app.route('/')
def index():
    return "Бот работает"

# Инициализация БД при старте
init_db()