# BetterAIBridge - start core (+ asr if installed). ASCII only.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # WiseEntity
$Install = Split-Path -Parent $Root
$Scripts = Join-Path $Root 'source_code\scripts'
$Log = Join-Path $Root 'runtime\logs\autostart.log'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Log) | Out-Null
function Say($m) { $line = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m; Add-Content -Path $Log -Value $line -Encoding UTF8 }
function Listening($port) {
  try { return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop) } catch { return $false }
}
$corePort = 40740
$asrPort = 40715
$info = Join-Path $Install 'config\install.json'
if (Test-Path -LiteralPath $info) {
  try {
    $doc = Get-Content -LiteralPath $info -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($doc.core) { $corePort = [int]$doc.core }
    if ($doc.asr) { $asrPort = [int]$doc.asr }
  } catch { Say 'install.json unreadable, using defaults' }
}
Say '=== start-all begin ==='
if (-not (Listening $corePort)) {
  Say ("starting core ({0})" -f $corePort)
  Start-Process cmd.exe -ArgumentList '/c', (Join-Path $Scripts 'start-core.cmd') -WindowStyle Hidden
  for ($i = 0; $i -lt 60; $i++) { Start-Sleep -Milliseconds 500; if (Listening $corePort) { break } }
} else { Say 'core already listening' }
$asr = Join-Path $Root 'capability\voice\asr\start-asr.cmd'
if ((Test-Path $asr) -and -not (Listening $asrPort)) {
  $venv = Join-Path $Root 'capability\voice\asr\.venv\Scripts\python.exe'
  if (Test-Path $venv) {
    Say ("starting asr ({0})" -f $asrPort)
    $env:BAB_ASR_PORT = "$asrPort"
    Start-Process cmd.exe -ArgumentList '/c', $asr -WindowStyle Hidden
  } else { Say 'asr venv missing, skip' }
}
Say ("status: core={0} asr={1}" -f (Listening $corePort), (Listening $asrPort))
