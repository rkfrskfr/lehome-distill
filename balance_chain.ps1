# Balance the four-type dataset (2026-09-08). The first pass collected only 16 keeps per garment
# for the three new types while Top_Long carries 914 episodes from the whole project — a 6:1
# imbalance that would make the "four-type average" mostly a Top_Long score.
# This tops the three new types up to 48 keeps per garment (about 480 per type), which is the
# range where Top_Long's returns started to flatten (267 -> 505 -> 674 gave 58 -> 73 -> 77%).
#
# run_collect3.ps1 skips a garment that already has enough episodes on disk, so this only collects
# the shortfall. Seeds are disjoint from the first pass.
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$winpy = "C:\Users\H\AppData\Local\Microsoft\WindowsApps\python.exe"
$mark = "$base\balance_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function MarkerDone([string]$f, [string]$p) { return (Test-Path $f) -and (Select-String -Path $f -Pattern $p -Quiet) }
function Restart-Relay([int]$gid) {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '15_winner_relay' -and $_.CommandLine -notmatch 'Win32_Process' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 5
    $a = @("$base\15_winner_relay.py")
    if ($gid -ge 0) { $a += @("--garment-id", "$gid", "--full-cfg") }
    Start-Process -WindowStyle Hidden -FilePath $winpy -ArgumentList $a `
        -RedirectStandardOutput "$base\relay_bal$gid.log" -RedirectStandardError "$base\relay_bal$gid.err.log" -WorkingDirectory $base
    $t = 0; while (-not (PortUp 8767) -and $t -lt 40) { Start-Sleep -Seconds 3; $t++ }
    return (PortUp 8767)
}

Mark "balance armed - waiting for the first four-type pass to finish"
$t = 0
while ($t -lt 900) {
    if (MarkerDone "$base\alltypes_markers.log" 'ALLTYPES-COLLECT-DONE') { break }
    $alive = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'alltypes_chain\.ps1' -and $_.CommandLine -notmatch 'Win32_Process' }
    if (-not $alive) { Mark "alltypes_chain gone - proceeding"; break }
    Start-Sleep -Seconds 60; $t++
}
if (-not (PortUp 8000)) { Mark "teacher 8000 down - abort"; exit 1 }

# two rounds of 3 garments so each type grows together; if the run is cut short the set stays balanced
$rounds = @(
    @{ keeps = 32; seed = 20000 },
    @{ keeps = 48; seed = 30000 }
)
$plan = @(
    @{ type = "Top_Short";  gid = 1; out = "distill_data_top_short" },
    @{ type = "Pant_Long";  gid = 2; out = "distill_data_pant_long" },
    @{ type = "Pant_Short"; gid = 3; out = "distill_data_pant_short" }
)
foreach ($r in $rounds) {
    foreach ($p in $plan) {
        $have = @(Get-ChildItem "$base\$($p.out)" -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'meta.json') }).Count
        Mark "round $($r.keeps)/garment : $($p.type) has $have"
        if (-not (Restart-Relay $p.gid)) { Mark "relay restart failed for $($p.type) - skip"; continue }
        & powershell -ExecutionPolicy Bypass -File "$base\run_collect3.ps1" `
            -Type $p.type -Keeps $r.keeps -Chunks 2 -Out $p.out -SeedBase ($r.seed + $p.gid * 100) -GarmentTex half
        $now = @(Get-ChildItem "$base\$($p.out)" -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'meta.json') }).Count
        Mark "  $($p.type) -> $now"
    }
    Mark "ROUND-$($r.keeps)-DONE"
}
Restart-Relay -1 | Out-Null
Mark "BALANCE-DONE"
