# Eval-only ablations on a separate port (8768) so they can run alongside training
# and never collide with the curation/weekend chains on 8766. ASCII only.
#  1) augmentation ablation: act_student_r3plus (aug OFF, same 267 eps) at n5, seeds 1..12 (same as champion)
#  2) champion replicate with disjoint seeds (eval-noise estimate)
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$py = "C:\isaacsim\python.bat"
$port = 8768
$mark = "$base\ablation_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function Stop-Srv {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' -and $_.CommandLine -match "--port $port" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $t = 0; while ((PortUp $port) -and $t -lt 30) { Start-Sleep -Seconds 2; $t++ }
}
function Start-Srv([string]$ckpt, [string]$tag) {
    Stop-Srv
    Start-Process -WindowStyle Hidden -FilePath $venv `
        -ArgumentList "$base\12_policy_server.py", $ckpt, "--n-action-steps", "5", "--port", "$port" `
        -RedirectStandardOutput "$base\server_$tag.log" -RedirectStandardError "$base\server_$tag.err.log" -WorkingDirectory $base
    $t = 0; while (-not (PortUp $port) -and $t -lt 60) { Start-Sleep -Seconds 3; $t++ }
    return (PortUp $port)
}
function Eval-All([string]$ckpt, [string]$tag, [int]$seedBase) {
    if (-not (Start-Srv $ckpt $tag)) { Mark "server failed $tag"; return }
    if (Test-Path "$base\bench_$tag.csv") { Remove-Item "$base\bench_$tag.csv" -Force }
    $all = Get-ChildItem "$base\Assets\objects\Challenge_Garment\Release\Top_Long" -Directory |
        Where-Object { $_.Name -match "_(Seen|Unseen)_\d+$" } | Sort-Object Name
    $i = 0
    foreach ($gd in $all) {
        $i++
        & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes 10 --steps 600 `
            --port $port --tag $tag --seed ($seedBase + $i) --reset-mode initial --phys-per-action 2
    }
    # deficit top-up (PhysX flake)
    $rows = @{}
    if (Test-Path "$base\bench_$tag.csv") { Import-Csv "$base\bench_$tag.csv" | ForEach-Object { $rows[$_.garment] = [int]$rows[$_.garment] + 1 } }
    $i = 0
    foreach ($gd in $all) {
        $i++
        $need = 10 - [int]$rows[$gd.Name]
        if ($need -gt 0) {
            if (-not (PortUp $port)) { Start-Srv $ckpt $tag | Out-Null }
            & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes $need --steps 600 `
                --port $port --tag $tag --seed ($seedBase + 50 + $i) --reset-mode initial --phys-per-action 2
        }
    }
    Stop-Srv
}

Mark "1 noaug ablation (seeds 1..12)"
Eval-All "$base\outputs\act_student_r3plus\checkpoints\060000\pretrained_model" "noaug_full_n5" 0
Mark "2 champion replicate (seeds 201..212)"
Eval-All "$base\outputs\act_student_r3plus_aug\checkpoints\060000\pretrained_model" "final_n5_rep" 200
Mark "ABLATION-DONE"
