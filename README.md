# voice-f9

> **按住 F9 说话，松开就上屏。完全离线，不上传你的声音。**

Windows 全局语音输入工具。在任何输入框里——微信、Word、浏览器、VS Code、终端——按住 `F9` 说话，松开后文字直接落进光标处。不用切换窗口，不用点麦克风按钮。

识别全部在本机完成，默认不发任何网络请求，录音不落盘。

## 快速事实

| 项 | 内容 |
|---|---|
| 是什么 | Windows 全局语音输入工具，按住 F9 说话，松开文字直接上屏 |
| 也叫 | 语音输入、语音打字、听写工具、按住说话、F9 语音输入 |
| 要不要装 Python | **不用**，下载解压双击即用 |
| 要不要显卡 | **不用**，纯 CPU 推理，核显和办公本都能跑 |
| 要不要联网 | **不用**，完全离线，声音不出本机 |
| 模型多大 | 228 MB（已内置在下载包里） |
| 识别速度 | 中文 0.21 秒 / 英文 0.19 秒（6 秒语音，含标点） |
| 支持系统 | Windows 10 / 11 64 位 |
| 开源协议 | MIT |

> 给编码助手读的技术说明在 [AGENTS.md](AGENTS.md)——怎么跑、改完怎么验证、哪些地方不能动。

## 为什么不用在线语音输入

在线方案要么有额度、要么要登录、要么把声音传出去。这个工具一次装好，之后永久免费、永久离线，连飞机上都能用。

## 实测数据

同一台机器（RTX 5060 Laptop + i9），同一段音频，两种引擎对比：

| | SenseVoice（默认） | faster-whisper medium（可选） |
|---|---|---|
| 运行设备 | **CPU** | GPU |
| 模型体积 | **228 MB** | 1460 MB |
| 模型加载 | **1.6 秒** | 18.2 秒 |
| 中文识别 | **0.21 秒** | 0.62 秒 |
| 英文识别 | 0.19 秒 | 0.59 秒 |
| 中文准确率 | 一致 | 一致 |
| 英文准确率 | 一般 | **更好** |

实测原文都是「请打开配置文件，把模型改成小号，然后重新启动这个工具。」：

- SenseVoice → `请打开配置文件，把模型改成小号，然后重新启动这个工具。` ✅
- faster-whisper → `请打开配置文件,把模型改成小号,然后重新启动这个工具。` ✅

英文上 SenseVoice 会差一些（`config.json` 可能识别成 `config dot JSO N`）。**日常中文输入用默认的 SenseVoice 就够**，需要英文和技术术语时再切 faster-whisper。

## 快速开始

### 方式一：下载即用（推荐）

到 [Releases](https://github.com/LvHR520/voice-f9/releases/latest) 下载 `voice-f9-win64.zip`（184 MB）：

1. 解压到任意目录
2. 双击 `start-voice-f9.vbs`（无黑窗口）或 `voice-f9.exe`
3. 光标点进任意输入框，**按住 F9 说话**

不需要 Python，不需要 CUDA，不需要单独下模型。整包 318 MB，模型已内置。

> **国内下载慢的话用镜像**（实测：直连约 26 KB/s，镜像约 300 KB/s，184 MB 大约 10 分钟）：
> - `https://ghfast.top/https://github.com/LvHR520/voice-f9/releases/latest/download/voice-f9-win64.zip`
> - `https://gh-proxy.com/https://github.com/LvHR520/voice-f9/releases/latest/download/voice-f9-win64.zip`

### 方式二：源码运行

需要 Python 3.10 或更高版本。

```powershell
git clone https://github.com/LvHR520/voice-f9.git
cd voice-f9
pip install sherpa-onnx sounddevice keyboard numpy
powershell -ExecutionPolicy Bypass -File download-model.ps1   # 下模型，约 228 MB
```

然后双击 `start-voice-f9.vbs`。

开机自启：右键 `install-autostart.ps1` → 用 PowerShell 运行。

模型下载默认走 `hf-mirror.com`（国内可达），中断后重跑会续传。

### 想用 GPU 版（faster-whisper）

准确率更高，但要装 CUDA 库，模型也大 6 倍：

```powershell
pip install faster-whisper "av<19" nvidia-cublas-cu12 nvidia-cudnn-cu12
```

然后在 `config.json` 里把 `"engine"` 改成 `"whisper"`。

> `av` 必须小于 19：PyAV 19 移除了 `av.open()` 的 `metadata_errors` 参数，faster-whisper 还在传它，装了 19 会直接 `TypeError`。

### 先自测，确认麦克风和模型都通

```powershell
python voice_f9.py --selftest 3            # 录 3 秒，只打印识别结果，不注入
python voice_f9.py --keytest 10            # 10 秒内按你想绑的键，打印键名
python voice_f9.py --file 某个.wav          # 用音频文件测转写
python voice_f9.py --text "测试" --delay 3  # 3 秒后自动粘贴到焦点窗口
python bench.py                            # 两个引擎的速度/准确率对比
```

`--selftest` 输出里的 `RMS` 是音量：静音约 0.003，正常说话 0.02~0.2。太低说明选错麦克风了。

## 配置

改 `config.json`，改完重启生效（`Ctrl+Alt+Q` 退出后重新双击 vbs）。

| 键 | 默认 | 说明 |
|---|---|---|
| `engine` | `sensevoice` | `sensevoice`（CPU、快、小）或 `whisper`（GPU、英文更准） |
| `hotkey` | `f9` | 用 `--keytest` 查可用键名（`f8`、`right ctrl`、`pause`…） |
| `hotkey_backend` | `poll` | 热键实现方式。`poll` 轮询按键状态，最兼容；`hook` 用键盘钩子，延迟更低且能拦截按键（`suppress` 生效） |
| `mode` | `hold` | `hold` 按住说话；`toggle` 按一下开始、再按一下结束 |
| `sensevoice_dir` | 空 | 模型目录，留空则用 `models/sensevoice` |
| `use_itn` | `true` | 数字和标点规整（「十五个」→「15个」） |
| `idle_unload_minutes` | `20` | 空闲多久卸载模型 |
| `trim_trailing_punct` | `true` | 去掉句末的「。，」，方便接着写 |
| `overlay` | `true` | 屏幕中下方浮标，显示录音/识别状态 |
| `model` / `device` | `medium` / `auto` | 仅 `engine=whisper` 时生效 |

## 常见问题

**Q: 按热键没反应？**

目标程序以管理员权限运行时，键盘钩子收不到事件 → 本工具也要用管理员权限启动。

**Q: 热键变成静音/音量键了？**

`F9` 在部分键盘上是媒体键。换 `f8`，或在配置里加 `"suppress": true`。

**Q: 粘贴没出现？**

先跑 `--text "测试" --delay 3` 验证注入链路，再查 `voice-f9.log`。

**Q: 识别不准？**

别用蓝牙耳机麦（常见 8000Hz 采样率），用桌面 USB 麦克风或笔记本麦克风阵列。

**Q: 用 whisper 引擎时日志报 `cublas64_12.dll is not found`？**

这是 faster-whisper 在 Windows 上最常见的坑。NVIDIA 的 pip 轮子把 DLL 放在 `site-packages/nvidia/*/bin`，而 Windows 默认不搜这个路径。两件事缺一不可：

1. 装了 `nvidia-cublas-cu12` 和 `nvidia-cudnn-cu12`
2. 程序启动时用 `os.add_dll_directory` 注册那些 `bin`（`voice_f9.py` 里已处理）

只做第一步还是会报错——模型能加载，但第一次推理就炸。

## 隐私

- 默认全离线：音频不出本机，进程不建立外部连接。
- 录音不落盘，转写完即释放。

## 已知限制

- 仅在 Windows 10/11 x64 上测试过。
- 依赖 `keyboard` 库做全局热键，该库不支持 macOS。
- SenseVoice 对英文专有名词的识别明显弱于 whisper，中英混说时建议切 `engine=whisper`。
- 目前还需要 Python 环境，**免安装版本正在做**。

## 致谢

- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — ONNX 推理引擎
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) — 阿里 FunAudioLLM 的多语言语音识别模型
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 可选引擎

## 许可

MIT