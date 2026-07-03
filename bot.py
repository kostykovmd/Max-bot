import asyncio
import httpx
import os
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("MAX_TOKEN")
if not TOKEN:
    logger.error("MAX_TOKEN не задан!")
    sys.exit(1)

BASE_URL = f"https://platform-api2.max.ru/bot{TOKEN}"

async def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

async def handle_update(update):
    if 'message' in update:
        msg = update['message']
        chat_id = msg['chat']['id']
        text = msg.get('text', '').strip()
        if text == '/start':
            reply = "👋 Привет! Я бот для MAX. Отправь /help."
        elif text == '/help':
            reply = "Доступные команды: /start, /help"
        elif text:
            reply = f"Вы написали: {text}"
        else:
            reply = "Я понимаю только текстовые сообщения."
        await send_message(chat_id, reply)

async def main():
    logger.info("🚀 Бот запущен в режиме polling")
    offset = None
    while True:
        url = f"{BASE_URL}/getUpdates"
        params = {"timeout": 30, "offset": offset} if offset else {"timeout": 30}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        await handle_update(update)
                else:
                    logger.error(f"Ошибка getUpdates: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Ошибка соединения: {e}")
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())