@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem ---- 模型缓存放在本文件夹，不占 C 盘 ----
set "HF_HOME=%~dp0hf_cache"
set "UV=%~dp0.uv\uv.exe"
if not exist "%UV%" (
  echo [1/4] 下载 uv（Python 环境管理器）...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_INSTALL_DIR='%~dp0.uv'; $env:UV_NO_MODIFY_PATH='1'; irm https://astral.sh/uv/install.ps1 | iex"
)
if not exist ".venv\Scripts\python.exe" (
  echo [2/4] 创建 Python 3.12 环境...
  "%UV%" venv .venv --python 3.12
  echo [3/4] 安装 PyTorch（CUDA 12.8，支持 RTX 50 系）和 diffusers...
  "%UV%" pip install --python .venv\Scripts\python.exe torch torchvision --index-url https://download.pytorch.org/whl/cu128
  "%UV%" pip install --python .venv\Scripts\python.exe diffusers transformers accelerate safetensors opencv-python-headless pillow huggingface_hub
)
echo [4/4] 开始重绘...
".venv\Scripts\python.exe" refine_local.py %*
echo.
echo 完成。结果在 ..\..\art\本地重绘\
pause
