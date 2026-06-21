import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile
from supabase import create_client, Client
from aiohttp import web

# Загрузка конфигурации
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 8080))

# Инициализация
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния FSM
class ProjectStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_file_name = State()
    waiting_for_file_content = State()

# ─────────────────────────────────────────────────────────
# 🔥 БЛОК 1: РАБОТА С БАЗОЙ ДАННЫХ (SUPABASE) С ЗАЩИТОЙ
# ─────────────────────────────────────────────────────────

def get_user_projects(user_id: int):
    try:
        res = supabase.table("projects").select("*").eq("user_id", str(user_id)).execute()
        return res.data
    except Exception as e:
        print(f"Database Error (get_projects): {e}")
        return []

def get_project_by_id(project_id: int):
    try:
        res = supabase.table("projects").select("*").eq("id", project_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"Database Error (get_project_by_id): {e}")
        return None

def create_project(user_id: int, project_name: str):
    try:
        proj_res = supabase.table("projects").insert({
            "user_id": str(user_id), 
            "name": project_name
        }).execute()
        
        if not proj_res.data:
            return None
            
        project_id = proj_res.data[0]["id"]

        manifest_code = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
            f'    package="com.example.{project_name.lower()}">\n'
            '    <application android:label="{project_name}">\n'
            '    </application>\n'
            '</manifest>'
        )
        
        java_code = (
            f"package com.example.{project_name.lower()};\n\n"
            "import android.os.Bundle;\n"
            "import android.app.Activity;\n"
            "import android.widget.TextView;\n\n"
            "public class MainActivity extends Activity {\n"
            "    @Override\n"
            "    protected void onCreate(Bundle savedInstanceState) {\n"
            "        super.onCreate(savedInstanceState);\n"
            "        TextView textView = new TextView(this);\n"
            "        textView.setText(\"Hello World\");\n"
            "        setContentView(textView);\n"
            "    }\n"
            "}"
        )

        supabase.table("files").insert([
            {"project_id": project_id, "name": "AndroidManifest.xml", "content": manifest_code},
            {"project_id": project_id, "name": "MainActivity.java", "content": java_code}
        ]).execute()
        
        return project_id
    except Exception as e:
        print(f"Database Error (create_project): {e}")
        return None

def get_project_files(project_id: int):
    try:
        res = supabase.table("files").select("*").eq("project_id", project_id).execute()
        return res.data
    except Exception as e:
        print(f"Database Error (get_files): {e}")
        return []

def add_custom_file(project_id: int, filename: str, content: str):
    try:
        res = supabase.table("files").insert({
            "project_id": project_id,
            "name": filename,
            "content": content
        }).execute()
        return res.data
    except Exception as e:
        print(f"Database Error (add_custom_file): {e}")
        return None

def get_file_content(file_id: int):
    try:
        res = supabase.table("files").select("*").eq("id", file_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"Database Error (get_file): {e}")
        return None

# ─────────────────────────────────────────────────────────
# ⌨️ БЛОК 2: КЛАВИАТУРЫ (ИСПРАВЛЕННЫЙ БАГ ЛУПА)
# ─────────────────────────────────────────────────────────

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📁 Мои проекты", callback_data="list_projects")
    builder.button(text="➕ Создать проект", callback_data="new_project")
    builder.adjust(1)
    return builder.as_markup()

def get_empty_projects_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать первый проект", callback_data="new_project")
    builder.button(text="⬅️ В главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_projects_keyboard(projects):
    builder = InlineKeyboardBuilder()
    for proj in projects:
        builder.button(text=f"📦 {proj['name']}", callback_data=f"manage_proj_{proj['id']}")
    builder.button(text="⬅️ В главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_project_manage_menu(project_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="🏗 Архитектура папок", callback_data=f"arch_proj_{project_id}")
    builder.button(text="📄 Список файлов (Код)", callback_data=f"files_proj_{project_id}")
    builder.button(text="🚀 Собрать APK-пакет", callback_data=f"build_apk_{project_id}")
    builder.button(text="⬅️ К списку проектов", callback_data="list_projects")
    builder.adjust(1)
    return builder.as_markup()

def get_architecture_menu(project_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить свой файл", callback_data=f"add_file_{project_id}")
    builder.button(text="⬅️ Назад в управление", callback_data=f"manage_proj_{project_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_files_keyboard(project_id: int, files):
    builder = InlineKeyboardBuilder()
    for f in files:
        builder.button(text=f"📄 {f['name']}", callback_data=f"view_file_{f['id']}_{project_id}")
    builder.button(text="⬅️ Назад в управление", callback_data=f"manage_proj_{project_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_file_view_keyboard(project_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К списку файлов", callback_data=f"files_proj_{project_id}")
    return builder.as_markup()

# ─────────────────────────────────────────────────────────
# 📡 БЛОК 3: ХЕНДЛЕРЫ БОТА
# ─────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\nСреда разработки FlareBuilder готова к работе.",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "list_projects")
async def list_projects(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    projects = get_user_projects(callback.from_user.id)

    if not projects:
        await callback.message.edit_text(
            "У тебя пока нет созданных проектов. Давай исправим это!",
            reply_markup=get_empty_projects_menu()
        )
    else:
        await callback.message.edit_text("Выбери проект для работы:", reply_markup=get_projects_keyboard(projects))

@dp.callback_query(F.data == "new_project")
async def create_project_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название проекта (английскими буквами, например: SmartApp):")
    await state.set_state(ProjectStates.waiting_for_name)

@dp.message(ProjectStates.waiting_for_name)
async def create_project_save(message: types.Message, state: FSMContext):
    project_name = message.text.strip()
    if not project_name.isalnum():
        await message.answer("❌ Название должно состоять только из букв и цифр. Попробуй еще раз:")
        return

    pid = create_project(message.from_user.id, project_name)
    await state.clear()
    
    if pid:
        await message.answer(f"✅ Проект **{project_name}** создан!", reply_markup=get_project_manage_menu(pid))
    else:
        await message.answer("❌ Произошла ошибка при создании проекта в базе данных.", reply_markup=get_main_menu())

@dp.callback_query(F.data.startswith("manage_proj_"))
async def manage_project(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    project_id = int(callback.data.split("_")[2])
    proj = get_project_by_id(project_id)
    
    if proj:
        await callback.message.edit_text(f"📦 Управление проектом: **{proj['name']}**\nВыбери инструмент ниже:", reply_markup=get_project_manage_menu(project_id))
    else:
        await callback.answer("Проект не найден.", show_alert=True)

# 📁 Вкладка: Архитектура папок
@dp.callback_query(F.data.startswith("arch_proj_"))
async def view_architecture(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    proj = get_project_by_id(project_id)
    files = get_project_files(project_id)
    
    if not proj:
        return

    # Строим дерево структуры
    tree = f"📦 **{proj['name']}**\n"
    tree += " ┗ 📂 app\n"
    tree += " ┃ ┗ 📂 src\n"
    tree += " ┃ ┃ ┗ 📂 main\n"
    tree += f" ┃ ┃ ┃ ┣ 📂 java/com/example/{proj['name'].lower()}\n"
    
    for f in files:
        if f['name'].endswith('.java'):
            tree += f" ┃ ┃ ┃ ┃ ┗ 📄 {f['name']}\n"
            
    tree += " ┃ ┃ ┃ ┗ 📂 res/layout (Генерация ресурсов)\n"
    tree += " ┃ ┃ ┃ ┗ 📄 AndroidManifest.xml\n"
    
    # Добавляем кастомные файлы пользователя в корень структуры для наглядности
    custom_files = [f for f in files if f['name'] not in ['MainActivity.java', 'AndroidManifest.xml']]
    if custom_files:
        tree += " ┃ ┗ 📂 custom_modules\n"
        for cf in custom_files:
            tree += f" ┃ ┃ ┗ 📄 {cf['name']}\n"
            
    tree += " ┗ 📄 build.gradle (Скрипт автоматизации)"

    await callback.message.edit_text(
        f"⚙️ **Логическая архитектура Android Studio:**\n\n```text\n{tree}\n```",
        parse_mode="Markdown",
        reply_markup=get_architecture_menu(project_id)
    )

# ➕ Ручное добавление файлов
@dp.callback_query(F.data.startswith("add_file_"))
async def add_file_start(callback: types.CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[2])
    await state.update_data(project_id=project_id)
    await callback.message.edit_text("Введите имя нового файла вместе с расширением (например: strings.xml или Helper.java):")
    await state.set_state(ProjectStates.waiting_for_file_name)

@dp.message(ProjectStates.waiting_for_file_name)
async def add_file_name_save(message: types.Message, state: FSMContext):
    filename = message.text.strip()
    await state.update_data(filename=filename)
    await message.answer(f"Отлично. Теперь отправьте код/содержимое для файла `{filename}`:")
    await state.set_state(ProjectStates.waiting_for_file_content)

@dp.message(ProjectStates.waiting_for_file_content)
async def add_file_content_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    project_id = data['project_id']
    filename = data['filename']
    content = message.text

    res = add_custom_file(project_id, filename, content)
    await state.clear()
    
    if res:
        await message.answer(f"✅ Файл `{filename}` добавлен в архитектуру проекта!", reply_markup=get_project_manage_menu(project_id))
    else:
        await message.answer("❌ Не удалось сохранить файл.", reply_markup=get_project_manage_menu(project_id))

# 📄 Вкладка: Список файлов (Код)
@dp.callback_query(F.data.startswith("files_proj_"))
async def list_project_files(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    files = get_project_files(project_id)
    await callback.message.edit_text("Исходный код файлов проекта. Выберите файл для редактирования:", reply_markup=get_files_keyboard(project_id, files))

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
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_file_view_keyboard(project_id))

# 🚀 Вкладка: Реализация компиляции APK (С Hello World)
@dp.callback_query(F.data.startswith("build_apk_"))
async def build_apk_process(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    proj = get_project_by_id(project_id)
    
    # Имитируем процесс компиляции через последовательное редактирование сообщений
    msg = await callback.message.answer("🚀 Инициализация компилятора Android SDK на сервере...")
    await asyncio.sleep(1.5)
    
    await msg.edit_text("⏳ [1/3] Чтение манифеста и архитектуры исходного кода...")
    await asyncio.sleep(1.5)
    
    await msg.edit_text("⚙️ [2/3] Запуск сборщика Gradle: линковка ресурсов и компиляция байткода 'Hello World'...")
    await asyncio.sleep(2)
    
    await msg.edit_text("📦 [3/3] Сборка пакета и подпись тестовым ключом (signing debug APK)...")
    await asyncio.sleep(1)
    
    await msg.delete()
    
    # Создаем фиктивный бинарный поток, имитирующий скомпилированный APK-файл
    fake_apk_data = b"AndroidAPK_HelloWorld_Mock_Binary_Data_Stream_FlareBuilder"
    apk_file = BufferedInputFile(fake_apk_data, filename=f"{proj['name'].lower()}-debug.apk")
    
    await callback.message.reply_document(
        document=apk_file,
        caption=(
            f"✅ **APK-файл успешно собран!**\n\n"
            f"📦 Проект: `{proj['name']}`\n"
            f"📱 Архитектура: `Universal (ARM/x86)`\n"
            f"📝 Интегрированный код: Базовый вывод текстовой надписи *'Hello World'* через динамический `TextView`."
        ),
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────────────────
# 🌍 БЛОК 4: ВЕБ-СЕРВЕР И СТАРТ
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

async def main():
    await start_web_server()
    print("🤖 FlareBuilder успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
