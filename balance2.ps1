# Bring every garment of all four types to 100 successful demonstrations (10 garments x 4 types
# = 4000 episodes). Runs two collection streams in parallel on two relays; the teacher server
# batches their requests together on the GPU.
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$mark = "$base\balance_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }

Mark "=== balance to 100/garment, two parallel streams ==="
$a = Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList '-ExecutionPolicy','Bypass','-File',"$base\balance_worker.ps1",'-TcpPort','8767','-Only','_Seen_[0-4]$','-Session','A','-Keeps','100' -RedirectStandardOutput "$base\balance_A.log" -RedirectStandardError "$base\balance_A.err.log"
Start-Sleep -Seconds 20
$b = Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList '-ExecutionPolicy','Bypass','-File',"$base\balance_worker.ps1",'-TcpPort','8777','-Only','_Seen_[5-9]$','-Session','B','-Keeps','100' -RedirectStandardOutput "$base\balance_B.log" -RedirectStandardError "$base\balance_B.err.log"
Mark "workers started (A pid $($a.Id), B pid $($b.Id))"

$a.WaitForExit()
$b.WaitForExit()
$tot = 0
foreach ($d in 'distill_data_rand','distill_data_r3','distill_data_r4','distill_data_fix',
                'distill_data_fix2','distill_data_fix3','distill_data_top_short',
                'distill_data_pant_long','distill_data_pant_short') {
    $n = @(Get-ChildItem "$base\$d" -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'meta.json') }).Count
    if ($n -gt 0) { Mark "  $d : $n" }
    $tot += $n
}
Mark "BALANCE-DONE total $tot episodes"
