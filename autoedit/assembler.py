"""무음 컷 -> 크기 맞춤 -> 인트로/아웃트로 -> 배경음악 -> 자막까지 전체 조립/렌더링."""
from __future__ import annotations

import os
import tempfile

from .config import Template
from .silence import detect_speech_segments, total_kept_duration


def _fit_to_resolution(clip, resolution: tuple[int, int], fit: str):
    target_w, target_h = resolution
    if fit == "contain":
        scale = min(target_w / clip.w, target_h / clip.h)
        resized = clip.resized(scale)
        return resized.with_background_color(
            size=resolution,
            color=(0, 0, 0),
            pos="center",
        )
    # cover (기본): 화면을 꽉 채우고 남는 부분은 중앙 기준으로 crop
    scale = max(target_w / clip.w, target_h / clip.h)
    resized = clip.resized(scale)
    return resized.cropped(
        x_center=resized.w / 2,
        y_center=resized.h / 2,
        width=target_w,
        height=target_h,
    )


def _trim_silence(clip, silence_cfg):
    """clip(영상)에서 무음 구간을 잘라낸 새 클립과, 남긴 구간 목록을 반환."""
    from moviepy import concatenate_videoclips
    from moviepy.audio.fx import AudioFadeIn, AudioFadeOut

    if clip.audio is None:
        return clip, [(0.0, clip.duration)]

    segments = detect_speech_segments(clip.audio, silence_cfg)
    if len(segments) == 1 and segments[0] == (0.0, clip.duration):
        return clip, segments

    fade_s = silence_cfg.crossfade_ms / 1000
    subclips = []
    for start, end in segments:
        sub = clip.subclipped(start, end)
        if sub.audio is not None and sub.duration > fade_s * 2:
            sub = sub.with_audio(sub.audio.with_effects([AudioFadeIn(fade_s), AudioFadeOut(fade_s)]))
        subclips.append(sub)

    trimmed = concatenate_videoclips(subclips, method="chain")
    return trimmed, segments


def _add_bgm(video_clip, music_cfg):
    from moviepy import AudioFileClip, CompositeAudioClip
    from moviepy.audio.fx import AudioLoop, MultiplyVolume

    if not music_cfg.enabled or not music_cfg.path:
        return video_clip

    bgm = AudioFileClip(music_cfg.path)
    if bgm.duration < video_clip.duration:
        bgm = bgm.with_effects([AudioLoop(duration=video_clip.duration)])
    else:
        bgm = bgm.subclipped(0, video_clip.duration)
    bgm = bgm.with_effects([MultiplyVolume(music_cfg.volume)])

    if video_clip.audio is not None:
        mixed = CompositeAudioClip([video_clip.audio, bgm])
    else:
        mixed = bgm
    return video_clip.with_audio(mixed)


def _load_and_prepare(path: str, template: Template):
    from moviepy import VideoFileClip

    clip = VideoFileClip(path)
    trimmed, segments = _trim_silence(clip, template.silence)
    fitted = _fit_to_resolution(trimmed, template.resolution, template.fit)
    fitted = fitted.with_fps(template.fps)
    return fitted, segments


def build_edited_video(input_paths: list[str], template: Template):
    """무음 컷 + 리사이즈 + 인트로/아웃트로 + 배경음악까지 적용된 최종 클립을 반환 (자막 제외)."""
    from moviepy import VideoFileClip, concatenate_videoclips

    parts = []
    total_original = 0.0
    total_kept = 0.0

    if template.intro:
        intro_clip = VideoFileClip(template.intro)
        parts.append(_fit_to_resolution(intro_clip, template.resolution, template.fit).with_fps(template.fps))

    for path in input_paths:
        fitted, segments = _load_and_prepare(path, template)
        parts.append(fitted)
        total_kept += total_kept_duration(segments)

    if template.outro:
        outro_clip = VideoFileClip(template.outro)
        parts.append(_fit_to_resolution(outro_clip, template.resolution, template.fit).with_fps(template.fps))

    final = parts[0] if len(parts) == 1 else concatenate_videoclips(parts, method="chain")
    final = _add_bgm(final, template.music)
    return final


def render(
    input_paths: list[str],
    template: Template,
    output_path: str,
    generate_captions: bool = True,
    srt_path: str | None = None,
    progress_cb=None,
) -> None:
    """전체 파이프라인 실행: 무음 컷 -> 조립 -> (선택)자막 -> 파일로 렌더링."""

    def report(msg: str):
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    report("[1/4] 무음 구간 분석 및 컷 편집 중...")
    final = build_edited_video(input_paths, template)

    caption_clips = []
    tmp_audio_path = None
    if generate_captions and template.captions.enabled and final.audio is not None:
        report("[2/4] 오디오 추출 및 자동 자막 생성 중 (STT)...")
        from . import captions as cap

        fd, tmp_audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        final.audio.write_audiofile(tmp_audio_path, fps=16000, logger=None)

        words = cap.transcribe(tmp_audio_path, template.captions)
        cues = cap.words_to_cues(words, template.captions)
        if srt_path:
            cap.write_srt(cues, srt_path)
        caption_clips = cap.build_caption_clips(cues, template.captions, template.resolution)
    else:
        report("[2/4] 자막 생성 건너뜀")

    if caption_clips:
        from moviepy import CompositeVideoClip

        report("[3/4] 자막 합성 중...")
        final = CompositeVideoClip([final, *caption_clips], size=template.resolution)
    else:
        report("[3/4] 합성 단계 건너뜀 (자막 없음)")

    report("[4/4] 최종 영상 렌더링 중...")
    final.write_videofile(
        output_path,
        fps=template.fps,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )

    if tmp_audio_path and os.path.exists(tmp_audio_path):
        os.remove(tmp_audio_path)

    report(f"완료: {output_path}")
