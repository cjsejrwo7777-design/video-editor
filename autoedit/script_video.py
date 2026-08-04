"""대본 + 사진 -> CapCut 드래프트.

edge-tts로 나레이션을 만들고, 사진들을 대본 타이밍에 맞춰 배치한 뒤
CapCut 네이티브 키프레임으로 부드러운 Ken Burns 줌, 전환효과, 자막을 입힌
드래프트를 생성한다. moviepy로 프레임을 직접 그리는 것보다 화질이 선명하고
확대/축소가 매끄러우며, CapCut에서 바로 다듬을 수 있다.
"""
from __future__ import annotations

import os

from .capcut_export import (
    _add_bgm_track,
    _caption_style_reference,
    _cover_crop_settings,
    _register_in_root_index,
)
from .config import Template
from .tts import NarrationCue, synthesize_narration

DEFAULT_VOICE = "ko-KR-SunHiNeural"


def _group_cues_by_image(image_paths: list[str], cues: list[NarrationCue]) -> list[tuple[str, float, float]]:
    """대본 줄 타이밍(cues)을 사진 개수만큼 그룹으로 묶어 (사진경로, 시작, 끝) 목록을 만든다."""
    if not cues or not image_paths:
        return []

    total_start = cues[0].start
    total_end = cues[-1].end
    total_duration = total_end - total_start

    if len(image_paths) > len(cues):
        # 사진이 대본 줄보다 많으면 내용과 정확히 맞출 수 없어 시간을 균등 분배한다.
        n = len(image_paths)
        per = total_duration / n
        return [(img, total_start + per * i, total_start + per * (i + 1)) for i, img in enumerate(image_paths)]

    n = len(image_paths)
    m = len(cues)
    base, remainder = divmod(m, n)
    groups: list[tuple[str, float, float]] = []
    idx = 0
    for i in range(n):
        count = base + (1 if i < remainder else 0)
        chunk = cues[idx: idx + count]
        idx += count
        groups.append((image_paths[i], chunk[0].start, chunk[-1].end))
    return groups


def _merge_consecutive_groups(
    assigned: list[str], cues: list[NarrationCue],
) -> list[tuple[str, float, float]]:
    """줄마다 배정된 사진 목록에서, 연속으로 같은 사진이 배정된 줄들을 하나의 구간으로 묶는다."""
    groups: list[tuple[str, float, float]] = []
    i = 0
    n = len(cues)
    while i < n:
        img = assigned[i]
        j = i
        while j + 1 < n and assigned[j + 1] == img:
            j += 1
        groups.append((img, cues[i].start, cues[j].end))
        i = j + 1
    return groups


def _match_images_by_keyword(image_paths: list[str], cues: list[NarrationCue]) -> list[tuple[str, float, float]]:
    """사진 파일명(확장자 제외)을 키워드로 보고, 그 단어가 포함된 대본 줄이 나올 때 그 사진을 배치한다.

    예) '동물.jpg' -> 대본에 "동물"이 들어간 줄이 나오면 그 사진이 나타남.
    어떤 줄에도 키워드가 안 걸리면 바로 이전에 매칭됐던 사진을 이어서 사용한다.
    """
    if not cues or not image_paths:
        return []

    keyword_pairs = [(os.path.splitext(os.path.basename(p))[0], p) for p in image_paths]

    assigned: list[str | None] = []
    last_matched: str | None = None
    for cue in cues:
        matched: str | None = None
        for keyword, img in keyword_pairs:
            if keyword and keyword in cue.text:
                matched = img
                break
        if matched is None:
            matched = last_matched
        else:
            last_matched = matched
        assigned.append(matched)

    # 맨 앞부터 매칭이 하나도 안 됐다면, 나중에 처음 매칭된 사진으로 앞부분을 채운다.
    first_idx = next((i for i, a in enumerate(assigned) if a is not None), None)
    if first_idx is not None:
        for i in range(first_idx):
            assigned[i] = assigned[first_idx]
    else:
        assigned = [image_paths[0]] * len(cues)

    return _merge_consecutive_groups(assigned, cues)


def _fetch_auto_stock_groups(
    cues: list[NarrationCue], api_key: str, draft_dir: str, resolution: tuple[int, int], progress_cb=None,
) -> list[tuple[str, float, float]]:
    """대본 줄마다 Pexels에서 스톡 사진을 자동 검색·다운로드해서 배치한다."""
    from . import stock_media

    def report(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    width, height = resolution
    orientation = "portrait" if height >= width else "landscape"

    stock_dir = os.path.join(draft_dir, "stock_images")
    os.makedirs(stock_dir, exist_ok=True)

    assigned: list[str] = []
    last_path: str | None = None
    for i, cue in enumerate(cues, start=1):
        dest_path = os.path.join(stock_dir, f"{i:03d}.jpg")
        try:
            found = stock_media.fetch_stock_photo(cue.text, api_key, dest_path, orientation=orientation)
        except Exception as e:
            if last_path is None:
                raise
            report(f"  사진 {i}/{len(cues)} 검색 실패({e}), 이전 사진으로 대체")
            assigned.append(last_path)
            continue

        if found:
            assigned.append(dest_path)
            last_path = dest_path
            report(f"  사진 {i}/{len(cues)} 검색 완료")
        elif last_path is not None:
            assigned.append(last_path)
            report(f"  사진 {i}/{len(cues)} 검색 결과 없음, 이전 사진으로 대체")
        else:
            raise ValueError(f"'{cue.text}'에 맞는 사진을 찾지 못했습니다. 대본 표현을 바꿔서 다시 시도해보세요.")

    return _merge_consecutive_groups(assigned, cues)


def _generate_image_cover(image_path: str | None, draft_dir: str, resolution: tuple[int, int]) -> None:
    if not image_path:
        return
    import subprocess

    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    width, height = resolution
    cover_path = os.path.join(draft_dir, "draft_cover.jpg")
    subprocess.run(
        [ffmpeg, "-y", "-i", image_path, "-frames:v", "1", "-vf", f"scale={width}:{height}", cover_path],
        capture_output=True,
    )


def build_script_draft(
    lines: list[str],
    image_paths: list[str],
    template: Template,
    drafts_folder: str,
    draft_name: str,
    voice: str = DEFAULT_VOICE,
    zoom_ratio: float = 1.12,
    transition_name: str | None = "叠化",
    transition_ms: int = 400,
    match_mode: str = "order",
    pexels_api_key: str | None = None,
    generate_captions: bool = True,
    allow_replace: bool = True,
    progress_cb=None,
):
    """대본+사진으로 CapCut 드래프트를 만들고 저장한다. 완성된 `ScriptFile`을 반환한다.

    match_mode="auto_stock" 이면 image_paths 없이도 Pexels에서 사진을 자동으로 찾아 채운다
    (이 경우 pexels_api_key 필수).
    """
    from pycapcut import (
        AudioMaterial,
        AudioSegment,
        DraftFolder,
        KeyframeProperty,
        TextSegment,
        Timerange,
        TrackType,
        TransitionType,
        VideoMaterial,
        VideoSegment,
    )

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

    dfolder = DraftFolder(drafts_folder)
    width, height = template.resolution
    script = dfolder.create_draft(draft_name, width, height, template.fps, allow_replace=allow_replace)
    draft_dir = os.path.join(drafts_folder, draft_name)

    # CapCut은 드래프트를 열 때마다 나레이션 mp3 경로를 다시 읽으므로,
    # 임시 폴더가 아니라 드래프트 폴더 안에 영구적으로 저장해야 한다.
    narration_dir = os.path.join(draft_dir, "narration")

    report("[1/5] 나레이션 음성 생성 중 (edge-tts)...")
    cues = synthesize_narration(lines, voice, narration_dir, progress_cb=report)
    if not cues:
        raise ValueError("나레이션 생성에 실패했습니다.")

    total_duration_us = int(round(cues[-1].end * 1_000_000))

    if match_mode == "auto_stock":
        report("[2/5] 대본에 맞는 사진을 자동으로 검색하는 중 (Pexels)...")
        groups = _fetch_auto_stock_groups(cues, pexels_api_key, draft_dir, template.resolution, progress_cb=report)
    else:
        report("[2/5] 사진을 대본 타이밍에 맞춰 배치 중...")
        if match_mode == "keyword":
            groups = _match_images_by_keyword(image_paths, cues)
        else:
            groups = _group_cues_by_image(image_paths, cues)

    script.add_track(TrackType.video, "video")
    script.add_track(TrackType.audio, "나레이션")

    report("[3/5] Ken Burns 줌 + 전환효과 적용 중...")
    transition_type = getattr(TransitionType, transition_name, None) if transition_name else None
    for i, (img_path, start, end) in enumerate(groups):
        start_us = int(round(start * 1_000_000))
        dur_us = int(round((end - start) * 1_000_000))
        if dur_us <= 0:
            continue

        material = VideoMaterial(img_path)
        material.crop_settings = _cover_crop_settings(material.width, material.height, width, height)
        seg = VideoSegment(material, Timerange(start_us, dur_us), source_timerange=Timerange(0, dur_us))

        zoom_in = i % 2 == 0
        start_scale, end_scale = (1.0, zoom_ratio) if zoom_in else (zoom_ratio, 1.0)
        seg.add_keyframe(KeyframeProperty.uniform_scale, 0, start_scale)
        seg.add_keyframe(KeyframeProperty.uniform_scale, dur_us, end_scale)

        if transition_type is not None and i < len(groups) - 1:
            seg.add_transition(transition_type, duration=transition_ms * 1000)

        script.add_segment(seg, "video")

    report("[4/5] 나레이션 오디오 배치 중...")
    for cue in cues:
        start_us = int(round(cue.start * 1_000_000))
        dur_us = int(round((cue.end - cue.start) * 1_000_000))
        if dur_us <= 0:
            continue
        audio_material = AudioMaterial(cue.path)
        # moviepy(재생시간 계산용)와 pymediainfo(소재 실제 길이) 측정치가 밀리초 단위로 미세하게
        # 어긋날 수 있어, 소재 길이를 넘지 않도록 클램프한다.
        seg_dur_us = min(dur_us, audio_material.duration)
        aseg = AudioSegment(
            audio_material, Timerange(start_us, seg_dur_us), source_timerange=Timerange(0, seg_dur_us),
        )
        script.add_segment(aseg, "나레이션")

    if template.music.enabled and template.music.path:
        _add_bgm_track(script, template.music, total_duration_us)

    if generate_captions and template.captions.enabled:
        report("[5/5] 자막 추가 중...")
        style_ref = _caption_style_reference(template)
        script.add_track(TrackType.text, "자막", relative_index=999)
        for cue in cues:
            start_us = int(round(cue.start * 1_000_000))
            dur_us = int(round((cue.end - cue.start) * 1_000_000))
            if dur_us <= 0:
                continue
            wrapped = cap._wrap(cue.text, template.captions)
            text_seg = TextSegment(
                wrapped,
                Timerange(start_us, dur_us),
                style=style_ref.style,
                border=style_ref.border,
                clip_settings=style_ref.clip_settings,
            )
            script.add_segment(text_seg, "자막")
    else:
        report("[5/5] 자막 생성 건너뜀")

    script.save()

    _generate_image_cover(groups[0][0] if groups else None, draft_dir, template.resolution)
    _register_in_root_index(drafts_folder, draft_name, total_duration_us)

    report(f"완료: CapCut 드래프트 '{draft_name}' 저장됨 ({drafts_folder})")
    return script
