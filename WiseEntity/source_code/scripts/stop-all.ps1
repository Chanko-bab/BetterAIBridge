# BetterAIBridge - stop core and asr (this install only). ASCII only.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # WiseEntity
$Install = Split-Path -Parent $Root
$corePort = 40740
$asrPort = 40715
$info = Join-Path $Install 'config\install.json'
if (Test-Path -LiteralPath $info) {
  try {
    $doc = Get-Content -LiteralPath $info -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($doc.core) { $corePort = [int]$doc.core }
    if ($doc.asr) { $asrPort = [int]$doc.asr }
  } catch { }
}
function Under-Install([string]$path) {
  if (-not $path) { return $false }
  return $path.StartsWith($Install, [System.StringComparison]::OrdinalIgnoreCase)
}
$targets = @{}
foreach ($port in @($corePort, $asrPort)) {
  try {
    foreach ($c in (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop)) {
      $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
      if ($proc -and (Under-Install $proc.Path)) { $targets[[int]$proc.Id] = $true }
    }
  } catch { }
}
try {
  $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
  foreach ($p in $procs) {
    $exe = [string]$p.ExecutablePath
    if ((Under-Install $exe) -and
        ($exe -match '\\entity\\.venv\\Scripts\\python\.exe$' -or
         $exe -match '\\asr\\.venv\\Scripts\\python\.exe$')) {
      $targets[[int]$p.ProcessId] = $true
    }
  }
} catch { }
foreach ($procId in ($targets.Keys | Sort-Object)) {
  if ($procId -and $procId -ne $PID) {
    Write-Host ("kill {0}" -f $procId)
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  }
}
