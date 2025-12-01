@echo off
title Instalación BacanoBot
color 0B

echo ===========================================
echo      🚀 Instalando BacanoBot
echo ===========================================
echo.

:: ================================
:: NODE (carpeta node_backend)
:: ================================
echo ➤ Instalando dependencias Node...
cd node_backend
call npm install

echo ➤ Instalando Baileys v7...
call npm install @whiskeysockets/baileys@latest

cd ..

echo -------------------------------------------

:: ================================
:: PYTHON (venv global)
:: ================================
if exist venv (
    echo ✔ Entorno virtual ya existe
) else (
    echo ➤ Creando entorno virtual Python...
    python -m venv venv
)

echo ➤ Activando entorno virtual...
call venv\Scripts\activate

echo ➤ Instalando requirements...
pip install -r python_backend\requirements.txt

echo -------------------------------------------

echo.
echo ===========================================
echo     ✔ Instalación completa
echo ===========================================
pause
