@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Kohya-SS LoRA 一键安装（离线包 + 国内镜像）

echo ============================================================
echo   Kohya-SS LoRA 一键安装（离线包 + 国内镜像）
echo   第 1 步：检查/安装 Git 与 Python（优先用内置安装包，无需联网）
echo   第 2 步：解压内置 kohya_ss + sd-scripts 源码（无需 GitHub/代理）
echo   第 3 步：创建 Python 虚拟环境
echo   第 4 步：设置 pip 清华 pypi + 阿里 pytorch 镜像
echo   第 5 步：安装全部依赖（约 10~30 分钟）
echo   第 6 步：配置 accelerate
echo ============================================================
echo.

set "KIT_DIR=%~dp0"

rem ================= Git =================
set "GIT_INSTALLER="
for %%F in ("%KIT_DIR%installers\git\Git-*.exe") do set "GIT_INSTALLER=%%~fF"

where git >nul 2>nul
if errorlevel 1 (
    if not defined GIT_INSTALLER (
        echo [错误] 没有找到 Git，且项目里没有内置 Git 安装包。
        echo        请手动安装：https://git-scm.com/download/win
        pause
        exit /b 1
    )
    echo [第 1 步] 正在用内置安装包安装 Git（静默安装）…
    "%GIT_INSTALLER%" /VERYSILENT /NORESTART /SP- /SUPPRESSMSGBOXES /NOCANCEL
    where git >nul 2>nul
    if errorlevel 1 (
        echo [错误] 内置 Git 安装后仍未找到，请手动安装：https://git-scm.com/download/win
        pause
        exit /b 1
    )
) else (
    echo [第 1 步] 已找到 Git，跳过安装。
)

rem ================= Python =================
rem 找一个可用的 Python 3.10.9~3.12.x（不因 PATH 里的旧/新 python 而粗暴退出）：
rem   1) PATH 里的 python（版本符合才用）
rem   2) py launcher 的 3.12（与内置 cp312 wheel 匹配，优先）
rem   3) py launcher 的 3.10
rem   4) 内置安装包静默装 3.12
set "PY_INSTALLER="
for %%F in ("%KIT_DIR%installers\python\python-*.exe") do set "PY_INSTALLER=%%~fF"
set "PY_BIN=python"
python -c "import sys; sys.exit(0 if (3,10,9) <= sys.version_info[:3] < (3,13,0) else 1)" >nul 2>nul
if not errorlevel 1 goto :python_ok
py -3.12 -c "import sys; sys.exit(0 if (3,10,9) <= sys.version_info[:3] < (3,13,0) else 1)" >nul 2>nul
if not errorlevel 1 ( set "PY_BIN=py -3.12" & goto :python_ok )
py -3.10 -c "import sys; sys.exit(0 if (3,10,9) <= sys.version_info[:3] < (3,13,0) else 1)" >nul 2>nul
if not errorlevel 1 ( set "PY_BIN=py -3.10" & goto :python_ok )
if defined PY_INSTALLER (
    echo [第 1 步] 未找到可用的 Python 3.10.9~3.12.x，正在用内置安装包静默安装 Python 3.12…
    "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 Include_doc=0 Include_tcltk=1 Include_pip=1
    py -3.12 -c "import sys; sys.exit(0 if (3,10,9) <= sys.version_info[:3] < (3,13,0) else 1)" >nul 2>nul
    if not errorlevel 1 ( set "PY_BIN=py -3.12" & goto :python_ok )
)
echo [错误] 未找到 3.10.9~3.12.x 的 Python。
python --version
echo        请安装 Python 3.12 后重跑本脚本：https://www.python.org/downloads/
pause
exit /b 1
:python_ok
echo [第 1 步] 使用 Python：%PY_BIN%

rem ================= 选择 kohya_ss 安装位置（不支持空格/中文路径） =================
set "KOHYA_DIR=%KIT_DIR%kohya_ss"
echo !KOHYA_DIR! | findstr /C:" " >nul 2>nul
if not errorlevel 1 set "KOHYA_DIR=%USERPROFILE%\kohya_ss"
set "HAS_NONASCII=0"
echo !KOHYA_DIR! | findstr /C:" " >nul 2>nul
if not errorlevel 1 set "HAS_NONASCII=1"
if "!HAS_NONASCII!"=="0" (
    set "KIT_CHECK=!KIT_DIR!"
    powershell -NoProfile -Command "if ($env:KIT_CHECK.ToCharArray() | Where-Object {[int]$_ -gt 127}) { '1' } else { '0' }" > "%TEMP%\kohya_check.txt" 2>nul
    set /p HAS_NONASCII=<"%TEMP%\kohya_check.txt"
)
if "!HAS_NONASCII!"=="1" set "KOHYA_DIR=%USERPROFILE%\kohya_ss"
echo [提示] kohya_ss 安装位置：!KOHYA_DIR!
echo.

rem ================= 解压内置 kohya_ss =================
if exist "%KOHYA_DIR%\kohya_gui.py" (
    echo [第 2 步] kohya_ss 已存在，跳过解压。
) else (
    if exist "%KOHYA_DIR%" (
        echo [错误] 目标目录已存在但不是 kohya_ss：
        echo        %KOHYA_DIR%
        echo        请删除或改名后重试。
        pause
        exit /b 1
    )
    echo [第 2 步] 解压内置 kohya_ss 源码包…
    mkdir "%KOHYA_DIR%"
    powershell -NoProfile -Command "$z = Get-ChildItem '%KIT_DIR%installers\kohya_ss\kohya_ss-*.zip' | Select-Object -First 1; if (-not $z) { exit 1 }; Expand-Archive -Force $z.FullName '%KOHYA_DIR%'; $top = Get-ChildItem '%KOHYA_DIR%' -Directory | Where-Object { $_.Name -like 'kohya_ss-*' } | Select-Object -First 1; if ($top) { Get-ChildItem $top.FullName -Force | Move-Item -Destination '%KOHYA_DIR%' -Force; Remove-Item $top.FullName -Recurse -Force }"
    if errorlevel 1 (
        echo [错误] 解压 kohya_ss 失败。
        pause
        exit /b 1
    )
)

rem ================= 解压内置 sd-scripts 子模块 =================
if not exist "%KOHYA_DIR%\sd-scripts\sdxl_train_network.py" (
    echo [第 2 步] 解压内置 sd-scripts 子模块…
    mkdir "%KOHYA_DIR%\sd-scripts" 2>nul
    powershell -NoProfile -Command "$z = Get-ChildItem '%KIT_DIR%installers\kohya_ss\sd-scripts-*.zip' | Select-Object -First 1; if (-not $z) { exit 1 }; Expand-Archive -Force $z.FullName '%KOHYA_DIR%\sd-scripts'; $top = Get-ChildItem '%KOHYA_DIR%\sd-scripts' -Directory | Where-Object { $_.Name -like 'sd-scripts-*' } | Select-Object -First 1; if ($top) { Get-ChildItem $top.FullName -Force | Move-Item -Destination '%KOHYA_DIR%\sd-scripts' -Force; Remove-Item $top.FullName -Recurse -Force }"
    if errorlevel 1 (
        echo [错误] 解压 sd-scripts 失败。
        pause
        exit /b 1
    )
)

rem ================= 创建虚拟环境 =================
rem 优先用 Python 3.12（与内置离线 wheel cp312 匹配）；3.10/3.11 建的 venv 装不上 cp312 依赖
rem 会导致 numpy/torch 报 not supported、训练退化成 CPU 版（accelerator device: cpu）。
if not exist "%KOHYA_DIR%\venv" (
    echo [第 3 步] 正在创建 Python 虚拟环境（%PY_BIN%）…
    pushd "%KOHYA_DIR%"
    %PY_BIN% -m venv venv 2>nul
    if errorlevel 1 python -m venv venv
    popd
    if not exist "%KOHYA_DIR%\venv\Scripts\python.exe" (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
) else (
    echo [第 3 步] 虚拟环境已存在，跳过。
)
"%KOHYA_DIR%\venv\Scripts\python.exe" -c "import sys;print('[信息] venv Python 版本:','%d.%d'%sys.version_info[:2])"
rem 若非 3.12，后续内置 cp312 wheel 可能装不上，提示用户装 3.12 重建
"%KOHYA_DIR%\venv\Scripts\python.exe" -c "import sys;sys.exit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [警告] venv 不是 Python 3.12，内置依赖为 3.12 版本，可能安装失败。
    echo        建议安装 Python 3.12 后删除 %KOHYA_DIR%\venv 再重跑本脚本。
)

rem 已安装则跳过（重复运行秒过）
"%KOHYA_DIR%\venv\Scripts\python.exe" -c "import torch" >nul 2>nul
if not errorlevel 1 (
    echo [提示] 已检测到已安装环境（torch 可用），跳过依赖安装。
    > "%KIT_DIR%kohya_dir.txt" echo %KOHYA_DIR%
    goto :done
)

rem ================= 设置镜像 =================
echo [第 4 步] 设置 pip 清华 pypi + 阿里 pytorch 镜像（无需代理）…
"%KOHYA_DIR%\venv\Scripts\python.exe" -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
"%KOHYA_DIR%\venv\Scripts\python.exe" -m pip config set global.extra-index-url https://mirrors.aliyun.com/pytorch-wheels/cu128

rem ================= 安装全部依赖 =================
echo [第 5 步] 正在安装全部依赖（约 10~30 分钟）…
pushd "%KOHYA_DIR%"
call venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel -q
set "PIP_EXTRA_INDEX_URL=https://mirrors.aliyun.com/pytorch-wheels/cu128"
python setup\setup_windows.py --headless
set "SETUP_RC=%errorlevel%"
call venv\Scripts\deactivate.bat
popd
if not "%SETUP_RC%"=="0" (
    echo [错误] 依赖安装失败，请向上滚动查看报错。
    pause
    exit /b 1
)

rem ================= 记录安装位置 =================
> "%KIT_DIR%kohya_dir.txt" echo %KOHYA_DIR%

:done
rem ================= 验证 =================
echo [第 6 步] 验证 PyTorch …
"%KOHYA_DIR%\venv\Scripts\python.exe" -c "import torch; print('torch', torch.__version__, '| CUDA 可用:', torch.cuda.is_available())"

echo.
echo ============================================================
echo   安装完成！
echo   kohya_ss 位置：%KOHYA_DIR%
echo.
echo   接下来：
echo   1. 把图片放到：%KIT_DIR%dataset\raw
echo   2. 运行 02_数据预处理_Preprocess.bat（或主程序 ③ 数据预处理）
echo   3. 运行主程序 ⑥ 一键训练（画风/人物双模式）
echo ============================================================
echo.
pause
endlocal

