# One collection stream. Two of these run at once, each with its own relay on its own TCP port,
# both talking to the same teacher server — serve.py batches concurrent requests into one GPU
# forward pass (InferenceBatcher), so two streams are close to twice the throughput.
# Each worker takes half the garments (Seen_0-4 or Seen_5-9) and walks the four types in the same
# order, so the dataset stays balanced even if the run is cut short.
#   powershell -File balance_worker.ps1 -TcpPort 8767 -Only "_Seen_[0-4]$" -Session A
# ASCII only.
param(
    [int]$TcpPort = 8767,
    [string]$Only = "_Seen_[0-4]$",
    [string]$Session = "A",
    [int]$Keeps = 100
)
$base = "C:\Users\H\Desktop\lehome-win"
$winpy = "C:\Users\H\AppData\Local\Microsoft\WindowsApps\python.exe"
$mark = "$base\balance_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  [$Session] $m" | Out-File -Append -Encoding ascii $mark; Write-Host "[$Session] $m" }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function Restart-Relay([int]$gid) {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '15_winner_relay' -and $_.CommandLine -match "--tcp-port $TcpPort" -and $_.CommandLine -notmatch 'Win32_Process' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 5
    $a = @("$base\15_winner_relay.py", "--tcp-port", "$TcpPort", "--session", $Session,
           "--garment-id", "$gid", "--full-cfg")
    Start-Process -WindowStyle Hidden -FilePath $winpy -ArgumentList $a `
        -RedirectStandardOutput "$base\relay_${Session}_$gid.log" -RedirectStandardError "$base\relay_${Session}_$gid.err.log" -WorkingDirectory $base
    $t = 0; while (-not (PortUp $TcpPort) -and $t -lt 40) { Start-Sleep -Seconds 3; $t++ }
    return (PortUp $TcpPort)
}

# Top_Long episodes are spread over five earlier rounds, so its shortfall is counted across all of
# them and only the remainder is written to a new folder.
$TL_COUNT = "distill_data_rand,distill_data_r3,distill_data_r4,distill_data_fix,distill_data_fix2,distill_data_fix3"
$plan = @(
    @{ type = "Top_Short";  gid = 1; out = "distill_data_top_short";  count = ""; seed = 40000 },
    @{ type = "Pant_Long";  gid = 2; out = "distill_data_pant_long";  count = ""; seed = 50000 },
    @{ type = "Pant_Short"; gid = 3; out = "distill_data_pant_short"; count = ""; seed = 60000 },
    @{ type = "Top_Long";   gid = 0; out = "distill_data_fix3";       count = $TL_COUNT; seed = 70000 }
)
$off = if ($Session -eq "A") { 0 } else { 5000 }

foreach ($p in $plan) {
    if (-not (PortUp 8000)) { Mark "teacher 8000 down - abort"; exit 1 }
    if (-not (Restart-Relay $p.gid)) { Mark "relay restart failed for $($p.type) - skip"; continue }
    Mark "collect $($p.type) to $Keeps/garment ($Only)"
    # an empty -CountDirs value makes PowerShell treat the next token as the argument, so only
    # pass the switch when there is something to pass
    $args = @("-Type", $p.type, "-Keeps", "$Keeps", "-Chunks", "2", "-Out", $p.out,
              "-Only", $Only, "-SeedBase", "$($p.seed + $off)", "-GarmentTex", "half",
              "-Port", "$TcpPort")
    if ($p.count -ne "") { $args += @("-CountDirs", $p.count) }
    & powershell -ExecutionPolicy Bypass -File "$base\run_collect3.ps1" @args
    $now = @(Get-ChildItem "$base\$($p.out)" -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'meta.json') }).Count
    Mark "$($p.type) folder now holds $now"
}
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '15_winner_relay' -and $_.CommandLine -match "--tcp-port $TcpPort" -and $_.CommandLine -notmatch 'Win32_Process' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Mark "WORKER-$Session-DONE"
