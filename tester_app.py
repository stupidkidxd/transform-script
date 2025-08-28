# tester_app.py
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import json
import logging
import requests
from datetime import datetime
import urllib.parse
from config import WLN_TOKEN

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WialonSimpleAPI:
    def __init__(self):
        self.base_url = "https://hst-api.wialon.com"
        self.sid = None
        self.token = WLN_TOKEN

    def login(self):
        """Простая авторизация по прямой ссылке"""
        try:
            logger.info("Logging in with direct URL...")
            
            # Формируем URL для авторизации (точно как в браузере)
            auth_url = f'{self.base_url}/wialon/ajax.html?svc=token/login&params={{"token":"{self.token}"}}'
            
            logger.info(f"Auth URL: {auth_url}")
            
            response = requests.get(auth_url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Login response: {data}")
            
            if data.get("error"):
                error_msg = f"Login error {data.get('error')}"
                if data.get("reason"):
                    error_msg += f": {data['reason']}"
                raise Exception(error_msg)
            
            self.sid = data.get("eid") or data.get("sid")
            if not self.sid:
                raise Exception("No session ID received")
                
            logger.info(f"Login successful. SID: {self.sid[:15]}...")
            return True
            
        except Exception as e:
            logger.error(f"Login failed: {e}")
            raise Exception(f"Login failed: {e}")

    def call_api(self, svc, params):
        """Вызов API метода"""
        if not self.sid:
            raise Exception("Not logged in")
        
        # Формируем URL с параметрами (правильное кодирование)
        params_json = json.dumps(params, ensure_ascii=False)
        params_encoded = urllib.parse.quote(params_json)
        url = f'{self.base_url}/wialon/ajax.html?svc={svc}&params={params_encoded}&sid={self.sid}'
        
        logger.debug(f"API URL: {url}")
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if isinstance(data, dict) and data.get("error"):
                error_code = data["error"]
                error_msg = f"API Error {error_code}"
                if data.get("reason"):
                    error_msg += f": {data['reason']}"
                raise Exception(error_msg)
                
            return data
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"HTTP request failed: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"JSON decode error: {e}")

    def search_unit_by_imei(self, imei):
        """Поиск юнита по IMEI согласно документации поддержки"""
        # Правильный формат согласно ответу поддержки
        params = {
            "spec": {
                "itemsType": "avl_unit",
                "propName": "sys_unique_id",  # Поиск по уникальному ID (IMEI)
                "propValueMask": imei,  # Точное совпадение с IMEI
                "sortType": "sys_name"
            },
            "force": 1,
            "flags": 1,  # Basic info
            "from": 0,
            "to": 0
        }
        
        return self.call_api("core/search_items", params)

    def export_unit_data(self, unit_id, filename="unit_export.wlp"):
        """Экспорт данных юнита в WLP формат"""
        params = {
            "fileName": filename,
            "json": {
                "units": [{
                    "id": unit_id,
                    "props": [
                        "general", "sensors", "commands", "custom_fields",
                        "fuel_consumption", "maintenance", "eco_driving",
                        "profile", "icon", "advanced"
                    ]
                }]
            }
        }
        
        return self.call_api("exchange/export_json", params)

    def get_unit_details(self, unit_id):
        """Получение детальной информации о юните"""
        params = {
            "id": unit_id,
            "flags": 0x7FFFFFFF  # Все флаги
        }
        
        return self.call_api("core/search_item", params)

class WialonSimpleTester:
    def __init__(self, root):
        self.root = root
        self.root.title("Wialon Simple Tester")
        self.root.geometry("1000x700")
        
        self.api = WialonSimpleAPI()
        self.current_data = None
        self.current_unit_id = None
        self.current_unit_name = None
        
        self.create_widgets()
        self.auto_login()
        
    def create_widgets(self):
        """Создание интерфейса"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Search frame
        search_frame = ttk.LabelFrame(main_frame, text="Поиск устройства по IMEI", padding="5")
        search_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(search_frame, text="IMEI устройства:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.search_entry = ttk.Entry(search_frame, width=25)
        self.search_entry.grid(row=0, column=1, sticky=tk.W, padx=5)
        self.search_entry.insert(0, "352093085741501")
        self.search_entry.bind('<Return>', lambda e: self.search_device())
        
        # Включаем поддержку Ctrl+V
        self.search_entry.bind('<Control-v>', self.paste_from_clipboard)
        self.search_btn = ttk.Button(search_frame, text="Найти", command=self.search_device)
        self.search_btn.grid(row=0, column=2, padx=5)
        
        # Export frame
        export_frame = ttk.Frame(main_frame)
        export_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.export_btn = ttk.Button(export_frame, text="Экспорт в WLP", command=self.export_data)
        self.export_btn.grid(row=0, column=0, padx=5)
        
        # Status
        self.status_var = tk.StringVar(value="Подготовка...")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_label.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Notebook
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=3, column=0, sticky=(tk.N, tk.S, tk.W, tk.E))
        
        # Raw data tab
        raw_frame = ttk.Frame(self.notebook)
        self.notebook.add(raw_frame, text="Сырые данные JSON")
        self.raw_text = scrolledtext.ScrolledText(raw_frame, wrap=tk.WORD, font=('Consolas', 9))
        self.raw_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Formatted tab
        formatted_frame = ttk.Frame(self.notebook)
        self.notebook.add(formatted_frame, text="Форматированный вид")
        self.formatted_text = scrolledtext.ScrolledText(formatted_frame, wrap=tk.WORD, font=('Arial', 10))
        self.formatted_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Configure weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # Initial state
        self.set_ui_state(False)
        
    def paste_from_clipboard(self, event=None):
        """Вставка из буфера обмена с очисткой от лишних символов"""
        try:
            # Получаем содержимое буфера обмена
            clipboard_content = self.root.clipboard_get()
            
            # Очищаем от лишних символов (пробелы, переносы и т.д.)
            cleaned_imei = ''.join(filter(str.isdigit, clipboard_content))
            
            if cleaned_imei:
                # Вставляем очищенный IMEI
                self.search_entry.delete(0, tk.END)
                self.search_entry.insert(0, cleaned_imei)
                
                # Показываем уведомление о вставке
                self.status_var.set(f"Вставлен IMEI: {cleaned_imei}")
                
            return "break"  # Предотвращаем стандартную обработку
        except Exception as e:
            logger.warning(f"Clipboard paste failed: {e}")
            return "break"
        
    def set_ui_state(self, enabled):
        """Установка состояния UI"""
        state = "normal" if enabled else "disabled"
        self.search_btn.config(state=state)
        self.export_btn.config(state=state)
        
    def auto_login(self):
        """Автоматическая авторизация"""
        self.status_var.set("Авторизация...")
        self.root.update()
        
        try:
            success = self.api.login()
            if success:
                self.status_var.set("Авторизация успешна! Введите IMEI")
                self.set_ui_state(True)
            else:
                raise Exception("Авторизация не удалась")
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Login failed: {error_msg}")
            
            test_url = f'https://hst-api.wialon.com/wialon/ajax.html?svc=token/login&params={{"token":"{WLN_TOKEN}"}}'
            error_msg += f"\n\nПроверьте ссылку в браузере:\n{test_url}"
            
            self.status_var.set("Ошибка авторизации")
            messagebox.showerror("Ошибка авторизации", error_msg)
            
    def search_device(self):
        """Поиск устройства по IMEI"""
        imei = self.search_entry.get().strip()
        if not imei:
            messagebox.showerror("Ошибка", "Введите IMEI устройства")
            return
            
        # Очищаем IMEI от возможных лишних символов
        cleaned_imei = ''.join(filter(str.isdigit, imei))
        if cleaned_imei != imei:
            self.search_entry.delete(0, tk.END)
            self.search_entry.insert(0, cleaned_imei)
            imei = cleaned_imei
            
        self.status_var.set(f"Поиск устройства: {imei}...")
        self.set_ui_state(False)
        self.root.update()
        
        try:
            search_result = self.api.search_unit_by_imei(imei)
            
            if not search_result or 'items' not in search_result or not search_result['items']:
                raise Exception(f"Устройство с IMEI '{imei}' не найдено")
            
            unit = search_result['items'][0]
            self.current_unit_id = unit['id']
            self.current_unit_name = unit['nm']
            
            self.status_var.set(f"Загрузка данных: {self.current_unit_name}...")
            unit_details = self.api.get_unit_details(self.current_unit_id)
            self.current_data = unit_details
            
            self.display_data(unit_details)
            self.status_var.set(f"Найдено: {self.current_unit_name} (ID: {self.current_unit_id})")
            
        except Exception as e:
            error_msg = f"Ошибка поиска: {str(e)}"
            logger.error(error_msg)
            self.status_var.set("Ошибка поиска")
            messagebox.showerror("Ошибка поиска", error_msg)
            
        finally:
            self.set_ui_state(True)
    
    def export_data(self):
        """Экспорт данных в WLP файл"""
        if not self.current_unit_id:
            messagebox.showerror("Ошибка", "Сначала найдите устройство")
            return
            
        try:
            self.status_var.set("Экспорт данных в WLP...")
            self.set_ui_state(False)
            self.root.update()
            
            filename = f"unit_{self.current_unit_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wlp"
            export_result = self.api.export_unit_data(self.current_unit_id, filename)
            
            self.status_var.set(f"Экспорт завершен: {filename}")
            messagebox.showinfo("Экспорт", f"Данные успешно экспортированы в файл:\n{filename}")
            
            # Показываем результат экспорта
            self.raw_text.delete(1.0, tk.END)
            self.raw_text.insert(tk.END, json.dumps(export_result, indent=2, ensure_ascii=False))
            
        except Exception as e:
            error_msg = f"Ошибка экспорта: {str(e)}"
            logger.error(error_msg)
            self.status_var.set("Ошибка экспорта")
            messagebox.showerror("Ошибка экспорта", error_msg)
            
        finally:
            self.set_ui_state(True)
    
    def display_data(self, data):
        """Отображение данных"""
        # Raw data
        self.raw_text.delete(1.0, tk.END)
        try:
            raw_json = json.dumps(data, indent=2, ensure_ascii=False)
            self.raw_text.insert(tk.END, raw_json)
        except Exception as e:
            self.raw_text.insert(tk.END, f"Ошибка: {e}")
        
        # Formatted data
        self.formatted_text.delete(1.0, tk.END)
        formatted = self.format_data(data)
        self.formatted_text.insert(tk.END, formatted)
    
    def format_data(self, data):
        """Форматирование данных"""
        try:
            output = []
            output.append("=" * 70)
            output.append(f"ДАННЫЕ УСТРОЙСТВА: {self.current_unit_name}")
            output.append("=" * 70)
            output.append("")
            
            general = data.get('general', {})
            output.append("ОСНОВНАЯ ИНФОРМАЦИЯ:")
            output.append(f"Название: {general.get('n', 'N/A')}")
            output.append(f"ID: {data.get('mu', 'N/A')}")
            output.append(f"UID (IMEI): {general.get('uid', 'N/A')}")
            output.append(f"Телефон: {general.get('ph', 'N/A')}")
            output.append(f"Оборудование: {general.get('hw', 'N/A')}")
            output.append("")
            
            # Счетчики
            counters = data.get('counters', {})
            if counters:
                output.append("СЧЕТЧИКИ:")
                for key, value in counters.items():
                    output.append(f"{key}: {value}")
                output.append("")
            
            # Датчики
            sensors = data.get('sensors', [])
            if sensors:
                output.append(f"ДАТЧИКИ ({len(sensors)}):")
                for sensor in sensors:
                    output.append(f"[{sensor.get('id')}] {sensor.get('n')} ({sensor.get('t')})")
                    output.append(f"   Параметр: {sensor.get('p')}, Ед.изм: {sensor.get('m')}")
                output.append("")
            
            return "\n".join(output)
            
        except Exception as e:
            return f"Ошибка форматирования: {e}"

def main():
    root = tk.Tk()
    app = WialonSimpleTester(root)
    
    # Center window
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_width()) // 2
    y = (root.winfo_screenheight() - root.winfo_height()) // 2
    root.geometry(f"+{x}+{y}")
    
    root.mainloop()

if __name__ == "__main__":
    main()