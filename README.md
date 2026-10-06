<p align="center">
  <img src="docs/assets/readme-hero.svg" alt="Kohya-LoRA：四类引擎，一套 Windows 本地训练工作台" width="100%" />
</p>

<h1 align="center">Kohya-LoRA 一键训练工具</h1>

<p align="center"><strong>四类引擎统一操作 · AI 助手协作训练 · 中文界面 · 免费开源</strong></p>

<p align="center">
  <a href="https://github.com/l1934332574-maker/Kohya-LoRA-Tool/releases/latest"><img alt="最新版本" src="https://img.shields.io/github/v/release/l1934332574-maker/Kohya-LoRA-Tool?style=flat-square&amp;color=6366f1" /></a>
  <img alt="Windows 10 / 11" src="https://img.shields.io/badge/Windows-10%20%2F%2011-2563eb?style=flat-square" />
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-059669?style=flat-square" /></a>
</p>

<p align="center">
  <a href="https://github.com/l1934332574-maker/Kohya-LoRA-Tool/releases/latest"><strong>下载安装</strong></a> ·
  <a href="https://modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool"><strong>国内下载</strong></a> ·
  <a href="CHANGELOG.md">更新记录</a> ·
  <a href="#交流与反馈"><strong>QQ 交流群：602396066</strong></a>
</p>

将环境安装、模型下载、打标、参数配置、训练和结果查看放进一个 Windows 桌面工具。适合训练 **人物、画风、概念 LoRA**，也接入了视频与音频训练模式。

## 核心优势

| 优势 | 你能直接用到的能力 |
|---|---|
| **四类引擎，一套操作** | kohya、musubi、AI Toolkit、Fizgig 共用项目入口，按模式显示准备步骤和参数 |
| **AI 助手直接参与训练** | 说出目标，助手提问补全需求，调用环境检查、模型下载、项目配置与训练流程 |
| **少折腾环境和下载** | 图形化安装与修复、国内下载源、大文件断点续传；可选择已有模型 |
| **参数变化看得见** | 六档训练方案，应用前显示参数变化，支持撤销与手动调整 |
| **数据准备到效果对比** | WD14、中文 / 英文描述、标签编辑、固定种子采样、历史查看与 A/B 对比 |
| **多个项目有序管理** | 项目配置、处理后数据与输出分开管理，配套训练记录、任务队列和日志导出 |

六档方案：**先跑通流程 / 快速试效果 / 降低显存占用 / 标准训练 / 加快每步速度 / 增加训练量**。

## 支持的模型

| 引擎 | 已接入模型 | 素材 |
|---|---|---|
| **kohya / sd-scripts** | SD1.5、SDXL、FLUX.1、Anima | 图片 |
| **musubi-tuner** | Krea 2、FLUX.2 | 图片 |
| **AI Toolkit** | Krea2、Qwen-Image、Z-Image；MiniMax H3 | 图片；H3 视频 |
| **Fizgig** | Krea2、FLUX.2 Klein 9B、Qwen-Image-2.1、MiniMax H3 | 图片；H3 图片 / 视频 / 音频 |

**Windows 10 / 11，NVIDIA 为主要支持路径。** AMD 提供兼容模式与 Fizgig ROCm 路径，部分仍属实验性支持。显存需求和采样稳定性取决于具体模型、引擎与配置；第三方底模需匹配对应架构。

## 下载与开始训练

- **安装版**：[GitHub Releases](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/releases/latest) 或 [魔搭](https://modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool) 下载 `Setup.exe`。
- **便携版**：下载 `KohyaLoraTool_*_portable.zip`，完整解压后运行 `Kohya一键工具.exe`。

`Code → Download ZIP` 是源码。基础模型和训练环境按所选模式准备，首次使用需要下载相应资源。

**新建项目 → 选择模型与模式 → 按引导准备环境 → 导入素材并核对标签 → 查看方案 → 开始训练。**

在任务窗口查看进度、日志与可用采样，完成后打开项目输出目录取走 LoRA。

## AI 助手怎么用

打开左侧 **训练助手**，连接自己的兼容文字服务或本地 Ollama，然后说出目标：

> 我要训练人物 LoRA，图集已经准备好了，帮我检查环境并设置参数。

助手通过可点击选项、文件选择补全信息，再按权限准备和执行任务。安装、下载、在线图片与自动开训可以分别授权，也可随时手动接管。对话按项目保存，重启不会自动恢复训练。

AI 服务需自行配置，在线服务可能收费；助手效果取决于接入模型。不接 AI 也能正常使用训练界面，助手不保证自动修复所有问题。

## 数据与隐私

训练在本机执行，项目、图集和产物保存在本地。使用在线助手时，相关对话、配置与按需读取的日志会发送给所选服务；发送图片需单独允许。服务密钥使用 Windows 用户加密保存，发布包不携带作者的私人配置。

实际数据位置可在软件内查看，LoRA 输出到 `数据目录/output/<项目名>/`。

## 交流与反馈

### QQ 交流群：**602396066**

交流训练经验、反馈问题、讨论新功能。反馈训练故障时，请附上 **软件版本、模式 / 引擎、显卡型号、复现步骤和导出的日志**。

也可以提交 [GitHub Issue](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/issues) 或 Pull Request。

<details>
<summary><strong>源码运行与使用文档</strong></summary>

建议 Python 3.12，前端构建需要 Node.js 20.19+ 或 22.12+；新版界面需要 WebView2。在仓库根目录执行：

```powershell
python -m pip install customtkinter pillow -r requirements-ui.txt
npm --prefix modern_ui ci
npm --prefix modern_ui run build
python kohya_gui.py
```

经典界面入口：`python kohya_gui.py --ui classic`。安装包用户可在快捷方式目标末尾追加 ` --ui classic`。

- [使用说明](README_使用说明.md)
- [更新日志](CHANGELOG.md)：安装包功能以对应已发布版本为准。
- [前端开发说明](modern_ui/README.md)

</details>

## 开源许可

项目采用 [MIT License](LICENSE)。底层引擎、模型及第三方资源遵循各自许可，见 [第三方声明](THIRD_PARTY_NOTICES.md)。请使用有权用于训练的素材。
