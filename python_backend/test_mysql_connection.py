from __future__ import annotations

import socket
import sys
from typing import Any

import mysql.connector
from mysql.connector import Error

from config_manager import load_config


DEFAULT_MYSQL_PORT = 3306
CONNECT_TIMEOUT_SECONDS = 10


def mask_user(user: str) -> str:
    if not user:
        return ""
    if len(user) <= 2:
        return "*" * len(user)
    return user[0] + ("*" * (len(user) - 2)) + user[-1]


def load_database_config() -> dict[str, Any]:
    config = load_config()
    db_config = config.get("database", {})
    required = ("host", "user", "password", "database")
    missing = [key for key in required if not str(db_config.get(key) or "").strip()]
    if missing:
        raise RuntimeError(
            "Faltan campos requeridos en 'database': " + ", ".join(missing)
        )
    return db_config


def test_tcp_connection(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_SECONDS):
            return True, "Puerto accesible"
    except OSError as exc:
        return False, str(exc)


def test_mysql_login(db_config: dict[str, Any]) -> tuple[bool, str]:
    connection = None
    try:
        connection = mysql.connector.connect(
            host=db_config["host"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"],
            charset="utf8",
            use_unicode=True,
            collation="utf8_general_ci",
            connection_timeout=CONNECT_TIMEOUT_SECONDS,
            autocommit=True,
        )
        if not connection.is_connected():
            return False, "MySQL no reporto una conexion activa."
        return True, "Conexion MySQL exitosa"
    except Error as exc:
        return False, str(exc)
    finally:
        if connection is not None and connection.is_connected():
            connection.close()


def main() -> None:
    try:
        db_config = load_database_config()
        host = str(db_config["host"])
        port = int(db_config.get("port") or DEFAULT_MYSQL_PORT)
        database_name = str(db_config["database"])
        masked_user = mask_user(str(db_config["user"]))

        print("Prueba de conexion MySQL")
        print(f"Host: {host}")
        print(f"Puerto: {port}")
        print(f"Base: {database_name}")
        print(f"Usuario: {masked_user}")

        tcp_ok, tcp_message = test_tcp_connection(host, port)
        print(f"TCP accesible: {'si' if tcp_ok else 'no'}")
        if not tcp_ok:
            print(f"Detalle TCP: {tcp_message}")
            raise SystemExit(1)

        mysql_ok, mysql_message = test_mysql_login(db_config)
        print(f"Login MySQL: {'si' if mysql_ok else 'no'}")
        print(f"Detalle: {mysql_message}")
        raise SystemExit(0 if mysql_ok else 1)

    except Exception as exc:
        print(str(exc) or "Error inesperado.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
