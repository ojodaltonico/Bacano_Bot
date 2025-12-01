@echo off
title Instalación BacanoBot - Todo en Uno
color 0B

echo ===========================================
echo      🚀 Instalando BacanoBot Todo en Uno
echo ===========================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python no está instalado
    echo 📥 Descarga Python: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Verificar Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Node.js no está instalado
    echo 📥 Descarga Node.js: https://nodejs.org/
    pause
    exit /b 1
)

:: ================================
:: NODE (carpeta node_backend)
:: ================================
echo ➤ Instalando dependencias Node...
cd node_backend
call npm install
if errorlevel 1 (
    echo ❌ Error instalando dependencias Node
    pause
    exit /b 1
)
cd ..

echo -------------------------------------------

:: ================================
:: PYTHON (venv global)
:: ================================
echo ➤ Creando entorno virtual Python...
python -m venv venv
if errorlevel 1 (
    echo ❌ Error creando entorno virtual
    pause
    exit /b 1
)

echo ➤ Activando entorno virtual...
call venv\Scripts\activate

echo ➤ Instalando requirements Python...
pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ Error instalando dependencias Python
    pause
    exit /b 1
)

:: ================================
:: CONFIG.JSON
:: ================================
if not exist config.json (
    echo ➤ Creando config.json de ejemplo...
    echo.
    echo 📋 Crea tu config.json con tus datos:
    echo.
    echo {
    echo   "database": {
    echo     "host": "IP",
    echo     "user": "USER",
    echo     "password": "PASS",
    echo     "database": "DB"
    echo   },
    echo   "promotions": [
    echo     "🎊 Champagne para cumpleañeros",
    echo     "🎊 Entrada Free para cumpleañeros"
    echo   ]
    echo }
    echo.
    echo Copia el contenido arriba en config.json
    pause
)

echo -------------------------------------------

echo.
echo ===========================================
echo     ✔ Instalación completada exitosamente!
echo ===========================================
echo.
echo 🚀 Para ejecutar:
echo 1. Asegúrate de tener config.json en la raíz
echo 2. Ejecuta: python run.py
echo.
pause