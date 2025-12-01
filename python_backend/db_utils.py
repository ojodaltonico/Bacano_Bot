import mysql.connector
from mysql.connector import Error
import logging

# Importar dinámicamente config_manager
import importlib.util
import os
import sys

# Añadir directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)


def get_config():
    """Obtener configuración dinámicamente"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), "config_manager.py")

        if os.path.exists(config_path):
            spec = importlib.util.spec_from_file_location("config_manager", config_path)
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)

            return config_module.get_db_config()
        else:
            logger.error("❌ No se encontró config_manager.py")
            return {}
    except Exception as e:
        logger.error(f"❌ Error obteniendo configuración: {e}")
        return {}


def get_connection():
    """Crear conexión a la base de datos compatible con MySQL 5.1"""
    try:
        db_config = get_config()

        if not db_config:
            logger.error("❌ No se pudo obtener configuración de BD")
            return None

        # Configuración compatible con MySQL 5.1
        connection_config = {
            'host': db_config.get('host', 'localhost'),
            'user': db_config.get('user', 'root'),
            'password': db_config.get('password', ''),
            'database': db_config.get('database', ''),
            'charset': 'utf8',  # MySQL 5.1 solo soporta utf8, no utf8mb4
            'use_unicode': True,
            'collation': 'utf8_general_ci'
        }

        connection = mysql.connector.connect(**connection_config)
        logger.info("✅ Conectado a MySQL")
        return connection

    except Error as e:
        logger.error(f"❌ Error conectando a MySQL: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}")
        return None


# ... (resto del código igual)


def get_user_by_dni(dni):
    """Buscar usuario por DNI"""
    connection = get_connection()
    if not connection:
        logger.error("❌ No se pudo conectar a la base de datos")
        return None

    try:
        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT Cli_Razon AS nombre, Cli_Adelantos AS adelantos 
            FROM clientes 
            WHERE Cli_DNI = %s
        """
        logger.info(f"🔍 Ejecutando query: {query} con DNI: {dni}")
        cursor.execute(query, (dni,))
        result = cursor.fetchone()

        logger.info(f"✅ Búsqueda por DNI {dni}: {result is not None}")
        if result:
            logger.info(f"📋 Usuario encontrado: {result}")
        else:
            logger.info(f"❌ Usuario no encontrado para DNI: {dni}")

        return result

    except Error as e:
        logger.error(f"❌ Error en get_user_by_dni: {e}")
        return None
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


def get_user_by_phone(phone):
    """Buscar usuario por teléfono"""
    connection = get_connection()
    if not connection:
        logger.error("❌ No se pudo conectar a la base de datos")
        return None

    try:
        # Limpiar número (solo mantener dígitos)
        formatted_phone = ''.join(filter(str.isdigit, phone))
        logger.info(f"🔍 Buscando por teléfono formateado: {formatted_phone}")

        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT Cli_Razon AS nombre, Cli_Adelantos AS adelantos 
            FROM clientes 
            WHERE REPLACE(REPLACE(Cli_Tel2, ' ', ''), '+', '') = %s
        """
        logger.info(f"🔍 Ejecutando query: {query}")
        cursor.execute(query, (formatted_phone,))
        result = cursor.fetchone()

        logger.info(f"✅ Búsqueda por teléfono {formatted_phone}: {result is not None}")
        if result:
            logger.info(f"📋 Usuario encontrado: {result}")
        else:
            logger.info(f"❌ Usuario no encontrado para teléfono: {formatted_phone}")

        return result

    except Error as e:
        logger.error(f"❌ Error en get_user_by_phone: {e}")
        return None
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()