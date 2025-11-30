import subprocess
import sys
import os
import threading
import time
import tkinter as tk
from pathlib import Path


def add_python_backend_to_path():
    """Agregar python_backend al path de Python"""
    python_backend_path = os.path.join(os.path.dirname(__file__), "python_backend")
    if python_backend_path not in sys.path:
        sys.path.insert(0, python_backend_path)


# Agregar el path ANTES de importar
add_python_backend_to_path()

# Ahora importamos después de agregar el path
try:
    from gui import BotControlGUI
except ImportError as e:
    print(f"❌ Error importando GUI: {e}")
    print("📁 Buscando archivos...")
    python_backend_dir = os.path.join(os.path.dirname(__file__), "python_backend")
    if os.path.exists(python_backend_dir):
        print(f"✅ Carpeta python_backend encontrada: {python_backend_dir}")
        files = os.listdir(python_backend_dir)
        print(f"📄 Archivos en python_backend: {files}")
    sys.exit(1)


def create_virtualenv():
    """Crear y configurar entorno virtual"""
    venv_path = ".venv"

    if not os.path.exists(venv_path):
        print("🔧 Creando entorno virtual...")
        try:
            subprocess.run([sys.executable, "-m", "venv", venv_path], check=True)
            print("✅ Entorno virtual creado")
        except subprocess.CalledProcessError as e:
            print(f"❌ Error creando entorno virtual: {e}")
            return None, None

    # Determinar el ejecutable de pip según el SO
    if os.name == 'nt':  # Windows
        pip_executable = os.path.join(venv_path, "Scripts", "pip.exe")
        python_executable = os.path.join(venv_path, "Scripts", "python.exe")
    else:  # Linux/Mac
        pip_executable = os.path.join(venv_path, "bin", "pip")
        python_executable = os.path.join(venv_path, "bin", "python")

    # Verificar que los ejecutables existen
    if not os.path.exists(python_executable):
        print(f"❌ No se encontró {python_executable}")
        return None, None

    return python_executable, pip_executable


def install_dependencies(pip_executable):
    """Instalar dependencias de Python"""
    print("📦 Instalando dependencias de Python...")
    requirements_file = "python_backend/requirements.txt"

    if not os.path.exists(requirements_file):
        print("❌ No se encuentra requirements.txt, creando uno básico...")
        with open(requirements_file, "w") as f:
            f.write("Flask==2.3.3\nmysql-connector-python==8.1.0\nrequests==2.31.0\n")

    try:
        subprocess.run([pip_executable, "install", "-r", requirements_file],
                       check=True, cwd=".")
        print("✅ Dependencias de Python instaladas")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error instalando dependencias: {e}")
        return False


def install_node_dependencies():
    """Instalar dependencias de Node.js"""
    print("📦 Instalando dependencias de Node.js...")
    node_dir = "node_backend"

    if not os.path.exists(node_dir):
        print("❌ No se encuentra carpeta node_backend")
        return False

    try:
        if os.name == 'nt':  # Windows
            result = subprocess.run(["npm", "install"], cwd=node_dir, check=True, shell=True, capture_output=True,
                                    text=True)
        else:  # Linux/Mac
            result = subprocess.run(["npm", "install"], cwd=node_dir, check=True, capture_output=True, text=True)

        print("✅ Dependencias de Node.js instaladas")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error instalando dependencias Node.js: {e}")
        print(f"   Salida: {e.stdout}")
        return False


def start_flask_app(python_executable):
    """Iniciar servidor Flask en un subproceso"""

    def run_flask():
        try:
            flask_process = subprocess.Popen(
                [python_executable, "app.py"],
                cwd="python_backend",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            print("✅ Servidor Flask iniciado")

            # Leer output en tiempo real
            for line in iter(flask_process.stdout.readline, ''):
                if line:
                    print(f"[FLASK] {line.strip()}")

            flask_process.stdout.close()
            return_code = flask_process.wait()
            print(f"❌ Flask se cerró con código: {return_code}")

        except Exception as e:
            print(f"❌ Error en Flask: {e}")

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    return flask_thread


def start_node_app():
    """Iniciar aplicación Node.js en un subproceso"""

    def run_node():
        # Esperar un poco a que Flask esté listo
        time.sleep(5)

        try:
            if os.name == 'nt':  # Windows
                node_process = subprocess.Popen(
                    ["npm", "start"],
                    cwd="node_backend",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=True,
                    bufsize=1,
                    universal_newlines=True
                )
            else:  # Linux/Mac
                node_process = subprocess.Popen(
    ["npm", "start"],
    cwd="node_backend",
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    shell=True,
    bufsize=1,
    universal_newlines=True,
    encoding="utf-8", errors="replace"
)

            print("✅ Node.js iniciado")

            # Leer output en tiempo real
            for line in iter(node_process.stdout.readline, ''):
                if line:
                    print(f"[NODE] {line.strip()}")

            node_process.stdout.close()
            return_code = node_process.wait()
            print(f"❌ Node.js se cerró con código: {return_code}")

        except Exception as e:
            print(f"❌ Error en Node.js: {e}")

    node_thread = threading.Thread(target=run_node, daemon=True)
    node_thread.start()
    return node_thread


def check_files():
    """Verificar que todos los archivos necesarios existan"""
    print("🔍 Verificando archivos...")

    required_files = {
        "python_backend/app.py": "Servidor Flask principal",
        "python_backend/respuestas.py": "Lógica de respuestas del bot",
        "python_backend/db_utils.py": "Utilidades de base de datos",
        "python_backend/config_manager.py": "Manejador de configuración",
        "python_backend/gui.py": "Interfaz gráfica",
        "node_backend/index.js": "Cliente WhatsApp Node.js",
        "node_backend/package.json": "Dependencias Node.js"
    }

    all_exists = True
    for file_path, description in required_files.items():
        if os.path.exists(file_path):
            print(f"   ✅ {description}")
        else:
            print(f"   ❌ {description} - NO ENCONTRADO")
            all_exists = False

    return all_exists


def main():
    print("🚀 Iniciando WhatsApp Bot - Bacano Club")
    print("=" * 50)

    # Verificar archivos primero
    if not check_files():
        print("\n❌ Faltan archivos esenciales. Por favor verifica la estructura.")
        input("Presiona Enter para salir...")
        return

    # Crear carpetas necesarias
    os.makedirs("node_backend/whatsapp-sessions", exist_ok=True)

    # Configurar entorno virtual
    python_executable, pip_executable = create_virtualenv()

    if not python_executable:
        print("❌ No se pudo configurar el entorno virtual")
        input("Presiona Enter para salir...")
        return

    # Instalar dependencias
    deps_ok = install_dependencies(pip_executable)
    node_deps_ok = install_node_dependencies()

    if not deps_ok:
        print("⚠️ Hubo problemas con las dependencias, continuando...")

    # Iniciar servicios
    print("\n🔄 Iniciando servicios...")
    flask_thread = start_flask_app(python_executable)

    # Dar tiempo a que Flask inicie
    time.sleep(3)

    node_thread = start_node_app()

    print("⏳ Esperando que servicios estabilicen...")
    time.sleep(5)

    # Iniciar la interfaz gráfica
    print("\n🎨 Iniciando interfaz gráfica...")

    try:
        root = tk.Tk()
        app = BotControlGUI(root)

        print("\n" + "=" * 50)
        print("✅ Sistema listo!")
        print("   • Servidor Flask: http://localhost:5000")
        print("   • Bot WhatsApp: Iniciado")
        print("   • Interfaz de control: Activa")
        print("\n📱 Escanea el código QR en la terminal para conectar WhatsApp")
        print("=" * 50)

        # Configurar para cerrar procesos al salir
        def on_closing():
            print("\n🛑 Cerrando aplicación...")
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", on_closing)

        root.mainloop()

    except Exception as e:
        print(f"❌ Error iniciando GUI: {e}")
        print("💡 Intentando continuar sin GUI...")
        try:
            # Mantener el script corriendo
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Cerrando aplicación...")


if __name__ == "__main__":
    main()