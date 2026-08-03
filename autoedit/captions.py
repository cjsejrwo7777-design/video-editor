"""faster-whisper 기반 자동 자막 생성 (STT -> 자막 청크 -> SRT / 화면 오버레이)."""
from __future__ import annotations

import textwrap
from dataclasses import dataclass

from .config import CaptionConfig

_MODEL_CACHE: dict[str, object] = {}


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _get_model(model_size: str):
    if model_size not in _MODEL_CACHE:
        from faster_whisper import WhisperModel

        # device="auto" + compute_type="int8" 조합은 일부 Windows/CPU 환경에서
        # 예외 없이 프로세스가 죽는 네이티브 크래시를 일으켜 device/compute_type을 명시한다.
        # GPU(CUDA)가 있으면 device="cuda", compute_type="float16" 으로 바꾸면 훨씬 빠름.
        _MODEL_CACHE[model_size] = WhisperModel(model_size, device="cpu", compute_type="float32")
    return _MODEL_CACHE[model_size]


def transcribe(audio_path: str, cfg: CaptionConfig) -> list[Word]:
    """오디오/영상 파일을 STT 해서 단어 단위 타임스탬프 리스트를 반환."""
    model = _get_model(cfg.model_size)
    segments, _info = model.transcribe(
        audio_path,
        language=cfg.language,
        word_timestamps=True,
        vad_filter=True,
    )
    words: list[Word] = []
    for seg in segments:
        if not seg.words:
            continue
        for w in seg.words:
            text = w.word.strip()
            if text:
                words.append(Word(start=w.start, end=w.end, text=text))
    return words


def words_to_cues(words: list[Word], cfg: CaptionConfig) -> list[Cue]:
    """단어들을 화면에 표시할 짧은 자막 덩어리(cue)로 묶는다 (CapCut식 짧은 캡션)."""
    max_chars = cfg.max_chars_per_line * cfg.max_lines
    cues: list[Cue] = []
    current: list[Word] = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            text = " ".join(w.text for w in current)
            cues.append(Cue(start=current[0].start, end=current[-1].end, text=text))
        current = []
        current_len = 0

    for w in words:
        added_len = len(w.text) + (1 if current else 0)
        ends_sentence = w.text.endswith((".", "?", "!", "다", "요", "죠", "니다"))
        if current and (current_len + added_len > max_chars):
            flush()
        current.append(w)
        current_len += added_len
        if ends_sentence and current_len >= max_chars * 0.6:
            flush()
    flush()
    return cues


def _wrap(text: str, cfg: CaptionConfig) -> str:
    lines = textwrap.wrap(text, width=cfg.max_chars_per_line)
    return "\n".join(lines[: cfg.max_lines])


def _fmt_ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[Cue], path: str) -> None:
    lines = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{_fmt_ts(cue.start)} --> {_fmt_ts(cue.end)}")
        lines.append(cue.text)
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def build_caption_clips(cues: list[Cue], cfg: CaptionConfig, video_size: tuple[int, int]):
    """Cue 리스트를 화면에 올릴 TextClip 목록으로 변환."""
    from moviepy import TextClip

    w, h = video_size
    clips = []
    for cue in cues:
        duration = max(0.05, cue.end - cue.start)
        txt = _wrap(cue.text, cfg)
        clip = TextClip(
            font=cfg.font,
            text=txt,
            font_size=cfg.font_size,
            color=cfg.color,
            stroke_color=cfg.stroke_color,
            stroke_width=cfg.stroke_width,
            method="caption",
            size=(int(w * 0.9), None),
            text_align="center",
            horizontal_align="center",
        ).with_start(cue.start).with_duration(duration)

        if cfg.position == "bottom":
            pos = ("center", h - cfg.margin - clip.h)
        elif cfg.position == "top":
            pos = ("center", cfg.margin)
        else:
            pos = ("center", "center")
        clip = clip.with_position(pos)
        clips.append(clip)
    return clips
