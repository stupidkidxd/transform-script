import sqlite3
import json
from config import DATABASE_NAME

def create_database():
    """Создает базу данных и таблицы"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Таблица для сырых данных из Wialon
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS raw_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id TEXT NOT NULL UNIQUE,
            unit_name TEXT,
            raw_json TEXT NOT NULL, -- Здесь храним весь JSON как текст
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица для стандартизированных данных
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS standard_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_unit_id TEXT NOT NULL UNIQUE,
            name TEXT,
            phone_number TEXT,
            imei TEXT,
            vehicle_model TEXT,
            driver_name TEXT,
            standard_json TEXT NOT NULL, -- Стандартизированный JSON
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_unit_id) REFERENCES raw_units (unit_id)
        )
    ''')

    conn.commit()
    conn.close()
    print(f"Database '{DATABASE_NAME}' initialized successfully.")

def save_raw_unit(unit_id, unit_name, raw_data):
    """Сохраняет сырые данные юнита в базу"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Пытаемся обновить, если запись с таким unit_id уже существует
    cursor.execute('''
        INSERT OR REPLACE INTO raw_units (unit_id, unit_name, raw_json)
        VALUES (?, ?, ?)
    ''', (unit_id, unit_name, json.dumps(raw_data, ensure_ascii=False)))

    conn.commit()
    conn.close()

def get_all_raw_units():
    """Извлекает все сырые записи из базы для последующей обработки"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT unit_id, raw_json FROM raw_units')
    rows = cursor.fetchall()
    conn.close()
    # Возвращаем список кортежей (unit_id, raw_json_dict)
    return [(row[0], json.loads(row[1])) for row in rows]