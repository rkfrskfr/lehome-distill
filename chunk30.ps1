# Horizon-match experiment: retrain the champion recipe with chunk_size=30
# (paper H=30) instead of 100, then eval executing 5 steps per replan.
# Usage: run after GPU is free. ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$train = "C:\Users\H\Desktop\lerobot\.venv\Scripts\lerobot-train.exe"
$py = "C:\isaacsim\python.bat"
$mark = "$base\chunk30_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }

Mark "train chunk30"
& $train "--dataset.repo_id=hd/lehome_distill_r3plus" "--dataset.root=$base\distill_lerobot_r3plus" `
    "--policy.type=act" "--output_dir=$base\outputs\act_student_chunk30" `
    "--policy.chunk_size=30" "--policy.n_action_steps=5" `
    "--steps=60000" "--batch_size=16" "--num_workers=4" "--seed=1000" "--save_freq=20000" `
    "--wandb.enable=false" "--policy.push_to_hub=false" `
    "--dataset.image_transforms.enable=true" "--dataset.image_transforms.max_num_transforms=3" `
    *>> "$base\train_chunk30.log"
$ck = "$base\outputs\act_student_chunk30\checkpoints\060000\pretrained_model"
if (-not (Test-Path $ck)) { Mark "TRAIN FAILED"; exit 1 }

Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 5
Start-Process -WindowStyle Hidden -FilePath $venv `
    -ArgumentList "$base\12_policy_server.py", $ck, "--n-action-steps", "5" `
    -RedirectStandardOutput "$base\server_chunk30.log" -RedirectStandardError "$base\server_chunk30.err.log" -WorkingDirectory $base
Start-Sleep -Seconds 45
Mark "eval chunk30_n5"
if (Test-Path "$base\bench_chunk30_n5.csv") { Remove-Item "$base\bench_chunk30_n5.csv" -Force }
& powershell -ExecutionPolicy Bypass -File "$base\run_full_bench.ps1" -Episodes 10 -Tag "chunk30_n5" -Port 8766 -PhysPerAction 2
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Mark "CHUNK30-DONE"
