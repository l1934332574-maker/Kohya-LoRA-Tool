@echo off
setlocal
chcp 65001 >nul
title 启动网页界面

echo ============================================================
echo   正在启动 Kohya-SS 网页界面…
echo   如果浏览器没有自动打开，请访问：http://127.0.0.1:7860
echo   关闭本窗口即可停止服务。
echo ============================================================
echo.

call "%~dp0_common.bat" resolve
if errorlevel 1 ( pause & exit /b 1 )

pushd "%KOHYA_DIR%"
call venv\Scripts\activate.bat

set "NOVERIFY="
echo %KOHYA_DIR% | findstr /C:" " >nul 2>nul
if not errorlevel 1 set "NOVERIFY=--noverify"

python kohya_gui.py --server_port 7860 --inbrowser %NOVERIFY%
popd

echo.
echo  网页界面已退出。
pause
endlocal