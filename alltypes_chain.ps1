# Four-garment-type expansion (2026-09-07). Until now the whole project only ever ran Top_Long,
# but the competition scores the average over Top_Long / Top_Short / Pant_Long / Pant_Short.
# The judge now dispatches per type (lehome_scene.check_conditions) and the pant 90-degree yaw and
# 4-condition thresholds were verified on the real benchmark path.
#
#   1) wait for the running Top_Long collection to finish (the relay serves one client)
#   2) for each new type: restart the relay pinned to that type with the official per-type
#      inference parameters (--garment-id N --full-cfg), then collect
#   3) restore the relay to its default state
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$winpy = "C:\Users\H\AppData\Local\Microsoft\WindowsApps\python.exe"
$mark = "$base\alltypes_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function MarkerDone([string]$file, [string]$pat) { return (Test-Path $file) -and (Select-String -Path $file -Pattern $pat -Quiet) }
function Restart-Relay([int]$gid) {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '15_winner_relay' -and $_.CommandLine -notmatch 'Win32_Process' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 5
    $a = @("$base\15_winner_relay.py")
    if ($gid -ge 0) { $a += @("--garment-id", "$gid", "--full-cfg") }
    Start-Process -WindowStyle Hidden -FilePath $winpy -ArgumentList $a `
        -RedirectStandardOutput "$base\relay_type$gid.log" -RedirectStandardError "$base\relay_type$gid.err.log" -WorkingDirectory $base
    $t = 0; while (-not (PortUp 8767) -and $t -lt 40) { Start-Sleep -Seconds 3; $t++ }
    return (PortUp 8767)
}

# ---- 1) wait for the Top_Long collection currently running
Mark "alltypes armed - waiting for COLLECT-MORE-DONE"
$t = 0
while ($t -lt 900) {
    if (MarkerDone "$base\collect_more_markers.log" 'COLLECT-MORE-DONE') { break }
    $alive = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'collect_more\.ps1' -and $_.CommandLine -notmatch 'Win32_Process' }
    if (-not $alive) { Mark "collect_more gone - proceeding"; break }
    Start-Sleep -Seconds 60; $t++
}
if (-not (PortUp 8000)) { Mark "teacher 8000 down - abort"; exit 1 }

# ---- 2) collect the three new types
#   garment id: 0 top_long, 1 top_short, 2 pant_long, 3 pant_short (15_winner_relay.GARMENT_TYPES)
$plan = @(
    @{ type = "Top_Short";  gid = 1; out = "distill_data_top_short";  seed = 6000 },
    @{ type = "Pant_Long";  gid = 2; out = "distill_data_pant_long";  seed = 7000 },
    @{ type = "Pant_Short"; gid = 3; out = "distill_data_pant_short"; seed = 8000 }
)
foreach ($p in $plan) {
    if (-not (Restart-Relay $p.gid)) { Mark "relay restart failed for $($p.type) - skip"; continue }
    Mark "collect $($p.type) (gid=$($p.gid), official per-type inference params) -> $($p.out)"
    & powershell -ExecutionPolicy Bypass -File "$base\run_collect3.ps1" `
        -Type $p.type -Keeps 16 -Chunks 2 -Out $p.out -SeedBase $p.seed -GarmentTex half
    $n = @(Get-ChildItem "$base\$($p.out)" -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'meta.json') }).Count
    Mark "$($p.type) done: $n episodes"
}

# ---- 3) restore the relay to the bootstrap default
Restart-Relay -1 | Out-Null
Mark "ALLTYPES-COLLECT-DONE"
