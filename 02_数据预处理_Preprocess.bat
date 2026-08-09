@echo off
setlocal
chcp 65001 >nul
title 数据预处理（画风 LoRA）

echo ============================================================
echo   数据预处理：缩放 1024px + 去黑边 + 去水印 + 统一画风标签
echo   模式：画风 LoRA（过滤人物五官/角色标签，repeats=5）
echo ============================================================
echo.

call "%~dp0_common.bat" resolve
if errorlevel 1 ( pause & exit /b 1 )

set "RAW=%~dp0dataset\raw"
set "TRAIN=%~dp0dataset\train"

if not exist "%RAW%" (
    echo [错误] 没有找到图片文件夹：%RAW%
    echo        请先把图片放进 dataset\raw 文件夹。
    pause
    exit /b 1
)

"%PYTHON%" "%~dp0preprocess.py" --input "%RAW%" --output "%TRAIN%" --size 1024 --mode style --repeats 5

echo.
echo  完成。处理结果请看上面的日志。
echo  预处理后的图片和标签在：%TRAIN%
pause
endlocal
