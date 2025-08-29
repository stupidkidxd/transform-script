# messages_export.py
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
from config import WLN_TOKEN

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WialonMessagesExporter:
    def __init__(self):
        self.base_url = "https://hst-api.wialon.com"
        self.sid = None
        self.token = WLN_TOKEN

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
            logger.info(f"API call: {svc} with params: {params}")
            response = requests.get(url, timeout=300)  # Увеличиваем таймаут для больших запросов
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

    def find_unit_by_imei(self, imei):
        """Поиск объекта по IMEI"""
        try:
            spec = {
                "itemsType": "avl_unit",
                "propName": "sys_unique_id",
                "propValueMask": imei,
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
            
            if not result or 'items' not in result or not result['items']:
                raise Exception(f"Объект с IMEI {imei} не найден")
            
            unit = result['items'][0]
            logger.info(f"Found unit: ID={unit['id']}, Name={unit['nm']}")
            return unit
            
        except Exception as e:
            logger.error(f"Find unit failed: {e}")
            raise Exception(f"Find unit failed: {e}")

    def load_messages_interval(self, unit_id, time_from, time_to):
        """Загрузка сообщений за интервал времени (первый этап)"""
        try:
            from_ts = int(time_from.timestamp())
            to_ts = int(time_to.timestamp())
            
            logger.info(f"Загрузка сообщений для unit_id {unit_id} с {from_ts} по {to_ts}")
            
            # Параметры согласно документации поддержки
            params = {
                "itemId": unit_id,
                "timeFrom": from_ts,
                "timeTo": to_ts,
                "flags": 1,          # Сообщения с позицией
                "flagsMask": 65281,   # 0xFF01 - для сообщений с данными и позицией
                "loadCount": 0        # Загрузить все сообщения
            }
            
            result = self.call_api("messages/load_interval", params)
            
            if not result:
                logger.warning(f"Нет сообщений за период {time_from} - {time_to}")
                return None
            
            # Анализируем структуру ответа
            logger.info(f"Структура ответа: {type(result)}")
            if isinstance(result, dict):
                logger.info(f"Ключи в ответе: {list(result.keys())}")
                if 'messages' in result:
                    messages = result['messages']
                    logger.info(f"Найдено сообщений: {len(messages)}")
                    return messages
                elif 'count' in result:
                    logger.info(f"Количество сообщений: {result['count']}")
                    return result
            elif isinstance(result, list):
                logger.info(f"Получен список из {len(result)} элементов")
                return result
            else:
                logger.warning(f"Неизвестный формат ответа: {type(result)}")
                return result
                
        except Exception as e:
            logger.error(f"Load messages interval failed: {e}")
            return None

    def get_messages(self, index_from=0, index_to=1000):
        """Получение конкретных сообщений из загруженного набора (второй этап)"""
        try:
            params = {
                "indexFrom": index_from,
                "indexTo": index_to
            }
            
            result = self.call_api("messages/get_messages", params)
            
            if not result:
                return []
            
            # Анализируем структуру ответа
            if isinstance(result, dict) and 'messages' in result:
                return result['messages']
            elif isinstance(result, list):
                return result
            else:
                logger.warning(f"Неизвестный формат ответa get_messages: {type(result)}")
                return []
                
        except Exception as e:
            logger.error(f"Get messages failed: {e}")
            return []

    def get_messages_direct(self, unit_id, time_from, time_to):
        """Прямое получение сообщений без двухэтапного процесса"""
        try:
            from_ts = int(time_from.timestamp())
            to_ts = int(time_to.timestamp())
            
            logger.info(f"Прямая загрузка сообщений для unit_id {unit_id}")
            
            # Пробуем разные комбинации параметров с лимитом 1,000,000 сообщений
            params_list = [
                {
                    "itemId": unit_id,
                    "timeFrom": from_ts,
                    "timeTo": to_ts,
                    "flags": 1,
                    "flagsMask": 65281,
                    "loadCount": 1000000  # Увеличено до 1,000,000
                },
                {
                    "itemId": unit_id,
                    "timeFrom": from_ts,
                    "timeTo": to_ts,
                    "flags": 0xFFFFFFFF,
                    "flagsMask": 0xFFFFFFFF,
                    "loadCount": 1000000  # Увеличено до 1,000,000
                },
                {
                    "itemId": unit_id,
                    "timeFrom": from_ts,
                    "timeTo": to_ts,
                    "flags": 0x1,
                    "flagsMask": 0x1,
                    "loadCount": 1000000  # Увеличено до 1,000,000
                }
            ]
            
            for i, params in enumerate(params_list):
                try:
                    logger.info(f"Попытка {i+1} с параметрами: {params}")
                    result = self.call_api("messages/load_interval", params)
                    
                    if result:
                        if isinstance(result, dict) and 'messages' in result:
                            messages = result['messages']
                            logger.info(f"Успешно получено {len(messages)} сообщений")
                            return messages
                        elif isinstance(result, list):
                            logger.info(f"Успешно получено {len(result)} сообщений")
                            return result
                        elif isinstance(result, dict) and 'count' in result:
                            # Если есть только счетчик, пробуем получить сообщения
                            count = result['count']
                            logger.info(f"Найдено {count} сообщений, получение...")
                            if count > 0:
                                messages = self.get_messages(0, min(count, 1000000) - 1)  # Увеличено до 1,000,000
                                return messages
                except Exception as e:
                    logger.warning(f"Попытка {i+1} не удалась: {e}")
                    continue
            
            return []
            
        except Exception as e:
            logger.error(f"Get messages direct failed: {e}")
            return []

    def get_all_messages(self, unit_id, time_from, time_to):
        """Получение всех сообщений"""
        try:
            # Пробуем прямой метод
            messages = self.get_messages_direct(unit_id, time_from, time_to)
            
            if messages:
                logger.info(f"Прямой метод: получено {len(messages)} сообщений")
                return messages
            
            # Если прямой метод не сработал, пробуем двухэтапный
            logger.info("Пробуем двухэтапный метод...")
            load_result = self.load_messages_interval(unit_id, time_from, time_to)
            
            if not load_result:
                return []
            
            # Определяем общее количество сообщений
            if isinstance(load_result, dict) and 'count' in load_result:
                total_messages = load_result['count']
            elif isinstance(load_result, list):
                total_messages = len(load_result)
            else:
                total_messages = 0
            
            logger.info(f"Всего сообщений для получения: {total_messages}")
            
            if total_messages == 0:
                return []
            
            # Получаем сообщения пачками
            all_messages = []
            batch_size = 5000  # Увеличиваем размер пачки для ускорения
            
            for i in range(0, min(total_messages, 1000000), batch_size):  # Ограничение 1,000,000
                batch_from = i
                batch_to = min(i + batch_size - 1, total_messages - 1, 1000000 - 1)  # Ограничение 1,000,000
                
                logger.info(f"Получение сообщений с {batch_from} по {batch_to}")
                
                messages_batch = self.get_messages(batch_from, batch_to)
                if messages_batch:
                    all_messages.extend(messages_batch)
                
                # Небольшая пауза между запросами
                time.sleep(0.05)
                
                # Обновляем прогресс каждые 50,000 сообщений
                if len(all_messages) % 50000 == 0:
                    logger.info(f"Получено {len(all_messages)} сообщений...")
            
            logger.info(f"Всего получено сообщений: {len(all_messages)}")
            return all_messages
            
        except Exception as e:
            logger.error(f"Get all messages failed: {e}")
            return []

    def export_to_zip(self, messages, filename, unit_info, time_from, time_to):
        """Экспорт сообщений в ZIP-архив"""
        try:
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. Сообщения в формате JSON
                messages_json = json.dumps(messages, indent=2, ensure_ascii=False, default=str)
                zipf.writestr('messages.json', messages_json)
                
                # 2. Информация об экспорте
                info_content = f"Экспорт данных Wialon\n"
                info_content += f"Время создания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                info_content += f"ID объекта: {unit_info.get('id', 'N/A')}\n"
                info_content += f"Название: {unit_info.get('name', 'N/A')}\n"
                info_content += f"IMEI: {unit_info.get('imei', 'N/A')}\n"
                info_content += f"Период: {time_from.strftime('%Y-%m-%d')} - {time_to.strftime('%Y-%m-%d')}\n"
                info_content += f"Количество сообщений: {len(messages)}\n"
                
                # Анализ данных
                if messages:
                    first_msg = messages[0] if isinstance(messages[0], dict) else {}
                    last_msg = messages[-1] if isinstance(messages[-1], dict) else {}
                    info_content += f"Первое сообщение: {datetime.fromtimestamp(first_msg.get('t', 0)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                    info_content += f"Последнее сообщение: {datetime.fromtimestamp(last_msg.get('t', 0)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                
                zipf.writestr('info.txt', info_content)
                
                # 3. CSV с позициями
                csv_content = "Дата,Время,Широта,Долгота,Скорость,Высота,Курс,Спутники\n"
                position_count = 0
                
                for msg in messages:
                    if isinstance(msg, dict) and 'pos' in msg:
                        pos = msg['pos']
                        dt = datetime.fromtimestamp(msg.get('t', 0))
                        csv_content += f"{dt.strftime('%Y-%m-%d')},{dt.strftime('%H:%M:%S')},{pos.get('y', '')},{pos.get('x', '')},{pos.get('s', '')},{pos.get('z', '')},{pos.get('c', '')},{pos.get('sc', '')}\n"
                        position_count += 1
                
                zipf.writestr('positions.csv', csv_content)
                
                # 4. Debug информация
                debug_info = {
                    "export_time": datetime.now().isoformat(),
                    "unit_info": unit_info,
                    "time_range": {
                        "from": time_from.isoformat(),
                        "to": time_to.isoformat(),
                        "days": (time_to - time_from).days
                    },
                    "messages_count": len(messages),
                    "positions_count": position_count,
                    "max_messages_limit": 1000000  # Добавлена информация о лимите
                }
                zipf.writestr('debug_info.json', json.dumps(debug_info, indent=2))
            
            # Сохраняем файл
            zip_buffer.seek(0)
            with open(filename, 'wb') as f:
                f.write(zip_buffer.read())
            
            return True
            
        except Exception as e:
            logger.error(f"Export to ZIP failed: {e}")
            return False

class MessagesExportApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Wialon Messages Exporter")
        self.root.geometry("1000x700")
        
        self.exporter = WialonMessagesExporter()
        self.current_unit_id = None
        self.current_unit_name = None
        self.current_imei = None
        
        self.create_widgets()
        self.auto_login()

    def create_widgets(self):
        """Создание интерфейса"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # IMEI input frame
        imei_frame = ttk.LabelFrame(main_frame, text="Поиск объекта по IMEI", padding="5")
        imei_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(imei_frame, text="IMEI устройства:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.imei_entry = ttk.Entry(imei_frame, width=20)
        self.imei_entry.grid(row=0, column=1, sticky=tk.W, padx=5)
        self.imei_entry.insert(0, "352093085741501")
        
        self.find_btn = ttk.Button(imei_frame, text="Найти объект", command=self.find_unit)
        self.find_btn.grid(row=0, column=2, padx=5)
        
        # Date range frame
        date_frame = ttk.LabelFrame(main_frame, text="Период для выгрузки", padding="5")
        date_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Устанавливаем период по умолчанию (последние 7 дней)
        default_end = datetime.now()
        default_start = default_end - timedelta(days=7)
        
        ttk.Label(date_frame, text="Начало периода:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.start_date = tk.StringVar(value=default_start.strftime("%Y-%m-%d"))
        start_entry = ttk.Entry(date_frame, textvariable=self.start_date, width=12)
        start_entry.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        ttk.Label(date_frame, text="Конец периода:").grid(row=0, column=2, sticky=tk.W, padx=(20, 5))
        self.end_date = tk.StringVar(value=default_end.strftime("%Y-%m-%d"))
        end_entry = ttk.Entry(date_frame, textvariable=self.end_date, width=12)
        end_entry.grid(row=0, column=3, sticky=tk.W, padx=5)
        
        ttk.Label(date_frame, text="(гггг-мм-дд)").grid(row=0, column=4, sticky=tk.W, padx=(5, 0))
        
        # Info label about limit
        limit_label = ttk.Label(date_frame, text="Лимит: до 1,000,000 сообщений за один экспорт", 
                               foreground="blue", font=('Arial', 9))
        limit_label.grid(row=1, column=0, columnspan=5, sticky=tk.W, pady=(5, 0))
        
        # Export frame
        export_frame = ttk.Frame(main_frame)
        export_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.export_btn = ttk.Button(export_frame, text="Выгрузить сообщения (до 1M)", command=self.export_data)
        self.export_btn.grid(row=0, column=0, padx=5)
        
        ttk.Label(export_frame, text="Папка для сохранения:").grid(row=0, column=1, sticky=tk.W, padx=(20, 5))
        self.export_dir = tk.StringVar(value=os.getcwd())
        ttk.Label(export_frame, textvariable=self.export_dir, width=30).grid(row=0, column=2, sticky=tk.W, padx=5)
        
        ttk.Button(export_frame, text="Выбрать", command=self.select_export_dir).grid(row=0, column=3, padx=5)
        
        # Progress
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Status
        self.status_var = tk.StringVar(value="Готов к работе")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_label.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Results
        results_frame = ttk.LabelFrame(main_frame, text="Информация и результаты", padding="5")
        results_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.info_text = scrolledtext.ScrolledText(results_frame, height=15, wrap=tk.WORD)
        self.info_text.pack(fill=tk.BOTH, expand=True)
        
        # Configure weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(5, weight=1)
        
        self.set_ui_state(False)

    def set_ui_state(self, enabled):
        """Установка состояния UI"""
        state = "normal" if enabled else "disabled"
        self.find_btn.config(state=state)
        self.export_btn.config(state=state)

    def select_export_dir(self):
        """Выбор папки для экспорта"""
        directory = filedialog.askdirectory(title="Выберите папку для сохранения")
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
                self.status_var.set("Авторизация успешна! Введите IMEI")
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

    def find_unit(self):
        """Поиск объекта по IMEI"""
        imei = self.imei_entry.get().strip()
        if not imei:
            messagebox.showerror("Ошибка", "Введите IMEI устройства")
            return
            
        self.status_var.set(f"Поиск объекта с IMEI {imei}...")
        self.set_ui_state(False)
        self.progress.start()
        self.root.update()
        
        try:
            unit = self.exporter.find_unit_by_imei(imei)
            self.current_unit_id = unit['id']
            self.current_unit_name = unit['nm']
            self.current_imei = imei
            
            # Показываем информацию об объекте
            start_date = datetime.strptime(self.start_date.get(), "%Y-%m-%d")
            end_date = datetime.strptime(self.end_date.get(), "%Y-%m-%d")
            days_count = (end_date - start_date).days
            
            info_text = f"Найден объект:\n"
            info_text += f"ID: {self.current_unit_id}\n"
            info_text += f"Название: {self.current_unit_name}\n"
            info_text += f"IMEI: {imei}\n\n"
            info_text += f"Период для выгрузки:\n"
            info_text += f"Начало: {start_date.strftime('%d.%m.%Y')}\n"
            info_text += f"Конец: {end_date.strftime('%d.%m.%Y')}\n"
            info_text += f"Дней: {days_count}\n"
            info_text += f"Лимит сообщений: до 1,000,000\n\n"
            info_text += f"Готов к выгрузке сообщений\n"
            
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, info_text)
            
            self.status_var.set(f"Найден: {self.current_unit_name}")
            
        except Exception as e:
            error_msg = f"Ошибка поиска: {str(e)}"
            logger.error(error_msg)
            self.status_var.set("Ошибка поиска")
            messagebox.showerror("Ошибка поиска", error_msg)
            
        finally:
            self.progress.stop()
            self.set_ui_state(True)

    def export_data(self):
        """Выгрузка сообщений"""
        if not self.current_unit_id:
            messagebox.showerror("Ошибка", "Сначала найдите объект по IMEI")
            return
            
        export_dir = self.export_dir.get()
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            
        # Получаем даты из интерфейса
        try:
            time_from = datetime.strptime(self.start_date.get(), "%Y-%m-%d")
            time_to = datetime.strptime(self.end_date.get(), "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Ошибка", "Неверный формат даты")
            return
            
        if time_to < time_from:
            messagebox.showerror("Ошибка", "Конечная дата не может быть раньше начальной")
            return
            
        # Предупреждение о большом периоде
        days_count = (time_to - time_from).days
        if days_count > 30:
            if not messagebox.askyesno("Подтверждение", 
                                      f"Выбран большой период: {days_count} дней.\n"
                                      f"Может содержать до 1,000,000 сообщений.\n"
                                      f"Выгрузка может занять длительное время.\n"
                                      f"Продолжить выгрузку?"):
                return
            
        self.status_var.set("Получение сообщений...")
        self.set_ui_state(False)
        self.progress.start()
        self.root.update()
        
        try:
            # Получаем сообщения
            messages = self.exporter.get_all_messages(self.current_unit_id, time_from, time_to)
            
            if not messages:
                # Пробуем получить тестовые данные для отладки
                self.status_var.set("Пробуем альтернативный метод...")
                messages = self.exporter.get_messages_direct(self.current_unit_id, time_from, time_to)
            
            if not messages:
                raise Exception("Не удалось получить сообщения за указанный период")
            
            # Сохраняем в ZIP-архив с простым именем
            filename = f"{self.current_imei}_track.zip"  # Простое имя файла
            filepath = os.path.join(export_dir, filename)
            
            unit_info = {
                'id': self.current_unit_id,
                'name': self.current_unit_name,
                'imei': self.current_imei
            }
            
            success = self.exporter.export_to_zip(messages, filepath, unit_info, time_from, time_to)
            
            if success:
                # Показываем статистику
                info_text = f"Выгрузка завершена успешно!\n\n"
                info_text += f"Объект: {self.current_unit_name}\n"
                info_text += f"IMEI: {self.current_imei}\n"
                info_text += f"Период: {time_from.strftime('%d.%m.%Y')} - {time_to.strftime('%d.%m.%Y')}\n"
                info_text += f"Дней: {days_count}\n"
                info_text += f"Сообщений: {len(messages):,}\n".replace(",", " ")
                info_text += f"Файл: {filename}\n"
                info_text += f"Размер: {os.path.getsize(filepath) / 1024 / 1024:.2f} MB\n\n"
                info_text += f"Содержимое архива:\n"
                info_text += f"- messages.json (данные в JSON)\n"
                info_text += f"- positions.csv (таблица с координатами)\n"
                info_text += f"- info.txt (информация об экспорте)\n"
                info_text += f"- debug_info.json (отладочная информация)\n"
                
                self.info_text.delete(1.0, tk.END)
                self.info_text.insert(tk.END, info_text)
                
                self.status_var.set(f"Выгружено {len(messages):,} сообщений".replace(",", " "))
                messagebox.showinfo("Успех", 
                                  f"Создан архив:\n{filename}\n\n"
                                  f"Сообщений: {len(messages):,}\n".replace(",", " ") +
                                  f"Период: {time_from.strftime('%d.%m.%Y')} - {time_to.strftime('%d.%m.%Y')}\n"
                                  f"Размер: {os.path.getsize(filepath) / 1024 / 1024:.2f} MB")
            else:
                raise Exception("Не удалось создать архив")
            
        except Exception as e:
            error_msg = f"Ошибка выгрузки: {str(e)}"
            logger.error(error_msg)
            self.status_var.set("Ошибка выгрузки")
            messagebox.showerror("Ошибка выгрузки", error_msg)
            
        finally:
            self.progress.stop()
            self.set_ui_state(True)

def main():
    root = tk.Tk()
    app = MessagesExportApp(root)
    
    # Center window
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_width()) // 2
    y = (root.winfo_screenheight() - root.winfo_height()) // 2
    root.geometry(f"+{x}+{y}")
    
    root.mainloop()

if __name__ == "__main__":
    main()