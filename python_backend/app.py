from flask import Flask, request, jsonify
import logging
import unicodedata

from respuestas import responder
from services.order_monitor_service import OrderMonitorService
from utils.phone_utils import normalize_argentine_phone


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
estados = {}
ticket_order_monitor = OrderMonitorService()


def _normalize_incoming_phone(numero):
    raw_number = str(numero or "")
    if "@" in raw_number:
        raw_number = raw_number.split("@", 1)[0]
    digits = "".join(char for char in raw_number if char.isdigit())
    return normalize_argentine_phone(digits)


def _mask_phone(numero):
    digits = "".join(char for char in str(numero or "") if char.isdigit())
    return f"{'*' * max(4, len(digits) - 4)}{digits[-4:]}" if digits else "****"


@app.route("/", methods=["GET"])
def home():
    return jsonify(
        {
            "status": "online",
            "service": "WhatsApp Bot Backend",
            "endpoints": {
                "webhook": "POST /webhook",
                "health": "GET /health",
            },
        }
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json or {}
        numero = data.get("from")
        mensaje = str(data.get("message") or "").strip()

        logger.info("Mensaje recibido de %s: %s", _mask_phone(numero), mensaje)

        normalized_phone = _normalize_incoming_phone(numero)
        normalized_text = "".join(
            char for char in unicodedata.normalize("NFD", mensaje.lower())
            if unicodedata.category(char) != "Mn"
        ).strip()
        logger.info(
            "Traza confirmacion: original=%s normalizado=%s texto=%s",
            _mask_phone(numero),
            _mask_phone(normalized_phone),
            normalized_text,
        )
        confirmation_result = ticket_order_monitor.confirm_pending_customer_deliveries(
            normalized_phone or str(numero or ""),
            mensaje,
        )
        logger.info(
            "Resultado confirmacion: handled=%s reason=%s orders=%s",
            confirmation_result.get("handled"),
            confirmation_result.get("reason"),
            [item.get("order_id") for item in confirmation_result.get("results") or []],
        )
        if confirmation_result.get("handled"):
            respuesta_confirmacion = str(confirmation_result.get("reply") or "").strip()
            logger.info(
                "Confirmacion de entradas para %s: %s",
                _mask_phone(numero),
                respuesta_confirmacion,
            )
            return jsonify({"reply": respuesta_confirmacion})

        respuesta = responder(mensaje, numero, estados)

        logger.info("Respuesta para %s: %s", _mask_phone(numero), respuesta)
        return jsonify({"reply": respuesta})
    except Exception as exc:
        logger.error("Error en webhook: %s", str(exc))
        return jsonify({"reply": "Error interno del servidor."})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "estados_activos": len(estados)})


if __name__ == "__main__":
    app.run(port=5000, debug=False, host="0.0.0.0")
