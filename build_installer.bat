@echo off
setlocal
chcp 65001 >nul
title 构建安装包（Inno Setup）

echo ============================================================
echo   构建安装包：build_exe\installer\Setup.exe
echo   前提：已安装 Inno Setup 6（https://jrsoftware.org/isinfo.php）
echo ============================================================
echo.

cd /d "%~dp0"

rem 先构建便携目录包（安装包内容来源）
call "%~dp0build_portable.bat"
if errorlevel 1 ( pause & exit /b 1 )

rem 找 ISCC
set "ISCC="
for %%P in (
  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
) do if exist "%%~P" set "ISCC=%%~P"
if not defined ISCC (
    echo [错误] 没有找到 Inno Setup。请先安装：https://jrsoftware.org/isinfo.php
    echo        安装完成后重新运行本脚本。
    pause
    exit /b 1
)

rem 图标（存在才带上）
if not exist "%~dp0build_exe\installer" mkdir "%~dp0build_exe\installer"
if exist "%~dp0app.ico" copy /y "%~dp0app.ico" "%~dp0build_exe\installer\app.ico" >nul

echo [Inno] 正在编译安装包 ...
"%ISCC%" "%~dp0build_exe\installer\installer.iss"
if errorlevel 1 (
    echo [错误] Inno Setup 编译失败。
    pause
    exit /b 1
)

echo.
echo   安装包已生成：build_exe\installer\Setup.exe
pause
endlocal
