import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import requests
import json
from config_manager import load_config, update_promotions, update_db_config, get_promotions


class BotControlGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Control Bot WhatsApp - Bacano Club")
        self.root.geometry("800x600")
        self.root.configure(bg='#2c3e50')

        self.config = load_config()
        self.setup_gui()

    def setup_gui(self):
        # Frame principal
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Título
        title_label = ttk.Label(main_frame, text="🤖 Control Bot WhatsApp - Bacano Club",
                                font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))

        # Sección de Estado
        status_frame = ttk.LabelFrame(main_frame, text="Estado del Bot", padding="10")
        status_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        self.status_label = ttk.Label(status_frame, text="🔴 Bot Inactivo",
                                      font=('Arial', 12), foreground='red')
        self.status_label.grid(row=0, column=0, sticky=tk.W)

        # Sección de Configuración de Base de Datos
        db_frame = ttk.LabelFrame(main_frame, text="Configuración Base de Datos", padding="10")
        db_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Label(db_frame, text="Host:").grid(row=0, column=0, sticky=tk.W)
        self.host_entry = ttk.Entry(db_frame, width=20)
        self.host_entry.grid(row=0, column=1, padx=(5, 10))
        self.host_entry.insert(0, self.config['database']['host'])

        ttk.Label(db_frame, text="Usuario:").grid(row=0, column=2, sticky=tk.W)
        self.user_entry = ttk.Entry(db_frame, width=15)
        self.user_entry.grid(row=0, column=3, padx=(5, 10))
        self.user_entry.insert(0, self.config['database']['user'])

        ttk.Label(db_frame, text="Contraseña:").grid(row=1, column=0, sticky=tk.W)
        self.password_entry = ttk.Entry(db_frame, width=20, show="*")
        self.password_entry.grid(row=1, column=1, padx=(5, 10))
        self.password_entry.insert(0, self.config['database']['password'])

        ttk.Label(db_frame, text="Base de Datos:").grid(row=1, column=2, sticky=tk.W)
        self.database_entry = ttk.Entry(db_frame, width=15)
        self.database_entry.grid(row=1, column=3, padx=(5, 10))
        self.database_entry.insert(0, self.config['database']['database'])

        ttk.Button(db_frame, text="Guardar DB",
                   command=self.save_db_config).grid(row=2, column=0, columnspan=4, pady=(10, 0))

        # Sección de Promociones
        promo_frame = ttk.LabelFrame(main_frame, text="Gestión de Promociones", padding="10")
        promo_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))

        ttk.Label(promo_frame, text="Promociones (una por línea):").grid(row=0, column=0, sticky=tk.W)

        self.promo_text = scrolledtext.ScrolledText(promo_frame, width=60, height=6)
        self.promo_text.grid(row=1, column=0, columnspan=2, pady=(5, 10))

        # Cargar promociones actuales
        current_promos = "\n".join(self.config['promotions'])
        self.promo_text.insert('1.0', current_promos)

        ttk.Button(promo_frame, text="Guardar Promociones",
                   command=self.save_promotions).grid(row=2, column=0, pady=(0, 5))

        ttk.Button(promo_frame, text="Ver Promociones Actuales",
                   command=self.show_current_promotions).grid(row=2, column=1, pady=(0, 5))

        # Sección de Logs
        log_frame = ttk.LabelFrame(main_frame, text="Logs del Sistema", padding="10")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.log_text = scrolledtext.ScrolledText(log_frame, width=80, height=10)
        self.log_text.grid(row=0, column=0, columnspan=2)

        # Configurar pesos para responsive
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)

        self.log("✅ Interfaz iniciada correctamente")
        self.log("📋 Cargada configuración actual")

    def save_db_config(self):
        """Guardar configuración de base de datos"""
        try:
            db_config = {
                "host": self.host_entry.get(),
                "user": self.user_entry.get(),
                "password": self.password_entry.get(),
                "database": self.database_entry.get()
            }

            if update_db_config(db_config):
                self.log("✅ Configuración de DB guardada correctamente")
                messagebox.showinfo("Éxito", "Configuración de base de datos guardada")
            else:
                self.log("❌ Error guardando configuración de DB")
                messagebox.showerror("Error", "No se pudo guardar la configuración")

        except Exception as e:
            self.log(f"❌ Error: {str(e)}")
            messagebox.showerror("Error", f"Error guardando configuración: {str(e)}")

    def save_promotions(self):
        """Guardar promociones"""
        try:
            promotions_text = self.promo_text.get('1.0', tk.END).strip()
            promotions = [promo.strip() for promo in promotions_text.split('\n') if promo.strip()]

            if update_promotions(promotions):
                self.log(f"✅ Promociones guardadas: {len(promotions)} promociones")
                messagebox.showinfo("Éxito", f"Promociones guardadas: {len(promotions)} items")
            else:
                self.log("❌ Error guardando promociones")
                messagebox.showerror("Error", "No se pudo guardar las promociones")

        except Exception as e:
            self.log(f"❌ Error: {str(e)}")
            messagebox.showerror("Error", f"Error guardando promociones: {str(e)}")

    def show_current_promotions(self):
        """Mostrar promociones actuales en un messagebox"""
        promotions = get_promotions()
        messagebox.showinfo("Promociones Actuales", promotions)

    def log(self, message):
        """Agregar mensaje al log"""
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)

    def check_bot_status(self):
        """Verificar estado del bot (placeholder)"""
        # Aquí puedes implementar la verificación del estado real
        pass


def main():
    root = tk.Tk()
    app = BotControlGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()