@echo off
title BacanoBot - Control Unificado
color 0A

echo =======================================
echo   🤖 BACANO BOT - Control Unificado
echo =======================================
echo.

:: Verificar que estamos en el directorio correcto
if not exist "python_backend\gui_unificado.py" (
    echo ❌ Error: Debes ejecutar este archivo desde la raíz del proyecto
    echo.
    echo La estructura debe ser:
    echo BacanoBot/
    echo   ├── run.bat
    echo   ├── config.json
    echo   └── python_backend/
    echo        └── gui_unificado.py
    echo.
    pause
    exit /b 1
)

:: Verificar entorno virtual
if not exist "venv\Scripts\python.exe" (
    echo ⚠ Entorno virtual no encontrado
    echo Ejecutando install.bat...
    call install.bat
    if errorlevel 1 (
        echo ❌ Error en la instalación
        pause
        exit /b 1
    )
)

:: Verificar config.json
if not exist "config.json" (
    echo ⚠ Creando config.json de ejemplo...
    (
        echo {
        echo   "database": {
        echo     "host": "localhost",
        echo     "user": "root",
        echo     "password": "",
        echo     "database": "bacano_db"
        echo   },
        echo   "promotions": [
        echo     "🎊 Champagne para cumpleañeros",
        echo     "🎊 Entrada Free para cumpleañeros"
        echo   ]
        echo }
    ) > config.json
    echo ✅ config.json creado
    echo.
    echo ⚠ IMPORTANTE: Edita config.json con tus datos de base de datos
    timeout /t 3 >nul
)

:: Verificar dependencias Node
if not exist "node_backend\node_modules" (
    echo ⚠ Dependencias de Node no encontradas
    echo Instalando...
    cd node_backend
    npm install
    cd ..
)

:: Activar entorno virtual y ejecutar GUI directamente SIN nueva terminal
echo ✅ Iniciando BacanoBot en modo GUI...
echo.
echo 📌 Todo se controlará desde la ventana principal
echo 💡 Cierra la ventana para terminar el programa
echo.

:: Ejecutar directamente sin abrir nueva terminal
"venv\Scripts\python.exe" "python_backend\gui_unificado.py"

:: Cuando se cierre la GUI, terminar todo
echo.
echo =======================================
echo   👋 BacanoBot finalizado
echo =======================================
echo.
pause