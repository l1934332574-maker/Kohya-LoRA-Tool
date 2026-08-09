@echo off
setlocal
chcp 65001 >nul
title 安装本地下载好的大文件

rem ============================================================
rem  使用方法：
rem   1. 用浏览器/下载器把 3 个文件下载到：
rem      %USERPROFILE%\Downloads\kohya_wheels
rem      （链接见该文件夹里的「下载说明.txt」）
rem   2. 双击本脚本即可，不会再重新下载大文件
rem ============================================================

set "WHEELS=%USERPROFILE%\Downloads\kohya_wheels"
set "KDIR=%USERPROFILE%\kohya_ss"
set "VPY=%KDIR%\venv\Scripts\python.exe"

if not exist "%VPY%" (
    echo [错误] 没找到虚拟环境：%VPY%
    echo        请先运行 01_一键安装_Setup.bat 或 手动安装_ManualInstall.bat。
    pause
    exit /b 1
)

if not exist "%WHEELS%\torch-2.7.0+cu128-cp312-cp312-win_amd64.whl" (
    echo [错误] 没找到 torch 文件。
    echo        请先把 3 个文件下载到：%WHEELS%
    echo        链接请看：%WHEELS%\下载说明.txt
    pause
    exit /b 1
)

echo [1/3] 安装本地 wheel（torch / torchvision / xformers，不再重新下载）…
"%VPY%" -m pip install ^
  "%WHEELS%\torch-2.7.0+cu128-cp312-cp312-win_amd64.whl" ^
  "%WHEELS%\torchvision-0.22.0+cu128-cp312-cp312-win_amd64.whl" ^
  "%WHEELS%\xformers-0.0.30-cp312-cp312-win_amd64.whl"
if errorlevel 1 (
    echo [错误] 本地安装失败，请把报错发给我。
    pause
    exit /b 1
)

echo [2/3] 校验并安装其余小依赖（走清华镜像，很快）…
pushd "%KDIR%"
"%VPY%" setup\setup_windows.py --headless
set "RC=%errorlevel%"
popd
if not "%RC%"=="0" (
    echo [错误] 剩余依赖安装失败，请把报错发给我。
    pause
    exit /b 1
)

echo [3/3] 记录安装位置并验证 PyTorch…
> "%~dp0kohya_dir.txt" echo %KDIR%
"%VPY%" -c "import torch; print('torch', torch.__version__, '| CUDA 可用:', torch.cuda.is_available())"

echo.
echo ============================================================
echo   安装完成！
echo   接下来：图片放进 dataset\raw，运行 02 预处理，03 启动界面
echo ============================================================
echo.
pause
endlocal