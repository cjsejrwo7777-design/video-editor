"""자동 영상편집기 GUI.

터미널이나 JSON 편집 없이 파일 추가 -> 옵션 선택 -> 실행 버튼만으로
CapCut 드래프트(또는 mp4)를 만들어내는 간단한 데스크톱 앱.

실행: venv\\Scripts\\python app.py
"""
from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from autoedit.config import Template

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac"}
TEMPLATES_DIR = Path(__file__).parent / "templates"


class AutoEditApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("자동 영상편집기")
        root.geometry("880x760")
        root.minsize(780, 680)

        self.input_paths: list[str] = []
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_drafts_folder: str | None = None

        self._build_ui()
        self._refresh_templates()
        self._poll_log_queue()

    # ---------------------------------------------------------------- UI 구성
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        file_frame = ttk.LabelFrame(self.root, text="1. 입력 영상")
        file_frame.pack(fill="x", **pad)

        self.file_listbox = tk.Listbox(file_frame, height=5, selectmode="extended")
        self.file_listbox.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)

        btn_col = ttk.Frame(file_frame)
        btn_col.pack(side="left", fill="y", padx=8, pady=8)
        ttk.Button(btn_col, text="파일 추가", command=self._add_files).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="폴더 추가", command=self._add_folder).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="선택 제거", command=self._remove_selected).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="전체 비우기", command=self._clear_files).pack(fill="x", pady=2)

        tmpl_frame = ttk.LabelFrame(self.root, text="2. 템플릿")
        tmpl_frame.pack(fill="x", **pad)

        self.template_var = tk.StringVar()
        self.template_combo = ttk.Combobox(tmpl_frame, textvariable=self.template_var, state="readonly", width=22)
        self.template_combo.pack(side="left", padx=8, pady=8)
        self.template_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_template_change())

        self.template_info_var = tk.StringVar(value="")
        ttk.Label(tmpl_frame, textvariable=self.template_info_var).pack(side="left", padx=8)

        engine_frame = ttk.LabelFrame(self.root, text="3. 출력 방식")
        engine_frame.pack(fill="x", **pad)

        self.engine_var = tk.StringVar(value="capcut")
        ttk.Radiobutton(
            engine_frame, text="CapCut 드래프트 생성 (추천 · 화질 손실 없음)",
            variable=self.engine_var, value="capcut", command=self._on_engine_change,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=2, columnspan=2)
        ttk.Radiobutton(
            engine_frame, text="MP4로 바로 렌더링 (CapCut 없이 완전 자동)",
            variable=self.engine_var, value="moviepy", command=self._on_engine_change,
        ).grid(row=1, column=0, sticky="w", padx=8, pady=2, columnspan=2)

        self.capcut_frame = ttk.Frame(engine_frame)
        ttk.Label(self.capcut_frame, text="드래프트 이름:").grid(row=0, column=0, sticky="w")
        self.draft_name_var = tk.StringVar()
        ttk.Entry(self.capcut_frame, textvariable=self.draft_name_var, width=26).grid(row=0, column=1, padx=4, pady=2)

        ttk.Label(self.capcut_frame, text="드래프트 폴더:").grid(row=1, column=0, sticky="w")
        self.drafts_folder_var = tk.StringVar(value=self._detect_drafts_folder())
        ttk.Entry(self.capcut_frame, textvariable=self.drafts_folder_var, width=46).grid(row=1, column=1, padx=4, pady=2)
        ttk.Button(self.capcut_frame, text="찾아보기", command=self._browse_drafts_folder).grid(row=1, column=2, padx=4)

        self.moviepy_frame = ttk.Frame(engine_frame)
        ttk.Label(self.moviepy_frame, text="출력 파일:").grid(row=0, column=0, sticky="w")
        self.output_path_var = tk.StringVar()
        ttk.Entry(self.moviepy_frame, textvariable=self.output_path_var, width=46).grid(row=0, column=1, padx=4, pady=2)
        ttk.Button(self.moviepy_frame, text="다른 이름으로 저장", command=self._browse_output).grid(row=0, column=2, padx=4)

        self.capcut_frame.grid(row=0, column=2, rowspan=2, sticky="w", padx=16)
        self._on_engine_change()

        silence_frame = ttk.LabelFrame(self.root, text="4. 무음 컷 민감도")
        silence_frame.pack(fill="x", **pad)

        self.thresh_var = tk.DoubleVar(value=-35.0)
        self._add_slider(silence_frame, "무음 판단 기준(dB, 낮을수록 민감)", self.thresh_var, -55, -15, row=0)

        self.min_silence_var = tk.DoubleVar(value=450)
        self._add_slider(silence_frame, "최소 무음 길이(ms, 낮을수록 더 많이 자름)", self.min_silence_var, 150, 1200, row=1)

        caption_frame = ttk.LabelFrame(self.root, text="5. 자동 자막")
        caption_frame.pack(fill="x", **pad)

        self.captions_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            caption_frame, text="자동 자막 생성", variable=self.captions_enabled_var,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        ttk.Label(caption_frame, text="정확도(모델 크기):").grid(row=0, column=1, sticky="e")
        self.model_size_var = tk.StringVar(value="small")
        ttk.Combobox(
            caption_frame, textvariable=self.model_size_var, state="readonly", width=10,
            values=["tiny", "base", "small", "medium", "large-v3"],
        ).grid(row=0, column=2, padx=8)
        ttk.Label(caption_frame, text="(클수록 정확하지만 느림)").grid(row=0, column=3, sticky="w")

        music_frame = ttk.LabelFrame(self.root, text="6. 배경음악 (선택)")
        music_frame.pack(fill="x", **pad)

        self.music_path_var = tk.StringVar()
        ttk.Entry(music_frame, textvariable=self.music_path_var, width=44).grid(row=0, column=0, padx=8, pady=4)
        ttk.Button(music_frame, text="파일 선택", command=self._browse_music).grid(row=0, column=1, padx=2)
        ttk.Button(music_frame, text="지우기", command=lambda: self.music_path_var.set("")).grid(row=0, column=2, padx=2)

        self.music_volume_var = tk.DoubleVar(value=0.15)
        self._add_slider(music_frame, "배경음악 볼륨", self.music_volume_var, 0.0, 1.0, row=1, fmt="{:.2f}")

        run_frame = ttk.Frame(self.root)
        run_frame.pack(fill="x", **pad)
        self.run_btn = ttk.Button(run_frame, text="실행", command=self._on_run)
        self.run_btn.pack(side="left")
        self.open_folder_btn = ttk.Button(run_frame, text="결과 폴더 열기", command=self._open_result_folder, state="disabled")
        self.open_folder_btn.pack(side="left", padx=8)
        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(run_frame, textvariable=self.status_var).pack(side="left", padx=12)

        log_frame = ttk.LabelFrame(self.root, text="진행 로그")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=12, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

    def _add_slider(self, parent, label, var, lo, hi, row, fmt="{:.0f}") -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        value_label = ttk.Label(parent, text=fmt.format(var.get()), width=8)

        def on_change(_evt=None):
            value_label.config(text=fmt.format(var.get()))

        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var, orient="horizontal", length=260, command=on_change)
        scale.grid(row=row, column=1, sticky="we", padx=8, pady=4)
        value_label.grid(row=row, column=2, sticky="w", padx=4)

    # ---------------------------------------------------------------- 파일 목록
    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="영상 파일 선택",
            filetypes=[("영상 파일", " ".join(f"*{ext}" for ext in VIDEO_EXTS)), ("모든 파일", "*.*")],
        )
        for p in paths:
            if p not in self.input_paths:
                self.input_paths.append(p)
                self.file_listbox.insert("end", p)

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="영상 폴더 선택")
        if not folder:
            return
        found = sorted(f for f in Path(folder).iterdir() if f.suffix.lower() in VIDEO_EXTS)
        for f in found:
            p = str(f)
            if p not in self.input_paths:
                self.input_paths.append(p)
                self.file_listbox.insert("end", p)

    def _remove_selected(self) -> None:
        for i in reversed(self.file_listbox.curselection()):
            del self.input_paths[i]
            self.file_listbox.delete(i)

    def _clear_files(self) -> None:
        self.input_paths.clear()
        self.file_listbox.delete(0, "end")

    # ---------------------------------------------------------------- 템플릿
    def _refresh_templates(self) -> None:
        files = sorted(TEMPLATES_DIR.glob("*.json"))
        self.template_combo["values"] = [f.name for f in files]
        if files:
            self.template_combo.current(0)
            self._on_template_change()

    def _on_template_change(self) -> None:
        name = self.template_var.get()
        if not name:
            return
        try:
            template = Template.load(TEMPLATES_DIR / name)
        except Exception as e:
            self.template_info_var.set(f"(템플릿 로드 실패: {e})")
            return
        self.template_info_var.set(f"{template.resolution[0]}x{template.resolution[1]} · {template.fit}")
        self.thresh_var.set(template.silence.thresh_db)
        self.min_silence_var.set(template.silence.min_silence_ms)
        self.captions_enabled_var.set(template.captions.enabled)
        self.model_size_var.set(template.captions.model_size)
        if template.music.enabled and template.music.path:
            self.music_path_var.set(template.music.path)
        self.music_volume_var.set(template.music.volume)

    # ---------------------------------------------------------------- 엔진 옵션
    def _on_engine_change(self) -> None:
        if self.engine_var.get() == "capcut":
            self.moviepy_frame.grid_forget()
            self.capcut_frame.grid(row=0, column=2, rowspan=2, sticky="w", padx=16)
        else:
            self.capcut_frame.grid_forget()
            self.moviepy_frame.grid(row=0, column=2, rowspan=2, sticky="w", padx=16)

    def _detect_drafts_folder(self) -> str:
        try:
            from autoedit.capcut_export import find_default_drafts_folder

            return find_default_drafts_folder() or ""
        except Exception:
            return ""

    def _browse_drafts_folder(self) -> None:
        folder = filedialog.askdirectory(title="CapCut 드래프트 폴더 선택")
        if folder:
            self.drafts_folder_var.set(folder)

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="출력 파일 저장 위치", defaultextension=".mp4",
            filetypes=[("MP4 영상", "*.mp4")],
        )
        if path:
            self.output_path_var.set(path)

    def _browse_music(self) -> None:
        path = filedialog.askopenfilename(
            title="배경음악 파일 선택",
            filetypes=[("오디오 파일", " ".join(f"*{ext}" for ext in AUDIO_EXTS)), ("모든 파일", "*.*")],
        )
        if path:
            self.music_path_var.set(path)

    def _open_result_folder(self) -> None:
        if self.last_drafts_folder and os.path.isdir(self.last_drafts_folder):
            os.startfile(self.last_drafts_folder)  # noqa: S606 - 사용자가 직접 만든 결과 폴더를 여는 것

    # ---------------------------------------------------------------- 실행
    def _build_template(self) -> Template:
        name = self.template_var.get()
        template = Template.load(TEMPLATES_DIR / name)
        template.silence.thresh_db = self.thresh_var.get()
        template.silence.min_silence_ms = int(self.min_silence_var.get())
        template.captions.enabled = self.captions_enabled_var.get()
        template.captions.model_size = self.model_size_var.get()
        music_path = self.music_path_var.get().strip()
        if music_path:
            template.music.enabled = True
            template.music.path = music_path
            template.music.volume = self.music_volume_var.get()
        else:
            template.music.enabled = False
        return template

    def _on_run(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.input_paths:
            messagebox.showwarning("입력 필요", "편집할 영상 파일을 먼저 추가해주세요.")
            return
        if not self.template_var.get():
            messagebox.showwarning("템플릿 필요", "템플릿을 선택해주세요.")
            return

        engine = self.engine_var.get()
        if engine == "moviepy" and not self.output_path_var.get().strip():
            messagebox.showwarning("출력 경로 필요", "MP4 출력 파일 경로를 지정해주세요.")
            return
        if engine == "capcut" and not self.drafts_folder_var.get().strip():
            messagebox.showwarning(
                "드래프트 폴더 필요",
                "CapCut 드래프트 폴더를 찾지 못했습니다. 직접 찾아보기로 지정해주세요.",
            )
            return

        try:
            template = self._build_template()
        except Exception as e:
            messagebox.showerror("템플릿 오류", str(e))
            return

        # tkinter 변수는 메인 스레드에서만 안전하게 읽을 수 있으므로,
        # 백그라운드 스레드로 넘기기 전에 여기서 전부 일반 값으로 뽑아둔다.
        input_paths = list(self.input_paths)
        captions_enabled = self.captions_enabled_var.get()
        drafts_folder = self.drafts_folder_var.get().strip()
        draft_name = self.draft_name_var.get().strip() or Path(input_paths[0]).stem
        output_path = self.output_path_var.get().strip()

        self._clear_log()
        self.run_btn.config(state="disabled")
        self.open_folder_btn.config(state="disabled")
        self.status_var.set("실행 중...")

        self.worker = threading.Thread(
            target=self._run_pipeline,
            args=(engine, template, input_paths, captions_enabled, drafts_folder, draft_name, output_path),
            daemon=True,
        )
        self.worker.start()

    def _run_pipeline(
        self,
        engine: str,
        template: Template,
        input_paths: list[str],
        captions_enabled: bool,
        drafts_folder: str,
        draft_name: str,
        output_path: str,
    ) -> None:
        def progress(msg: str) -> None:
            self.log_queue.put(msg)

        try:
            if engine == "capcut":
                from autoedit.capcut_export import build_draft

                build_draft(
                    input_paths=input_paths,
                    template=template,
                    drafts_folder=drafts_folder,
                    draft_name=draft_name,
                    generate_captions=captions_enabled,
                    allow_replace=True,
                    progress_cb=progress,
                )
                self.last_drafts_folder = os.path.join(drafts_folder, draft_name)
                progress(f"\nCapCut에서 '{draft_name}' 드래프트를 열어 확인하세요.")
            else:
                from autoedit.assembler import render

                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                render(
                    input_paths=input_paths,
                    template=template,
                    output_path=output_path,
                    generate_captions=captions_enabled,
                    progress_cb=progress,
                )
                self.last_drafts_folder = str(Path(output_path).parent)

            self.log_queue.put("__DONE__")
        except Exception:
            self.log_queue.put(traceback.format_exc())
            self.log_queue.put("__FAILED__")

    # ---------------------------------------------------------------- 로그/폴링
    def _clear_log(self) -> None:
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__DONE__":
                    self.status_var.set("완료")
                    self.run_btn.config(state="normal")
                    self.open_folder_btn.config(state="normal")
                elif msg == "__FAILED__":
                    self.status_var.set("오류 발생")
                    self.run_btn.config(state="normal")
                    messagebox.showerror("실행 실패", "로그 창에서 자세한 오류 내용을 확인해주세요.")
                else:
                    self._append_log(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def main() -> None:
    root = tk.Tk()
    AutoEditApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
