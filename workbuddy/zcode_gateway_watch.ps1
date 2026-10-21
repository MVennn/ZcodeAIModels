#requires -Version 5.1
<#
.SYNOPSIS
    让 wb2api 网关的生命周期跟随 ZCode：ZCode 启动 -> 静默拉起网关，ZCode 全部退出 -> 停网关。

.DESCRIPTION
    常驻后台运行（无窗口），由同目录的 zcode_gateway_watch.vbs 启动。
    状态机只有两条：
      * ZCode 主进程从无到有 -> 确认网关在跑，不在就静默启动；
      * ZCode 主进程从有到无 -> 等 StopGraceSeconds 宽限 + 在途连接排空后停网关。
    主进程 = 命令行既不含 --type= 也不含 zcode.cjs 的那个 ZCode.exe（Electron 主进程），
    这样 GUI 子进程 / crashpad / CLI 宿主晚退几秒也不会拖住网关。
    网关在 ZCode 运行期间意外退出会自动重启（每 HealthCheckSeconds 检查一次）。

    环境变量（都可选）：
      WB_GATEWAY_DIR    网关安装目录（含 wb2api.exe 与 config.json）
                        默认 <仓库>/workbuddy/gateway（按脚本位置推导）
      WB_GATEWAY_BASE   健康检查地址，默认 http://127.0.0.1:7863
      ZCODE_WATCH_LOG   日志目录，默认 %LOCALAPPDATA%\ZCodeGateway

.PARAMETER Status
    打印一次当前状态（ZCode / 网关 / 守护器 / 日志位置）后退出。

.PARAMETER Install
    注册开机自启（启动文件夹放一个指向同目录 .vbs 的快捷方式），并立即启动守护器后退出。

.PARAMETER Uninstall
    删除开机自启快捷方式，并停掉当前守护器进程后退出（不动网关）。

.PARAMETER DryRun
    只记状态迁移，不启停任何进程（用于验证状态机）。

.PARAMETER Once
    只跑一轮状态检查就退出（用于调试）。

.PARAMETER DrainTimeoutSeconds
    停网关前等待在途连接排空的上限（秒），默认 30；超时才强制停止。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\zcode_gateway_watch.ps1 -Status

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\zcode_gateway_watch.ps1 -Install
#>
[CmdletBinding()]
param(
    [string]$GatewayDir = $env:WB_GATEWAY_DIR,
    [string]$GatewayBase = $(if ($env:WB_GATEWAY_BASE) { $env:WB_GATEWAY_BASE } else { 'http://127.0.0.1:7863' }),
    [string]$ProcessName = 'ZCode',
    [int]$PollMilliseconds = 500,
    [int]$StopGraceSeconds = 8,
    [int]$HealthCheckSeconds = 15,
    [int]$StartTimeoutSeconds = 25,
    [int]$DrainTimeoutSeconds = 30,
    [string]$LogDir = $env:ZCODE_WATCH_LOG,
    [string]$MutexName = 'Local\ZCodeGatewayWatch',
    [switch]$Status,
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$DryRun,
    [switch]$Once
)

$ProcessName = $ProcessName -replace '\.exe$', ''

if (-not $GatewayDir) {
    if ($PSScriptRoot) { $GatewayDir = Join-Path $PSScriptRoot 'gateway' }
    else { $GatewayDir = 'E:\Tool\AITool\workbuddy2api-panel' }
}
if (-not $LogDir) {
    if ($env:LOCALAPPDATA) { $LogDir = Join-Path $env:LOCALAPPDATA 'ZCodeGateway' }
    else { $LogDir = Join-Path $GatewayDir 'watch' }
}
$GatewayBase = $GatewayBase.TrimEnd('/')
$GatewayUri = [Uri]$GatewayBase
$LogFile = Join-Path $LogDir 'watchdog.log'
$WatchScript = $MyInvocation.MyCommand.Path
$VbsScript = Join-Path $PSScriptRoot 'zcode_gateway_watch.vbs'

function Write-Log {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    try {
        if (-not (Test-Path -LiteralPath $LogDir)) {
            New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        }
        if (Test-Path -LiteralPath $LogFile) {
            if ((Get-Item -LiteralPath $LogFile).Length -gt 1MB) {
                Move-Item -LiteralPath $LogFile -Destination "$LogFile.1" -Force
            }
        }
        [System.IO.File]::AppendAllText($LogFile, $line + "`r`n", (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

function Test-GatewayPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($GatewayUri.Host, $GatewayUri.Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-GatewayPid {
    try {
        $conn = Get-NetTCPConnection -LocalPort $GatewayUri.Port -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
    } catch { }
    return 0
}

function Test-GatewayReady {
    try {
        $r = Invoke-WebRequest -Uri ($GatewayBase + '/panel/') -UseBasicParsing -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Wait-GatewayDrained {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $conns = @(Get-NetTCPConnection -LocalPort $GatewayUri.Port -State Established -ErrorAction Stop)
        } catch {
            $conns = @()
        }
        if ($conns.Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-ZCodeMainProcess {
    # Electron 主进程的判据：命令行既没有 --type=（GPU/renderer/crashpad），
    # 也没有 zcode.cjs（app-server / plugin-host）。子进程晚退不会拖住网关。
    $exeName = $ProcessName + '.exe'
    $procs = @(Get-CimInstance Win32_Process -Filter "name='$exeName'" -ErrorAction SilentlyContinue)
    if ($procs.Count -eq 0) { return $null }
    return $procs | Where-Object {
        $_.CommandLine -and
        ($_.CommandLine -notmatch '--type=') -and
        ($_.CommandLine -notmatch 'zcode\.cjs')
    } | Select-Object -First 1
}

function Get-ProviderSummary {
    $path = $env:ZCODE_PERSONAL_PROVIDER_CONFIG_FILE
    if (-not $path) { $path = Join-Path $HOME '.zcode\v2\provider_config.json' }
    if (-not (Test-Path -LiteralPath $path)) { return @("Provider：未找到 $path") }
    try {
        $cfg = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $rules = $cfg.config.providerConfigRules.providerRules
        if ($rules -isnot [System.Array]) { $rules = @($rules) }
        $expected = $GatewayBase.TrimEnd('/') + '/v1'
        $lines = @()
        foreach ($r in $rules) {
            $provId = [string]$r.providerId
            if (-not $provId.StartsWith('workbuddy')) { continue }
            $base = [string]$r.config.api.baseUrl
            $ids = @($r.config.personalModelIds)
            $state = if ($base.TrimEnd('/') -eq $expected) { 'OK' } else { "不匹配，期望 $expected" }
            $keyState = if ($r.config.access.apiKey) { 'key 已配置' } else { 'key 缺失' }
            $name = if ($r.providerName) { $r.providerName } else { $provId }
            $lines += ("Provider：{0}（{1}）{2} 个模型 → {3} [{4}；{5}]" -f $name, $provId, $ids.Count, $base, $state, $keyState)
        }
        if ($lines.Count -eq 0) {
            $lines += 'Provider：未找到 workbuddy-* provider（先跑 workbuddy_zcode_sync.py）'
        }
        return $lines
    } catch {
        return @("Provider：读取失败 $($_.Exception.Message)")
    }
}

function Start-Gateway {
    $exe = Join-Path $GatewayDir 'wb2api.exe'
    $cfg = Join-Path $GatewayDir 'config.json'
    if (-not (Test-Path -LiteralPath $exe)) {
        Write-Log "启动失败：找不到 $exe（用 WB_GATEWAY_DIR 指定网关目录）"
        return 0
    }
    # 与 run.bat 一致：清掉继承来的 HTTP 代理，网关要直连上游
    $env:HTTP_PROXY = ''
    $env:HTTPS_PROXY = ''
    $env:http_proxy = ''
    $env:https_proxy = ''
    $env:NO_PROXY = '*'
    if (-not (Test-Path -LiteralPath $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    $outLog = Join-Path $LogDir 'gateway.stdout.log'
    $errLog = Join-Path $LogDir 'gateway.stderr.log'
    foreach ($f in @($outLog, $errLog)) {
        if (Test-Path -LiteralPath $f) { Move-Item -LiteralPath $f -Destination "$f.1" -Force }
    }
    try {
        $proc = Start-Process -FilePath $exe `
            -ArgumentList @('-config', $cfg) `
            -WorkingDirectory $GatewayDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $outLog `
            -RedirectStandardError $errLog `
            -PassThru
        Write-Log "已静默启动网关 pid=$($proc.Id)"
        return [int]$proc.Id
    } catch {
        Write-Log "启动网关异常：$($_.Exception.Message)"
        return 0
    }
}

function Stop-Gateway {
    param([int]$GatewayPid)
    if ($GatewayPid -le 0) { return }
    $proc = Get-Process -Id $GatewayPid -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Log "网关 pid=$GatewayPid 已不在"
        return
    }
    if ($proc.ProcessName -ne 'wb2api') {
        Write-Log "pid=$GatewayPid 现在是 $($proc.ProcessName)，不是 wb2api，跳过（避免误杀）"
        return
    }
    try {
        Stop-Process -Id $GatewayPid -Force -ErrorAction Stop
        Write-Log "已停止网关 pid=$GatewayPid"
    } catch {
        Write-Log "停止网关失败 pid=$GatewayPid：$($_.Exception.Message)"
    }
}

function Ensure-Gateway {
    $existing = Get-GatewayPid
    if ($existing -gt 0) {
        $owner = Get-Process -Id $existing -ErrorAction SilentlyContinue
        if ($owner -and $owner.ProcessName -eq 'wb2api') {
            Write-Log "网关已在监听 $GatewayBase（pid=$existing），接管"
            return $existing
        }
        $ownerName = if ($owner) { $owner.ProcessName } else { 'unknown' }
        Write-Log "端口 $($GatewayUri.Port) 被 $ownerName（pid=$existing）占用，不接管、不启动"
        return 0
    }
    $started = Start-Gateway
    if ($started -le 0) { return 0 }
    $deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        if (Test-GatewayReady) {
            $owner = Get-GatewayPid
            if ($owner -le 0) { $owner = $started }
            Write-Log "网关就绪 $GatewayBase（pid=$owner，/panel/ 200）"
            return $owner
        }
        if (-not (Get-Process -Id $started -ErrorAction SilentlyContinue)) {
            Write-Log "网关进程提前退出 pid=$started，见 $LogDir\gateway.stderr.log"
            return 0
        }
    }
    Write-Log "网关 ${StartTimeoutSeconds}s 内未就绪 pid=$started，继续守着"
    return $started
}

function Test-WatcherRunning {
    $held = $false
    try {
        $m = New-Object System.Threading.Mutex($false, $MutexName)
        try {
            $acquired = $m.WaitOne(0)
            if ($acquired) { $m.ReleaseMutex() }
            $held = -not $acquired
        } catch [System.Threading.AbandonedMutexException] {
            try { $m.ReleaseMutex() } catch { }
            $held = $false
        } finally {
            $m.Dispose()
        }
    } catch { }
    return $held
}

# ---- 一次性模式：Install / Uninstall / Status ---------------------------------

if ($Install) {
    if (-not (Test-Path -LiteralPath $VbsScript)) { throw "缺少静默启动器：$VbsScript" }
    $startup = [Environment]::GetFolderPath('Startup')
    $lnkPath = Join-Path $startup 'ZCode Gateway Watch.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
    $lnk.Arguments = '"' + $VbsScript + '"'
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.WindowStyle = 7
    $lnk.Description = 'ZCode 打开时自动拉起 wb2api 网关，关闭时停止'
    $lnk.Save()
    "已注册开机自启：$lnkPath"
    if (Test-WatcherRunning) {
        "守护器已在运行，无需重复启动"
    } else {
        Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\wscript.exe') `
            -ArgumentList ('"{0}"' -f $VbsScript) -WindowStyle Hidden
        Start-Sleep -Milliseconds 800
        "已启动守护器（无窗口）"
    }
    "日志：$LogFile"
    exit 0
}

if ($Uninstall) {
    $startup = [Environment]::GetFolderPath('Startup')
    $lnkPath = Join-Path $startup 'ZCode Gateway Watch.lnk'
    if (Test-Path -LiteralPath $lnkPath) {
        Remove-Item -LiteralPath $lnkPath -Force
        "已移除开机自启：$lnkPath"
    } else {
        "没有找到自启快捷方式：$lnkPath"
    }
    $watchers = @(Get-CimInstance Win32_Process -Filter "name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and $_.CommandLine.Contains('zcode_gateway_watch.ps1') -and
            $_.ProcessId -ne $PID
        })
    foreach ($w in $watchers) {
        try {
            Stop-Process -Id $w.ProcessId -Force -ErrorAction Stop
            "已停止守护器进程 pid=$($w.ProcessId)（网关保持运行）"
        } catch { }
    }
    exit 0
}

if ($Status) {
    $procs = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue)
    $main = Get-ZCodeMainProcess
    if ($procs.Count -gt 0) {
        if ($main) {
            "ZCode：运行中（主进程 pid=$($main.ProcessId)，共 $($procs.Count) 个进程）"
        } else {
            "ZCode：有 $($procs.Count) 个进程，但未识别到主进程"
        }
    } else {
        "ZCode：未运行"
    }
    if (Test-GatewayPort) {
        $gwPid = Get-GatewayPid
        $gw = if ($gwPid -gt 0) { Get-Process -Id $gwPid -ErrorAction SilentlyContinue } else { $null }
        $gwName = if ($gw) { $gw.ProcessName } else { 'unknown' }
        "网关：监听中 $GatewayBase（pid=$gwPid，$gwName）"
        if (Test-GatewayReady) { "网关：就绪（/panel/ 200）" } else { "网关：端口通但 /panel/ 未就绪" }
    } else {
        "网关：未监听"
    }
    if (Test-WatcherRunning) { "守护器：运行中" } else { "守护器：未运行" }
    foreach ($line in (Get-ProviderSummary)) { $line }
    "日志：$LogFile"
    exit 0
}

# ---- 常驻模式 ------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$mutex = New-Object System.Threading.Mutex($false, $MutexName)
$ownsMutex = $false
try {
    $ownsMutex = $mutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $ownsMutex = $true
}
if (-not $ownsMutex) {
    Write-Log '已有守护器实例在运行，本实例退出'
    exit 0
}

Write-Log "守护器启动：进程名=$ProcessName 网关目录=$GatewayDir 地址=$GatewayBase 日志=$LogFile"
if ($DryRun) { Write-Log '[dry-run] 只记录状态迁移，不启停任何进程' }

$gatewayPid = 0
$zcodeWasRunning = $false
$zcodeMainPid = 0
$stopPendingSince = $null
$nextStartAttempt = [DateTime]::MinValue
$lastHealthCheck = [DateTime]::MinValue
$lastNoMainLog = [DateTime]::MinValue

try {
    while ($true) {
        $now = Get-Date

        if ($zcodeMainPid -gt 0) {
            $alive = Get-Process -Id $zcodeMainPid -ErrorAction SilentlyContinue
            if (-not $alive) { $zcodeMainPid = 0 }
            $zcodeRunning = [bool]$alive
        } else {
            $anyProcs = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue)
            if ($anyProcs.Count -gt 0) {
                $main = Get-ZCodeMainProcess
                if ($main) {
                    $zcodeMainPid = [int]$main.ProcessId
                    $zcodeRunning = $true
                } else {
                    $zcodeRunning = $false
                    if (($now - $lastNoMainLog).TotalSeconds -ge 30) {
                        Write-Log "有 $($anyProcs.Count) 个 $ProcessName 进程，但未识别到主进程（按已退出处理）"
                        $lastNoMainLog = $now
                    }
                }
            } else {
                $zcodeRunning = $false
            }
        }

        if ($zcodeRunning) {
            $stopPendingSince = $null

            if (-not $zcodeWasRunning) {
                Write-Log "检测到 $ProcessName 主进程启动（pid=$zcodeMainPid）"
                if (-not $DryRun) {
                    foreach ($line in (Get-ProviderSummary)) {
                        if ($line -match '不匹配|未找到|未识别|读取失败|key 缺失') {
                            Write-Log "联动警告：$line"
                        }
                    }
                }
                if ($DryRun) {
                    Write-Log '[dry-run] 将拉起网关'
                } else {
                    $gatewayPid = Ensure-Gateway
                    $nextStartAttempt = if ($gatewayPid -gt 0) { [DateTime]::MinValue } else { $now.AddSeconds(60) }
                }
                $lastHealthCheck = $now
            } elseif (-not $DryRun -and (($now - $lastHealthCheck).TotalSeconds -ge $HealthCheckSeconds)) {
                $lastHealthCheck = $now
                if (-not (Test-GatewayPort) -and $now -ge $nextStartAttempt) {
                    Write-Log '网关无响应，尝试重启'
                    $gatewayPid = Ensure-Gateway
                    $nextStartAttempt = if ($gatewayPid -gt 0) { [DateTime]::MinValue } else { $now.AddSeconds(60) }
                }
            }

            $zcodeWasRunning = $true
        } else {
            if ($zcodeWasRunning) {
                if ($null -eq $stopPendingSince) {
                    $stopPendingSince = $now
                    Write-Log "$ProcessName 主进程已退出，${StopGraceSeconds}s 后停网关"
                } elseif (($now - $stopPendingSince).TotalSeconds -ge $StopGraceSeconds) {
                    # 宽限期内可能被重新打开（ZCode 更新重启 / 误关），再确认一次
                    $recheck = if ($DryRun) { $null } else { Get-ZCodeMainProcess }
                    if ($recheck) {
                        Write-Log "$ProcessName 主进程已回来（pid=$($recheck.ProcessId)），取消停网关"
                        $zcodeMainPid = [int]$recheck.ProcessId
                        $stopPendingSince = $null
                        $zcodeWasRunning = $true
                    } else {
                        if ($DryRun) {
                            Write-Log "[dry-run] 将停止网关 pid=$gatewayPid"
                        } else {
                            if (Wait-GatewayDrained -TimeoutSeconds $DrainTimeoutSeconds) {
                                Write-Log '在途连接已排空'
                            } else {
                                Write-Log "在途连接 ${DrainTimeoutSeconds}s 未排空，强制停止"
                            }
                            Stop-Gateway -GatewayPid $gatewayPid
                        }
                        $gatewayPid = 0
                        $stopPendingSince = $null
                        $zcodeWasRunning = $false
                    }
                }
            }
        }

        if ($Once) { break }
        Start-Sleep -Milliseconds $PollMilliseconds
    }
} finally {
    try { $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
}
