@echo off
rem 后台启动 ComfyUI（Comfy Desktop 那份实例）+ SageAttention 加速，并自检写入状态文件。
rem 真正逻辑在 _start_comfyui.ps1：Comfy Desktop 直接点启动不带 --use-sage-attention，
rem 会丢掉约 1.8x 提速；这里显式带上，含空格路径也已正确加引号。
rem 自检结果：scripts\_start_comfyui.status.log；服务日志：_comfyui.out.log / _comfyui.err.log
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_start_comfyui.ps1"
echo STARTED (sage attention ON). status: scripts\_start_comfyui.status.log
