import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Buscar config.json en diferentes ubicaciones
CONFIG_PATHS = [
    "config.json",  # Raíz del proyecto
    "python_backend/config.json",  # Carpeta python_backend
    os.path.join(os.path.dirname(__file__), "config.json"),  # Mismo directorio
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"),  # Directorio padre
]

DEFAULT_CONFIG = {
    "database": {
        "host": "localhost",
        "user": "root",
        "password": "",
        "database": "bacano_db"
    },
    "promotions": [
        "🎊 Champagne para cumpleañeros",
        "🎊 Entrada Free para cumpleañeros"
    ]
}


def find_config_file():
    """Buscar archivo de configuración en varias ubicaciones"""
    for config_path in CONFIG_PATHS:
        if os.path.exists(config_path):
            logger.info(f"✅ Configuración encontrada en: {config_path}")
            return config_path
    return None


def load_config():
    """Cargar configuración desde archivo JSON"""
    config_file = find_config_file()

    if config_file:
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Asegurarse de que no tenga charset incompatible
            if 'database' in config:
                config['database'].pop('charset', None)
                config['database'].pop('collation', None)

            logger.info("✅ Configuración cargada exitosamente")
            return config

        except Exception as e:
            logger.error(f"❌ Error cargando configuración: {e}")
            return DEFAULT_CONFIG
    else:
        # Crear archivo de configuración por defecto en raíz
        logger.warning("⚠️ No se encontró config.json. Creando uno por defecto...")
        try:
            with open("config.json", 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            logger.info("✅ Config.json creado por defecto en la raíz")
            return DEFAULT_CONFIG
        except Exception as e:
            logger.error(f"❌ Error creando config.json: {e}")
            return DEFAULT_CONFIG


def save_config(config):
    """Guardar configuración en archivo JSON"""
    try:
        # Asegurarse de no guardar charset incompatible
        if 'database' in config:
            config['database'].pop('charset', None)
            config['database'].pop('collation', None)

        # Guardar siempre en la raíz
        with open("config.json", 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info("✅ Configuración guardada en config.json")
        return True

    except Exception as e:
        logger.error(f"❌ Error guardando configuración: {e}")
        return False


# Funciones auxiliares
def get_db_config():
    """Obtener configuración de base de datos"""
    config = load_config()
    return config.get("database", {})


def get_promotions():
    """Obtener lista de promociones"""
    config = load_config()
    promotions = config.get("promotions", [])
    return promotions


def update_promotions(new_promotions):
    """Actualizar lista de promociones"""
    config = load_config()
    config["promotions"] = new_promotions
    return save_config(config)


def update_db_config(db_config):
    """Actualizar configuración de base de datos"""
    config = load_config()
    # Eliminar charset incompatible antes de guardar
    db_config.pop('charset', None)
    db_config.pop('collation', None)
    config["database"] = db_config
    return save_config(config)