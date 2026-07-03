import asyncio
import json
import os
import httpx

TOKEN = os.getenv("MAX_TOKEN", "f9LHodD0cOJQLGdPclFfUG2JCEjydpFl3UxgbliXV0BRGMubyg0_WmGEfDxLw0PgclvPI_Hh5ubrgXX2PjcD")
BASE_URL = f"https://api.max.ru/bot{TOKEN}"

async def get_updates(offset=None):
    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 30, "offset": offset} if offset else {"timeout": 30}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("result", [])
            else:
                print(f"Ошибка getUpdates: {resp.status_code} - {resp.text}")
                return []
        except Exception as e:
            print(f"Ошибка соединения: {e}")
            return []

async def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=30)
        except Exception as e:
            print(f"Ошибка отправки: {e}")

async def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    
    if text.startswith("/start"):
        await send_message(chat_id, 
            "👋 Привет! Я бот для помощи с хронической болью.\n"
            "Отправьте /help для списка команд."
        )
    elif text.startswith("/help"):
        await send_message(chat_id,
            "📋 Доступные команды:\n"
            "/start — начать\n"
            "/help — справка\n"
            "/today — записать сегодняшнюю боль (пока заглушка)"
        )
    elif text.startswith("/today"):
        await send_message(chat_id,
            "📝 Функция записи боли появится позже.\n"
            "А пока просто напишите мне что-нибудь, и я отвечу."
        )
    else:
        await send_message(chat_id, 
            f"Вы написали: «{text}»\n\n"
            "Скоро я научусь вести дневник боли и давать рекомендации."
        )

async def main():
    print("🚀 Бот запущен. Ожидаю сообщения...")
    offset = None
    while True:
        updates = await get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            if "message" in update:
                await handle_message(update["message"])
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
