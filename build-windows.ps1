$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 PyInstaller，正在安装..."
    python -m pip install pyinstaller
}

pyinstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "Codex剩余额度弹窗" `
    "codex_quota_popup.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 打包失败，退出码：$LASTEXITCODE"
}

Write-Host ""
Write-Host "打包完成：$projectRoot\dist\Codex剩余额度弹窗.exe"
