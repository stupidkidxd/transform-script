import logging
from wialon_api import wialon_api
from database import create_database, save_raw_unit, get_all_raw_units
from transformer import transform_wialon_unit_to_standard, save_standard_unit
import sqlite3
from config import DATABASE_NAME

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Wialon export and standardization process...")

    # Инициализируем БД
    create_database()

    try:
        # 1. Логинимся в Wialon
        wialon_api.login()

        # 2. Получаем список всех юнитов
        logger.info("Fetching list of all units...")
        units_list_result = wialon_api.get_units_list()
        if not units_list_result or 'items' not in units_list_result:
            logger.error("Failed to get units list or list is empty.")
            return

        units = units_list_result['items']
        logger.info(f"Found {len(units)} units.")

        # 3. Для каждого юнита получаем детальную информацию и сохраняем в БД
        for unit in units:
            unit_id = unit['id']
            unit_name = unit['nm']
            logger.info(f"Processing unit: {unit_name} (ID: {unit_id})")

            try:
                unit_details = wialon_api.get_unit_details(unit_id)
                # Сохраняем сырые данные
                save_raw_unit(unit_id, unit_name, unit_details)
                logger.info(f"Saved raw data for unit ID: {unit_id}")

            except Exception as e:
                logger.error(f"Failed to fetch or save details for unit {unit_id}: {e}")
                continue # Продолжаем со следующим юнитом

        logger.info("Finished fetching all raw data.")

        # 4. Трансформация: читаем сырые данные из БД и преобразуем их
        logger.info("Starting data transformation...")
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        raw_units = get_all_raw_units()
        for unit_id, raw_data in raw_units:
            try:
                standard_data = transform_wialon_unit_to_standard(raw_data)
                save_standard_unit(standard_data, cursor)
                logger.info(f"Transformed and saved standard data for unit ID: {unit_id}")
            except Exception as e:
                logger.error(f"Failed to transform unit {unit_id}: {e}")
                continue

        conn.commit()
        conn.close()
        logger.info("Data transformation completed successfully.")

    except Exception as e:
        logger.critical(f"A critical error occurred: {e}")
    finally:
        # Всегда пытаемся разлогиниться
        try:
            wialon_api.logout()
        except:
            pass
        logger.info("Process finished.")

if __name__ == "__main__":
    main()