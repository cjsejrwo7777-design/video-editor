"""CapCut 스타일 자동 영상편집기 CLI.

사용 예:
  python main.py --input clip.mp4 --template templates/shorts.json --output output/final.mp4
  python main.py --input a.mp4 b.mp4 --template templates/default.json --output output/final.mp4 --srt output/final.srt
  python main.py --input clip.mp4 --template templates/shorts.json --output output/final.mp4 --music bgm.mp3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from autoedit.assembler import render
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


def main():
    parser = argparse.ArgumentParser(description="무음 자동 컷 + 자동 자막 + 템플릿 기반 자동 영상편집기")
    parser.add_argument("--input", nargs="+", required=True, help="입력 영상 파일 또는 폴더 (여러 개 지정 시 순서대로 이어붙임)")
    parser.add_argument("--template", default="templates/default.json", help="템플릿 JSON 경로")
    parser.add_argument("--output", required=True, help="출력 영상 파일 경로")
    parser.add_argument("--srt", default=None, help="자막을 SRT 파일로도 저장할 경로 (선택)")
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


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
