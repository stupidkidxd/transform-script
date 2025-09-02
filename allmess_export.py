import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import json
import logging
import requests
from datetime import datetime, timedelta
import urllib.parse
import os
import time
import zipfile
import io
import threading
from config import WLN_TOKEN

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('batch_export.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class WialonBatchExporter:
    def __init__(self):
        self.base_url = "https://hst-api.wialon.com"
        self.sid = None
        self.token = WLN_TOKEN
        self.is_running = False
        self.current_export = None

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
            response = requests.get(url, timeout=300)
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

    def get_all_units(self):
        """Получение всех объектов"""
        try:
            logger.info("Получение списка всех объектов...")
            
            # Параметры для поиска всех объектов
            spec = {
                "itemsType": "avl_unit",
                "propName": "",
                "propValueMask": "*",
                "sortType": "sys_name"
            }
            
            params = {
                "spec": spec,
                "force": 1,
                "flags": 1,
                "from": 0,
                "to": 0
            }
            
            result = self.call_api("core/search_items", params)
            
            if not result or 'items' not in result:
                raise Exception("Не удалось получить список объектов")
            
            units = result['items']
            logger.info(f"Найдено объектов: {len(units)}")
            
            # Фильтруем только активные объекты с IMEI
            filtered_units = []
            for unit in units:
                if unit.get('nm') and unit.get('id'):
                    # Проверяем наличие IMEI в уникальных идентификаторах
                    if 'uids' in unit and unit['uids']:
                        for uid in unit['uids']:
                            if uid.get('id') and len(uid['id']) >= 15:  # IMEI обычно 15 цифр
                                filtered_units.append({
                                    'id': unit['id'],
                                    'name': unit['nm'],
                                    'imei': uid['id']
                                })
                                break
                    # Если нет в uids, ищем в других полях
                    elif 'uid' in unit and unit['uid'] and len(unit['uid']) >= 15:
                        filtered_units.append({
                            'id': unit['id'],
                            'name': unit['nm'],
                            'imei': unit['uid']
                        })
            
            logger.info(f"Отфильтровано объектов с IMEI: {len(filtered_units)}")
            return filtered_units
            
        except Exception as e:
            logger.error(f"Get all units failed: {e}")
            return []

    def get_messages_direct(self, unit_id, time_from, time_to):
        """Прямое получение сообщений"""
        try:
            from_ts = int(time_from.timestamp())
            to_ts = int(time_to.timestamp())
            
            params = {
                "itemId": unit_id,
                "timeFrom": from_ts,
                "timeTo": to_ts,
                "flags": 1,
                "flagsMask": 65281,
                "loadCount": 500000  # Лимит на объект
            }
            
            result = self.call_api("messages/load_interval", params)
            
            if not result:
                return []
            
            if isinstance(result, dict) and 'messages' in result:
                return result['messages']
            elif isinstance(result, list):
                return result
            else:
                return []
                
        except Exception as e:
            logger.warning(f"Get messages for unit {unit_id} failed: {e}")
            return []

    def export_unit_messages(self, unit, time_from, time_to, export_dir):
        """Экспорт сообщений для одного объекта"""
        try:
            logger.info(f"Обработка объекта: {unit['name']} (IMEI: {unit['imei']})")
            
            messages = self.get_messages_direct(unit['id'], time_from, time_to)
            
            if not messages:
                logger.warning(f"Нет сообщений для объекта {unit['name']}")
                return False
            
            # Создаем папку для объекта
            unit_dir = os.path.join(export_dir, f"{unit['imei']}")
            os.makedirs(unit_dir, exist_ok=True)
            
            # Сохраняем в ZIP
            filename = f"{unit['imei']}_track.zip"
            filepath = os.path.join(unit_dir, filename)
            
            success = self.export_to_zip(messages, filepath, unit, time_from, time_to)
            
            if success:
                logger.info(f"Успешно экспортирован {unit['name']}: {len(messages)} сообщений")
                return True
            else:
                logger.error(f"Ошибка экспорта для {unit['name']}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка обработки объекта {unit['name']}: {e}")
            return False

    def export_to_zip(self, messages, filename, unit_info, time_from, time_to):
        """Экспорт сообщений в ZIP-архив"""
        try:
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Основной файл с сообщениями
                messages_json = json.dumps(messages, indent=2, ensure_ascii=False, default=str)
                zipf.writestr('messages.json', messages_json)
                
                # Информация об экспорте
                info_content = f"Экспорт данных Wialon\n"
                info_content += f"Время создания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                info_content += f"ID объекта: {unit_info.get('id', 'N/A')}\n"
                info_content += f"Название: {unit_info.get('name', 'N/A')}\n"
                info_content += f"IMEI: {unit_info.get('imei', 'N/A')}\n"
                info_content += f"Период: {time_from.strftime('%Y-%m-%d')} - {time_to.strftime('%Y-%m-%d')}\n"
                info_content += f"Количество сообщений: {len(messages)}\n"
                zipf.writestr('info.txt', info_content)
                
                # CSV с позициями
                csv_content = "Дата,Время,Широта,Долгота,Скорость,Высота,Курс,Спутники\n"
                for msg in messages:
                    if isinstance(msg, dict) and 'pos' in msg:
                        pos = msg['pos']
                        dt = datetime.fromtimestamp(msg.get('t', 0))
                        csv_content += f"{dt.strftime('%Y-%m-%d')},{dt.strftime('%H:%M:%S')},{pos.get('y', '')},{pos.get('x', '')},{pos.get('s', '')},{pos.get('z', '')},{pos.get('c', '')},{pos.get('sc', '')}\n"
                zipf.writestr('positions.csv', csv_content)
            
            # Сохраняем файл
            zip_buffer.seek(0)
            with open(filename, 'wb') as f:
                f.write(zip_buffer.read())
            
            return True
            
        except Exception as e:
            logger.error(f"Export to ZIP failed: {e}")
            return False

class BatchExportApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Wialon Batch Exporter")
        self.root.geometry("1200x800")
        
        self.exporter = WialonBatchExporter()
        self.export_thread = None
        self.is_exporting = False
        
        self.create_widgets()
        self.auto_login()

    def create_widgets(self):
        """Создание интерфейса"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Date range frame
        date_frame = ttk.LabelFrame(main_frame, text="Период для выгрузки", padding="5")
        date_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Устанавливаем период за последний год
        default_end = datetime.now()
        default_start = default_end - timedelta(days=365)
        
        ttk.Label(date_frame, text="Начало периода:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.start_date = tk.StringVar(value=default_start.strftime("%Y-%m-%d"))
        start_entry = ttk.Entry(date_frame, textvariable=self.start_date, width=12)
        start_entry.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        ttk.Label(date_frame, text="Конец периода:").grid(row=0, column=2, sticky=tk.W, padx=(20, 5))
        self.end_date = tk.StringVar(value=default_end.strftime("%Y-%m-%d"))
        end_entry = ttk.Entry(date_frame, textvariable=self.end_date, width=12)
        end_entry.grid(row=0, column=3, sticky=tk.W, padx=5)
        
        ttk.Label(date_frame, text="(гггг-мм-дд)").grid(row=0, column=4, sticky=tk.W, padx=(5, 0))
        
        # Export settings frame
        settings_frame = ttk.LabelFrame(main_frame, text="Настройки выгрузки", padding="5")
        settings_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(settings_frame, text="Папка для сохранения:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.export_dir = tk.StringVar(value=os.path.join(os.getcwd(), "wialon_export"))
        ttk.Label(settings_frame, textvariable=self.export_dir, width=50).grid(row=0, column=1, sticky=tk.W, padx=5)
        
        ttk.Button(settings_frame, text="Выбрать", command=self.select_export_dir).grid(row=0, column=2, padx=5)
        
        # Delay between units
        ttk.Label(settings_frame, text="Задержка между объектами (сек):").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        self.delay_var = tk.StringVar(value="5")
        delay_entry = ttk.Entry(settings_frame, textvariable=self.delay_var, width=10)
        delay_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=(10, 0))
        
        # Control buttons frame
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.start_btn = ttk.Button(control_frame, text="Запустить пакетную выгрузку", command=self.start_batch_export)
        self.start_btn.grid(row=0, column=0, padx=5)
        
        self.stop_btn = ttk.Button(control_frame, text="Остановить выгрузку", command=self.stop_batch_export, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=5)
        
        # Progress
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Status
        self.status_var = tk.StringVar(value="Готов к работе")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_label.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Results and log
        results_frame = ttk.LabelFrame(main_frame, text="Лог выгрузки и статистика", padding="5")
        results_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Create notebook for tabs
        notebook = ttk.Notebook(results_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # Log tab
        log_frame = ttk.Frame(notebook)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        notebook.add(log_frame, text="Лог")
        
        # Statistics tab
        stats_frame = ttk.Frame(notebook)
        self.stats_text = scrolledtext.ScrolledText(stats_frame, height=20, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        notebook.add(stats_frame, text="Статистика")
        
        # Configure weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(5, weight=1)

    def select_export_dir(self):
        """Выбор папки для экспорта"""
        directory = filedialog.askdirectory(title="Выберите папку для сохранения")
        if directory:
            self.export_dir.set(directory)

    def auto_login(self):
        """Автоматическая авторизация"""
        self.status_var.set("Авторизация...")
        self.progress.start()
        
        def login_thread():
            try:
                success = self.exporter.login()
                if success:
                    self.status_var.set("Авторизация успешна! Готов к выгрузке")
                else:
                    raise Exception("Авторизация не удалась")
                    
            except Exception as e:
                error_msg = str(e)
                self.status_var.set("Ошибка авторизации")
                messagebox.showerror("Ошибка авторизации", error_msg)
                
            finally:
                self.progress.stop()
        
        threading.Thread(target=login_thread, daemon=True).start()

    def start_batch_export(self):
        """Запуск пакетной выгрузки"""
        if self.is_exporting:
            return
            
        export_dir = self.export_dir.get()
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            
        # Получаем даты из интерфейса
        try:
            time_from = datetime.strptime(self.start_date.get(), "%Y-%m-%d")
            time_to = datetime.strptime(self.end_date.get(), "%Y-%m-%d")
            delay = float(self.delay_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Неверный формат данных")
            return
            
        if time_to < time_from:
            messagebox.showerror("Ошибка", "Конечная дата не может быть раньше начальной")
            return
            
        # Подтверждение для длительной операции
        if not messagebox.askyesno("Подтверждение", 
                                  f"Запустить пакетную выгрузку для ВСЕХ объектов?\n"
                                  f"Период: {time_from.strftime('%d.%m.%Y')} - {time_to.strftime('%d.%m.%Y')}\n"
                                  f"Операция может занять несколько дней!\n"
                                  f"Продолжить?"):
            return
            
        self.is_exporting = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Запуск пакетной выгрузки...")
        self.progress.start()
        
        # Запуск в отдельном потоке
        self.export_thread = threading.Thread(
            target=self.run_batch_export,
            args=(time_from, time_to, export_dir, delay),
            daemon=True
        )
        self.export_thread.start()

    def stop_batch_export(self):
        """Остановка выгрузки"""
        if self.is_exporting:
            self.is_exporting = False
            self.status_var.set("Остановка выгрузки...")
            self.exporter.is_running = False

    def run_batch_export(self, time_from, time_to, export_dir, delay):
        """Запуск пакетной выгрузки в фоновом режиме"""
        try:
            self.log_message("Начало пакетной выгрузки...")
            self.log_message(f"Период: {time_from.strftime('%Y-%m-%d')} - {time_to.strftime('%Y-%m-%d')}")
            self.log_message(f"Папка: {export_dir}")
            
            # Получаем все объекты
            self.log_message("Получение списка объектов...")
            units = self.exporter.get_all_units()
            
            if not units:
                self.log_message("Не найдено объектов для выгрузки")
                return
                
            self.log_message(f"Найдено объектов: {len(units)}")
            
            # Создаем файл статистики
            stats_file = os.path.join(export_dir, "export_statistics.json")
            statistics = {
                "start_time": datetime.now().isoformat(),
                "time_from": time_from.isoformat(),
                "time_to": time_to.isoformat(),
                "total_units": len(units),
                "processed_units": 0,
                "successful_units": 0,
                "failed_units": 0,
                "units": []
            }
            
            # Обрабатываем каждый объект
            self.exporter.is_running = True
            for i, unit in enumerate(units):
                if not self.exporter.is_running:
                    self.log_message("Выгрузка остановлена пользователем")
                    break
                    
                self.status_var.set(f"Обработка {i+1}/{len(units)}: {unit['name']}")
                self.log_message(f"[{i+1}/{len(units)}] Обработка: {unit['name']} (IMEI: {unit['imei']})")
                
                try:
                    success = self.exporter.export_unit_messages(unit, time_from, time_to, export_dir)
                    
                    if success:
                        statistics["successful_units"] += 1
                        unit_stat = {
                            "imei": unit["imei"],
                            "name": unit["name"],
                            "status": "success",
                            "time": datetime.now().isoformat()
                        }
                    else:
                        statistics["failed_units"] += 1
                        unit_stat = {
                            "imei": unit["imei"],
                            "name": unit["name"],
                            "status": "failed",
                            "time": datetime.now().isoformat()
                        }
                    
                    statistics["units"].append(unit_stat)
                    statistics["processed_units"] += 1
                    
                    # Сохраняем статистику после каждого объекта
                    with open(stats_file, 'w', encoding='utf-8') as f:
                        json.dump(statistics, f, indent=2, ensure_ascii=False)
                    
                    # Обновляем статистику в UI
                    self.update_statistics(statistics)
                    
                except Exception as e:
                    self.log_message(f"Ошибка при обработке {unit['name']}: {str(e)}")
                    statistics["failed_units"] += 1
                    statistics["processed_units"] += 1
                
                # Задержка между объектами
                if i < len(units) - 1 and self.exporter.is_running:
                    self.log_message(f"Пауза {delay} секунд...")
                    for sec in range(int(delay)):
                        if not self.exporter.is_running:
                            break
                        time.sleep(1)
                        self.status_var.set(f"Пауза... {delay - sec} сек")
            
            # Завершение
            statistics["end_time"] = datetime.now().isoformat()
            statistics["duration"] = str(datetime.fromisoformat(statistics["end_time"]) - 
                                       datetime.fromisoformat(statistics["start_time"]))
            
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(statistics, f, indent=2, ensure_ascii=False)
            
            self.log_message("Пакетная выгрузка завершена!")
            self.log_message(f"Успешно: {statistics['successful_units']}")
            self.log_message(f"Ошибки: {statistics['failed_units']}")
            self.update_statistics(statistics)
            
        except Exception as e:
            self.log_message(f"Критическая ошибка: {str(e)}")
        finally:
            self.is_exporting = False
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.status_var.set("Выгрузка завершена")
            self.progress.stop()

    def log_message(self, message):
        """Добавление сообщения в лог"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        def update_log():
            self.log_text.insert(tk.END, log_entry)
            self.log_text.see(tk.END)
            
        self.root.after(0, update_log)
        logger.info(message)

    def update_statistics(self, statistics):
        """Обновление статистики"""
        stats_text = f"СТАТИСТИКА ВЫГРУЗКИ\n\n"
        stats_text += f"Время начала: {statistics['start_time']}\n"
        stats_text += f"Всего объектов: {statistics['total_units']}\n"
        stats_text += f"Обработано: {statistics['processed_units']}\n"
        stats_text += f"Успешно: {statistics['successful_units']}\n"
        stats_text += f"Ошибки: {statistics['failed_units']}\n"
        
        if 'end_time' in statistics:
            stats_text += f"Время завершения: {statistics['end_time']}\n"
            stats_text += f"Длительность: {statistics['duration']}\n"
        
        def update_stats():
            self.stats_text.delete(1.0, tk.END)
            self.stats_text.insert(tk.END, stats_text)
            
        self.root.after(0, update_stats)

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