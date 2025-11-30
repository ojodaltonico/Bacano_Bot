import baileys from "@whiskeysockets/baileys"
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion
} = baileys

import Pino from "pino"
import { Boom } from "@hapi/boom"
import fs from "fs"
import qrcode from "qrcode"
import axios from "axios"
import { exec } from "child_process"

const AUTH_FOLDER = "./whatsapp-sessions"

async function startBot() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER)
  const { version } = await fetchLatestBaileysVersion()

  console.log("Iniciando Baileys versión:", version)

  const sock = makeWASocket({
    version,
    browser: ["Chrome (Linux)", "Chrome", "10.0.0"],
    auth: state,
    logger: Pino({ level: "silent" }),
    printQRInTerminal: false
  })

  // =====================================
  //               QR
  // =====================================
  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update

    if (qr) {
      console.log("QR recibido. Generando imagen...")

      const qrPath = "./qr.png"

      try {
        await qrcode.toFile(qrPath, qr)
        exec(`start "" "${qrPath}"`)
        console.log("QR generado y abierto correctamente.")
      } catch (err) {
        console.log("Error generando QR:", err.message)
      }
    }

    if (connection === "close") {
      const reason = new Boom(lastDisconnect?.error)?.output?.statusCode

      if (reason === DisconnectReason.loggedOut) {
        console.log("Sesión cerrada. Reiniciando...")
        fs.rmSync(AUTH_FOLDER, { recursive: true, force: true })
        return startBot()
      }

      console.log("Conexión perdida. Reintentando...")
      return startBot()
    }

    if (connection === "open") {
      console.log("Conectado a WhatsApp correctamente.")
    }
  })

  sock.ev.on("creds.update", saveCreds)

  // =====================================
  //          MENSAJES
  // =====================================
  sock.ev.on("messages.upsert", async ({ messages }) => {
    const msg = messages[0]
    if (!msg.message || msg.key.fromMe) return

    const from = msg.key.remoteJid
    const text =
      msg.message.conversation ||
      msg.message.extendedTextMessage?.text ||
      null

    if (!text) return

    console.log(`Mensaje recibido de ${from}: ${text}`)

    try {
      const response = await axios.post(
        "http://localhost:5000/webhook",
        { from, message: text },
        { timeout: 15000 }
      )

      if (response.data?.reply) {
        await sock.sendMessage(from, { text: response.data.reply })
      }
    } catch (err) {
      console.error("Error webhook:", err.message)
    }
  })
}

startBot().catch((err) => console.error("Error general:", err))
