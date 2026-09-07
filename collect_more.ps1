# Extra Top_Long collection on the corrected environment (judge v3 + true rest pose).
# Pushes the proven lever: 674 demos -> ~900. Seeds 5000+ so nothing collides with distill_data_fix.
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$mark = "$base\collect_more_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
if (-not (PortUp 8767)) { Mark "relay 8767 down - abort"; exit 1 }
Mark "collect Top_Long +24/garment -> distill_data_fix2 (seeds 5000+)"
& powershell -ExecutionPolicy Bypass -File "$base\run_collect3.ps1" -Keeps 24 -Chunks 2 -Out distill_data_fix2 -SeedBase 5000 -GarmentTex half
$n = @(Get-ChildItem "$base\distill_data_fix2" -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'meta.json') }).Count
Mark "COLLECT-MORE-DONE keeps=$n"
