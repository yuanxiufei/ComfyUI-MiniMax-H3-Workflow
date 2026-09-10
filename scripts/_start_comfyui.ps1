# 以 SageAttention 加速参数重启 ComfyUI（Comfy Desktop 那份实例），并自检结果。
# 背景：Comfy Desktop 直接点启动时不会带 --use-sage-attention，会丢掉约 1.8x 提速；
#      且 Start-Process 传数组参数时不会为含空格的路径自动加引号（曾把模型路径配置拆断）。
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\_start_comfyui.ps1
$ErrorActionPreference = 'Stop'

$PY     = 'D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-MiniMax-H3-Workflow\ComfyUI\.venv\Scripts\python.exe'
$APP    = 'D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-MiniMax-H3-Workflow\ComfyUI\main.py'
$CWD    = 'D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-MiniMax-H3-Workflow\ComfyUI'
$MODELS = 'C:\Users\24969\AppData\Roaming\Comfy Desktop\instance-model-paths\inst-1788311613966.yaml'
$IN     = 'D:\Comfy-Desktop\ComfyUI-Shared\input'
$OUT    = 'D:\Comfy-Desktop\ComfyUI-Shared\output'
$LOG_OUT = 'd:\code\voide\ComfyUI-MiniMax-H3-Workflow\scripts\_comfyui.out.log'
$LOG_ERR = 'd:\code\voide\ComfyUI-MiniMax-H3-Workflow\scripts\_comfyui.err.log'
$STATUS  = 'd:\code\voide\ComfyUI-MiniMax-H3-Workflow\scripts\_start_comfyui.status.log'

# 统一写 UTF8：Tee-Object 默认写 UTF-16，读起来是"二进制文件"，不利于排查
function Log($msg) {
    $line = "$((Get-Date).ToString('HH:mm:ss')) $msg"
    Write-Host $line
    Add-Content -Path $STATUS -Value $line -Encoding UTF8
}

Set-Content -Path $STATUS -Value '' -Encoding UTF8 -ErrorAction SilentlyContinue
Log "== 启动 ComfyUI（sage on）=="

# 1) 清掉旧实例：Comfy Desktop 拉起的实例不带 sage，留着会抢 8188 和显存
$old = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
       Where-Object { $_.CommandLine -like '*main.py*' }
foreach ($p in $old) { Log ("kill old main.py pid=" + $p.ProcessId); Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
if ($old) { Start-Sleep -Seconds 5 }

# 2) 显式给含空格的路径加引号后启动（Start-Process 不会自动加）
$argLine = @(
    '"' + $APP + '"',
    '--port', '8188',
    '--use-sage-attention',
    '--input-directory',  '"' + $IN + '"',
    '--output-directory', '"' + $OUT + '"',
    '--extra-model-paths-config', '"' + $MODELS + '"'
) -join ' '
Log ("start: " + $argLine)
Start-Process -FilePath $PY -WorkingDirectory $CWD -ArgumentList $argLine `
    -WindowStyle Hidden -RedirectStandardOutput $LOG_OUT -RedirectStandardError $LOG_ERR | Out-Null

# 3) 等 8188 起来
$up = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 3
    try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 5; $up = $true; break } catch { }
}
Log ("port8188_up=" + $up)

# 4) 自检：进程参数带 sage？日志里 sage 生效？有报错？
$live = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like '*main.py*' }
foreach ($p in $live) { Log ("live pid=" + $p.ProcessId + " sage=" + ($p.CommandLine -like '*use-sage-attention*')) }
$errTxt = Get-Content $LOG_ERR -Raw -ErrorAction SilentlyContinue
$outTxt = Get-Content $LOG_OUT -Raw -ErrorAction SilentlyContinue
Log ("log_sage=" + (($errTxt + $outTxt) -match 'sage attention|SageAttention'))
Log ("log_error=" + (($errTxt + $outTxt) -match 'Traceback|FileNotFoundError'))
if (-not $up) { Log "!! 8188 未就绪，请看 _comfyui.err.log 尾部" }
Log "== 完成 =="
