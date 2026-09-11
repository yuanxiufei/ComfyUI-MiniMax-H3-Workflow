@echo off
rem 后台启动 ComfyUI（Comfy Desktop 那份实例）+ SageAttention 加速，并自检写入状态文件。
rem 真正逻辑在 _start_comfyui.ps1：Comfy Desktop 直接点启动不带 --use-sage-attention，
rem 会丢掉约 1.8x 提速；这里显式带上，含空格路径也已正确加引号。
rem 自检结果：scripts\_start_comfyui.status.log；服务日志：_comfyui.out.log / _comfyui.err.log
chcp 65001 >nul
rem 日志/输出统一 UTF-8：与 comfy_config.py、_start_comfyui.ps1 保持一致，避免中文乱码
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_start_comfyui.ps1"
echo STARTED (sage attention ON). status: scripts\_start_comfyui.status.log
