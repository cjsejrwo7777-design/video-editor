"""CapCut 스타일 자동 영상편집기 CLI.

두 가지 엔진 지원:
  - capcut (기본값): pycapcut으로 실제 CapCut 드래프트를 생성. 원본 화질 그대로,
    CapCut 앱에서 열어 다듬은 뒤 CapCut 자체 엔진으로 내보낸다.
  - moviepy: ffmpeg 기반으로 즉시 mp4 파일까지 렌더링. CapCut 없이 완전 자동 처리.

사용 예:
  python main.py --input clip.mp4 --template templates/shorts.json --draft-name my_video
  python main.py --input a.mp4 b.mp4 --template templates/default.json --engine moviepy --output output/final.mp4
  python main.py --input clip.mp4 --template templates/shorts.json --draft-name my_video --music bgm.mp3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from autoedit.config import Template

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}


def collect_inputs(raw_inputs: list[str]) -> list[str]:
    paths: list[str] = []
    for item in raw_inputs:
        p = Path(item)
        if p.is_dir():
            found = sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXTS)
            paths.extend(str(f) for f in found)
        elif p.is_file():
            paths.append(str(p))
        else:
            raise FileNotFoundError(f"입력 경로를 찾을 수 없습니다: {item}")
    if not paths:
        raise ValueError("편집할 영상 파일을 찾지 못했습니다.")
    return paths


def run_capcut(args, template: Template, input_paths: list[str]) -> None:
    from autoedit.capcut_export import build_draft, find_default_drafts_folder

    drafts_folder = args.drafts_folder or find_default_drafts_folder()
    if not drafts_folder:
        raise FileNotFoundError(
            "CapCut 드래프트 폴더를 자동으로 찾지 못했습니다. --drafts-folder 로 직접 지정해주세요.\n"
            r"보통 위치: %LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft"
        )
    draft_name = args.draft_name or Path(input_paths[0]).stem

    print(f"템플릿: {template.name} ({template.resolution[0]}x{template.resolution[1]})")
    print(f"입력 영상 {len(input_paths)}개: {', '.join(Path(p).name for p in input_paths)}")
    print(f"CapCut 드래프트 폴더: {drafts_folder}")

    build_draft(
        input_paths=input_paths,
        template=template,
        drafts_folder=drafts_folder,
        draft_name=draft_name,
        generate_captions=not args.no_captions,
        allow_replace=True,
    )
    print(f"\nCapCut을 열어 '{draft_name}' 드래프트를 선택하면 편집 결과를 바로 확인할 수 있습니다.")
    print("CapCut에서 미리보기로 다듬은 뒤 '내보내기'로 최종 영상을 뽑아주세요.")


def run_moviepy(args, template: Template, input_paths: list[str]) -> None:
    from autoedit.assembler import render

    if not args.output:
        raise ValueError("--engine moviepy 를 쓸 때는 --output 경로가 필요합니다.")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    print(f"템플릿: {template.name} ({template.resolution[0]}x{template.resolution[1]})")
    print(f"입력 영상 {len(input_paths)}개: {', '.join(Path(p).name for p in input_paths)}")

    render(
        input_paths=input_paths,
        template=template,
        output_path=args.output,
        generate_captions=not args.no_captions,
        srt_path=args.srt,
    )


def main():
    parser = argparse.ArgumentParser(description="무음 자동 컷 + 자동 자막 + 템플릿 기반 자동 영상편집기")
    parser.add_argument("--input", nargs="+", required=True, help="입력 영상 파일 또는 폴더 (여러 개 지정 시 순서대로 이어붙임)")
    parser.add_argument("--template", default="templates/default.json", help="템플릿 JSON 경로")
    parser.add_argument("--engine", choices=["capcut", "moviepy"], default="capcut",
                        help="capcut: 실제 CapCut 드래프트 생성(기본값, 고품질/수동 검토·수정 가능) / "
                             "moviepy: ffmpeg으로 바로 mp4까지 자동 렌더링")

    # capcut 엔진 전용
    parser.add_argument("--draft-name", default=None, help="[capcut] 드래프트 이름 (기본값: 첫 입력 파일명)")
    parser.add_argument("--drafts-folder", default=None, help="[capcut] CapCut 드래프트 폴더 경로 (기본값: 자동 감지)")

    # moviepy 엔진 전용
    parser.add_argument("--output", default=None, help="[moviepy] 출력 영상 파일 경로")
    parser.add_argument("--srt", default=None, help="[moviepy] 자막을 SRT 파일로도 저장할 경로 (선택)")

    parser.add_argument("--no-captions", action="store_true", help="자동 자막 생성을 끔")
    parser.add_argument("--music", default=None, help="배경음악 파일 경로 (템플릿 설정을 덮어씀)")
    parser.add_argument("--music-volume", type=float, default=None, help="배경음악 볼륨 (0.0 ~ 1.0)")
    args = parser.parse_args()

    template = Template.load(args.template)

    if args.music:
        template.music.enabled = True
        template.music.path = args.music
    if args.music_volume is not None:
        template.music.volume = args.music_volume

    input_paths = collect_inputs(args.input)

    if args.engine == "capcut":
        run_capcut(args, template, input_paths)
    else:
        run_moviepy(args, template, input_paths)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
