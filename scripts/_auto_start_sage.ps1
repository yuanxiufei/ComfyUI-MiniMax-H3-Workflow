$ErrorActionPreference = 'SilentlyContinue'
$port = 8188
Write-Output "[auto] waiting for Desktop to release $port ..."

$free = $false
for ($i=1; $i -le 360; $i++) {   # up to ~18 min
    Start-Sleep -Seconds 3
    $li = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $li) { $free = $true; Write-Output "[auto] port $port free after ~$($i*3)s"; break }
}
if (-not $free) { Write-Output "[auto] TIMEOUT: $port still occupied by Desktop"; exit 1 }

# cleanup leftover ComfyUI python main.py processes (incl half-dead sage)
Write-Output "[auto] cleanup leftover ComfyUI python procs..."
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'main\.py' } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output "[auto] killed PID $($_.ProcessId)"
}
Start-Sleep -Seconds 3
$li2 = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($li2) { Write-Output "[auto] ERROR: $port still in use after cleanup"; exit 1 }

# start sage instance on the now-free port
$py    = 'D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-MiniMax-H3-Workflow\ComfyUI\.venv\Scripts\python.exe'
$cwd   = 'D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-MiniMax-H3-Workflow'
$logOut = 'D:\code\voide\ComfyUI-MiniMax-H3-Workflow\scripts\_comfyui_sage.out.log'
$logErr = 'D:\code\voide\ComfyUI-MiniMax-H3-Workflow\scripts\_comfyui_sage.err.log'
$argstr = '-s "ComfyUI\main.py" --port 8188 --feature-flag show_signin_button=true --feature-flag enable_telemetry=true --enable-manager --extra-model-paths-config "C:\Users\24969\AppData\Roaming\Comfy Desktop\instance-model-paths\inst-1788311613966.yaml" --input-directory D:\Comfy-Desktop\ComfyUI-Shared\input --output-directory D:\Comfy-Desktop\ComfyUI-Shared\output --use-sage-attention'
Start-Process -FilePath $py -ArgumentList $argstr -WorkingDirectory $cwd -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logErr
Write-Output "[auto] sage start launched, waiting ready..."

$ok = $false
for ($i=1; $i -le 150; $i++) {
    Start-Sleep -Seconds 2
    try {
        $s = Invoke-RestMethod -Uri "http://127.0.0.1:$port/system_stats" -TimeoutSec 3
        $ok = $true
        Write-Output "[auto] READY ver=$($s.system.comfyui_version) dev=$($s.devices[0].name)"
        break
    } catch { }
}
if ($ok) { Write-Output "[auto] Sage instance READY on $port" } else { Write-Output "[auto] NOT ready, check err log" }
