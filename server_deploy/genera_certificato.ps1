# ============================================================
#  Genera un certificato SSL self-signed per SyncAPI Server
#  Eseguire sul SERVER come Amministratore
# ============================================================
#
# Questo script crea:
#   ssl\server.key  - chiave privata
#   ssl\server.crt  - certificato server (usato anche come CA)
#
# Il file server.crt va poi copiato su ogni PC client.

param(
    [string]$IP = "",
    [int]$ValidYears = 10
)

# Chiedi l'IP se non fornito
if (-not $IP) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  Generatore Certificato SSL per SyncAPI Server" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    
    # Mostra gli IP disponibili
    Write-Host "IP disponibili su questa macchina:" -ForegroundColor Yellow
    Get-NetIPAddress -AddressFamily IPv4 | 
        Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.PrefixOrigin -ne "WellKnown" } | 
        ForEach-Object { Write-Host "  - $($_.IPAddress)" -ForegroundColor Green }
    Write-Host ""
    
    $IP = Read-Host "Inserisci l'IP PUBBLICO del server (es. 203.0.113.50)"
    if (-not $IP) {
        Write-Host "ERRORE: Devi specificare un IP!" -ForegroundColor Red
        exit 1
    }
}

$SSLDir = Join-Path $PSScriptRoot "ssl"
$KeyFile = Join-Path $SSLDir "server.key"
$CertFile = Join-Path $SSLDir "server.crt"
$ConfigFile = Join-Path $SSLDir "_openssl.cnf"

# Crea cartella ssl
if (-not (Test-Path $SSLDir)) {
    New-Item -ItemType Directory -Path $SSLDir -Force | Out-Null
}

# Cerca OpenSSL
$opensslPath = $null

# 1. Cerca nel PATH
$opensslPath = Get-Command openssl -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source

# 2. Cerca in Git for Windows (molto comune su Windows)
if (-not $opensslPath) {
    $gitPaths = @(
        "C:\Program Files\Git\usr\bin\openssl.exe",
        "C:\Program Files (x86)\Git\usr\bin\openssl.exe"
    )
    foreach ($p in $gitPaths) {
        if (Test-Path $p) {
            $opensslPath = $p
            break
        }
    }
}

# 3. Se non trovato, usa il metodo PowerShell nativo
if (-not $opensslPath) {
    Write-Host ""
    Write-Host "OpenSSL non trovato. Uso il metodo PowerShell nativo..." -ForegroundColor Yellow
    Write-Host ""
    
    # Genera con PowerShell nativo (New-SelfSignedCertificate)
    $cert = New-SelfSignedCertificate `
        -DnsName "SyncAPI Server" `
        -TextExtension @("2.5.29.17={text}IP Address=$IP") `
        -CertStoreLocation "Cert:\LocalMachine\My" `
        -NotAfter (Get-Date).AddYears($ValidYears) `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -FriendlyName "SyncAPI Server SSL"
    
    # Esporta il certificato (con chiave privata) in PFX
    $pfxFile = Join-Path $SSLDir "server.pfx"
    $password = ConvertTo-SecureString -String "syncapi_temp_export" -Force -AsPlainText
    Export-PfxCertificate -Cert $cert -FilePath $pfxFile -Password $password | Out-Null
    
    # Esporta solo il certificato pubblico (per i client)
    Export-Certificate -Cert $cert -FilePath $CertFile -Type CERT | Out-Null
    
    # Rimuovi dal cert store (non serve piu')
    Remove-Item "Cert:\LocalMachine\My\$($cert.Thumbprint)" -Force
    
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  CERTIFICATO GENERATO (metodo PowerShell/PFX)" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  PFX (server):      $pfxFile" -ForegroundColor White
    Write-Host "  Certificato (client): $CertFile" -ForegroundColor White
    Write-Host "  Valido per:         $ValidYears anni" -ForegroundColor White
    Write-Host "  IP:                 $IP" -ForegroundColor White
    Write-Host ""
    Write-Host "  NOTA: Il formato PFX richiede una configurazione diversa." -ForegroundColor Yellow
    Write-Host "  Si consiglia di installare Git for Windows per ottenere OpenSSL" -ForegroundColor Yellow
    Write-Host "  e rieseguire questo script per file .key/.crt standard." -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

Write-Host ""
Write-Host "Uso OpenSSL: $opensslPath" -ForegroundColor Green
Write-Host "IP server: $IP" -ForegroundColor Green
Write-Host "Validita': $ValidYears anni" -ForegroundColor Green
Write-Host ""

# Crea il file di configurazione OpenSSL con SAN (Subject Alternative Name)
$opensslConfig = @"
[req]
default_bits = 2048
prompt = no
default_md = sha256
x509_extensions = v3_req
distinguished_name = dn

[dn]
C = IT
ST = Italia
L = Sede
O = Safety Test Manager
OU = SyncAPI
CN = SyncAPI Server

[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:TRUE
keyUsage = digitalSignature, keyEncipherment, keyCertSign
extendedKeyUsage = serverAuth

[alt_names]
IP.1 = $IP
IP.2 = 127.0.0.1
DNS.1 = localhost
"@

Set-Content -Path $ConfigFile -Value $opensslConfig -Encoding ASCII

# Genera chiave privata + certificato self-signed
Write-Host "Generazione certificato..." -ForegroundColor Yellow

& $opensslPath req -x509 -nodes -days ($ValidYears * 365) `
    -newkey rsa:2048 `
    -keyout $KeyFile `
    -out $CertFile `
    -config $ConfigFile 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRORE nella generazione del certificato!" -ForegroundColor Red
    exit 1
}

# Rimuovi il file di config temporaneo
Remove-Item $ConfigFile -Force -ErrorAction SilentlyContinue

# Verifica
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  CERTIFICATO SSL GENERATO CON SUCCESSO" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  File generati:" -ForegroundColor White
Write-Host "    Chiave privata: $KeyFile" -ForegroundColor White
Write-Host "    Certificato:    $CertFile" -ForegroundColor White
Write-Host "    Validita':      $ValidYears anni" -ForegroundColor White
Write-Host "    IP incluso:     $IP" -ForegroundColor White
Write-Host ""
Write-Host "  PROSSIMI PASSI:" -ForegroundColor Yellow
Write-Host "    1. Il .env e' gia' configurato per cercare ssl\server.crt e ssl\server.key" -ForegroundColor White
Write-Host "    2. Riavvia il servizio NSSM:  nssm restart SyncAPI" -ForegroundColor White
Write-Host "    3. Copia server.crt su ogni PC client nella cartella del programma" -ForegroundColor White
Write-Host "    4. Sui client, modifica config.ini:" -ForegroundColor White
Write-Host "         [server]" -ForegroundColor Cyan
Write-Host "         url = https://${IP}:8000" -ForegroundColor Cyan
Write-Host "         ssl_ca_cert = server.crt" -ForegroundColor Cyan
Write-Host ""
