@echo off
setlocal
chcp 65001 >nul
title 构建便携目录包（onedir）

echo ============================================================
echo   构建 Windows 便携目录包（不是单 exe）
echo   产物：build_exe\dist\Kohya一键工具\  （整个文件夹即便携包）
echo   注：不打包 torch/大模型/用户数据，仅代码、脚本、配置、离线安装包
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/3] PyInstaller 构建 onedir ...
python -m PyInstaller --noconfirm --clean ^
  --distpath "build_exe\dist" --workpath "build_exe\work" ^
  "build_exe\Kohya一键工具.spec"
if errorlevel 1 (
    echo [错误] PyInstaller 构建失败。
    pause
    exit /b 1
)

set "PKG=build_exe\dist\Kohya一键工具"

echo [2/3] 复制代码/脚本/配置/离线安装包进便携包 ...
copy /y "preprocess.py" "%PKG%\" >nul
copy /y "model_downloader.py" "%PKG%\" >nul
copy /y "README_使用说明.md" "%PKG%\" >nul
copy /y "LICENSE" "%PKG%\" >nul
copy /y "THIRD_PARTY_NOTICES.md" "%PKG%\" >nul
copy /y "01_一键安装_Setup.bat" "%PKG%\" >nul
copy /y "02_数据预处理_Preprocess.bat" "%PKG%\" >nul
copy /y "03_启动UI_StartUI.bat" "%PKG%\" >nul
copy /y "04_一键训练_TrainCLI.bat" "%PKG%\" >nul
copy /y "安装本地依赖.bat" "%PKG%\" >nul
copy /y "手动安装_ManualInstall.bat" "%PKG%\" >nul
copy /y "_common.bat" "%PKG%\" >nul

if not exist "%PKG%\installers"    xcopy /e /i /q "installers"    "%PKG%\installers"    >nul
if not exist "%PKG%\configs"       xcopy /e /i /q "configs"       "%PKG%\configs"       >nul
if not exist "%PKG%\models\base"   mkdir "%PKG%\models\base" >nul 2>nul

rem 清空 kohya_dir.txt：首次运行自动检测 kohya 源码（不写死本机路径）
> "%PKG%\kohya_dir.txt" echo.

echo [3/3] 压缩便携包为 zip（可直接分发）...
powershell -NoProfile -Command "Compress-Archive -Force -Path '%PKG%\*' -DestinationPath 'build_exe\dist\Kohya一键工具_便携版.zip'"

echo.
echo   便携包：%PKG%
echo   便携 zip：build_exe\dist\Kohya一键工具_便携版.zip
echo   运行数据（output/dataset/logs/tokenizers）会自动写入 %%APPDATA%%\KohyaLoraTool，避免权限问题。
echo   首次运行请先点「01_一键安装_Setup.bat」或主程序「②一键安装」。
pause
endlocal

