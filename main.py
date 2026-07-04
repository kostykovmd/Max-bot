import asyncio
import logging
import os
from datetime import datetime
from typing import Dict

from maxapi import Bot, Dispatcher, types
from maxapi.types import MessageCreated, Command

# ---------- Логирование ----------
logging.basicConfig(level=logging.INFO)

# ---------- Токен ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

# ---------- База данных SQLite ----------
import sqlite3
import aiosqlite

DB_PATH = "painbot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                max_user_id TEXT UNIQUE NOT NULL,
                role TEXT DEFAULT 'patient',
                password TEXT,
                full_name TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS pain_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                intensity INTEGER,
                location TEXT,
                character TEXT,
                medication TEXT,
                comment TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(record_id) REFERENCES pain_records(id),
                FOREIGN KEY(doctor_id) REFERENCES users(id)
            )
        ''')
        await db.commit()

# ---------- Функции БД ----------
async def get_user_by_max_id(max_user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = await db.execute("SELECT * FROM users WHERE max_user_id = ?", (max_user_id,))
        return await cursor.fetchone()

async def create_user(max_user_id: str, role: str, password: str = None, full_name: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (max_user_id, role, password, full_name) VALUES (?, ?, ?, ?)",
            (max_user_id, role, password, full_name)
        )
        await db.commit()

async def add_pain_record(user_id: int, intensity: int, location: str, character: str, medication: str, comment: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO pain_records (user_id, intensity, location, character, medication, comment) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, intensity, location, character, medication, comment)
        )
        await db.commit()
        return cursor.lastrowid

async def get_patient_records(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = await db.execute(
            "SELECT * FROM pain_records WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit)
        )
        return await cursor.fetchall()

async def get_all_patients():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = await db.execute("SELECT * FROM users WHERE role = 'patient'")
        return await cursor.fetchall()

async def add_comment(record_id: int, doctor_id: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO comments (record_id, doctor_id, text) VALUES (?, ?, ?)",
            (record_id, doctor_id, text)
        )
        await db.commit()

async def get_comments_for_record(record_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = await db.execute("SELECT * FROM comments WHERE record_id = ? ORDER BY timestamp", (record_id,))
        return await cursor.fetchall()

# ---------- Бот ----------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# Состояния пользователей (для пошагового ввода)
user_states: Dict[str, Dict] = {}
reports_store: Dict[str, str] = {}

# ---------- Клавиатуры (reply) ----------
def main_menu_patient():
    keyboard = [
        ["📝 Новая запись", "📋 История"],
        ["📊 Отчёт", "💬 Комментарии"],
        ["❌ Выйти"]
    ]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def main_menu_doctor():
    keyboard = [
        ["👨‍⚕️ Пациенты", "🔍 Просмотр записей"],
        ["💬 Оставить комментарий", "❌ Выйти"]
    ]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def intensity_keyboard():
    keyboard = [["0", "1", "2", "3", "4", "5"], ["6", "7", "8", "9", "10"]]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def location_keyboard():
    keyboard = [
        ["Голова", "Шея", "Спина"],
        ["Грудная клетка", "Живот", "Руки"],
        ["Ноги", "Суставы", "Другое"]
    ]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def character_keyboard():
    keyboard = [
        ["Острая", "Тупая", "Жгучая"],
        ["Колющая", "Ноющая", "Другое"]
    ]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def medication_keyboard():
    keyboard = [["Да", "Нет"]]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def cancel_keyboard():
    keyboard = [["❌ Отмена"]]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ---------- Вспомогательная функция для отправки меню ----------
async def send_main_menu(event: MessageCreated, user):
    if user['role'] == 'patient':
        await event.message.answer("🏠 Главное меню:", reply_markup=main_menu_patient())
    else:
        await event.message.answer("🏠 Главное меню врача:", reply_markup=main_menu_doctor())

# ---------- Обработчики команд ----------
@dp.message_created(Command('start'))
async def cmd_start(event: MessageCreated):
    user = await get_user_by_max_id(str(event.message.from_.id))
    if user:
        await event.message.answer(f"👋 С возвращением, {user['full_name'] or 'пользователь'}!")
        await send_main_menu(event, user)
    else:
        await event.message.answer(
            "👋 Добро пожаловать! Вы новый пользователь.\n"
            "Зарегистрируйтесь: `/register роль [пароль] [имя]`\n"
            "Роль: patient или doctor\n"
            "Пример: `/register patient 1234 Иван`",
            parse_mode="Markdown"
        )

@dp.message_created(Command('register'))
async def cmd_register(event: MessageCreated):
    max_id = str(event.message.from_.id)
    if await get_user_by_max_id(max_id):
        await event.message.answer("Вы уже зарегистрированы.")
        return
    parts = event.message.text.split(maxsplit=3)
    if len(parts) < 2:
        await event.message.answer("Используйте: `/register роль [пароль] [имя]`", parse_mode="Markdown")
        return
    role = parts[1].lower()
    if role not in ('patient', 'doctor'):
        await event.message.answer("Роль должна быть 'patient' или 'doctor'.")
        return
    password = parts[2] if len(parts) > 2 else None
    full_name = parts[3] if len(parts) > 3 else None
    await create_user(max_id, role, password, full_name)
    await event.message.answer(f"✅ Регистрация успешна! Роль: {role}")
    user = await get_user_by_max_id(max_id)
    await send_main_menu(event, user)

# ---------- Основной обработчик всех текстовых сообщений ----------
@dp.message_created()
async def handle_text(event: MessageCreated):
    user_id = str(event.message.from_.id)
    text = event.message.text.strip()
    user = await get_user_by_max_id(user_id)
    if not user:
        await event.message.answer("Сначала зарегистрируйтесь: /register")
        return

    # ----- Обработка команд врача /view и /comment -----
    if text.startswith('/view'):
        parts = text.split()
        if len(parts) < 2:
            await event.message.answer("Укажите ID пациента: /view <id>")
            return
        try:
            patient_id = int(parts[1])
        except ValueError:
            await event.message.answer("ID должен быть числом.")
            return
        if user['role'] != 'doctor':
            await event.message.answer("Только для врачей.")
            return
        records = await get_patient_records(patient_id, 20)
        if not records:
            await event.message.answer("У пациента нет записей.")
            return
        answer = f"📋 Записи пациента ID {patient_id}:\n\n"
        for r in records:
            answer += f"ID: {r['id']} | {r['timestamp']}\nИнт.{r['intensity']}, Лок.{r['location']}, Хар.{r['character']}, Лек.{r['medication']}\n"
            comments = await get_comments_for_record(r['id'])
            if comments:
                answer += "Комментарии: " + "; ".join([c['text'] for c in comments]) + "\n"
            else:
                answer += "Комментариев нет.\n"
            answer += "\n"
        await event.message.answer(answer[:4000])
        await send_main_menu(event, user)
        return

    if text.startswith('/comment'):
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await event.message.answer("Используйте: /comment <id_записи> <текст>")
            return
        try:
            record_id = int(parts[1])
        except ValueError:
            await event.message.answer("ID записи должен быть числом.")
            return
        comment_text = parts[2]
        if user['role'] != 'doctor':
            await event.message.answer("Только для врачей.")
            return
        # Проверяем существование записи
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT id FROM pain_records WHERE id = ?", (record_id,))
            if not await cursor.fetchone():
                await event.message.answer("Запись не найдена.")
                return
        await add_comment(record_id, user['id'], comment_text)
        await event.message.answer(f"✅ Комментарий добавлен к записи {record_id}.")
        await send_main_menu(event, user)
        return

    # ----- Если пользователь в процессе заполнения -----
    if user_id in user_states:
        state = user_states[user_id]
        step = state.get('step')

        if step == 'intensity':
            if text == "❌ Отмена":
                del user_states[user_id]
                await event.message.answer("❌ Отменено.", reply_markup=main_menu_patient() if user['role'] == 'patient' else main_menu_doctor())
                return
            if not text.isdigit() or not (0 <= int(text) <= 10):
                await event.message.answer("Введите число от 0 до 10.")
                return
            state['intensity'] = int(text)
            state['step'] = 'location'
            await event.message.answer("Выберите локализацию боли:", reply_markup=location_keyboard())

        elif step == 'location':
            if text == "❌ Отмена":
                del user_states[user_id]
                await event.message.answer("❌ Отменено.", reply_markup=main_menu_patient() if user['role'] == 'patient' else main_menu_doctor())
                return
            state['location'] = text
            state['step'] = 'character'
            await event.message.answer("Выберите характер боли:", reply_markup=character_keyboard())

        elif step == 'character':
            if text == "❌ Отмена":
                del user_states[user_id]
                await event.message.answer("❌ Отменено.", reply_markup=main_menu_patient() if user['role'] == 'patient' else main_menu_doctor())
                return
            state['character'] = text
            state['step'] = 'medication'
            await event.message.answer("Принимали ли вы обезболивающие? (Да/Нет)", reply_markup=medication_keyboard())

        elif step == 'medication':
            if text == "❌ Отмена":
                del user_states[user_id]
                await event.message.answer("❌ Отменено.", reply_markup=main_menu_patient() if user['role'] == 'patient' else main_menu_doctor())
                return
            if text.lower() not in ['да', 'нет']:
                await event.message.answer("Ответьте Да или Нет.")
                return
            state['medication'] = text
            state['step'] = 'comment'
            await event.message.answer("Введите комментарий (или напишите 'нет'):", reply_markup=cancel_keyboard())

        elif step == 'comment':
            if text == "❌ Отмена":
                del user_states[user_id]
                await event.message.answer("❌ Отменено.", reply_markup=main_menu_patient() if user['role'] == 'patient' else main_menu_doctor())
                return
            comment = None if text.lower() == 'нет' else text
            await add_pain_record(
                user_id=state['user_id'],
                intensity=state['intensity'],
                location=state['location'],
                character=state['character'],
                medication=state['medication'],
                comment=comment
            )
            del user_states[user_id]
            await event.message.answer("✅ Запись сохранена!", reply_markup=main_menu_patient() if user['role'] == 'patient' else main_menu_doctor())
        return

    # ----- Если не в процессе, обрабатываем команды из меню -----
    if user['role'] == 'patient':
        if text == "📝 Новая запись":
            user_states[user_id] = {'step': 'intensity', 'user_id': user['id']}
            await event.message.answer("Введите интенсивность боли (0-10):", reply_markup=intensity_keyboard())
        elif text == "📋 История":
            records = await get_patient_records(user['id'], 10)
            if not records:
                await event.message.answer("У вас нет записей.")
            else:
                answer = "📊 Последние записи:\n\n"
                for r in records:
                    answer += f"🕒 {r['timestamp']}\n💥 {r['intensity']} 📍 {r['location']} 📌 {r['character']} 💊 {r['medication']}\n📝 {r['comment'] or 'нет'}\n\n"
                await event.message.answer(answer[:4000])
            await send_main_menu(event, user)
        elif text == "📊 Отчёт":
            records = await get_patient_records(user['id'], 100)
            if not records:
                await event.message.answer("Нет записей для отчёта.")
                return
            report = f"📋 Отчёт {user['full_name'] or user['max_user_id']}\n{datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            for r in records:
                report += f"{r['timestamp']}: Инт.{r['intensity']}, Лок.{r['location']}, Хар.{r['character']}, Лек.{r['medication']}\n"
            reports_store[user_id] = report
            await event.message.answer("📄 Отчёт сгенерирован. Чтобы отправить врачу, напишите 'Отправить отчёт'.")
            await send_main_menu(event, user)
        elif text == "Отправить отчёт":
            if user_id not in reports_store:
                await event.message.answer("Сначала создайте отчёт через '📊 Отчёт'.")
                return
            await event.message.answer("✅ Отчёт отправлен врачу (демо-режим).\n\n" + reports_store[user_id][:1000])
            await send_main_menu(event, user)
        elif text == "💬 Комментарии":
            records = await get_patient_records(user['id'], 20)
            if not records:
                await event.message.answer("У вас нет записей.")
                return
            answer = "💬 Комментарии врачей:\n\n"
            found = False
            for r in records:
                comments = await get_comments_for_record(r['id'])
                if comments:
                    found = True
                    answer += f"📌 {r['timestamp']}:\n"
                    for c in comments:
                        answer += f"  - {c['text']}\n"
            if not found:
                await event.message.answer("Комментариев нет.")
            else:
                await event.message.answer(answer[:4000])
            await send_main_menu(event, user)
        elif text == "❌ Выйти":
            await event.message.answer("👋 До свидания!", reply_markup=types.ReplyKeyboardRemove())
        else:
            await event.message.answer("Неизвестная команда. Используйте кнопки меню.", reply_markup=main_menu_patient())

    elif user['role'] == 'doctor':
        if text == "👨‍⚕️ Пациенты":
            patients = await get_all_patients()
            if not patients:
                await event.message.answer("Нет пациентов.")
            else:
                answer = "👨‍⚕️ Пациенты:\n\n"
                for p in patients:
                    answer += f"ID: {p['id']}, {p['full_name'] or p['max_user_id']}\n"
                await event.message.answer(answer[:4000])
            await send_main_menu(event, user)
        elif text == "🔍 Просмотр записей":
            await event.message.answer("Введите ID пациента для просмотра (команда: /view <id>)")
        elif text == "💬 Оставить комментарий":
            await event.message.answer("Введите команду: /comment <id_записи> <текст>")
        elif text == "❌ Выйти":
            await event.message.answer("👋 До свидания!", reply_markup=types.ReplyKeyboardRemove())
        else:
            await event.message.answer("Неизвестная команда. Используйте кнопки меню.", reply_markup=main_menu_doctor())

# ---------- Запуск ----------
async def main():
    await init_db()
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
