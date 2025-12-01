@echo off
title BacanoBot - Ejecutando
color 0A

echo 🚀 Iniciando WhatsApp Bot - Bacano Club...
echo 📍 Todo en uno - Entorno virtual incluido
echo.

echo =======================================
echo   BACANO BOT - Controlador unificado
echo =======================================
echo.

:: ================================
:: VALIDAR CONFIG
:: ================================
if not exist python_backend\config.json (
    echo ❌ Falta: python_backend\config.json
    echo Ejecutá install.bat primero.
    goto END
)

:: ================================
:: ACTIVAR PYTHON
:: ================================
echo ✔ Activando entorno virtual Python...
call venv\Scripts\activate

:: INICIAR FLASK
echo ⏳ Iniciando Flask backend...
start "" cmd /c "cd python_backend && ..\venv\Scripts\activate && python app.py"

:: INICIAR GUI
echo 🖥️ Abriendo interfaz gráfica...
start "" python python_backend/gui.py

:: INICIAR BAILEYS
echo ⏳ Iniciando WhatsApp (Node.js)...
start "WhatsApp Node" cmd /k "cd node_backend && node index.js"




echo.
echo ======================================
echo   ✔ Sistema en ejecución
echo   Cuando aparezca QR: escanealo
echo ======================================
echo.

:END
pause
