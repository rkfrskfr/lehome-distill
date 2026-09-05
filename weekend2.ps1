# Weekend chain v2 (audit-fixed). Stages:
#  A wait curation  B seed-variance  H chunk_size=30 horizon experiment
#  C recovery collection (robot_z-aware, per-episode picks)
#  D curated+recovery (only if >=20 recovery eps)  E low-res (server auto-resizes)
# Evals scrub randomization env vars. ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$train = "C:\Users\H\Desktop\lerobot\.venv\Scripts\lerobot-train.exe"
$py = "C:\isaacsim\python.bat"
$winpy = "C:\Users\H\AppData\Local\Microsoft\WindowsApps\python.exe"
$mark = "$base\weekend2_markers.log"

function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function Clear-RandEnv {
    foreach ($k in @("LEHOME_RAND_LIGHT","LEHOME_RAND_TABLE_TEX","LEHOME_RAND_GARMENT_TEX","LEHOME_RAND_CAM","LEHOME_RAND_PERSTEP","LEHOME_DROP_Z_RANGE","LEHOME_ROBOT_Z")) {
        Remove-Item "Env:$k" -ErrorAction SilentlyContinue
    }
}
function Stop-Student {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $t = 0; while ((PortUp 8766) -and $t -lt 30) { Start-Sleep -Seconds 2; $t++ }
}
function Start-Student([string]$ckpt, [string]$tag) {
    Stop-Student
    Start-Process -WindowStyle Hidden -FilePath $venv `
        -ArgumentList "$base\12_policy_server.py", $ckpt, "--n-action-steps", "5" `
        -RedirectStandardOutput "$base\server_$tag.log" -RedirectStandardError "$base\server_$tag.err.log" -WorkingDirectory $base
    $t = 0; while (-not (PortUp 8766) -and $t -lt 60) { Start-Sleep -Seconds 3; $t++ }
    return (PortUp 8766)
}
function Ensure-Teacher {
    if (-not (PortUp 8000)) {
        Mark "teacher down - restarting WSL server"
        Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '15_winner_relay' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        wsl -d Ubuntu-24.04 -- bash -c "cd /root/lehome_winner/lehome_solution && setsid nohup /root/.local/bin/uv run python scripts/serve.py --port 8000 --num_rollout_candidates 4 policy:checkpoint --policy.config pi_modified_bc_rl --policy.dir /root/lehome_winner/checkpoints/lehome_sim > /tmp/wsrv.log 2>&1 < /dev/null & sleep 110; echo started"
    }
    if (-not (PortUp 8767)) {
        Mark "relay down - restarting"
        Start-Process -WindowStyle Hidden -FilePath $winpy -ArgumentList "$base\15_winner_relay.py" `
            -RedirectStandardOutput "$base\relay_weekend2.log" -RedirectStandardError "$base\relay_weekend2.err.log" -WorkingDirectory $base
        Start-Sleep -Seconds 20
    }
    return ((PortUp 8000) -and (PortUp 8767))
}
function Full-Eval([string]$ckpt, [string]$tag) {
    Clear-RandEnv
    if (-not (Start-Student $ckpt $tag)) { Mark "server failed for $tag"; return }
    if (Test-Path "$base\bench_$tag.csv") { Remove-Item "$base\bench_$tag.csv" -Force }
    & powershell -ExecutionPolicy Bypass -File "$base\run_full_bench.ps1" -Episodes 10 -Tag $tag -Port 8766 -PhysPerAction 2
    # top-up only the per-garment deficit (PhysX flake) so the denominator stays 120
    $rows = @{}
    if (Test-Path "$base\bench_$tag.csv") { Import-Csv "$base\bench_$tag.csv" | ForEach-Object { $rows[$_.garment] = [int]$rows[$_.garment] + 1 } }
    $all = Get-ChildItem "$base\Assets\objects\Challenge_Garment\Release\Top_Long" -Directory |
        Where-Object { $_.Name -match "_(Seen|Unseen)_\d+$" } | Sort-Object Name
    $i = 0
    foreach ($gd in $all) {
        $i++
        $need = 10 - [int]$rows[$gd.Name]
        if ($need -gt 0) {
            if (-not (PortUp 8766)) { Start-Student $ckpt $tag | Out-Null }
            & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes $need --steps 600 `
                --port 8766 --tag $tag --seed (140 + $i) --reset-mode initial --phys-per-action 2
        }
    }
    Stop-Student
}
function Train-Std([string]$repo, [string]$root, [string]$out, [int]$seed, [int]$steps, [string[]]$extra) {
    $a = @("--dataset.repo_id=$repo", "--dataset.root=$root", "--policy.type=act", "--output_dir=$out",
        "--steps=$steps", "--batch_size=16", "--num_workers=4", "--seed=$seed", "--save_freq=20000",
        "--wandb.enable=false", "--policy.push_to_hub=false",
        "--dataset.image_transforms.enable=true", "--dataset.image_transforms.max_num_transforms=3")
    if ($extra) { $a += $extra }
    & $train $a *>> "$base\train_$(Split-Path $out -Leaf).log"
}

# ---------------- A: wait for curation chain (with process-alive fallback)
Mark "A wait curation"
while (-not (Select-String -Path "$base\curation_chain.log" -Pattern "CURATION-DONE|FAILED" -Quiet -ErrorAction SilentlyContinue)) {
    $alive = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'curation\.ps1' }
    if (-not $alive) { Mark "A curation process gone - proceeding"; break }
    Start-Sleep -Seconds 300
}
Mark "A curation finished"

# ---------------- B: seed-variance run of the champion recipe
Mark "B train seed2"
Train-Std "hd/lehome_distill_r3plus" "$base\distill_lerobot_r3plus" "$base\outputs\act_student_seed2" 2000 60000 @()
$ck = "$base\outputs\act_student_seed2\checkpoints\060000\pretrained_model"
if (Test-Path $ck) { Mark "B eval seed2"; Full-Eval $ck "seed2_n5"; Mark "B done" } else { Mark "B TRAIN FAILED" }

# ---------------- H: horizon-match experiment (chunk_size 30)
Mark "H train chunk30"
Train-Std "hd/lehome_distill_r3plus" "$base\distill_lerobot_r3plus" "$base\outputs\act_student_chunk30" 1000 60000 @("--policy.chunk_size=30", "--policy.n_action_steps=5")
$ck = "$base\outputs\act_student_chunk30\checkpoints\060000\pretrained_model"
if (Test-Path $ck) { Mark "H eval chunk30"; Full-Eval $ck "chunk30_n5"; Mark "H done" } else { Mark "H TRAIN FAILED" }

# ---------------- C: recovery-data collection (teacher retries from failure snapshots)
Mark "C recovery collection"
$garments = @("Top_Long_Seen_0","Top_Long_Seen_3","Top_Long_Seen_7","Top_Long_Seen_1","Top_Long_Seen_5","Top_Long_Seen_6","Top_Long_Seen_4","Top_Long_Seen_2")
$i = 0
foreach ($gname in $garments) {
    $i++
    if (-not (Ensure-Teacher)) { Mark "C teacher unavailable - skip $gname"; continue }
    Clear-RandEnv
    $env:LEHOME_RAND_LIGHT = "1"; $env:LEHOME_RAND_TABLE_TEX = "1"
    $p = Start-Process -FilePath $py -ArgumentList "$base\22_replay_snapshots.py","--src","distill_data_r4_fail","--out","distill_data_recov","--mode","recover","--garment-dir",$gname,"--per-snap","2","--max-snaps","12","--port","8767","--seed",(3000+$i) `
        -NoNewWindow -PassThru -RedirectStandardOutput "$base\recov_$gname.log" -RedirectStandardError "$base\recov_$gname.err.log" -WorkingDirectory $base
    if (-not $p.WaitForExit(55 * 60 * 1000)) { taskkill /PID $p.Id /T /F | Out-Null; Mark "C timeout $gname" }
    Clear-RandEnv
}
$nrec = @(Get-ChildItem "$base\distill_data_recov" -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'meta.json') }).Count
Mark "C done - recovery episodes: $nrec"

# ---------------- D: curated + recovery training (only if recovery data is meaningful)
if ($nrec -ge 20) {
    Mark "D build cur2"
    $dst = "$base\distill_data_cur2"
    Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force $dst | Out-Null
    foreach ($src in 'distill_data_rand','distill_data_r3','distill_data_r4','distill_data_recov') {
        foreach ($d in Get-ChildItem "$base\$src" -Directory -ErrorAction SilentlyContinue) {
            if (Test-Path (Join-Path $d.FullName 'meta.json')) { New-Item -ItemType Junction -Path (Join-Path $dst "$($src)__$($d.Name)") -Target $d.FullName | Out-Null }
        }
    }
    & $venv "$base\17_convert_distill.py" --src distill_data_cur2 --dst distill_lerobot_cur2 --repo-id hd/lehome_cur2 *>> "$base\convert_cur2.log"
    Mark "D train cur2"
    Train-Std "hd/lehome_cur2" "$base\distill_lerobot_cur2" "$base\outputs\act_student_cur2" 1000 60000 @()
    $ck = "$base\outputs\act_student_cur2\checkpoints\060000\pretrained_model"
    if (Test-Path $ck) { Mark "D eval cur2"; Full-Eval $ck "cur2_n5"; Mark "D done" } else { Mark "D TRAIN FAILED" }
} else { Mark "D skipped (recovery eps $nrec < 20)" }

# ---------------- E: low-res (240x320) on curated data; server resizes obs automatically
Mark "E convert cur240"
& $venv "$base\17_convert_distill.py" --src distill_data_cur --dst distill_lerobot_cur240 --repo-id hd/lehome_cur240 --resize 240x320 *>> "$base\convert_cur240.log"
Mark "E train cur240"
Train-Std "hd/lehome_cur240" "$base\distill_lerobot_cur240" "$base\outputs\act_student_cur240" 1000 60000 @()
$ck = "$base\outputs\act_student_cur240\checkpoints\060000\pretrained_model"
if (Test-Path $ck) { Mark "E eval cur240"; Full-Eval $ck "cur240_n5"; Mark "E done" } else { Mark "E TRAIN FAILED" }

Mark "WEEKEND2-DONE"
