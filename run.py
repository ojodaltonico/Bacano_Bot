#!/usr/bin/env python3
"""
BacanoBot - Controlador Unificado
Ejecuta todo en una sola ventana con GUI
"""

import tkinter as tk
from python_backend.gui_unificado import BacanoBotGUI
import sys
import os


def main():
    # Verificar config.json
    if not os.path.exists('config.json'):
        print("❌ Error: No se encontró config.json")
        print("📋 Crea un archivo config.json en la raíz con:")
        print("""
{
  "database": {
    "host": "IP",
    "user": "USER",
    "password": "PASS",
    "database": "DB"
  },
  "promotions": [
    "🎊 Champagne para cumpleañeros",
    "🎊 Entrada Free para cumpleañeros"
  ]
}
        """)
        input("Presiona Enter para salir...")
        return

    # Iniciar GUI
    root = tk.Tk()
    app = BacanoBotGUI(root)

    # Centrar ventana
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')

    root.mainloop()


if __name__ == "__main__":
    main()