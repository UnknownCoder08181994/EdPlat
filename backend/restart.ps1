$procs = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%app.py%'" | Where-Object { $_.Name -eq 'python.exe' }
foreach ($p in $procs) {
    Write-Host "Killing PID $($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force
}
Start-Sleep -Seconds 1
Set-Location "C:\Users\Shane\Desktop\zenflow-rebuild\backend"
Start-Process -FilePath python -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\Shane\Desktop\zenflow-rebuild\backend' -WindowStyle Hidden
Write-Host "Server restarted"
