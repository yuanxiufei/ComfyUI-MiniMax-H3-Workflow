@echo off
rem 用 PowerShell Start-Process 真正独立后台启动 ComfyUI（v0.34.2），输出目录指向共享池
rem 日志合并写入 _comfyui.log，避免 cmd 会话回收导致进程退出
chcp 65001 >nul
set "PY=D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\.venv\Scripts\python.exe"
set "APP=D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\main.py"
set "LOG_OUT=d:\code\voide\ComfyUI-MiniMax-H3-Workflow\scripts\_comfyui.out.log"
set "LOG_ERR=d:\code\voide\ComfyUI-MiniMax-H3-Workflow\scripts\_comfyui.err.log"
set "OUT=D:\Comfy-Desktop\ComfyUI-Shared\output"

powershell -NoProfile -Command "Start-Process -FilePath '%PY%' -ArgumentList '\"%APP%\" --port 8188 --output-directory \"%OUT%\" --extra-model-paths-config \"D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\extra_model_paths.yaml\"' -WindowStyle Hidden -RedirectStandardOutput '%LOG_OUT%' -RedirectStandardError '%LOG_ERR%'"

echo STARTED. waiting for 8188...
