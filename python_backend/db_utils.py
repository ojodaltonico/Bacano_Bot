import mysql.connector
from mysql.connector import Error
import logging
from config_manager import get_db_config

logger = logging.getLogger(__name__)


def get_connection():
    """Crear conexión a la base de datos compatible con MySQL 5.1"""
    try:
        db_config = get_db_config()

        # Configuración compatible con MySQL 5.1
        connection_config = {
            'host': db_config['host'],
            'user': db_config['user'],
            'password': db_config['password'],
            'database': db_config['database'],
            'charset': 'utf8',  # MySQL 5.1 solo soporta utf8, no utf8mb4
            'use_unicode': True,
            'collation': 'utf8_general_ci'
        }

        connection = mysql.connector.connect(**connection_config)
        logger.info("✅ Conectado a MySQL 5.1 con charset=utf8")
        return connection

    except Error as e:
        logger.error(f"❌ Error conectando a MySQL: {e}")
        return None


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