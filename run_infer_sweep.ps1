# Inference-setting sweep (paper section 7): the same checkpoint can score very
# differently depending on how the action chunk is consumed.
# Configs: chunk length (n_action_steps), temporal ensemble, consensus-of-N,
# plus the no-aug baseline for the augmentation A/B.
# ASCII only.
param(
    [int]$Episodes = 8,
    [string[]]$Garments = @("Top_Long_Seen_2", "Top_Long_Seen_5",
                            "Top_Long_Seen_9", "Top_Long_Unseen_0")
)

$py = "C:\isaacsim\python.bat"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$base = "C:\Users\H\Desktop\lehome-win"
$aug = "$base\outputs\act_student_r3plus_aug\checkpoints\060000\pretrained_model"
$noaug = "$base\outputs\act_student_r3plus\checkpoints\060000\pretrained_model"

# tag | checkpoint | extra server args
$configs = @(
    @("noaug_n100", $noaug, @()),
    @("aug_n100", $aug, @()),
    @("aug_n20", $aug, @("--n-action-steps", "20")),
    @("aug_n5", $aug, @("--n-action-steps", "5")),
    @("aug_ens", $aug, @("--ensemble", "0.01")),
    @("aug_n5_cons3", $aug, @("--n-action-steps", "5", "--consensus", "3"))
)

function Stop-Student {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match '12_policy_server' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 5
}

foreach ($cfg in $configs) {
    $tag = $cfg[0]; $ckpt = $cfg[1]; $extra = $cfg[2]
    Write-Host ""
    Write-Host "=============== $tag ==============="
    $csv = "$base\bench_$tag.csv"
    if (Test-Path $csv) { Remove-Item $csv -Force }

    Stop-Student
    $srvArgs = @("$base\12_policy_server.py", $ckpt) + $extra
    Start-Process -WindowStyle Hidden -FilePath $venv -ArgumentList $srvArgs `
        -RedirectStandardOutput "$base\sweep_server_$tag.log" `
        -RedirectStandardError "$base\sweep_server_$tag.err.log" `
        -WorkingDirectory $base
    Start-Sleep -Seconds 45
    $up = (Test-NetConnection -ComputerName 127.0.0.1 -Port 8766 `
        -InformationLevel Quiet -WarningAction SilentlyContinue)
    Write-Host "server up: $up"
    if (-not $up) { Write-Host "SKIP $tag (server failed)"; continue }

    $i = 0
    foreach ($g in $Garments) {
        $i++
        & $py "$base\14_benchmark.py" --garment-dir $g --garment-type Top_Long `
            --episodes $Episodes --steps 600 --port 8766 --tag $tag `
            --seed $i --reset-mode initial --phys-per-action 2
    }
}
Stop-Student
Write-Host ""
Write-Host "===== SWEEP DONE ====="
