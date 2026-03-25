@echo off
REM ============================================================
REM  Avvia il server SyncAPI - Safety Test Manager
REM  (Versione EXE compilata - non richiede Python)
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo   Safety Test Sync API - Avvio Server
echo ============================================================

REM Controlla che .env esista
if not exist ".env" (
    echo ERRORE: File .env non trovato!
    echo Copia .env.example in .env e configuralo con i parametri corretti.
    pause
    exit /b 1
)

REM Controlla che l'exe esista
if not exist "SyncAPI_Server\SyncAPI_Server.exe" (
    echo ERRORE: SyncAPI_Server.exe non trovato nella cartella SyncAPI_Server\
    echo Assicurati di aver copiato la build compilata.
    pause
    exit /b 1
)

echo Avvio SyncAPI_Server.exe ...
echo Premi Ctrl+C per fermare il server.
echo.

REM Avvia l'exe dalla directory corrente (dove c'e' il .env)
SyncAPI_Server\SyncAPI_Server.exe

pause
