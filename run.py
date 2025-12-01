import subprocess
import sys
import os
import threading
import time
import signal
import atexit
from pathlib import Path

# --- Compatibilidad de impresión UTF-8 en Windows ---
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# Procesos globales
flask_process = None
node_process = None


# ======================================================
# 🧹 Limpieza de procesos
# ======================================================
def cleanup():
    print("\nCerrando servicios...")

    def kill(p, name):
        if p and p.poll() is None:
            print(f"  - Terminando {name}...")
            try:
                if os.name == "nt":
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)], stdout=subprocess.DEVNULL)
                else:
                    p.terminate()
            except:
                pass

    kill(node_process, "WhatsApp / Node.js")
    kill(flask_process, "Flask")

    time.sleep(1)
    print("✔ Todos los servicios cerrados\n")


def signal_handler(sig, frame):
    print("\nInterrupción recibida. Cerrando todo...")
    cleanup()
    sys.exit(0)


# ======================================================
# 🔌 Verificación de puertos
# ======================================================
def check_port(port):
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0


def check_ports():
    if check_port(5000):
        print("⚠ El puerto 5000 ya está en uso (Flask). Cerrá lo que lo esté usando.")
    else:
        print("✔ Puerto 5000 disponible")


# ======================================================
# 🌐 Flask
# ======================================================
def start_flask():
    global flask_process
    print("Iniciando Flask...")

    try:
        flask_process = subprocess.Popen(
            [sys.executable, "python_backend/app.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace"
        )

        def reader():
            for line in flask_process.stdout:
                line = line.strip()
                if not line:
                    continue

                if "running" in line.lower():
                    print(f"[FLASK] ✔ {line}")
                elif any(err in line.lower() for err in ["error", "exception", "fail"]):
                    print(f"[FLASK] ❌ {line}")
                else:
                    print(f"[FLASK] {line}")

        threading.Thread(target=reader, daemon=True).start()

        time.sleep(2)
        return flask_process.poll() is None

    except Exception as e:
        print(f"❌ Error al lanzar Flask: {e}")
        return False


# ======================================================
# 📱 Node.js (WhatsApp Bot)
# ======================================================
def start_node():
    global node_process

    print("Iniciando WhatsApp (Node.js)...")

    try:
        node_process = subprocess.Popen(
            ["npm", "start"],
            cwd="node_backend",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace"
        )

        def reader():
            for line in node_process.stdout:
                line = line.strip()
                if not line:
                    continue

                if "qr" in line.lower():
                    print(f"[WHATSAPP] (QR) {line}")
                elif "connected" in line.lower():
                    print(f"[WHATSAPP] ✔ {line}")
                elif "error" in line.lower():
                    print(f"[WHATSAPP] ❌ {line}")
                else:
                    print(f"[WHATSAPP] {line}")

        threading.Thread(target=reader, daemon=True).start()

        return True

    except Exception as e:
        print(f"❌ Error iniciando Node.js: {e}")
        return False


# ======================================================
# 🖥 GUI opcional (si falla → modo consola)
# ======================================================
def start_gui():
    print("Cargando interfaz gráfica...")

    try:
        sys.path.insert(0, "python_backend")
        from gui import BotControlGUI
        import tkinter as tk

        root = tk.Tk()
        app = BotControlGUI(root)

        def on_close():
            print("\nCerrando GUI...")
            root.destroy()
            cleanup()

        root.protocol("WM_DELETE_WINDOW", on_close)

        print("\n✔ Interfaz lista en http://localhost:5000")
        print("Escaneá el QR cuando aparezca en consola\n")

        root.mainloop()

    except Exception as e:
        print(f"⚠ La GUI no está disponible ({e}). Activando modo consola...\n")
        return start_console()


# ======================================================
# 🧭 Consola interactiva
# ======================================================
def start_console():
    print("📟 Modo Consola")
    print("-----------------------------")
    print("Comandos:")
    print("  q = salir")
    print("  s = estado")
    print("  r = reiniciar WhatsApp")
    print("-----------------------------")

    while True:
        cmd = input("> ").strip().lower()

        if cmd == "q":
            print("Saliendo...")
            cleanup()
            break

        elif cmd == "s":
            print("\nEstado:")
            print("  Flask:   ", "✔ Activo" if flask_process.poll() is None else "❌ Caído")
            print("  WhatsApp:", "✔ Activo" if node_process.poll() is None else "❌ Caído")

        elif cmd == "r":
            print("Reiniciando WhatsApp...")
            if node_process:
                node_process.terminate()
                time.sleep(1)
            start_node()

        else:
            print("Comando no reconocido.")


# ======================================================
# 🧠 MAIN
# ======================================================
def main():
    print("=======================================")
    print("  BACANO BOT - Controlador unificado")
    print("=======================================\n")

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)

    required = [
        "python_backend/app.py",
        "node_backend/index.js",
        "python_backend/config.json"
    ]

    for file in required:
        if not os.path.exists(file):
            print(f"❌ Falta: {file}")
            print("Ejecutá install.bat primero.")
            return

    check_ports()

    if not start_flask():
        print("❌ Flask no inició.")
        return

    start_node()
    time.sleep(3)

    start_gui()


if __name__ == "__main__":
    main()

