"""voice-f9 双引擎对比测试：SenseVoice(CPU) vs faster-whisper(GPU)。

在 voice-f9 目录下运行：
    python bench.py                                   # 用当前目录的 test-speech.wav / test-zh.wav
    python bench.py 英文.wav 中文.wav                  # 指定文件
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import voice_f9 as vf

FILES = [
    ("英文", sys.argv[1] if len(sys.argv) > 1 else "test-speech.wav"),
    ("中文", sys.argv[2] if len(sys.argv) > 2 else "test-zh.wav"),
]
ENGINES = ["sensevoice", "whisper"]
RUNS = 3

vf.cuda_dll_dirs()
base = vf.load_config()

for engine in ENGINES:
    cfg = dict(base)
    cfg["engine"] = engine
    if engine == "whisper":
        cfg["model"] = "medium"
        cfg["device"] = "cuda"
    tr = vf.Transcriber(cfg)
    t0 = time.time()
    ok = tr.ensure()
    load = time.time() - t0
    if not ok:
        print(f"[{engine}] 加载失败: {tr.error}")
        continue
    tr.warmup()
    print(f"\n=== {engine} ({tr.device}) 加载 {load:.1f}s ===")
    for label, path in FILES:
        if not Path(path).exists():
            print(f"  {label}: 文件不存在")
            continue
        times = []
        text = ""
        for _ in range(RUNS):
            t = time.time()
            text = tr.transcribe(path)
            times.append(time.time() - t)
        best = min(times)
        avg = sum(times[1:]) / max(1, len(times) - 1) if len(times) > 1 else times[0]
        print(f"  {label}: 首次 {times[0]:.2f}s | 热态均值 {avg:.2f}s | 最快 {best:.2f}s")
        print(f"         → {text}")