<#
    注册 / 卸载 Windows 计划任务：每天 18:00 自动生成公文通汇总
    用法：
        powershell -ExecutionPolicy Bypass -File install_task.ps1
        powershell -ExecutionPolicy Bypass -File install_task.ps1 -Time 18:30
        powershell -ExecutionPolicy Bypass -File install_task.ps1 -Uninstall
#>
param(
    [string]$Time = "18:00",
    [string]$TaskName = "SZTU-GongWenTong-DailyDigest",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $root "nbw_digest.py"

function Find-PythonW {
    $c = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($c) {
        $w = Join-Path (Split-Path $c.Source) "pythonw.exe"
        if (Test-Path $w) { return $w }
        return $c.Source
    }
    throw "未找到 pythonw.exe / python.exe，请先安装 Python 3 并加入 PATH。"
}

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "已删除计划任务：$TaskName" -ForegroundColor Green
    } else {
        Write-Host "计划任务不存在：$TaskName" -ForegroundColor Yellow
    }
    return
}

if (-not (Test-Path $script)) { throw "找不到主程序：$script" }

$pythonw = Find-PythonW
Write-Host "Python : $pythonw"
Write-Host "脚本   : $script"
Write-Host "时间   : 每天 $Time"

$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$script`"" -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

# StartWhenAvailable：错过时间点（关机/休眠）后开机补跑一次
# 失败自动重试 2 次、间隔 15 分钟（例如 18:00 恰好没连上校园网）
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 15)

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Force `
        -Description "每天抓取深圳技术大学公文通并生成 Markdown 汇总" | Out-Null
    Write-Host "`n已注册计划任务：$TaskName（每天 $Time 运行）" -ForegroundColor Green
} catch {
    Write-Host "Register-ScheduledTask 失败：$($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "改用 schtasks 注册……"
    $cmd = "`"$pythonw`" `"$script`""
    schtasks /Create /F /TN $TaskName /SC DAILY /ST $Time /TR $cmd | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "已通过 schtasks 注册：$TaskName（每天 $Time）" -ForegroundColor Green
    } else {
        throw "schtasks 注册失败，请用管理员身份重试。"
    }
}

Write-Host "`n查看状态： Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "立即试跑： Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "删除任务： powershell -ExecutionPolicy Bypass -File install_task.ps1 -Uninstall"
