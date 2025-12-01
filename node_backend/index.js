import makeWASocket, {
    useMultiFileAuthState,
    fetchLatestBaileysVersion,
    DisconnectReason
} from "@whiskeysockets/baileys"

import Pino from "pino"
import { Boom } from "@hapi/boom"
import fs from "fs"
import qrcode from "qrcode-terminal"
import axios from "axios"

const AUTH_FOLDER = "./whatsapp-sessions"

async function startBot() {

    console.log("🚀 Iniciando WhatsApp Bot con Baileys v7...")

    // --- Sesión ---
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER)

    // --- Obtener versión oficial de WhatsApp ---
    const { version } = await fetchLatestBaileysVersion()
    console.log("📡 Version WA:", version)

    // --- Crear socket ---
    const sock = makeWASocket({
        version,
        logger: Pino({ level: "silent" }),
        browser: ["Bacano-Bot", "Chrome", "1.0.0"],
        auth: state,
        printQRInTerminal: false,   // lo manejamos manualmente
        syncFullHistory: false,     // recomendado
        markOnlineOnConnect: true
    })

    // ============================================
    //                  QR
    // ============================================
    sock.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update

        if (qr) {
            console.log("📲 Escaneá este QR para vincular:")
            qrcode.generate(qr, { small: true })
        }

        // --- Desconexión ---
        if (connection === "close") {
            const reason = new Boom(lastDisconnect?.error)?.output?.statusCode

            if (reason === DisconnectReason.loggedOut) {
                console.log("❌ Sesión cerrada. Eliminando datos y reiniciando...")
                fs.rmSync(AUTH_FOLDER, { recursive: true, force: true })
                return startBot()
            }

            console.log("⚠️ Conexión perdida. Reintentando...")
            return startBot()
        }

        if (connection === "open") {
            console.log("✅ Conectado a WhatsApp correctamente.")
        }
    })

    // Guardar credenciales cuando se actualizan
    sock.ev.on("creds.update", saveCreds)

    // ============================================
    //              RECEPCIÓN DE MENSAJES
    // ============================================
    sock.ev.on("messages.upsert", async ({ messages }) => {
        const msg = messages[0]
        if (!msg.message || msg.key.fromMe) return

        const from = msg.key.remoteJid
        const text =
            msg.message.conversation ||
            msg.message.extendedTextMessage?.text ||
            null

        if (!text) return

        console.log(`💬 Mensaje recibido de ${from}: "${text}"`)

        // --- Enviar al backend Python ---
        try {
            const webhookData = { from, message: text }

            const resp = await axios.post(
                "http://localhost:5000/webhook",
                webhookData,
                { timeout: 10000 }
            )

            if (resp.data?.reply) {
                await sock.sendMessage(from, { text: resp.data.reply })
                console.log("📨 Respuesta enviada.")
            }

        } catch (err) {
            console.error("❌ Error webhook:", err.message)
            try {
                await sock.sendMessage(from, { text: "⚠️ Error del servidor. Intenta más tarde." })
            } catch {}
        }
    })
}

// --- Iniciar ---
startBot().catch(err => console.error("❌ Error fatal:", err))
