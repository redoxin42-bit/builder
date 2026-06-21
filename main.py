import os
import io
import zipfile
import asyncio
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile, InlineKeyboardButton
from supabase import create_client, Client
from aiohttp import web
from github import Github

# 1. ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
PORT = int(os.getenv("PORT", 8080))

# 🛠 ПАРСЕР ССЫЛКИ СБОРЩИКА
raw_repo = os.getenv("GITHUB_REPO", "").strip()
raw_repo = raw_repo.replace("https://", "").replace("http://", "").replace("github.com/", "")
if raw_repo.endswith("/"):
    raw_repo = raw_repo[:-1]

GITHUB_REPO_CLEANED = raw_repo

if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, GITHUB_TOKEN, GITHUB_REPO_CLEANED]):
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Проверь ключи окружения в Environment!")
    exit(1)

# Инициализация клиентов
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
github_client = Github(GITHUB_TOKEN)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class ProjectStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_file_name = State()
    waiting_for_file_content = State()
    waiting_for_import_url = State()
    waiting_for_ai_prompt = State()
    waiting_for_manual_edit = State()

# ─────────────────────────────────────────────────────────
# 🧠 БЛОК ИИ: GOOGLE AI STUDIO (GEMINI API)
# ─────────────────────────────────────────────────────────

async def ai_java_to_kotlin(java_code: str) -> str:
    """Конвертирует Java-код в чистый Kotlin через Gemini API"""
    if not GEMINI_API_KEY:
        return "// AI_ERROR: Ключ GEMINI_API_KEY не задан в окружении"
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        "Convert the following Java Android code into fully compatible and modern Kotlin code. "
        "Return ONLY the pure Kotlin code. Do NOT wrap it in markdown formatting like ```kotlin or ```, "
        "and do NOT provide any explanations or notes.\n\n"
        f"Java Code:\n{java_code}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    return text.replace("```kotlin", "").replace("```", "").strip()
                else:
                    return f"// AI_ERROR: Gemini API returned status {resp.status}"
    except Exception as e:
        return f"// AI_ERROR: {str(e)}"

async def ai_modify_code(current_code: str, user_request: str) -> str:
    """Модифицирует существующий код по запросу пользователя"""
    if not GEMINI_API_KEY:
        return current_code
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        "You are an expert Android Developer. Modify the provided source code based strictly on the user's request. "
        "Return ONLY the updated valid code. Do NOT wrap it in markdown code blocks, do not explain changes.\n\n"
        f"User Request: {user_request}\n\n"
        f"Original Source Code:\n{current_code}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    return text.replace("```kotlin", "").replace("```", "").replace("```xml", "").strip()
    except Exception:
        pass
    return current_code

# ─────────────────────────────────────────────────────────
# 🔥 БЛОК 1: РАБОТА С БАЗОЙ ДАННЫХ (SUPABASE)
# ─────────────────────────────────────────────────────────

def get_user_projects(user_id: int):
    try:
        res = supabase.table("projects").select("*").eq("user_id", user_id).execute()
        return res.data
    except Exception:
        return []

def get_project_by_id(project_id: int):
    try:
        res = supabase.table("projects").select("*").eq("id", project_id).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None

def create_project(user_id: int, project_name: str):
    try:
        proj_res = supabase.table("projects").insert({"user_id": user_id, "name": project_name}).execute()
        if not proj_res.data:
            return None, "Ответ БД пуст."
        project_id = proj_res.data[0]["id"]

        manifest_code = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<manifest xmlns:android="[http://schemas.android.com/apk/res/android](http://schemas.android.com/apk/res/android)"\n'
            '    package="com.flare.compiler">\n'
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
        
        kotlin_code = (
            "package com.flare.compiler\n\n"
            "import android.os.Bundle\n"
            "import android.app.Activity\n"
            "import android.widget.TextView\n\n"
            "class MainActivity : Activity() {\n"
            "    override fun onCreate(savedInstanceState: Bundle?) {\n"
            "        super.onCreate(savedInstanceState)\n"
            "        val textView = TextView(this)\n"
            "        textView.text = \"Hello World from FlareBuilder Kotlin IDE!\"\n"
            "        setContentView(textView)\n"
            "    }\n"
            "}"
        )

        supabase.table("files").insert([
            {"project_id": project_id, "name": "AndroidManifest.xml", "content": manifest_code},
            {"project_id": project_id, "name": "MainActivity.kt", "content": kotlin_code}
        ]).execute()
        
        return project_id, None
    except Exception as e:
        return None, str(e)

def get_project_files(project_id: int):
    try:
        res = supabase.table("files").select("*").eq("project_id", project_id).execute()
        return res.data
    except Exception:
        return []

def update_file_content(file_id: int, content: str):
    try:
        supabase.table("files").update({"content": content}).eq("id", file_id).execute()
        return True
    except Exception:
        return False

# ─────────────────────────────────────────────────────────
# ⌨️ БЛОК 2: КЛАВИАТУРЫ И СТИЛИ КНОПОК ПО BOT API 9.4
# ─────────────────────────────────────────────────────────

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📁 Мои проекты", callback_data="list_projects"))
    builder.add(InlineKeyboardButton(text="📥 Импортировать репозиторий", callback_data="import_repo_start"))
    # Нативно зелёная кнопка благодаря обновлению Bot API 9.4 (style="success")
    builder.add(InlineKeyboardButton(text="🚀 Забилдить APK", callback_data="fast_build_select", style="success"))
    builder.adjust(1, 2)
    return builder.as_markup()

def get_project_manage_menu(project_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🏗 Архитектура папок", callback_data=f"arch_proj_{project_id}"))
    builder.add(InlineKeyboardButton(text="📄 Список файлов (Код)", callback_data=f"files_proj_{project_id}"))
    builder.add(InlineKeyboardButton(text="🚀 Собрать APK-пакет", callback_data=f"build_apk_{project_id}", style="success"))
    builder.add(InlineKeyboardButton(text="⬅️ К списку проектов", callback_data="list_projects", style="danger"))
    builder.adjust(1)
    return builder.as_markup()

def get_file_view_keyboard(file_id: int, project_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✏️ Изменить вручную", callback_data=f"edit_man_{file_id}_{project_id}", style="primary"))
    builder.add(InlineKeyboardButton(text="🤖 Оптимизировать через AI", callback_data=f"edit_ai_{file_id}_{project_id}", style="success"))
    builder.add(InlineKeyboardButton(text="⬅️ К списку файлов", callback_data=f"files_proj_{project_id}", style="danger"))
    builder.adjust(2, 1)
    return builder.as_markup()

# ─────────────────────────────────────────────────────────
# 📡 БЛОК 3: ХЕНДЛЕРЫ ЛОГИКИ И ИМПОРТА ЧЕРЕЗ ZIP
# ─────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛸 **Мобильная Среда Разработки FlareBuilder Kotlin IDE**", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "list_projects")
async def list_projects(callback: types.CallbackQuery):
    projects = get_user_projects(callback.from_user.id)
    if not projects:
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="➕ Создать проект", callback_data="new_project_start", style="success"))
        builder.add(InlineKeyboardButton(text="⬅️ Меню", callback_data="main_menu", style="danger"))
        builder.adjust(1)
        await callback.message.edit_text("У вас нет проектов.", reply_markup=builder.as_markup())
    else:
        builder = InlineKeyboardBuilder()
        for p in projects:
            builder.add(InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"manage_proj_{p['id']}"))
        builder.add(InlineKeyboardButton(text="➕ Создать проект", callback_data="new_project_start", style="success"))
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu", style="danger"))
        builder.adjust(1)
        await callback.message.edit_text("Выбери проект:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🛸 **Мобильная Среда Разработки FlareBuilder Kotlin IDE**", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "new_project_start")
async def np_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите имя нового Kotlin проекта:")
    await state.set_state(ProjectStates.waiting_for_name)

@dp.message(ProjectStates.waiting_for_name)
async def np_save(message: types.Message, state: FSMContext):
    pid, err = create_project(message.from_user.id, message.text.strip())
    await state.clear()
    if pid:
        await message.answer("✅ Проект создан успешно!", reply_markup=get_project_manage_menu(pid))
    else:
         await message.answer(f"❌ Ошибка: {err}", reply_markup=get_main_menu())

@dp.callback_query(F.data == "import_repo_start")
async def import_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📥 Отправь мне ссылку на GitHub репозиторий для импорта и полной Kotlin-модернизации:")
    await state.set_state(ProjectStates.waiting_for_import_url)

@dp.message(ProjectStates.waiting_for_import_url)
async def import_process(message: types.Message, state: FSMContext):
    url = message.text.strip()
    
    if url.endswith(".git"):
        url = url[:-4]
    if url.endswith("/"):
        url = url[:-1]
        
    cleaned_path = url.replace("https://", "").replace("http://", "").replace("[github.com/](https://github.com/)", "")
    parts = cleaned_path.split("/")
    
    if len(parts) < 2:
        await message.answer("❌ Неверный формат ссылки. Отправьте ссылку вида: `https://github.com/автор/репозиторий`", parse_mode="Markdown")
        await state.clear()
        return
        
    owner = parts[0]
    proj_name = parts[1]
    
    status_msg = await message.answer("📥 Выполняю облачный `git clone`: Подключаюсь и скачиваю файлы...")
    zip_url = f"[https://api.github.com/repos/](https://api.github.com/repos/){owner}/{proj_name}/zipball"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(zip_url) as resp:
                if resp.status != 200:
                    await status_msg.edit_text(f"❌ Ошибка загрузки ({resp.status}). Проверьте, что репозиторий открытый.")
                    await state.clear()
                    return
                zip_data = await resp.read()
                
        await status_msg.edit_text("🗂 Распаковка структуры файлов и чтение кода...")
        
        proj_res = supabase.table("projects").insert({"user_id": message.from_user.id, "name": proj_name}).execute()
        project_id = proj_res.data[0]["id"]
        
        files_to_insert = []
        
        with zipfile.ZipFile(io.BytesIO(zip_data)) as archive:
            for file_info in archive.infolist():
                if file_info.is_dir() or "/." in file_info.filename:
                    continue
                    
                if file_info.filename.endswith(('.java', '.kt', '.xml')):
                    filename = os.path.basename(file_info.filename)
                    if not filename:
                        continue
                    try:
                        content = archive.read(file_info.filename).decode('utf-8', errors='ignore')
                        files_to_insert.append({"name": filename, "content": content})
                    except Exception:
                        pass
                        
        if not files_to_insert:
            await status_msg.edit_text("❌ Внутри репозитория не найдено пригодных исходников (.java, .kt, .xml).")
            await state.clear()
            return
            
        await status_msg.edit_text("🧠 ИИ-Конвертер активирован. Перевожу Java-код на Kotlin...")
        
        for f in files_to_insert:
            name = f['name']
            content = f['content']
            
            if name.endswith(".java"):
                await status_msg.edit_text(f"🤖 ИИ адаптирует: `{name}` ➔ Kotlin...")
                content = await ai_java_to_kotlin(content)
                name = name.replace(".java", ".kt")
                
            supabase.table("files").insert({"project_id": project_id, "name": name, "content": content}).execute()
            
        await status_msg.delete()
        await message.answer(f"🚀 Проект `{proj_name}` успешно клонирован и полностью переведён на Kotlin!", reply_markup=get_project_manage_menu(project_id))
        await state.clear()
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Критический сбой импорта:\n`{str(e)}`", parse_mode="Markdown")
        await state.clear()

@dp.callback_query(F.data == "fast_build_select")
async def fbs(callback: types.CallbackQuery):
    projects = get_user_projects(callback.from_user.id)
    if not projects:
         await callback.message.edit_text("У вас нет проектов для сборки.", reply_markup=get_main_menu())
    else:
        builder = InlineKeyboardBuilder()
        for p in projects:
            builder.add(InlineKeyboardButton(text=f"🚀 Собрать {p['name']}", callback_data=f"build_apk_{p['id']}", style="success"))
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu", style="danger"))
        builder.adjust(1)
        await callback.message.edit_text("Выбери проект для мгновенного билда:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("manage_proj_"))
async def manage_proj(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[2])
    p = get_project_by_id(pid)
    await callback.message.edit_text(f"📦 Управление проектом: **{p['name']}**", reply_markup=get_project_manage_menu(pid), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("arch_proj_"))
async def arch_proj(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[2])
    p = get_project_by_id(pid)
    files = get_project_files(pid)
    
    tree = f"📦 **{p['name']}**\n ┗ 📂 app\n ┃ ┗ 📂 src/main\n ┃ ┃ ┣ 📂 kotlin/com/flare/compiler\n"
    for f in files:
        if f['name'].endswith('.kt'): 
            tree += f" ┃ ┃ ┃ ┗ 📄 {f['name']}\n"
    tree += " ┃ ┃ ┣ 📂 res (ресурсы макетов)\n"
    tree += " ┃ ┃ ┗ 📄 AndroidManifest.xml"
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_proj_{pid}", style="danger"))
    await callback.message.edit_text(f"⚙️ **Новая Архитектура Папок (Kotlin):**\n```text\n{tree}\n```", parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("files_proj_"))
async def files_proj(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[2])
    files = get_project_files(pid)
    builder = InlineKeyboardBuilder()
    for f in files:
        builder.add(InlineKeyboardButton(text=f"📄 {f['name']}", callback_data=f"vf_{f['id']}_{pid}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад в управление", callback_data=f"manage_proj_{pid}", style="danger"))
    builder.adjust(1)
    await callback.message.edit_text("Выбери файл для просмотра или редактирования:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("vf_"))
async def view_file(callback: types.CallbackQuery):
    fid = int(callback.data.split("_")[1])
    pid = int(callback.data.split("_")[2])
    res = supabase.table("files").select("*").eq("id", fid).execute()
    f_data = res.data[0]
    
    lang = "xml" if f_data['name'].endswith(".xml") else "kotlin"
    text = f"📄 **Файл:** `{f_data['name']}`\n```{lang}\n{f_data['content']}\n```"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_file_view_keyboard(fid, pid))

@dp.callback_query(F.data.startswith("edit_ai_"))
async def edit_ai_start(callback: types.CallbackQuery, state: FSMContext):
    fid = int(callback.data.split("_")[2])
    pid = int(callback.data.split("_")[3])
    await state.update_data(ai_fid=fid, ai_pid=pid)
    await callback.message.answer("🤖 **Ассистент Gemini.** Напиши текстом, что нужно изменить или добавить в этот файл:")
    await state.set_state(ProjectStates.waiting_for_ai_prompt)

@dp.message(ProjectStates.waiting_for_ai_prompt)
async def edit_ai_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    fid, pid = data['ai_fid'], data['ai_pid']
    await state.clear()
    
    status_msg = await message.answer("🧠 ИИ переписывает структуру кода...")
    res = supabase.table("files").select("*").eq("id", fid).execute()
    current_code = res.data[0]['content']
    
    updated_code = await ai_modify_code(current_code, message.text)
    update_file_content(fid, updated_code)
    
    await status_msg.delete()
    await message.answer("✨ ИИ успешно применил правки к файлу!", reply_markup=get_project_manage_menu(pid))

@dp.callback_query(F.data.startswith("edit_man_"))
async def edit_man_start(callback: types.CallbackQuery, state: FSMContext):
    fid = int(callback.data.split("_")[2])
    pid = int(callback.data.split("_")[3])
    await state.update_data(m_fid=fid, m_pid=pid)
    await callback.message.answer("✏️ Отправь мне обновленный код для этого файла целиком в одном сообщении:")
    await state.set_state(ProjectStates.waiting_for_manual_edit)

@dp.message(ProjectStates.waiting_for_manual_edit)
async def edit_man_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    fid, pid = data['m_fid'], data['m_pid']
    await state.clear()
    
    update_file_content(fid, message.text)
    await message.answer("✅ Файл сохранен!", reply_markup=get_project_manage_menu(pid))

@dp.callback_query(F.data.startswith("build_apk_"))
async def build_apk_process(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    proj = get_project_by_id(project_id)
    files = get_project_files(project_id)
    
    status_msg = await callback.message.answer("📡 Шаг 1: Подключение к компилятору GitHub...")

    try:
        repo = github_client.get_repo(GITHUB_REPO_CLEANED)
        await status_msg.edit_text("📝 Шаг 2: Синхронизация Kotlin исходников...")
        
        for f in files:
            name = f['name']
            content = f['content']
            
            if name == "AndroidManifest.xml":
                path = "app/src/main/AndroidManifest.xml"
            elif name.endswith(".kt"):
                path = f"app/src/main/kotlin/com/flare/compiler/{name}"
            else:
                path = f"app/src/main/{name}"
                
            try:
                git_file = repo.get_contents(path, ref="main")
                repo.update_file(git_file.path, f"Update {name}", content, git_file.sha, branch="main")
            except Exception:
                repo.create_file(path, f"Create {name}", content, branch="main")

        await status_msg.edit_text("🚀 Шаг 3: Запуск Gradle сборки...")
        await asyncio.sleep(5) 
        
        success_build = False
        run_id = None
        
        for _ in range(35): 
            await asyncio.sleep(10)
            try:
                runs = repo.get_workflow_runs(branch="main")
                if runs.totalCount > 0:
                    latest_run = runs[0] 
                    run_id = latest_run.id
                    if latest_run.status == "in_progress":
                        await status_msg.edit_text("⚙️ Gradle компилирует и линкует ресурсы приложения в APK...")
                    elif latest_run.status == "completed":
                        if latest_run.conclusion == "success":
                            success_build = True
                            break
                        else:
                            await status_msg.edit_text("❌ Ошибка сборки Gradle! Проверь синтаксис Kotlin кода.")
                            return
            except Exception:
                pass

        if not success_build or not run_id:
            await status_msg.edit_text("❌ Время таймаута компиляции истекло.")
            return

        await status_msg.edit_text("📥 Шаг 4: Скачивание бинарного APK артефакта...")
        
        try:
            import requests
            artifacts = repo.get_artifacts()
            apk_artifact = None
            for art in artifacts:
                if "app" in art.name.lower() or "debug" in art.name.lower(): 
                    apk_artifact = art
                    break
            
            if not apk_artifact:
                await status_msg.edit_text("❌ Файл сборки не найден на сервере артефактов.")
                return
                
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            response = requests.get(apk_artifact.archive_download_url, headers=headers)
            if response.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
                    for file_info in zip_file.infolist():
                        if file_info.filename.endswith(".apk"):
                            apk_data = zip_file.read(file_info.filename)
                            await status_msg.delete()
                            
                            input_file = BufferedInputFile(apk_data, filename=f"{proj['name']}.apk")
                            await callback.message.answer_document(
                                document=input_file,
                                caption=f"📱 **Твое Kotlin приложение успешно забилжено!**\n\n📦 Проект: `{proj['name']}`\n🔥 Устанавливай APK прямо из чата!"
                            )
                            return
            await status_msg.edit_text("❌ Не удалось извлечь APK из сборочного пакета.")
        except Exception as e_art:
            await status_msg.edit_text(f"❌ Критический сбой передачи данных: {str(e_art)}")
    except Exception as e:
        await status_msg.edit_text(f"❌ Критическая ошибка:\n`{str(e)}`")

# ─────────────────────────────────────────────────────────
# 🌍 БЛОК 4: СТАРТ ВЕБ-СЕРВЕРА КЛИЕНТА
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
    print("🤖 FlareBuilder Kotlin IDE с ИИ Gemini запущена!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
