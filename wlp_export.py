# batch_export.py
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import json
import logging
import requests
from datetime import datetime
import urllib.parse
import os
import time
from config import WLN_TOKEN

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WialonBatchExporter:
    def __init__(self):
        self.base_url = "https://hst-api.wialon.com"
        self.sid = None
        self.token = WLN_TOKEN
        self.units = []

    def login(self):
        """Авторизация по токену"""
        try:
            auth_url = f'{self.base_url}/wialon/ajax.html?svc=token/login&params={{"token":"{self.token}"}}'
            
            response = requests.get(auth_url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("error"):
                raise Exception(f"Login error: {data.get('reason', 'Unknown error')}")
            
            self.sid = data.get("eid") or data.get("sid")
            if not self.sid:
                raise Exception("No session ID received")
                
            logger.info("Login successful")
            return True
            
        except Exception as e:
            logger.error(f"Login failed: {e}")
            raise Exception(f"Login failed: {e}")

    def call_api(self, svc, params):
        """Вызов API метода"""
        if not self.sid:
            raise Exception("Not logged in")
        
        params_json = json.dumps(params, ensure_ascii=False)
        params_encoded = urllib.parse.quote(params_json)
        url = f'{self.base_url}/wialon/ajax.html?svc={svc}&params={params_encoded}&sid={self.sid}'
        
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

    def search_units_by_code_api(self, client_code):
        """Прямой поиск объектов по коду через API"""
        try:
            spec = {
                "itemsType": "avl_unit",
                "propName": "sys_name",  # Ищем в названиях
                "propValueMask": f"*code{client_code}*",  # Ищем код в названиях
                "sortType": "sys_name"
            }
            
            params = {
                "spec": spec,
                "force": 1,
                "flags": 0x1,  # Basic info
                "from": 0,
                "to": 0
            }
            
            result = self.call_api("core/search_items", params)
            
            if not result or 'items' not in result:
                return []
            
            # Получаем детальную информацию для найденных объектов
            detailed_units = []
            for unit in result['items']:
                unit_id = unit['id']
                unit_details = self.get_unit_details(unit_id)
                if unit_details and 'item' in unit_details:
                    detailed_units.append(unit_details['item'])
            
            return detailed_units
            
        except Exception as e:
            logger.error(f"API search failed: {e}")
            return []

    def get_unit_details(self, unit_id):
        """Получение детальной информации об объекте"""
        try:
            params = {
                "id": unit_id,
                "flags": 0x1  # Только базовая информация
            }
            
            return self.call_api("core/search_item", params)
            
        except Exception as e:
            logger.warning(f"Failed to get details for unit {unit_id}: {e}")
            return None

    def check_unit_has_code(self, unit_id, client_code):
        """Проверяет, есть ли у объекта нужный код"""
        try:
            unit_details = self.get_unit_details(unit_id)
            if not unit_details or 'item' not in unit_details:
                return False
            
            item = unit_details['item']
            fields = item.get('flds', {})
            
            # Проверяем поля
            for field_id, field in fields.items():
                field_name = field.get('n', '')
                if field_name and f"code{client_code}" in field_name:
                    return True
            
            # Проверяем название объекта
            unit_name = item.get('nm', '').lower()
            if f"code{client_code}" in unit_name:
                return True
                
            return False
            
        except Exception as e:
            logger.warning(f"Error checking unit {unit_id}: {e}")
            return False

    def export_unit_wlp(self, unit_id, unit_name, export_dir):
        """Экспорт объекта в WLP файл"""
        try:
            safe_name = "".join(c for c in unit_name if c.isalnum() or c in (' ', '.', '_')).rstrip()
            filename = f"{safe_name}_{unit_id}.wlp"
            filepath = os.path.join(export_dir, filename)
            
            params = {
                "fileName": filename,
                "json": {
                    "units": [{
                        "id": unit_id,
                        "props": ["general", "sensors", "custom_fields"]
                    }]
                }
            }
            
            result = self.call_api("exchange/export_json", params)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            return filepath
            
        except Exception as e:
            logger.error(f"Export failed for unit {unit_id}: {e}")
            return None

class BatchExportApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Wialon Batch Exporter")
        self.root.geometry("1000x700")
        
        self.exporter = WialonBatchExporter()
        self.found_units = []
        
        self.create_widgets()
        self.auto_login()

    def create_widgets(self):
        """Создание интерфейса"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Input frame
        input_frame = ttk.LabelFrame(main_frame, text="Поиск объектов по коду клиента", padding="5")
        input_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(input_frame, text="4-значный код клиента:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.code_entry = ttk.Entry(input_frame, width=10)
        self.code_entry.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        self.search_btn = ttk.Button(input_frame, text="Найти объекты", command=self.search_units)
        self.search_btn.grid(row=0, column=2, padx=5)
        
        # Export frame
        export_frame = ttk.Frame(main_frame)
        export_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.export_btn = ttk.Button(export_frame, text="Экспортировать все", command=self.export_all)
        self.export_btn.grid(row=0, column=0, padx=5)
        
        ttk.Label(export_frame, text="Папка для экспорта:").grid(row=0, column=1, sticky=tk.W, padx=(20, 5))
        self.export_dir = tk.StringVar(value=os.getcwd())
        ttk.Label(export_frame, textvariable=self.export_dir, width=40).grid(row=0, column=2, sticky=tk.W, padx=5)
        
        ttk.Button(export_frame, text="Выбрать", command=self.select_export_dir).grid(row=0, column=3, padx=5)
        
        # Progress
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Status
        self.status_var = tk.StringVar(value="Готов к работе")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_label.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Results
        results_frame = ttk.LabelFrame(main_frame, text="Найденные объекты", padding="5")
        results_frame.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Treeview
        columns = ("name", "id", "code_field")
        self.tree = ttk.Treeview(results_frame, columns=columns, show="headings", height=10)
        
        self.tree.heading("name", text="Название")
        self.tree.heading("id", text="ID")
        self.tree.heading("code_field", text="Поле с кодом")
        
        self.tree.column("name", width=400)
        self.tree.column("id", width=100)
        self.tree.column("code_field", width=200)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(results_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.W, tk.E))
        v_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        # Configure weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        
        self.set_ui_state(False)

    def set_ui_state(self, enabled):
        """Установка состояния UI"""
        state = "normal" if enabled else "disabled"
        self.search_btn.config(state=state)
        self.export_btn.config(state=state)

    def select_export_dir(self):
        """Выбор папки для экспорта"""
        directory = filedialog.askdirectory(title="Выберите папку для экспорта")
        if directory:
            self.export_dir.set(directory)

    def auto_login(self):
        """Автоматическая авторизация"""
        self.status_var.set("Авторизация...")
        self.progress.start()
        self.root.update()
        
        try:
            success = self.exporter.login()
            if success:
                self.status_var.set("Авторизация успешна! Введите код клиента")
                self.set_ui_state(True)
            else:
                raise Exception("Авторизация не удалась")
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Login failed: {error_msg}")
            self.status_var.set("Ошибка авторизации")
            messagebox.showerror("Ошибка авторизации", error_msg)
            
        finally:
            self.progress.stop()

    def search_units(self):
        """Поиск объектов по коду"""
        client_code = self.code_entry.get().strip()
        if not client_code or len(client_code) != 4 or not client_code.isdigit():
            messagebox.showerror("Ошибка", "Введите 4-значный цифровой код клиента")
            return
            
        self.status_var.set(f"Поиск объектов с кодом {client_code}...")
        self.set_ui_state(False)
        self.progress.start()
        self.root.update()
        
        try:
            # Используем быстрый API поиск
            self.found_units = self.exporter.search_units_by_code_api(client_code)
            
            # Очищаем treeview
            for item in self.tree.get_children():
                self.tree.delete(item)
            
            # Заполняем treeview
            for unit in self.found_units:
                name = unit.get('nm', 'N/A')
                unit_id = unit.get('id', 'N/A')
                
                # Ищем поле с кодом
                code_field = "Не найдено"
                fields = unit.get('flds', {})
                for field_id, field in fields.items():
                    field_name = field.get('n', '')
                    if field_name and f"code{client_code}" in field_name:
                        code_field = field_name
                        break
                
                self.tree.insert("", "end", values=(name, unit_id, code_field))
            
            count = len(self.found_units)
            self.status_var.set(f"Найдено объектов: {count}")
            messagebox.showinfo("Результаты", f"Найдено объектов с кодом {client_code}: {count}")
            
        except Exception as e:
            error_msg = f"Ошибка поиска: {str(e)}"
            logger.error(error_msg)
            self.status_var.set("Ошибка поиска")
            messagebox.showerror("Ошибка поиска", error_msg)
            
        finally:
            self.progress.stop()
            self.set_ui_state(True)

    def export_all(self):
        """Экспорт всех найденных объектов"""
        if not self.found_units:
            messagebox.showerror("Ошибка", "Сначала найдите объекты")
            return
            
        export_dir = self.export_dir.get()
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            
        self.status_var.set("Начало экспорта...")
        self.set_ui_state(False)
        self.progress.start()
        self.root.update()
        
        success_count = 0
        failed_count = 0
        
        try:
            for i, unit in enumerate(self.found_units):
                unit_id = unit.get('id')
                unit_name = unit.get('nm', f'unit_{unit_id}')
                
                self.status_var.set(f"Экспорт {i+1}/{len(self.found_units)}: {unit_name}")
                self.root.update()
                
                result = self.exporter.export_unit_wlp(unit_id, unit_name, export_dir)
                if result:
                    success_count += 1
                    # Помечаем успех в treeview
                    for item in self.tree.get_children():
                        if self.tree.item(item, 'values')[1] == str(unit_id):
                            self.tree.item(item, tags=('success',))
                            break
                else:
                    failed_count += 1
                    # Помечаем ошибку в treeview
                    for item in self.tree.get_children():
                        if self.tree.item(item, 'values')[1] == str(unit_id):
                            self.tree.item(item, tags=('error',))
                            break
                
                # Небольшая пауза между запросами
                time.sleep(0.1)
            
            # Настраиваем цвета
            self.tree.tag_configure('success', background='#d4edda')
            self.tree.tag_configure('error', background='#f8d7da')
            
            self.status_var.set(f"Экспорт завершен: {success_count} успешно, {failed_count} с ошибками")
            messagebox.showinfo("Готово", 
                              f"Успешно: {success_count}\nОшибки: {failed_count}\nПапка: {export_dir}")
            
        except Exception as e:
            error_msg = f"Ошибка экспорта: {str(e)}"
            logger.error(error_msg)
            self.status_var.set("Ошибка экспорта")
            messagebox.showerror("Ошибка экспорта", error_msg)
            
        finally:
            self.progress.stop()
            self.set_ui_state(True)

def main():
    root = tk.Tk()
    app = BatchExportApp(root)
    
    # Center window
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_width()) // 2
    y = (root.winfo_screenheight() - root.winfo_height()) // 2
    root.geometry(f"+{x}+{y}")
    
    root.mainloop()

if __name__ == "__main__":
    main()