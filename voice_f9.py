#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""voice-f9 —— 全局「按住说话」离线语音输入。

按住快捷键说话 → 松开 → 本地 faster-whisper(优先 GPU) 转写 → 文字落到光标处。
默认 100% 离线；config.json 里把 polish 打开可接 DeepSeek 润色（可选联网）。

用法：
    pythonw voice_f9.py            常驻（无窗口，走 start-voice-f9.vbs 启动）
    python  voice_f9.py --selftest 录 3 秒，只打印识别结果，不注入
    python  voice_f9.py --keytest  10 秒按键测试，打印你按的键名（挑热键用）
    python  voice_f9.py --text "..." 直接把一段文字走注入链路（测粘贴）
    python  voice_f9.py --file a.mp3 用音频文件测转写（不注入）
"""

from __future__ import annotations

import argparse
import ctypes
import glob
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

if getattr(sys, "frozen", False):
    # 打包后（PyInstaller）程序本体在 _internal 里，配置和模型要跟着 exe 走
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
LOG_PATH = BASE / "voice-f9.log"
CREDENTIALS = Path.home() / ".dsh" / ".credentials.yaml"

_lock = threading.Lock()


# ---------------------------------------------------------------- 基础设施
def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        with _lock, LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    if sys.stderr and getattr(sys.stderr, "isatty", lambda: False)():
        print(line, flush=True)


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return cfg


def cuda_dll_dirs() -> None:
    """把 pip 装的 cuBLAS/cuDNN 目录挂进进程，faster-whisper 才找得到。"""
    import site

    roots = []
    try:
        roots.extend(site.getsitepackages())
    except Exception:
        pass
    roots.append(str(Path(sys.executable).parent / "Lib" / "site-packages"))
    nvidia = None
    for root in roots:
        cand = Path(root) / "nvidia"
        if cand.is_dir():
            nvidia = cand
            break
    if not nvidia:
        return
    bins = [str(p) for p in nvidia.glob("*/bin") if p.is_dir()]
    for b in bins:
        try:
            os.add_dll_directory(b)
        except OSError:
            pass
    if bins:
        os.environ["PATH"] = ";".join(bins) + ";" + os.environ.get("PATH", "")


def single_instance() -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Global\\voice-f9-singleton")
    return bool(handle) and kernel32.GetLastError() != 183


# ---------------------------------------------------------------- 剪贴板 / 注入
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def set_clipboard(text: str) -> bool:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        log("clipboard: OpenClipboard 失败（可能被别的程序占用）")
        return False
    try:
        user32.EmptyClipboard()
        size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
        handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(ctypes.c_void_p(handle))
            return False
        buf = ctypes.create_unicode_buffer(text)
        ctypes.memmove(ctypes.c_void_p(ptr), buf, size)
        kernel32.GlobalUnlock(ctypes.c_void_p(handle))
        ok = user32.SetClipboardData(_CF_UNICODETEXT, ctypes.c_void_p(handle))
        if not ok:
            kernel32.GlobalFree(ctypes.c_void_p(handle))
        return bool(ok)
    finally:
        user32.CloseClipboard()


def get_clipboard() -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.restype = ctypes.c_void_p
    if not user32.OpenClipboard(None):
        return ""
    try:
        if not user32.IsClipboardFormatAvailable(_CF_UNICODETEXT):
            return ""
        handle = user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(ctypes.c_void_p(handle))
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(ctypes.c_void_p(handle))
    finally:
        user32.CloseClipboard()


def paste_text(text: str, delay_ms: int = 60, restore: bool = False) -> bool:
    import keyboard  # 延迟导入：--selftest 不需要钩子

    old = get_clipboard() if restore else ""
    if not set_clipboard(text):
        return False
    time.sleep(max(delay_ms, 10) / 1000.0)
    keyboard.send("ctrl+v")
    if restore and old:
        threading.Timer(0.8, lambda: set_clipboard(old)).start()
    return True


# ---------------------------------------------------------------- 文本整理
_FILLER_HEAD = re.compile(r"^(?:嗯+|呃+|啊+|那个|那么|就是说)[，,、\s]*")
_FILLER_TAIL = re.compile(r"[，,、\s]*$")
_CJK = r"\u4e00-\u9fff"


def normalize_punct(text: str) -> str:
    """把 Whisper 输出的半角/竖排标点统一成中文全角。"""
    t = text
    t = t.replace("﹐", "，").replace("﹑", "、").replace("｡", "。")
    t = re.sub(rf"(?<=[{_CJK}]),", "，", t)
    t = re.sub(rf",(?=[{_CJK}])", "，", t)
    t = re.sub(rf"(?<=[{_CJK}])\?", "？", t)
    t = re.sub(rf"(?<=[{_CJK}])!", "！", t)
    t = re.sub(rf"(?<=[{_CJK}]);", "；", t)
    t = re.sub(r"(?<=[\u4e00-\u9fff)】」』]):", "：", t)
    t = re.sub(rf"(?<=[{_CJK}])\.(?=\s|$)", "。", t)
    t = re.sub(r"\s*([，。！？；：、])\s*", r"\1", t)
    return t


def clean_text(text: str, cfg: dict) -> str:
    t = text.strip().replace("\n", " ")
    if cfg.get("fullwidth_punct", True):
        t = normalize_punct(t)
    if cfg.get("strip_fillers", True):
        prev = None
        while prev != t:
            prev = t
            t = _FILLER_HEAD.sub("", t)
    if cfg.get("trim_trailing_punct", True):
        t = re.sub(r"[。．.！!？?；;]+$", "", t) if not t.endswith(("！", "？", "!")) else t
        t = _FILLER_TAIL.sub("", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t


_POLISH_PROMPT = (
    "你是语音输入的整理器。只做文字整理：去掉口头禅、修正错别字和语法、"
    "补全标点、把口语断句理顺。不要改写意思，不要扩写，不要回答问题，"
    "不要加任何解释或前后缀。直接输出整理后的正文。"
)


def deepseek_key() -> str:
    try:
        raw = CREDENTIALS.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"DEEPSEEK_API_KEY:\s*(\S+)", raw)
    return m.group(1) if m else ""


def polish(text: str, cfg: dict) -> str:
    key = deepseek_key()
    if not key:
        log("polish: 没找到 DEEPSEEK_API_KEY，跳过润色")
        return text
    payload = json.dumps(
        {
            "model": cfg.get("polish_model", "deepseek-chat"),
            "messages": [
                {"role": "system", "content": _POLISH_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("polish_timeout", 12)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = data["choices"][0]["message"]["content"].strip()
        return out or text
    except Exception as exc:  # 断网/超时/限流都退回原文
        log(f"polish 失败，用原文：{type(exc).__name__}: {exc}")
        return text


# ---------------------------------------------------------------- 录音
class Recorder:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.sr = 16000
        self._stream = None
        self._chunks: list = []
        self._t0 = 0.0
        self._auto_stop = False

    def start(self) -> None:
        import sounddevice as sd

        self._chunks = []
        self._auto_stop = False
        self._t0 = time.time()

        def cb(indata, frames, time_info, status):  # noqa: ANN001
            self._chunks.append(indata.copy())
            if (time.time() - self._t0) > self.cfg.get("max_seconds", 60):
                self._auto_stop = True

        for sr in (16000, 48000, 44100):
            try:
                self._stream = sd.InputStream(
                    samplerate=sr, channels=1, dtype="float32", callback=cb, blocksize=0
                )
                self._stream.start()
                self.sr = sr
                return
            except Exception as exc:  # noqa: BLE001
                log(f"录音启动 {sr}Hz 失败：{type(exc).__name__}: {exc}")
                self._stream = None
        raise RuntimeError("没有可用的录音设备")

    def stop(self):
        import numpy as np

        if self._stream is None:
            return None, 0.0
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        seconds = time.time() - self._t0
        if not self._chunks:
            return None, seconds
        audio = np.concatenate(self._chunks, axis=0).reshape(-1).astype("float32")
        if self.sr != 16000:
            n = int(len(audio) * 16000 / self.sr)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
            ).astype("float32")
        return audio, seconds

    @property
    def auto_stopped(self) -> bool:
        return self._auto_stop


# ---------------------------------------------------------------- 转写
def load_audio_16k(path) -> "object":
    """把音频文件读成 16k 单声道 float32 数组。

    wav 用标准库解码（不依赖第三方包）；其他格式回退到 av。
    """
    import numpy as np

    p = Path(path)
    if p.suffix.lower() == ".wav":
        import wave

        with wave.open(str(p), "rb") as w:
            sr = w.getframerate()
            ch = w.getnchannels()
            width = w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if width == 2:
            data = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
        elif width == 4:
            data = np.frombuffer(raw, dtype="<i4").astype("float32") / 2147483648.0
        else:
            u = np.frombuffer(raw, dtype="u1").astype("float32")
            data = (u - 128.0) / 128.0
        if ch > 1:
            data = data.reshape(-1, ch).mean(axis=1)
        if sr != 16000 and data.size:
            n = int(round(data.size * 16000 / sr))
            data = np.interp(np.linspace(0, data.size - 1, n), np.arange(data.size), data)
        return data.astype("float32")

    try:
        import av
    except ImportError:
        raise SystemExit(f"解不了 {p.suffix}，请先转成 wav（或安装 av）")
    parts = []
    with av.open(str(p)) as c:
        stream = c.streams.audio[0]
        res = av.audio.resampler.AudioResampler(format="flt", layout="mono", rate=16000)
        for frame in c.decode(stream):
            for f in res.resample(frame):
                parts.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            parts.append(f.to_ndarray().reshape(-1))
    if not parts:
        return np.zeros(0, dtype="float32")
    return np.concatenate(parts).astype("float32")


class Transcriber:
    """常驻模型；按需加载，支持空闲后卸载显存。"""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.engine = str(cfg.get("engine", "sensevoice")).lower()
        self.model = None
        self.device = "?"
        self.ready = threading.Event()
        self.error = ""
        self.last_use = 0.0
        self._load_lock = threading.Lock()

    def _build(self) -> bool:
        if self.engine == "sensevoice":
            return self._build_sensevoice()
        return self._build_whisper()

    def _build_sensevoice(self) -> bool:
        """SenseVoice via sherpa-onnx：纯 CPU，160 MB 模型，无需 CUDA。"""
        cfg = self.cfg
        model_dir = Path(cfg.get("sensevoice_dir") or (BASE / "models" / "sensevoice"))
        model_file = model_dir / "model.int8.onnx"
        tokens = model_dir / "tokens.txt"
        if not model_file.is_file() or not tokens.is_file():
            self.error = f"SenseVoice 模型缺失：{model_dir}"
            log(self.error)
            return False
        try:
            import numpy as np
            import sherpa_onnx

            t0 = time.time()
            recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model_file),
                tokens=str(tokens),
                num_threads=int(cfg.get("sensevoice_threads", 2)),
                use_itn=bool(cfg.get("use_itn", True)),
                language=str(cfg.get("sensevoice_language", "auto")),
                debug=False,
            )
            # 探针：真解一段静音，确认运行期不炸
            probe = recognizer.create_stream()
            probe.accept_waveform(16000, np.zeros(16000, dtype="float32"))
            recognizer.decode_stream(probe)
            self.model = recognizer
            self.device = "cpu/sensevoice"
            log(f"SenseVoice 就绪：{self.device}，加载 {time.time()-t0:.1f}s（{model_dir}）")
            return True
        except Exception as exc:  # noqa: BLE001
            self.error = f"SenseVoice 加载失败：{type(exc).__name__}: {str(exc)[:160]}"
            log(self.error)
            return False

    def _build_whisper(self) -> bool:
        cfg = self.cfg
        device = cfg.get("device", "auto")
        compute = cfg.get("compute_type", "int8_float16")
        attempts = []
        if device in ("auto", "cuda"):
            attempts += [("cuda", compute), ("cuda", "float16")]
        attempts += [("cpu", "int8")]
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            self.error = "没装 faster-whisper，无法使用 whisper 引擎（改用 engine=sensevoice）"
            log(self.error)
            return False

        for dev, ct in attempts:
            try:
                t0 = time.time()
                model = WhisperModel(cfg.get("model", "medium"), device=dev, compute_type=ct)
                # 真跑一小段，确认这个设备真的能用（cuBLAS 缺失之类只有推理时才炸）
                import numpy as np

                probe = np.zeros(16000, dtype="float32")
                list(model.transcribe(probe, language=None, beam_size=1)[0])
                self.model = model
                self.device = f"{dev}/{ct}"
                log(f"模型 {cfg.get('model')} 就绪：{self.device}，加载 {time.time()-t0:.1f}s")
                return True
            except Exception as exc:  # noqa: BLE001
                log(f"模型 {dev}/{ct} 加载失败：{type(exc).__name__}: {str(exc)[:160]}")
        self.error = "模型加载失败"
        log(self.error)
        return False

    def ensure(self) -> bool:
        if self.model is not None:
            return True
        with self._load_lock:
            if self.model is not None:
                return True
            return self._build()

    def warmup(self) -> None:
        self.ensure()
        self.ready.set()

    def unload(self) -> None:
        with self._load_lock:
            if self.model is None:
                return
            self.model = None
        import gc

        gc.collect()
        log("模型已卸载（空闲释放显存/内存）")

    def idle_guard(self) -> None:
        minutes = float(self.cfg.get("idle_unload_minutes", 0) or 0)
        if minutes <= 0:
            return
        while True:
            time.sleep(30)
            if self.model is not None and self.last_use:
                if (time.time() - self.last_use) > minutes * 60:
                    self.unload()

    def transcribe(self, audio) -> str:
        cfg = self.cfg
        if not self.ensure():
            return ""
        self.last_use = time.time()
        if self.engine == "sensevoice":
            if isinstance(audio, (str, Path)):
                audio = load_audio_16k(audio)
            stream = self.model.create_stream()
            stream.accept_waveform(16000, audio)
            self.model.decode_stream(stream)
            return (stream.result.text or "").strip()
        segments, _info = self.model.transcribe(
            audio,
            language=cfg.get("language") or None,
            beam_size=cfg.get("beam_size", 1),
            vad_filter=cfg.get("vad_filter", True),
            initial_prompt=cfg.get("initial_prompt") or None,
            hotwords=cfg.get("hotwords") or None,
            condition_on_previous_text=False,
        )
        return "".join(s.text for s in segments).strip()


# ---------------------------------------------------------------- 提示音 / 浮标
def beep(kind: str, cfg: dict) -> None:
    if not cfg.get("beep", True):
        return
    try:
        import winsound

        freq, dur = (880, 45) if kind == "start" else (1180, 55)
        if kind == "error":
            freq, dur = (420, 140)
        winsound.Beep(freq, dur)
    except Exception:
        pass


class Overlay:
    """右下角小浮标：不抢焦点、不进任务栏。"""

    def __init__(self) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.top = tk.Toplevel(self.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-alpha", 0.92)
        self.top.configure(bg="#1b1b1f")
        self.label = tk.Label(
            self.top,
            text="",
            bg="#1b1b1f",
            fg="#f2f2f2",
            font=("Microsoft YaHei UI", 11),
            padx=14,
            pady=7,
        )
        self.label.pack()
        self.top.withdraw()
        self._queue: queue.Queue = queue.Queue()
        self._poll()

    def _poll(self) -> None:
        try:
            while True:
                kind, text = self._queue.get_nowait()
                if kind == "show":
                    self.label.configure(text=text)
                    self.top.update_idletasks()
                    w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
                    sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
                    self.top.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 140}")
                    self.top.deiconify()
                elif kind == "hide":
                    self.top.withdraw()
                elif kind == "quit":
                    self.root.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    def show(self, text: str) -> None:
        self._queue.put(("show", text))

    def hide(self) -> None:
        self._queue.put(("hide", ""))

    def quit(self) -> None:
        self._queue.put(("quit", ""))

    def run(self) -> None:
        self.root.mainloop()


# ---------------------------------------------------------------- 热键
VK_MAP = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "pause": 0x13, "scroll lock": 0x91, "caps lock": 0x14, "tab": 0x09, "space": 0x20,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "page up": 0x21, "page down": 0x22,
    "left ctrl": 0xA2, "right ctrl": 0xA3, "left alt": 0xA4, "right alt": 0xA5,
    "left shift": 0xA0, "right shift": 0xA1,
    "mouse left": 0x01, "mouse right": 0x02, "mouse middle": 0x04,
}


def vk_of(name: str):
    """把键名换成虚拟键码；不认识返回 None。"""
    n = str(name).strip().lower()
    if n in VK_MAP:
        return VK_MAP[n]
    if len(n) == 1 and n.isprintable():
        return ord(n.upper())
    return None


class PollHotkey:
    """不装键盘钩子的全局热键：轮询 GetAsyncKeyState。

    为什么需要它：低层键盘钩子（keyboard 库用的那个）在部分环境下收不到
    任何事件——安全软件拦截、焦点在提权窗口、远程会话等。轮询走的是完全
    不同的机制，在这些环境里通常仍然可用。

    代价：不能拦截按键（suppress 无效），轮询间隔带来约 20ms 延迟。
    """

    def __init__(self, hotkey, on_down, on_up, quit_combo=None, on_quit=None, interval=0.02):
        self.hotkey = hotkey
        self.on_down = on_down
        self.on_up = on_up
        self.quit_combo = quit_combo
        self.on_quit = on_quit
        self.interval = interval
        self._alive = False
        self._thread = None

    def start(self) -> None:
        self._alive = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="poll-hotkey")
        self._thread.start()

    def stop(self) -> None:
        self._alive = False

    def _run(self) -> None:
        try:
            key_state = ctypes.windll.user32.GetAsyncKeyState
        except Exception as exc:  # noqa: BLE001
            log(f"热键轮询启动失败：{exc}")
            return

        vk = vk_of(self.hotkey)
        if vk is None:
            log(f"轮询后端不认识这个键名：{self.hotkey}")
            return

        quit_vks: list[int] = []
        if self.quit_combo:
            quit_vks = [vk_of(p) for p in str(self.quit_combo).split("+")]
        quit_ok = (
            self.on_quit is not None
            and bool(quit_vks)
            and all(quit_vks)  # type: ignore[arg-type]
        )

        down = False
        quit_down = False
        while self._alive:
            pressed = bool(key_state(vk) & 0x8000)
            if pressed and not down:
                try:
                    self.on_down()
                except Exception as exc:  # noqa: BLE001
                    log(f"热键按下处理出错：{exc}")
            elif not pressed and down:
                try:
                    self.on_up()
                except Exception as exc:  # noqa: BLE001
                    log(f"热键松开处理出错：{exc}")
            down = pressed

            if quit_ok:
                q = all(bool(key_state(k) & 0x8000) for k in quit_vks)
                if q and not quit_down:
                    try:
                        self.on_quit()
                    except Exception:  # noqa: BLE001
                        pass
                quit_down = q

            time.sleep(self.interval)


# ---------------------------------------------------------------- 主程序
class App:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.recorder = Recorder(cfg)
        self.transcriber = Transcriber(cfg)
        self.overlay = Overlay() if cfg.get("overlay", True) else None
        self.busy = threading.Lock()
        self.recording = False
        self._t_press = 0.0

    def ui(self, text: str | None) -> None:
        if not self.overlay:
            return
        if text is None:
            self.overlay.hide()
        else:
            self.overlay.show(text)

    def on_press(self) -> None:
        if self.recording:
            return
        if self.cfg.get("mode", "hold") == "toggle":
            self.toggle_on()
            return
        self.recording = True
        self._t_press = time.time()
        beep("start", self.cfg)
        try:
            self.recorder.start()
            self.ui("🎙 录音中…松开结束")
        except Exception as exc:  # noqa: BLE001
            self.recording = False
            log(f"录音失败：{exc}")
            beep("error", self.cfg)
            self.ui("⚠ 麦克风打不开")

    def toggle_on(self) -> None:
        self.recording = True
        self._t_press = time.time()
        beep("start", self.cfg)
        try:
            self.recorder.start()
            self.ui("🎙 录音中…再按一次结束")
        except Exception as exc:  # noqa: BLE001
            self.recording = False
            log(f"录音失败：{exc}")
            self.ui("⚠ 麦克风打不开")

    def on_release(self) -> None:
        if not self.recording or self.cfg.get("mode", "hold") == "toggle":
            return
        self.finish()

    def on_toggle(self) -> None:
        if self.cfg.get("mode", "hold") != "toggle" or not self.recording:
            return
        self.finish()

    def finish(self) -> None:
        if not self.recording:
            return
        self.recording = False
        audio, seconds = self.recorder.stop()
        if audio is None or seconds < self.cfg.get("min_seconds", 0.35):
            log(f"太短({seconds:.2f}s)，忽略")
            self.ui(None)
            return
        if self.transcriber.model is None:
            self.ui("⏳ 加载模型…（约 30 秒）")
        else:
            self.ui("✍ 识别中…")
        threading.Thread(target=self._work, args=(audio, seconds), daemon=True).start()

    def _work(self, audio, seconds: float) -> None:
        with self.busy:
            t0 = time.time()
            try:
                raw = self.transcriber.transcribe(audio)
            except Exception as exc:  # noqa: BLE001
                log(f"转写失败：{type(exc).__name__}: {exc}")
                beep("error", self.cfg)
                self.ui("⚠ 识别失败")
                time.sleep(0.8)
                self.ui(None)
                return
            t_asr = time.time() - t0
            text = clean_text(raw, self.cfg)
            if not text:
                log(f"空结果（{seconds:.1f}s 音频，{t_asr:.2f}s 转写）")
                self.ui(None)
                return
            if self.cfg.get("polish", False):
                self.ui("✨ 润色中…")
                text = polish(text, self.cfg)
            if self.cfg.get("dry_run", False):
                log(f"[dry-run] 不注入，结果：{text}")
                self.ui("🧪 dry-run：" + text[:24])
                time.sleep(1.0)
                self.ui(None)
                return
            ok = paste_text(
                text,
                delay_ms=self.cfg.get("paste_delay_ms", 60),
                restore=self.cfg.get("restore_clipboard", False),
            )
            total = time.time() - t0
            log(
                f"{'ok' if ok else 'paste-fail'} {seconds:.1f}s音频 asr={t_asr:.2f}s "
                f"总={total:.2f}s chars={len(text)} text={text[:60]!r}"
            )
            self.ui(None)
            if not ok:
                beep("error", self.cfg)

    def install_hooks(self) -> None:
        backend = str(self.cfg.get("hotkey_backend", "auto")).lower()
        if backend == "hook":
            self._install_hook()
            return
        try:
            self._install_poll()
        except Exception as exc:  # noqa: BLE001
            log(f"轮询热键启动失败：{exc}，回退到键盘钩子")
            self._install_hook()

    def _install_poll(self) -> None:
        hotkey = self.cfg.get("hotkey", "f9")
        mode = self.cfg.get("mode", "hold")
        quit_key = self.cfg.get("quit_hotkey")
        if mode == "hold":
            on_down, on_up = self.on_press, self.on_release
        else:

            def on_down() -> None:
                if not self.recording:
                    self.on_press()
                else:
                    self.on_toggle()

            on_up = lambda: None  # noqa: E731
        self._poll = PollHotkey(hotkey, on_down, on_up, quit_key, self.shutdown)
        self._poll.start()
        if self.cfg.get("suppress"):
            log("提示：轮询后端无法拦截按键，suppress 不生效")
        log(
            f"监听中（轮询）：{'按住' if mode == 'hold' else '按一下'} "
            f"{hotkey.upper()} 说话，{quit_key} 退出"
        )

    def _install_hook(self) -> None:
        import keyboard

        hotkey = self.cfg.get("hotkey", "f9")
        mode = self.cfg.get("mode", "hold")
        suppress = bool(self.cfg.get("suppress", False))
        if mode == "hold":
            keyboard.on_press_key(hotkey, lambda _e: self.on_press(), suppress=suppress)
            keyboard.on_release_key(hotkey, lambda _e: self.on_release(), suppress=suppress)
        else:
            keyboard.on_press_key(
                hotkey,
                lambda _e: self.on_press() if not self.recording else self.on_toggle(),
                suppress=suppress,
            )
        quit_key = self.cfg.get("quit_hotkey")
        if quit_key:
            keyboard.add_hotkey(quit_key, self.shutdown)
        log(f"监听中（钩子）：{'按住' if mode == 'hold' else '按一下'} {hotkey.upper()} 说话，{quit_key} 退出")

    def shutdown(self) -> None:
        log("收到退出指令")
        poll = getattr(self, "_poll", None)
        if poll is not None:
            try:
                poll.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            import keyboard

            keyboard.unhook_all()
        except Exception:
            pass
        if self.overlay:
            self.overlay.quit()
        os._exit(0)


# ---------------------------------------------------------------- 命令行
def cmd_selftest(cfg: dict, seconds: float) -> int:
    rec = Recorder(cfg)
    tr = Transcriber(cfg)
    print(f"加载模型 {cfg.get('model')} …", flush=True)
    tr.warmup()
    print(f"引擎：{tr.device}", flush=True)
    print(f"请说话，{seconds:.0f} 秒后自动结束…", flush=True)
    beep("start", cfg)
    rec.start()
    time.sleep(seconds)
    audio, dur = rec.stop()
    beep("start", cfg)
    if audio is None:
        print("没有录到音频")
        return 1
    import numpy as np

    rms = float(np.sqrt((audio**2).mean()))
    t0 = time.time()
    text = tr.transcribe(audio)
    dt = time.time() - t0
    print(f"录到 {dur:.2f}s（RMS={rms:.4f}）→ 转写 {dt:.2f}s")
    print("原文：", text)
    print("整理：", clean_text(text, cfg))
    return 0


def cmd_keytest(seconds: float) -> int:
    import keyboard

    print(f"{seconds:.0f} 秒内按你想绑定的键（Esc 提前结束）…", flush=True)
    seen: list[str] = []

    def handler(e):  # noqa: ANN001
        if e.event_type == "down" and e.name:
            if e.name not in seen:
                seen.append(e.name)
                print("  按键：", e.name, flush=True)

    keyboard.hook(handler)
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(0.05)
    keyboard.unhook_all()
    print("见过的键：", ", ".join(seen) if seen else "（没检测到）")
    return 0


def cmd_file(cfg: dict, path: str) -> int:
    tr = Transcriber(cfg)
    tr.warmup()
    t0 = time.time()
    text = tr.transcribe(path)
    print(f"{time.time()-t0:.2f}s → {text}")
    return 0


def cmd_text(cfg: dict, text: str, delay: float) -> int:
    print(f"{delay:.0f} 秒后把文字粘贴到当前焦点窗口…")
    time.sleep(delay)
    ok = paste_text(text, delay_ms=cfg.get("paste_delay_ms", 60))
    print("粘贴" + ("成功" if ok else "失败"))
    return 0 if ok else 1


def main() -> int:
    global CONFIG_PATH
    parser = argparse.ArgumentParser(description="全局按住说话离线语音输入")
    parser.add_argument("--config", default=None)
    parser.add_argument("--selftest", nargs="?", const=3.0, type=float, help="录 N 秒打印识别结果")
    parser.add_argument("--keytest", nargs="?", const=10.0, type=float, help="按键名检测")
    parser.add_argument("--file", help="用音频文件测转写")
    parser.add_argument("--text", help="直接把一段文字走注入链路（--delay 秒后执行）")
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()

    global CONFIG_PATH
    if args.config:
        CONFIG_PATH = Path(args.config)
    cfg = load_config()
    cuda_dll_dirs()

    if args.keytest:
        return cmd_keytest(args.keytest)
    if args.text:
        return cmd_text(cfg, args.text, args.delay)
    if args.file:
        return cmd_file(cfg, args.file)
    if args.selftest:
        return cmd_selftest(cfg, args.selftest)

    if not single_instance():
        log("已有实例在跑，退出")
        return 0

    cuda_dll_dirs()
    log("=" * 60)
    log(f"启动 voice-f9，配置 {CONFIG_PATH}")
    app = App(cfg)
    threading.Thread(target=app.transcriber.warmup, daemon=True).start()
    threading.Thread(target=app.transcriber.idle_guard, daemon=True).start()
    try:
        app.install_hooks()
    except Exception as exc:  # noqa: BLE001
        log(f"热键钩子安装失败：{type(exc).__name__}: {exc}")
        print("热键钩子装不上，可能需要在管理员权限下运行。", file=sys.stderr)
        return 2
    if app.overlay:
        app.overlay.show("voice-f9 就绪")
        app.overlay.root.after(1200, app.overlay.hide)
        app.overlay.run()
    else:
        while True:
            time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())