# ============================================================
# DEPLOY RAPIDO SU SERVER - Safety Test Manager SyncAPI
# ============================================================
# Questo script:
# 1. Ferma il servizio NSSM "SyncAPI" sul server
# 2. Copia i file aggiornati
# 3. Riavvia il servizio
#
# USO: .\deploy_server.ps1
# ============================================================

param(
    [string]$ServerIP = "195.149.221.71",
    [string]$ServiceName = "SyncAPI",
    [string]$RemotePath = "C$\Program Files (x86)\VerificheElettriche\SyncAPI_Server"
)

$ErrorActionPreference = "Stop"
$LocalPackage = Join-Path $PSScriptRoot "server_deploy\DEPLOY_PACKAGE\SyncAPI_Server"
$RemoteUNC = "\\$ServerIP\$RemotePath"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  DEPLOY SyncAPI Server" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Server:  $ServerIP" -ForegroundColor White
Write-Host "  Da:      $LocalPackage" -ForegroundColor White
Write-Host "  A:       $RemoteUNC" -ForegroundColor White
Write-Host ""

# --- VERIFICA PACCHETTO LOCALE ---
if (-not (Test-Path "$LocalPackage\SyncAPI_Server.exe")) {
    Write-Host "ERRORE: SyncAPI_Server.exe non trovato in $LocalPackage" -ForegroundColor Red
    Write-Host "Esegui prima: pyinstaller real_server.spec --noconfirm" -ForegroundColor Yellow
    exit 1
}

# --- VERIFICA CONNESSIONE AL SERVER ---
Write-Host "[1/5] Verifico connessione al server..." -ForegroundColor Yellow
if (-not (Test-Path "\\$ServerIP\C$" -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "ERRORE: Impossibile accedere a \\$ServerIP\C$" -ForegroundColor Red
    Write-Host ""
    Write-Host "Soluzioni:" -ForegroundColor Yellow
    Write-Host "  1. Apri Esplora File e vai a: \\$ServerIP\C$" -ForegroundColor White
    Write-Host "     (inserisci le credenziali admin del server)" -ForegroundColor Gray
    Write-Host "  2. Oppure esegui:" -ForegroundColor White
    Write-Host "     net use \\$ServerIP\C$ /user:NOMESERVER\Administrator PASSWORD" -ForegroundColor Gray
    Write-Host "  3. Poi rilancia questo script" -ForegroundColor White
    Write-Host ""
    
    $cred = Read-Host "Vuoi inserire le credenziali ora? (s/n)"
    if ($cred -eq 's') {
        $username = Read-Host "Username (es: Administrator)"
        $password = Read-Host "Password" -AsSecureString
        $plainPwd = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($password))
        net use "\\$ServerIP\C$" /user:$username $plainPwd 2>&1 | Out-Null
        if (-not (Test-Path "\\$ServerIP\C$" -ErrorAction SilentlyContinue)) {
            Write-Host "Connessione fallita. Verifica credenziali e firewall." -ForegroundColor Red
            exit 1
        }
        Write-Host "  Connesso!" -ForegroundColor Green
    } else {
        exit 1
    }
}
Write-Host "  OK - Server raggiungibile" -ForegroundColor Green

# --- FERMA IL SERVIZIO ---
Write-Host "[2/5] Fermo il servizio $ServiceName..." -ForegroundColor Yellow
try {
    # Prova via sc.exe remoto
    $result = sc.exe "\\$ServerIP" stop $ServiceName 2>&1
    Write-Host "  Servizio fermato (attendo 5 secondi...)" -ForegroundColor Green
    Start-Sleep -Seconds 5
} catch {
    Write-Host "  WARN: Impossibile fermare il servizio da remoto" -ForegroundColor Yellow
    Write-Host "  Il servizio verra' fermato manualmente sul server" -ForegroundColor Yellow
}

# --- COPIA FILE ---
Write-Host "[3/5] Copio i file aggiornati..." -ForegroundColor Yellow

# Crea la cartella se non esiste
if (-not (Test-Path $RemoteUNC)) {
    New-Item -ItemType Directory -Path $RemoteUNC -Force | Out-Null
    Write-Host "  Cartella creata: $RemoteUNC" -ForegroundColor Gray
}

# Copia EXE
Write-Host "  Copio SyncAPI_Server.exe..." -ForegroundColor Gray
Copy-Item "$LocalPackage\SyncAPI_Server.exe" -Destination "$RemoteUNC\SyncAPI_Server.exe" -Force

# Copia _internal
Write-Host "  Copio _internal\ (dipendenze)..." -ForegroundColor Gray
if (Test-Path "$RemoteUNC\_internal") { Remove-Item "$RemoteUNC\_internal" -Recurse -Force }
Copy-Item "$LocalPackage\_internal" -Destination "$RemoteUNC\_internal" -Recurse

# Copia SSL (solo se non esiste gia' o se e' aggiornato)
Write-Host "  Copio certificati SSL..." -ForegroundColor Gray
if (-not (Test-Path "$RemoteUNC\ssl")) { New-Item -ItemType Directory -Path "$RemoteUNC\ssl" -Force | Out-Null }
Copy-Item "$LocalPackage\ssl\server.crt" -Destination "$RemoteUNC\ssl\server.crt" -Force
Copy-Item "$LocalPackage\ssl\server.key" -Destination "$RemoteUNC\ssl\server.key" -Force

# Copia .env (solo se non esiste - NON sovrascrivere la config di produzione!)
if (-not (Test-Path "$RemoteUNC\.env")) {
    Write-Host "  Copio .env (prima installazione)..." -ForegroundColor Gray
    Copy-Item "$LocalPackage\.env" -Destination "$RemoteUNC\.env" -Force
} else {
    Write-Host "  .env gia' presente - NON sovrascritto (ok)" -ForegroundColor Gray
}

# Copia start_server.bat
Copy-Item "$LocalPackage\start_server.bat" -Destination "$RemoteUNC\start_server.bat" -Force

Write-Host "  Copia completata!" -ForegroundColor Green

# --- RIAVVIA IL SERVIZIO ---
Write-Host "[4/5] Riavvio il servizio $ServiceName..." -ForegroundColor Yellow
try {
    $result = sc.exe "\\$ServerIP" start $ServiceName 2>&1
    Start-Sleep -Seconds 3
    Write-Host "  Servizio riavviato!" -ForegroundColor Green
} catch {
    Write-Host "  WARN: Impossibile riavviare da remoto - riavvia manualmente" -ForegroundColor Yellow
}

# --- VERIFICA ---
Write-Host "[5/5] Verifico che il server risponda..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
try {
    $certPath = Join-Path $PSScriptRoot "ssl\server.crt"
    # Ignora errori SSL per il quick check
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    $response = Invoke-WebRequest -Uri "https://${ServerIP}:8000/" -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        Write-Host "  Server ONLINE e funzionante!" -ForegroundColor Green
    } else {
        Write-Host "  Server risponde con status $($response.StatusCode)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  WARN: Server non risponde ancora - potrebbe aver bisogno di piu' tempo" -ForegroundColor Yellow
    Write-Host "  Verifica manualmente: https://${ServerIP}:8000/" -ForegroundColor Gray
} finally {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $null
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  DEPLOY COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
