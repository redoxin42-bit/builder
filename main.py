import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from supabase import create_client, Client
from aiohttp import web

# Автоматически загружаем переменные из файла .env, если он есть рядом
load_dotenv()

# Вытягиваем настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 10000))  # Render сам передает порт, локально будет 10000

# Проверяем, что всё загрузилось
if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ Ошибка: Не все переменные окружения найдены в .env или системе!")
    exit(1)

# Инициализируем базу данных и телеграм-бота
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Твой обработчик команд (сюда потом допишем остальную логику)
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🚀 Привет! Бот успешно запущен из единого репозитория и готов к работе!")

# --- ФЕЙКОВЫЙ СЕРВЕР ДЛЯ ОБХОДА БЛОКИРОВКИ RENDER ---
async def handle_ping(request):
    return web.Response(text="Бот живой и не спит!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌍 Фейковый веб-сервер успешно поднят на порту {PORT}")

# --- ГЛАВНЫЙ ЗАПУСК ---
async def main():
    # 1. Запускаем веб-сервер в фоне, чтобы Render был доволен
    await start_web_server()
    
    # 2. Включаем постоянный опрос Телеграма
    print("🤖 Бот вышел в онлайн и слушает команды...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
