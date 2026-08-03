# 영상편집기 (Auto Video Editor)

CapCut처럼 영상을 넣으면 **무음 구간 자동 컷 + 자동 자막 생성 + 템플릿 기반 자동 조립**까지 한 번에 처리하는 Python CLI 도구입니다.

## 엔진 두 가지

- **`capcut` (기본값)**: [pycapcut](https://github.com/GuanYixuan/pyCapCut)으로 **진짜 CapCut 드래프트**를 생성합니다. 화면을 직접 그리지 않고 "어느 구간을 어떤 순서로 재생할지"만 기록하기 때문에 원본 화질 손실이 전혀 없고, CapCut을 열면 바로 편집 결과가 보입니다. CapCut에서 자유롭게 다듬은 뒤 CapCut 자체 엔진(진짜 전환효과/필터/자막 스타일)으로 내보내면 됩니다.
- **`moviepy`**: ffmpeg 기반으로 CapCut 없이 즉시 mp4까지 완전 자동 렌더링합니다. 서버/배치 처리처럼 CapCut 앱 없이 끝까지 무인 처리해야 할 때 씁니다.

## 주요 기능

- **무음/침묵 구간 자동 컷**: 말이 없는 구간을 자동으로 잘라내되, 짧은 호흡/쉼표는 자연스럽게 남겨서 편집 결과가 뚝뚝 끊기지 않도록 처리합니다.
- **자동 자막 생성**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)로 음성을 인식해 자막을 만들고, `capcut` 엔진에서는 CapCut 네이티브 자막으로, `moviepy` 엔진에서는 화면 오버레이 + `.srt` 파일로 반영합니다.
- **템플릿 기반 자동 조립**: 해상도, 자막 스타일, 배경음악 등을 JSON 템플릿으로 정의해두면 영상 클립만 넣어도 완성본이 나옵니다.

## 설치

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

ffmpeg는 `imageio-ffmpeg` 패키지가 자동으로 내려받아 쓰기 때문에 별도 설치가 필요 없습니다. `capcut` 엔진을 쓰려면 PC에 CapCut이 설치되어 있어야 합니다.

## 사용법 (capcut 엔진, 기본값)

```bash
venv\Scripts\python main.py --input clip.mp4 --template templates/shorts.json --draft-name my_video
```

실행이 끝나면 CapCut 앱을 열고 `my_video` 드래프트를 클릭하면 무음 컷과 자막이 이미 적용된 타임라인이 보입니다. 거기서 다듬은 뒤 CapCut의 "내보내기"로 최종 영상을 뽑으면 됩니다.

드래프트 폴더는 보통 자동으로 찾지만, 안 되면 직접 지정할 수 있습니다:

```bash
venv\Scripts\python main.py --input clip.mp4 --template templates/shorts.json --draft-name my_video --drafts-folder "C:\Users\<사용자명>\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft"
```

## 사용법 (moviepy 엔진, CapCut 없이 완전 자동)

```bash
venv\Scripts\python main.py --input clip.mp4 --template templates/shorts.json --engine moviepy --output output/final.mp4
```

여러 클립을 순서대로 이어붙이기:

```bash
venv\Scripts\python main.py --input a.mp4 b.mp4 --template templates/default.json --engine moviepy --output output/final.mp4
```

폴더를 통째로 넣으면 폴더 안의 영상 파일을 이름순으로 이어붙입니다:

```bash
venv\Scripts\python main.py --input clips/ --template templates/shorts.json --draft-name my_video
```

배경음악 추가, 자막 SRT 저장(moviepy 전용), 자막 끄기:

```bash
venv\Scripts\python main.py --input clip.mp4 --template templates/shorts.json --draft-name my_video --music bgm.mp3
venv\Scripts\python main.py --input clip.mp4 --template templates/default.json --engine moviepy --output output/final.mp4 --srt output/final.srt
venv\Scripts\python main.py --input clip.mp4 --template templates/shorts.json --draft-name my_video --no-captions
```

## 템플릿

`templates/default.json` (16:9, 유튜브용)과 `templates/shorts.json` (9:16, 쇼츠/릴스용)이 기본 제공됩니다. 템플릿을 복사해서 값을 바꾸면 나만의 스타일을 만들 수 있습니다.

| 항목 | 설명 |
|---|---|
| `resolution` | 출력 해상도 `[가로, 세로]` |
| `fit` | `cover`(꽉 채우고 크롭) / `contain`(레터박스, moviepy 엔진에서만 사용) |
| `silence.thresh_db` | 이 데시벨보다 조용하면 무음으로 판단 (기본 -35dB) |
| `silence.min_silence_ms` | 이보다 긴 무음만 잘라냄 (기본 450ms) — 값을 올리면 덜 자르고, 내리면 더 공격적으로 자름 |
| `silence.pad_ms` | 컷 경계에 남기는 여유 (말 잘림 방지) |
| `captions.model_size` | whisper 모델 크기 (`tiny`/`base`/`small`/`medium`/`large-v3`). 클수록 정확하지만 느림 |
| `music` | 배경음악 파일/볼륨 (capcut 엔진은 부족한 길이만큼 자동 반복 재생) |
| `intro` / `outro` | 인트로/아웃트로 영상 경로 (moviepy 엔진 전용) |

## 참고

- Whisper 모델은 처음 실행할 때 자동으로 다운로드됩니다 (`small` 기준 약 500MB).
- GPU(CUDA)가 있으면 `autoedit/captions.py`의 `device="cpu"`를 `"cuda"`로 바꾸면 훨씬 빠릅니다.
- `capcut` 엔진은 CapCut 앱의 실제 렌더링/내보내기 UI를 자동으로 조작하지는 않습니다(버전/언어별로 깨지기 쉬워 의도적으로 뺐습니다). 드래프트 생성까지만 자동화하고, 최종 검토·내보내기는 CapCut에서 직접 합니다.
- `test_assets/`에는 파이프라인 검증용 샘플과 한국어 TTS 생성 스크립트가 들어 있습니다.
