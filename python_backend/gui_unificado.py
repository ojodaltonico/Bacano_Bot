import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import subprocess
import sys
import os
import queue
import json
from datetime import datetime


class BacanoBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🤖 BacanoBot - Control Unificado")
        self.root.geometry("1200x700")
        self.root.configure(bg='#1a1a1a')

        # Procesos
        self.flask_process = None
        self.node_process = None

        # Colas para logs
        self.flask_queue = queue.Queue()
        self.node_queue = queue.Queue()

        self.setup_ui()
        self.load_config()

    def setup_ui(self):
        # Frame principal con notebook (pestañas)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)

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
        self.status_bar = tk.Label(
            self.root,
            text="🟢 Listo",
            bd=1,
            relief=tk.SUNKEN,
            anchor=tk.W,
            bg='green',
            fg='white'
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Botones de control
        control_frame = tk.Frame(self.root)
        control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)

        tk.Button(
            control_frame,
            text="▶️ Iniciar Todo",
            command=self.start_all,
            bg='#28a745',
            fg='white',
            font=('Arial', 10, 'bold')
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            control_frame,
            text="⏹️ Detener Todo",
            command=self.stop_all,
            bg='#dc3545',
            fg='white',
            font=('Arial', 10, 'bold')
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            control_frame,
            text="🔄 Reiniciar",
            command=self.restart_all,
            bg='#ffc107',
            fg='black',
            font=('Arial', 10, 'bold')
        ).pack(side=tk.LEFT, padx=5)

        # Iniciar monitoreo de logs
        self.root.after(100, self.update_logs)

    def setup_dashboard_tab(self):
        # Estado de servicios
        status_frame = ttk.LabelFrame(self.tab_dashboard, text="Estado de Servicios", padding=15)
        status_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Flask Status
        self.flask_status = tk.Label(
            status_frame,
            text="🔴 Flask Backend - Detenido",
            font=('Arial', 12),
            fg='red'
        )
        self.flask_status.grid(row=0, column=0, sticky='w', pady=10, padx=20)

        # Node Status
        self.node_status = tk.Label(
            status_frame,
            text="🔴 WhatsApp Bot - Detenido",
            font=('Arial', 12),
            fg='red'
        )
        self.node_status.grid(row=1, column=0, sticky='w', pady=10, padx=20)

        # QR Code Display
        qr_frame = ttk.LabelFrame(self.tab_dashboard, text="Código QR WhatsApp", padding=15)
        qr_frame.pack(fill='both', expand=True, padx=10, pady=10)

        self.qr_label = tk.Label(
            qr_frame,
            text="Escanea el código QR cuando aparezca aquí...",
            font=('Arial', 10),
            wraplength=400
        )
        self.qr_label.pack(pady=20)

    def setup_logs_tab(self):
        # Frame para logs con pestañas
        logs_notebook = ttk.Notebook(self.tab_logs)
        logs_notebook.pack(fill='both', expand=True)

        # Logs de Flask
        flask_log_frame = ttk.Frame(logs_notebook)
        logs_notebook.add(flask_log_frame, text='Flask Backend')

        self.flask_log = scrolledtext.ScrolledText(
            flask_log_frame,
            wrap=tk.WORD,
            bg='black',
            fg='white',
            insertbackground='white',
            font=('Consolas', 9)
        )
        self.flask_log.pack(fill='both', expand=True, padx=5, pady=5)

        # Logs de Node
        node_log_frame = ttk.Frame(logs_notebook)
        logs_notebook.add(node_log_frame, text='WhatsApp Bot')

        self.node_log = scrolledtext.ScrolledText(
            node_log_frame,
            wrap=tk.WORD,
            bg='black',
            fg='white',
            insertbackground='white',
            font=('Consolas', 9)
        )
        self.node_log.pack(fill='both', expand=True, padx=5, pady=5)

        # Botones para logs
        btn_frame = tk.Frame(self.tab_logs)
        btn_frame.pack(fill='x', padx=10, pady=5)

        tk.Button(
            btn_frame,
            text="📋 Copiar Logs",
            command=self.copy_logs
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_frame,
            text="🧹 Limpiar Logs",
            command=self.clear_logs
        ).pack(side=tk.LEFT, padx=5)

    def setup_config_tab(self):
        # Cargar configuración
        config_frame = ttk.LabelFrame(self.tab_config, text="Configuración", padding=15)
        config_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Configuración de Base de Datos
        ttk.Label(config_frame, text="Host:").grid(row=0, column=0, sticky='w', pady=5)
        self.host_entry = ttk.Entry(config_frame, width=30)
        self.host_entry.grid(row=0, column=1, pady=5, padx=10)

        ttk.Label(config_frame, text="Usuario:").grid(row=1, column=0, sticky='w', pady=5)
        self.user_entry = ttk.Entry(config_frame, width=30)
        self.user_entry.grid(row=1, column=1, pady=5, padx=10)

        ttk.Label(config_frame, text="Contraseña:").grid(row=2, column=0, sticky='w', pady=5)
        self.pass_entry = ttk.Entry(config_frame, width=30, show="*")
        self.pass_entry.grid(row=2, column=1, pady=5, padx=10)

        ttk.Label(config_frame, text="Base de Datos:").grid(row=3, column=0, sticky='w', pady=5)
        self.db_entry = ttk.Entry(config_frame, width=30)
        self.db_entry.grid(row=3, column=1, pady=5, padx=10)

        # Promociones
        ttk.Label(config_frame, text="Promociones (una por línea):").grid(row=4, column=0, sticky='nw', pady=10)
        self.promo_text = scrolledtext.ScrolledText(config_frame, width=40, height=10)
        self.promo_text.grid(row=4, column=1, pady=10, padx=10)

        # Botones
        btn_frame = tk.Frame(config_frame)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=20)

        tk.Button(
            btn_frame,
            text="💾 Guardar Configuración",
            command=self.save_config,
            bg='#007bff',
            fg='white'
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_frame,
            text="📤 Cargar Configuración",
            command=self.load_config,
            bg='#6c757d',
            fg='white'
        ).pack(side=tk.LEFT, padx=5)

    def setup_database_tab(self):
        # Herramientas de BD
        db_frame = ttk.LabelFrame(self.tab_database, text="Herramientas de Base de Datos", padding=15)
        db_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Botón de prueba de conexión
        tk.Button(
            db_frame,
            text="🔍 Probar Conexión a BD",
            command=self.test_db_connection,
            bg='#17a2b8',
            fg='white',
            font=('Arial', 10, 'bold')
        ).pack(pady=10)

        # Resultados de prueba
        self.db_result = tk.Label(
            db_frame,
            text="",
            font=('Arial', 10),
            wraplength=500
        )
        self.db_result.pack(pady=10)

        # Buscar usuario
        ttk.Label(db_frame, text="Buscar por DNI:").pack(pady=5)
        self.search_dni = ttk.Entry(db_frame, width=20)
        self.search_dni.pack(pady=5)

        tk.Button(
            db_frame,
            text="👤 Buscar Usuario",
            command=self.search_user_by_dni
        ).pack(pady=10)

        # Resultados de búsqueda
        self.search_result = scrolledtext.ScrolledText(db_frame, width=60, height=10)
        self.search_result.pack(pady=10)

    def load_config(self):
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)

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
        except Exception as e:
            self.log(f"❌ Error cargando configuración: {e}")

    def save_config(self):
        try:
            config = {
                "database": {
                    "host": self.host_entry.get(),
                    "user": self.user_entry.get(),
                    "password": self.pass_entry.get(),
                    "database": self.db_entry.get()
                },
                "promotions": self.promo_text.get('1.0', tk.END).strip().split('\n')
            }

            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            self.log("✅ Configuración guardada")
            messagebox.showinfo("Éxito", "Configuración guardada correctamente")
        except Exception as e:
            self.log(f"❌ Error guardando configuración: {e}")
            messagebox.showerror("Error", f"Error: {e}")

    def start_all(self):
        """Iniciar todos los servicios"""
        threading.Thread(target=self.start_flask, daemon=True).start()
        threading.Thread(target=self.start_node, daemon=True).start()

    def start_flask(self):
        """Iniciar Flask backend"""
        try:
            self.flask_status.config(text="🟡 Flask Backend - Iniciando...", fg='orange')

            # Activar venv y ejecutar Flask
            if os.name == 'nt':  # Windows
                activate_cmd = os.path.join('venv', 'Scripts', 'activate')
                cmd = f'cmd /c "{activate_cmd} && python python_backend/app.py"'
            else:  # Linux/Mac
                cmd = 'source venv/bin/activate && python python_backend/app.py'

            self.flask_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            self.log("🚀 Flask backend iniciado")
            self.flask_status.config(text="🟢 Flask Backend - Ejecutándose", fg='green')

            # Leer output en tiempo real
            for line in iter(self.flask_process.stdout.readline, ''):
                if line:
                    self.flask_queue.put(line)

        except Exception as e:
            self.log(f"❌ Error iniciando Flask: {e}")
            self.flask_status.config(text="🔴 Flask Backend - Error", fg='red')

    def start_node(self):
        """Iniciar WhatsApp bot"""
        try:
            self.node_status.config(text="🟡 WhatsApp Bot - Iniciando...", fg='orange')

            cmd = 'node node_backend/index.js'
            self.node_process = subprocess.Popen(
                cmd,
                shell=True,
                cwd='node_backend',
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            self.log("🚀 WhatsApp bot iniciado")
            self.node_status.config(text="🟢 WhatsApp Bot - Ejecutándose", fg='green')

            # Leer output en tiempo real
            for line in iter(self.node_process.stdout.readline, ''):
                if line:
                    self.node_queue.put(line)

        except Exception as e:
            self.log(f"❌ Error iniciando Node: {e}")
            self.node_status.config(text="🔴 WhatsApp Bot - Error", fg='red')

    def stop_all(self):
        """Detener todos los servicios"""
        if self.flask_process:
            self.flask_process.terminate()
            self.flask_status.config(text="🔴 Flask Backend - Detenido", fg='red')

        if self.node_process:
            self.node_process.terminate()
            self.node_status.config(text="🔴 WhatsApp Bot - Detenido", fg='red')

        self.log("⏹️ Todos los servicios detenidos")

    def restart_all(self):
        """Reiniciar todos los servicios"""
        self.stop_all()
        self.root.after(2000, self.start_all)
        self.log("🔄 Reiniciando servicios...")

    def update_logs(self):
        """Actualizar logs en tiempo real"""
        # Procesar logs de Flask
        while not self.flask_queue.empty():
            line = self.flask_queue.get()
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.flask_log.insert(tk.END, f"[{timestamp}] {line}")
            self.flask_log.see(tk.END)

            # Detectar QR code
            if "QR" in line.upper() or "ESCANEA" in line.upper():
                self.qr_label.config(text=f"📱 QR Detectado:\n{line}")

        # Procesar logs de Node
        while not self.node_queue.empty():
            line = self.node_queue.get()
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.node_log.insert(tk.END, f"[{timestamp}] {line}")
            self.node_log.see(tk.END)

            # Detectar QR code
            if "QR" in line.upper():
                self.qr_label.config(text=f"📱 QR Code Detectado:\n{line}")

        # Programar siguiente actualización
        self.root.after(100, self.update_logs)

    def log(self, message):
        """Agregar mensaje a logs"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.flask_log.insert(tk.END, f"[{timestamp}] {message}\n")
        self.flask_log.see(tk.END)

        # Actualizar barra de estado
        self.status_bar.config(text=f"📝 {message}")

    def test_db_connection(self):
        """Probar conexión a base de datos"""
        try:
            from python_backend.db_utils import get_connection

            conn = get_connection()
            if conn:
                self.db_result.config(
                    text="✅ Conexión exitosa a la base de datos",
                    fg='green'
                )
                conn.close()
            else:
                self.db_result.config(
                    text="❌ No se pudo conectar a la base de datos",
                    fg='red'
                )
        except Exception as e:
            self.db_result.config(
                text=f"❌ Error: {str(e)}",
                fg='red'
            )

    def search_user_by_dni(self):
        """Buscar usuario por DNI"""
        dni = self.search_dni.get().strip()
        if not dni:
            return

        try:
            from python_backend.db_utils import get_user_by_dni

            user = get_user_by_dni(dni)
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
        except Exception as e:
            self.search_result.insert('1.0', f"❌ Error: {str(e)}")

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
        self.log("🧹 Logs limpiados")


def main():
    root = tk.Tk()
    app = BacanoBotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()