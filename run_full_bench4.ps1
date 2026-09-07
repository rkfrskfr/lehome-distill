# Full four-garment-type evaluation: the competition scores the average over
# Top_Long / Top_Short / Pant_Long / Pant_Short, so this is the number that is
# comparable to the official leaderboard (the winner scored 79.63% overall).
# 4 types x 12 garments x N episodes. ASCII only.
#   powershell -ExecutionPolicy Bypass -File run_full_bench4.ps1 -Tag combo4_n5 -Port 8768 -Episodes 10
param(
    [string]$Tag = "eval4",
    [int]$Port = 8766,
    [int]$Episodes = 10,
    [int]$Steps = 600,
    [int]$PhysPerAction = 2,
    [int]$SeedBase = 900,
    [string]$Types = "Top_Long,Top_Short,Pant_Long,Pant_Short"
)
$base = "C:\Users\H\Desktop\lehome-win"
$py = "C:\isaacsim\python.bat"
$root = "$base\Assets\objects\Challenge_Garment\Release"

# a stale randomization env var silently changes the physics of an evaluation
foreach ($k in @("LEHOME_RAND_LIGHT","LEHOME_RAND_TABLE_TEX","LEHOME_RAND_GARMENT_TEX",
                 "LEHOME_RAND_CAM","LEHOME_RAND_PERSTEP","LEHOME_DROP_Z_RANGE",
                 "LEHOME_DROP_Z","LEHOME_ROBOT_Z")) {
    Remove-Item "Env:$k" -ErrorAction SilentlyContinue
}
if (Test-Path "$base\bench_$Tag.csv") { Remove-Item "$base\bench_$Tag.csv" -Force }

$i = 0
foreach ($t in $Types.Split(",")) {
    $dirs = Get-ChildItem "$root\$t" -Directory | Where-Object { $_.Name -match "_(Seen|Unseen)_\d+$" } | Sort-Object Name
    Write-Host "=== $t : $($dirs.Count) garments x $Episodes ==="
    foreach ($gd in $dirs) {
        $i++
        & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type $t `
            --episodes $Episodes --steps $Steps --port $Port --tag $Tag `
            --seed ($SeedBase + $i) --reset-mode initial --phys-per-action $PhysPerAction
    }
}

# top up whatever PhysX flakes dropped, so every garment has the same denominator
$rows = @{}
if (Test-Path "$base\bench_$Tag.csv") { Import-Csv "$base\bench_$Tag.csv" | ForEach-Object { $rows[$_.garment] = [int]$rows[$_.garment] + 1 } }
$i = 0
foreach ($t in $Types.Split(",")) {
    $dirs = Get-ChildItem "$root\$t" -Directory | Where-Object { $_.Name -match "_(Seen|Unseen)_\d+$" } | Sort-Object Name
    foreach ($gd in $dirs) {
        $i++
        $need = $Episodes - [int]$rows[$gd.Name]
        if ($need -gt 0) {
            Write-Host "--- top up $($gd.Name): $need"
            & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type $t `
                --episodes $need --steps $Steps --port $Port --tag $Tag `
                --seed ($SeedBase + 500 + $i) --reset-mode initial --phys-per-action $PhysPerAction
        }
    }
}
Write-Host "===== done: bench_$Tag.csv ====="
