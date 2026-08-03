"""edge-tts로 대본 줄 단위 나레이션을 생성하고, 줄마다 실제 타이밍(cue)을 계산한다.

API 키나 비용 없이 쓸 수 있는 Microsoft Edge 온라인 TTS를 사용한다.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

VOICE_OPTIONS = [
    {"id": "sunhi", "gender": "female", "name": "선희", "voice": "ko-KR-SunHiNeural"},
    {"id": "jimin", "gender": "female", "name": "지민", "voice": "ko-KR-JiMinNeural"},
    {"id": "seohyeon", "gender": "female", "name": "서현", "voice": "ko-KR-SeoHyeonNeural"},
    {"id": "soonbok", "gender": "female", "name": "순복", "voice": "ko-KR-SoonBokNeural"},
    {"id": "yujin", "gender": "female", "name": "유진", "voice": "ko-KR-YuJinNeural"},
    {"id": "injoon", "gender": "male", "name": "인준", "voice": "ko-KR-InJoonNeural"},
    {"id": "hyunsu", "gender": "male", "name": "현수", "voice": "ko-KR-HyunsuNeural"},
    {"id": "bongjin", "gender": "male", "name": "봉진", "voice": "ko-KR-BongJinNeural"},
    {"id": "gookmin", "gender": "male", "name": "국민", "voice": "ko-KR-GookMinNeural"},
]
DEFAULT_VOICE = "ko-KR-SunHiNeural"


@dataclass
class NarrationCue:
    path: str
    text: str
    start: float  # 초
    end: float  # 초


def _probe_duration(path: str) -> float:
    from moviepy import AudioFileClip

    clip = AudioFileClip(path)
    try:
        return clip.duration
    finally:
        clip.close()


async def _synthesize_one(text: str, voice: str, path: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(path)


async def _synthesize_all(lines: list[str], voice: str, out_dir: str, progress_cb=None) -> list[NarrationCue]:
    os.makedirs(out_dir, exist_ok=True)
    cues: list[NarrationCue] = []
    cursor = 0.0
    for i, line in enumerate(lines, start=1):
        path = os.path.join(out_dir, f"{i:03d}.mp3")
        await _synthesize_one(line, voice, path)
        duration = _probe_duration(path)
        cues.append(NarrationCue(path=path, text=line, start=cursor, end=cursor + duration))
        cursor += duration
        if progress_cb:
            progress_cb(f"  나레이션 {i}/{len(lines)} 생성 완료")
    return cues


def synthesize_narration(lines: list[str], voice: str, out_dir: str, progress_cb=None) -> list[NarrationCue]:
    """대본 줄들을 음성으로 합성하고, 줄마다 (시작,끝) 타이밍을 반환한다."""
    return asyncio.run(_synthesize_all(lines, voice, out_dir, progress_cb))
