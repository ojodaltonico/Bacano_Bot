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

from services.balance_admin_service import BalanceAdminService
from services.balance_settings_service import BalanceSettingsService
from services.ticket_admin_service import TicketAdminService
from services.ticket_settings_service import TicketSettingsService
from utils.phone_utils import normalize_argentine_phone


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
        self.balance_settings_service = BalanceSettingsService()
        self.balance_admin_service = None
        self.balance_rows = {}
        self.ticket_settings_service = TicketSettingsService()
        self.ticket_admin_service = None
        self.ticket_rows = {}
        self.ticket_selected_order_id = None
        self.ticket_detail_data = None

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

        # Pestaña de administración de cargas de saldo
        self.tab_balance = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_balance, text='💳 Cargas')
        self.setup_balance_tab()

        # Pestaña de administración de entradas
        self.tab_tickets = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_tickets, text='🎟 Entradas')
        self.setup_tickets_tab()

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

    def setup_balance_tab(self):
        controls = ttk.LabelFrame(self.tab_balance, text="Controles operativos", padding=10)
        controls.pack(fill="x", padx=10, pady=10)

        self.accept_new_loads_var = tk.BooleanVar(value=False)
        self.monitor_payments_var = tk.BooleanVar(value=False)
        self.auto_credit_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            controls,
            text="Aceptar nuevas cargas",
            variable=self.accept_new_loads_var,
        ).grid(row=0, column=0, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(
            controls,
            text="Monitorear pagos iniciados",
            variable=self.monitor_payments_var,
            command=self.on_monitor_toggle,
        ).grid(row=0, column=1, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(
            controls,
            text="Acreditar automáticamente",
            variable=self.auto_credit_var,
            command=self.on_auto_credit_toggle,
        ).grid(row=0, column=2, sticky="w", padx=5, pady=3)

        ttk.Label(controls, text="Order ID mínimo:").grid(row=1, column=0, sticky="e", padx=5)
        self.balance_after_order_entry = ttk.Entry(controls, width=14)
        self.balance_after_order_entry.grid(row=1, column=1, sticky="w", padx=5)
        ttk.Label(controls, text="Fecha mínima ISO:").grid(row=1, column=2, sticky="e", padx=5)
        self.balance_after_date_entry = ttk.Entry(controls, width=25)
        self.balance_after_date_entry.grid(row=1, column=3, sticky="w", padx=5)
        ttk.Label(controls, text="Intervalo (seg):").grid(row=1, column=4, sticky="e", padx=5)
        self.balance_interval_entry = ttk.Entry(controls, width=8)
        self.balance_interval_entry.grid(row=1, column=5, sticky="w", padx=5)
        ttk.Button(controls, text="Guardar controles", command=self.save_balance_settings).grid(
            row=0, column=5, padx=10, pady=3
        )

        filters = ttk.Frame(self.tab_balance)
        filters.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(filters, text="Estado:").pack(side="left")
        self.balance_status_filter = ttk.Combobox(
            filters,
            state="readonly",
            values=("Todos", "Pendiente", "Pagado", "Acreditado", "Cancelado", "Fallido", "Error"),
            width=14,
        )
        self.balance_status_filter.set("Todos")
        self.balance_status_filter.pack(side="left", padx=5)
        ttk.Label(filters, text="Order ID:").pack(side="left", padx=(15, 0))
        self.balance_order_search = ttk.Entry(filters, width=14)
        self.balance_order_search.pack(side="left", padx=5)
        ttk.Button(filters, text="Actualizar", command=self.refresh_balance_loads).pack(side="left", padx=5)
        self.balance_refresh_status = ttk.Label(filters, text="")
        self.balance_refresh_status.pack(side="left", padx=10)

        content = ttk.Panedwindow(self.tab_balance, orient=tk.VERTICAL)
        content.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        table_frame = ttk.Frame(content)
        detail_frame = ttk.LabelFrame(content, text="Detalle de la carga", padding=8)
        content.add(table_frame, weight=3)
        content.add(detail_frame, weight=2)

        columns = (
            "order_id", "date", "client", "dni", "amount", "method",
            "woo_status", "local_status", "accreditation", "error",
        )
        self.balance_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
        headings = {
            "order_id": "Order ID", "date": "Fecha", "client": "Cliente", "dni": "DNI",
            "amount": "Importe", "method": "Método", "woo_status": "WooCommerce",
            "local_status": "Estado local", "accreditation": "Acreditación", "error": "Último error",
        }
        widths = {"order_id": 75, "date": 145, "client": 150, "dni": 80, "amount": 85,
                  "method": 150, "woo_status": 95, "local_status": 95,
                  "accreditation": 90, "error": 220}
        for column in columns:
            self.balance_tree.heading(column, text=headings[column])
            self.balance_tree.column(column, width=widths[column], anchor="w")
        vertical_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.balance_tree.yview)
        horizontal_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.balance_tree.xview)
        self.balance_tree.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        self.balance_tree.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.balance_tree.bind("<<TreeviewSelect>>", self.on_balance_selected)

        self.balance_detail = scrolledtext.ScrolledText(detail_frame, height=9, wrap=tk.WORD)
        self.balance_detail.pack(fill="both", expand=True)
        self.balance_detail.insert("1.0", "Seleccioná una carga para ver el detalle.")
        self.balance_detail.config(state="disabled")
        self.load_balance_settings()

    def load_balance_settings(self):
        settings = self.balance_settings_service.get_settings()
        self.accept_new_loads_var.set(settings["accept_new_loads"])
        self.monitor_payments_var.set(settings["monitor_payments"])
        self.auto_credit_var.set(settings["auto_credit"])
        self.balance_after_order_entry.delete(0, tk.END)
        self.balance_after_order_entry.insert(0, settings.get("monitor_after_order_id") or "")
        self.balance_after_date_entry.delete(0, tk.END)
        self.balance_after_date_entry.insert(0, settings.get("monitor_after_date") or "")
        self.balance_interval_entry.delete(0, tk.END)
        self.balance_interval_entry.insert(0, settings.get("monitor_interval") or 60)

    def on_monitor_toggle(self):
        if not self.monitor_payments_var.get():
            self.auto_credit_var.set(False)

    def on_auto_credit_toggle(self):
        if self.auto_credit_var.get() and not self.monitor_payments_var.get():
            self.auto_credit_var.set(False)
            messagebox.showwarning("Control seguro", "Primero habilitá el monitoreo de pagos.")

    def save_balance_settings(self):
        try:
            settings = self.balance_settings_service.update_settings(
                accept_new_loads=self.accept_new_loads_var.get(),
                monitor_payments=self.monitor_payments_var.get(),
                auto_credit=self.auto_credit_var.get(),
                monitor_after_order_id=self.balance_after_order_entry.get().strip() or None,
                monitor_after_date=self.balance_after_date_entry.get().strip() or None,
                monitor_interval=self.balance_interval_entry.get().strip() or 60,
            )
            self.load_balance_settings()
            self.log("✅ Controles operativos de cargas guardados")
            messagebox.showinfo("Cargas", "Controles guardados correctamente.")
            return settings
        except Exception as exc:
            messagebox.showerror("Cargas", str(exc))
            return None

    def refresh_balance_loads(self):
        raw_order_id = self.balance_order_search.get().strip()
        if raw_order_id and not raw_order_id.isdigit():
            messagebox.showerror("Cargas", "El Order ID debe ser numérico.")
            return
        order_id = int(raw_order_id) if raw_order_id else None
        status = self.balance_status_filter.get()
        settings = self.balance_settings_service.get_settings()
        self.balance_refresh_status.config(text="Actualizando...")

        def worker():
            try:
                if self.balance_admin_service is None:
                    self.balance_admin_service = BalanceAdminService()
                rows = self.balance_admin_service.list_recent_loads(
                    limit=100,
                    status=status,
                    order_id=order_id,
                    refresh_remote=bool(settings["monitor_payments"]),
                )
                self.root.after(0, lambda: self.populate_balance_rows(rows))
            except Exception as exc:
                message = str(exc)
                self.root.after(0, lambda value=message: self.balance_refresh_failed(value))

        threading.Thread(target=worker, daemon=True).start()

    def populate_balance_rows(self, rows):
        self.balance_tree.delete(*self.balance_tree.get_children())
        self.balance_rows = {int(row["order_id"]): row for row in rows}
        for row in rows:
            self.balance_tree.insert("", "end", iid=str(row["order_id"]), values=(
                row["order_id"], row.get("date") or "-", row.get("client_name") or "-",
                row.get("dni_masked") or "-", row.get("amount") or "-",
                row.get("payment_method") or "-", row.get("woocommerce_status") or "-",
                row.get("display_status") or "-", row.get("accreditation") or "No",
                row.get("last_error") or "",
            ))
        self.balance_refresh_status.config(text=f"{len(rows)} carga(s)")

    def balance_refresh_failed(self, message):
        self.balance_refresh_status.config(text="Error")
        messagebox.showerror("Cargas", message)

    def on_balance_selected(self, _event=None):
        selected = self.balance_tree.selection()
        if not selected or self.balance_admin_service is None:
            return
        order_id = int(selected[0])
        self.set_balance_detail_text("Cargando detalle...")

        def worker():
            try:
                detail = self.balance_admin_service.get_load_detail(order_id, refresh_remote=False) or {}
                detail.update({
                    key: value
                    for key, value in self.balance_rows.get(order_id, {}).items()
                    if value is not None
                })
                self.root.after(0, lambda value=detail: self.render_balance_detail(value))
            except Exception as exc:
                message = str(exc)
                self.root.after(0, lambda value=message: self.balance_refresh_failed(value))

        threading.Thread(target=worker, daemon=True).start()

    def render_balance_detail(self, detail):
        monitor = detail.get("monitor_info") or {}
        text = (
            f"Referencia: {detail.get('reference') or '-'}\n"
            f"Fecha de pago: {detail.get('date_paid') or '-'}\n"
            f"Saldo anterior: {detail.get('previous_balance') or '-'}\n"
            f"Importe: {detail.get('credited_amount') or detail.get('amount') or '-'}\n"
            f"Saldo posterior: {detail.get('new_balance') or '-'}\n"
            f"Recarga asociada: {detail.get('recarga_id') or '-'}\n"
            f"Historial asociado: {detail.get('historial_id') or '-'}\n"
            f"Error administrativo: {detail.get('admin_error') or detail.get('last_error') or '-'}\n"
            f"Monitor: estado={monitor.get('local_status') or detail.get('local_status') or '-'} | "
            f"pagado={monitor.get('paid')} | acreditado={detail.get('credited')} | "
            f"puede acreditar={monitor.get('can_credit')}\n"
            f"Motivo: {monitor.get('reason') or detail.get('reason') or '-'}"
        )
        self.set_balance_detail_text(text)

    def set_balance_detail_text(self, text):
        self.balance_detail.config(state="normal")
        self.balance_detail.delete("1.0", tk.END)
        self.balance_detail.insert("1.0", text)
        self.balance_detail.config(state="disabled")

    def setup_tickets_tab(self):
        controls = ttk.LabelFrame(self.tab_tickets, text="Controles operativos", padding=10)
        controls.pack(fill="x", padx=10, pady=10)

        self.ticket_monitor_enabled_var = tk.BooleanVar(value=False)
        self.ticket_test_mode_var = tk.BooleanVar(value=True)
        self.ticket_auto_send_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            controls,
            text="Monitor de entradas ON",
            variable=self.ticket_monitor_enabled_var,
            command=self.on_ticket_monitor_toggle,
        ).grid(row=0, column=0, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(
            controls,
            text="Modo prueba",
            variable=self.ticket_test_mode_var,
            command=self.on_ticket_test_mode_toggle,
        ).grid(row=0, column=1, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(
            controls,
            text="Envio automatico al comprador",
            variable=self.ticket_auto_send_var,
            command=self.on_ticket_auto_send_toggle,
        ).grid(row=0, column=2, sticky="w", padx=5, pady=3)
        ttk.Button(controls, text="Guardar controles", command=self.save_ticket_settings).grid(
            row=0, column=5, padx=10, pady=3
        )

        ttk.Label(controls, text="Telefono de prueba:").grid(row=1, column=0, sticky="e", padx=5)
        self.ticket_test_phone_entry = ttk.Entry(controls, width=18)
        self.ticket_test_phone_entry.grid(row=1, column=1, sticky="w", padx=5)
        ttk.Label(controls, text="Intervalo (seg):").grid(row=1, column=2, sticky="e", padx=5)
        self.ticket_interval_entry = ttk.Entry(controls, width=8)
        self.ticket_interval_entry.grid(row=1, column=3, sticky="w", padx=5)

        self.ticket_mode_label = ttk.Label(controls, text="Modo efectivo: monitor apagado", foreground="gray")
        self.ticket_mode_label.grid(row=2, column=0, columnspan=6, sticky="w", padx=5, pady=(6, 0))

        advanced = ttk.LabelFrame(
            self.tab_tickets,
            text="Configuracion avanzada / backfill inicial",
            padding=8,
        )
        advanced.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(
            advanced,
            text="Sirve para definir desde donde empezar a revisar pedidos historicos. No es un control cotidiano.",
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=5, pady=(0, 6))
        ttk.Label(advanced, text="Order ID minimo:").grid(row=1, column=0, sticky="e", padx=5)
        self.ticket_after_order_entry = ttk.Entry(advanced, width=14)
        self.ticket_after_order_entry.grid(row=1, column=1, sticky="w", padx=5)
        ttk.Label(advanced, text="Fecha minima ISO:").grid(row=1, column=2, sticky="e", padx=5)
        self.ticket_after_date_entry = ttk.Entry(advanced, width=25)
        self.ticket_after_date_entry.grid(row=1, column=3, sticky="w", padx=5)

        filters = ttk.Frame(self.tab_tickets)
        filters.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(filters, text="Estado:").pack(side="left")
        self.ticket_status_filter = ttk.Combobox(
            filters,
            state="readonly",
            values=(
                "Todos",
                "Detectado",
                "Esperando pago",
                "Esperando ticket",
                "Listo",
                "Enviando",
                "Enviado",
                "Error reintentable",
                "Error permanente",
                "Ignorado",
                "Simulado",
            ),
            width=18,
        )
        self.ticket_status_filter.set("Todos")
        self.ticket_status_filter.pack(side="left", padx=5)
        self.ticket_show_ignored_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filters,
            text="Mostrar ignorados",
            variable=self.ticket_show_ignored_var,
        ).pack(side="left", padx=(10, 5))
        ttk.Label(filters, text="Order ID:").pack(side="left", padx=(15, 0))
        self.ticket_order_search = ttk.Entry(filters, width=14)
        self.ticket_order_search.pack(side="left", padx=5)
        ttk.Button(filters, text="Actualizar", command=self.refresh_ticket_deliveries).pack(side="left", padx=5)
        self.ticket_refresh_status = ttk.Label(filters, text="")
        self.ticket_refresh_status.pack(side="left", padx=10)

        content = ttk.Panedwindow(self.tab_tickets, orient=tk.HORIZONTAL)
        content.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        table_frame = ttk.Frame(content)
        detail_frame = ttk.LabelFrame(content, text="Detalle del pedido", padding=8)
        content.add(table_frame, weight=3)
        content.add(detail_frame, weight=2)

        columns = (
            "order_id", "date", "client", "original_phone", "normalized_phone",
            "expected", "progress", "status", "last_sent", "error",
        )
        self.ticket_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {
            "order_id": "Order ID",
            "date": "Fecha",
            "client": "Cliente",
            "original_phone": "Telefono original",
            "normalized_phone": "Telefono WhatsApp",
            "expected": "Esperados",
            "progress": "Encontrados/Enviados",
            "status": "Estado",
            "last_sent": "Ultimo envio",
            "error": "Ultimo error",
        }
        widths = {
            "order_id": 80,
            "date": 145,
            "client": 150,
            "original_phone": 120,
            "normalized_phone": 135,
            "expected": 70,
            "progress": 120,
            "status": 120,
            "last_sent": 145,
            "error": 220,
        }
        for column in columns:
            self.ticket_tree.heading(column, text=headings[column])
            self.ticket_tree.column(column, width=widths[column], anchor="w")
        v_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.ticket_tree.yview)
        h_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.ticket_tree.xview)
        self.ticket_tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        self.ticket_tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.ticket_tree.bind("<<TreeviewSelect>>", self.on_ticket_selected)

        form = ttk.Frame(detail_frame)
        form.pack(fill="x", pady=(0, 8))
        form.grid_columnconfigure(1, weight=1)
        self.ticket_detail_labels = {}
        row = 0
        for key, label in (
            ("order_id", "Order ID"),
            ("client_name", "Cliente"),
            ("original_phone", "Telefono WooCommerce"),
            ("normalized_phone", "Telefono normalizado"),
            ("expected_tickets", "Tickets"),
            ("display_status", "Estado"),
            ("last_sent_at", "Ultimo envio"),
            ("last_error", "Ultimo error"),
        ):
            ttk.Label(form, text=f"{label}:").grid(row=row, column=0, sticky="nw", padx=(0, 6), pady=2)
            value = ttk.Label(form, text="-", wraplength=260, justify="left")
            value.grid(row=row, column=1, sticky="w", pady=2)
            self.ticket_detail_labels[key] = value
            row += 1

        destination_frame = ttk.Frame(detail_frame)
        destination_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(destination_frame, text="Telefono destino editable:").pack(anchor="w")
        self.ticket_destination_entry = ttk.Entry(destination_frame)
        self.ticket_destination_entry.pack(fill="x", pady=(2, 4))
        self.ticket_destination_preview = ttk.Label(destination_frame, text="Normalizado: -", foreground="gray")
        self.ticket_destination_preview.pack(anchor="w")
        self.ticket_destination_entry.bind("<KeyRelease>", self.on_ticket_destination_changed)

        ttk.Label(detail_frame, text="PDFs disponibles:").pack(anchor="w")
        self.ticket_pdf_list = tk.Listbox(detail_frame, height=5)
        self.ticket_pdf_list.pack(fill="both", expand=False, pady=(2, 6))

        action_frame = ttk.Frame(detail_frame)
        action_frame.pack(fill="x", pady=(0, 6))
        ttk.Button(action_frame, text="Reenviar tickets", command=self.manual_resend_selected_ticket).pack(side="left")

        self.ticket_detail = scrolledtext.ScrolledText(detail_frame, height=9, wrap=tk.WORD)
        self.ticket_detail.pack(fill="both", expand=True)
        self.ticket_detail.insert("1.0", "Selecciona un pedido para ver detalle y reenviar manualmente.")
        self.ticket_detail.config(state="disabled")

        self.load_ticket_settings()

    def load_ticket_settings(self):
        settings = self.ticket_settings_service.get_settings()
        self.ticket_monitor_enabled_var.set(settings["monitor_enabled"])
        self.ticket_test_mode_var.set(settings["test_mode"])
        self.ticket_auto_send_var.set(settings["auto_send_customer"])
        self.ticket_test_phone_entry.delete(0, tk.END)
        self.ticket_test_phone_entry.insert(0, settings.get("test_phone") or "")
        self.ticket_after_order_entry.delete(0, tk.END)
        self.ticket_after_order_entry.insert(0, settings.get("monitor_after_order_id") or "")
        self.ticket_after_date_entry.delete(0, tk.END)
        self.ticket_after_date_entry.insert(0, settings.get("monitor_after_date") or "")
        self.ticket_interval_entry.delete(0, tk.END)
        self.ticket_interval_entry.insert(0, settings.get("monitor_interval") or 60)
        self.refresh_ticket_mode_label()

    def refresh_ticket_mode_label(self):
        if not self.ticket_monitor_enabled_var.get():
            text = "Modo efectivo: monitor apagado"
        elif self.ticket_test_mode_var.get():
            text = "Modo efectivo: live-test (solo telefono de prueba)"
        elif self.ticket_auto_send_var.get():
            text = "Modo efectivo: envio automatico al comprador"
        else:
            text = "Modo efectivo: simulacion segura sin envio automatico"
        self.ticket_mode_label.config(text=text)

    def on_ticket_monitor_toggle(self):
        if not self.ticket_monitor_enabled_var.get():
            self.ticket_auto_send_var.set(False)
        self.refresh_ticket_mode_label()

    def on_ticket_test_mode_toggle(self):
        if self.ticket_test_mode_var.get():
            self.ticket_auto_send_var.set(False)
        self.refresh_ticket_mode_label()

    def on_ticket_auto_send_toggle(self):
        if self.ticket_auto_send_var.get():
            if not self.ticket_monitor_enabled_var.get():
                self.ticket_auto_send_var.set(False)
                messagebox.showwarning("Entradas", "Primero activa el monitor.")
            elif self.ticket_test_mode_var.get():
                self.ticket_auto_send_var.set(False)
                messagebox.showwarning("Entradas", "El modo prueba tiene prioridad absoluta.")
        self.refresh_ticket_mode_label()

    def save_ticket_settings(self):
        try:
            settings = self.ticket_settings_service.update_settings(
                monitor_enabled=self.ticket_monitor_enabled_var.get(),
                test_mode=self.ticket_test_mode_var.get(),
                auto_send_customer=self.ticket_auto_send_var.get(),
                test_phone=self.ticket_test_phone_entry.get().strip() or None,
                monitor_after_order_id=self.ticket_after_order_entry.get().strip() or None,
                monitor_after_date=self.ticket_after_date_entry.get().strip() or None,
                monitor_interval=self.ticket_interval_entry.get().strip() or 60,
            )
            self.load_ticket_settings()
            self.log("Controles operativos de entradas guardados")
            messagebox.showinfo("Entradas", "Controles guardados correctamente.")
            return settings
        except Exception as exc:
            messagebox.showerror("Entradas", str(exc))
            return None

    def refresh_ticket_deliveries(self):
        raw_order_id = self.ticket_order_search.get().strip()
        if raw_order_id and not raw_order_id.isdigit():
            messagebox.showerror("Entradas", "El Order ID debe ser numerico.")
            return
        order_id = int(raw_order_id) if raw_order_id else None
        status = self.ticket_status_filter.get()
        self.ticket_refresh_status.config(text="Actualizando...")

        def worker():
            try:
                if self.ticket_admin_service is None:
                    self.ticket_admin_service = TicketAdminService()
                rows = self.ticket_admin_service.list_recent_deliveries(
                    limit=100,
                    status=status,
                    order_id=order_id,
                    show_ignored=self.ticket_show_ignored_var.get(),
                )
                self.root.after(0, lambda: self.populate_ticket_rows(rows))
            except Exception as exc:
                self.root.after(0, lambda value=str(exc): self.ticket_refresh_failed(value))

        threading.Thread(target=worker, daemon=True).start()

    def populate_ticket_rows(self, rows):
        self.ticket_tree.delete(*self.ticket_tree.get_children())
        self.ticket_rows = {int(row["order_id"]): row for row in rows}
        for row in rows:
            self.ticket_tree.insert("", "end", iid=str(row["order_id"]), values=(
                row["order_id"],
                row.get("date") or "-",
                row.get("client_name") or "-",
                row.get("original_phone") or "-",
                row.get("normalized_phone") or "-",
                row.get("expected_tickets") or 0,
                row.get("ticket_progress") or "0/0",
                row.get("display_status") or "-",
                row.get("last_sent_at") or "-",
                row.get("last_error") or "-",
            ))
        self.ticket_refresh_status.config(text=f"{len(rows)} entrega(s)")

    def ticket_refresh_failed(self, message):
        self.ticket_refresh_status.config(text="Error")
        messagebox.showerror("Entradas", message)

    def on_ticket_selected(self, _event=None):
        selected = self.ticket_tree.selection()
        if not selected:
            return
        self.ticket_selected_order_id = int(selected[0])
        self.set_ticket_detail_text("Cargando detalle...")
        self.ticket_pdf_list.delete(0, tk.END)

        def worker():
            try:
                if self.ticket_admin_service is None:
                    self.ticket_admin_service = TicketAdminService()
                detail = self.ticket_admin_service.get_delivery_detail(
                    self.ticket_selected_order_id,
                    include_pdfs=True,
                )
                self.root.after(0, lambda value=detail: self.render_ticket_detail(value))
            except Exception as exc:
                self.root.after(0, lambda value=str(exc): self.ticket_refresh_failed(value))

        threading.Thread(target=worker, daemon=True).start()

    def render_ticket_detail(self, detail):
        self.ticket_detail_data = detail
        for key, widget in self.ticket_detail_labels.items():
            value = detail.get(key)
            if key == "expected_tickets":
                value = (
                    f"{detail.get('expected_tickets', 0)} esperados | "
                    f"{detail.get('found_tickets', 0)} encontrados | "
                    f"{detail.get('sent_tickets', 0)} enviados"
                )
            widget.config(text=value or "-")

        destination = detail.get("destination_phone") or ""
        self.ticket_destination_entry.delete(0, tk.END)
        self.ticket_destination_entry.insert(0, destination)
        self.on_ticket_destination_changed()

        self.ticket_pdf_list.delete(0, tk.END)
        pdf_files = detail.get("pdf_files") or []
        for pdf_file in pdf_files:
            self.ticket_pdf_list.insert(tk.END, pdf_file)
        if not pdf_files and detail.get("pdf_error"):
            self.ticket_pdf_list.insert(tk.END, f"Sin PDFs listos: {detail['pdf_error']}")

        manual_lines = []
        for item in detail.get("manual_history") or []:
            manual_lines.append(
                f"- {item.get('created_at')} | {item.get('status')} | "
                f"{item.get('normalized_phone') or item.get('destination_phone')}"
            )
        text = (
            f"Order ID: {detail.get('order_id')}\n"
            f"Cliente: {detail.get('client_name')}\n"
            f"Telefono original: {detail.get('original_phone') or '-'}\n"
            f"Telefono normalizado: {detail.get('normalized_phone') or '-'}\n"
            f"Estado: {detail.get('display_status')}\n"
            f"Ultimo error: {detail.get('last_error') or '-'}\n"
            f"Ultimo envio: {detail.get('last_sent_at') or '-'}\n"
            f"PDFs listos: {detail.get('pdf_count', 0)}\n"
            f"Historial manual:\n"
            + ("\n".join(manual_lines) if manual_lines else "- Sin reenvios manuales")
        )
        self.set_ticket_detail_text(text)

    def on_ticket_destination_changed(self, _event=None):
        raw_phone = self.ticket_destination_entry.get().strip()
        normalized = normalize_argentine_phone(raw_phone)
        if normalized:
            self.ticket_destination_preview.config(text=f"Normalizado: {normalized}", foreground="green")
        elif raw_phone:
            self.ticket_destination_preview.config(text="Normalizado: numero invalido", foreground="red")
        else:
            self.ticket_destination_preview.config(text="Normalizado: -", foreground="gray")

    def manual_resend_selected_ticket(self):
        if not self.ticket_detail_data or not self.ticket_selected_order_id:
            messagebox.showwarning("Entradas", "Selecciona un pedido primero.")
            return

        destination_phone = self.ticket_destination_entry.get().strip()
        normalized = normalize_argentine_phone(destination_phone)
        if not normalized:
            messagebox.showerror("Entradas", "El telefono de destino no es valido.")
            return

        pdf_count = len(self.ticket_detail_data.get("pdf_files") or [])
        if pdf_count <= 0:
            messagebox.showerror("Entradas", "No hay PDFs disponibles para reenviar.")
            return

        order_id = int(self.ticket_selected_order_id)

        if not messagebox.askyesno(
            "Reenviar tickets",
            f"Order ID: {order_id}\n"
            f"Comprador: {self.ticket_detail_data.get('client_name') or '-'}\n"
            f"Telefono original: {self.ticket_detail_data.get('original_phone') or '-'}\n"
            f"Telefono destino: {normalized}\n"
            f"Cantidad de tickets/PDFs: {pdf_count}\n\n"
            "Confirmas el reenvio manual?",
        ):
            return
        self.ticket_refresh_status.config(text="Reenviando...")

        def worker():
            try:
                if self.ticket_admin_service is None:
                    self.ticket_admin_service = TicketAdminService()
                result = self.ticket_admin_service.resend_tickets(order_id, destination_phone)
                self.root.after(0, lambda value=result: self.handle_manual_resend_result(value))
            except Exception as exc:
                self.root.after(0, lambda value=str(exc): self.ticket_refresh_failed(value))

        threading.Thread(target=worker, daemon=True).start()

    def handle_manual_resend_result(self, result):
        if result.get("ok"):
            self.ticket_refresh_status.config(text="Reenvio manual OK")
            self.log(f"Reenvio manual de entradas OK para order {result.get('order_id')}")
            messagebox.showinfo(
                "Entradas",
                f"Se reenviaron {result.get('sent_tickets', 0)} PDF(s) a {result.get('normalized_destination')}.",
            )
        else:
            self.ticket_refresh_status.config(text="Reenvio manual con error")
            messagebox.showerror("Entradas", str(result.get("reason") or "No se pudo reenviar."))
        self.refresh_ticket_deliveries()
        if self.ticket_selected_order_id:
            self.on_ticket_selected()

    def set_ticket_detail_text(self, text):
        self.ticket_detail.config(state="normal")
        self.ticket_detail.delete("1.0", tk.END)
        self.ticket_detail.insert("1.0", text)
        self.ticket_detail.config(state="disabled")

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
        try:
            print(formatted_message)
        except UnicodeEncodeError:
            safe_message = formatted_message.encode("cp1252", errors="replace").decode("cp1252")
            print(safe_message)

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
