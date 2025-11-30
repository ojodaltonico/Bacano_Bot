from flask import Flask, request, jsonify
from respuestas import responder
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
estados = {}


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "service": "WhatsApp Bot Backend",
        "endpoints": {
            "webhook": "POST /webhook",
            "health": "GET /health"
        }
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        numero = data.get("from")
        mensaje = data.get("message", "").strip()

        logger.info(f"📩 Mensaje recibido de {numero}: {mensaje}")

        respuesta = responder(mensaje, numero, estados)

        logger.info(f"📤 Respuesta para {numero}: {respuesta}")
        return jsonify({"reply": respuesta})

    except Exception as e:
        logger.error(f"❌ Error en webhook: {str(e)}")
        return jsonify({"reply": "⚠️ Error interno del servidor."})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "estados_activos": len(estados)})


if __name__ == "__main__":
    app.run(port=5000, debug=False, host='0.0.0.0')