import fs from "fs"
import path from "path"

import makeWASocket, {
    useMultiFileAuthState,
    fetchLatestBaileysVersion,
    DisconnectReason
} from "@whiskeysockets/baileys"
import { Boom } from "@hapi/boom"
import Pino from "pino"
import qrcode from "qrcode-terminal"

const AUTH_FOLDER = path.resolve("node_backend", "whatsapp-sessions-dev")
const MESSAGE_TEXT = "🎟️ Prueba de envío de entrada Bacano"

function parseArgs(argv) {
    if (argv.length !== 4) {
        throw new Error(
            'Uso: node node_backend/test_send_pdf.js <numero_internacional> "ruta\\\\al\\\\ticket.pdf"'
        )
    }

    const phone = String(argv[2]).trim()
    const pdfPath = path.resolve(argv[3])

    if (!/^\d+$/.test(phone)) {
        throw new Error("El numero debe contener solamente digitos.")
    }

    if (!fs.existsSync(pdfPath)) {
        throw new Error("El archivo PDF no existe.")
    }

    if (path.extname(pdfPath).toLowerCase() !== ".pdf") {
        throw new Error("El archivo debe terminar en .pdf.")
    }

    const stats = fs.statSync(pdfPath)
    if (!stats.isFile()) {
        throw new Error("La ruta indicada no corresponde a un archivo.")
    }
    if (stats.size <= 0) {
        throw new Error("El archivo PDF esta vacio.")
    }

    return { phone, pdfPath }
}

async function createSocket() {
    fs.mkdirSync(AUTH_FOLDER, { recursive: true })
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER)
    const { version } = await fetchLatestBaileysVersion()

    const sock = makeWASocket({
        version,
        logger: Pino({ level: "silent" }),
        browser: ["Bacano-PDF-Test", "Chrome", "1.0.0"],
        auth: state,
        printQRInTerminal: false,
        syncFullHistory: false,
        markOnlineOnConnect: false
    })

    sock.ev.on("creds.update", saveCreds)
    return sock
}

async function waitForConnection(sock) {
    return new Promise((resolve, reject) => {
        let settled = false

        const cleanup = () => {
            sock.ev.off("connection.update", onUpdate)
        }

        const fail = (error) => {
            if (settled) return
            settled = true
            cleanup()
            reject(error)
        }

        const succeed = () => {
            if (settled) return
            settled = true
            cleanup()
            resolve()
        }

        const onUpdate = (update) => {
            const { connection, lastDisconnect, qr } = update

            if (qr) {
                qrcode.generate(qr, { small: true })
            }

            if (connection === "open") {
                console.log("Conexion abierta")
                succeed()
                return
            }

            if (connection === "close") {
                const reason = new Boom(lastDisconnect?.error)?.output?.statusCode
                if (reason === DisconnectReason.loggedOut) {
                    fail(new Error("Sesion cerrada en WhatsApp. Volve a vincular la sesion de desarrollo."))
                    return
                }

                const message = lastDisconnect?.error?.message || "Conexion cerrada antes de completar la prueba."
                fail(new Error(message))
            }
        }

        sock.ev.on("connection.update", onUpdate)
    })
}

async function closeSocket(sock) {
    try {
        sock.end(new Error("Test finalizado"))
    } catch {
    }
}

async function main() {
    let sock

    try {
        const { phone, pdfPath } = parseArgs(process.argv)
        const pdfBuffer = fs.readFileSync(pdfPath)
        const pdfName = path.basename(pdfPath)
        const jid = `${phone}@s.whatsapp.net`

        sock = await createSocket()
        await waitForConnection(sock)

        const lookup = await sock.onWhatsApp(jid)
        const numberValid = Array.isArray(lookup) && lookup.length > 0 && Boolean(lookup[0]?.exists)
        console.log(`Numero valido: ${numberValid ? "si" : "no"}`)

        if (!numberValid) {
            throw new Error("El numero no esta registrado en WhatsApp.")
        }

        let textSent = false
        let pdfSent = false

        await sock.sendMessage(jid, { text: MESSAGE_TEXT })
        textSent = true
        console.log(`Texto enviado: ${textSent ? "si" : "no"}`)

        await sock.sendMessage(jid, {
            document: pdfBuffer,
            fileName: pdfName,
            mimetype: "application/pdf",
            caption: "Entrada Bacano en PDF"
        })
        pdfSent = true
        console.log(`PDF enviado: ${pdfSent ? "si" : "no"}`)

        await closeSocket(sock)
        process.exit(0)
    } catch (error) {
        console.log(`Error: ${error.message}`)
        if (sock) {
            try {
                sock.end(new Error("Test finalizado con error"))
            } catch {
            }
        }
        process.exit(1)
    }
}

main()
