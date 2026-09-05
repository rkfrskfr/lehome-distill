# Teacher (pi0.5 via relay :8767) re-evaluation under the corrected success judge (v3, 2026-09-05).
# Same protocol as the student evals: 12 garments x 10 eps, 600 steps, phys-per-action 2, seeds 301..312.
$base = "C:\Users\H\Desktop\lehome-win"
$py = "C:\isaacsim\python.bat"
$port = 8767
$tag = "teacher_v3"
$mark = "$base\teacher_eval_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
Mark "teacher eval start (judge v3)"
if (-not (PortUp $port)) { Mark "relay 8767 down - abort"; exit 1 }
if (Test-Path "$base\bench_$tag.csv") { Remove-Item "$base\bench_$tag.csv" -Force }
$all = Get-ChildItem "$base\Assets\objects\Challenge_Garment\Release\Top_Long" -Directory |
    Where-Object { $_.Name -match "_(Seen|Unseen)_\d+$" } | Sort-Object Name
$i = 0
foreach ($gd in $all) {
    $i++
    & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes 10 --steps 600 `
        --port $port --tag $tag --seed (300 + $i) --reset-mode initial --phys-per-action 1
}
$rows = @{}
if (Test-Path "$base\bench_$tag.csv") { Import-Csv "$base\bench_$tag.csv" | ForEach-Object { $rows[$_.garment] = [int]$rows[$_.garment] + 1 } }
$i = 0
foreach ($gd in $all) {
    $i++
    $need = 10 - [int]$rows[$gd.Name]
    if ($need -gt 0 -and (PortUp $port)) {
        & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes $need --steps 600 `
            --port $port --tag $tag --seed (350 + $i) --reset-mode initial --phys-per-action 1
    }
}
Mark "TEACHER-EVAL-DONE"
