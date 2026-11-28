# 演示物料

`demo.gif` 是 README 首屏用的演示图，**由脚本自动生成，不需要任何人录屏**。

## 怎么来的

Windows 自带中文 TTS（`Microsoft Huihui Desktop`）合成三句话 → `voice_f9.py --file` 用**同一套模型**识别 → 输出由 `term2gif.py` 渲染成 GIF。

```powershell
# 生成演示（语音 -> 识别，全程无需麦克风；python 需已装 sherpa-onnx）
powershell -ExecutionPolicy Bypass -File examples\demo.ps1

# 渲染成 GIF
python ..\_factory\term2gif.py --out docs\demo.gif --title "voice-f9 · 离线识别实测" `
  --display "examples\demo.ps1" --width 900 --fps 10 `
  -- powershell -NoProfile -ExecutionPolicy Bypass -File examples\demo.ps1
```

## 为什么不用真机录屏

按键和麦克风在自动化环境里读不到（规则 4），而且录屏会带进桌面文件（规则 7）。
TTS + 文件转写走的是同一条推理链路，识别质量和延迟都是真的，只是入口换了。

**未覆盖的部分**：F9 热键触发、光标注入。这两项写进 README 的「已知限制」，不作为发版阻塞项。

## 要求

- 900 px 宽、10–12 fps、200 KB ~ 3.5 MB
- 中文要确认字形正常（`term2gif` 已做中英双字体回退）
- 生成后自己看一帧，确认没有方框、没有截断