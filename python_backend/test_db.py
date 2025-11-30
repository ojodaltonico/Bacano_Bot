from db_utils import get_user_by_dni, get_user_by_phone
import logging

# Configurar logging para ver detalles
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def test_mysql_51():
    print("🔍 Probando MySQL 5.1 con datos reales...")

    # Probar DNI que SÍ existe
    dni_existente = "32701001"
    print(f"\n🔍 Buscando DNI existente: {dni_existente}")
    usuario = get_user_by_dni(dni_existente)
    print(f"✅ Resultado: {usuario}")

    # Probar DNI que NO existe
    dni_inexistente = "99999999"
    print(f"\n🔍 Buscando DNI inexistente: {dni_inexistente}")
    usuario = get_user_by_dni(dni_inexistente)
    print(f"✅ Resultado: {usuario}")

    # Probar teléfono que SÍ existe (usa un teléfono real de tu BD)
    telefono_existente = "69634422268"  # Cambia por un teléfono real
    print(f"\n🔍 Buscando teléfono existente: {telefono_existente}")
    usuario = get_user_by_phone(telefono_existente)
    print(f"✅ Resultado: {usuario}")

    # Probar teléfono que NO existe
    telefono_inexistente = "9999999999"
    print(f"\n🔍 Buscando teléfono inexistente: {telefono_inexistente}")
    usuario = get_user_by_phone(telefono_inexistente)
    print(f"✅ Resultado: {usuario}")


if __name__ == "__main__":
    test_mysql_51()