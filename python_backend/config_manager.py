import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "database": {
        "host": "IP",
        "user": "User",
        "password": "Pass",
        "database": "BD"
        # ⚠️ ELIMINAR charset y collation para MySQL 5.1
    },
    "promotions": [
        "🎉 2x1 en tragos los jueves",
        "🍕 30% off en pizzas los viernes",
        "🎊 Entrada gratis en cumpleaños",
        "🥳 Descuento del 20% para estudiantes"
    ]
}


def load_config():
    """Cargar configuración desde archivo JSON"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Asegurarse de que no tenga charset incompatible
                if 'database' in config and 'charset' in config['database']:
                    config['database'].pop('charset', None)
                    config['database'].pop('collation', None)
                return config
        else:
            # Crear archivo de configuración por defecto
            save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG
    except Exception as e:
        logger.error(f"Error cargando configuración: {e}")
        return DEFAULT_CONFIG


def save_config(config):
    """Guardar configuración en archivo JSON"""
    try:
        # Asegurarse de no guardar charset incompatible
        if 'database' in config:
            config['database'].pop('charset', None)
            config['database'].pop('collation', None)

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error guardando configuración: {e}")
        return False


def get_db_config():
    """Obtener configuración de base de datos"""
    config = load_config()
    return config.get("database", {})


def get_promotions():
    """Obtener lista de promociones"""
    config = load_config()
    promotions = config.get("promotions", [])
    return "\n".join(f"• {promo}" for promo in promotions)


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