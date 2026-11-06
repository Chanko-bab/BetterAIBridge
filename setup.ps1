# BetterAIBridge - one-shot setup (creates the three venvs). ASCII only.
# Behavior: tries several PyPI mirrors, checks every exit code, verifies imports,
# and exits non-zero with a clear message if anything fails. No false "done".
param([switch]$SkipAsr, [string[]]$Index = @())

$ErrorActionPreference = 'Stop'
$D = Split-Path -Parent $MyInvocation.MyCommand.Path
$W = Join-Path $D 'WiseEntity'

if (-not $Index -or $Index.Count -eq 0) {
    $Index = @(
        'https://mirrors.aliyun.com/pypi/simple/',
        'https://pypi.org/simple',
        'https://pypi.tuna.tsinghua.edu.cn/simple'
    )
}

function Fail([string]$msg) {
    Write-Host ''
    Write-Host "[setup] FAILED: $msg" -ForegroundColor Red
    Write-Host '[setup] fix the cause above, then run setup.cmd again.'
    exit 1
}

function Invoke-Pip([string]$py, [string[]]$pipArgs) {
    foreach ($idx in $Index) {
        Write-Host "[setup] pip -i $idx"
        & $py -m pip @pipArgs -i $idx --timeout 15 --retries 1
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "[setup] mirror failed (exit $LASTEXITCODE): $idx" -ForegroundColor Yellow
    }
    Fail "pip could not install ($($pipArgs -join ' ')) from any mirror."
}

function Ensure([string]$venv, [string]$req, [string]$label, [string]$importCheck) {
    $py = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $py)) {
        Write-Host "[setup] creating $label venv -> $venv"
        & python -m venv $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) { Fail "cannot create venv: $venv" }
    }
    if (-not (Test-Path $req)) { Fail "requirements file missing: $req" }
    Write-Host "[setup] upgrading pip ($label)"
    Invoke-Pip $py @('install', '--upgrade', 'pip', '-q')
    Write-Host "[setup] installing $label dependencies"
    Invoke-Pip $py @('install', '-r', $req)
    Write-Host "[setup] verifying $label"
    & $py -c $importCheck
    if ($LASTEXITCODE -ne 0) { Fail "$label post-install check failed: $importCheck" }
    Write-Host "[setup] $label OK"
}

function Add-PythonToPath([string]$dir) {
    if ($dir -and (Test-Path (Join-Path $dir 'python.exe'))) {
        $env:Path = "$dir;$env:Path"
        return $true
    }
    return $false
}

function Get-PythonVersionOk([string]$exe) {
    try {
        & $exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

$pyOk = $false
if (Get-Command python -ErrorAction SilentlyContinue) {
    if (Get-PythonVersionOk 'python') { $pyOk = $true }
}

if (-not $pyOk) {
    # 常见安装位置先找一遍（有的机器装了但没进 PATH）
    $guess = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310'),
        'C:\Python312', 'C:\Python311', 'C:\Python310'
    )
    foreach ($g in $guess) {
        if (Add-PythonToPath $g) {
            if (Get-PythonVersionOk (Join-Path $g 'python.exe')) { $pyOk = $true; Write-Host "[setup] found python at $g"; break }
        }
    }
}

if (-not $pyOk) {
    Write-Host '[setup] python not found, downloading Python 3.12 (per-user, no admin needed)...' -ForegroundColor Yellow
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $tmp = Join-Path $env:TEMP 'bab-python-3.12.8-amd64.exe'
    $urls = @(
        'https://mirrors.huaweicloud.com/python/3.12.8/python-3.12.8-amd64.exe',
        'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe'
    )
    $got = $false
    foreach ($u in $urls) {
        try {
            Write-Host "[setup] downloading $u"
            Invoke-WebRequest -Uri $u -OutFile $tmp -UseBasicParsing -TimeoutSec 300
            if ((Get-Item $tmp).Length -gt 10MB) { $got = $true; break }
        } catch {
            Write-Host "[setup] download failed: $u" -ForegroundColor Yellow
        }
    }
    if (-not $got) {
        Fail 'python not found and download failed. Install Python 3.10+ from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and re-run setup.cmd.'
    }
    Write-Host '[setup] installing Python (this can take 1-3 minutes, please wait)'
    $instArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0', 'Include_launcher=1', 'Shortcuts=0', 'AssociateFiles=0')
    $proc = Start-Process -FilePath $tmp -ArgumentList $instArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Fail "Python installer returned $($proc.ExitCode). Install Python 3.10+ manually from https://www.python.org/downloads/ and re-run setup.cmd."
    }
    # 重新从注册表拼 PATH（当前进程看不到安装器改的 PATH）
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
    $pyOk = $false
    if (Get-Command python -ErrorAction SilentlyContinue) {
        if (Get-PythonVersionOk 'python') { $pyOk = $true }
    }
    if (-not $pyOk) {
        foreach ($g in @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310')
        )) {
            if (Add-PythonToPath $g) { if (Get-PythonVersionOk (Join-Path $g 'python.exe')) { $pyOk = $true; break } }
        }
    }
    if (-not $pyOk) {
        Fail 'Python was installed but still not runnable. Close this window, open a NEW one, and run setup.cmd again.'
    }
    Write-Host '[setup] python installed and ready'
}

& python -c "import sys; print('[setup] python', sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { Fail 'python is not runnable from PATH. Reopen the window and try again.' }

Ensure (Join-Path $D '.venv') (Join-Path $D 'requirements-launcher.txt') 'launcher' 'import PySide6, yaml, httpx, psutil; print("PySide6", PySide6.__version__)'
Ensure (Join-Path $W 'entity\.venv') (Join-Path $D 'requirements-core.txt') 'core' 'import fastapi, uvicorn, numpy, pydantic, edge_tts'
if (-not $SkipAsr) {
    $asr = Join-Path $W 'capability\voice\asr'
    Ensure (Join-Path $asr '.venv') (Join-Path $D 'requirements-asr.txt') 'asr' 'import faster_whisper'
} else {
    Write-Host '[setup] skipping asr (voice) on request'
}

Write-Host ''
Write-Host '[setup] all dependencies installed and verified.'
Write-Host '[setup] next: double-click launch.vbs (or start.cmd)'
Write-Host '[setup] core listens on 40720, asr on 40715'
exit 0
