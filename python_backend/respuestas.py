from db_utils import get_user_by_dni, get_user_by_phone
from config_manager import get_promotions
import logging

logger = logging.getLogger(__name__)


def responder(mensaje, numero, estados):
    mensaje = mensaje.lower().strip()

    # ✅ **VERIFICAR PRIMERO SI QUIERE VOLVER AL MENÚ**
    if mensaje in ['hola', 'menu', 'menú', 'volver', 'inicio', 'salir']:
        estados[numero] = {"estado": "menu_principal"}
        logger.info(f"🔄 Reiniciando estado para {numero} a menu_principal")
        return mostrar_menu_principal()

    # Si no existe el estado, crear uno nuevo
    if numero not in estados:
        estados[numero] = {"estado": "menu_principal"}
        return mostrar_menu_principal()

    estado_actual = estados[numero].get("estado", "menu_principal")

    logger.info(f"📊 Estado actual para {numero}: {estado_actual}, mensaje: {mensaje}")

    try:
        # Menú principal
        if estado_actual == "menu_principal":
            if mensaje == '1' or mensaje == 'saldo' or mensaje == 'consultar saldo':
                estados[numero] = {"estado": "esperando_confirmacion_telefono"}
                raw_number = numero.split('@')[0] if '@' in numero else numero
                phone_number = ''.join(filter(str.isdigit, raw_number))[-11:]

                logger.info(f"🔍 Buscando usuario por teléfono: {phone_number}")

                user_info = get_user_by_phone(phone_number)
                if user_info:
                    estados[numero]["user_info"] = user_info
                    return f"🙌 Te tengo registrado como {user_info['nombre']}. ¿Está bien? (Sí/No)\n\n💡 Escribí 'hola' para volver al menú principal"
                else:
                    estados[numero] = {"estado": "esperando_dni"}
                    return "👀 No tenemos tu tel registrado. Ingresá tu DNI (sin puntos ni espacios):\n\n💡 Escribí 'hola' para volver al menú principal"

            elif mensaje == '2':
                return '🎟️ Ingresá en el link 👉 bacanoclub.com.ar\n\n💡 Escribí "hola" para volver al menú principal'

            elif mensaje == '3':
                promotions = get_promotions()
                return f"🚀 Promo Time en Bacano Club:\n{promotions}\n\n💡 Escribí 'hola' para volver al menú principal"

            else:
                return "❌ Opción no válida. " + mostrar_menu_principal()

        # Confirmación de teléfono
        elif estado_actual == "esperando_confirmacion_telefono":
            if mensaje in ['sí', 'si', 's']:
                user_info = estados[numero].get("user_info")
                if user_info:
                    estados[numero] = {"estado": "menu_principal"}
                    return f"💸 Tu saldo actual: {user_info['adelantos']} 😎🔥"
                else:
                    estados[numero] = {"estado": "esperando_dni"}
                    return "⚠️ Algo no cuadra. Ingresá tu DNI (sin puntos ni espacios):\n\n💡 Escribí 'hola' para volver al menú principal"

            elif mensaje in ['no', 'n']:
                estados[numero] = {"estado": "esperando_dni"}
                return "🔍 Escribí tu DNI (sin puntos ni espacios):\n\n💡 Escribí 'hola' para volver al menú principal"

            else:
                return "😆 Vamos, jugátela… Sí o No. 😂\n\n💡 Escribí 'hola' para volver al menú principal"

        # Esperando DNI - **CORREGIDO: verificar "hola" aquí también**
        elif estado_actual == "esperando_dni":
            # Si llega "hola" aquí, ya debería haberse capturado arriba, pero por si acaso
            if mensaje in ['hola', 'menu', 'menú', 'volver']:
                estados[numero] = {"estado": "menu_principal"}
                return "🔁 Volviendo al menú principal...\n\n" + mostrar_menu_principal()

            if mensaje.isdigit():
                logger.info(f"🔍 Buscando usuario por DNI: {mensaje}")
                user_info = get_user_by_dni(mensaje)
                if user_info:
                    estados[numero] = {"estado": "menu_principal"}
                    return f"💸 Tu saldo actual: {user_info['adelantos']} 😎🔥\n\n" + mostrar_menu_principal()
                else:
                    return "🚨 Ups, no encontramos tu DNI. Verificá los números y probá otra vez. 😬\n\n💡 Escribí 'hola' para volver al menú principal"
            else:
                return "❌ Por favor, ingresá solo números (sin puntos ni espacios).\n\n💡 Escribí 'hola' para volver al menú principal"

        # Cualquier otro estado desconocido
        else:
            estados[numero] = {"estado": "menu_principal"}
            return "🔁 Reiniciando al menú principal...\n\n" + mostrar_menu_principal()

    except Exception as e:
        logger.error(f"❌ Error procesando mensaje: {str(e)}")
        estados[numero] = {"estado": "menu_principal"}
        return "❌ Ocurrió un error. " + mostrar_menu_principal()


def mostrar_menu_principal():
    return '''💃🕺 ¡Bienvenido a Bacano Club! 🎉🔥
¿Qué querés hacer hoy? 🤩
1️⃣ Consultar saldo 💰
2️⃣ Comprar entrada 🎟️
3️⃣ Ver promociones 💥

💡 Siempre podés escribir "hola" para volver a este menú'''