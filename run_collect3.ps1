# Cycle-3 collection: per-garment balanced keeps + widened randomization.
# Height +-10mm (per chunk), drop-z range, lighting, table texture always on.
# Garment texture: -GarmentTex off | on | half (half = only even chunks).
# Seen_8 included since 2026-09-05 (its 0% was a judge mapping bug, fixed in lehome_scene v3).
# ASCII only. Usage:
#   powershell -ExecutionPolicy Bypass -File run_collect3.ps1
#   powershell -ExecutionPolicy Bypass -File run_collect3.ps1 -Keeps 20 -GarmentTex half
param(
    [int]$Keeps = 20,          # target successful episodes per garment (total)
    [int]$Chunks = 2,          # processes per garment, each with its own robot z
    [int]$Steps = 600,
    [int]$Port = 8767,
    [string]$Type = "Top_Long",
    [string]$Out = "distill_data_r3",
    [string]$GarmentTex = "half",
    [int]$SeedBase = 500,      # change for a fresh batch (seeds = base+10*i+c)
    [string]$Only = "",        # regex: collect only matching garments
    [string]$DropRange = "0.545,0.63"
)

$py = "C:\isaacsim\python.bat"
$script = "C:\Users\H\Desktop\lehome-win\16_collect_distill.py"
$root = "C:\Users\H\Desktop\lehome-win\Assets\objects\Challenge_Garment\Release\$Type"

$garments = Get-ChildItem $root -Directory |
    Where-Object { $_.Name -match "_Seen_\d+$" } |
    Sort-Object Name
if ($Only -ne "") {
    $garments = $garments | Where-Object { $_.Name -match $Only }
}

$env:LEHOME_RAND_LIGHT = "1"
$env:LEHOME_DROP_Z_RANGE = $DropRange
$env:LEHOME_RAND_TABLE_TEX = "1"

$rand = New-Object System.Random(99)
$keepsPerChunk = [math]::Ceiling($Keeps / $Chunks)
Write-Host "===== CYCLE 3: $($garments.Count) garments x $Keeps keeps ($Chunks chunks of $keepsPerChunk, garment-tex $GarmentTex) -> $Out ====="
$i = 0
:outer foreach ($g in $garments) {
    $i++
    # resume support: skip a garment that already has enough episodes on disk
    $have = @(Get-ChildItem "C:\Users\H\Desktop\lehome-win\$Out" -Directory `
        -Filter "$($g.Name)_*" -ErrorAction SilentlyContinue).Count
    if ($have -ge $Keeps) {
        Write-Host "--- skip $($g.Name): already $have/$Keeps ---"
        continue
    }
    for ($c = 1; $c -le $Chunks; $c++) {
        # abort the whole run if the teacher relay died (unattended overnight)
        $alive = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port `
            -InformationLevel Quiet -WarningAction SilentlyContinue
        if (-not $alive) {
            Write-Host "!!! relay port $Port not responding - aborting run"
            break outer
        }
        # robot height uniform in [0.490, 0.510] per chunk process
        $z = 0.490 + 0.020 * $rand.NextDouble()
        $env:LEHOME_ROBOT_Z = ("{0:F4}" -f $z)
        $gt = "0"
        if ($GarmentTex -eq "on") { $gt = "1" }
        elseif ($GarmentTex -eq "half" -and ($c % 2 -eq 0)) { $gt = "1" }
        $env:LEHOME_RAND_GARMENT_TEX = $gt
        Write-Host "--- R3 [$i/$($garments.Count)] $($g.Name) chunk $c/$Chunks z=$($env:LEHOME_ROBOT_Z) gtex=$gt ---"
        # watchdog (paper section C): run the chunk with a hard 3h limit so a
        # hung/crashed sim cannot stall the whole overnight chain
        $chunkArgs = @($script, '--garment-dir', $g.Name, '--garment-type', $Type,
            '--target-keeps', $keepsPerChunk, '--steps', $Steps, '--port', $Port,
            '--seed', ($SeedBase + 10 * $i + $c), '--out', $Out,
            '--keep-fail', '--snapshot')
        $proc = Start-Process -FilePath $py -ArgumentList $chunkArgs `
            -NoNewWindow -PassThru
        if (-not $proc.WaitForExit(3 * 3600 * 1000)) {
            Write-Host "!!! chunk timeout (3h) - killing tree, moving on"
            taskkill /PID $proc.Id /T /F | Out-Null
            Start-Sleep -Seconds 15
        }
    }
}

# clean up: do not leak randomization env vars into the calling console
$env:LEHOME_ROBOT_Z = "0.5"
Remove-Item Env:LEHOME_DROP_Z_RANGE, Env:LEHOME_RAND_TABLE_TEX, `
    Env:LEHOME_RAND_GARMENT_TEX, Env:LEHOME_RAND_LIGHT -ErrorAction SilentlyContinue

Write-Host ""
$n = (Get-ChildItem "C:\Users\H\Desktop\lehome-win\$Out" -Directory -ErrorAction SilentlyContinue).Count
Write-Host "===== DONE: $Out total $n episodes ====="
