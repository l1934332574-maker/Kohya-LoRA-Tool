@echo off
setlocal
chcp 65001 >nul
title 一键训练（画风 LoRA - SDXL）

echo ============================================================
echo   一键训练（sdxl_train_network.py，画风 LoRA 预设已更新）
echo   rank=12 alpha=6 lr=3e-4 te_lr=1.5e-4 epochs=8 repeats=5
echo   底模：models\AniShadow_V5.safetensors（SDXL）
echo ============================================================
echo.

call "%~dp0_common.bat" resolve
if errorlevel 1 ( pause & exit /b 1 )

set "BASE_MODEL=%~dp0models\AniShadow_V5.safetensors"
if not "%~1"=="" set "BASE_MODEL=%~1"

if not exist "%BASE_MODEL%" (
    echo [错误] 没有找到底模：%BASE_MODEL%
    echo        请确认 models 文件夹里有 AniShadow_V5.safetensors。
    pause
    exit /b 1
)

if not exist "%~dp0dataset\train" (
    echo [错误] 没有找到预处理数据，请先运行 02_数据预处理_Preprocess.bat。
    pause
    exit /b 1
)

if not exist "%~dp0configs\dataset_config.toml" (
    echo [错误] 缺少数据集配置，请先运行 02_数据预处理_Preprocess.bat。
    pause
    exit /b 1
)

if not exist "%~dp0output" mkdir "%~dp0output"
if not exist "%~dp0logs" mkdir "%~dp0logs"

pushd "%KOHYA_DIR%\sd-scripts"
call "%KOHYA_DIR%\venv\Scripts\activate.bat"

accelerate launch --num_cpu_threads_per_process 2 sdxl_train_network.py ^
  --pretrained_model_name_or_path="%BASE_MODEL%" ^
  --dataset_config="%~dp0configs\dataset_config.toml" ^
  --output_dir="%~dp0output" ^
  --output_name="anime_style_lora" ^
  --logging_dir="%~dp0logs" ^
  --save_model_as="safetensors" ^
  --save_precision="bf16" ^
  --network_module="networks.lora" ^
  --network_dim=12 ^
  --network_alpha=6 ^
  --learning_rate=3e-4 ^
  --unet_lr=3e-4 ^
  --text_encoder_lr=1.5e-4 ^
  --train_text_encoder ^
  --optimizer_type="AdamW8bit" ^
  --lr_scheduler="cosine" ^
  --lr_warmup_steps=120 ^
  --max_train_epochs=8 ^
  --train_batch_size=1 ^
  --max_data_loader_n_workers=1 ^
  --seed=1234 ^
  --mixed_precision="bf16" ^
  --cache_latents ^
  --cache_latents_to_disk ^
  --cache_text_encoder_outputs ^
  --gradient_checkpointing ^
  --enable_bucket ^
  --bucket_no_upscale ^
  --min_bucket_reso=512 ^
  --max_bucket_reso=2048 ^
  --bucket_reso_steps=64 ^
  --caption_extension=".txt" ^
  --sdpa ^
  --save_every_n_steps=300

popd

echo.
echo  训练结束。模型保存在：%~dp0output\anime_style_lora.safetensors
echo  使用模板：%~dp0output\anime_style_lora_使用模板.txt
pause
endlocal
