# Stop weekend3 after its stage B (seed2 train+eval): stages C/D/H/E train on pre-fix data and would
# collide with fix_chain on the relay and on GPU. ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$mark = "$base\weekend3_markers.log"
$t = 0
while ($t -lt (20 * 60)) {
    if ((Test-Path $mark) -and (Select-String -Path $mark -Pattern '(B done|B TRAIN FAILED)' -Quiet)) { break }
    Start-Sleep -Seconds 60; $t++
}
$me = $PID
Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $me -and $_.CommandLine -match 'weekend3\.ps1' -and $_.CommandLine -notmatch 'Win32_Process' -and $_.CommandLine -notmatch 'weekend3_stop' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
"$(Get-Date -Format 'MM-dd HH:mm')  weekend3 stopped after stage B (pre-fix data experiments dropped)" | Out-File -Append -Encoding ascii $mark
