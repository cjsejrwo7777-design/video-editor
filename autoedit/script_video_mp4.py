"""대본 + 사진 -> mp4 (CapCut 없이 바로 재생 가능한 파일).

script_video.py와 같은 이미지 배치 로직(순서대로/키워드/자동 스톡 검색)을 그대로 쓰되,
CapCut 드래프트 대신 moviepy로 즉시 mp4 파일까지 렌더링한다.
CapCut 사용법을 몰라도 결과물을 더블클릭해서 바로 볼 수 있다.
"""
from __future__ import annotations

import os

from .assembler import _add_bgm, _fit_to_resolution
from .config import Template
from .script_video import (
    _fetch_auto_stock_groups,
    _group_cues_by_image,
    _match_images_by_keyword,
)
from .tts import DEFAULT_VOICE, synthesize_narration


def _make_kenburns_clip(image_path: str, duration: float, resolution: tuple[int, int], zoom_ratio: float, zoom_in: bool):
    from moviepy import CompositeVideoClip, ImageClip

    clip = ImageClip(image_path).with_duration(duration)
    fitted = _fit_to_resolution(clip, resolution, "cover")

    start_scale, end_scale = (1.0, zoom_ratio) if zoom_in else (zoom_ratio, 1.0)

    def scale_at(t: float) -> float:
        progress = t / duration if duration > 0 else 0
        return start_scale + (end_scale - start_scale) * progress

    zoomed = fitted.resized(scale_at).with_position("center")
    return CompositeVideoClip([zoomed], size=resolution).with_duration(duration)


def render_script_video(
    lines: list[str],
    image_paths: list[str],
    template: Template,
    output_path: str,
    voice: str = DEFAULT_VOICE,
    zoom_ratio: float = 1.12,
    match_mode: str = "order",
    pexels_api_key: str | None = None,
    generate_captions: bool = True,
    progress_cb=None,
) -> None:
    """대본+사진으로 mp4 영상을 만들어 output_path에 저장한다."""
    from moviepy import AudioFileClip, CompositeVideoClip, concatenate_audioclips

    from . import captions as cap

    def report(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    lines = [line.strip() for line in lines if line.strip()]
    if not lines:
        raise ValueError("대본이 비어 있습니다.")
    if match_mode == "auto_stock":
        if not pexels_api_key:
            raise ValueError("자동 이미지 검색을 쓰려면 Pexels API 키가 필요합니다.")
    elif not image_paths:
        raise ValueError("사진을 하나 이상 추가해주세요.")

    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    narration_dir = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(output_path))[0]}_narration")

    report("[1/5] 나레이션 음성 생성 중 (edge-tts)...")
    cues = synthesize_narration(lines, voice, narration_dir, progress_cb=report)
    if not cues:
        raise ValueError("나레이션 생성에 실패했습니다.")

    if match_mode == "auto_stock":
        report("[2/5] 대본에 맞는 사진을 자동으로 검색하는 중 (Pexels)...")
        groups = _fetch_auto_stock_groups(cues, pexels_api_key, out_dir, template.resolution, progress_cb=report)
    else:
        report("[2/5] 사진을 대본 타이밍에 맞춰 배치 중...")
        if match_mode == "keyword":
            groups = _match_images_by_keyword(image_paths, cues)
        else:
            groups = _group_cues_by_image(image_paths, cues)

    report("[3/5] Ken Burns 줌 적용 및 화면 합성 중...")
    image_clips = []
    for i, (img_path, start, end) in enumerate(groups):
        duration = end - start
        if duration <= 0:
            continue
        clip = _make_kenburns_clip(img_path, duration, template.resolution, zoom_ratio, zoom_in=(i % 2 == 0))
        clip = clip.with_start(start)
        image_clips.append(clip)

    total_duration = cues[-1].end
    video = CompositeVideoClip(image_clips, size=template.resolution).with_duration(total_duration)
    video = video.with_fps(template.fps)

    report("[4/5] 나레이션 오디오 합치는 중...")
    narration_audio = concatenate_audioclips([AudioFileClip(cue.path) for cue in cues])
    video = video.with_audio(narration_audio)
    video = _add_bgm(video, template.music)

    if generate_captions and template.captions.enabled:
        report("[5/5] 자막 합성 중...")
        caption_cues = [cap.Cue(start=c.start, end=c.end, text=c.text) for c in cues]
        caption_clips = cap.build_caption_clips(caption_cues, template.captions, template.resolution)
        video = CompositeVideoClip([video, *caption_clips], size=template.resolution)
    else:
        report("[5/5] 자막 생성 건너뜀")

    video.write_videofile(
        output_path,
        fps=template.fps,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )

    report(f"완료: {output_path}")
