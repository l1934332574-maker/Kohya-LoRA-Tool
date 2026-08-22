@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Kohya-SS 手动安装（代理模式）

rem ============================================================
rem  手动安装脚本（适合你开代理自己跑）
rem  使用方法：
rem   1. 打开你的代理软件（Clash / v2rayN 等）
rem   2. 把下面 PROXY 改成你的代理地址
rem      Clash 默认：http://127.0.0.1:7890
rem      v2rayN 默认：http://127.0.0.1:10809
rem   3. 双击本脚本，全程保持代理开启
rem ============================================================

set "PROXY=http://127.0.0.1:7897"

echo [1/6] 配置代理环境变量（HTTP_PROXY / HTTPS_PROXY）…
set "HTTP_PROXY=%PROXY%"
set "HTTPS_PROXY=%PROXY%"

echo [2/6] 配置 Git：openssl 后端 + 走代理，解决 GitHub 报错…
git config --global http.sslBackend openssl
git config --global http.version HTTP/1.1
git config --global http.postBuffer 524288000
git config --global http.proxy %PROXY%
git config --global https.proxy %PROXY%

echo [3/6] 进入 kohya_ss 目录并激活虚拟环境…
set "KIT_DIR=%~dp0"
set "KDIR=%USERPROFILE%\kohya_ss"
if not exist "%KDIR%\.git" (
    echo [错误] 没有找到仓库：%KDIR%
    echo        请先运行 01_一键安装_Setup.bat 克隆仓库。
    pause
    exit /b 1
)
pushd "%KDIR%"
call venv\Scripts\activate.bat

echo [4/6] 确认 pip 清华镜像源…
python -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

echo [5/6] 安装全部依赖（约 10~30 分钟，请保持代理开启）…
python -m pip install --upgrade pip setuptools wheel -q
python setup\setup_windows.py --headless
if errorlevel 1 (
    echo [错误] 依赖安装失败，请向上滚动查看报错。
    echo        如果是网络报错，请检查代理端口是否正确、代理是否开启。
    call venv\Scripts\deactivate.bat
    popd
    pause
    exit /b 1
)

echo [6/6] 记录安装位置并验证 PyTorch…
popd
> "%KIT_DIR%kohya_dir.txt" echo %KDIR%
"%KDIR%\venv\Scripts\python.exe" -c "import torch; print('torch', torch.__version__, '| CUDA 可用:', torch.cuda.is_available())"

echo.
echo ============================================================
echo   安装完成！
echo   接下来：
echo   1. 把图片放进：%KIT_DIR%dataset\raw
echo   2. 运行 02_数据预处理_Preprocess.bat
echo   3. 运行 03_启动UI_StartUI.bat 打开网页界面训练
echo ============================================================
echo.
pause
endlocal