# start_offline.ps1 - bridge + agent against the OFFLINE dev client
# Uses the REAL bridge (browser_bridge.cjs + src/bridge/*), not a fork:
# WOC_TAB_MATCH points GameClient at the vite tab.
$ErrorActionPreference = "SilentlyContinue"

Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'browser_bridge|play_autonomous' -and
    $_.Name -match 'node|python'
} | ForEach-Object {
    Write-Output ("  kill " + $_.ProcessId)
    Stop-Process -Id $_.ProcessId -Force
}
Start-Sleep -Seconds 3

Write-Output "Starting REAL bridge (offline tab)..."
$env:WOC_TAB_MATCH = "localhost:5173"
$bridge = Start-Process -FilePath 'node' -ArgumentList 'D:\world-of-claudecraft\browser_bridge.cjs' `
    -WorkingDirectory 'D:\world-of-claudecraft' -WindowStyle Hidden -PassThru
Write-Output ("  bridge PID: " + $bridge.Id)
Start-Sleep -Seconds 12

$port = Get-NetTCPConnection -LocalPort 8791 -State Listen -ErrorAction SilentlyContinue
if ($port) { Write-Output "Bridge OK on :8791" }
else { Write-Output "Bridge FAILED"; exit 1 }

Write-Output "Starting agent..."
$agent = Start-Process -FilePath 'C:\Users\vladc\AppData\Local\Programs\Python\Python312\python.exe' `
    -ArgumentList '-X','faulthandler','-m','play_autonomous' `
    -WorkingDirectory 'D:\world-of-claudecraft\python' `
    -WindowStyle Hidden -PassThru
Write-Output ("  agent PID: " + $agent.Id)
Start-Sleep -Seconds 5
Write-Output "Done. Logs: python/autonomous_log.jsonl"
