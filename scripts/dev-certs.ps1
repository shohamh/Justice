[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "..\deploy\minio\certs")
)

$ErrorActionPreference = "Stop"
$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $openssl) {
    $gitOpenSsl = Join-Path ${env:ProgramFiles} "Git\usr\bin\openssl.exe"
    if (Test-Path $gitOpenSsl) { $openssl = Get-Command $gitOpenSsl }
    else { throw "OpenSSL is required. Install Git for Windows or OpenSSL and ensure openssl.exe is on PATH." }
}

$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$null = New-Item -ItemType Directory -Force -Path $OutputDirectory
$caKey = Join-Path $OutputDirectory "ca.key"
$caCert = Join-Path $OutputDirectory "ca.crt"
if (-not (Test-Path $caKey) -or -not (Test-Path $caCert)) {
    & $openssl.Source req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 `
        -keyout $caKey -out $caCert -subj "/CN=Justice Local Development CA" `
        -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
    if ($LASTEXITCODE -ne 0) { throw "OpenSSL failed to create the local CA." }
}

function New-LocalCertificate([string]$Name, [string[]]$DnsNames, [string]$ExtendedKeyUsage) {
    $directory = Join-Path $OutputDirectory $Name
    $null = New-Item -ItemType Directory -Force -Path $directory
    $key = Join-Path $directory "private.key"
    $csr = Join-Path $directory "request.csr"
    $cert = Join-Path $directory "public.crt"
    if ((Test-Path $cert) -and (Test-Path $key)) { return }
    $ext = Join-Path $directory "extensions.cnf"
    $san = ($DnsNames | ForEach-Object -Begin { $i = 0 } -Process { $i++; "DNS.$i = $_" }) -join "`n"
    @"
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=$ExtendedKeyUsage
subjectAltName=@alt_names
[alt_names]
$san
"@ | Set-Content -Path $ext -Encoding ascii
    & $openssl.Source req -new -newkey rsa:2048 -sha256 -nodes -keyout $key `
        -out $csr -subj "/CN=$($DnsNames[0])"
    if ($LASTEXITCODE -ne 0) { throw "OpenSSL failed to create the $Name private key and CSR." }
    & $openssl.Source x509 -req -sha256 -days 825 -in $csr -CA $caCert -CAkey $caKey `
        -CAcreateserial -out $cert -extfile $ext
    if ($LASTEXITCODE -ne 0) { throw "OpenSSL failed to sign the $Name certificate." }
    Remove-Item -Force $csr, $ext
    if ($Name -eq "minio") {
        $caDirectory = Join-Path $directory "CAs"
        $null = New-Item -ItemType Directory -Force -Path $caDirectory
        Copy-Item $caCert (Join-Path $caDirectory "ca.crt") -Force
    }
}

New-LocalCertificate "minio" @("minio") "serverAuth"
New-LocalCertificate "gateway" @("gateway") "serverAuth,clientAuth"
New-LocalCertificate "file-authorization" @("file-authorization") "serverAuth"
New-LocalCertificate "proxy" @("proxy", "frontend") "serverAuth"

Write-Host "Generated a local CA and TLS certificates for minio, gateway, file-authorization, proxy, and frontend."
Write-Host "Private keys are local development credentials; do not share them."

$secretsDirectory = Join-Path (Split-Path $OutputDirectory -Parent) "secrets"
$initializerEnv = Join-Path $secretsDirectory "initializer.env"
$apiEnv = Join-Path $secretsDirectory "api.env"
$gatewayEnv = Join-Path $secretsDirectory "gateway.env"
$maintenanceEnv = Join-Path $secretsDirectory "maintenance.env"
if (-not (Test-Path $initializerEnv) -or -not (Test-Path $apiEnv) -or
    -not (Test-Path $gatewayEnv) -or -not (Test-Path $maintenanceEnv)) {
    $null = New-Item -ItemType Directory -Force -Path $secretsDirectory
    function New-Secret([int]$ByteCount = 36) {
        $bytes = New-Object byte[] $ByteCount
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $rng.Dispose()
        [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', 'a').Replace('/', 'b')
    }
    $rootUser = "root-$(New-Secret 9)"
    $rootPassword = New-Secret 36
    $apiKey = "api-$([guid]::NewGuid().ToString('N').Substring(0, 16))"
    $apiPassword = New-Secret 36
    $gatewayKey = "gw-$([guid]::NewGuid().ToString('N').Substring(0, 17))"
    $gatewayPassword = New-Secret 36
    $maintenanceKey = "maint-$([guid]::NewGuid().ToString('N').Substring(0, 14))"
    $maintenancePassword = New-Secret 36
    @("MINIO_ROOT_USER=$rootUser", "MINIO_ROOT_PASSWORD=$rootPassword", "MINIO_BUCKET=justice-files",
      "API_ACCESS_KEY=$apiKey", "API_SECRET_KEY=$apiPassword", "GATEWAY_ACCESS_KEY=$gatewayKey",
      "GATEWAY_SECRET_KEY=$gatewayPassword", "MAINTENANCE_ACCESS_KEY=$maintenanceKey",
      "MAINTENANCE_SECRET_KEY=$maintenancePassword") | Set-Content -Path $initializerEnv -Encoding ascii
    @("STORAGE_ACCESS_KEY_ID=$apiKey", "STORAGE_SECRET_ACCESS_KEY=$apiPassword") |
        Set-Content -Path $apiEnv -Encoding ascii
    @("STORAGE_GATEWAY_ACCESS_KEY_ID=$gatewayKey", "STORAGE_GATEWAY_SECRET_ACCESS_KEY=$gatewayPassword") |
        Set-Content -Path $gatewayEnv -Encoding ascii
    @("STORAGE_MAINTENANCE_ACCESS_KEY_ID=$maintenanceKey", "STORAGE_MAINTENANCE_SECRET_ACCESS_KEY=$maintenancePassword") |
        Set-Content -Path $maintenanceEnv -Encoding ascii
}

Write-Host "Generated ignored local MinIO credentials under deploy/minio/secrets/."
