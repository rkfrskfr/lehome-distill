# chunk_size 30 experiment: the student predicts a 100-step (3.3 s) chunk but only ever executes 5.
# The training loss is therefore spread across 95 steps that are never used. Shrinking the chunk to
# 30 concentrates capacity on the steps that matter. Trains on the current best dataset (combo, 674 eps)
# so the only change vs act_student_combo (77.1%) is the chunk length.
# Runs while collection is on the relay: training + one Isaac process fits in 32 GB.
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$train = "C:\Users\H\Desktop\lerobot\.venv\Scripts\lerobot-train.exe"
$mark = "$base\chunk30_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
Mark "train act_student_combo30 (chunk_size=30, n_action_steps=5)"
$a = @("--dataset.repo_id=hd/lehome_combo", "--dataset.root=$base\distill_lerobot_combo",
    "--policy.type=act", "--output_dir=$base\outputs\act_student_combo30",
    "--steps=60000", "--batch_size=16", "--num_workers=4", "--seed=1000", "--save_freq=20000",
    "--wandb.enable=false", "--policy.push_to_hub=false",
    "--dataset.image_transforms.enable=true", "--dataset.image_transforms.max_num_transforms=3",
    "--policy.chunk_size=30", "--policy.n_action_steps=5")
& $train $a *>> "$base\train_act_student_combo30.log"
if (Test-Path "$base\outputs\act_student_combo30\checkpoints\060000\pretrained_model") {
    Mark "CHUNK30-TRAIN-DONE"
} else { Mark "CHUNK30-TRAIN-FAILED" }
