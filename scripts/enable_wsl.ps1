# 以管理员身份运行此脚本，启用 WSL2 与虚拟机平台
# 然后重启 Windows，再安装 Ubuntu： wsl --install -d Ubuntu
#
# 用管理员 PowerShell 运行：
#   powershell -ExecutionPolicy Bypass -File .\scripts\enable_wsl.ps1

$ErrorActionPreference = "Stop"

Write-Host "== 启用 Microsoft-Windows-Subsystem-Linux ==" -ForegroundColor Cyan
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart

Write-Host "== 启用 VirtualMachinePlatform ==" -ForegroundColor Cyan
Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart

Write-Host ""
Write-Host "完成！请重启 Windows，然后在普通 PowerShell 中执行：" -ForegroundColor Green
Write-Host "    wsl --install -d Ubuntu" -ForegroundColor Yellow
Write-Host "    # 安装完成后在 Ubuntu 中设置用户名密码"
Write-Host "    # 然后执行 scripts\setup_buildozer_in_wsl.sh"
