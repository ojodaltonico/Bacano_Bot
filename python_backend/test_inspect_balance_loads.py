from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

import mysql.connector
from mysql.connector import Error

from config_manager import load_config


DEBUG_DIR = Path(__file__).resolve().parent / "debug"
OUTPUT_PATH = DEBUG_DIR / "balance_load_schema_sample.json"
TARGET_TABLES = ("clientes", "recargas", "historial", "articulos")
RECARGA_KEYWORDS = ("recarga", "carga", "saldo", "adelanto")


def connect_read_only():
    config = load_config()
    db_config = config.get("database", {})
    required = ("host", "user", "password", "database")
    missing = [key for key in required if not str(db_config.get(key) or "").strip()]
    if missing:
        raise RuntimeError(
            "Faltan campos requeridos en 'database': " + ", ".join(missing)
        )

    return mysql.connector.connect(
        host=db_config["host"],
        user=db_config["user"],
        password=db_config["password"],
        database=db_config["database"],
        charset="utf8",
        use_unicode=True,
        collation="utf8_general_ci",
        autocommit=True,
    )


def fetch_all_dict(cursor, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor.execute(query, params)
    return list(cursor.fetchall())


def fetch_one_dict(cursor, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    cursor.execute(query, params)
    return cursor.fetchone()


def get_table_schema(cursor, table_name: str) -> dict[str, Any]:
    columns = fetch_all_dict(
        cursor,
        """
        SELECT
            COLUMN_NAME,
            COLUMN_TYPE,
            IS_NULLABLE,
            COLUMN_DEFAULT,
            COLUMN_KEY,
            EXTRA
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table_name,),
    )
    indexes = fetch_all_dict(
        cursor,
        """
        SELECT
            INDEX_NAME,
            NON_UNIQUE,
            SEQ_IN_INDEX,
            COLUMN_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        ORDER BY INDEX_NAME, SEQ_IN_INDEX
        """,
        (table_name,),
    )
    return {
        "table_name": table_name,
        "exists": bool(columns),
        "columns": [
            {
                "name": row["COLUMN_NAME"],
                "type": row["COLUMN_TYPE"],
                "nullable": row["IS_NULLABLE"] == "YES",
                "default": row["COLUMN_DEFAULT"],
                "primary_key": row["COLUMN_KEY"] == "PRI",
                "auto_increment": "auto_increment" in str(row["EXTRA"] or "").lower(),
                "extra": row["EXTRA"],
            }
            for row in columns
        ],
        "indexes": [
            {
                "name": row["INDEX_NAME"],
                "non_unique": bool(row["NON_UNIQUE"]),
                "seq_in_index": row["SEQ_IN_INDEX"],
                "column_name": row["COLUMN_NAME"],
            }
            for row in indexes
        ],
    }


def get_column_names(schema: dict[str, Any]) -> list[str]:
    return [column["name"] for column in schema.get("columns", [])]


def find_column(columns: list[str], keywords: tuple[str, ...]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for column in columns:
        name = column.lower()
        if all(keyword in name for keyword in keywords):
            return column
    for keyword in keywords:
        for lowered_name, original in lowered.items():
            if keyword in lowered_name:
                return original
    return None


def find_numeric_like_columns(columns: list[str], keywords: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for column in columns:
        lowered = column.lower()
        if any(keyword in lowered for keyword in keywords):
            found.append(column)
    return found


def choose_order_column(schema: dict[str, Any]) -> str | None:
    columns = get_column_names(schema)
    candidates = (
        ("fecha",),
        ("fch",),
        ("id",),
        ("indice",),
        ("nro",),
        ("numero",),
    )
    for keywords in candidates:
        column = find_column(columns, keywords)
        if column:
            return column
    return columns[0] if columns else None


def choose_select_columns(columns: list[str]) -> list[str]:
    selected = []
    sensitive_keywords = (
        "nombre",
        "razon",
        "mail",
        "email",
        "tel",
        "telefono",
        "cel",
        "dni",
        "tarjeta",
        "direccion",
        "domic",
    )
    for column in columns:
        lowered = column.lower()
        if any(keyword in lowered for keyword in sensitive_keywords):
            continue
        selected.append(column)
    return selected or columns[:]


def build_recent_query(table_name: str, schema: dict[str, Any], limit: int) -> str:
    columns = choose_select_columns(get_column_names(schema))
    order_column = choose_order_column(schema)
    quoted_columns = ", ".join(f"`{column}`" for column in columns)
    query = f"SELECT {quoted_columns} FROM `{table_name}`"
    if order_column:
        query += f" ORDER BY `{order_column}` DESC"
    query += f" LIMIT {int(limit)}"
    return query


def decimal_to_native(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def sanitize_value(column_name: str, value: Any) -> Any:
    if value is None:
        return None
    lowered = column_name.lower()
    if any(
        keyword in lowered
        for keyword in ("nombre", "razon", "mail", "email", "tel", "telefono", "cel", "dni")
    ):
        return "[REDACTED]"
    return decimal_to_native(value)


def sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: sanitize_value(key, value) for key, value in row.items()}


def get_recent_rows(cursor, table_name: str, schema: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    query = build_recent_query(table_name, schema, limit)
    rows = fetch_all_dict(cursor, query)
    return [sanitize_row(row) for row in rows]


def get_matching_articles(cursor, schema: dict[str, Any]) -> list[dict[str, Any]]:
    columns = get_column_names(schema)
    name_columns = find_numeric_like_columns(columns, ("nombre", "detalle", "descripcion", "art"))
    if not name_columns:
        return []

    where_parts = []
    params: list[str] = []
    for column in name_columns:
        for keyword in RECARGA_KEYWORDS:
            where_parts.append(f"LOWER(COALESCE(`{column}`, '')) LIKE %s")
            params.append(f"%{keyword}%")

    query = (
        "SELECT "
        + ", ".join(f"`{column}`" for column in choose_select_columns(columns))
        + " FROM `articulos` WHERE "
        + " OR ".join(where_parts)
        + " LIMIT 50"
    )
    rows = fetch_all_dict(cursor, query, tuple(params))
    return [sanitize_row(row) for row in rows]


def row_matches_keywords(row: dict[str, Any]) -> bool:
    for value in row.values():
        text = str(value or "").lower()
        if any(keyword in text for keyword in RECARGA_KEYWORDS):
            return True
    return False


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def pick_field(row: dict[str, Any], keywords: tuple[str, ...]) -> tuple[str | None, Any]:
    for column, value in row.items():
        lowered = column.lower()
        if all(keyword in lowered for keyword in keywords):
            return column, value
    for keyword in keywords:
        for column, value in row.items():
            if keyword in column.lower():
                return column, value
    return None, None


def filter_historial_candidates(
    historial_rows: list[dict[str, Any]],
    article_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    article_codes = {
        value
        for row in article_rows
        for key, value in row.items()
        if value is not None and ("id" in key.lower() or "art" in key.lower() or "cod" in key.lower())
    }
    candidates: list[dict[str, Any]] = []
    for row in historial_rows:
        if row_matches_keywords(row):
            candidates.append(row)
            continue
        for value in row.values():
            if value in article_codes:
                candidates.append(row)
                break
    return candidates


def relate_loads(
    recargas_rows: list[dict[str, Any]],
    historial_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for recarga in recargas_rows:
        recarga_cliente_col, recarga_cliente = pick_field(recarga, ("cli",))
        if recarga_cliente is None:
            recarga_cliente_col, recarga_cliente = pick_field(recarga, ("cliente",))
        recarga_importe_col, recarga_importe = pick_field(recarga, ("imp",))
        if recarga_importe is None:
            recarga_importe_col, recarga_importe = pick_field(recarga, ("total",))
        recarga_caja_col, recarga_caja = pick_field(recarga, ("caja",))
        recarga_fecha_col, recarga_fecha = pick_field(recarga, ("fecha",))
        recarga_importe_decimal = to_decimal(recarga_importe)

        for historial in historial_rows:
            historial_cliente_col, historial_cliente = pick_field(historial, ("cli",))
            if historial_cliente is None:
                historial_cliente_col, historial_cliente = pick_field(historial, ("cliente",))
            historial_total_col, historial_total = pick_field(historial, ("total",))
            historial_unitario_col, historial_unitario = pick_field(historial, ("precio",))
            historial_caja_col, historial_caja = pick_field(historial, ("caja",))
            historial_fecha_col, historial_fecha = pick_field(historial, ("fecha",))
            historial_total_decimal = to_decimal(historial_total)
            if historial_total_decimal is None:
                historial_total_decimal = to_decimal(historial_unitario)

            same_client = (
                recarga_cliente is not None
                and historial_cliente is not None
                and str(recarga_cliente) == str(historial_cliente)
            )
            same_amount = (
                recarga_importe_decimal is not None
                and historial_total_decimal is not None
                and recarga_importe_decimal == historial_total_decimal
            )
            same_box = (
                recarga_caja is not None
                and historial_caja is not None
                and str(recarga_caja) == str(historial_caja)
            )

            if same_client and same_amount:
                matches.append(
                    {
                        "recargas": {
                            "fecha": recarga_fecha,
                            "cliente_id": recarga_cliente,
                            "caja": recarga_caja,
                            "tipo_pago": pick_field(recarga, ("pago",))[1],
                            "importe": recarga_importe,
                            "fecha_col": recarga_fecha_col,
                            "cliente_col": recarga_cliente_col,
                            "caja_col": recarga_caja_col,
                            "importe_col": recarga_importe_col,
                        },
                        "historial": {
                            "fecha": historial_fecha,
                            "cliente_id": historial_cliente,
                            "caja": historial_caja,
                            "articulo_id": pick_field(historial, ("art",))[1],
                            "detalle": pick_field(historial, ("det",))[1],
                            "cantidad": pick_field(historial, ("cant",))[1],
                            "unitario": historial_unitario,
                            "total": historial_total,
                            "fecha_col": historial_fecha_col,
                            "cliente_col": historial_cliente_col,
                            "caja_col": historial_caja_col,
                            "total_col": historial_total_col or historial_unitario_col,
                        },
                        "same_box": same_box,
                    }
                )
                break
    return matches[:5]


def find_box_related_structures(cursor) -> list[dict[str, Any]]:
    table_matches = fetch_all_dict(
        cursor,
        """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND (
            LOWER(TABLE_NAME) LIKE %s OR
            LOWER(TABLE_NAME) LIKE %s OR
            LOWER(TABLE_NAME) LIKE %s OR
            LOWER(TABLE_NAME) LIKE %s OR
            LOWER(TABLE_NAME) LIKE %s
          )
        ORDER BY TABLE_NAME
        """,
        ("%kiosco%", "%instagram%", "%entrada%", "%computadora%", "%caja%"),
    )

    column_matches = fetch_all_dict(
        cursor,
        """
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND (
            LOWER(COLUMN_NAME) LIKE %s OR
            LOWER(COLUMN_NAME) LIKE %s OR
            LOWER(COLUMN_NAME) LIKE %s OR
            LOWER(COLUMN_NAME) LIKE %s OR
            LOWER(COLUMN_NAME) LIKE %s
          )
        ORDER BY TABLE_NAME, COLUMN_NAME
        """,
        ("%kiosco%", "%instagram%", "%entrada%", "%computadora%", "%caja%"),
    )

    return {
        "tables": table_matches,
        "columns": column_matches,
    }


def summarize_box_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for row in rows:
        caja_col, caja_value = pick_field(row, ("caja",))
        if caja_col:
            summaries.append(
                {
                    "column": caja_col,
                    "example_value": caja_value,
                    "example_type": type(caja_value).__name__,
                }
            )
    return summaries[:10]


def print_schema(schema: dict[str, Any]) -> None:
    print(f"Tabla: {schema['table_name']}")
    if not schema["exists"]:
        print("No existe o no es visible.")
        return
    print("Columnas:")
    for column in schema["columns"]:
        print(
            f"- {column['name']} | {column['type']} | "
            f"NULL={'si' if column['nullable'] else 'no'} | "
            f"default={column['default']} | "
            f"PK={'si' if column['primary_key'] else 'no'} | "
            f"auto_increment={'si' if column['auto_increment'] else 'no'}"
        )
    print("Indices:")
    for index in schema["indexes"]:
        print(
            f"- {index['name']} | non_unique={'si' if index['non_unique'] else 'no'} | "
            f"seq={index['seq_in_index']} | columna={index['column_name']}"
        )


def print_rows(title: str, rows: list[dict[str, Any]]) -> None:
    print(title)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, default=str))


def print_related_matches(matches: list[dict[str, Any]]) -> None:
    for match in matches:
        print("RECARGAS")
        print(f"fecha: {match['recargas']['fecha']}")
        print(f"cliente_id: {match['recargas']['cliente_id']}")
        print(f"caja: {match['recargas']['caja']}")
        print(f"tipo_pago: {match['recargas']['tipo_pago']}")
        print(f"importe: {match['recargas']['importe']}")
        print("HISTORIAL")
        print(f"fecha: {match['historial']['fecha']}")
        print(f"cliente_id: {match['historial']['cliente_id']}")
        print(f"caja: {match['historial']['caja']}")
        print(f"articulo_id: {match['historial']['articulo_id']}")
        print(f"detalle: {match['historial']['detalle']}")
        print(f"cantidad: {match['historial']['cantidad']}")
        print(f"unitario: {match['historial']['unitario']}")
        print(f"total: {match['historial']['total']}")


def main() -> None:
    connection = None
    cursor = None
    try:
        connection = connect_read_only()
        cursor = connection.cursor(dictionary=True)

        schemas = {table: get_table_schema(cursor, table) for table in TARGET_TABLES}
        for schema in schemas.values():
            print_schema(schema)

        recargas_rows = (
            get_recent_rows(cursor, "recargas", schemas["recargas"], 20)
            if schemas["recargas"]["exists"]
            else []
        )
        historial_rows = (
            get_recent_rows(cursor, "historial", schemas["historial"], 100)
            if schemas["historial"]["exists"]
            else []
        )
        article_rows = (
            get_matching_articles(cursor, schemas["articulos"])
            if schemas["articulos"]["exists"]
            else []
        )
        historial_candidates = filter_historial_candidates(historial_rows, article_rows)
        related_matches = relate_loads(recargas_rows, historial_candidates)
        box_structures = find_box_related_structures(cursor)
        box_examples = summarize_box_examples(recargas_rows + historial_rows)

        print_rows("Ultimos 20 registros de recargas:", recargas_rows)
        print_rows("Articulos relacionados con recarga:", article_rows)
        print_rows("Candidatos de historial relacionados con recarga:", historial_candidates[:20])
        print_related_matches(related_matches)
        print("Posibles estructuras relacionadas con caja:")
        print(json.dumps(box_structures, ensure_ascii=False, default=str))
        print("Ejemplos de valores de caja:")
        print(json.dumps(box_examples, ensure_ascii=False, default=str))

        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        sample = {
            "schemas": schemas,
            "recargas_sample": recargas_rows,
            "historial_candidates_sample": historial_candidates[:20],
            "articulos_related_sample": article_rows[:20],
            "related_matches_sample": related_matches,
            "box_related_structures": box_structures,
            "box_examples": box_examples,
        }
        OUTPUT_PATH.write_text(
            json.dumps(sample, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"Muestra anonimizada guardada en: {OUTPUT_PATH}")

    except Error as exc:
        print(f"Error MySQL: {exc}")
        raise SystemExit(1)
    except Exception as exc:
        print(str(exc) or "Error inesperado.")
        raise SystemExit(1)
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    main()
