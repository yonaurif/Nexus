@echo off
rem NEXUS: arranca todo (Docker -> base de datos -> migraciones -> interfaz -> servidor) y abre el navegador.
rem Uso: doble clic, o "iniciar_nexus.bat 8000" para elegir el puerto. Parar: Ctrl+C en esta ventana.
setlocal
cd /d "%~dp0"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"
set "URL=http://127.0.0.1:%PORT%"
title NEXUS - %URL%

if not exist ".env" (
    echo [X] Falta el archivo .env en %CD% ^(NEXUS_DB_PASSWORD, NEXUS_API_TOKEN...^).
    goto :fail
)
if not exist "backend\.venv\Scripts\uvicorn.exe" (
    echo [X] Falta el entorno de Python en backend\.venv. Ver "Arranque local" en plan.md.
    goto :fail
)

rem --- 1. Docker ---
docker info >nul 2>&1
if errorlevel 1 (
    echo [..] Docker no esta en marcha: abriendo Docker Desktop...
    if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
        start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    ) else (
        echo [X] No encuentro Docker Desktop. Arrancalo a mano y vuelve a ejecutar este archivo.
        goto :fail
    )
    for /l %%i in (1,1,90) do (
        docker info >nul 2>&1 && goto :docker_ok
        timeout /t 2 /nobreak >nul
    )
    echo [X] Docker no respondio en 3 minutos.
    goto :fail
)
:docker_ok
echo [ok] Docker

rem --- 2. Base de datos ---
docker compose up -d db
if errorlevel 1 goto :fail
for /l %%i in (1,1,60) do (
    docker compose exec -T db pg_isready -U nexus -d nexus >nul 2>&1 && goto :db_ok
    timeout /t 1 /nobreak >nul
)
echo [X] PostgreSQL no acepta conexiones.
goto :fail
:db_ok
echo [ok] PostgreSQL

rem --- 3. Migraciones ---
pushd backend
.venv\Scripts\alembic.exe upgrade head
if errorlevel 1 ( popd & goto :fail )
popd
echo [ok] Migraciones

rem --- 4. Interfaz (solo si no esta compilada) ---
if not exist "frontend\dist\index.html" (
    where npm >nul 2>&1
    if errorlevel 1 (
        echo [!] Sin Node/npm: la interfaz no esta compilada, solo funcionara la API.
    ) else (
        echo [..] Compilando la interfaz...
        pushd frontend
        if not exist node_modules call npm install
        call npm run build
        popd
    )
)

rem --- 5. Servidor ---
netstat -ano | findstr /r /c:"127.0.0.1:%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo [!] El puerto %PORT% ya esta en uso: NEXUS ya esta abierto o hay otro programa. Abriendo %URL%
    start "" "%URL%"
    goto :end
)
rem Abre el navegador cuando el servidor responda (cargar el modelo en la GPU tarda un poco).
if not defined NEXUS_NO_BROWSER start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 180;$i++){try{Invoke-WebRequest -UseBasicParsing '%URL%/' -TimeoutSec 2 | Out-Null; Start-Process '%URL%'; break}catch{Start-Sleep 1}}"
echo [..] Arrancando NEXUS en %URL%  (Ctrl+C para parar)
cd backend
.venv\Scripts\uvicorn.exe nexus.api.app:app --host 127.0.0.1 --port %PORT%
goto :end

:fail
echo.
echo NEXUS no se ha iniciado.
pause
exit /b 1

:end
endlocal
