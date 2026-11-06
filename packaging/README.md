# 出包（Windows）

这个目录是 `BetterAIBridge-Setup-*.exe` 的可复现脚本副本。以前它放在 `C:\bab_pkg`，
仓库里只有一个“去那台机器上跑”的说明；现在脚本和 IExpress 资源都在这里。

## 依赖

- Windows 10/11
- PowerShell 5.1+（系统自带）
- 源码树已建好 `.venv`（`python -m venv .venv` + `requirements-launcher.txt`）
- 内置的 `iexpress.exe`（`%WINDIR%\System32\iexpress.exe`）

## 出包

```powershell
# 在仓库根
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build.ps1
```

默认行为：

- 版本号从仓库根 `VERSION.txt` 读取（`BetterAIBridge 0.4.58` → `0.4.58`）。
- 源码目录 = 本目录的上一级。
- 产物写到仓库的上一级 `dist\BetterAIBridge-Setup-<版本>.exe`。
- 先在源码树跑 `tools/check.py`，失败就不出包。

常用参数：

```powershell
# 指定版本（不读 VERSION.txt）
powershell -NoProfile -File packaging\build.ps1 -Version 0.4.58

# 指定源码/输出
powershell -NoProfile -File packaging\build.ps1 -Src D:\BetterAIBridge -Out D:\BAB-release

# 急着出包，跳过自检（不建议）
powershell -NoProfile -File packaging\build.ps1 -SkipCheck
```

## 目录里的文件

| 文件 | 用途 |
|---|---|
| `build.ps1` | staging → payload.zip → bab.sed → IExpress |
| `install.ps1` | 安装器主体（解压、依赖、快捷方式、首次配置） |
| `install.cmd` / `install.vbs` | IExpress 的入口，隐藏窗口并取退出码 |
| `bab.ico` / `bab-setup.ico` | 安装器窗口和快捷方式图标 |

`payload/`、`payload.zip`、`bab.sed` 是构建中间产物，已在 `.gitignore` 里。

## 验证

构建完至少做一次静默安装：

```powershell
$env:BAB_TEST_DIR = 'D:\bab_test_x'
powershell -NoProfile -File packaging\install.ps1 -NoDeps -NoLaunch
Remove-Item Env:BAB_TEST_DIR
```

检查 `VERSION.txt`、`config/install.json` 的 `version`、`program_cache` 和关键文件哈希。
