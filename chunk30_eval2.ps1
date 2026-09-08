# Evaluate the chunk_size=30 student (trained 09-07 19:23) on Top_Long, so it is directly
# comparable to act_student_combo (77.1%, chunk 100). Own port so it never touches the
# collection running on the relay. ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$port = 8793
$tag  = "combo30b_n5"
$ck   = "$base\outputs\act_student_combo30\checkpoints\060000\pretrained_model"
$mark = "$base\chunk30b_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
if (-not (Test-Path $ck)) { Mark "checkpoint missing"; exit 1 }
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' -and $_.CommandLine -match "--port $port" -and $_.CommandLine -notmatch 'Win32_Process' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -WindowStyle Hidden -FilePath $venv `
    -ArgumentList "$base\12_policy_server.py", $ck, "--n-action-steps", "5", "--port", "$port" `
    -RedirectStandardOutput "$base\server_$tag.log" -RedirectStandardError "$base\server_$tag.err.log" -WorkingDirectory $base
$t = 0; while (-not (PortUp $port) -and $t -lt 60) { Start-Sleep -Seconds 3; $t++ }
if (-not (PortUp $port)) { Mark "server failed"; exit 1 }
Mark "eval $tag (chunk 30 vs chunk 100 baseline 77.1%)"
& powershell -ExecutionPolicy Bypass -File "$base\run_full_bench4.ps1" -Tag $tag -Port $port -Episodes 10 -SeedBase 1400 -Types "Top_Long"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' -and $_.CommandLine -match "--port $port" -and $_.CommandLine -notmatch 'Win32_Process' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Mark "CHUNK30-EVAL-DONE"
