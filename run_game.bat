@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3.14 -m venv .venv
    if errorlevel 1 (
        echo No se pudo crear el entorno Python. Instala Python 3.14 y vuelve a intentarlo.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import ursina, gltf, simplepbr" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo No se pudieron instalar las dependencias del juego.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" "juego_guerrero.py" %*
if errorlevel 1 pause


