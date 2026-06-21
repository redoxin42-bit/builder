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
from github import Github  # Библиотека для работы с GitHub API

# 1. ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PORT = int(os.getenv("PORT", 8080))

# 🛠 БРОНЕБОЙНЫЙ ПАРСЕР ССЫЛКИ РЕПОЗИТОРИЯ
# Вырезает "логин/репозиторий" из абсолютно любого формата, введенного на Render
raw_repo = os.getenv("GITHUB_REPO", "").strip()
raw_repo = raw_repo.replace("https://", "").replace("http://", "").replace("github.com/", "")
if raw_repo.endswith("/"):
    raw_repo = raw_repo[:-1]

GITHUB_REPO_CLEANED = raw_repo

# Проверка критических данных
if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, GITHUB_TOKEN, GITHUB_REPO_CLEANED]):
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Проверь ключи Supabase и GitHub в Environment!")
    exit(1)

# Инициализация клиентов
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
github_client = Github(GITHUB_TOKEN)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния FSM для пошагового ввода данных
class ProjectStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_file_name = State()
    waiting_for_file_content = State()

# ─────────────────────────────────────────────────────────
# 🔥 БЛОК 1: РАБОТА С БАЗОЙ ДАННЫХ (SUPABASE)
# ─────────────────────────────────────────────────────────

def get_user_projects(user_id: int):
    try:
        res = supabase.table("projects").select("*").eq("user_id", user_id).execute()
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
            "user_id": user_id, 
            "name": project_name
        }).execute()
        
        if not proj_res.data:
            return None, "БД вернула пустой ответ."
            
        project_id = proj_res.data[0]["id"]

        manifest_code = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
            f'    package="com.flare.compiler">\n'
            '    <application android:label="FlareApp">\n'
            '        <activity android:name=".MainActivity" android:exported="true">\n'
            '            <intent-filter>\n'
            '                <action android:name="android.intent.action.MAIN" />\n'
            '                <category android:name="android.intent.category.LAUNCHER" />\n'
            '            </intent-filter>\n'
            '        </activity>\n'
            '    </application>\n'
            '</manifest>'
        )
        
        java_code = (
            "package com.flare.compiler;\n\n"
            "import android.os.Bundle;\n"
            "import android.app.Activity;\n"
            "import android.widget.TextView;\n\n"
            "public class MainActivity extends Activity {\n"
            "    @Override\n"
            "    protected void onCreate(Bundle savedInstanceState) {\n"
            "        super.onCreate(savedInstanceState);\n"
            "        TextView textView = new TextView(this);\n"
            "        textView.setText(\"Hello World from FlareBuilder!\");\n"
            "        setContentView(textView);\n"
            "    }\n"
            "}"
        )

        supabase.table("files").insert([
            {"project_id": project_id, "name": "AndroidManifest.xml", "content": manifest_code},
            {"project_id": project_id, "name": "MainActivity.java", "content": java_code}
        ]).execute()
        
        return project_id, None
    except Exception as e:
        print(f"Database Error (create_project): {e}")
        return None, str(e)

def get_project_files(project_id: int):
    try:
        res = supabase.table("files").select("*").eq("project_id", project_id).execute()
        return res.data
    except Exception as e:
        print(f"Database Error (get_files): {e}")
        return []

def get_file_content(file_id: int):
    try:
        res = supabase.table("files").select("*").eq("id", file_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"Database Error (get_file): {e}")
        return None

# ─────────────────────────────────────────────────────────
# ⌨️ БЛОК 2: ГЕНЕРАЦИЯ ИНТЕРФЕЙСА (КЛАВИАТУРЫ)
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
# 📡 БЛОК 3: ХЕНДЛЕРЫ И СБОРКА APK С ДИАГНОСТИКОЙ И ОБТЕКАНИЕМ ОШИБОК
# ─────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\nСреда разработки FlareBuilder подключена к компилятору.",
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
        await callback.message.edit_text("У тебя пока нет созданных проектов.", reply_markup=get_empty_projects_menu())
    else:
        await callback.message.edit_text("Выбери проект для работы:", reply_markup=get_projects_keyboard(projects))

@dp.callback_query(F.data == "new_project")
async def create_project_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название проекта (английскими буквами):")
    await state.set_state(ProjectStates.waiting_for_name)

@dp.message(ProjectStates.waiting_for_name)
async def create_project_save(message: types.Message, state: FSMContext):
    project_name = message.text.strip()
    if not project_name.isalnum():
        await message.answer("❌ Название должно состоять только из букв и цифр:")
        return

    pid, err_msg = create_project(message.from_user.id, project_name)
    await state.clear()
    
    if pid:
        await message.answer(f"✅ Проект **{project_name}** успешно создан!", reply_markup=get_project_manage_menu(pid))
    else:
        await message.answer(f"❌ Ошибка базы данных:\n`{err_msg}`", reply_markup=get_main_menu())

@dp.callback_query(F.data.startswith("manage_proj_"))
async def manage_project(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    project_id = int(callback.data.split("_")[2])
    proj = get_project_by_id(project_id)
    if proj:
        await callback.message.edit_text(f"📦 Управление проектом: **{proj['name']}**", reply_markup=get_project_manage_menu(project_id))

@dp.callback_query(F.data.startswith("arch_proj_"))
async def view_architecture(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    proj = get_project_by_id(project_id)
    files = get_project_files(project_id)
    
    tree = f"📦 **{proj['name']}**\n ┗ 📂 app\n ┃ ┗ 📂 src/main\n ┃ ┃ ┣ 📂 java/com/flare/compiler\n"
    for f in files:
        if f['name'].endswith('.java'): tree += f" ┃ ┃ ┃ ┗ 📄 {f['name']}\n"
    tree += " ┃ ┃ ┗ 📄 AndroidManifest.xml"

    await callback.message.edit_text(f"⚙️ **Архитектура проекта:**\n```text\n{tree}\n```", parse_mode="Markdown", reply_markup=get_architecture_menu(project_id))

@dp.callback_query(F.data.startswith("files_proj_"))
async def list_project_files(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    files = get_project_files(project_id)
    await callback.message.edit_text("Выберите файл проекта для чтения кода:", reply_markup=get_files_keyboard(project_id, files))

@dp.callback_query(F.data.startswith("view_file_"))
async def view_file(callback: types.CallbackQuery):
    file_id = int(callback.data.split("_")[2])
    project_id = int(callback.data.split("_")[3])
    file_data = get_file_content(file_id)
    text = f"📄 **Файл:** `{file_data['name']}`\n```java\n{file_data['content']}\n```"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_file_view_keyboard(project_id))

# ХЕНДЛЕР СБОРКИ С УЛУЧШЕННОЙ ОБРАБОТКОЙ ОШИБОК И ФОРМАТОВ ССЫЛОК
@dp.callback_query(F.data.startswith("build_apk_"))
async def build_apk_process(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    proj = get_project_by_id(project_id)
    files = get_project_files(project_id)
    
    status_msg = await callback.message.answer("📡 Шаг 1: Подключение к GitHub Actions...")

    try:
        manifest_content = next((f['content'] for f in files if f['name'] == "AndroidManifest.xml"), None)
        java_content = next((f['content'] for f in files if f['name'] == "MainActivity.java"), None)

        if not manifest_content or not java_content:
            await status_msg.edit_text("❌ Ошибка: В базе Supabase нет базовых файлов кода.")
            return

        # ЭТАП 1: ПОЛУЧЕНИЕ РЕПОЗИТОРИЯ
        try:
            repo = github_client.get_repo(GITHUB_REPO_CLEANED)
        except Exception as e_repo:
            await status_msg.edit_text(
                f"❌ Ошибка на этапе поиска репозитория `{GITHUB_REPO_CLEANED}`:\n`{str(e_repo)}` \n\n"
                f"Проверь настройки твоего Personal Access Token на GitHub! Если это Fine-grained токен, "
                f"убедись, что в пункте Repository Access выбран именно этот репозиторий."
            )
            return

        await status_msg.edit_text("📝 Шаг 2: Загрузка Манифеста на GitHub...")
        
        # ЭТАП 2: МАНИФЕСТ
        try:
            manifest_file = repo.get_contents("app/src/main/AndroidManifest.xml", ref="main")
            repo.update_file(manifest_file.path, "Update Manifest from Bot", manifest_content, manifest_file.sha, branch="main")
        except Exception:
            try:
                repo.create_file("app/src/main/AndroidManifest.xml", "Create Manifest from Bot", manifest_content, branch="main")
            except Exception as e_man:
                await status_msg.edit_text(f"❌ Не удалось записать AndroidManifest.xml:\n`{str(e_man)}`")
                return

        await status_msg.edit_text("📝 Шаг 3: Загрузка Java кода на GitHub...")

        # ЭТАП 3: JAVA ФАЙЛ
        try:
            java_file = repo.get_contents("app/src/main/java/com/flare/compiler/MainActivity.java", ref="main")
            repo.update_file(java_file.path, "Update Java Code from Bot", java_content, java_file.sha, branch="main")
        except Exception:
            try:
                repo.create_file("app/src/main/java/com/flare/compiler/MainActivity.java", "Create Java Code from Bot", java_content, branch="main")
            except Exception as e_jav:
                await status_msg.edit_text(f"❌ Не удалось записать MainActivity.java:\n`{str(e_jav)}`")
                return

        await status_msg.edit_text("🚀 Шаг 4: Запуск Gradle сборки...")
        await asyncio.sleep(6) 
        
        success_build = False
        run_id = None
        
        for _ in range(35): 
            await asyncio.sleep(10)
            try:
                runs = repo.get_workflow_runs(branch="main")
                if runs.totalCount > 0:
                    latest_run = runs[0] 
                    run_id = latest_run.id
                    status = latest_run.status       
                    conclusion = latest_run.conclusion 
                    
                    if status == "in_progress":
                        await status_msg.edit_text("⚙️ Gradle компилирует приложение в облаке...")
                    elif status == "completed":
                        if conclusion == "success":
                            success_build = True
                            break
                        else:
                            await status_msg.edit_text("❌ Ошибка компиляции Gradle на GitHub Actions!")
                            return
            except Exception:
                pass

        if not success_build or not run_id:
            await status_msg.edit_text("❌ Время ожидания сборки истекло.")
            return

        await status_msg.edit_text("📦 Шаг 5: Получение готового APK...")
        
        try:
            artifacts = repo.get_artifacts()
            apk_artifact = None
            for art in artifacts:
                if art.name == "app-debug": 
                    apk_artifact = art
                    break
            
            if not apk_artifact:
                await status_msg.edit_text("❌ Сборка завершена, но артефакт 'app-debug' не найден.")
                return
        except Exception as e_art:
            await status_msg.edit_text(f"❌ Ошибка получения артефактов:\n`{str(e_art)}`")
            return

        await status_msg.delete()
        
        builder = InlineKeyboardBuilder()
        builder.button(text="📥 Скачать готовый APK", url=f"https://github.com/{GITHUB_REPO_CLEANED}/actions/runs/{run_id}")
        builder.button(text="⬅️ Назад в меню", callback_data=f"manage_proj_{project_id}")
        builder.adjust(1)

        await callback.message.answer(
            f"📦 **Ваше настоящее Android-приложение успешно собрано!**\n\n"
            f"📱 Проект: `{proj['name']}`\n"
            f"GitHub заархивировал ваш `.apk`. Нажмите кнопку ниже, пролистайте страницу вниз до раздела **Artifacts** и скачайте файл `app-debug`!",
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Общая критическая ошибка:\n`{str(e)}`")

# ─────────────────────────────────────────────────────────
# 🌍 БЛОК 4: ВЕБ-СЕРВЕР И СТАРТ СИСТЕМЫ
# ─────────────────────────────────────────────────────────
async def handle_ping(request): return web.Response(text="Бот онлайн!", status=200)
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

async def main():
    await start_web_server()
    print("🤖 Среда FlareBuilder запущена!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
