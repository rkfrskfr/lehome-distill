# Package everything the OTHER computer (laptop with the real SO-101) needs, into one folder.
# The folder can be zipped or copied to a USB stick. Isaac Sim is NOT needed on that machine.
#   powershell -ExecutionPolicy Bypass -File make_portable.ps1                 -> .\lehome_portable
#   powershell -ExecutionPolicy Bypass -File make_portable.ps1 -Out E:\lehome  -> that folder
# ASCII only.
param(
    [string]$Out = "C:\Users\H\Desktop\lehome_portable",
    [string]$Ckpt = "C:\Users\H\Desktop\lehome-win\outputs\act_student_combo\checkpoints\060000\pretrained_model"
)
$base = "C:\Users\H\Desktop\lehome-win"

if (-not (Test-Path $Ckpt)) { Write-Host "!! checkpoint not found: $Ckpt"; exit 1 }
New-Item -ItemType Directory -Force $Out | Out-Null
New-Item -ItemType Directory -Force "$Out\model" | Out-Null

# 1) scripts + docs
foreach ($f in "12_policy_server.py", "31_real_robot_bridge.py", "REAL_ROBOT_RUNBOOK.md", "LAPTOP_SETUP.md") {
    if (Test-Path "$base\$f") { Copy-Item "$base\$f" "$Out\$f" -Force; Write-Host "copied $f" }
}

# 2) trained model (about 200 MB; normalization statistics are inside, no dataset needed)
Copy-Item "$Ckpt\*" "$Out\model" -Recurse -Force
$mb = [math]::Round(((Get-ChildItem "$Out\model" -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "copied model ($mb MB)"

# 3) torchvision resnet18 weights: the policy builds its vision backbone at load time and would
#    otherwise download 45 MB from download.pytorch.org on first run (HF_HUB_OFFLINE does not stop it).
$hub = "$env:USERPROFILE\.cache\torch\hub\checkpoints\resnet18-f37072fd.pth"
if (Test-Path $hub) {
    New-Item -ItemType Directory -Force "$Out\torch_hub" | Out-Null
    Copy-Item $hub "$Out\torch_hub" -Force
    Write-Host "copied resnet18 weights -> put them in %USERPROFILE%\.cache\torch\hub\checkpoints\ on the laptop"
} else {
    Write-Host "!! resnet18-f37072fd.pth not found in the torch cache; the laptop will download it (needs internet once)"
}

# 4) calibration files, if this machine already has them (optional; the laptop can redo calibration)
$calSrc = "$env:USERPROFILE\.cache\huggingface\lerobot\calibration\robots\so_follower"
if (Test-Path $calSrc) {
    New-Item -ItemType Directory -Force "$Out\calibration" | Out-Null
    Copy-Item "$calSrc\*.json" "$Out\calibration" -Force -ErrorAction SilentlyContinue
    Write-Host "copied calibration json files FOR REFERENCE ONLY."
    Write-Host "  !! do NOT rename them to lehome_bi_left/right.json unless you are certain which"
    Write-Host "     physical arm each one belongs to - a wrong file gives silently wrong angles."
    Write-Host "     Re-calibrating on the laptop is the safe path (see REAL_ROBOT_RUNBOOK.md step 3)."
}

# 5) install list for the laptop
@'
# Laptop install (Python 3.12+, no GPU needed)
#   py -3.12 -m venv .venv
#   .venv\Scripts\activate
#   pip install -r requirements-laptop.txt
# CPU-only torch (smaller download, no CUDA):
#   pip install torch --index-url https://download.pytorch.org/whl/cpu
lerobot[feetech]==0.6.1
opencv-python==4.13.0.92
numpy==2.2.6
pyserial==3.5
'@ | Set-Content -Encoding ascii "$Out\requirements-laptop.txt"

# 6) ready-to-edit launch commands
@'
:: 1) model server (this window stays open). Add --host 0.0.0.0 only for split deployment.
python 12_policy_server.py model --n-action-steps 5 --device cpu

:: 2) protocol check without the robot
python 31_real_robot_bridge.py --selftest

:: 3) arms  (replace COM5/COM6 with the ports from lerobot-find-port)
python 31_real_robot_bridge.py --check --left COM5 --right COM6
python 31_real_robot_bridge.py --home  --left COM5 --right COM6

:: 4) closed loop: print only, then for real
python 31_real_robot_bridge.py --run --left COM5 --right COM6 --cams 0,1,2
python 31_real_robot_bridge.py --run --left COM5 --right COM6 --cams 0,1,2 --live
'@ | Set-Content -Encoding ascii "$Out\COMMANDS.txt"

Write-Host ""
Write-Host "===== ready: $Out ====="
Write-Host "copy the whole folder to the laptop, then follow LAPTOP_SETUP.md"
