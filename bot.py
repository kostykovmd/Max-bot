import asyncio
import httpx
import logging

# --- НАСТРОЙКИ ---
MAX_TOKEN = "f9LHodD0cOK1xZkq6p6SokUPknfyqD-0IcgoK8Mq2kk6VoH3Y2hxL88YVygiZlcuYuzziMciAQh5uRIvq9kw"  # <-- ВСТАВЬТЕ СЮДА ВАШ ТОКЕН
BASE_URL = f"https://platform-api2.max.ru/bot{MAX_TOKEN}"
# -----------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_message(chat_id, text):
    """Отправляет текстовое сообщение пользователю."""
    url = f"{BASE_URL}/sendMessage"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

async def handle_update(update):
    """Обрабатывает входящее обновление (сообщение)."""
    if 'message' in update:
        msg = update['message']
        chat_id = msg['chat']['id']
        text = msg.get('text', '').strip()

        if text == '/start':
            reply = "👋 Привет! Я бот для МАКС. Отправь /help."
        elif text == '/help':
            reply = "Доступные команды: /start, /help"
        elif text:
            reply = f"Вы написали: {text}"
        else:
            reply = "Я понимаю только текстовые сообщения."

        await send_message(chat_id, reply)

async def main():
    """Главный цикл бота (Long Polling)."""
    logger.info("🚀 Бот запущен в режиме Long Polling")
    marker = None  # Переменная для отслеживания последнего обработанного события[reference:7]
    while True:
        url = f"{BASE_URL}/getUpdates"
        params = {"timeout": 30, "marker": marker} if marker else {"timeout": 30} # Используем marker[reference:8]
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    updates = data.get("updates", []) # В ответе приходит поле "updates"[reference:9]
                    if updates:
                        marker = data.get("marker") # Сохраняем marker для следующего запроса[reference:10]
                        for update in updates:
                            await handle_update(update)
                else:
                    logger.error(f"Ошибка getUpdates: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Ошибка соединения: {e}")
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())