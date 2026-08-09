@echo off
chcp 65001 >nul
rem ============================================================
rem  共用脚本：自动找到 kohya_ss 安装位置、虚拟环境和 python
rem  用法：call "%~dp0_common.bat" resolve
rem ============================================================

if /i "%~1"=="resolve" goto :resolve
exit /b 0

:resolve
set "KIT_DIR=%~dp0"
set "KOHYA_DIR="
if exist "%KIT_DIR%kohya_dir.txt" set /p KOHYA_DIR=<"%KIT_DIR%kohya_dir.txt"
if not defined KOHYA_DIR set "KOHYA_DIR=%KIT_DIR%kohya_ss"

rem 仅当 kohya_dir.txt 不存在时才检测：路径含空格/中文则回退到用户目录
if exist "%KIT_DIR%kohya_dir.txt" goto :have_kohya
set "HAS_NONASCII=0"
echo %KIT_DIR% | findstr /C:" " >nul 2>nul
if not errorlevel 1 set "HAS_NONASCII=1"
if "%HAS_NONASCII%"=="0" (
    set "KIT_CHECK=%KIT_DIR%"
    powershell -NoProfile -Command "if ($env:KIT_CHECK.ToCharArray() | Where-Object {[int]$_ -gt 127}) { '1' } else { '0' }" > "%TEMP%\kohya_check.txt" 2>nul
    set /p HAS_NONASCII=<"%TEMP%\kohya_check.txt"
)
if "%HAS_NONASCII%"=="1" set "KOHYA_DIR=%USERPROFILE%\kohya_ss"

:have_kohya
if not exist "%KOHYA_DIR%\venv\Scripts\activate.bat" (
    echo [错误] 没有找到 kohya_ss 虚拟环境：%KOHYA_DIR%
    echo        请先运行 01_一键安装_Setup.bat。
    exit /b 1
)
set "VENV_DIR=%KOHYA_DIR%\venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PATH=%PATH%;%KOHYA_DIR%\venv\Lib\site-packages\torch\lib"
exit /b 0
