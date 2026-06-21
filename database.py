import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Инициализируем клиент
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def create_project(user_id: int, name: str) -> dict:
    """Создает новый проект и дефолтные файлы для него"""
    # 1. Создаем сам проект
    proj_response = supabase.table("projects").insert({
        "user_id": user_id, 
        "name": name
    }).execute()
    
    project = proj_response.data[0]
    project_id = project['id']

    # 2. Генерируем базовую структуру Android-проекта
    default_files = [
        {
            "project_id": project_id, 
            "name": "AndroidManifest.xml", 
            "content": "\n<manifest xmlns:android='http://schemas.android.com/apk/res/android'>\n    <application>\n    </application>\n</manifest>"
        },
        {
            "project_id": project_id, 
            "name": "MainActivity.java", 
            "content": "package com.example.app;\n\npublic class MainActivity {\n    // Твой первый Java код\n}"
        },
        {
            "project_id": project_id, 
            "name": "activity_main.xml", 
            "content": "\n<LinearLayout>\n</LinearLayout>"
        }
    ]
    
    supabase.table("files").insert(default_files).execute()
    return project

def get_user_projects(user_id: int) -> list:
    """Получает все проекты конкретного пользователя"""
    response = supabase.table("projects").select("*").eq("user_id", user_id).execute()
    return response.data

def get_project_files(project_id: int) -> list:
    """Получает список всех файлов внутри проекта"""
    response = supabase.table("files").select("*").eq("project_id", project_id).execute()
    return response.data

def get_file_content(file_id: int) -> dict:
    """Получает данные и содержимое конкретного файла"""
    response = supabase.table("files").select("*").eq("id", file_id).execute()
    return response.data[0] if response.data else None
