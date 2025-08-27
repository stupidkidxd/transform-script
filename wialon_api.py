import requests
import json
import logging
from config import WLN_CMS_BASE_URL, WLN_USERNAME, WLN_PASSWORD

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WialonCMSAPI:
    def __init__(self):
        self.base_url = WLN_CMS_BASE_URL.rstrip('/')
        self.sid = None
        self.user_id = None
        self.session = requests.Session()

    def _call_api(self, svc, params):
        """Базовый метод для вызова API Wialon CMS"""
        url = f"{self.base_url}/wialon/ajax.html"
        
        payload = {
            "svc": svc,
            "params": json.dumps(params),
            "sid": self.sid
        }
        
        try:
            logger.debug(f"Calling API: {svc} with params: {params}")
            response = self.session.post(url, data=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"API response: {data}")
            
            # Обработка ошибок Wialon API
            if isinstance(data, dict) and data.get("error"):
                error_code = data["error"]
                error_msg = f"Wialon API Error {error_code}"
                if "reason" in data:
                    error_msg += f": {data['reason']}"
                raise Exception(error_msg)
                
            return data
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"HTTP request failed: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"JSON decode error: {e}")

    def login(self):
        """Авторизация в Wialon CMS"""
        url = f"{self.base_url}/wialon/ajax.html"
        
        login_params = {
            "user": WLN_USERNAME,
            "password": WLN_PASSWORD,
            "params": ""
        }
        
        payload = {
            "svc": "core/login",
            "params": json.dumps(login_params)
        }
        
        try:
            logger.info(f"Logging in to {self.base_url} as {WLN_USERNAME}")
            response = self.session.post(url, data=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"Login response: {data}")
            
            if data.get("error"):
                error_msg = f"Login failed: {data['error']}"
                if "reason" in data:
                    error_msg += f" - {data['reason']}"
                raise Exception(error_msg)
                
            self.sid = data.get("eid") or data.get("sid")
            
            if not self.sid:
                raise Exception("Session ID not received in login response")
                
            # Получаем информацию о пользователе
            user_info = self._call_api("core/get_user_data", {})
            self.user_id = user_info.get("id")
                
            logger.info(f"Login successful. SID: {self.sid}, User ID: {self.user_id}")
            return self.sid
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Login request failed: {e}")

    def logout(self):
        """Завершение сессии"""
        if self.sid:
            try:
                self._call_api("core/logout", {})
                logger.info("Logged out successfully.")
            except Exception as e:
                logger.warning(f"Logout failed: {e}")
            finally:
                self.sid = None
                self.user_id = None

    def get_units_list(self):
        """Получение списка всех юнитов"""
        params = {
            "force": 1,
            "flags": 0x1,  # Basic flags
            "from": 0,
            "to": 0
        }
        return self._call_api("core/search_items", params)

    def get_unit_details(self, unit_id):
        """Получение детальной информации о конкретном юните"""
        params = {
            "id": unit_id,
            "flags": 0x7FFFFFFF  # Все флаги для полных данных
        }
        return self._call_api("core/search_item", params)
    
    def search_unit_by_imei(self, imei):
        """Поиск юнита по IMEI"""
        search_params = {
            "itemsType": "avl_unit",
            "propName": "sys_name", 
            "propValueMask": f"*{imei}*",
            "sortType": "sys_name"
        }
        
        params = {
            "force": 1,
            "flags": 0x1,
            "from": 0,
            "to": 0,
            "params": json.dumps(search_params)
        }
        
        return self._call_api("core/search_items", params)
    
    def search_unit_by_uid(self, uid):
        """Поиск юнита по UID (обычно здесь IMEI)"""
        search_params = {
            "itemsType": "avl_unit",
            "propName": "sys_unique_id",  # Поиск по уникальному ID
            "propValueMask": f"*{uid}*",
            "sortType": "sys_name"
        }
        
        params = {
            "force": 1,
            "flags": 0x1,
            "from": 0,
            "to": 0,
            "params": json.dumps(search_params)
        }
        
        return self._call_api("core/search_items", params)

# Создаем экземпляр API
wialon_api = WialonCMSAPI()