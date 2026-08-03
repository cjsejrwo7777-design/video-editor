"""오디오 RMS 분석 기반 무음/발화 구간 감지.

pydub(=audioop 의존, Python 3.13+ 에서 제거됨) 대신 moviepy가 이미 들고 있는
numpy 오디오 배열을 직접 분석해서 외부 의존성을 늘리지 않는다.
"""
from __future__ import annotations

import numpy as np

from .config import SilenceConfig


def _to_mono_array(audioclip) -> tuple[np.ndarray, int]:
    # moviepy(2.1.2)의 to_soundarray(fps=...)는 특정 다운샘플 비율(예: 16000Hz)에서
    # 무음(전부 0)을 반환하는 버그가 있어, 리샘플링 없이 원본 fps로 읽는다.
    fps = int(audioclip.fps or 44100)
    arr = audioclip.to_soundarray(fps=fps)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    return arr, fps


def _rms_envelope(arr: np.ndarray, fps: int, window_ms: int) -> np.ndarray:
    window = max(1, int(fps * window_ms / 1000))
    n = len(arr) // window
    if n == 0:
        return np.array([])
    trimmed = arr[: n * window]
    reshaped = trimmed.reshape(n, window)
    return np.sqrt(np.mean(reshaped**2, axis=1) + 1e-12)


def _to_db(x: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.maximum(x, 1e-8))


def detect_speech_segments(
    audioclip,
    cfg: SilenceConfig,
    window_ms: int = 20,
) -> list[tuple[float, float]]:
    """오디오 클립에서 '남길' 발화 구간 (start, end) 초 단위 리스트를 반환.

    - min_silence_ms 보다 짧은 무음(자연스러운 숨쉬기/쉼표)은 잘라내지 않고 유지한다.
    - min_speech_ms 보다 짧은 소리 조각은 잡음으로 보고 제거한다.
    - pad_ms 만큼 앞뒤 여유를 남겨 단어가 잘리지 않게 한다.
    """
    duration = audioclip.duration
    arr, analysis_fps = _to_mono_array(audioclip)
    if len(arr) == 0:
        return [(0.0, duration)]

    rms = _rms_envelope(arr, analysis_fps, window_ms)
    if len(rms) == 0:
        return [(0.0, duration)]

    levels = _to_db(rms)
    is_speech = levels > cfg.thresh_db
    window_s = window_ms / 1000

    segments: list[tuple[float, float]] = []
    start = None
    for i, sp in enumerate(is_speech):
        t = i * window_s
        if sp and start is None:
            start = t
        elif not sp and start is not None:
            segments.append((start, t))
            start = None
    if start is not None:
        segments.append((start, len(is_speech) * window_s))

    if not segments:
        return [(0.0, duration)]

    # 서로 가까운 발화 구간 사이의 짧은 무음은 자연스러운 흐름을 위해 유지(병합)
    merged = [segments[0]]
    for s, e in segments[1:]:
        prev_s, prev_e = merged[-1]
        gap_ms = (s - prev_e) * 1000
        if gap_ms < cfg.min_silence_ms:
            merged[-1] = (prev_s, e)
        else:
            merged.append((s, e))

    # 너무 짧은 소리 조각(잡음) 제거
    filtered = [(s, e) for s, e in merged if (e - s) * 1000 >= cfg.min_speech_ms]
    if not filtered:
        filtered = merged

    # 패딩 적용 후 클립 범위로 클램프
    pad = cfg.pad_ms / 1000
    padded = [(max(0.0, s - pad), min(duration, e + pad)) for s, e in filtered]

    # 패딩으로 인해 겹치는 구간 병합
    final = [padded[0]]
    for s, e in padded[1:]:
        prev_s, prev_e = final[-1]
        if s <= prev_e:
            final[-1] = (prev_s, max(prev_e, e))
        else:
            final.append((s, e))

    return final


def total_kept_duration(segments: list[tuple[float, float]]) -> float:
    return sum(e - s for s, e in segments)
