[CmdletBinding()]
param(
    [string]$OutputDirectory
)
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
    $OutputDirectory = Join-Path $scriptDirectory "..\deploy\seaweedfs\certs"
}

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
    if ($Name -eq "seaweedfs") {
        $caDirectory = Join-Path $directory "CAs"
        $null = New-Item -ItemType Directory -Force -Path $caDirectory
        Copy-Item $caCert (Join-Path $caDirectory "ca.crt") -Force
    }
}

# "localhost" lets the natively-run dev backend (dev.ps1) verify the published S3 proxy.
New-LocalCertificate "seaweedfs" @("seaweedfs", "localhost") "serverAuth"
New-LocalCertificate "gateway" @("gateway") "serverAuth,clientAuth"
New-LocalCertificate "file-authorization" @("file-authorization") "serverAuth"
New-LocalCertificate "proxy" @("proxy", "frontend") "serverAuth"

Write-Host "Generated a local CA and TLS certificates for SeaweedFS, gateway, file-authorization, proxy, and frontend."
Write-Host "Private keys are local development credentials; do not share them."

$secretsDirectory = Join-Path (Split-Path $OutputDirectory -Parent) "secrets"
$configPath = Join-Path $secretsDirectory "s3.json"
$initializerEnv = Join-Path $secretsDirectory "initializer.env"
$apiEnv = Join-Path $secretsDirectory "api.env"
$gatewayEnv = Join-Path $secretsDirectory "gateway.env"
$maintenanceEnv = Join-Path $secretsDirectory "maintenance.env"
$encryptionEnv = Join-Path $secretsDirectory "encryption.env"
$secretPaths = @($configPath, $initializerEnv, $apiEnv, $gatewayEnv, $maintenanceEnv, $encryptionEnv)
$existing = @($secretPaths | Where-Object { Test-Path $_ })
if ($existing.Count -gt 0 -and $existing.Count -lt $secretPaths.Count) {
    throw "SeaweedFS secret files are only partially present. Preserve them and restore the missing files from the operator backup before continuing."
}
if ($existing.Count -eq 0) {
    $null = New-Item -ItemType Directory -Force -Path $secretsDirectory
    function New-Secret([int]$ByteCount = 36) {
        $bytes = New-Object byte[] $ByteCount
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $rng.Dispose()
        [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', 'a').Replace('/', 'b')
    }
    function New-SecretHex([int]$ByteCount = 32) {
        $bytes = New-Object byte[] $ByteCount
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $rng.Dispose()
        -join ($bytes | ForEach-Object { $_.ToString('x2') })
    }
    $bucket = "justice-files"
    $prefixes = @("soldier_exemption", "exemption_request", "gimelim", "bug_report_screenshot", "bug_report_comment", "import_workbook", "bug_report_json_mirror")
    $objectResources = @($prefixes | ForEach-Object { "arn:aws:s3:::$bucket/$_/*" })
    $listPrefixes = @($prefixes | ForEach-Object { "$($_)/*" })
    $adminKey = "bootstrap-$([guid]::NewGuid().ToString('N').Substring(0, 16))"
    $adminSecret = New-Secret
    $apiKey = "api-$([guid]::NewGuid().ToString('N').Substring(0, 16))"
    $apiSecret = New-Secret
    $gatewayKey = "gateway-$([guid]::NewGuid().ToString('N').Substring(0, 13))"
    $gatewaySecret = New-Secret
    $maintenanceKey = "maint-$([guid]::NewGuid().ToString('N').Substring(0, 14))"
    $maintenanceSecret = New-Secret
    $kek = New-SecretHex 32
    $kekPassphrase = New-Secret
    $apiPolicy = @{
        Version = "2012-10-17"
        Statement = @(@{ Effect = "Allow"; Action = @("s3:GetObject", "s3:PutObject"); Resource = $objectResources })
    } | ConvertTo-Json -Depth 12 -Compress
    $gatewayPolicy = @{
        Version = "2012-10-17"
        Statement = @(@{ Effect = "Allow"; Action = @("s3:GetObject"); Resource = $objectResources })
    } | ConvertTo-Json -Depth 12 -Compress
    $maintenancePolicy = @{
        Version = "2012-10-17"
        Statement = @(
            @{ Effect = "Allow"; Action = @("s3:ListBucket"); Resource = @("arn:aws:s3:::$bucket"); Condition = @{ StringLike = @{ "s3:prefix" = $listPrefixes } } },
            @{ Effect = "Allow"; Action = @("s3:GetObject", "s3:PutObject", "s3:DeleteObject"); Resource = $objectResources }
        )
    } | ConvertTo-Json -Depth 12 -Compress
    $config = @{
        identities = @(
            @{ name = "bootstrap"; credentials = @(@{ accessKey = $adminKey; secretKey = $adminSecret }); actions = @("Admin") },
            @{ name = "justice-api"; credentials = @(@{ accessKey = $apiKey; secretKey = $apiSecret }); policyNames = @("justice-api") },
            @{ name = "justice-gateway"; credentials = @(@{ accessKey = $gatewayKey; secretKey = $gatewaySecret }); policyNames = @("justice-gateway") },
            @{ name = "justice-maintenance"; credentials = @(@{ accessKey = $maintenanceKey; secretKey = $maintenanceSecret }); policyNames = @("justice-maintenance") }
        )
        policies = @(
            @{ name = "justice-api"; content = $apiPolicy },
            @{ name = "justice-gateway"; content = $gatewayPolicy },
            @{ name = "justice-maintenance"; content = $maintenancePolicy }
        )
    }
    $configJson = $config | ConvertTo-Json -Depth 20
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($configPath, $configJson + [Environment]::NewLine, $utf8NoBom)
    @("STORAGE_BUCKET=$bucket", "STORAGE_REGION=us-east-1", "STORAGE_ENDPOINT_URL=https://seaweedfs:9443", "STORAGE_PATH_STYLE=true", "STORAGE_BOOTSTRAP_ACCESS_KEY_ID=$adminKey", "STORAGE_BOOTSTRAP_SECRET_ACCESS_KEY=$adminSecret") | Set-Content -Path $initializerEnv -Encoding ascii
    @("STORAGE_ACCESS_KEY_ID=$apiKey", "STORAGE_SECRET_ACCESS_KEY=$apiSecret", "STORAGE_SSE_ALGORITHM=AES256") | Set-Content -Path $apiEnv -Encoding ascii
    @("STORAGE_GATEWAY_ACCESS_KEY_ID=$gatewayKey", "STORAGE_GATEWAY_SECRET_ACCESS_KEY=$gatewaySecret", "STORAGE_ACCESS_KEY_ID=$gatewayKey", "STORAGE_SECRET_ACCESS_KEY=$gatewaySecret") | Set-Content -Path $gatewayEnv -Encoding ascii
    @("STORAGE_MAINTENANCE_ACCESS_KEY_ID=$maintenanceKey", "STORAGE_MAINTENANCE_SECRET_ACCESS_KEY=$maintenanceSecret") | Set-Content -Path $maintenanceEnv -Encoding ascii
    @("WEED_S3_SSE_KEK=$kek", "WEED_S3_SSE_KEK_PASSPHRASE=$kekPassphrase") | Set-Content -Path $encryptionEnv -Encoding ascii
}
Write-Host "Generated ignored local SeaweedFS identities and SSE-S3 key under deploy/seaweedfs/secrets/."
Write-Host "Private keys and storage credentials are local development secrets; preserve them across restarts."
