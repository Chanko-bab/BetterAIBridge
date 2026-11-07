param(

    [string]$Target = '',

    [switch]$NoDeps,

    [switch]$NoLaunch

)



# BetterAIBridge installer 0.1.2

# 单窗口：解压 + 可选装依赖 + 可选快捷方式；进度百分比在窗口里；装完自动关。

# 静默测试模式：设置环境变量 BAB_TEST_DIR=<dir>，不做 UI，只解压并生成 app.yaml。



$ErrorActionPreference = 'Stop'

# Force a taskbar button for the form. When this script is started with a hidden

# window style the shell does not register our window, so a minimized installer

# cannot be brought back by clicking its taskbar slot.

Add-Type -TypeDefinition @"

using System;

using System.Runtime.InteropServices;

[ComImport, Guid("56FDF344-FD6D-11d0-958A-006097C9A090")]

public class CTaskbarList { }

[ComImport, Guid("56FDF342-FD6D-11d0-958A-006097C9A090"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]

public interface ITaskbarList {

    void HrInit();

    void AddTab(IntPtr hwnd);

    void DeleteTab(IntPtr hwnd);

    void ActivateTab(IntPtr hwnd);

    void SetActiveAlt(IntPtr hwnd);

}

public static class BabTaskbar {

    public static void Add(IntPtr h) {

        ITaskbarList t = (ITaskbarList)new CTaskbarList();

        t.HrInit();

        t.AddTab(h);

    }

    public static void Activate(IntPtr h) {

        ITaskbarList t = (ITaskbarList)new CTaskbarList();

        t.HrInit();

        t.ActivateTab(h);

    }

}

"@





$Version = '0.5.8'

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

$VerFile = Join-Path $Here 'version.txt'
if (Test-Path $VerFile) {
    $rawVer = (Get-Content $VerFile -Raw -Encoding ASCII).Trim()
    if ($rawVer) { $Version = $rawVer }
}

$AppName = "BetterAIBridge"

$DirName = "BetterAIBridge $Version"

$LauncherName = "BetterAIBridge"

$LauncherFile = "$LauncherName.vbs"

$Zip = Join-Path $Here 'payload.zip'

$BgFile = Join-Path $Here 'bab-bg.jpg'

$Tpl = 'config\app.yaml.template'

$Log = Join-Path $env:TEMP 'bab-install.log'

$Silent = [bool]$env:BAB_TEST_DIR

if ($Silent) { $Target = $env:BAB_TEST_DIR }

# 0.4.19 起数据回到安装目录（每个安装一份）；$DataDir 只用于读旧版 install.json 的 data_dir

$DataDir = if ($env:BAB_TEST_DATA) { $env:BAB_TEST_DATA } else { '' }



function Write-Log([string]$m) {

    try {

        $line = ('{0} {1}' -f (Get-Date -Format 'HH:mm:ss'), $m)

        [System.IO.File]::AppendAllText($Log, $line + "`r`n", (New-Object System.Text.UTF8Encoding($false)))

    } catch { }

}



function Show-BabError([string]$why) {

    try {

        Add-Type -AssemblyName System.Windows.Forms

        Add-Type -AssemblyName System.Drawing

        $f = New-Object System.Windows.Forms.Form

        $f.Text = 'BetterAIBridge 安装程序'

        $f.ClientSize = New-Object System.Drawing.Size(480, 250)

        $f.StartPosition = 'CenterScreen'

        $f.FormBorderStyle = 'FixedSingle'

        $f.MaximizeBox = $false

        $f.MinimizeBox = $false

        $f.TopMost = $true

        $f.BackColor = [System.Drawing.Color]::White

        if (Test-Path $BgFile) {

            try {

                $f.BackgroundImage = [System.Drawing.Image]::FromFile($BgFile)

                $f.BackgroundImageLayout = [System.Windows.Forms.ImageLayout]::Stretch

            } catch { }

        }

        $lab = New-Object System.Windows.Forms.Label

        $lab.Text = ("安装没能完成：`r`n`r`n{0}`r`n`r`n日志：{1}" -f $why, $Log)

        $lab.Location = New-Object System.Drawing.Point(24, 22)

        $lab.Size = New-Object System.Drawing.Size(432, 158)

        $lab.BackColor = [System.Drawing.Color]::Transparent

        $f.Controls.Add($lab)

        $btn = New-Object System.Windows.Forms.Button

        $btn.Text = '好'

        $btn.Location = New-Object System.Drawing.Point(366, 200)

        $btn.Size = New-Object System.Drawing.Size(90, 30)

        $btn.Add_Click({ $this.FindForm().Close() })

        $f.Controls.Add($btn)

        $f.AcceptButton = $btn

        [void]$f.ShowDialog()

    } catch {

        [System.Windows.Forms.MessageBox]::Show(

            ("安装没能完成：`r`n`r`n{0}`r`n`r`n日志：{1}" -f $why, $Log),

            "BetterAIBridge 安装程序", 'OK', 'Error') | Out-Null

    }

}

function Fail([string]$why) {

    Write-Log "FAIL $why"

    if ($Silent) { Write-Host "[install] FAILED: $why"; exit 1 }

    Show-BabError $why

    exit 1

}





function Find-FreePort([int]$Start) {

    for ($p = $Start; $p -lt ($Start + 60); $p++) {

        try {

            $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)

            $l.Start(); $l.Stop(); return $p

        } catch { }

    }

    return $Start

}





function Test-InstallTarget([string]$Dir) {

    $full = [System.IO.Path]::GetFullPath($Dir).TrimEnd([char]92)

    if ($full -match '^[A-Za-z]:$') { return '不能直接装在盘根，请选一个文件夹。' }



    # LOCALAPPDATA\BetterAIBridge* 是默认安装位置，必须先于 USERPROFILE 放行

    $isLocalBab = $false

    if ($env:LOCALAPPDATA) {

        $localBab = Join-Path $env:LOCALAPPDATA 'BetterAIBridge'

        $isLocalBab = ($full -eq $localBab) -or

                      $full.StartsWith($localBab + [char]92, [StringComparison]::OrdinalIgnoreCase) -or

                      $full.StartsWith($localBab + ' ', [StringComparison]::OrdinalIgnoreCase)

    }



    $blocked = @($env:USERPROFILE, $env:WINDIR, $env:ProgramFiles, ${env:ProgramFiles(x86)},

                 $env:LOCALAPPDATA, $env:APPDATA, $env:TEMP, $env:SystemDrive)

    foreach ($b in $blocked) {

        if (-not $b) { continue }

        $bf = [System.IO.Path]::GetFullPath($b).TrimEnd([char]92)

        if ($isLocalBab -and (($b -eq $env:LOCALAPPDATA) -or ($b -eq $env:USERPROFILE))) { continue }

        if ($full -eq $bf) { return "不能装在这个目录：$b" }

        if ($bf -and $full.StartsWith($bf + [char]92)) { return "不能装在系统/用户目录里面：$b" }

    }

    if (Test-Path -LiteralPath $full) {

        $items = @(Get-ChildItem -LiteralPath $full -Force -ErrorAction SilentlyContinue)

        if ($items.Count -gt 0 -and -not (Test-Path (Join-Path $full 'config\install.json'))) {

            # 老版本（含从别处拷来的）没有 install.json，但结构就是 BAB：允许接管升级

            $looksBab = (Test-Path (Join-Path $full 'main.py')) -and

                        (Test-Path (Join-Path $full 'WiseEntity')) -and

                        (Test-Path (Join-Path $full 'VERSION.txt'))

            if (-not $looksBab) {

                return '这个文件夹不是空的，也不是 BetterAIBridge 的安装目录，换一个吧。'

            }

        }

    }

    return ''

}



function Get-LastParent {

    try {

        $v = (Get-ItemProperty -Path 'HKCU:\Software\BetterAIBridge' -Name LastInstallParent -ErrorAction Stop).LastInstallParent

        if ($v -and (Test-Path -LiteralPath $v)) { return [string]$v }

    } catch { }

    return ''

}



function Set-LastParent([string]$Dir) {

    if (-not $Dir) { return }

    try {

        if (-not (Test-Path 'HKCU:\Software\BetterAIBridge')) {

            New-Item -Path 'HKCU:\Software\BetterAIBridge' -Force | Out-Null

        }

        Set-ItemProperty -Path 'HKCU:\Software\BetterAIBridge' -Name LastInstallParent -Value $Dir

    } catch { }

}



function Merge-Missing([string]$Src, [string]$Dst) {

    # 只补对方没有的文件；已在数据目录里的版本永远不覆盖

    if (-not (Test-Path -LiteralPath $Src)) { return 0 }

    New-Item -ItemType Directory -Force -Path $Dst | Out-Null

    $count = 0

    foreach ($item in @(Get-ChildItem -LiteralPath $Src -Force -Recurse)) {

        $rel = $item.FullName.Substring($Src.TrimEnd([char]92).Length).TrimStart([char]92)

        $to = Join-Path $Dst $rel

        if ($item.PSIsContainer) {

            if (-not (Test-Path -LiteralPath $to)) { New-Item -ItemType Directory -Force -Path $to | Out-Null }

        } elseif (-not (Test-Path -LiteralPath $to)) {

            Copy-Item -LiteralPath $item.FullName -Destination $to -Force

            $count++

        }

    }

    return $count

}



function Move-DataBack([string]$Dir, [string]$From) {

    # 0.4.16–0.4.18 把数据放在 data_dir；0.4.19 起搬回安装目录，只补缺、不覆盖

    if (-not $From -or -not (Test-Path -LiteralPath $From)) { return 0 }

    $n = 0

    # persona/config 以旧数据为准（安装树里是占位模板）；其余只补缺，避免覆盖 0.4.19 后的改动

    foreach ($sub in @('persona', 'config')) {

        $src = Join-Path $From "entity\$sub"

        $dst = Join-Path $Dir "WiseEntity\entity\$sub"

        if (Test-Path -LiteralPath $src) {

            New-Item -ItemType Directory -Force -Path $dst | Out-Null

            foreach ($f in @(Get-ChildItem -LiteralPath $src -Recurse -File -ErrorAction SilentlyContinue)) {

                if ($f.Name -in @('app.yaml', 'install.json')) { continue }

                $rel = $f.FullName.Substring($src.Length).TrimStart([char]92)

                $to = Join-Path $dst $rel

                $parent = Split-Path -Parent $to

                if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }

                Copy-Item -LiteralPath $f.FullName -Destination $to -Force

                $n++

            }

        }

    }

    foreach ($sub in @('memory', 'state', 'emotion', 'registry', 'brain')) {

        $n += (Merge-Missing (Join-Path $From "entity\$sub") (Join-Path $Dir "WiseEntity\entity\$sub"))

    }

    $n += (Merge-Missing (Join-Path $From 'program_bundle') (Join-Path $Dir 'program_bundle'))

    if ($n -gt 0) { Write-Log "data moved back from $From ($n files)" }

    return $n

}



function Stop-AppUnderDir([string]$Dir) {

    # 覆盖安装前先停掉这个安装目录里的进程，避免文件被占用

    $prefix = $Dir.TrimEnd([char]92) + [char]92

    $killed = 0

    foreach ($p in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {

        $exe = [string]$p.ExecutablePath

        if ($exe -and $exe.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {

            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; $killed++ } catch { }

        }

    }

    if ($killed -gt 0) {

        Write-Log "stopped $killed process(es) under $Dir"

        Start-Sleep -Milliseconds 800

    }

}



function Copy-Except([string]$Src, [string]$Dst, [string[]]$Skip, [int]$Depth = 0) {

    New-Item -ItemType Directory -Force -Path $Dst | Out-Null

    foreach ($item in @(Get-ChildItem -LiteralPath $Src -Force)) {

        if ($Depth -eq 0 -and ($Skip -contains $item.Name)) { continue }

        if ($item.PSIsContainer) {

            Copy-Except $item.FullName (Join-Path $Dst $item.Name) @() ($Depth + 1)

        } else {

            Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $Dst $item.Name) -Force

        }

    }

}



function Copy-Payload([string]$Src, [string]$Dst) {

    # 只覆盖程序文件；entity 的数据子目录、program_bundle、logs、install.json 一律不碰

    New-Item -ItemType Directory -Force -Path $Dst | Out-Null

    $dataNames = @('config', 'persona', 'memory', 'state', 'emotion', 'registry', 'brain', '.venv')

    foreach ($item in @(Get-ChildItem -LiteralPath $Src -Force)) {

        if ($item.Name -eq 'logs') { continue }

        if ($item.Name -eq 'program_bundle') {

            Merge-Missing $item.FullName (Join-Path $Dst 'program_bundle') | Out-Null

            continue

        }

        if ($item.Name -eq 'config') {

            New-Item -ItemType Directory -Force -Path (Join-Path $Dst 'config') | Out-Null

            foreach ($f in @(Get-ChildItem -LiteralPath $item.FullName -Force -File)) {

                if ($f.Name -eq 'app.yaml' -or $f.Name -eq 'install.json') { continue }

                Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $Dst ('config\' + $f.Name)) -Force

            }

            continue

        }

        if ($item.Name -eq 'WiseEntity') {

            Copy-Except $item.FullName (Join-Path $Dst 'WiseEntity') @('entity') 0

            Copy-Except (Join-Path $item.FullName 'entity') (Join-Path $Dst 'WiseEntity\entity') $dataNames 0

            # 首次安装补上模板数据（persona/llm 等）；已有文件一律不覆盖

            foreach ($d in @('config', 'persona', 'memory', 'state', 'emotion', 'registry', 'brain')) {

                Merge-Missing (Join-Path $item.FullName "entity\$d") (Join-Path $Dst "WiseEntity\entity\$d") | Out-Null

            }

            continue

        }

        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $Dst $item.Name) -Recurse -Force

    }

}



function Read-InstallInfo([string]$Dir) {

    $p = Join-Path $Dir 'config\install.json'

    if (-not (Test-Path -LiteralPath $p)) { return [pscustomobject]@{} }

    try { return (Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json) }

    catch { return [pscustomobject]@{} }

}



function Expand-Payload([string]$Dir) {

    # 先解到临时目录校验；确认是完整 payload 再动安装目录

    $stage = Join-Path $env:TEMP ('bab-stage-' + [guid]::NewGuid().ToString('N'))

    New-Item -ItemType Directory -Force -Path $stage | Out-Null

    try {

        Expand-Archive -Path $Zip -DestinationPath $stage -Force

        if (-not (Test-Path (Join-Path $stage 'main.py')) -or

            -not (Test-Path (Join-Path $stage 'WiseEntity')) -or

            -not (Test-Path (Join-Path $stage $Tpl))) {

            throw '安装包不完整（缺 main.py / WiseEntity / app.yaml.template）'

        }

        $old = Read-InstallInfo $Dir

        if ($old.PSObject.Properties['data_dir']) {

            $from = [string]$old.data_dir

            if ($from) { Move-DataBack $Dir $from | Out-Null }

        }

        Stop-AppUnderDir $Dir

        Copy-Payload $stage $Dir

        foreach ($rel in @('main.py', 'WiseEntity', $Tpl)) {

            if (-not (Test-Path (Join-Path $Dir $rel))) { throw "安装不完整：缺 $rel" }

        }

    } finally {

        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue

    }

}



# 解压后收尾：写 app.yaml（按实际目录 + 本机空闲端口），并把端口写进启动脚本，

# 这样同一台机器上装第二份时不会跟第一份抢 40720。

function Initialize-Install([string]$Dir, [int]$Core = 0, [int]$Asr = 0, [string]$InstallId = '') {

    if ($Core -gt 0) { $core = $Core } else { $core = Find-FreePort 40720 }

    if ($Asr -gt 0) { $asr = $Asr } else { $asr = Find-FreePort 40715 }

    $tplPath = Join-Path $Dir $Tpl

    if (-not (Test-Path $tplPath)) { throw "app.yaml.template missing" }

    $yaml = (Get-Content $tplPath -Raw -Encoding UTF8)

    $yaml = $yaml.Replace('{{APP_DIR}}', $Dir.TrimEnd([char]92)).Replace('{{CORE_PORT}}', "$core").Replace('{{ASR_PORT}}', "$asr")

    [System.IO.File]::WriteAllText((Join-Path $Dir "config\app.yaml"), $yaml, (New-Object System.Text.UTF8Encoding($false)))

    foreach ($rel in @("WiseEntity\source_code\scripts\start-core.cmd", "WiseEntity\source_code\scripts\start-all.ps1", "WiseEntity\source_code\scripts\stop-all.ps1")) {

        $f = Join-Path $Dir $rel

        if (Test-Path $f) {

            $s = [System.IO.File]::ReadAllText($f)

            $s = $s.Replace("40720", "$core").Replace("40715", "$asr")

            $s = [regex]::Replace($s, 'set BAB_PORT=\d+', "set BAB_PORT=$core")

            [System.IO.File]::WriteAllText($f, $s, (New-Object System.Text.UTF8Encoding($false)))

        }

    }

    Write-Log "ports: core=$core asr=$asr"



    # 启动器按版本号命名：launch.vbs -> BetterAIBridgeLauncher <ver>.vbs

    $oldLauncher = Join-Path $Dir "launch.vbs"

    $newLauncher = Join-Path $Dir $LauncherFile

    if (Test-Path $oldLauncher) {

        try {

            if ((Split-Path -Leaf $oldLauncher) -ne $LauncherFile) {

                if (Test-Path $newLauncher) { Remove-Item -LiteralPath $newLauncher -Force }

                Move-Item -LiteralPath $oldLauncher -Destination $newLauncher -Force

            }

            Write-Log "launcher -> $LauncherFile"

        } catch { Write-Log ("launcher rename failed: " + $_.Exception.Message) }

    }

    $startCmd = Join-Path $Dir "start.cmd"

    if (Test-Path $startCmd) {

        try {

            $sc = [System.IO.File]::ReadAllText($startCmd)

            $sc = $sc.Replace("launch.vbs", $LauncherFile)

            [System.IO.File]::WriteAllText($startCmd, $sc, (New-Object System.Text.UTF8Encoding($false)))

        } catch { Write-Log ("start.cmd patch failed: " + $_.Exception.Message) }

    }

    $info = [ordered]@{

        install_id = if ($InstallId) { $InstallId } else { [guid]::NewGuid().ToString('N') }

        base = $core

        core = $core

        asr = $asr

        version = $Version

        maker = 'installer'

    }

    $json = $info | ConvertTo-Json

    [System.IO.File]::WriteAllText((Join-Path $Dir 'config\install.json'), $json,

        (New-Object System.Text.UTF8Encoding($false)))

    Write-Log "install.json: core=$core asr=$asr"

    foreach ($rel in @($LauncherFile, 'start.cmd', 'config\app.yaml')) {

        if (-not (Test-Path (Join-Path $Dir $rel))) { throw "安装后缺少 $rel" }

    }

    return $core

}



function Clear-Except([string]$Dir) {

    # 重装/升级时保留她的数据与已装好的依赖；其余旧文件清掉，避免残留

    if (-not (Test-Path $Dir)) { return }

    # 数据已搬到 $DataDir；程序目录里只保留依赖，其余全部由安装包重建

    $KeepRel = @('.venv', 'WiseEntity\entity\.venv',

                 'WiseEntity\capability\voice\asr\.venv')

    $Keep = @()

    foreach ($r in $KeepRel) { $Keep += (Join-Path $Dir $r).TrimEnd('\') }



    function Remove-Except([string]$Path) {

        foreach ($child in (Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)) {

            $full = $child.FullName.TrimEnd('\')

            $isKeep = $false

            $holdsKeep = $false

            foreach ($k in $Keep) {

                if ($full -eq $k -or $full.StartsWith($k + '\')) { $isKeep = $true; break }

                if ($k.StartsWith($full + '\')) { $holdsKeep = $true; break }

            }

            if ($isKeep) { continue }

            if ($holdsKeep) { Remove-Except $full; continue }

            Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction SilentlyContinue

        }

    }

    Remove-Except $Dir

}

# ---------------------------------------------------------------- 静默模式

if ($Silent) {

    if (-not (Test-Path $Zip)) { Fail "payload.zip 不在 $Here" }

    $err = Test-InstallTarget $Target

    if ($err) { Fail $err }

    if (-not (Test-Path $Target)) { New-Item -ItemType Directory -Force -Path $Target | Out-Null }

    $old = Read-InstallInfo $Target

    $oldCore = 0; $oldAsr = 0; $installId = ''

    if ($old.PSObject.Properties['core']) { $oldCore = [int]$old.core }

    elseif ($old.PSObject.Properties['base']) { $oldCore = [int]$old.base }

    if ($old.PSObject.Properties['asr']) { $oldAsr = [int]$old.asr }

    if ($old.PSObject.Properties['install_id']) { $installId = [string]$old.install_id }

    try {

        Expand-Payload $Target

        Initialize-Install $Target $oldCore $oldAsr $installId | Out-Null

    } catch { Fail "$_" }

    Write-Host "[install] silent OK -> $Target"

    exit 0

}



# ---------------------------------------------------------------- UI

Add-Type -AssemblyName System.Windows.Forms

Add-Type -AssemblyName System.Drawing

[System.Windows.Forms.Application]::EnableVisualStyles()



if (-not (Test-Path $Zip)) { Fail "payload.zip 不在 $Here" }



$lastParent = Get-LastParent

$defaultDir = if ($Target) { $Target }

elseif ($lastParent) { Join-Path $lastParent $DirName }

else { Join-Path $env:LOCALAPPDATA $DirName }



$form = New-Object System.Windows.Forms.Form

$setupIcon = Join-Path $PSScriptRoot 'bab-setup.ico'

if (Test-Path $setupIcon) {

    try { $form.Icon = New-Object System.Drawing.Icon($setupIcon) } catch { Write-Log ("icon failed: " + $_.Exception.Message) }

}

$form.Text = "$AppName $Version 安装程序"

$form.ClientSize = New-Object System.Drawing.Size(640, 430)

$form.StartPosition = 'CenterScreen'

$form.FormBorderStyle = 'FixedSingle'

$form.MaximizeBox = $false

$form.MinimizeBox = $false

$form.ShowInTaskbar = $true

$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)



$head = New-Object System.Windows.Forms.Label

$head.Text = "BetterAIBridge $Version"

$head.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 15, [System.Drawing.FontStyle]::Bold)

$head.AutoSize = $true

$head.Location = New-Object System.Drawing.Point(24, 18)

$form.Controls.Add($head)



$sub = New-Object System.Windows.Forms.Label

$sub.Text = "一个程序设计的AI生命：选好位置，点开始。装依赖要联网，慢的话十来分钟。"

$sub.AutoSize = $false

$sub.Location = New-Object System.Drawing.Point(26, 52)

$sub.Size = New-Object System.Drawing.Size(585, 36)

$sub.ForeColor = [System.Drawing.Color]::FromArgb(90, 90, 90)

$form.Controls.Add($sub)



$lblPath = New-Object System.Windows.Forms.Label

$lblPath.Text = '安装位置'

$lblPath.AutoSize = $true

$lblPath.Location = New-Object System.Drawing.Point(26, 100)

$form.Controls.Add($lblPath)



$tbPath = New-Object System.Windows.Forms.TextBox

$tbPath.Text = $defaultDir

$tbPath.Location = New-Object System.Drawing.Point(26, 122)

$tbPath.Size = New-Object System.Drawing.Size(500, 26)

$form.Controls.Add($tbPath)



$btnBrowse = New-Object System.Windows.Forms.Button

$btnBrowse.Text = '浏览…'

$btnBrowse.Location = New-Object System.Drawing.Point(534, 121)

$btnBrowse.Size = New-Object System.Drawing.Size(78, 28)

$form.Controls.Add($btnBrowse)



$lblHint = New-Object System.Windows.Forms.Label

$lblHint.Text = "默认装到新目录，旧版本和数据不会被覆盖。`r`n要沿用旧目录，请先导出存档，再把路径改到旧目录。"

$lblHint.AutoSize = $false

$lblHint.Location = New-Object System.Drawing.Point(26, 148)

$lblHint.Size = New-Object System.Drawing.Size(586, 30)

$lblHint.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 8.5)

$lblHint.ForeColor = [System.Drawing.Color]::FromArgb(110, 110, 110)

$form.Controls.Add($lblHint)



$lblPreview = New-Object System.Windows.Forms.Label

$lblPreview.AutoSize = $false

$lblPreview.Location = New-Object System.Drawing.Point(26, 180)

$lblPreview.Size = New-Object System.Drawing.Size(586, 18)

$lblPreview.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 8)

$form.Controls.Add($lblPreview)



$updatePreview = {

    $why = Test-InstallTarget $tbPath.Text

    if ($why) {

        $lblPreview.ForeColor = [System.Drawing.Color]::FromArgb(190, 60, 40)

        $lblPreview.Text = '不能用这个位置：' + $why

    } else {

        $lblPreview.ForeColor = [System.Drawing.Color]::FromArgb(40, 120, 80)

        $lblPreview.Text = '将安装到：' + $tbPath.Text

    }

}

$tbPath.Add_TextChanged($updatePreview)

& $updatePreview



$cbShortcut = New-Object System.Windows.Forms.CheckBox

$cbShortcut.Text = '创建桌面快捷方式'

$cbShortcut.Checked = $true

$cbShortcut.AutoSize = $true

$cbShortcut.Location = New-Object System.Drawing.Point(26, 212)

$form.Controls.Add($cbShortcut)



$cbDeps = New-Object System.Windows.Forms.CheckBox

$cbDeps.Text = '现在就装 Python 依赖（约 400MB，需要联网）'

$cbDeps.Checked = (-not $NoDeps)

$cbDeps.AutoSize = $true

$cbDeps.Location = New-Object System.Drawing.Point(26, 240)

$form.Controls.Add($cbDeps)



$cbLaunch = New-Object System.Windows.Forms.CheckBox

$cbLaunch.Text = '装完启动'

$cbLaunch.Checked = (-not $NoLaunch)

$cbLaunch.AutoSize = $true

$cbLaunch.Location = New-Object System.Drawing.Point(26, 268)

$form.Controls.Add($cbLaunch)



$pbar = New-Object System.Windows.Forms.ProgressBar

$pbar.Location = New-Object System.Drawing.Point(26, 290)

$pbar.Size = New-Object System.Drawing.Size(586, 20)

$pbar.Minimum = 0

$pbar.Maximum = 100

$form.Controls.Add($pbar)



$status = New-Object System.Windows.Forms.Label

$status.Text = '准备好了，点「开始安装」。装的时候别关窗口，进度会自己走完。'

$status.AutoSize = $false

$status.Location = New-Object System.Drawing.Point(26, 318)

$status.Size = New-Object System.Drawing.Size(586, 32)

$status.ForeColor = [System.Drawing.Color]::FromArgb(70, 70, 70)

$form.Controls.Add($status)



$btnStart = New-Object System.Windows.Forms.Button

$btnStart.Text = '开始安装'

$btnStart.Location = New-Object System.Drawing.Point(420, 360)

$btnStart.Size = New-Object System.Drawing.Size(190, 40)

$btnStart.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold)

$form.Controls.Add($btnStart)



$btnClose = New-Object System.Windows.Forms.Button

$btnClose.Text = '取消'

$btnClose.Location = New-Object System.Drawing.Point(320, 360)

$btnClose.Size = New-Object System.Drawing.Size(90, 40)

$form.Controls.Add($btnClose)


# ---- 0.5.1 背景：沿用启动器的内置白底图 ----

$bgPath = Join-Path $Here 'bab-bg.jpg'

if (Test-Path $bgPath) {

    try {

        $form.BackgroundImage = [System.Drawing.Image]::FromFile($bgPath)

        $form.BackgroundImageLayout = [System.Windows.Forms.ImageLayout]::Stretch

        foreach ($c in @($head, $sub, $lblPath, $lblHint, $lblPreview, $status,

                         $cbShortcut, $cbDeps, $cbLaunch)) {

            $c.BackColor = [System.Drawing.Color]::Transparent

        }

    } catch {

        Write-Log ('background failed: ' + $_.Exception.Message)

    }

}



$script:busy = $false

$script:done = $false



$btnBrowse.Add_Click({

    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog

    $dlg.Description = '选择安装位置'

    $dlg.SelectedPath = $tbPath.Text

    if ($dlg.ShowDialog() -eq 'OK') {

        $sel = $dlg.SelectedPath.TrimEnd([char]92)

        $leaf = Split-Path -Leaf $sel

        $isBab = (Test-Path (Join-Path $sel 'config\install.json')) -or

                 ((Test-Path (Join-Path $sel 'main.py')) -and (Test-Path (Join-Path $sel 'WiseEntity')))

        if ($isBab -or ($leaf -eq $DirName) -or ($leaf -eq $AppName)) { $tbPath.Text = $sel }

        else { $tbPath.Text = Join-Path $sel $DirName }

    }

})



$btnClose.Add_Click({

    if ($script:busy) {

        $status.Text = '正在安装，先别关。'

        return

    }

    $form.Close()

})



function Pump([int]$ms) {

    $end = (Get-Date).AddMilliseconds($ms)

    while ((Get-Date) -lt $end) {

        [System.Windows.Forms.Application]::DoEvents()

        Start-Sleep -Milliseconds 60

    }

}



$script:lastPct = -1

function Set-Progress([int]$v, [string]$msg) {

    $v = [Math]::Max(0, [Math]::Min(100, $v))

    $pbar.Value = $v

    if ($msg) { $status.Text = $msg }

    if ($v -ne $script:lastPct) { Write-Log ("progress {0}% {1}" -f $v, $msg); $script:lastPct = $v }

    [System.Windows.Forms.Application]::DoEvents()

}



function New-Shortcut([string]$dir) {

    $desktop = [Environment]::GetFolderPath('Desktop')

    # 旧版快捷方式带版本号；升级时清掉，桌面只留一个 BetterAIBridge。
    foreach ($pat in @('BetterAIBridgeLauncher *.lnk', 'BetterAIBridgeLauncher.lnk')) {
        Get-ChildItem -LiteralPath $desktop -Filter $pat -File -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }

    $lnkPath = Join-Path $desktop ($LauncherName + '.lnk')

    $icon = Join-Path $dir 'assets\bab.ico'

    $target = Join-Path $dir $LauncherFile

    if (-not (Test-Path $target)) { $target = Join-Path $dir 'start.cmd' }

    $ws = New-Object -ComObject WScript.Shell

    $lnk = $ws.CreateShortcut($lnkPath)

    $lnk.TargetPath = $target

    $lnk.WorkingDirectory = $dir

    $lnk.Description = $AppName

    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }

    $lnk.Save()

    Write-Log "shortcut -> $lnkPath (target $target)"

}



$btnStart.Add_Click({

    if ($script:busy) { return }

    $dir = $tbPath.Text.Trim().TrimEnd('\')

    if (-not $dir) { $status.Text = '先填一个安装位置。'; return }

    $why = Test-InstallTarget $dir

    if ($why) { $status.Text = $why; Write-Log "target rejected: $dir ($why)"; return }

    $parent = Split-Path -Parent $dir

    if ($parent -and -not (Test-Path $parent)) {

        try { New-Item -ItemType Directory -Force -Path $parent | Out-Null }

        catch { $status.Text = "建不了上级目录：$parent"; return }

    }



    $script:busy = $true

    $btnStart.Enabled = $false

    $btnBrowse.Enabled = $false

    $tbPath.ReadOnly = $true

    $cbShortcut.Enabled = $false

    $cbDeps.Enabled = $false

    $cbLaunch.Enabled = $false

    $btnClose.Enabled = $false

    Write-Log "install start -> $dir (deps=$($cbDeps.Checked))"



    try {

        Set-Progress 6 '正在检查安装位置…'

        $old = Read-InstallInfo $dir

        $oldCore = 0; $oldAsr = 0; $installId = ''

        if ($old.PSObject.Properties['core']) { $oldCore = [int]$old.core }

        elseif ($old.PSObject.Properties['base']) { $oldCore = [int]$old.base }

        if ($old.PSObject.Properties['asr']) { $oldAsr = [int]$old.asr }

        if ($old.PSObject.Properties['install_id']) { $installId = [string]$old.install_id }

        Set-Progress 10 '正在解压文件…'

        Expand-Payload $dir

        Set-Progress 18 '写入配置…'



        $corePort = Initialize-Install $dir $oldCore $oldAsr $installId



        if ($cbShortcut.Checked) {

            Set-Progress 24 '创建桌面快捷方式…'

            New-Shortcut $dir

        }



        if ($cbDeps.Checked) {

            Set-Progress 30 '安装 Python 依赖（5–15 分钟，别关窗口）…'

            $setup = Join-Path $dir 'setup.ps1'

            if (-not (Test-Path $setup)) { throw "setup.ps1 缺失" }

            $depsLog = Join-Path $env:TEMP 'bab-deps.log'

            $ps = (Get-Command powershell.exe).Source

            $args = '/c ""' + $ps + '" -NoProfile -ExecutionPolicy Bypass -File "' + $setup + '" > "' + $depsLog + '" 2>&1"'

            $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList $args -WindowStyle Hidden -PassThru

            $fake = 30

            while (-not $proc.HasExited) {

                if ($fake -lt 86) { $fake += 1 }

                Set-Progress $fake '安装 Python 依赖（5–15 分钟，别关窗口）…'

                Pump 900

            }

            if ($proc.ExitCode -ne 0) {

                throw ("装依赖失败（exit {0}）。日志：{1}" -f $proc.ExitCode, $depsLog)

            }

            Set-Progress 90 '依赖装好了…'

        }



        Set-Progress 96 '收尾…'

        Set-LastParent (Split-Path -Parent $dir)

        Write-Log 'install ok'



        if ($cbLaunch.Checked) {

            $launch = Join-Path $dir $LauncherFile

            if (Test-Path $launch) {

                Start-Process -FilePath 'wscript.exe' -ArgumentList ('"' + $launch + '"') -WorkingDirectory $dir

                Write-Log 'launched app'

            }

        }



        Set-Progress 100 '装好了，正在关闭…'

        $script:done = $true

        $status.ForeColor = [System.Drawing.Color]::FromArgb(30, 130, 70)

        Pump 1200

        $form.Close()

    } catch {

        $script:busy = $false

        $btnClose.Enabled = $true

        $status.ForeColor = [System.Drawing.Color]::FromArgb(180, 40, 40)

        $status.Text = '失败了：' + $_.Exception.Message

        Write-Log ('EXCEPTION ' + $_.Exception.ToString())

    }

})



$form.Add_FormClosing({

    param($s, $e)

    if ($script:busy -and -not $script:done) {

        $e.Cancel = $true

        $status.Text = '正在安装，先别关窗口，进度会自己走完。'

    }

})



Write-Log "installer shown (version $Version, target $defaultDir)"

if ($env:BAB_SELFTEST) {

    # 自测钩子：窗口显示后自动点"开始安装"，用于无人值守验证进度/自动关闭

    $form.Add_Shown({ try { $btnStart.PerformClick() } catch { Write-Log ('selftest click failed: ' + $_.Exception.Message) } })

}



[void]$form.Add_Shown({ [BabTaskbar]::Add($form.Handle) })

[void]$form.ShowDialog()

if (-not $script:done) { Write-Log 'installer closed without finish' }

