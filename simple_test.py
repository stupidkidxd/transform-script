# simple_test.py
import requests
import json
import urllib.parse
from config import WLN_TOKEN

def test_api():
    """Тестирование API"""
    base_url = "https://hst-api.wialon.com"
    token = WLN_TOKEN
    
    print("1. Тестируем авторизацию...")
    auth_url = f'{base_url}/wialon/ajax.html?svc=token/login&params={{"token":"{token}"}}'
    
    try:
        response = requests.get(auth_url, timeout=30)
        data = response.json()
        print(f"   Ответ: {data}")
        
        if data.get("error"):
            print(f"   Ошибка авторизации: {data.get('reason')}")
            return False
            
        sid = data.get("eid") or data.get("sid")
        if not sid:
            print("   Не получили SID")
            return False
            
        print(f"   Авторизация успешна, SID: {sid[:10]}...")
        
        # 2. Правильный формат запроса с spec
        print("2. Тестируем правильный формат запроса...")
        
        # Правильный формат spec
        spec = {
            "itemsType": "avl_unit",
            "propName": "sys_name", 
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
        
        # Кодируем параметры
        params_json = json.dumps(params)
        params_encoded = urllib.parse.quote(params_json)
        
        search_url = f'{base_url}/wialon/ajax.html?svc=core/search_items&params={params_encoded}&sid={sid}'
        print(f"   URL: {search_url}")
        
        response = requests.get(search_url, timeout=30)
        data = response.json()
        print(f"   Response: {data}")
        
        if not data.get("error") and 'items' in data:
            print(f"   УСПЕХ! Найдено объектов: {len(data['items'])}")
            if data['items']:
                print(f"   Первый объект: {data['items'][0]}")
            return True
        else:
            print(f"   Ошибка: {data.get('reason')}")
            return False
        
    except Exception as e:
        print(f"   Ошибка: {e}")
        return False

if __name__ == "__main__":
    print("Запуск теста API Wialon...")
    success = test_api()
    print(f"\nРезультат: {'УСПЕХ' if success else 'ОШИБКА'}")