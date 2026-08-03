"""pycapcut로 실제 CapCut 드래프트(draft_content.json)를 생성하는 엔진.

moviepy 엔진(assembler.py)은 화면을 직접 합성해서 mp4로 렌더링하지만,
이 엔진은 원본 영상 파일을 건드리지 않고 '어느 구간을 어떤 순서로 재생할지'만
CapCut 드래프트에 기록한다. 최종 렌더링은 CapCut 앱 자체가 하기 때문에:
  - 화질 손실이 없다 (원본 소스를 그대로 참조)
  - CapCut의 진짜 자막 스타일/전환효과/필터를 쓸 수 있다
  - 사용자가 CapCut에서 열어서 자유롭게 다듬은 뒤 내보낼 수 있다
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from .config import Template

DEFAULT_CAPCUT_DRAFTS_DIRS = [
    r"%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft",
    r"%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft",
]


def find_default_drafts_folder() -> Optional[str]:
    """이 PC에 설치된 CapCut(또는 JianyingPro)의 드래프트 폴더를 자동으로 찾는다."""
    for template in DEFAULT_CAPCUT_DRAFTS_DIRS:
        path = os.path.expandvars(template)
        if os.path.isdir(path):
            return path
    return None


def _cover_crop_settings(material_w: int, material_h: int, target_w: int, target_h: int):
    """template.fit == 'cover' 를 흉내내는 크롭: 캔버스 비율에 맞게 원본의 위아래/좌우를 잘라낸다."""
    from pycapcut import CropSettings

    src_ratio = material_w / material_h
    tgt_ratio = target_w / target_h

    if abs(src_ratio - tgt_ratio) < 1e-6:
        return CropSettings()

    if src_ratio > tgt_ratio:
        # 원본이 더 넓다 -> 좌우를 crop
        keep = tgt_ratio / src_ratio
        margin = (1 - keep) / 2
        return CropSettings(
            upper_left_x=margin, upper_left_y=0.0,
            upper_right_x=1 - margin, upper_right_y=0.0,
            lower_left_x=margin, lower_left_y=1.0,
            lower_right_x=1 - margin, lower_right_y=1.0,
        )
    # 원본이 더 좁다(세로로 김) -> 위아래를 crop
    keep = src_ratio / tgt_ratio
    margin = (1 - keep) / 2
    return CropSettings(
        upper_left_x=0.0, upper_left_y=margin,
        upper_right_x=1.0, upper_right_y=margin,
        lower_left_x=0.0, lower_left_y=1 - margin,
        lower_right_x=1.0, lower_right_y=1 - margin,
    )


def _analyze_inputs(input_paths: list[str], silence_cfg):
    """각 입력 영상의 무음 컷 구간(초 단위)과 해상도를 계산한다. 렌더링은 하지 않는다."""
    from moviepy import VideoFileClip

    from .silence import detect_speech_segments

    results = []
    for path in input_paths:
        clip = VideoFileClip(path)
        try:
            if clip.audio is not None:
                segments = detect_speech_segments(clip.audio, silence_cfg)
            else:
                segments = [(0.0, clip.duration)]
            results.append({"path": path, "w": clip.w, "h": clip.h, "segments": segments})
        finally:
            clip.close()
    return results


def _write_stt_audio(analyzed: list[dict], tmp_wav_path: str) -> None:
    """무음 컷이 적용된 최종 타임라인과 동일한 오디오를 임시로 렌더링 (자막 타이밍 산출용)."""
    from moviepy import VideoFileClip, concatenate_audioclips
    from moviepy.audio.fx import AudioFadeIn, AudioFadeOut

    fade_s = 0.04
    audio_clips = []
    open_clips = []
    for item in analyzed:
        clip = VideoFileClip(item["path"])
        open_clips.append(clip)
        if clip.audio is None:
            continue
        for start, end in item["segments"]:
            sub = clip.audio.subclipped(start, end)
            if sub.duration > fade_s * 2:
                sub = sub.with_effects([AudioFadeIn(fade_s), AudioFadeOut(fade_s)])
            audio_clips.append(sub)

    if not audio_clips:
        for clip in open_clips:
            clip.close()
        return

    final_audio = concatenate_audioclips(audio_clips)
    final_audio.write_audiofile(tmp_wav_path, fps=16000, logger=None)
    for clip in open_clips:
        clip.close()


def _generate_srt(analyzed: list[dict], template: Template, srt_path: str) -> bool:
    """무음 컷 타임라인 기준으로 STT 실행 후 SRT 저장. 생성했으면 True 반환."""
    from . import captions as cap

    fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        _write_stt_audio(analyzed, tmp_wav)
        if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) == 0:
            return False
        words = cap.transcribe(tmp_wav, template.captions)
        if not words:
            return False
        cues = cap.words_to_cues(words, template.captions)
        cap.write_srt(cues, srt_path)
        return True
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)


def _caption_style_reference(template: Template):
    """템플릿의 CaptionConfig를 CapCut 텍스트 스타일(TextSegment)로 변환한다."""
    from pycapcut import ClipSettings, TextBorder, TextSegment, TextStyle, trange

    def _hex_to_rgb01(name: str) -> tuple[float, float, float]:
        table = {"white": (1.0, 1.0, 1.0), "black": (0.0, 0.0, 0.0)}
        if name in table:
            return table[name]
        if name.startswith("#") and len(name) == 7:
            r, g, b = int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16)
            return (r / 255, g / 255, b / 255)
        return (1.0, 1.0, 1.0)

    cfg = template.captions
    # CapCut 자막 기본 크기(8.0)를 기준으로 우리 템플릿의 font_size를 상대 변환
    size = cfg.font_size / 64 * 8.0

    if cfg.position == "bottom":
        transform_y = -0.75
    elif cfg.position == "top":
        transform_y = 0.75
    else:
        transform_y = 0.0

    style = TextStyle(size=size, color=_hex_to_rgb01(cfg.color), align=1, auto_wrapping=True)
    border = TextBorder(color=_hex_to_rgb01(cfg.stroke_color), width=cfg.stroke_width * 10)
    return TextSegment(
        "샘플",
        trange(0, "1s"),
        style=style,
        border=border,
        clip_settings=ClipSettings(transform_y=transform_y),
    )


def _add_bgm_track(script, music_cfg, total_duration_us: int) -> None:
    from pycapcut import AudioMaterial, AudioSegment, Timerange, TrackType

    material = AudioMaterial(music_cfg.path)
    script.add_track(TrackType.audio, "배경음악")

    fade_in = min(1_000_000, max(1, total_duration_us // 10))
    fade_out = fade_in

    cursor = 0
    is_first = True
    while cursor < total_duration_us:
        remaining = total_duration_us - cursor
        chunk = min(material.duration, remaining)
        is_last = chunk == remaining
        seg = AudioSegment(
            material,
            Timerange(cursor, chunk),
            source_timerange=Timerange(0, chunk),
            volume=music_cfg.volume,
        )
        in_dur = fade_in if is_first else 0
        out_dur = fade_out if is_last else 0
        if in_dur or out_dur:
            seg.add_fade(in_dur, out_dur)
        script.add_segment(seg, "배경음악")
        cursor += chunk
        is_first = False


def build_draft(
    input_paths: list[str],
    template: Template,
    drafts_folder: str,
    draft_name: str,
    generate_captions: bool = True,
    allow_replace: bool = True,
    progress_cb=None,
):
    """CapCut 드래프트를 생성하고 저장한다. 완성된 `ScriptFile`을 반환한다."""
    from pycapcut import DraftFolder, Timerange, TrackType, VideoMaterial, VideoSegment

    def report(msg: str):
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    report("[1/4] 입력 영상 분석 및 무음 구간 계산 중...")
    analyzed = _analyze_inputs(input_paths, template.silence)

    dfolder = DraftFolder(drafts_folder)
    width, height = template.resolution
    script = dfolder.create_draft(draft_name, width, height, template.fps, allow_replace=allow_replace)
    script.add_track(TrackType.video, "video")

    report("[2/4] 무음 컷 구간을 타임라인에 배치 중 (원본 화질 유지)...")
    cursor_us = 0
    for item in analyzed:
        crop = _cover_crop_settings(item["w"], item["h"], width, height)
        material = VideoMaterial(item["path"], crop_settings=crop)
        for start, end in item["segments"]:
            start_us = int(round(start * 1_000_000))
            dur_us = int(round((end - start) * 1_000_000))
            if dur_us <= 0:
                continue
            seg = VideoSegment(
                material,
                Timerange(cursor_us, dur_us),
                source_timerange=Timerange(start_us, dur_us),
            )
            script.add_segment(seg, "video")
            cursor_us += dur_us

    if template.music.enabled and template.music.path:
        report("[3/4] 배경음악 트랙 추가 중...")
        _add_bgm_track(script, template.music, cursor_us)
    else:
        report("[3/4] 배경음악 건너뜀")

    if generate_captions and template.captions.enabled:
        report("[4/4] 오디오 추출 및 자동 자막 생성 중 (STT)...")
        draft_dir = os.path.join(drafts_folder, draft_name)
        srt_path = os.path.join(draft_dir, "auto_captions.srt")
        ok = _generate_srt(analyzed, template, srt_path)
        if ok:
            style_ref = _caption_style_reference(template)
            script.import_srt(srt_path, "자막", style_reference=style_ref, clip_settings=None)
        else:
            report("(음성이 감지되지 않아 자막을 생성하지 못했습니다)")
    else:
        report("[4/4] 자막 생성 건너뜀")

    script.save()
    report(f"완료: CapCut 드래프트 '{draft_name}' 저장됨 ({drafts_folder})")
    return script
