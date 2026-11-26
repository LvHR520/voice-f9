# voice-f9

> **按住 F9 说话，松开就上屏。完全离线，不上传你的声音。**

Windows 全局语音输入工具。在任何输入框里——微信、Word、浏览器、VS Code、终端——按住 `F9` 说话，松开后文字直接落进光标处，不用切换窗口，不用点麦克风按钮。

识别全部在本机完成。默认不发任何网络请求，录音不落盘。

## 实测数据

在 RTX 5060 Laptop（medium 模型，int8_float16）上的实测：

| 项目 | 数值 |
|---|---|
| 热态推理延迟 | **0.47–0.66 秒**（首次含 CUDA 内核编译，约 7 秒） |
| 模型加载 | 4.3–11.9 秒（进程启动一次，之后常驻） |
| 空闲显存占用 | +934 MiB |
| 空闲 CPU | 0.07%（热键监听是事件驱动，不轮询） |
| 空闲 20 分钟后 | 自动卸载模型，释放显存，再按 F9 重新加载 |

> 想要更轻：`config.json` 里把 `model` 改成 `small`，内存减半、速度快一倍、中文准确率略降。没有独立显卡也会自动回退 CPU（慢一个数量级，但能用）。

## 中英文混说

`language` 默认是 `null`（自动检测），不要改成 `"zh"`。

写死 `"zh"` 时 Whisper 会把英文**翻译成中文**。同一句英文实测：

| 配置 | 识别结果 |
|---|---|
| `"zh"` | 请打开 config.json 的文件并转成小，然后重新开始 Voice F9。 |
| `"zh"` + 热词 | 请打开 config.json 文件并转成小，然后重新开始声 F9。 |
| 自动检测 + 热词 | **Please open the config.json file and change the model to small, then restart voice-f9.** |

纯中文场景自动检测仍会判成中文（置信度 0.98），质量不受影响。遇到新词识别错，往 `hotwords` 里加就行。

## 快速开始

需要 Python 3.10 或更高版本。

```powershell
git clone https://github.com/LvHR520/voice-f9.git
cd voice-f9
pip install -r requirements.txt
```

然后双击 `start-voice-f9.vbs`（无黑窗口）。等十几秒，日志里出现 `模型 medium 就绪：cuda/int8_float16` 就可以用了。

1. 把光标点进任意输入框
2. **按住 F9 说话**，松开 → 文字上屏
3. 退出：`Ctrl + Alt + Q`

开机自启：右键 `install-autostart.ps1` → 用 PowerShell 运行。

首次运行会从 HuggingFace 下载 medium 模型（约 1.5 GB）。国内网络建议先设镜像：

```powershell
$env:HF_ENDPOINT = 'https://hf-mirror.com'
```

### 先自测，确认麦克风和模型都通

```powershell
python voice_f9.py --selftest 3          # 录 3 秒，只打印识别结果，不注入
python voice_f9.py --keytest 10          # 10 秒内按你想绑的键，打印键名
python voice_f9.py --file 某个.mp3        # 用音频文件测转写
python voice_f9.py --text "测试" --delay 3 # 3 秒后自动粘贴到焦点窗口
```

`--selftest` 输出里的 `RMS` 是音量：静音约 0.003，正常说话 0.02~0.2。太低说明选错麦克风了。

## 配置

改 `config.json`，改完重启生效（`Ctrl+Alt+Q` 退出后重新双击 vbs）。

| 键 | 默认 | 说明 |
|---|---|---|
| `hotkey` | `f9` | 用 `--keytest` 查可用键名（`f8`、`right ctrl`、`pause`…） |
| `mode` | `hold` | `hold` 按住说话；`toggle` 按一下开始、再按一下结束 |
| `model` | `medium` | `small` 更省更快，`large-v3` 更准 |
| `device` / `compute_type` | `auto` / `int8_float16` | 失败自动回退 CPU |
| `language` | `null` | **别改回 `"zh"`**，理由见上 |
| `hotwords` | 见文件 | 专有名词白名单，保证拼写正确 |
| `initial_prompt` | 中文标点提示 | **别删**，删了结果会没有标点 |
| `idle_unload_minutes` | `20` | 空闲多久卸载模型 |
| `trim_trailing_punct` | `true` | 去掉句末的「。，」，方便接着写 |
| `overlay` | `true` | 屏幕中下方浮标，显示录音/识别状态 |

完整说明见文件内注释。

## 常见问题

**Q: 日志里报 `Library cublas64_12.dll is not found or cannot be loaded`？**

这是 faster-whisper 在 Windows 上最常见的坑。NVIDIA 的 pip 轮子会把 DLL 放在 `site-packages/nvidia/*/bin`，而 Windows 默认不搜索这个路径。两个条件缺一不可：

1. 装了 CUDA 轮子：`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`
2. 程序启动时用 `os.add_dll_directory` 把那些 `bin` 注册进去（`voice_f9.py` 开头已处理）

只做第一步还是会报错——模型能加载，但第一次推理就炸。

**Q: 按热键没反应？**

目标程序以管理员权限运行时，键盘钩子收不到事件 → 本工具也要用管理员权限启动。

**Q: 热键变成静音/音量键了？**

`F9` 在部分键盘上是媒体键。换 `f8`，或在配置里加 `"suppress": true`。

**Q: 粘贴没出现？**

先跑 `--text "测试" --delay 3` 验证注入链路，再查 `voice-f9.log`。

**Q: 识别不准？**

别用蓝牙耳机麦（常见 8000Hz 采样率）。中文专有名词可以写进 `hotwords`。

## 隐私

- 默认全离线：音频不出本机，进程不建立外部连接。
- 录音不落盘，转写完即释放。
- 只有把 `polish` 打开时，才会把**文字**（不是音频）发给 DeepSeek 润色。

## 已知限制

- 仅在 Windows 10/11 x64 上测试过。
- 依赖 `keyboard` 库做全局热键，该库不支持 macOS。
- 需要 Python 环境。**正在做免安装版本**（换 ONNX 引擎，模型从 1.5 GB 降到约 230 MB，打包成解压即用）。

## 许可

MIT