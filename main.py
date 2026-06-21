import os
import io
import re
import json
import zipfile
import asyncio
import aiohttp
import subprocess
import tempfile
import shutil
import urllib.parse
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

# Сборщик чистого имени репозитория для компиляции
raw_repo = os.getenv("GITHUB_REPO", "").strip()
raw_repo = re.sub(r'^(https?://)?(www\.)?github\.com/', '', raw_repo, flags=re.IGNORECASE)
GITHUB_REPO_CLEANED = raw_repo.strip('/')

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
    waiting_for_import_url = State()
    waiting_for_ai_project_prompt = State()
    waiting_for_file_path = State()
    waiting_for_manual_edit = State()

# ─────────────────────────────────────────────────────────
# 🧠 МОЩНЫЙ БЛОК ИИ: МУЛЬТИ-ФАЙЛОВАЯ АРХИТЕКТУРА ЧЕРЕЗ JSON
# ─────────────────────────────────────────────────────────

async def ai_project_wide_develop(files_list: list, user_request: str) -> list:
    """Передаёт весь проект в Gemini и получает список новых/изменённых файлов в JSON формате"""
    if not GEMINI_API_KEY:
        return []
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    # Собираем контекст текущих файлов
    context = "Текущая структура и файлы проекта:\n"
    for f in files_list:
        context += f"--- ФАЙЛ: {f['name']} ---\n{f['content']}\n\n"
        
    prompt = (
        f"{context}\n"
        f"Задача от пользователя: {user_request}\n\n"
        "Ты — ведущий Android-разработчик. Тебе необходимо выполнить задачу пользователя. "
        "Ты можешь изменять существующие файлы или СОЗДАВАТЬ новые файлы по любым путям (если папок нет, они создадутся). "
        "Возвращай ТОЛЬКО валидный массив JSON объектов, содержащий файлы, которые нужно создать или изменить. "
        "Не измененные файлы включать в массив не нужно. Не оборачивай ответ в markdown разметку вроде ```json или ```.\n"
        "Пример формата ответа:\n"
        "[\n"
        "  {\n"
        "    \"path\": \"app/src/main/kotlin/com/flare/compiler/ui/SettingsActivity.kt\",\n"
        "    \"content\": \"package com.flare.compiler.ui\\n\\n...код...\"\n"
        "  }\n"
        "]"
    )
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw_text = data['candidates'][0]['content']['parts'][0]['text'].strip()
                    # Чистим случайные маркдаун-теги от ИИ
                    raw_text = raw_text.replace("```json", "").replace("```", "").strip()
                    return json.loads(raw_text)
    except Exception as e:
        print(f"Ошибка ИИ-архитектора: {e}")
    return []

# ─────────────────────────────────────────────────────────
# 🔥 БЛОК 1: РАБОТА С БАЗОЙ ДАННЫХ (SUPABASE)
# ─────────────────────────────────────────────────────────

def get_user_projects(user_id: int):
    try:
        res = supabase.table("projects").select("*").eq("user_id", user_id).execute()
        return res.data
    except Exception: return []

def get_project_by_id(project_id: int):
    try:
        res = supabase.table("projects").select("*").eq("id", project_id).execute()
        return res.data[0] if res.data else None
    except Exception: return None

def create_project(user_id: int, project_name: str):
    try:
        proj_res = supabase.table("projects").insert({"user_id": user_id, "name": project_name}).execute()
        if not proj_res.data: return None, "БД вернула пустой ответ."
        project_id = proj_res.data[0]["id"]

        # Создаем файлы сразу с правильными путями
        manifest_path = "app/src/main/AndroidManifest.xml"
        kotlin_path = "app/src/main/kotlin/com/flare/compiler/MainActivity.kt"

        manifest_code = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
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
            "        textView.text = \"Hello World from FlareBuilder!\"\n"
            "        setContentView(textView)\n"
            "    }\n"
            "}"
        )

        supabase.table("files").insert([
            {"project_id": project_id, "name": manifest_path, "content": manifest_code},
            {"project_id": project_id, "name": kotlin_path, "content": kotlin_code}
        ]).execute()
        
        return project_id, None
    except Exception as e: return None, str(e)

def get_project_files(project_id: int):
    try:
        res = supabase.table("files").select("*").eq("project_id", project_id).execute()
        return res.data
    except Exception: return []

# ─────────────────────────────────────────────────────────
# ⌨️ БЛОК 2: КЛАВИАТУРЫ И СТИЛИ КНОПОК
# ─────────────────────────────────────────────────────────

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📁 Мои проекты", callback_data="list_projects"))
    builder.add(InlineKeyboardButton(text="📥 Импортировать через Git Clone", callback_data="import_repo_start"))
    builder.adjust(1)
    return builder.as_markup()

def get_project_manage_menu(project_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🗂 Проводник файлов (Код)", callback_data=f"files_proj_{project_id}"))
    builder.add(InlineKeyboardButton(text="🤖 AI Проектирование (Создание/Правка)", callback_data=f"project_ai_dev_{project_id}", style="primary"))
    builder.add(InlineKeyboardButton(text="🚀 Собрать APK-пакет", callback_data=f"build_apk_{project_id}", style="success"))
    builder.add(InlineKeyboardButton(text="⬅️ К списку проектов", callback_data="list_projects", style="danger"))
    builder.adjust(1)
    return builder.as_markup()

def get_file_view_keyboard(file_id: int, project_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✏️ Изменить вручную", callback_data=f"edit_man_{file_id}_{project_id}", style="primary"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад в проводник", callback_data=f"files_proj_{project_id}", style="danger"))
    builder.adjust(1)
    return builder.as_markup()

# ─────────────────────────────────────────────────────────
# 📡 БЛОК 3: ХЕНДЛЕРЫ ЛОГИКИ И СИСТЕМНЫЙ GIT CLONE
# ─────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛸 **FlareBuilder Kotlin IDE** готова к работе.", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "list_projects")
async def list_projects(callback: types.CallbackQuery):
    projects = get_user_projects(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    if not projects:
        builder.add(InlineKeyboardButton(text="➕ Создать новый проект", callback_data="new_project_start", style="success"))
        builder.add(InlineKeyboardButton(text="⬅️ Меню", callback_data="main_menu", style="danger"))
        builder.adjust(1)
        await callback.message.edit_text("У вас пока нет созданных проектов.", reply_markup=builder.as_markup())
    else:
        for p in projects:
            builder.add(InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"manage_proj_{p['id']}"))
        builder.add(InlineKeyboardButton(text="➕ Создать новый проект", callback_data="new_project_start", style="success"))
        builder.add(InlineKeyboardButton(text="⬅️ Меню", callback_data="main_menu", style="danger"))
        builder.adjust(1)
        await callback.message.edit_text("Выберите проект для работы:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🛸 **FlareBuilder Kotlin IDE** готова к работе.", reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "new_project_start")
async def np_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите имя нового Kotlin проекта:")
    await state.set_state(ProjectStates.waiting_for_name)

@dp.message(ProjectStates.waiting_for_name)
async def np_save(message: types.Message, state: FSMContext):
    pid, err = create_project(message.from_user.id, message.text.strip())
    await state.clear()
    if pid:
        await message.answer("✅ Проект инициализирован!", reply_markup=get_project_manage_menu(pid))
    else:
         await message.answer(f"❌ Ошибка создания: {err}", reply_markup=get_main_menu())

@dp.callback_query(F.data == "import_repo_start")
async def import_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📥 Отправьте ссылку на GitHub репозиторий. Поддерживается любой формат (даже прямая вставка строки `git clone ...`):")
    await state.set_state(ProjectStates.waiting_for_import_url)

@dp.message(ProjectStates.waiting_for_import_url)
async def import_process(message: types.Message, state: FSMContext):
    raw_input = urllib.parse.unquote(message.text.strip())
    await state.clear()
    
    # 🛠 УЛЬТИМАТИВНЫЙ ДЕКОДЕР И СБОР ССЫЛКИ ДЛЯ ТЕРМИНАЛА
    match = re.search(r'github\.com/([^/\s]+)/([^/\s\.]+)', raw_input, re.IGNORECASE)
    if match:
        owner, repo_name = match.group(1), match.group(2)
    else:
        cleaned = re.sub(r'^(git clone\s+)?(https?://)?(www\.)?', '', raw_input, flags=re.IGNORECASE)
        parts = [p for p in cleaned.split('/') if p]
        if len(parts) >= 2:
            owner, repo_name = parts[0], parts[1]
        else:
            await message.answer("❌ Не удалось распознать ссылку на репозиторий. Попробуйте скопировать её стандартный вид.", reply_markup=get_main_menu())
            return

    clone_url = f"https://github.com/{owner}/{repo_name}.git"
    status_msg = await message.answer(f"🖥 `Terminal:` Выполняю команду `git clone {clone_url}` в изолированном окружении...")

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Запуск терминального клонирования через подпроцесс
            process = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", clone_url, tmpdir,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                await status_msg.edit_text(f"❌ `Terminal Error:` Сбой выполнения клонирования.\nЛог:\n`{stderr.decode(errors='ignore')}`")
                return

            await status_msg.edit_text("🗂 Сканирование структуры репозитория и сохранение путей...")

            proj_res = supabase.table("projects").insert({"user_id": message.from_user.id, "name": repo_name}).execute()
            project_id = proj_res.data[0]["id"]

            files_inserted = 0
            for root, _, files in os.walk(tmpdir):
                for file in files:
                    if file.endswith(('.kt', '.java', '.xml')):
                        full_path = os.path.join(root, file)
                        # Получаем чистый относительный путь файла в структуре проекта
                        rel_path = os.path.relpath(full_path, tmpdir)
                        
                        try:
                            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f_content:
                                content = f_content.read()
                            
                            # Сохраняем имя файла прямо как его путь! (напр. app/src/main/res/layout/main.xml)
                            supabase.table("files").insert({
                                "project_id": project_id,
                                "name": rel_path,
                                "content": content
                            }).execute()
                            files_inserted += 1
                        except Exception:
                            pass

            await status_msg.delete()
            if files_inserted > 0:
                await message.answer(f"🚀 Репозиторий `{repo_name}` успешно импортирован!\nСохранено исходных файлов: {files_inserted}", reply_markup=get_project_manage_menu(project_id))
            else:
                await message.answer("⚠ Репозиторий склонирован, но внутри не найдено файлов Android исходников (.kt, .java, .xml).", reply_markup=get_main_menu())

        except Exception as e:
            await status_msg.edit_text(f"❌ Критический сбой работы окружения: {str(e)}")

@dp.callback_query(F.data.startswith("manage_proj_"))
async def manage_proj(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[2])
    p = get_project_by_id(pid)
    await callback.message.edit_text(f"📦 Проект: **{p['name']}**\nВыберите действие:", reply_markup=get_project_manage_menu(pid), parse_mode="Markdown")

# ─────────────────────────────────────────────────────────
# 📂 СТРУКТУРА ПАПОК НА INLINE-КНОПКАХ (ПРОВОДНИК)
# ─────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("files_proj_"))
async def files_proj(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[2])
    files = get_project_files(pid)
    
    builder = InlineKeyboardBuilder()
    if not files:
        await callback.message.edit_text("В проекте нет файлов. Воспользуйтесь ИИ для их создания.", reply_markup=get_project_manage_menu(pid))
        return
        
    for f in files:
        # Показываем красивую кнопку с относительным путем файла
        builder.add(InlineKeyboardButton(text=f"📄 {f['name']}", callback_data=f"vf_{f['id']}_{pid}"))
        
    builder.add(InlineKeyboardButton(text="➕ Создать файл вручную", callback_data=f"add_f_{pid}", style="success"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_proj_{pid}", style="danger"))
    builder.adjust(1)
    
    await callback.message.edit_text("🗂 **Проводник файлов проекта:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("vf_"))
async def view_file(callback: types.CallbackQuery):
    fid = int(callback.data.split("_")[1])
    pid = int(callback.data.split("_")[2])
    res = supabase.table("files").select("*").eq("id", fid).execute()
    f_data = res.data[0]
    
    lang = "xml" if f_data['name'].endswith(".xml") else "kotlin"
    text = f"📄 **Файл:** `{f_data['name']}`\n```{lang}\n{f_data['content']}\n```"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_file_view_keyboard(fid, pid))

@dp.callback_query(F.data.startswith("add_f_"))
async def add_file_start(callback: types.CallbackQuery, state: FSMContext):
    pid = int(callback.data.split("_")[2])
    await state.update_data(create_pid=pid)
    await callback.message.answer("✍ Введите полный относительный путь для нового файла (например, `app/src/main/res/values/strings.xml`):")
    await state.set_state(ProjectStates.waiting_for_file_path)

@dp.message(ProjectStates.waiting_for_file_path)
async def add_file_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pid = data['create_pid']
    path = message.text.strip().strip('/')
    
    # Создаем пустой файл
    supabase.table("files").insert({"project_id": pid, "name": path, "content": "// Новый файл"}).execute()
    await state.clear()
    await message.answer(f"✅ Файл `{path}` успешно добавлен в дерево папок!", reply_markup=get_project_manage_menu(pid))

@dp.callback_query(F.data.startswith("edit_man_"))
async def edit_man_start(callback: types.CallbackQuery, state: FSMContext):
    fid = int(callback.data.split("_")[2])
    pid = int(callback.data.split("_")[3])
    await state.update_data(m_fid=fid, m_pid=pid)
    await callback.message.answer("✏️ Отправьте измененный код для этого файла целиком в одном сообщении:")
    await state.set_state(ProjectStates.waiting_for_manual_edit)

@dp.message(ProjectStates.waiting_for_manual_edit)
async def edit_man_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    fid, pid = data['m_fid'], data['m_pid']
    await state.clear()
    
    supabase.table("files").update({"content": message.text}).eq("id", fid).execute()
    await message.answer("✅ Изменения в файле успешно сохранены!", reply_markup=get_project_manage_menu(pid))

# ─────────────────────────────────────────────────────────
# 🤖 АВТОМАТИЧЕСКОЕ ИИ ПРОЕКТИРОВАНИЕ ПАПОК И КОДА
# ─────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("project_ai_dev_"))
async def ai_dev_start(callback: types.CallbackQuery, state: FSMContext):
    pid = int(callback.data.split("_")[3])
    await state.update_data(ai_pid=pid)
    await callback.message.answer(
        "🤖 **Глобальный ИИ-Архитектор проекта**\n\n"
        "Опишите задачу текстом. ИИ проанализирует текущие файлы и **сам создаст нужные папки/файлы**, "
        "а также изменит старые в соответствии с вашим запросом."
    )
    await state.set_state(ProjectStates.waiting_for_ai_project_prompt)

@dp.message(ProjectStates.waiting_for_ai_project_prompt)
async def ai_dev_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pid = data['ai_pid']
    await state.clear()
    
    status_msg = await message.answer("🧠 ИИ изучает архитектуру проекта и пишет код...")
    
    current_files = get_project_files(pid)
    ai_actions = await ai_project_wide_develop(current_files, message.text.strip())
    
    if not ai_actions:
        await status_msg.edit_text("❌ ИИ не смог сформировать изменения или вернул неверный формат. Попробуйте изменить запрос.")
        return
        
    created_count = 0
    updated_count = 0
    
    for action in ai_actions:
        target_path = action.get("path", "").strip().strip('/')
        new_content = action.get("content", "")
        
        if not target_path:
            continue
            
        # Проверяем, существует ли файл с таким путем в проекте
        existing_file = next((f for f in current_files if f['name'] == target_path), None)
        
        if existing_file:
            # Обновляем старый файл
            supabase.table("files").update({"content": new_content}).eq("id", existing_file['id']).execute()
            updated_count += 1
        else:
            # Создаем новый файл по сгенерированному ИИ пути (папки виртуально создаются путями)
            supabase.table("files").insert({"project_id": pid, "name": target_path, "content": new_content}).execute()
            created_count += 1
            
    await status_msg.delete()
    await message.answer(
        f"✨ **ИИ успешно завершил проектирование!**\n\n"
        f"📁 Создано новых файлов: `{created_count}`\n"
        f"📝 Модифицировано файлов: `{updated_count}`",
        parse_mode="Markdown",
        reply_markup=get_project_manage_menu(pid)
    )

# ─────────────────────────────────────────────────────────
# 🚀 БИЛДЕР ЧЕРЕЗ ДИНАМИЧЕСКИЕ ПУТИ ИЗ БД
# ─────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("build_apk_"))
async def build_apk_process(callback: types.CallbackQuery):
    project_id = int(callback.data.split("_")[2])
    proj = get_project_by_id(project_id)
    files = get_project_files(project_id)
    
    status_msg = await callback.message.answer("📡 Шаг 1: Подключение к репозиторию компилятора...")

    try:
        repo = github_client.get_repo(GITHUB_REPO_CLEANED)
        await status_msg.edit_text("📝 Шаг 2: Синхронизация структуры папок и исходников...")
        
        for f in files:
            path = f['name']  # Полный путь файла из БД
            content = f['content']
                
            try:
                git_file = repo.get_contents(path, ref="main")
                repo.update_file(git_file.path, f"Update {path}", content, git_file.sha, branch="main")
            except Exception:
                repo.create_file(path, f"Create {path}", content, branch="main")

        await status_msg.edit_text("🚀 Шаг 3: Запуск удаленной Gradle сборки...")
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
                        await status_msg.edit_text("⚙️ Gradle компилирует и линкует ресурсы приложения в APK пакет...")
                    elif latest_run.status == "completed":
                        if latest_run.conclusion == "success":
                            success_build = True
                            break
                        else:
                            await status_msg.edit_text("❌ Ошибка сборки Gradle! Проверьте синтаксис вашего кода.")
                            return
            except Exception: pass

        if not success_build or not run_id:
            await status_msg.edit_text("❌ Превышено время ожидания компиляции (Timeout).")
            return

        await status_msg.edit_text("📥 Шаг 4: Извлечение готового APK артефакта...")
        
        try:
            import requests
            artifacts = repo.get_artifacts()
            apk_artifact = None
            for art in artifacts:
                if "app" in art.name.lower() or "debug" in art.name.lower(): 
                    apk_artifact = art
                    break
            
            if not apk_artifact:
                await status_msg.edit_text("❌ Готовый скомпилированный файл не найден.")
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
                                caption=f"📱 **Твое приложение успешно собрано!**\n\n📦 Проект: `{proj['name']}`\n🔥 Устанавливай APK прямо сейчас!"
                            )
                            return
            await status_msg.edit_text("❌ Ошибка при распаковке APK пакета.")
        except Exception as e_art:
            await status_msg.edit_text(f"❌ Ошибка загрузки артефактов: {str(e_art)}")
    except Exception as e:
        await status_msg.edit_text(f"❌ Критическая ошибка сборщика:\n`{str(e)}`")

# ─────────────────────────────────────────────────────────
# 🌍 ВЕБ-СЕРВЕР И СТАРТ
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
    print("🤖 FlareBuilder Kotlin IDE успешно запущена!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
