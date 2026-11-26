# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.2.1] - 2026-11-26

### 修复

- **`start-voice-f9.vbs` 双击无法启动**。VBScript 的续行符 `_` 要求 CRLF 换行，而文件是 LF，导致整个脚本报「未结束的字符串常量」直接退出。改为不使用续行符的单行写法，并强制 CRLF——两种情况都能跑。
- v0.2.0 的发布包内置的就是这个坏文件，本次重新打包。

## [0.2.0] - 2026-11-26

### 变更

- **默认引擎换成 sherpa-onnx + SenseVoice**。模型从 1460 MB 降到 228 MB，加载从 18.2 秒降到 1.6 秒，中文识别从 0.62 秒降到 0.21 秒，且不再需要显卡和 CUDA。
- faster-whisper 降级为可选引擎，`config.json` 里 `"engine": "whisper"` 才启用。

### 新增

- 免安装包：`voice-f9-v0.2.0-win64.zip`（188 MB），下载解压双击即用，不需要 Python。
- `load_audio_16k()`：`--file` 现在支持任意音频，wav 走标准库，其他格式走 av。
- `download-model.ps1`：从 hf-mirror 下载模型，支持断点续传。
- `bench.py`：两个引擎的速度与准确率对比。
- GitHub Actions 自动构建发布（`.github/workflows/build-release.yml`）。
- `AGENTS.md`：给编码助手读的项目说明书。

### 修复

- `start-voice-f9.vbs` 原来写死了作者本机的 pythonw 路径，别人下载后无法启动。改为依次查找同目录 `.venv`、`venv`、`pythonw.exe`，最后查 PATH。
- `av` 版本冲突：PyAV 19 移除了 `av.open()` 的 `metadata_errors` 参数，而 faster-whisper 仍在传它，装了 19 会直接 `TypeError`。`requirements.txt` 加 `<19` 上界。

### 已知问题

- SenseVoice 对英文专有名词的识别弱于 whisper（`config.json` 可能识别成 `config dot JSO N`）。
- GitHub Release 在国内下载慢，直连约 26 KB/s，镜像约 300 KB/s。

## [0.1.0] - 2026-11-26

### 新增

- 首个版本：按住 F9 说话，松开后文字注入当前光标处。
- 全局热键、按住/切换两种模式、屏幕浮标、空闲自动卸载模型。
- 基于 faster-whisper，支持 GPU 加速与自动回退 CPU。
- 热词表、自动语言检测、标点提示。
- `--selftest` / `--keytest` / `--file` / `--text` 四个自测命令。