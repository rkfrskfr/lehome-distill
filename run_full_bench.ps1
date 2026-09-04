# Large-scale benchmark: all garments of a type x N episodes.
# ASCII only -- Windows PowerShell 5.1 misreads UTF-8 script files.
# Usage: powershell -ExecutionPolicy Bypass -File run_full_bench.ps1 -Episodes 10 -Tag full
param(
    [int]$Episodes = 10,
    [string]$Tag = "full",
    [int]$Steps = 600,
    [int]$Port = 8767,
    [string]$Type = "Top_Long",
    [int]$PhysPerAction = 1
)

$py = "C:\isaacsim\python.bat"
$script = "C:\Users\H\Desktop\lehome-win\14_benchmark.py"
$root = "C:\Users\H\Desktop\lehome-win\Assets\objects\Challenge_Garment\Release\$Type"

$garments = Get-ChildItem $root -Directory |
    Where-Object { $_.Name -match "_(Seen|Unseen)_\d+$" } | Sort-Object Name
Write-Host "Garments: $($garments.Count) x $Episodes eps = $($garments.Count * $Episodes) episodes"

$i = 0
foreach ($g in $garments) {
    $i++
    Write-Host ""
    Write-Host "===== [$i/$($garments.Count)] $($g.Name) ====="
    & $py $script --garment-dir $g.Name --garment-type $Type --episodes $Episodes `
        --steps $Steps --port $Port --tag $Tag --seed $i --reset-mode initial `
        --phys-per-action $PhysPerAction
}

Write-Host ""
Write-Host "===== DONE: bench_$Tag.csv ====="
