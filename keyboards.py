from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

def get_main_menu() -> InlineKeyboardMarkup:
    """Главное меню бота"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📂 Мои проекты", callback_data="list_projects")
    builder.button(text="➕ Создать проект", callback_data="new_project")
    builder.adjust(1)
    return builder.as_markup()

def get_projects_keyboard(projects: list) -> InlineKeyboardMarkup:
    """Список проектов пользователя"""
    builder = InlineKeyboardBuilder()
    for proj in projects:
        builder.button(text=f"📦 {proj['name']}", callback_data=f"open_proj_{proj['id']}")
    builder.button(text="⬅️ В главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_files_keyboard(project_id: int, files: list) -> InlineKeyboardMarkup:
    """Список файлов внутри выбранного проекта"""
    builder = InlineKeyboardBuilder()
    for f in files:
        # Так как папки пока не разветвляем, просто выводим файлы с иконкой
        builder.button(text=f"📄 {f['name']}", callback_data=f"view_file_{f['id']}")
    
    builder.button(text="🚀 Собрать APK", callback_data=f"build_apk_{project_id}")
    builder.button(text="⬅️ Назад к проектам", callback_data="list_projects")
    builder.adjust(1)
    return builder.as_markup()

def get_file_view_keyboard(file_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Действия внутри открытого файла кода"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Проверить через AI", callback_data=f"ai_check_{file_id}")
    builder.button(text="⬅️ Назад к файлам", callback_data=f"open_proj_{project_id}")
    builder.adjust(1)
    return builder.as_markup()
