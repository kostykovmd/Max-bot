import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any

from maxapi import Bot, Dispatcher, types
from maxapi.types import MessageCreated, Command
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker as async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.sql import func

# ---------- Логирование ----------
logging.basicConfig(level=logging.INFO)

# ---------- Переменные окружения ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite+aiosqlite:///./painbot.db"
    logging.warning("DATABASE_URL не задан, используем SQLite (данные могут теряться).")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif "sqlite://" in DATABASE_URL and "sqlite+aiosqlite" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://")

# ---------- Модели БД ----------
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    max_user_id = Column(String, unique=True, nullable=False)
    role = Column(String, default='patient')
    password = Column(String, nullable=True)
    full_name = Column(String, nullable=True)

class PainRecord(Base):
    __tablename__ = 'pain_records'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    timestamp = Column(DateTime, default=func.now())
    intensity = Column(Integer)
    location = Column(String)
    character = Column(String)
    medication = Column(String)
    comment = Column(Text, nullable=True)
    user = relationship("User", backref="records")

class Comment(Base):
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True)
    record_id = Column(Integer, ForeignKey('pain_records.id'), nullable=False)
    doctor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    text = Column(Text)
    timestamp = Column(DateTime, default=func.now())
    record = relationship("PainRecord", backref="comments")
    doctor = relationship("User", backref="doctor_comments")

# ---------- Движок БД ----------
async_engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ---------- Вспомогательные функции ----------
async def get_user_by_max_id(max_user_id: str) -> Optional[User]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.max_user_id == max_user_id))
        return result.scalar_one_or_none()

async def create_user(max_user_id: str, role: str = 'patient', password: str = None, full_name: str = None):
    async with AsyncSessionLocal() as session:
        user = User(max_user_id=max_user_id, role=role, password=password, full_name=full_name)
        session.add(user)
        await session.commit()
        return user

async def add_pain_record(user_id: int, intensity: int, location: str, character: str, medication: str, comment: str = None):
    async with AsyncSessionLocal() as session:
        record = PainRecord(
            user_id=user_id,
            intensity=intensity,
            location=location,
            character=character,
            medication=medication,
            comment=comment
        )
        session.add(record)
        await session.commit()
        return record

async def get_patient_records(user_id: int, limit: int = 10):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PainRecord)
            .where(PainRecord.user_id == user_id)
            .order_by(PainRecord.timestamp.desc())
            .limit(limit)
        )
        return result.scalars().all()

async def get_all_patients():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.role == 'patient'))
        return result.scalars().all()

async def add_comment(record_id: int, doctor_id: int, text: str):
    async with AsyncSessionLocal() as session:
        comment = Comment(record_id=record_id, doctor_id=doctor_id, text=text)
        session.add(comment)
        await session.commit()
        return comment

async def get_comments_for_record(record_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Comment)
            .where(Comment.record_id == record_id)
            .order_by(Comment.timestamp)
        )
        return result.scalars().all()

# ---------- Инициализация бота ----------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ---------- Хранилище состояний (в памяти) ----------
user_states: Dict[str, Dict[str, Any]] = {}
reports_store: Dict[str, str] = {}

# ---------- Вспомогательные функции для клавиатур ----------
def make_inline_keyboard(buttons: list, row_width: int = 3):
    keyboard = []
    for i in range(0, len(buttons), row_width):
        row = []
        for text, callback_data in buttons[i:i+row_width]:
            row.append(types.InlineKeyboardButton(text=text, callback_data=callback_data))
        keyboard.append(row)
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def main_menu_patient():
    buttons = [
        ("📝 Новая запись", "new_record"),
        ("📋 История", "history"),
        ("📊 Отчёт", "report"),
        ("💬 Комментарии", "comments"),
        ("❌ Выйти", "exit")
    ]
    return make_inline_keyboard(buttons, row_width=2)

def main_menu_doctor():
    buttons = [
        ("👨‍⚕️ Пациенты", "patients"),
        ("🔍 Просмотр записей", "view_records"),
        ("💬 Оставить комментарий", "leave_comment"),
        ("❌ Выйти", "exit")
    ]
    return make_inline_keyboard(buttons, row_width=2)

def intensity_keyboard():
    buttons = [(str(i), f"intensity_{i}") for i in range(11)]
    return make_inline_keyboard(buttons, row_width=6)

def location_keyboard():
    locs = [
        ("Голова", "loc_голова"),
        ("Шея", "loc_шея"),
        ("Спина", "loc_спина"),
        ("Грудная клетка", "loc_грудная клетка"),
        ("Живот", "loc_живот"),
        ("Руки", "loc_руки"),
        ("Ноги", "loc_ноги"),
        ("Суставы", "loc_суставы"),
        ("Другое", "loc_другое")
    ]
    return make_inline_keyboard(locs, row_width=3)

def character_keyboard():
    chars = [
        ("Острая", "char_острая"),
        ("Тупая", "char_тупая"),
        ("Жгучая", "char_жгучая"),
        ("Колющая", "char_колющая"),
        ("Ноющая", "char_ноющая"),
        ("Другое", "char_другое")
    ]
    return make_inline_keyboard(chars, row_width=3)

def medication_keyboard():
    buttons = [("✅ Да", "med_yes"), ("❌ Нет", "med_no")]
    return make_inline_keyboard(buttons, row_width=2)

def cancel_keyboard():
    buttons = [("❌ Отмена", "cancel")]
    return make_inline_keyboard(buttons, row_width=1)

# ---------- Отправка главного меню ----------
async def send_main_menu(event: MessageCreated, user: User):
    if user.role == 'patient':
        await event.message.answer(
            "🏠 *Главное меню*\nВыберите действие:",
            reply_markup=main_menu_patient(),
            parse_mode="Markdown"
        )
    else:
        await event.message.answer(
            "🏠 *Главное меню врача*\nВыберите действие:",
            reply_markup=main_menu_doctor(),
            parse_mode="Markdown"
        )

# ---------- Обработчики команд ----------
@dp.message_created(Command('start'))
async def cmd_start(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if user:
        await event.message.answer(
            f"👋 С возвращением, {user.full_name or 'пользователь'}!",
            parse_mode="Markdown"
        )
        await send_main_menu(event, user)
    else:
        await event.message.answer(
            "👋 Добро пожаловать! Вы новый пользователь.\n"
            "Чтобы зарегистрироваться, отправьте:\n"
            "`/register роль [пароль] [имя]`\n"
            "Роль: `patient` или `doctor`\n"
            "Пример: `/register patient 1234 Иван`",
            parse_mode="Markdown"
        )

@dp.message_created(Command('register'))
async def cmd_register(event: MessageCreated):
    max_id = str(event.message.from_.id)
    existing = await get_user_by_max_id(max_id)
    if existing:
        await event.message.answer("Вы уже зарегистрированы.")
        return
    parts = event.message.text.split(maxsplit=3)
    if len(parts) < 2:
        await event.message.answer("Неверный формат. Используйте: `/register роль [пароль] [имя]`", parse_mode="Markdown")
        return
    role = parts[1].lower()
    if role not in ('patient', 'doctor'):
        await event.message.answer("Роль должна быть 'patient' или 'doctor'.")
        return
    password = parts[2] if len(parts) > 2 else None
    full_name = parts[3] if len(parts) > 3 else None

    user = await create_user(max_id, role, password, full_name)
    await event.message.answer(
        f"✅ Регистрация успешна! Роль: {role}\nИмя: {full_name or 'не указано'}",
        parse_mode="Markdown"
    )
    await send_main_menu(event, user)

# ---------- Обработчик callback-запросов (без аннотации типа) ----------
@dp.callback_query()
async def handle_callback(callback):  # не указываем тип, чтобы избежать ошибки импорта
    user_id = str(callback.from_.id)
    data = callback.data

    if data == "exit":
        await callback.answer("До свидания!")
        await callback.message.edit_text("👋 Вы вышли из главного меню. Для повторного входа отправьте /start")
        return

    user = await get_user_by_max_id(user_id)
    if not user:
        await callback.answer("Пожалуйста, зарегистрируйтесь командой /register")
        await callback.message.edit_text("Пожалуйста, зарегистрируйтесь командой /register")
        return

    # ---------- Действия пациента ----------
    if user.role == 'patient':
        if data == "new_record":
            user_states[user_id] = {'step': 'intensity', 'user_id': user.id}
            await callback.answer()
            await callback.message.edit_text(
                "📝 *Новая запись*\nВыберите интенсивность боли от 0 до 10:",
                reply_markup=intensity_keyboard(),
                parse_mode="Markdown"
            )
        elif data == "history":
            records = await get_patient_records(user.id, 10)
            if not records:
                await callback.answer("Нет записей")
                await callback.message.edit_text("У вас пока нет записей.")
            else:
                text = "📊 *Последние записи:*\n\n"
                for r in records:
                    text += (
                        f"🕒 {r.timestamp.strftime('%d.%m %H:%M')}\n"
                        f"💥 Интенсивность: {r.intensity}\n"
                        f"📍 Локализация: {r.location}\n"
                        f"📌 Характер: {r.character}\n"
                        f"💊 Лекарства: {r.medication}\n"
                        f"📝 Комментарий: {r.comment or 'нет'}\n\n"
                    )
                await callback.answer()
                await callback.message.edit_text(text[:4000], parse_mode="Markdown")
                await callback.message.answer("Выберите действие:", reply_markup=main_menu_patient())
        elif data == "report":
            records = await get_patient_records(user.id, 100)
            if not records:
                await callback.answer("Нет записей для отчёта")
                await callback.message.edit_text("Нет записей для отчёта.")
                return
            report = f"📋 *Отчёт пациента {user.full_name or user.max_user_id}*\nДата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            for r in records:
                report += (
                    f"{r.timestamp.strftime('%d.%m %H:%M')}: Инт.{r.intensity}, "
                    f"Лок.{r.location}, Хар.{r.character}, Лек.{r.medication}"
                    f"{', Комм.: '+r.comment if r.comment else ''}\n"
                )
            reports_store[user_id] = report
            await callback.answer()
            await callback.message.edit_text(
                "📄 Отчёт сгенерирован. Чтобы отправить врачу, нажмите кнопку ниже.",
                reply_markup=make_inline_keyboard([("📤 Отправить врачу", "share_report")], row_width=1)
            )
        elif data == "share_report":
            if user_id not in reports_store:
                await callback.answer("Сначала сгенерируйте отчёт через /report")
                return
            report = reports_store[user_id]
            await callback.answer()
            await callback.message.edit_text(
                "✅ Отчёт отправлен врачу (в демо-режиме).\n\n" + report[:1000],
                parse_mode="Markdown"
            )
            await callback.message.answer("Выберите действие:", reply_markup=main_menu_patient())
        elif data == "comments":
            records = await get_patient_records(user.id, 20)
            if not records:
                await callback.answer("Нет записей")
                await callback.message.edit_text("У вас нет записей.")
                return
            answer = "💬 *Комментарии врача:*\n\n"
            found = False
            for rec in records:
                comments = await get_comments_for_record(rec.id)
                if comments:
                    found = True
                    answer += f"📌 Запись от {rec.timestamp.strftime('%d.%m %H:%M')}:\n"
                    for c in comments:
                        answer += f"  - {c.text} (врач {c.doctor_id})\n"
            if not found:
                await callback.answer("Нет комментариев")
                await callback.message.edit_text("Нет комментариев от врачей.")
            else:
                await callback.answer()
                await callback.message.edit_text(answer[:4000], parse_mode="Markdown")
                await callback.message.answer("Выберите действие:", reply_markup=main_menu_patient())

    # ---------- Действия врача ----------
    elif user.role == 'doctor':
        if data == "patients":
            patients = await get_all_patients()
            if not patients:
                await callback.answer("Нет пациентов")
                await callback.message.edit_text("Нет зарегистрированных пациентов.")
                return
            text = "👨‍⚕️ *Список пациентов:*\n\n"
            for p in patients:
                text += f"ID: {p.id}, Имя: {p.full_name or p.max_user_id}\n"
            await callback.answer()
            await callback.message.edit_text(text[:4000], parse_mode="Markdown")
            await callback.message.answer("Выберите действие:", reply_markup=main_menu_doctor())
        elif data == "view_records":
            await callback.answer()
            await callback.message.edit_text(
                "Введите ID пациента, чьи записи хотите просмотреть.\n"
                "Например: `/view 5`\n"
                "(можно использовать команду /view <id>)"
            )
        elif data == "leave_comment":
            await callback.answer()
            await callback.message.edit_text(
                "Введите команду: `/comment <id_записи> <текст>`\n"
                "Например: `/comment 12 Отличная динамика!`"
            )

    # ---------- Обработка шагов создания записи ----------
    if data.startswith("intensity_"):
        intensity = int(data.split("_")[1])
        if user_id not in user_states:
            await callback.answer("Начните новую запись через /new")
            return
        user_states[user_id]['intensity'] = intensity
        user_states[user_id]['step'] = 'location'
        await callback.answer(f"Выбрано: {intensity}")
        await callback.message.edit_text(
            f"✅ Интенсивность: {intensity}\n\n"
            "Теперь выберите локализацию боли:",
            reply_markup=location_keyboard(),
            parse_mode="Markdown"
        )

    elif data.startswith("loc_"):
        location = data.split("_", 1)[1]
        if user_id not in user_states or user_states[user_id].get('step') != 'location':
            await callback.answer("Пожалуйста, начните заново через /new")
            return
        user_states[user_id]['location'] = location
        user_states[user_id]['step'] = 'character'
        await callback.answer(f"Локализация: {location}")
        await callback.message.edit_text(
            f"📍 Локализация: {location}\n\n"
            "Выберите характер боли:",
            reply_markup=character_keyboard(),
            parse_mode="Markdown"
        )

    elif data.startswith("char_"):
        character = data.split("_", 1)[1]
        if user_id not in user_states or user_states[user_id].get('step') != 'character':
            await callback.answer("Пожалуйста, начните заново через /new")
            return
        user_states[user_id]['character'] = character
        user_states[user_id]['step'] = 'medication'
        await callback.answer(f"Характер: {character}")
        await callback.message.edit_text(
            f"📌 Характер: {character}\n\n"
            "Принимали ли вы обезболивающие?",
            reply_markup=medication_keyboard(),
            parse_mode="Markdown"
        )

    elif data.startswith("med_"):
        med = "Да" if data == "med_yes" else "Нет"
        if user_id not in user_states or user_states[user_id].get('step') != 'medication':
            await callback.answer("Пожалуйста, начните заново через /new")
            return
        user_states[user_id]['medication'] = med
        user_states[user_id]['step'] = 'comment'
        await callback.answer(f"Лекарства: {med}")
        await callback.message.edit_text(
            f"💊 Лекарства: {med}\n\n"
            "Оставьте дополнительный комментарий (или нажмите 'Пропустить'):",
            reply_markup=make_inline_keyboard([("⏭ Пропустить", "skip_comment")], row_width=1),
            parse_mode="Markdown"
        )

    elif data == "skip_comment":
        if user_id not in user_states or user_states[user_id].get('step') != 'comment':
            await callback.answer("Ошибка. Начните заново.")
            return
        state = user_states[user_id]
        record = await add_pain_record(
            user_id=state['user_id'],
            intensity=state['intensity'],
            location=state['location'],
            character=state['character'],
            medication=state['medication'],
            comment=None
        )
        del user_states[user_id]
        await callback.answer("Запись сохранена!")
        await callback.message.edit_text(
            f"✅ *Запись сохранена!*\n"
            f"Интенсивность: {record.intensity}\n"
            f"Локализация: {record.location}\n"
            f"Характер: {record.character}\n"
            f"Лекарства: {record.medication}\n"
            f"Комментарий: нет",
            parse_mode="Markdown"
        )
        await callback.message.answer("Выберите действие:", reply_markup=main_menu_patient())

    elif data == "cancel":
        if user_id in user_states:
            del user_states[user_id]
        await callback.answer("Действие отменено")
        await callback.message.edit_text("❌ Действие отменено.")
        user = await get_user_by_max_id(user_id)
        if user:
            await callback.message.answer("Выберите действие:", reply_markup=main_menu_patient() if user.role == 'patient' else main_menu_doctor())

# ---------- Обработчик текстовых сообщений (для комментариев и команд) ----------
@dp.message_created()
async def handle_text(event: MessageCreated):
    user_id = str(event.message.from_.id)
    text = event.message.text.strip()

    # Если пользователь в процессе ввода комментария
    if user_id in user_states and user_states[user_id].get('step') == 'comment':
        state = user_states[user_id]
        record = await add_pain_record(
            user_id=state['user_id'],
            intensity=state['intensity'],
            location=state['location'],
            character=state['character'],
            medication=state['medication'],
            comment=text
        )
        del user_states[user_id]
        await event.message.answer(
            f"✅ *Запись сохранена!*\n"
            f"Интенсивность: {record.intensity}\n"
            f"Локализация: {record.location}\n"
            f"Характер: {record.character}\n"
            f"Лекарства: {record.medication}\n"
            f"Комментарий: {text}",
            parse_mode="Markdown"
        )
        user = await get_user_by_max_id(user_id)
        if user:
            await send_main_menu(event, user)
        return

    # Обработка команд /view и /comment (врач)
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
        user = await get_user_by_max_id(user_id)
        if not user or user.role != 'doctor':
            await event.message.answer("Только для врачей.")
            return
        async with AsyncSessionLocal() as session:
            patient = await session.get(User, patient_id)
            if not patient or patient.role != 'patient':
                await event.message.answer("Пациент не найден.")
                return
            records = await get_patient_records(patient_id, 20)
            if not records:
                await event.message.answer("У пациента нет записей.")
                return
            answer = f"📋 Записи пациента {patient.full_name or patient.max_user_id}:\n\n"
            for r in records:
                answer += (
                    f"ID записи: {r.id} | {r.timestamp.strftime('%d.%m %H:%M')}\n"
                    f"Инт.: {r.intensity}, Лок.: {r.location}, Хар.: {r.character}, Лек.: {r.medication}\n"
                    f"Комм. пациента: {r.comment or 'нет'}\n"
                    f"Комментарии врача: "
                )
                comments = await get_comments_for_record(r.id)
                if comments:
                    for c in comments:
                        answer += f"[{c.timestamp.strftime('%H:%M')}] {c.text}; "
                else:
                    answer += "нет"
                answer += "\n\n"
            await event.message.answer(answer[:4000])

    elif text.startswith('/comment'):
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await event.message.answer("Используйте: /comment <id_записи> <текст комментария>")
            return
        try:
            record_id = int(parts[1])
        except ValueError:
            await event.message.answer("ID записи должен быть числом.")
            return
        comment_text = parts[2]
        user = await get_user_by_max_id(user_id)
        if not user or user.role != 'doctor':
            await event.message.answer("Только для врачей.")
            return
        async with AsyncSessionLocal() as session:
            record = await session.get(PainRecord, record_id)
            if not record:
                await event.message.answer("Запись не найдена.")
                return
            await add_comment(record_id, user.id, comment_text)
            await event.message.answer(f"✅ Комментарий к записи {record_id} добавлен.")

# ---------- Запуск ----------
async def main():
    await init_db()
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
