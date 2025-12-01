import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import subprocess
import sys
import os
import queue
import json
import time
from datetime import datetime
import importlib.util
import traceback

# Añadir el directorio actual al path para importaciones
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BacanoBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🤖 BacanoBot - Control Unificado")
        self.root.geometry("1200x700")

        # Intentar cargar icono
        try:
            self.root.iconbitmap("bacano.ico")
        except:
            pass

        # Procesos
        self.flask_process = None
        self.node_process = None

        # Colas para logs
        self.flask_queue = queue.Queue()
        self.node_queue = queue.Queue()

        # Estado
        self.is_flask_running = False
        self.is_node_running = False

        self.setup_ui()

        # Cargar configuración después de crear la UI
        self.root.after(1000, self.load_config)

    def setup_ui(self):
        # Configurar grid
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # Frame principal
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")

        # Configurar grid del frame principal
        main_frame.grid_rowconfigure(1, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # Barra superior
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        # Título
        title_label = ttk.Label(
            top_frame,
            text="🤖 BacanoBot - Control Unificado",
            font=("Arial", 16, "bold")
        )
        title_label.grid(row=0, column=0, sticky="w")

        # Botones de control
        control_frame = ttk.Frame(top_frame)
        control_frame.grid(row=0, column=1, sticky="e")

        self.start_btn = ttk.Button(
            control_frame,
            text="▶️ Iniciar Todo",
            command=self.start_all,
            style="success.TButton"
        )
        self.start_btn.grid(row=0, column=0, padx=2)

        self.stop_btn = ttk.Button(
            control_frame,
            text="⏹️ Detener Todo",
            command=self.stop_all,
            style="danger.TButton",
            state="disabled"
        )
        self.stop_btn.grid(row=0, column=1, padx=2)

        # Notebook (pestañas)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        # Pestaña 1: Dashboard
        self.tab_dashboard = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dashboard, text='📊 Dashboard')
        self.setup_dashboard_tab()

        # Pestaña 2: Logs
        self.tab_logs = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_logs, text='📝 Logs')
        self.setup_logs_tab()

        # Pestaña 3: Configuración
        self.tab_config = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_config, text='⚙️ Configuración')
        self.setup_config_tab()

        # Pestaña 4: Base de Datos
        self.tab_database = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_database, text='🗄️ Base de Datos')
        self.setup_database_tab()

        # Barra de estado
        self.status_bar = ttk.Label(
            main_frame,
            text="🟢 Listo para iniciar",
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.status_bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        # Estilos
        self.setup_styles()

        # Iniciar monitoreo de logs
        self.root.after(500, self.update_logs)

    def setup_styles(self):
        style = ttk.Style()

        # Colores para botones
        style.configure("success.TButton", foreground="white", background="green")
        style.configure("danger.TButton", foreground="white", background="red")
        style.configure("warning.TButton", foreground="black", background="yellow")

    def setup_dashboard_tab(self):
        # Frame para estado
        status_frame = ttk.LabelFrame(self.tab_dashboard, text="Estado de Servicios", padding=15)
        status_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Grid para status
        status_frame.grid_columnconfigure(1, weight=1)

        # Flask Status
        ttk.Label(status_frame, text="Flask Backend:", font=("Arial", 11)).grid(
            row=0, column=0, sticky="w", pady=5, padx=5
        )

        self.flask_status = ttk.Label(
            status_frame,
            text="🔴 Detenido",
            font=("Arial", 11, "bold"),
            foreground="red"
        )
        self.flask_status.grid(row=0, column=1, sticky="w", pady=5, padx=5)

        # Node Status
        ttk.Label(status_frame, text="WhatsApp Bot:", font=("Arial", 11)).grid(
            row=1, column=0, sticky="w", pady=5, padx=5
        )

        self.node_status = ttk.Label(
            status_frame,
            text="🔴 Detenido",
            font=("Arial", 11, "bold"),
            foreground="red"
        )
        self.node_status.grid(row=1, column=1, sticky="w", pady=5, padx=5)

        # Webhook Status
        ttk.Label(status_frame, text="Webhook URL:", font=("Arial", 11)).grid(
            row=2, column=0, sticky="w", pady=5, padx=5
        )

        self.webhook_status = ttk.Label(
            status_frame,
            text="http://localhost:5000/webhook",
            font=("Arial", 11),
            foreground="blue"
        )
        self.webhook_status.grid(row=2, column=1, sticky="w", pady=5, padx=5)

        # QR Code Display
        qr_frame = ttk.LabelFrame(self.tab_dashboard, text="Código QR WhatsApp", padding=15)
        qr_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.qr_text = scrolledtext.ScrolledText(
            qr_frame,
            height=10,
            wrap=tk.WORD,
            font=("Consolas", 9)
        )
        self.qr_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.qr_text.insert("1.0", "Escanea el código QR cuando aparezca aquí...\n\n")
        self.qr_text.config(state="disabled")

    def setup_logs_tab(self):
        # Frame para logs con pestañas
        logs_notebook = ttk.Notebook(self.tab_logs)
        logs_notebook.pack(fill="both", expand=True)

        # Logs de Flask
        flask_log_frame = ttk.Frame(logs_notebook)
        logs_notebook.add(flask_log_frame, text='Flask Backend')

        self.flask_log = scrolledtext.ScrolledText(
            flask_log_frame,
            wrap=tk.WORD,
            font=("Consolas", 9)
        )
        self.flask_log.pack(fill="both", expand=True, padx=5, pady=5)

        # Logs de Node
        node_log_frame = ttk.Frame(logs_notebook)
        logs_notebook.add(node_log_frame, text='WhatsApp Bot')

        self.node_log = scrolledtext.ScrolledText(
            node_log_frame,
            wrap=tk.WORD,
            font=("Consolas", 9)
        )
        self.node_log.pack(fill="both", expand=True, padx=5, pady=5)

        # Botones para logs
        btn_frame = ttk.Frame(self.tab_logs)
        btn_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(
            btn_frame,
            text="📋 Copiar Logs",
            command=self.copy_logs
        ).pack(side="left", padx=5)

        ttk.Button(
            btn_frame,
            text="🧹 Limpiar Logs",
            command=self.clear_logs
        ).pack(side="left", padx=5)

    def setup_config_tab(self):
        # Frame principal
        config_frame = ttk.Frame(self.tab_config)
        config_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Configuración de Base de Datos
        db_frame = ttk.LabelFrame(config_frame, text="Configuración de Base de Datos", padding=10)
        db_frame.pack(fill="x", pady=(0, 10))

        # Host
        ttk.Label(db_frame, text="Host:").grid(row=0, column=0, sticky="w", pady=5)
        self.host_entry = ttk.Entry(db_frame, width=40)
        self.host_entry.grid(row=0, column=1, pady=5, padx=10, sticky="ew")

        # Usuario
        ttk.Label(db_frame, text="Usuario:").grid(row=1, column=0, sticky="w", pady=5)
        self.user_entry = ttk.Entry(db_frame, width=40)
        self.user_entry.grid(row=1, column=1, pady=5, padx=10, sticky="ew")

        # Contraseña
        ttk.Label(db_frame, text="Contraseña:").grid(row=2, column=0, sticky="w", pady=5)
        self.pass_entry = ttk.Entry(db_frame, width=40, show="*")
        self.pass_entry.grid(row=2, column=1, pady=5, padx=10, sticky="ew")

        # Base de Datos
        ttk.Label(db_frame, text="Base de Datos:").grid(row=3, column=0, sticky="w", pady=5)
        self.db_entry = ttk.Entry(db_frame, width=40)
        self.db_entry.grid(row=3, column=1, pady=5, padx=10, sticky="ew")

        db_frame.columnconfigure(1, weight=1)

        # Promociones
        promo_frame = ttk.LabelFrame(config_frame, text="Promociones (una por línea)", padding=10)
        promo_frame.pack(fill="both", expand=True, pady=(10, 0))

        self.promo_text = scrolledtext.ScrolledText(promo_frame, height=8)
        self.promo_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Botones
        btn_frame = ttk.Frame(config_frame)
        btn_frame.pack(fill="x", pady=(10, 0))

        ttk.Button(
            btn_frame,
            text="💾 Guardar Configuración",
            command=self.save_config
        ).pack(side="left", padx=5)

        ttk.Button(
            btn_frame,
            text="📤 Cargar Configuración",
            command=self.load_config
        ).pack(side="left", padx=5)

    def setup_database_tab(self):
        # Frame principal
        db_frame = ttk.Frame(self.tab_database)
        db_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Herramientas de BD
        tools_frame = ttk.LabelFrame(db_frame, text="Herramientas de Base de Datos", padding=15)
        tools_frame.pack(fill="both", expand=True)

        # Botón de prueba de conexión
        ttk.Button(
            tools_frame,
            text="🔍 Probar Conexión a BD",
            command=self.test_db_connection,
            style="warning.TButton"
        ).pack(pady=(0, 10))

        # Resultados de prueba
        self.db_result = ttk.Label(
            tools_frame,
            text="",
            wraplength=500
        )
        self.db_result.pack(pady=5)

        # Separador
        ttk.Separator(tools_frame, orient="horizontal").pack(fill="x", pady=20)

        # Buscar usuario
        search_frame = ttk.Frame(tools_frame)
        search_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(search_frame, text="Buscar por DNI:").pack(side="left", padx=(0, 10))

        self.search_dni = ttk.Entry(search_frame, width=20)
        self.search_dni.pack(side="left", padx=(0, 10))

        ttk.Button(
            search_frame,
            text="👤 Buscar Usuario",
            command=self.search_user_by_dni
        ).pack(side="left")

        # Resultados de búsqueda
        self.search_result = scrolledtext.ScrolledText(tools_frame, height=8)
        self.search_result.pack(fill="both", expand=True, pady=(10, 0))

    def load_config(self):
        """Cargar configuración"""
        try:
            # Importar dinámicamente para evitar errores
            config_path = os.path.join(os.path.dirname(__file__), "config_manager.py")

            if os.path.exists(config_path):
                spec = importlib.util.spec_from_file_location("config_manager", config_path)
                config_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config_module)

                config = config_module.load_config()

                if config:
                    # Cargar datos de BD
                    db = config.get('database', {})
                    self.host_entry.delete(0, tk.END)
                    self.host_entry.insert(0, db.get('host', ''))
                    self.user_entry.delete(0, tk.END)
                    self.user_entry.insert(0, db.get('user', ''))
                    self.pass_entry.delete(0, tk.END)
                    self.pass_entry.insert(0, db.get('password', ''))
                    self.db_entry.delete(0, tk.END)
                    self.db_entry.insert(0, db.get('database', ''))

                    # Cargar promociones
                    promotions = config.get('promotions', [])
                    self.promo_text.delete('1.0', tk.END)
                    self.promo_text.insert('1.0', '\n'.join(promotions))

                    self.log("✅ Configuración cargada")
                else:
                    self.log("⚠️ No se pudo cargar la configuración")
            else:
                self.log("❌ No se encontró config_manager.py")

        except Exception as e:
            error_msg = f"❌ Error cargando configuración: {str(e)}"
            self.log(error_msg)
            print(f"Error detallado: {traceback.format_exc()}")

    def save_config(self):
        """Guardar configuración"""
        try:
            config = {
                "database": {
                    "host": self.host_entry.get(),
                    "user": self.user_entry.get(),
                    "password": self.pass_entry.get(),
                    "database": self.db_entry.get()
                },
                "promotions": [p.strip() for p in self.promo_text.get('1.0', tk.END).strip().split('\n') if p.strip()]
            }

            # Importar dinámicamente
            config_path = os.path.join(os.path.dirname(__file__), "config_manager.py")

            if os.path.exists(config_path):
                spec = importlib.util.spec_from_file_location("config_manager", config_path)
                config_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config_module)

                if config_module.save_config(config):
                    self.log("✅ Configuración guardada")
                    messagebox.showinfo("Éxito", "Configuración guardada correctamente")
                else:
                    self.log("❌ Error guardando configuración")
                    messagebox.showerror("Error", "No se pudo guardar la configuración")
            else:
                self.log("❌ No se encontró config_manager.py")

        except Exception as e:
            error_msg = f"❌ Error guardando configuración: {str(e)}"
            self.log(error_msg)
            messagebox.showerror("Error", error_msg)
            print(f"Error detallado: {traceback.format_exc()}")

    def start_all(self):
        """Iniciar todos los servicios"""
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        threading.Thread(target=self.start_flask, daemon=True).start()
        time.sleep(2)  # Esperar a que Flask inicie
        threading.Thread(target=self.start_node, daemon=True).start()

        self.log("🚀 Iniciando todos los servicios...")

    def start_flask(self):
        """Iniciar Flask backend"""
        try:
            self.flask_status.config(text="🟡 Iniciando...", foreground="orange")

            # Comando para Flask
            venv_python = "venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python"

            cmd = f'"{venv_python}" "{os.path.join(os.path.dirname(__file__), "app.py")}"'

            self.flask_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                universal_newlines=True
            )

            self.is_flask_running = True
            self.flask_status.config(text="🟢 Ejecutándose", foreground="green")
            self.log("🚀 Flask backend iniciado")

            # Leer output en tiempo real
            def read_flask_output():
                for line in iter(self.flask_process.stdout.readline, ''):
                    if line:
                        self.flask_queue.put(f"[FLASK] {line.strip()}")
                self.flask_process.stdout.close()

            threading.Thread(target=read_flask_output, daemon=True).start()

        except Exception as e:
            self.log(f"❌ Error iniciando Flask: {str(e)}")
            self.flask_status.config(text="🔴 Error", foreground="red")
            self.is_flask_running = False

    def start_node(self):
        """Iniciar WhatsApp bot"""
        try:
            self.node_status.config(text="🟡 Iniciando...", foreground="orange")

            # Cambiar al directorio de node_backend
            node_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "node_backend")

            cmd = f'cd "{node_dir}" && node index.js'

            self.node_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                universal_newlines=True
            )

            self.is_node_running = True
            self.node_status.config(text="🟢 Ejecutándose", foreground="green")
            self.log("🚀 WhatsApp bot iniciado")

            # Leer output en tiempo real
            def read_node_output():
                for line in iter(self.node_process.stdout.readline, ''):
                    if line:
                        self.node_queue.put(f"[WHATSAPP] {line.strip()}")
                self.node_process.stdout.close()

            threading.Thread(target=read_node_output, daemon=True).start()

        except Exception as e:
            self.log(f"❌ Error iniciando Node: {str(e)}")
            self.node_status.config(text="🔴 Error", foreground="red")
            self.is_node_running = False

    def stop_all(self):
        """Detener todos los servicios"""
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

        self.log("⏹️ Deteniendo todos los servicios...")

        # Detener Node.js (WhatsApp)
        if self.node_process and self.is_node_running:
            try:
                self.log("⏹️ Deteniendo WhatsApp bot...")
                if os.name == 'nt':  # Windows
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.node_process.pid)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:  # Linux/Mac
                    self.node_process.terminate()
                    self.node_process.wait(timeout=3)
            except Exception as e:
                self.log(f"⚠️ Error deteniendo Node: {e}")
                try:
                    self.node_process.kill()
                except:
                    pass
            finally:
                self.is_node_running = False
                self.node_status.config(text="🔴 Detenido", foreground="red")

        # Detener Flask
        if self.flask_process and self.is_flask_running:
            try:
                self.log("⏹️ Deteniendo Flask backend...")
                if os.name == 'nt':  # Windows
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.flask_process.pid)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:  # Linux/Mac
                    self.flask_process.terminate()
                    self.flask_process.wait(timeout=3)
            except Exception as e:
                self.log(f"⚠️ Error deteniendo Flask: {e}")
                try:
                    self.flask_process.kill()
                except:
                    pass
            finally:
                self.is_flask_running = False
                self.flask_status.config(text="🔴 Detenido", foreground="red")

        # Limpiar colas
        while not self.flask_queue.empty():
            self.flask_queue.get()
        while not self.node_queue.empty():
            self.node_queue.get()

        self.log("✅ Todos los servicios detenidos")
        self.status_bar.config(text="⏹️ Servicios detenidos")

    def restart_all(self):
        """Reiniciar todos los servicios"""
        self.stop_all()
        time.sleep(2)
        self.start_all()
        self.log("🔄 Reiniciando servicios...")

    def update_logs(self):
        """Actualizar logs en tiempo real"""
        # Procesar logs de Flask
        while not self.flask_queue.empty():
            line = self.flask_queue.get()
            self.flask_log.insert(tk.END, f"{line}\n")
            self.flask_log.see(tk.END)

            # Detectar QR code
            if "qr" in line.lower():
                self.qr_text.config(state="normal")
                self.qr_text.insert(tk.END, f"{line}\n")
                self.qr_text.see(tk.END)
                self.qr_text.config(state="disabled")

        # Procesar logs de Node
        while not self.node_queue.empty():
            line = self.node_queue.get()
            self.node_log.insert(tk.END, f"{line}\n")
            self.node_log.see(tk.END)

            # Detectar QR code
            if "qr" in line.lower():
                self.qr_text.config(state="normal")
                self.qr_text.insert(tk.END, f"{line}\n")
                self.qr_text.see(tk.END)
                self.qr_text.config(state="disabled")

        # Actualizar barra de estado
        if self.is_flask_running and self.is_node_running:
            self.status_bar.config(text="🟢 Todos los servicios ejecutándose")
        elif self.is_flask_running or self.is_node_running:
            self.status_bar.config(text="🟡 Servicios parcialmente ejecutándose")
        else:
            self.status_bar.config(text="🔴 Servicios detenidos")

        # Programar siguiente actualización
        self.root.after(100, self.update_logs)

    def log(self, message):
        """Agregar mensaje a logs"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"

        self.flask_log.insert(tk.END, f"{formatted_message}\n")
        self.flask_log.see(tk.END)
        print(formatted_message)

        # Actualizar barra de estado brevemente
        self.status_bar.config(text=message)
        self.root.after(5000, lambda: self.status_bar.config(
            text="🟢 Ejecutándose" if self.is_flask_running and self.is_node_running else "🔴 Detenido"
        ))

    def test_db_connection(self):
        """Probar conexión a base de datos"""
        try:
            # Importar dinámicamente
            db_utils_path = os.path.join(os.path.dirname(__file__), "db_utils.py")

            if os.path.exists(db_utils_path):
                spec = importlib.util.spec_from_file_location("db_utils", db_utils_path)
                db_utils_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(db_utils_module)

                conn = db_utils_module.get_connection()
                if conn:
                    self.db_result.config(text="✅ Conexión exitosa a la base de datos", foreground="green")
                    conn.close()
                else:
                    self.db_result.config(text="❌ No se pudo conectar a la base de datos", foreground="red")
            else:
                self.db_result.config(text="❌ No se encontró db_utils.py", foreground="red")

        except Exception as e:
            error_msg = f"❌ Error de conexión: {str(e)}"
            self.db_result.config(text=error_msg, foreground="red")
            print(f"Error detallado: {traceback.format_exc()}")

    def search_user_by_dni(self):
        """Buscar usuario por DNI"""
        dni = self.search_dni.get().strip()
        if not dni:
            return

        try:
            # Importar dinámicamente
            db_utils_path = os.path.join(os.path.dirname(__file__), "db_utils.py")

            if os.path.exists(db_utils_path):
                spec = importlib.util.spec_from_file_location("db_utils", db_utils_path)
                db_utils_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(db_utils_module)

                user = db_utils_module.get_user_by_dni(dni)
                self.search_result.delete('1.0', tk.END)

                if user:
                    self.search_result.insert('1.0',
                                              f"✅ Usuario encontrado:\n\n"
                                              f"👤 Nombre: {user.get('nombre', 'N/A')}\n"
                                              f"💰 Adelantos: {user.get('adelantos', 'N/A')}\n"
                                              f"🔢 DNI: {dni}"
                                              )
                else:
                    self.search_result.insert('1.0',
                                              f"❌ No se encontró usuario con DNI: {dni}"
                                              )
            else:
                self.search_result.insert('1.0', "❌ No se encontró db_utils.py")

        except Exception as e:
            self.search_result.insert('1.0', f"❌ Error: {str(e)}")
            print(f"Error detallado: {traceback.format_exc()}")

    def copy_logs(self):
        """Copiar logs al portapapeles"""
        self.root.clipboard_clear()
        logs = self.flask_log.get('1.0', tk.END)
        self.root.clipboard_append(logs)
        self.log("📋 Logs copiados al portapapeles")

    def clear_logs(self):
        """Limpiar todos los logs"""
        self.flask_log.delete('1.0', tk.END)
        self.node_log.delete('1.0', tk.END)
        self.qr_text.config(state="normal")
        self.qr_text.delete('1.0', tk.END)
        self.qr_text.insert('1.0', "Escanea el código QR cuando aparezca aquí...\n\n")
        self.qr_text.config(state="disabled")
        self.log("🧹 Logs limpiados")


def main():
    root = tk.Tk()
    app = BacanoBotGUI(root)

    # Manejar cierre de ventana
    def on_closing():
        app.stop_all()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()