import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# Импортируем наши собственные модули
import database as db
import keyboards as kb

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния для создания проекта
class ProjectStates(StatesGroup):
    waiting_for_name = State()

# --- ХЕНДЛЕРЫ КОМАНД ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Стартовая команда /start"""
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\n"
        f"Добро пожаловать в мобильную среду разработки Android-приложений.\n\n"
        f"Управляй своими проектами с помощью inline-меню ниже:",
        reply_markup=kb.get_main_menu()
    )

# --- ОБРАБОТКА ИНЛАЙН КНОПОК ---

@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    await callback.message.edit_text(
        "Главное меню. Выбери действие:",
        reply_markup=kb.get_main_menu()
    )

@dp.callback_query(F.data == "list_projects")
async def list_projects(callback: types.CallbackQuery):
    """Вывод списка проектов пользователя"""
    user_id = callback.from_user.id
    projects = db.get_user_projects(user_id)

    if not projects:
        await callback.message.edit_text(
            "У тебя пока нет созданных проектов. Давай создадим первый!",
            reply_markup=kb.get_main_menu()
        )
    else:
        await callback.message.edit_text(
            "Список твоих Android-проектов:",
            reply_markup=kb.get_projects_keyboard(projects)
        )

@dp.callback_query(F.data == "new_project")
async def create_project_start(callback: types.CallbackQuery, state: FSMContext):
    """Кнопка 'Создать проект' -> Включение FSM"""
    await callback.message.edit_text(
        "Введите название для нового Android-приложения (английскими буквами, например: MegaApp):"
    )
    await state.set_state(ProjectStates.waiting_for_name)

@dp.message(ProjectStates.waiting_for_name)
async def create_project_save(message: types.Message, state: FSMContext):
    """Получение имени проекта и сохранение в БД вместе с дефолтными файлами"""
    project_name = message.text.strip()
    user_id = message.from_user.id

    # Создаем проект и структуру через модуль database
    db.create_project(user_id, project_name)

    await state.clear()
    await message.answer(
        f"✅ Проект **{project_name}** успешно создан!\n"
        f"В него автоматически добавлены базовые файлы Android Studio (`MainActivity.java`, `AndroidManifest.xml`).",
        reply_markup=kb.get_main_menu()
    )

@dp.callback_query(F.data.startswith("open_proj_"))
async def open_project(callback: types.CallbackQuery):
    """Открытие архитектуры файлов внутри проекта"""
    project_id = int(callback.data.split("_")[2])
    files = db.get_project_files(project_id)

    await callback.message.edit_text(
        "Архитектура файлов проекта. Нажми на файл для просмотра кода:",
        reply_markup=kb.get_files_keyboard(project_id, files)
    )

@dp.callback_query(F.data.startswith("view_file_"))
async def view_file(callback: types.CallbackQuery):
    """Просмотр содержимого конкретного файла"""
    file_id = int(callback.data.split("_")[2])
    file_data = db.get_file_content(file_id)

    if not file_data:
        await callback.answer("Файл не найден!", show_alert=True)
        return

    # Красиво форматируем код под Markdown
    text = (
        f"📄 **Файл:** `{file_data['name']}`\n"
        f"────────────────────\n"
        f"```java\n{file_data['content']}\n```"
    )
    
    await callback.message.edit_text(
        text, 
        parse_mode="Markdown", 
        reply_markup=kb.get_file_view_keyboard(file_id, file_data['project_id'])
    )

# --- ЗАГЛУШКИ ДЛЯ БУДУЩИХ МОДУЛЕЙ ---

@dp.callback_query(F.data.startswith("ai_check_"))
async def stub_ai_check(callback: types.CallbackQuery):
    """Заглушка для ИИ проверки кода"""
    await callback.answer("🤖 Модуль ИИ Gemini будет подключен на следующем этапе!", show_alert=True)

@dp.callback_query(F.data.startswith("build_apk_"))
async def stub_build_apk(callback: types.CallbackQuery):
    """Заглушка для компиляции через GitHub Actions"""
    await callback.answer("🚀 Модуль сборки через GitHub Actions будет подключен на следующем этапе!", show_alert=True)

# --- ФЕЙКОВЫЙ СЕРВЕР ДЛЯ ОБХОДА ПРОВЕРКИ ПОРТА RENDER ---
async def handle_render_ping(reader, writer):
    """Отвечает Render'у, что наше приложение живое"""
    await reader.read(100)
    response = "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"
    writer.write(response.encode())
    await writer.drain()
    writer.close()

# --- ЗАПУСК БОТА ---
async def main():
    # Поднимаем пустой порт для Render, чтобы он успокоился
    port = int(os.getenv("PORT", 8080))
    await asyncio.start_server(handle_render_ping, "0.0.0.0", port)
    
    print("Бот успешно запущен на раздельной архитектуре!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
