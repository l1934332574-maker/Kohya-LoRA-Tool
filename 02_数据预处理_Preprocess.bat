@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 数据预处理（画风 / 人物 LoRA）

echo ============================================================
echo   数据预处理：缩放 1024px + 去黑边 + 去水印 + WD14 自动打标
echo   模式由环境变量 MODE 决定：style=画风 / character=人物
echo   人物/画风均可通过 TRIGGER_WORD 环境变量指定触发词，
echo   打标完成后自动追加到每张标签最开头（可留空跳过）。
echo ============================================================
echo.

call "%~dp0_common.bat" resolve
if errorlevel 1 ( pause & exit /b 1 )

rem ================= 模式解析（环境变量 MODE，未设置默认画风）=================
if not defined MODE set "MODE=style"
if /i "%MODE%"=="character" (
    set "MODE_NAME=人物角色"
    set "TRAIN=%~dp0dataset\train_character"
    set "PP_MODE=character"
    set "PP_REPEATS=15"
) else (
    set "MODE_NAME=画风"
    set "TRAIN=%~dp0dataset\train"
    set "PP_MODE=style"
    set "PP_REPEATS=5"
)
set "RAW=%~dp0dataset\raw"

echo [模式] %MODE_NAME% LoRA（MODE=%MODE%）
echo [输出] %TRAIN%
echo.

if not exist "%RAW%" (
    echo [错误] 没有找到图片文件夹：%RAW%
    echo        请先把图片放进 dataset\raw 文件夹。
    pause
    exit /b 1
)

rem ================= WD14 自动打标（原有逻辑，保持不变）=================
"%PYTHON%" "%~dp0preprocess.py" --input "%RAW%" --output "%TRAIN%" --size 1024 --mode %PP_MODE% --repeats %PP_REPEATS%
if errorlevel 1 (
    echo [错误] 预处理失败，已停止，未修改任何标签文件。
    pause
    exit /b 1
)

rem ============================================================
rem  [新增] Trigger 触发词后处理（WD14 打标完成后执行）
rem  · 触发词来自环境变量 TRIGGER_WORD（GUI/外部脚本调用前设置）
rem  · trigger_word 为空 → 直接跳过，不修改任何文件
rem  · 只修改 *.txt 标签文件（UTF-8 编码），绝不改动图片
rem  · 防重复：第一行已以触发词开头则跳过该文件
rem ============================================================
if defined TRIGGER_WORD set "trigger_word=%TRIGGER_WORD%"
if not defined trigger_word set "trigger_word="
if "%trigger_word%"=="" (
    echo.
echo ℹ你没有填触发词
echo 训练出来的模型照样能用，但是画图要复制训练生成的标签才能出想要效果
    goto :after_trigger
)

echo.
if /i "%MODE%"=="character" (
    echo 【追加角色触发词：%trigger_word%】
) else (
    echo 【追加画风专属触发词：%trigger_word%】
)
echo.

rem 生成临时 Python 脚本（Python 3 默认 UTF-8 读源码，中文安全）
set "PYT=%TEMP%\kohya_add_trigger_%RANDOM%.py"
echo # -*- coding: utf-8 -*-                                   > "%PYT%"
echo import os, re, sys                                        >> "%PYT%"
echo trig = (os.environ.get("TRIGGER_WORD") or "").strip()     >> "%PYT%"
echo d = os.environ.get("TRIG_DIR", "")                        >> "%PYT%"
echo if not os.path.isdir(d):                                  >> "%PYT%"
echo     print("目录不存在: " + d)                              >> "%PYT%"
echo     sys.exit(0)                                           >> "%PYT%"
echo n = 0                                                     >> "%PYT%"
echo for name in sorted(os.listdir(d)):                        >> "%PYT%"
echo     if not name.lower().endswith(".txt"):                 >> "%PYT%"
echo         continue                                          >> "%PYT%"
echo     fp = os.path.join(d, name)                            >> "%PYT%"
echo     with open(fp, "r", encoding="utf-8") as f:            >> "%PYT%"
echo         text = f.read()                                   >> "%PYT%"
echo     if not text.strip():                                  >> "%PYT%"
echo         with open(fp, "w", encoding="utf-8") as f:        >> "%PYT%"
echo             f.write(trig)                                 >> "%PYT%"
echo         print("[已追加] " + name)                          >> "%PYT%"
echo         n += 1                                             >> "%PYT%"
echo         continue                                           >> "%PYT%"
echo     first = text.lstrip().splitlines()[0].strip()          >> "%PYT%"
echo     if re.match("^" + re.escape(trig), first, re.IGNORECASE): >> "%PYT%"
echo         print("[跳过] 已含触发词: " + name)                 >> "%PYT%"
echo         continue                                            >> "%PYT%"
echo     with open(fp, "w", encoding="utf-8") as f:              >> "%PYT%"
echo         f.write(trig + ", " + text)                          >> "%PYT%"
echo     print("[已追加] " + name)                                >> "%PYT%"
echo     n += 1                                                   >> "%PYT%"
echo print("共追加 " + str(n) + " 个文件")                        >> "%PYT%"

set "TRIG_DIR=%TRAIN%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%PYTHON%" "%PYT%"
echo.
echo =====================================
echo ✅已经把你的触发词加到全部图片标签里了
echo 📢训练完模型，画图的时候写上这个词，就能调出你的角色/画风
echo =====================================
del "%PYT%" >nul 2>nul

:after_trigger
echo.
echo  完成。处理结果请看上面的日志。
echo  预处理后的图片和标签在：%TRAIN%
pause
endlocal
