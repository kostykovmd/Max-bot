from flask import Flask, request, jsonify
import httpx
import os

TOKEN = os.getenv("MAX_TOKEN")
BASE_URL = f"https://api.max.ru/bot{TOKEN}"

app = Flask(__name__)

def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    try:
        httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print("Ошибка отправки:", e)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False}), 400

    if 'message' in data:
        msg = data['message']
        chat_id = msg['chat']['id']
        text = msg.get('text', '')

        if text == '/start':
            reply = "👋 Привет! Я простой бот для MAX. Отправь /help."
        elif text == '/help':
            reply = "Доступные команды: /start, /help"
        else:
            reply = f"Вы написали: {text}"

        send_message(chat_id, reply)

    return jsonify({"ok": True})

@app.route('/')
def index():
    return "Бот работает"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)