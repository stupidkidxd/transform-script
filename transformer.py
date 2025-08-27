import json

def transform_wialon_unit_to_standard(raw_unit_data):
    # Извлекаем данные из сложной структуры Wialon
    general_info = raw_unit_data.get('general', {})
    hw_config = raw_unit_data.get('hwConfig', {})
    counters = raw_unit_data.get('counters', {})
    sensors = raw_unit_data.get('sensors', [])
    fields = raw_unit_data.get('fields', [])

    # 1. Извлекаем базовую информацию
    name = general_info.get('n', '').strip()
    phone_number = general_info.get('ph', '')
    # Парсим IMEI из uid. В вашем примере uid="352093085741501" - это похоже на IMEI.
    imei = general_info.get('uid', '')

    # 2. Обрабатываем датчики. Приводим их к стандартному списку.
    standard_sensors = []
    for sensor in sensors:
        standard_sensor = {
            'id': sensor.get('id'),
            'name': sensor.get('n'),
            'type': sensor.get('t'),
            'measure_unit': sensor.get('m'),
            'parameter': sensor.get('p'), # Код параметра в сообщениях (например, 'pwr_ext')
            # 'value': None # Текущее значение не хранится в конфиге, только в данных сообщений
        }
        standard_sensors.append(standard_sensor)

    # 3. Обрабатываем произвольные поля (fields)
    standard_fields = {}
    for field in fields:
        field_name = field.get('n')
        field_value = field.get('v')
        standard_fields[field_name] = field_value

    # 4. Собираем ВСЁ в стандартный JSON
    # Это ядро стандарта. Структуру можно менять под свои нужды.
    standard_data = {
        'source_system': 'wialon',
        'source_unit_id': raw_unit_data.get('mu'), # ID юнита в Wialon
        'name': name,
        'phone_number': phone_number,
        'imei': imei,
        'hardware': hw_config.get('hw'),
        'counters': counters, # Сохраняем всю структуру счетчиков как есть
        'sensors': standard_sensors,
        'custom_fields': standard_fields,
        # Можно добавить другие поля: 'icon', 'healthCheck', 'reportProps' и т.д.
        # 'original_data': raw_unit_data # Опционально: можно сохранить оригинал для ссылок
    }

    return standard_data

def save_standard_unit(standard_data, db_cursor):
    """Сохраняет стандартизированные данные в базу"""
    source_unit_id = standard_data['source_unit_id']
    standard_json = json.dumps(standard_data, ensure_ascii=False, indent=2)

    # Вставляем или обновляем запись
    db_cursor.execute('''
        INSERT OR REPLACE INTO standard_units 
        (source_unit_id, name, phone_number, imei, vehicle_model, driver_name, standard_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        source_unit_id,
        standard_data['name'],
        standard_data['phone_number'],
        standard_data['imei'],
        standard_data['vehicle_model'],
        standard_data['driver_name'],
        standard_json
    ))