"""템플릿(.json) 로딩 및 설정 데이터 구조."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SilenceConfig:
    thresh_db: float = -35.0       # 이 값보다 조용하면 '무음'으로 판단
    min_silence_ms: int = 450      # 이보다 긴 무음만 잘라냄 (짧은 호흡/쉼표는 자연스럽게 유지)
    min_speech_ms: int = 250       # 이보다 짧은 소리 조각은 잡음으로 보고 제거
    pad_ms: int = 120              # 컷 경계에 남기는 여유(패딩) - 말이 잘리는 것 방지
    crossfade_ms: int = 40         # 컷 경계 오디오 마이크로 크로스페이드(클릭/팝 노이즈 방지)


@dataclass
class CaptionConfig:
    enabled: bool = True
    language: str = "ko"
    model_size: str = "small"
    font: str = r"C:\Windows\Fonts\malgunbd.ttf"
    font_size: int = 64
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 3
    position: str = "bottom"       # bottom | center | top
    margin: int = 140
    max_chars_per_line: int = 16
    max_lines: int = 2


@dataclass
class MusicConfig:
    enabled: bool = False
    path: str | None = None
    volume: float = 0.15
    duck_volume: float = 0.06      # 말하는 구간에서 배경음 볼륨을 낮춤(자연스러운 흐름)


@dataclass
class Template:
    name: str = "default"
    resolution: tuple[int, int] = (1920, 1080)
    fit: str = "cover"             # cover | contain
    fps: int = 30
    silence: SilenceConfig = field(default_factory=SilenceConfig)
    captions: CaptionConfig = field(default_factory=CaptionConfig)
    music: MusicConfig = field(default_factory=MusicConfig)
    intro: str | None = None
    outro: str | None = None

    @staticmethod
    def load(path: str | Path) -> "Template":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        silence = SilenceConfig(**data.get("silence", {}))
        captions = CaptionConfig(**data.get("captions", {}))
        music = MusicConfig(**data.get("music", {}))
        resolution = tuple(data.get("resolution", [1920, 1080]))
        return Template(
            name=data.get("name", "default"),
            resolution=resolution,
            fit=data.get("fit", "cover"),
            fps=data.get("fps", 30),
            silence=silence,
            captions=captions,
            music=music,
            intro=data.get("intro"),
            outro=data.get("outro"),
        )
