import asyncio
import logging
import os

from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, Command

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Токен и секрет – берём из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
if not WEBHOOK_SECRET:
    raise ValueError("WEBHOOK_SECRET не задан!")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# Хранилище данных пользователей (в памяти, для теста)
user_data = {}

# ---------- Обработчики команд ----------

@dp.message_created(Command('start'))
async def cmd_start(event: MessageCreated):
    await event.message.answer(
        "👋 Привет! Я бот для ведения дневника боли.\n"
        "Отправьте /help, чтобы узнать мои команды."
    )

@dp.message_created(Command('help'))
async def cmd_help(event: MessageCreated):
    await event.message.answer(
        "📋 Доступные команды:\n"
        "/start - Начать работу\n"
        "/help - Показать эту справку\n"
        "/new - Добавить новую запись о боли\n"
        "/history - Показать последние записи"
    )

@dp.message_created(Command('new'))
async def cmd_new(event: MessageCreated):
    user_id = event.message.from_.id
    # Начинаем опрос
    user_data[user_id] = {'step': 'intensity'}
    await event.message.answer(
        "Оцените интенсивность боли по шкале от 0 до 10 (числом):"
    )

# Обработчик всех текстовых сообщений (для пошагового сбора)
@dp.message_created()
async def handle_text(event: MessageCreated):
    user_id = event.message.from_.id
    if user_id not in user_data:
        return  # не в процессе ввода

    step = user_data[user_id].get('step')
    text = event.message.text.strip()

    if step == 'intensity':
        try:
            intensity = int(text)
            if 0 <= intensity <= 10:
                user_data[user_id]['intensity'] = intensity
                user_data[user_id]['step'] = 'location'
                await event.message.answer("Укажите локализацию боли (например, голова, спина):")
            else:
                await event.message.answer("Введите число от 0 до 10.")
        except ValueError:
            await event.message.answer("Пожалуйста, введите число.")

    elif step == 'location':
        user_data[user_id]['location'] = text
        user_data[user_id]['step'] = 'character'
        await event.message.answer("Опишите характер боли (острая, тупая, жгучая и т.п.):")

    elif step == 'character':
        user_data[user_id]['character'] = text
        user_data[user_id]['step'] = 'medication'
        await event.message.answer("Принимали ли вы обезболивающие? (Да/Нет):")

    elif step == 'medication':
        user_data[user_id]['medication'] = text
        # Сохраняем запись
        record = {
            'intensity': user_data[user_id].get('intensity'),
            'location': user_data[user_id].get('location'),
            'character': user_data[user_id].get('character'),
            'medication': user_data[user_id].get('medication')
        }
        if 'records' not in user_data[user_id]:
            user_data[user_id]['records'] = []
        user_data[user_id]['records'].append(record)

        # Очищаем состояние
        del user_data[user_id]

        await event.message.answer(
            f"✅ Запись сохранена!\n"
            f"Интенсивность: {record['intensity']}\n"
            f"Локализация: {record['location']}\n"
            f"Характер: {record['character']}\n"
            f"Принимали лекарства: {record['medication']}"
        )

@dp.message_created(Command('history'))
async def cmd_history(event: MessageCreated):
    user_id = event.message.from_.id
    if user_id not in user_data or 'records' not in user_data[user_id]:
        await event.message.answer("У вас пока нет записей. Добавьте через /new.")
        return

    records = user_data[user_id]['records'][-5:]  # последние 5
    answer = "📊 Ваши последние записи:\n\n"
    for i, rec in enumerate(reversed(records), 1):
        answer += (
            f"{i}. Интенсивность: {rec['intensity']}, "
            f"Локализация: {rec['location']}, "
            f"Характер: {rec['character']}, "
            f"Лекарства: {rec['medication']}\n"
        )
    await event.message.answer(answer)

# ---------- Запуск через вебхук ----------
async def main():
    # На случай, если остался старый вебхук
    await bot.delete_webhook()
    # Запускаем веб-сервер, который будет принимать POST-запросы от MAX
    # Секрет будет проверяться автоматически в каждом запросе
    await dp.handle_webhook(
        bot=bot,
        host='0.0.0.0',                     # слушаем все интерфейсы
        port=int(os.getenv("PORT", 8080)), # порт, который использует Bothost
        secret=WEBHOOK_SECRET,             # передаём секрет для проверки
        log_level='info'
    )

if __name__ == '__main__':
    asyncio.run(main())