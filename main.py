import asyncio
import logging
import os

from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, Command

# Настройка логирования для отслеживания работы бота
logging.basicConfig(level=logging.INFO)

# --- 1. Инициализация ---
# Токен бота берется из переменной окружения BOT_TOKEN.
# Это безопаснее, чем хранить его прямо в коде.
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# --- 2. Обработчики команд ---

# Обработчик команды /start
@dp.message_created(Command('start'))
async def cmd_start(event: MessageCreated):
    """Приветственное сообщение."""
    await event.message.answer(
        "👋 Привет! Я бот для ведения дневника боли.\n"
        "Отправьте /help, чтобы узнать, что я умею."
    )

# Обработчик команды /help
@dp.message_created(Command('help'))
async def cmd_help(event: MessageCreated):
    """Справка по командам."""
    await event.message.answer(
        "📋 Доступные команды:\n"
        "/start - Начать работу\n"
        "/help - Показать эту справку\n\n"
        "🛠 Скоро здесь появятся команды для ведения дневника!"
    )

# --- 3. Запуск бота ---

async def main():
    """Главная функция для запуска бота через Webhook."""
    # Важно: удаляем предыдущие настройки вебхука, если они были
    await bot.delete_webhook()
    
    # Запускаем веб-сервер для приема сообщений от MAX
    # Bothost автоматически предоставит публичный URL и SSL-сертификат[reference:7]
    await dp.handle_webhook(
        bot=bot,
        host='0.0.0.0',  # Слушаем все интерфейсы
        port=int(os.getenv("PORT", 8080)),  # Порт, который будет использовать Bothost
        log_level='info'
    )

if __name__ == '__main__':
    asyncio.run(main())