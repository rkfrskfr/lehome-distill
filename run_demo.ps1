# Live folding demo: best student model, rotating high-success garments.
# Runs forever until Ctrl+C (or closing this terminal). ASCII only.
#   powershell -ExecutionPolicy Bypass -File run_demo.ps1                 (auto-picks the checkpoint)
#   powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Ckpt <path>    (explicit checkpoint)
param([string]$Ckpt = "")
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$py = "C:\isaacsim\python.bat"

# Checkpoint: best small model under the corrected environment (2026-09-07):
#   act_student_combo (674 eps) 76.7%  >  act_student_cur (505 eps) 73.3% (n=240)  >  r3plus_aug (267 eps) 58.3%
$bestCk = "$base\outputs\act_student_combo\checkpoints\060000\pretrained_model"
$secondCk = "$base\outputs\act_student_cur\checkpoints\060000\pretrained_model"
$oldCk = "$base\outputs\act_student_r3plus_aug\checkpoints\060000\pretrained_model"
if ($Ckpt -ne "") { $ckpt = $Ckpt } elseif (Test-Path $bestCk) { $ckpt = $bestCk } elseif (Test-Path $secondCk) { $ckpt = $secondCk } else { $ckpt = $oldCk }
Write-Host "checkpoint: $ckpt"

# refuse to start while training / an automated evaluation or collection is using the GPU
$tr = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'lerobot-train' -and $_.CommandLine -notmatch 'Win32_Process' }
if ($tr) { Write-Host "!! training is still running - stop it first"; exit 1 }
$busy = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'kit.exe' -and $_.CommandLine -match '(14_benchmark|16_collect_distill|22_replay_snapshots)' }
if ($busy) { Write-Host "!! an automated evaluation/collection is running (kit.exe) - wait for it or stop the chain first"; exit 1 }

# (re)start the model server on port 8766 with 5-step replanning (chain servers on other ports are left alone)
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' -and $_.CommandLine -notmatch '--port' -and $_.CommandLine -notmatch 'Win32_Process' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 4
Start-Process -WindowStyle Hidden -FilePath $venv `
    -ArgumentList "$base\12_policy_server.py", $ckpt, "--n-action-steps", "5" `
    -RedirectStandardOutput "$base\demo_server.log" `
    -RedirectStandardError "$base\demo_server.err.log" -WorkingDirectory $base
Write-Host "model server starting (about 40s)..."
Start-Sleep -Seconds 40

# rotate garments forever (Ctrl+C to stop). act_student_combo: Seen_4 10/10, Seen_1/Seen_8 9/10, Unseen_1 8/10.
$garments = @("Top_Long_Seen_4", "Top_Long_Seen_1", "Top_Long_Seen_8", "Top_Long_Unseen_1", "Top_Long_Seen_5")
while ($true) {
    foreach ($g in $garments) {
        Write-Host ""
        Write-Host ">>> $g (3 episodes)" -ForegroundColor Cyan
        & $py "$base\30_demo.py" --garment-dir $g --episodes 3 --port 8766
    }
}
