import makeWASocket, {
    useMultiFileAuthState,
    fetchLatestBaileysVersion,
    DisconnectReason
} from "@whiskeysockets/baileys"

import Pino from "pino"
import { Boom } from "@hapi/boom"
import fs from "fs"
import http from "http"
import path from "path"
import qrcode from "qrcode-terminal"
import { fileURLToPath } from "url"
import axios from "axios"

const AUTH_FOLDER = "./whatsapp-sessions"
const INTERNAL_PORT = 3000
const CURRENT_FILE = fileURLToPath(import.meta.url)
const PROJECT_ROOT = path.resolve(path.dirname(CURRENT_FILE), "..")
const ALLOWED_DEBUG_DIR = path.resolve(PROJECT_ROOT, "python_backend", "debug")

let activeSock = null
let internalServerStarted = false

function isLocalRequest(req) {
    const remote = req.socket?.remoteAddress || ""
    return remote === "127.0.0.1" || remote === "::1" || remote === "::ffff:127.0.0.1"
}

function sendJson(res, statusCode, payload) {
    res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" })
    res.end(JSON.stringify(payload))
}

function isDigitsOnly(value) {
    return /^\d+$/.test(value)
}

function isPdfPathAllowed(filePath) {
    const resolved = path.resolve(filePath)
    return resolved === ALLOWED_DEBUG_DIR || resolved.startsWith(`${ALLOWED_DEBUG_DIR}${path.sep}`)
}

function sanitizeErrorName(error) {
    if (!error || typeof error !== "object") {
        return "UnknownError"
    }
    return String(error.name || "Error")
}

async function handleInternalSendDocument(req, res) {
    if (!isLocalRequest(req)) {
        sendJson(res, 403, { ok: false, error: "Acceso no permitido" })
        return
    }

    if (!activeSock) {
        sendJson(res, 503, { ok: false, error: "Conexion de WhatsApp no disponible" })
        return
    }

    let rawBody = ""
    req.on("data", (chunk) => {
        rawBody += chunk
        if (rawBody.length > 1024 * 1024) {
            req.destroy()
        }
    })

    req.on("end", async () => {
        try {
            const payload = JSON.parse(rawBody || "{}")
            const phone = String(payload.phone || "").trim()
            const filePath = String(payload.file_path || "").trim()
            const filename = String(payload.filename || "").trim()
            const caption = String(payload.caption || "").trim()

            if (!isDigitsOnly(phone)) {
                sendJson(res, 400, { ok: false, error: "Telefono invalido" })
                return
            }

            if (!filePath) {
                sendJson(res, 400, { ok: false, error: "Ruta de archivo invalida" })
                return
            }

            const resolvedPath = path.resolve(filePath)
            if (!isPdfPathAllowed(resolvedPath)) {
                sendJson(res, 400, { ok: false, error: "Ruta de archivo no permitida" })
                return
            }

            if (!fs.existsSync(resolvedPath)) {
                sendJson(res, 400, { ok: false, error: "El archivo no existe" })
                return
            }

            const stats = fs.statSync(resolvedPath)
            if (!stats.isFile()) {
                sendJson(res, 400, { ok: false, error: "La ruta no corresponde a un archivo" })
                return
            }

            if (stats.size <= 0) {
                sendJson(res, 400, { ok: false, error: "El archivo esta vacio" })
                return
            }

            if (path.extname(resolvedPath).toLowerCase() !== ".pdf") {
                sendJson(res, 400, { ok: false, error: "El archivo debe ser PDF" })
                return
            }

            const jid = `${phone}@s.whatsapp.net`
            const lookup = await activeSock.onWhatsApp(jid)
            const numberValid =
                Array.isArray(lookup) && lookup.length > 0 && Boolean(lookup[0]?.exists)

            if (!numberValid) {
                sendJson(res, 400, { ok: false, error: "Numero no registrado en WhatsApp" })
                return
            }

            const safeFileName = filename || path.basename(resolvedPath)
            const pdfBuffer = fs.readFileSync(resolvedPath)
            if (!pdfBuffer || pdfBuffer.length <= 0) {
                sendJson(res, 400, { ok: false, error: "El archivo esta vacio" })
                return
            }

            await activeSock.sendMessage(jid, { text: caption })

            try {
                await activeSock.sendMessage(jid, {
                    document: pdfBuffer,
                    mimetype: "application/pdf",
                    fileName: safeFileName,
                    caption: undefined
                })
            } catch (error) {
                console.error("Document send failed:", sanitizeErrorName(error))
                console.error("Document send message:", error?.message || "Sin mensaje")
                if (error?.stack) {
                    console.error(error.stack)
                }
                sendJson(res, 500, {
                    ok: false,
                    error: "document-send-failed",
                    detail: error?.message || "Fallo enviando documento PDF"
                })
                return
            }

            sendJson(res, 200, { ok: true, message: "Documento enviado" })
        } catch (error) {
            sendJson(res, 500, { ok: false, error: error.message || "Error interno" })
        }
    })

    req.on("error", () => {
        sendJson(res, 500, { ok: false, error: "Error leyendo la solicitud" })
    })
}

async function handleInternalSendText(req, res) {
    if (!isLocalRequest(req)) {
        sendJson(res, 403, { ok: false, error: "Acceso no permitido" })
        return
    }

    if (!activeSock) {
        sendJson(res, 503, { ok: false, error: "Conexion de WhatsApp no disponible" })
        return
    }

    let rawBody = ""
    req.on("data", (chunk) => {
        rawBody += chunk
        if (rawBody.length > 1024 * 1024) {
            req.destroy()
        }
    })

    req.on("end", async () => {
        try {
            const payload = JSON.parse(rawBody || "{}")
            const phone = String(payload.phone || "").trim()
            const text = String(payload.text || "").trim()

            if (!isDigitsOnly(phone)) {
                sendJson(res, 400, { ok: false, error: "Telefono invalido" })
                return
            }

            if (!text) {
                sendJson(res, 400, { ok: false, error: "Texto invalido" })
                return
            }

            const jid = `${phone}@s.whatsapp.net`
            const lookup = await activeSock.onWhatsApp(jid)
            const numberValid =
                Array.isArray(lookup) && lookup.length > 0 && Boolean(lookup[0]?.exists)

            if (!numberValid) {
                sendJson(res, 400, { ok: false, error: "Numero no registrado en WhatsApp" })
                return
            }

            await activeSock.sendMessage(jid, { text })
            sendJson(res, 200, { ok: true, message: "Texto enviado" })
        } catch (error) {
            sendJson(res, 500, { ok: false, error: error.message || "Error interno" })
        }
    })

    req.on("error", () => {
        sendJson(res, 500, { ok: false, error: "Error leyendo la solicitud" })
    })
}

function ensureInternalServer() {
    if (internalServerStarted) {
        return
    }

    const server = http.createServer((req, res) => {
        if (req.method === "POST" && req.url === "/internal/send-document") {
            handleInternalSendDocument(req, res)
            return
        }
        if (req.method === "POST" && req.url === "/internal/send-text") {
            handleInternalSendText(req, res)
            return
        }

        sendJson(res, 404, { ok: false, error: "Ruta no encontrada" })
    })

    server.listen(INTERNAL_PORT, "127.0.0.1", () => {
        console.log(`Endpoint interno listo en http://127.0.0.1:${INTERNAL_PORT}`)
    })

    internalServerStarted = true
}

async function startBot() {

    console.log("Iniciando WhatsApp Bot con Baileys v7...")
    ensureInternalServer()

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER)

    const { version } = await fetchLatestBaileysVersion()
    console.log("Version WA:", version)

    const sock = makeWASocket({
        version,
        logger: Pino({ level: "silent" }),
        browser: ["Bacano-Bot", "Chrome", "1.0.0"],
        auth: state,
        printQRInTerminal: false,
        syncFullHistory: false,
        markOnlineOnConnect: true
    })

    sock.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update

        if (qr) {
            console.log("Escanea este QR para vincular:")
            qrcode.generate(qr, { small: true })
        }

        if (connection === "close") {
            if (activeSock === sock) {
                activeSock = null
            }

            const reason = new Boom(lastDisconnect?.error)?.output?.statusCode

            if (reason === DisconnectReason.loggedOut) {
                console.log("Sesion cerrada. Eliminando datos y reiniciando...")
                fs.rmSync(AUTH_FOLDER, { recursive: true, force: true })
                return startBot()
            }

            console.log("Conexion perdida. Reintentando...")
            return startBot()
        }

        if (connection === "open") {
            activeSock = sock
            console.log("Conectado a WhatsApp correctamente.")
        }
    })

    sock.ev.on("creds.update", saveCreds)

    sock.ev.on("messages.upsert", async ({ messages }) => {
        const msg = messages[0]
        if (!msg.message || msg.key.fromMe) return

        const from = msg.key.remoteJid
        const text =
            msg.message.conversation ||
            msg.message.extendedTextMessage?.text ||
            null

        if (!text) return

        console.log(`Mensaje recibido de ${from}: "${text}"`)

        try {
            const webhookData = { from, message: text }

            const resp = await axios.post(
                "http://localhost:5000/webhook",
                webhookData,
                { timeout: 10000 }
            )

            if (resp.data?.reply) {
                await sock.sendMessage(from, { text: resp.data.reply })
                console.log("Respuesta enviada.")
            }

        } catch (err) {
            console.error("Error webhook:", err.message)
            try {
                await sock.sendMessage(from, { text: "Error del servidor. Intenta mas tarde." })
            } catch {}
        }
    })
}

startBot().catch(err => console.error("Error fatal:", err))
