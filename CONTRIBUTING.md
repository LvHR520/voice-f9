# 参与贡献

## 提交问题前

先看 [README 的常见问题](README.md#常见问题)。几个高频坑已经写在里面了：

- 按 F9 没反应 → 目标窗口是不是管理员权限运行的
- F9 变成静音 → 它是媒体键，换 `f8`
- 识别不准 → 蓝牙耳机麦克风常见 8000 Hz

## 改代码前

1. 读 `AGENTS.md`，那里写了哪些地方不能动、为什么
2. 装环境：

```powershell
pip install sherpa-onnx sounddevice keyboard numpy
powershell -ExecutionPolicy Bypass -File download-model.ps1
```

3. 确认基线是通的：

```powershell
python voice_f9.py --file 任意.wav
```

## 改完要跑

```powershell
python -m py_compile voice_f9.py
python voice_f9.py --file 任意.wav
python bench.py
```

三条都过才算没弄坏。改了行为记得更新 `CHANGELOG.md`。

## 提交

- 一个提交只做一件事
- 提交信息说清「为什么改」，不只是「改了什么」
- 不要提交 `models/`、`voice-f9.log`、`__pycache__/`

## 发版

打 tag 即可，CI 会自动构建并发布：

```powershell
git tag v0.2.1
git push --tags
```

## 报告问题时带上

- 系统版本（`winver`）
- `config.json` 里的 `engine`
- `voice-f9.log` 最后 20 行

有这三样基本能定位，省一轮来回。