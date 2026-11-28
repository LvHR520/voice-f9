# AGENTS.md

给编码助手读的项目说明书。人读的版本在 [README.md](README.md)。

## 这个项目是什么

Windows 全局语音输入工具。按住 `F9` 说话，松开后文字注入到当前光标处。

单文件主程序 `voice_f9.py`（约 30 KB），无框架、无构建步骤。默认引擎是 sherpa-onnx + SenseVoice（ONNX，纯 CPU），可选 faster-whisper（GPU）。

## 怎么跑起来

```powershell
pip install sherpa-onnx sounddevice keyboard numpy
powershell -ExecutionPolicy Bypass -File download-model.ps1   # 下 228 MB 模型
python voice_f9.py                                            # 前台跑，方便看输出
```

无窗口启动用 `start-voice-f9.vbs`（会找同目录 `.venv` 或 PATH 里的 `pythonw.exe`）。

## 验证改动的命令

改完必须跑这三条，全部通过才算没弄坏：

```powershell
python -m py_compile voice_f9.py                    # 语法
python voice_f9.py --file 任意.wav                   # 转写链路（不需要麦克风）
python bench.py                                     # 两个引擎都要能加载并出结果
```

`--file` 支持 wav（走标准库）和 mp3/m4a（走 av）。没有 av 时只支持 wav，属于预期行为。

## 不要动的地方

| 位置 | 原因 |
|---|---|
| `config.json` 的 `"language": null` | 改成 `"zh"` 会让 Whisper 把英文翻译成中文 |
| `config.json` 的 `initial_prompt` | 删掉后识别结果没有标点 |
| `requirements.txt` 的 `av<19` 上界 | PyAV 19 移除了 `av.open()` 的 `metadata_errors` 参数，faster-whisper 仍在传，装 19 会 TypeError |
| `load_audio_16k()` 里的 16000 | SenseVoice 与 whisper 都要求 16 kHz，改了会静音或乱码 |

## 架构约定

- **双引擎**：`config.json` 的 `engine` 决定走哪条分支，`Transcriber._build()` 分发。
- **模型位置**：`sensevoice_dir` 留空时用 `<程序目录>/models/sensevoice`；打包后 `<程序目录>` 指 exe 所在目录（`BASE` 已按 `sys.frozen` 处理）。
- **热键**：两套后端，`config.json` 的 `hotkey_backend` 切换。`poll` 轮询 `GetAsyncKeyState`（默认，兼容性最好）；`hook` 用 `keyboard` 库的低层钩子（延迟更低、`suppress` 生效）。**从沙箱化进程启动时两者都读不到按键**——那是输入隔离，不代表程序坏了。所以热键本身不纳入自动验证（写进 README 已知限制），转写链路用 `--file` 或 `examples\demo.ps1` 验证。
- **打包**：PyInstaller onedir，必须带 `--exclude-module faster_whisper/ctranslate2/av/torch/transformers/tokenizers/onnxruntime`，否则会多收 250 MB。参见 `.github/workflows/build-release.yml`。

## 已知限制

- 仅 Windows 10/11 x64 测过。
- `keyboard` 库不支持 macOS。
- SenseVoice 对英文专有名词明显弱于 whisper，中英混说建议 `engine=whisper`。
- 模型 228 MB，不进仓库（`.gitignore` 已排除 `models/`）。

## 提交前

- 不要提交 `models/`、`voice-f9.log`、`__pycache__/`
- 改行为要更新 `CHANGELOG.md`
- 发版：打 `v*` tag，CI 自动构建并发布到 Release