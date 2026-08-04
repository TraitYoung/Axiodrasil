param(
    [ValidateSet("start", "stop", "restart", "status", "menu")]
    [string]$Action = "menu",
    [switch]$All,
    [ValidateSet("redis", "backend", "frontend")]
    [string[]]$Service = @(),
    [switch]$ForceKillPort,
    [switch]$OpenBrowser
)

# 菜单里选「启动全部 / 重启全部」时自动打开浏览器（命令行请用：-Action start -All -OpenBrowser）
$script:OpenBrowserFromMenu = $false

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $ProjectRoot ".devstack"
$LogDir = Join-Path $StateDir "logs"
$PidFile = Join-Path $StateDir "pids.json"
# 与启动器一致：Windows 本地库，避免落在 WSL UNC 路径导致 SQLite 卡死
$DefaultDbPath = Join-Path $env:USERPROFILE ".axiodrasil\axiodrasil_core.db"
if ([string]::IsNullOrWhiteSpace($env:AX_DB_PATH)) {
    $env:AX_DB_PATH = $DefaultDbPath
}

$Services = @{
    redis = @{
        Name = "redis"
        Port = 6379
        Cwd = $ProjectRoot
        Command = "redis-server --port 6379"
        Log = Join-Path $LogDir "redis.log"
    }
    backend = @{
        Name = "backend"
        Port = 8000
        Cwd = $ProjectRoot
        Command = "python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"
        Log = Join-Path $LogDir "backend.log"
    }
    frontend = @{
        Name = "frontend"
        Port = 3000
        Cwd = Join-Path $ProjectRoot "frontend"
        Command = "npm run dev"
        Log = Join-Path $LogDir "frontend.log"
    }
}

function Ensure-Dirs {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Read-Pids {
    if (-not (Test-Path $PidFile)) { return @{} }
    try {
        $raw = Get-Content $PidFile -Raw
        if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
        $obj = $raw | ConvertFrom-Json
        if ($null -eq $obj) { return @{} }

        $map = @{}
        foreach ($prop in $obj.PSObject.Properties) {
            $map[$prop.Name] = [int]$prop.Value
        }
        return $map
    } catch {
        return @{}
    }
}

function Write-Pids([hashtable]$map) {
    ($map | ConvertTo-Json -Depth 5) | Set-Content -Path $PidFile -Encoding UTF8
}

function Is-ProcessAlive([int]$ProcId) {
    $proc = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    return $null -ne $proc
}

function Get-PortPids([int]$Port) {
    $list = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    if ($null -eq $list) { return @() }
    return @($list)
}

function Stop-ByPort([int]$Port) {
    $pids = @(Get-PortPids -Port $Port)
    foreach ($portPid in $pids) {
        $stillAlive = $true
        try {
            Stop-Process -Id $portPid -Force -ErrorAction Stop
            Write-Host "Stopped PID=$portPid on port $Port"
            $stillAlive = $false
        } catch {
            Write-Warning "Stop-Process 失败 PID=$portPid 端口=${Port}: $($_.Exception.Message)"
        }
        if ($stillAlive -and (Get-Process -Id $portPid -ErrorAction SilentlyContinue)) {
            try {
                $p = Start-Process -FilePath "taskkill.exe" -ArgumentList @("/F", "/PID", "$portPid") -Wait -PassThru -WindowStyle Hidden -ErrorAction Stop
                if ($p.ExitCode -eq 0) {
                    Write-Host "Stopped PID=$portPid on port $Port (taskkill)"
                    $stillAlive = $false
                }
            } catch {
                # ignore
            }
        }
        if ($stillAlive -and (Get-Process -Id $portPid -ErrorAction SilentlyContinue)) {
            Write-Warning @"
仍无法结束 PID=${portPid}（常见原因：Redis 以 Windows 服务 / SYSTEM / 管理员身份启动，当前 PowerShell 权限不足）。
请任选其一：
  1) 右键「以管理员身份运行」PowerShell，再执行： .\scripts\dev_stack.ps1 -Action stop -All
  2) 若 Redis 是服务： services.msc 中找到 Redis 并「停止」
  3) 管理员 CMD： taskkill /F /PID ${portPid}
"@
        }
    }
}

function Resolve-Targets {
    if ($All -or $Service.Count -eq 0) {
        return @("redis", "backend", "frontend")
    }
    return $Service
}

function Get-WslInfo([string]$windowsPath) {
    # \\wsl.localhost\Ubuntu-24.04\home\admin\Axiodrasil -> distro + /home/admin/Axiodrasil
    if ($windowsPath -match '^\\\\(?:wsl\.localhost|wsl\$)\\([^\\]+)\\(.+)$') {
        $rest = ($Matches[2] -replace '\\', '/').TrimStart('/')
        return @{ Distro = $Matches[1]; LinuxPath = "/$rest" }
    }
    return $null
}

function Wait-PortListen([int]$Port, [int]$TimeoutSec = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $listen = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        if ($listen.Count -gt 0) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-One([string]$name, [hashtable]$pids) {
    $svc = $Services[$name]
    if ($null -eq $svc) { throw "Unknown service: $name" }

    # 以端口为准，避免外壳进程还在但服务已挂时误判「已启动」
    $portPids = @(Get-PortPids -Port $svc.Port)
    if ($portPids.Count -gt 0) {
        Write-Host "[$name] already running on port $($svc.Port) (PID(s): $($portPids -join ', '))"
        return
    }

    # 项目在 WSL UNC 时：Windows npm/cmd 无法作当前目录，前端必须走 WSL+nvm
    if ($name -eq "frontend") {
        $wsl = Get-WslInfo -windowsPath $ProjectRoot
        if ($null -ne $wsl) {
            $linuxFe = "$($wsl.LinuxPath)/frontend"
            $inner = "pkill -f next-server 2>/dev/null || true; pkill -f 'next dev' 2>/dev/null || true; cd '$linuxFe' && npm run dev -- --hostname 127.0.0.1 --port $($svc.Port)"
            $psCmd = "wsl -d '$($wsl.Distro)' -- bash -lic `"$inner`""
            $proc = Start-Process -FilePath "powershell" -ArgumentList @("-NoProfile", "-Command", $psCmd) -PassThru -WindowStyle Minimized
            $pids[$name] = $proc.Id
            Write-Host "[$name] started via WSL $($wsl.Distro) (PID=$($proc.Id), port=$($svc.Port))"
            return
        }
    }

    $psCmdParts = @("Set-Location -LiteralPath '$($svc.Cwd)'")
    if ($name -eq "backend") {
        $dbEsc = $env:AX_DB_PATH.Replace("'", "''")
        $psCmdParts = @(
            "`$env:AX_DB_PATH = '$dbEsc'",
            "Set-Location -LiteralPath '$($svc.Cwd)'",
            "$($svc.Command)"
        )
        Write-Host "[$name] AX_DB_PATH=$($env:AX_DB_PATH)"
    } else {
        $psCmdParts += "$($svc.Command)"
    }
    $psCmd = $psCmdParts -join "; "
    $proc = Start-Process -FilePath "powershell" -ArgumentList @("-NoProfile", "-Command", $psCmd) -PassThru -WindowStyle Minimized
    $pids[$name] = $proc.Id
    Write-Host "[$name] started (PID=$($proc.Id), port=$($svc.Port))"
    if ($name -eq "redis") {
        Start-Sleep -Milliseconds 500
        $listen = @(Get-NetTCPConnection -LocalPort $svc.Port -State Listen -ErrorAction SilentlyContinue)
        if ($listen.Count -eq 0) {
            Write-Warning "[$name] 端口 $($svc.Port) 未处于 Listen。常见原因：旧实例（如 Windows 服务）仍占用端口，或 redis-server 启动失败。请查看 $($svc.Log)"
        }
    }
}

function Stop-One([string]$name, [hashtable]$pids) {
    $svc = $Services[$name]
    if ($null -eq $svc) { throw "Unknown service: $name" }

    $stopped = $false
    if ($pids.ContainsKey($name)) {
        $svcPid = [int]$pids[$name]
        if ($svcPid -gt 0 -and (Is-ProcessAlive -ProcId $svcPid)) {
            try {
                Stop-Process -Id $svcPid -Force -ErrorAction Stop
                Write-Host "[$name] stopped by pid (PID=$svcPid)"
                $stopped = $true
            } catch {
                Write-Warning "[$name] failed stopping PID=$svcPid`: $($_.Exception.Message)"
            }
        }
        $pids.Remove($name) | Out-Null
    }

    $portPids = @(Get-PortPids -Port $svc.Port)
    if ($portPids.Count -gt 0) {
        Stop-ByPort -Port $svc.Port
        $stopped = $true
    }

    if (-not $stopped) {
        Write-Host "[$name] not running"
    }
}

function Status-One([string]$name, [hashtable]$pids) {
    $svc = $Services[$name]
    $recordedPid = if ($pids.ContainsKey($name)) { [int]$pids[$name] } else { 0 }
    $alive = $false
    if ($recordedPid -gt 0) { $alive = Is-ProcessAlive -ProcId $recordedPid }
    $portPids = @(Get-PortPids -Port $svc.Port)
    $portInfo = if ($portPids.Count -gt 0) { $portPids -join "," } else { "-" }
    $state = if ($alive -or $portPids.Count -gt 0) { "RUNNING" } else { "STOPPED" }
    Write-Host ("{0,-9} state={1,-8} pid={2,-8} port={3,-5} owner={4}" -f $name, $state, $recordedPid, $svc.Port, $portInfo)
}

function Start-Targets {
    Ensure-Dirs
    $pids = Read-Pids
    foreach ($name in (Resolve-Targets)) {
        Start-One -name $name -pids $pids
    }
    Write-Pids -map $pids

    $targets = Resolve-Targets
    if ($targets -contains "frontend" -or $All) {
        if (-not (Wait-PortListen -Port 3000 -TimeoutSec 90)) {
            Write-Warning "前端端口 3000 未就绪。项目在 WSL 路径时请确认 WSL 内已装 Node（nvm）。"
        }
    }
    if ($targets -contains "backend" -or $All) {
        if (-not (Wait-PortListen -Port 8000 -TimeoutSec 45)) {
            Write-Warning "后端端口 8000 未就绪，请查看 .devstack/logs/backend.log"
        }
    }

    if ($OpenBrowser -or $script:OpenBrowserFromMenu) {
        if ($targets -contains "frontend" -or $All) {
            try {
                Start-Process "http://127.0.0.1:3000/solo"
                Write-Host "Opened browser: http://127.0.0.1:3000/solo"
            } catch {
                Write-Warning "Failed to open browser automatically: $($_.Exception.Message)"
            }
        }
    }
}

function Stop-Targets {
    Ensure-Dirs
    $pids = Read-Pids
    foreach ($name in (Resolve-Targets)) {
        Stop-One -name $name -pids $pids
    }
    Write-Pids -map $pids
}

function Restart-Targets {
    Stop-Targets
    Start-Targets
}

function Status-Targets {
    Ensure-Dirs
    $pids = Read-Pids
    foreach ($name in (Resolve-Targets)) {
        Status-One -name $name -pids $pids
    }
}

function Show-Menu {
    Write-Host ""
    Write-Host "=== Dev Stack Control ===" -ForegroundColor Cyan
    Write-Host "1) Start ALL"
    Write-Host "2) Stop ALL"
    Write-Host "3) Restart ALL"
    Write-Host "4) Status"
    Write-Host "5) Start one (redis/backend/frontend)"
    Write-Host "6) Stop one (redis/backend/frontend)"
    Write-Host "0) Exit"
    Write-Host ""
}

function Run-Menu {
    while ($true) {
        Show-Menu
        $choice = Read-Host "Select"
        switch ($choice) {
            "1" { $script:All = $true; $script:OpenBrowserFromMenu = $true; Start-Targets; $script:OpenBrowserFromMenu = $false }
            "2" { $script:All = $true; Stop-Targets }
            "3" { $script:All = $true; $script:OpenBrowserFromMenu = $true; Restart-Targets; $script:OpenBrowserFromMenu = $false }
            "4" { $script:All = $true; Status-Targets }
            "5" {
                $target = Read-Host "Service name"
                $script:All = $false
                $script:Service = @($target)
                Start-Targets
            }
            "6" {
                $target = Read-Host "Service name"
                $script:All = $false
                $script:Service = @($target)
                Stop-Targets
            }
            "0" { break }
            default { Write-Warning "Invalid choice" }
        }
    }
}

switch ($Action) {
    "start" { Start-Targets }
    "stop" { Stop-Targets }
    "restart" { Restart-Targets }
    "status" { Status-Targets }
    "menu" { Run-Menu }
}
