param(
    [Parameter(Mandatory=$true)][string]$AvatarPath,
    [Parameter(Mandatory=$true)][string]$CameraPath,
    [string]$BaseUrl = 'http://127.0.0.1:8095',
    [string]$ServiceKey = $env:FACE_SERVICE_KEY
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ServiceKey)) {
    throw 'Set FACE_SERVICE_KEY in this PowerShell session, matching the AI service.'
}
$headers = @{ 'X-Face-Service-Key' = $ServiceKey }
function Read-ImageBase64([string]$ImagePath) {
    $resolved = (Resolve-Path -LiteralPath $ImagePath).ProviderPath
    return [Convert]::ToBase64String([IO.File]::ReadAllBytes($resolved))
}
$enrollment = Invoke-RestMethod -Uri "$BaseUrl/v1/face/enroll" -Method Post -Headers $headers `
    -ContentType 'application/json' -TimeoutSec 30 `
    -Body (@{image=(Read-ImageBase64 $AvatarPath)} | ConvertTo-Json -Compress)
$enrollment | Select-Object accepted, reason, quality | ConvertTo-Json -Depth 5
if (-not $enrollment.accepted) {
    throw "Avatar rejected: $($enrollment.reason), $($enrollment.quality.issue)"
}
$body = @{
    image = Read-ImageBase64 $CameraPath
    template = @($enrollment.template)
    modelVersion = $enrollment.modelVersion
} | ConvertTo-Json -Depth 5 -Compress
$result = Invoke-RestMethod -Uri "$BaseUrl/v1/face/verify" -Method Post -Headers $headers `
    -ContentType 'application/json' -TimeoutSec 30 -Body $body
$result | ConvertTo-Json -Depth 5
