import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Optional

from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, Command
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker as async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.sql import func

# ---------- Настройка логирования ----------
logging.basicConfig(level=logging.INFO)

# ---------- Переменные окружения ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не задан!")

# Для SQLAlchemy нужно заменить "postgres://" на "postgresql+asyncpg://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# ---------- Модели данных ----------
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    max_user_id = Column(String, unique=True, nullable=False)  # ID пользователя в MAX
    role = Column(String, default='patient')  # 'patient' или 'doctor'
    password = Column(String, nullable=True)  # временно, для простоты
    full_name = Column(String, nullable=True)

class PainRecord(Base):
    __tablename__ = 'pain_records'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    timestamp = Column(DateTime, default=func.now())
    intensity = Column(Integer)          # 0-10
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

# ---------- Инициализация БД ----------
async_engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ---------- Инициализация бота ----------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

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

async def get_all_patients(doctor_id: int):
    # упрощённо: возвращаем всех пользователей с ролью 'patient'
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

# ---------- Обработчики команд ----------

# Регистрация / старт
@dp.message_created(Command('start'))
async def cmd_start(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if user:
        await event.message.answer(
            f"👋 С возвращением, {user.full_name or 'пользователь'}!\n"
            f"Ваша роль: {user.role}\n"
            "Отправьте /help для списка команд."
        )
    else:
        await event.message.answer(
            "👋 Добро пожаловать! Вы новый пользователь.\n"
            "Чтобы продолжить, зарегистрируйтесь командой:\n"
            "/register <роль> [пароль] [имя]\n"
            "Роль: patient или doctor\n"
            "Пример: /register patient 1234 Иван"
        )

# Регистрация
@dp.message_created(Command('register'))
async def cmd_register(event: MessageCreated):
    max_id = str(event.message.from_.id)
    existing = await get_user_by_max_id(max_id)
    if existing:
        await event.message.answer("Вы уже зарегистрированы.")
        return

    # Парсим аргументы: /register role password name
    parts = event.message.text.split(maxsplit=3)
    if len(parts) < 2:
        await event.message.answer("Неверный формат. Используйте: /register <роль> [пароль] [имя]")
        return
    role = parts[1].lower()
    if role not in ('patient', 'doctor'):
        await event.message.answer("Роль должна быть 'patient' или 'doctor'.")
        return
    password = parts[2] if len(parts) > 2 else None
    full_name = parts[3] if len(parts) > 3 else None

    user = await create_user(max_id, role, password, full_name)
    await event.message.answer(
        f"✅ Регистрация успешна! Роль: {role}\n"
        f"Имя: {full_name or 'не указано'}\n"
        "Теперь вы можете использовать команды."
    )

# Справка
@dp.message_created(Command('help'))
async def cmd_help(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if not user:
        await event.message.answer("Сначала зарегистрируйтесь: /register")
        return

    if user.role == 'patient':
        help_text = (
            "📋 Команды для пациента:\n"
            "/new - Добавить запись о боли\n"
            "/history - Показать последние 10 записей\n"
            "/report - Сгенерировать отчёт для врача (все записи)\n"
            "/share - Отправить отчёт врачу (пока просто текст)\n"
            "/comments - Показать комментарии врача к вашим записям\n"
        )
    else:
        help_text = (
            "📋 Команды для врача:\n"
            "/patients - Список ваших пациентов (всех)\n"
            "/view <id пациента> - Просмотреть записи пациента\n"
            "/comment <id записи> <текст> - Оставить комментарий к записи\n"
        )
    await event.message.answer(help_text)

# ----- Команды для пациента -----
@dp.message_created(Command('new'))
async def cmd_new(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if not user or user.role != 'patient':
        await event.message.answer("Эта команда только для пациентов. Зарегистрируйтесь как patient.")
        return
    # Используем временное хранилище для состояний (в памяти)
    # В реальном проекте лучше хранить в Redis или БД, но для простоты оставим в памяти
    if 'temp' not in globals():
        globals()['temp'] = {}
    temp = globals()['temp']
    temp[max_id] = {'step': 'intensity', 'user_id': user.id}
    await event.message.answer("Оцените интенсивность боли от 0 до 10 (числом):")

@dp.message_created()
async def handle_patient_input(event: MessageCreated):
    max_id = str(event.message.from_.id)
    if 'temp' not in globals() or max_id not in globals()['temp']:
        return
    temp = globals()['temp']
    data = temp[max_id]
    step = data['step']
    text = event.message.text.strip()

    if step == 'intensity':
        try:
            intensity = int(text)
            if 0 <= intensity <= 10:
                data['intensity'] = intensity
                data['step'] = 'location'
                await event.message.answer("Укажите локализацию боли (например, голова, спина):")
            else:
                await event.message.answer("Введите число от 0 до 10.")
        except ValueError:
            await event.message.answer("Пожалуйста, введите число.")
    elif step == 'location':
        data['location'] = text
        data['step'] = 'character'
        await event.message.answer("Опишите характер боли (острая, тупая, жгучая и т.п.):")
    elif step == 'character':
        data['character'] = text
        data['step'] = 'medication'
        await event.message.answer("Принимали ли вы обезболивающие? (Да/Нет):")
    elif step == 'medication':
        data['medication'] = text
        data['step'] = 'comment'
        await event.message.answer("Дополнительный комментарий (или 'нет'):")
    elif step == 'comment':
        comment = text if text.lower() != 'нет' else None
        record = await add_pain_record(
            user_id=data['user_id'],
            intensity=data['intensity'],
            location=data['location'],
            character=data['character'],
            medication=data['medication'],
            comment=comment
        )
        del temp[max_id]
        await event.message.answer(
            f"✅ Запись сохранена! ID записи: {record.id}\n"
            f"Интенсивность: {record.intensity}\n"
            f"Локализация: {record.location}\n"
            f"Характер: {record.character}\n"
            f"Лекарства: {record.medication}\n"
            f"Комментарий: {record.comment or 'нет'}"
        )

@dp.message_created(Command('history'))
async def cmd_history(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if not user or user.role != 'patient':
        await event.message.answer("Только для пациентов.")
        return
    records = await get_patient_records(user.id, 10)
    if not records:
        await event.message.answer("У вас нет записей.")
        return
    answer = "📊 Последние записи:\n\n"
    for r in records:
        answer += (
            f"ID: {r.id} | {r.timestamp.strftime('%d.%m %H:%M')}\n"
            f"Инт.: {r.intensity}, Локал.: {r.location}, Хар.: {r.character}, Лек.: {r.medication}\n"
            f"Комм.: {r.comment or 'нет'}\n\n"
        )
    await event.message.answer(answer[:4000])  # ограничение длины

@dp.message_created(Command('report'))
async def cmd_report(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if not user or user.role != 'patient':
        await event.message.answer("Только для пациентов.")
        return
    records = await get_patient_records(user.id, 100)  # все записи
    if not records:
        await event.message.answer("Нет записей для отчёта.")
        return
    report = f"📋 Отчёт пациента {user.full_name or user.max_user_id}\nДата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    for r in records:
        report += (
            f"{r.timestamp.strftime('%d.%m %Y %H:%M')}: Инт.{r.intensity}, "
            f"Лок.{r.location}, Хар.{r.character}, Лек.{r.medication}"
            f"{', Комм.: '+r.comment if r.comment else ''}\n"
        )
    # Сохраняем отчёт в памяти для отправки врачу
    if 'reports' not in globals():
        globals()['reports'] = {}
    globals()['reports'][max_id] = report
    await event.message.answer("Отчёт сгенерирован. Чтобы отправить врачу, используйте /share")

@dp.message_created(Command('share'))
async def cmd_share(event: MessageCreated):
    max_id = str(event.message.from_.id)
    if 'reports' not in globals() or max_id not in globals()['reports']:
        await event.message.answer("Сначала сгенерируйте отчёт через /report")
        return
    report = globals()['reports'][max_id]
    # В реальном проекте здесь нужно найти врача пациента и отправить ему сообщение.
    # Для простоты отправим отчёт в личные сообщения боту (можно потом расширить).
    # Пока просто подтверждаем.
    await event.message.answer("Отчёт отправлен врачу (в демо-режиме).\n\n" + report[:1000])

@dp.message_created(Command('comments'))
async def cmd_comments(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if not user or user.role != 'patient':
        await event.message.answer("Только для пациентов.")
        return
    records = await get_patient_records(user.id, 20)
    if not records:
        await event.message.answer("Нет записей.")
        return
    answer = "💬 Комментарии врача:\n\n"
    found = False
    for rec in records:
        comments = await get_comments_for_record(rec.id)
        if comments:
            found = True
            answer += f"Запись ID {rec.id} ({rec.timestamp.strftime('%d.%m')}):\n"
            for c in comments:
                answer += f"  - {c.text} (врач {c.doctor_id})\n"
    if not found:
        await event.message.answer("Нет комментариев.")
    else:
        await event.message.answer(answer[:4000])

# ----- Команды для врача -----
@dp.message_created(Command('patients'))
async def cmd_patients(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if not user or user.role != 'doctor':
        await event.message.answer("Только для врачей.")
        return
    patients = await get_all_patients(user.id)
    if not patients:
        await event.message.answer("Нет зарегистрированных пациентов.")
        return
    answer = "👨‍⚕️ Список пациентов:\n\n"
    for p in patients:
        answer += f"ID: {p.id}, Имя: {p.full_name or p.max_user_id}\n"
    await event.message.answer(answer[:4000])

@dp.message_created(Command('view'))
async def cmd_view(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if not user or user.role != 'doctor':
        await event.message.answer("Только для врачей.")
        return
    parts = event.message.text.split()
    if len(parts) < 2:
        await event.message.answer("Укажите ID пациента: /view <id>")
        return
    try:
        patient_id = int(parts[1])
    except ValueError:
        await event.message.answer("ID должен быть числом.")
        return
    # Получаем записи пациента
    async with AsyncSessionLocal() as session:
        # Проверяем, что пациент существует
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

@dp.message_created(Command('comment'))
async def cmd_comment(event: MessageCreated):
    max_id = str(event.message.from_.id)
    user = await get_user_by_max_id(max_id)
    if not user or user.role != 'doctor':
        await event.message.answer("Только для врачей.")
        return
    parts = event.message.text.split(maxsplit=2)
    if len(parts) < 3:
        await event.message.answer("Используйте: /comment <id_записи> <текст комментария>")
        return
    try:
        record_id = int(parts[1])
    except ValueError:
        await event.message.answer("ID записи должен быть числом.")
        return
    comment_text = parts[2]

    # Проверяем, существует ли запись
    async with AsyncSessionLocal() as session:
        record = await session.get(PainRecord, record_id)
        if not record:
            await event.message.answer("Запись не найдена.")
            return
        # Добавляем комментарий
        await add_comment(record_id, user.id, comment_text)
        await event.message.answer(f"✅ Комментарий к записи {record_id} добавлен.")

# ---------- Запуск бота ----------
async def main():
    await init_db()
    # Удаляем старый вебхук, если был
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
