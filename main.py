import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from supabase import create_client, Client
from aiohttp import web

# Загрузка переменных окружения
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 8080))

# Инициализация клиентов
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния FSM для создания проекта
class ProjectStates(StatesGroup):
    waiting_for_name = State()

# ─────────────────────────────────────────────────────────
# 🔥 БЛОК 1: ФУНКЦИИ РАБОТЫ С БАЗОЙ ДАННЫХ (SUPABASE)
# ─────────────────────────────────────────────────────────

def get_user_projects(user_id: int):
    """Получить список проектов пользователя"""
    res = supabase.table("projects").select("*").eq("user_id", str(user_id)).execute()
    return res.data

def create_project(user_id: int, project_name: str):
    """Создать проект и наполнить его базовыми файлами Android Studio"""
    # 1. Создаем сам проект
    proj_res = supabase.table("projects").insert({
        "user_id": str(user_id), 
        "name": project_name
    }).execute()
    
    if not proj_res.data:
        return None
        
    project_id = proj_res.data[0]["id"]

    # 2. Генерируем дефолтный код для Android-файлов
    manifest_code = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
        f'    package="com.example.{project_name.lower()}">\n'
        '    <application android:label="AppName">\n'
        '    </application>\n'
        '</manifest>'
    )
    
    java_code = (
        f"package com.example.{project_name.lower()};\n\n"
        "import android.os.Bundle;\n"
        "import android.app.Activity;\n\n"
        "public class MainActivity extends Activity {\n"
        "    @Override\n"
        "    protected void onCreate(Bundle savedInstanceState) {\n"
        "        super.onCreate(savedInstanceState);\n"
        "        // Твой код начнется здесь\n"
        "    }\n"
        "}"
    )

    # 3. Заливаем файлы в таблицу
    supabase.table("files").insert([
        {"project_id": project_id, "name": "AndroidManifest.xml", "content": manifest_code},
        {"project_id": project_id, "name": "MainActivity.java", "content": java_code}
    ]).execute()
    
    return project_id

def get_project_files(project_id: int):
    """Получить файлы конкретного проекта"""
    res = supabase.table("files").select("*").eq("project_id", project_id).execute()
    return res.data

def get_file_content(file_id: int):
    """Получить данные конкретного файла"""
    res = supabase.table("files").select("*").eq("id", file_id).execute()
    return res.data[0] if res.data else None

# ─────────────────────────────────────────────────────────
# ⌨️ БЛОК 2: ГЕНЕРАЦИЯ КЛАВИАТУР (KEYBOARDS)
# ─────────────────────────────────────────────────────────

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📁 Мои проекты", callback_data="list_projects")
    builder.button(text="➕ Создать проект", callback_data="new_project")
    builder.adjust(1)
    return builder.as_markup()

def get_projects_keyboard(projects):
    builder = InlineKeyboardBuilder()
    for proj in projects:
        builder.button(text=f"📦 {proj['name']}", callback_data=f"open_proj_{proj['id']}")
    builder.button(text="⬅️ В главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_files_keyboard(project_id: int, files):
    builder = InlineKeyboardBuilder()
    for f in files:
        builder.button(text=f"📄 {f['name']}", callback_data=f"view_file_{f['id']}_{project_id}")
    builder.button(text="⬅️ К проектам", callback_data="list_projects")
    builder.adjust(1)
    return builder.as_markup()

def get_file_view_keyboard(file_id: int, project_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Проверить код (ИИ)", callback_data=f"ai_check_{file_id}")
    builder.button(text="🚀 Собрать APK", callback_data=f"build_apk_{project_id}")
    builder.button(text="⬅️ К файлам проекта", callback_data=f"open_proj_{project_id}")
    builder.adjust(1)
    return builder.as_markup()

# ─────────────────────────────────────────────────────────
# 📡 БЛОК 3: ХЕНДЛЕРЫ И ОБРАБОТКА КОМАНД БОТА
# ─────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\n"
        f"Добро пожаловать в мобильную среду разработки Android-приложений.\n\n"
        f"Управляй проектами с помощью меню:",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("Главное меню. Выбери действие:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "list_projects")
async def list_projects(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    projects = get_user_projects(user_id)

    if not projects:
        await callback.message.edit_text(
            "У тебя пока нет созданных проектов. Давай создадим первый!",
            reply_markup=get_main_menu()
        )
    else:
        await callback.message.edit_text("Список твоих Android-проектов:", reply_markup=get_projects_keyboard(projects))

@dp.callback_query(F.data == "new_project")
async def create_project_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название для нового Android-приложения (английскими буквами, например: MyFirstApp):")
    await state.set_state(ProjectStates.waiting_for_name)

@dp.message(ProjectStates.waiting_for_name)
async def create_project_save(message: types.Message, state: FSMContext):
    project_name = message.text.strip()
    user_id = message.from_user.id

    create_project(user_id, project_name)
    await state.clear()
    await message.answer(
        f"✅ Проект **{project_name}** успешно создан!\n"
        f"В него добавлены базовые файлы: `MainActivity.java` и `AndroidManifest.xml`.",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data.startswith("open_proj_"))
async def open_project(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    files = get_project_files(project_id)
    await callback.message.edit_text("Архитектура файлов проекта. Выберите файл для просмотра:", reply_markup=get_files_keyboard(project_id, files))

@dp.callback_query(F.data.startswith("view_file_"))
async def view_file(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    file_id = int(data_parts[2])
    project_id = int(data_parts[3])
    
    file_data = get_file_content(file_id)
    if not file_data:
        await callback.answer("Файл не найден!", show_alert=True)
        return

    text = f"📄 **Файл:** `{file_data['name']}`\n────────────────────\n```java\n{file_data['content']}\n```"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_file_view_keyboard(file_id, project_id))

# --- ЗАГЛУШКИ ДЛЯ ИИ И СБОРКИ ---
@dp.callback_query(F.data.startswith("ai_check_"))
async def stub_ai_check(callback: types.CallbackQuery):
    await callback.answer("🤖 Модуль ИИ Gemini будет подключен на следующем шаге!", show_alert=True)

@dp.callback_query(F.data.startswith("build_apk_"))
async def stub_build_apk(callback: types.CallbackQuery):
    await callback.answer("🚀 Модуль компиляции APK через GitHub Actions будет подключен на следующем шаге!", show_alert=True)


# ─────────────────────────────────────────────────────────
# 🌍 БЛОК 4: ВЕБ-СЕРВЕР И ГЛАВНЫЙ ЗАПУСК СИСТЕМЫ
# ─────────────────────────────────────────────────────────

async def handle_ping(request):
    return web.Response(text="Бот онлайн!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌍 Веб-сервер пинга запущен на порту {PORT}")

async def main():
    await start_web_server()
    print("🤖 Бот вышел в онлайн и готов к работе со встроенной БД!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
