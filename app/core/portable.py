"""存档与卸载：纯逻辑（不弹窗、不依赖 Qt），方便单测。

存档 = 一个 zip（`.babpak`），里面只放"她还是她"需要的东西：
人格、记忆、模型/声音/情绪配置、聊天记录。不含程序本体、不含 .venv。

卸载 = 生成一段批处理：等两秒、让本进程先退出，再删掉整个程序目录。
只删**带 main.py 和 WiseEntity 的程序目录**，别的路径一律拒绝。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

from . import config

ARCHIVE_FORMAT = "bab-archive/1"
ARCHIVE_EXT = ".babpak"

# 会进存档的配置文件（占位模板不进）
CONFIG_FILES = ("llm.json", "tts.json", "emotion_profile.json", "stomach.json", "memory.json")
# 会进存档的状态文件（其余是运行期状态，不带走）
STATE_FILES = ("sessions.json", "persona_drift.json")


def entity_dir(project_root: Optional[Path] = None) -> Path:
    if project_root:
        return Path(project_root) / "entity"
    return config.entity_dir()


def archive_dir() -> Path:
    """存档默认放用户文档里，不放程序目录——卸载时不能被一起删掉。"""
    home = Path.home()
    docs = home / "Documents"
    base = (docs if docs.is_dir() else home) / "BetterAIBridge 存档"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        base = Path(config.APP_DIR) / "archives"
        base.mkdir(parents=True, exist_ok=True)
    return base


def archive_name(display: str, now: Optional[float] = None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(now if now is not None else time.time()))
    name = "".join(ch for ch in str(display or "智能体") if ch not in '\\/:*?"<>|').strip() or "智能体"
    return f"存档-{name}-{stamp}{ARCHIVE_EXT}"


def _walk_memory(memory: Path) -> Iterable[Path]:
    if not memory.is_dir():
        return []
    out: List[Path] = []
    for p in sorted(memory.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix in (".part", ".tmp") or p.name.startswith("."):
            continue
        out.append(p)
    return out


def collect(entity: Path) -> List[tuple[str, Path]]:
    """返回 (存档内路径, 源文件) 列表；存档内路径一律用 / 分隔。"""
    entity = Path(entity)
    items: List[tuple[str, Path]] = []

    persona = entity / "persona" / "persona.md"
    if persona.is_file():
        items.append(("entity/persona/persona.md", persona))

    cfg = entity / "config"
    for name in CONFIG_FILES:
        p = cfg / name
        if p.is_file():
            items.append((f"entity/config/{name}", p))

    for p in _walk_memory(entity / "memory"):
        items.append((f"entity/memory/{p.relative_to(entity / 'memory').as_posix()}", p))

    for p in _walk_memory(entity / "self"):
        items.append((f"entity/self/{p.relative_to(entity / 'self').as_posix()}", p))

    st = entity / "state"
    for name in STATE_FILES:
        p = st / name
        if p.is_file():
            items.append((f"entity/state/{name}", p))
    return items


def _llm_doc(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _llm_without_key(path: Path) -> bytes:
    """存档默认不带 Key：同一份配置，只把 api_key 拿掉。"""
    doc = _llm_doc(path)
    doc.pop("api_key", None)
    return json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")


def write_archive(entity: Path, display: str, note: str = "", target: Optional[Path] = None,
                  include_key: bool = False) -> Dict[str, Any]:
    """把人格/记忆/配置打成一个 .babpak。

    include_key=False（默认）时 llm.json 里的 api_key 会被拿掉：存档可以放心发给别人；
    include_key=True 才原样带上，换电脑不用重填，但拿到存档的人也能用这份额度。
    """
    entity = Path(entity)
    items = collect(entity)
    if not items:
        return {"ok": False, "error": "没有可存档的内容（人格、记忆、配置都是空的）"}
    path = Path(target) if target else (archive_dir() / archive_name(display))
    path.parent.mkdir(parents=True, exist_ok=True)
    llm_path = entity / "config" / "llm.json"
    has_key = bool(str(_llm_doc(llm_path).get("api_key") or "").strip())
    manifest = {
        "format": ARCHIVE_FORMAT,
        "app": "BetterAIBridge",
        "name": str(display or ""),
        "note": str(note or ""),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": len(items),
        "has_api_key": bool(include_key and has_key),
    }
    memory_n = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for rel, src in items:
            if rel == "entity/config/llm.json" and not include_key:
                zf.writestr(rel, _llm_without_key(src))
            else:
                zf.write(src, rel)
            if rel.startswith("entity/memory/"):
                memory_n += 1
    return {
        "ok": True,
        "path": str(path),
        "files": len(items),
        "memory": memory_n,
        "bytes": path.stat().st_size,
        "name": manifest["name"],
        "has_api_key": bool(manifest["has_api_key"]),
    }


def read_archive(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "error": f"找不到存档：{path}"}
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            manifest = {}
            if "manifest.json" in names:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            has_key = bool(manifest.get("has_api_key"))
            if not has_key and "entity/config/llm.json" in names:
                try:
                    doc = json.loads(zf.read("entity/config/llm.json").decode("utf-8-sig"))
                    has_key = bool(str((doc or {}).get("api_key") or "").strip())
                except Exception:  # noqa: BLE001
                    has_key = False
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        return {"ok": False, "error": f"这不是有效的存档：{exc}"}
    fmt = str(manifest.get("format") or "")
    if not fmt.startswith("bab-archive/"):
        return {"ok": False, "error": "存档清单不认识（缺 format 或版本不对）"}
    has_persona = "entity/persona/persona.md" in names
    has_memory = any(n.startswith("entity/memory/") for n in names)
    if not (has_persona or has_memory):
        return {"ok": False, "error": "存档里既没有人物也没有记忆"}
    return {"ok": True, "manifest": manifest, "members": names,
            "persona": has_persona, "memory": has_memory, "has_api_key": has_key}


MAX_ARCHIVE_FILES = 20000
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ONE = 64 * 1024 * 1024


def _archive_rel(name: str) -> Optional[str]:
    """把 zip 里的成员名换成 entity/ 下的相对路径；不属于存档白名单就返回 None。

    只认正斜杠、只认 entity/ 开头，且必须落在人格/配置/记忆/状态四类里。
    绝对路径、盘符、UNC、`..` 一律拒绝——这些在 Windows 上能跳出 entity。
    """
    if not name or "\\" in name or "\x00" in name:
        return None
    p = PurePosixPath(name)
    if p.is_absolute():
        return None
    parts = p.parts
    if len(parts) < 2 or parts[0] != "entity":
        return None
    if any(part in ("", ".", "..") for part in parts):
        return None
    if any(":" in part for part in parts):
        return None
    if name == "entity/persona/persona.md":
        return str(Path("persona") / "persona.md")
    if name in {f"entity/config/{n}" for n in CONFIG_FILES}:
        return "config/" + parts[-1]
    if name in {f"entity/state/{n}" for n in STATE_FILES}:
        return "state/" + parts[-1]
    if parts[1] == "memory" and len(parts) >= 3:
        return "/".join(parts[1:])
    if parts[1] == "self" and len(parts) >= 3:
        return "/".join(parts[1:])
    return None


def restore_archive(path: Path, entity: Path, api_key: str = "") -> Dict[str, Any]:
    """把存档写进 entity/。

    先全量校验再落盘：任何一条路径不在白名单里，整包拒绝，一个字节都不写。
    校验通过后先解到 entity 旁边的临时目录，最后逐个 os.replace 过去——
    中途失败不会留下半套文件，也不会覆盖到程序代码。

    api_key 非空时，导入完成后再补写进 config/llm.json（给「存档没带 Key」的情况用）。
    """
    info = read_archive(path)
    if not info.get("ok"):
        return info
    entity = Path(entity)
    pairs: List[tuple[str, str]] = []
    total = 0
    with zipfile.ZipFile(Path(path)) as zf:
        for name in zf.namelist():
            if name.endswith("/") or name == "manifest.json":
                continue
            rel = _archive_rel(name)
            if rel is None:
                return {"ok": False, "error": f"存档里有不允许的路径：{name}"}
            zi = zf.getinfo(name)
            if zi.file_size > MAX_ARCHIVE_ONE:
                return {"ok": False, "error": f"存档里的文件太大：{name}"}
            total += int(zi.file_size or 0)
            if total > MAX_ARCHIVE_BYTES:
                return {"ok": False, "error": "存档解压后太大，拒绝导入"}
            pairs.append((name, rel))
        if not pairs:
            return {"ok": False, "error": "存档里没有可导入的文件"}
        if len(pairs) > MAX_ARCHIVE_FILES:
            return {"ok": False, "error": "存档里的文件太多，拒绝导入"}

        stage = entity.parent / (".restore-" + uuid.uuid4().hex)
        try:
            for name, rel in pairs:
                dst = stage / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(zf.read(name))
            written = 0
            memory_n = 0
            for _name, rel in pairs:
                dst = entity / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage / rel, dst)
                written += 1
                if rel.startswith("memory/"):
                    memory_n += 1
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    key = str(api_key or "").strip()
    if key:
        cfg = entity / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        doc = _llm_doc(cfg / "llm.json")
        doc["api_key"] = key
        (cfg / "llm.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "files": written, "memory": memory_n,
            "manifest": info.get("manifest") or {},
            "has_api_key": bool(info.get("has_api_key") or key)}


def uninstall_workspace() -> Path:
    """卸载脚本要放在**纯 ASCII 路径**下（cmd 按 ANSI 解析，中文路径会变乱码）。"""
    candidates = [
        Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "BetterAIBridge",
        Path(os.environ.get("PUBLIC") or r"C:\Users\Public") / "BetterAIBridge",
    ]
    for p in candidates:
        if any(ord(ch) > 127 for ch in str(p)):
            continue
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".w"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
            return p
        except (OSError, UnicodeError):
            continue
    return Path(tempfile.gettempdir())


PS_TEMPLATE = r"""$ErrorActionPreference = 'SilentlyContinue'
$app = '__APP__'
$work = '__WORK__'
$log = Join-Path $env:TEMP 'bab-uninstall.log'

function Log([string] $m) {
    $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $m
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = '卸载 BetterAIBridge'
$form.ClientSize = New-Object System.Drawing.Size(520, 286)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.ControlBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(246, 248, 252)
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)

$title = New-Object System.Windows.Forms.Label
$title.Text = '正在卸载'
$title.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 16, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(34, 48, 74)
$title.Location = New-Object System.Drawing.Point(24, 20)
$title.AutoSize = $true
$form.Controls.Add($title)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = '会删除程序目录、快捷方式和临时文件。记忆和人格会先备份到本机，不会跟着删。'
$sub.ForeColor = [System.Drawing.Color]::FromArgb(110, 122, 145)
$sub.Location = New-Object System.Drawing.Point(26, 58)
$sub.Size = New-Object System.Drawing.Size(470, 36)
$form.Controls.Add($sub)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Minimum = 0
$bar.Maximum = 100
$bar.Value = 0
$bar.Location = New-Object System.Drawing.Point(26, 104)
$bar.Size = New-Object System.Drawing.Size(468, 16)
$bar.Style = 'Continuous'
$form.Controls.Add($bar)

$status = New-Object System.Windows.Forms.Label
$status.Text = '准备卸载…'
$status.ForeColor = [System.Drawing.Color]::FromArgb(58, 71, 99)
$status.Location = New-Object System.Drawing.Point(26, 132)
$status.Size = New-Object System.Drawing.Size(468, 40)
$form.Controls.Add($status)

$detail = New-Object System.Windows.Forms.Label
$detail.Text = ''
$detail.ForeColor = [System.Drawing.Color]::FromArgb(150, 160, 178)
$detail.Location = New-Object System.Drawing.Point(26, 176)
$detail.Size = New-Object System.Drawing.Size(468, 40)
$form.Controls.Add($detail)

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = '关闭'
$btnClose.Size = New-Object System.Drawing.Size(88, 30)
$btnClose.Location = New-Object System.Drawing.Point(406, 232)
$btnClose.FlatStyle = 'Flat'
$btnClose.BackColor = [System.Drawing.Color]::FromArgb(255, 255, 255)
$btnClose.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(220, 227, 238)
$btnClose.Visible = $false
$btnClose.Add_Click({ $form.Close() })
$form.Controls.Add($btnClose)

function Ui([int]$p, [string]$s) {
    if ($p -lt 0) { $p = 0 }
    if ($p -gt 100) { $p = 100 }
    $bar.Value = $p
    $status.Text = $s
    [System.Windows.Forms.Application]::DoEvents()
}

function Fail([string]$s) {
    $status.ForeColor = [System.Drawing.Color]::FromArgb(194, 64, 47)
    $status.Text = $s
    $detail.Text = '详细原因写在：' + $log
    $btnClose.Visible = $true
    [System.Windows.Forms.Application]::DoEvents()
}

$form.Show()
Ui 5 '正在关闭还在运行的程序…'

$self = $PID
$sep = [System.IO.Path]::DirectorySeparatorChar
$prefix = $app + $sep
$ci = [System.StringComparison]::OrdinalIgnoreCase
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $self -and $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($prefix, $ci)
} | ForEach-Object {
    Log ('kill ' + $_.ProcessId + ' ' + $_.Name)
    Stop-Process -Id $_.ProcessId -Force
}

Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $self -and $_.CommandLine -and
    $_.CommandLine.IndexOf($prefix, $ci) -ge 0 -and
    $_.Name -match '^(python|pythonw|node|electron)\.exe$'
} | ForEach-Object {
    Log ('kill(cmdline) ' + $_.ProcessId + ' ' + $_.Name)
    Stop-Process -Id $_.ProcessId -Force
}
Start-Sleep -Milliseconds 400

# 旧安装的记忆和人格还在程序目录里：先搬到用户数据目录，别跟着一起删。
$backup = ''
$inst = Join-Path $app 'config\install.json'
$hasData = $false
if (Test-Path -LiteralPath $inst) {
    try {
        $j = Get-Content -LiteralPath $inst -Raw | ConvertFrom-Json
        if ($j.data_dir -and (Test-Path -LiteralPath $j.data_dir)) { $hasData = $true }
    } catch { }
}
$entity = Join-Path $app 'WiseEntity\entity'
if ((-not $hasData) -and (Test-Path -LiteralPath (Join-Path $entity 'persona'))) {
    $backup = Join-Path $env:LOCALAPPDATA ('BetterAIBridge\uninstalled-entity-' + $stamp)
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    Move-Item -LiteralPath $entity -Destination $backup -Force -ErrorAction SilentlyContinue
    Log ('backup entity -> ' + $backup)
}

Ui 12 '正在删除快捷方式…'
$sh = New-Object -ComObject WScript.Shell
$places = @(
    [System.IO.Path]::Combine($env:USERPROFILE, 'Desktop'),
    [System.IO.Path]::Combine($env:PUBLIC, 'Desktop'),
    [System.IO.Path]::Combine($env:APPDATA, 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
    [System.IO.Path]::Combine($env:APPDATA, 'Microsoft', 'Internet Explorer', 'Quick Launch', 'User Pinned', 'TaskBar')
)
foreach ($dir in $places) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    Get-ChildItem -LiteralPath $dir -Filter *.lnk -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
        $lnk = $_
        $target = ''
        try { $target = $sh.CreateShortcut($lnk.FullName).TargetPath } catch { }
        if ($target -and $target.StartsWith($prefix, $ci)) {
            Log ('del lnk ' + $lnk.FullName + ' -> ' + $target)
            Remove-Item -LiteralPath $lnk.FullName -Force
        }
    }
}

$startMenu = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft', 'Windows', 'Start Menu', 'Programs')
Get-ChildItem -LiteralPath $startMenu -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $sub2 = $_
    $files = @(Get-ChildItem -LiteralPath $sub2.FullName -Recurse -File -ErrorAction SilentlyContinue)
    $name = $sub2.Name.ToLower()
    if ($files.Count -eq 0 -and ($name -like '*betteraibridge*' -or $name -like 'bab*')) {
        Log ('rmdir ' + $sub2.FullName)
        Remove-Item -LiteralPath $sub2.FullName -Recurse -Force
    }
}

Ui 25 '正在删除程序文件…'
$top = @(Get-ChildItem -LiteralPath $app -Force -ErrorAction SilentlyContinue)
$n = $top.Count
if ($n -lt 1) { $n = 1 }
$i = 0
foreach ($it in $top) {
    $detail.Text = '正在删除：' + $it.Name
    Remove-Item -LiteralPath $it.FullName -Recurse -Force -ErrorAction SilentlyContinue
    $i++
    $pct = 25 + [int](65 * $i / $n)
    Ui $pct ('正在删除程序文件…（' + $i + ' / ' + $n + '）')
}

for ($i = 0; $i -lt 40; $i++) {
    if (-not (Test-Path -LiteralPath $app)) { break }
    Remove-Item -LiteralPath $app -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $app) {
        & cmd /c ('rd /s /q "' + $app + '"') 2>$null
    }
    Start-Sleep -Seconds 1
}

Ui 96 '正在清理临时文件…'
if ($work -and (Test-Path -LiteralPath $work)) {
    Get-ChildItem -LiteralPath $work -File -Filter 'bab-uninstall-*' -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddMinutes(-1) } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}

# 文件删净了、只剩一个空根目录被句柄占着：这不算失败。
if (Test-Path -LiteralPath $app) {
    $leftFiles = @(Get-ChildItem -LiteralPath $app -Recurse -File -Force -ErrorAction SilentlyContinue)
    if ($leftFiles.Count -eq 0) {
        $newName = $app + '.delete-' + $stamp
        try {
            Rename-Item -LiteralPath $app -NewName (Split-Path -Leaf $newName) -ErrorAction Stop
            Log ('renamed empty dir -> ' + $newName)
        } catch {
            Remove-Item -LiteralPath $app -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

if (Test-Path -LiteralPath $app) {
    Log 'STILL THERE'
    $left = @(Get-ChildItem -LiteralPath $app -Recurse -File -ErrorAction SilentlyContinue |
              Select-Object -First 20 -ExpandProperty FullName)
    foreach ($f in $left) { Log ('  locked: ' + $f) }
    Fail '还有文件没删干净：可能被别的程序占用。关掉相关程序后重试，或手动删除这个目录。'
    $detail.Text = $app + '　·　日志：' + $log
    while ($form.Visible) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 80
    }
} else {
    Log 'removed'
    $bar.Value = 100
    $status.Text = '卸载完成'
    $status.ForeColor = [System.Drawing.Color]::FromArgb(26, 157, 91)
    if ($backup) {
        $detail.Text = '记忆和人格已备份到：' + $backup
    } else {
        $detail.Text = '程序目录、快捷方式和临时文件都已清理。'
    }
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 1200
    $form.Close()
}
"""


def uninstall_script(app_dir: Path) -> Dict[str, Any]:
    """生成卸载方案：一个纯 ASCII 的 .cmd 壳 + 一段 UTF-8(BOM) 的 PowerShell。"""
    app = Path(app_dir).resolve()
    parts = app.parts
    # 允许 D:\BetterAIBridge 这种"盘符 + 一层目录"（安装器默认就装在这里），
    # 但要挡住盘根、系统目录和用户目录本身。
    if len(parts) < 2 or not app.name:
        return {"ok": False, "reason": f"这个路径太浅，不敢删：{app}"}
    if app.name.lower() in {"windows", "program files", "program files (x86)", "users", "system32"}:
        return {"ok": False, "reason": f"这是系统目录，不敢删：{app}"}
    if not (app / "main.py").is_file():
        return {"ok": False, "reason": f"这里没有 main.py，不像是程序目录：{app}"}
    if not (app / "WiseEntity").is_dir():
        return {"ok": False, "reason": f"这里没有 WiseEntity，不像是程序目录：{app}"}

    work_dir = uninstall_workspace()
    ps1 = PS_TEMPLATE.replace("__APP__", str(app)).replace("__WORK__", str(work_dir))
    cmd = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        'powershell -NoProfile -ExecutionPolicy Bypass -File "{ps1}"\r\n'
        "exit /b 0\r\n"
    )
    return {
        "ok": True,
        "app_dir": str(app),
        "ps1": ps1,
        "cmd": cmd,
        "log": str(Path(tempfile.gettempdir()) / "bab-uninstall.log"),
        "work_dir": str(work_dir),
    }


def spawn_uninstall(plan: Dict[str, Any]) -> Dict[str, Any]:
    """落地 ps1/cmd 并脱离父进程启动；调用方随后自己退出。"""
    if not plan.get("ok"):
        return {"ok": False, "error": plan.get("reason") or "卸载计划无效"}
    # 保险：BAB_NO_UNINSTALL=1 时只回计划、不落盘不起进程。
    # 测试必须设它——2026-10-31 一次跑测试真的把开发树删了。
    if os.environ.get("BAB_NO_UNINSTALL") == "1":
        return {"ok": True, "script": "", "dry_run": True, "app_dir": plan.get("app_dir")}

    work = Path(plan.get("work_dir") or uninstall_workspace())
    work.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    ps1 = work / f"bab-uninstall-{stamp}.ps1"
    cmd = work / f"bab-uninstall-{stamp}.cmd"
    # PS 5.1 只有看到 BOM 才会按 UTF-8 读脚本，否则中文路径一律乱码。
    ps1.write_text(plan["ps1"], encoding="utf-8-sig", newline="\r\n")
    cmd.write_text(plan["cmd"].replace("{ps1}", str(ps1)), encoding="ascii", newline="")
    # 用 CREATE_NO_WINDOW（不是 DETACHED_PROCESS）：不再弹 cmd/PowerShell 黑窗口，
    # 只留脚本自己画的那块卸载窗口；进程独立于启动器，启动器可以立刻退出。
    flags = 0
    if os.name == "nt":
        flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    # cwd 必须离开程序目录：Windows 删不掉"某个活进程的当前目录"。
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-File", str(ps1)],
        cwd=str(work), creationflags=flags, close_fds=True,
    )
    return {"ok": True, "script": str(ps1), "ps1": str(ps1), "cmd": str(cmd)}
