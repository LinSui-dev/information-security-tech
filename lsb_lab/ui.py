"""Tkinter 基础功能界面；导入本模块不创建窗口。"""
import tkinter as tk
import sys
from tkinter import ttk, filedialog, messagebox
from .controller import LabController
from .contracts import capacity_for
from .errors import LabError


class LabApp(ttk.Frame):
    def __init__(self, master: tk.Tk, controller: LabController | None = None):
        super().__init__(master, padding=10)
        self.controller = controller or LabController()
        self._refreshing = False
        self._images = {}
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        master.title("LSB 信息隐藏 · 基础实验")
        master.protocol("WM_DELETE_WINDOW", self.close)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="① 打开原图", command=self.open_source).pack(side="left", padx=4)
        self.embed_button = ttk.Button(toolbar, text="② 嵌入信息", command=self.embed)
        self.embed_button.pack(side="left", padx=4)
        self.save_button = ttk.Button(toolbar, text="③ 另存 BMP", command=self.save)
        self.save_button.pack(side="left", padx=4)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=12)
        ttk.Button(toolbar, text="从 BMP 文件提取", command=self.extract).pack(side="left", padx=4)
        self.capacity_label = ttk.Label(self)
        self.capacity_label.grid(row=1, column=0, sticky="w", pady=(0, 8))
        pictures = ttk.Frame(self)
        pictures.grid(row=2, column=0, sticky="nsew")
        pictures.columnconfigure((0, 1), weight=1, uniform="pictures")
        pictures.rowconfigure(0, weight=1)
        self.source_frame = ttk.LabelFrame(pictures, text="原图", padding=5)
        self.result_frame = ttk.LabelFrame(pictures, text="结果", padding=5)
        self.source_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.result_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.source_canvas = self._canvas(self.source_frame)
        self.result_canvas = self._canvas(self.result_frame)
        text_area = ttk.Frame(self)
        text_area.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        text_area.columnconfigure((0, 1), weight=1, uniform="texts")
        ttk.Label(text_area, text="待嵌入文本 · UTF-8").grid(row=0, column=0, sticky="w")
        ttk.Label(text_area, text="提取结果（只读）").grid(row=0, column=1, sticky="w")
        input_frame = ttk.Frame(text_area)
        output_frame = ttk.Frame(text_area)
        input_frame.grid(row=1, column=0, sticky="ew", padx=(0, 5))
        output_frame.grid(row=1, column=1, sticky="ew", padx=(5, 0))
        self.input = tk.Text(input_frame, height=4, width=1, wrap="word", undo=True, padx=6, pady=4)
        self.output = tk.Text(output_frame, height=4, width=1, wrap="word", state="disabled", padx=6, pady=4)
        for frame, widget in ((input_frame, self.input), (output_frame, self.output)):
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
            widget.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            widget.pack(side="left", fill="x", expand=True)
        self.input.bind("<<Modified>>", self._input_changed)
        self.status = ttk.Label(self, text="请选择 BMP 原图，或直接从载体文件提取。")
        self.status.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.refresh()

    def _canvas(self, parent):
        canvas = tk.Canvas(parent, width=1, height=1, background="#eeeeee", highlightthickness=0)
        canvas.bind("<Configure>", lambda event: self._center_placeholder(canvas))
        xbar = ttk.Scrollbar(parent, orient="horizontal", command=canvas.xview)
        ybar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        xbar.grid(row=1, column=0, sticky="ew")
        ybar.grid(row=0, column=1, sticky="ns")
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        return canvas

    def _center_placeholder(self, canvas):
        if canvas.find_withtag("placeholder"):
            canvas.coords("placeholder", canvas.winfo_width() / 2, canvas.winfo_height() / 2)

    def _confirm_discard(self):
        return not self.controller.state.dirty or messagebox.askokcancel(
            "未保存的载体", "继续将丢弃未保存的嵌入结果。是否继续？", parent=self.winfo_toplevel())

    def _run(self, operation, success):
        try:
            operation()
        except (LabError, OSError, UnicodeError) as exc:
            messagebox.showerror("操作失败", str(exc), parent=self.winfo_toplevel())
            return False
        self.refresh()
        self.status.configure(text=success)
        return True

    def _replace_text(self, widget, text, readonly=False):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if readonly:
            widget.configure(state="disabled")

    def _input_changed(self, event=None):
        if self._refreshing or not self.input.edit_modified():
            return
        self.input.edit_modified(False)
        text = self.input.get("1.0", "end-1c")
        if text == self.controller.state.input_text:
            return
        if not self._confirm_discard():
            self.refresh()
            return
        self.controller.set_input_text(text)
        self.refresh()

    def refresh(self):
        self._refreshing = True
        try:
            state = self.controller.state
            if self.input.get("1.0", "end-1c") != state.input_text:
                self._replace_text(self.input, state.input_text)
            self.input.edit_modified(False)
            self._replace_text(self.output, state.extracted_text, readonly=True)
            for key, canvas, preview in (
                ("source", self.source_canvas, self.controller.get_source_preview()),
                ("result", self.result_canvas, self.controller.get_result_preview())):
                canvas.delete("all")
                if preview is None:
                    self._images.pop(key, None)
                    canvas.configure(scrollregion=(0, 0, 0, 0))
                    canvas.create_text(0, 0, text="未加载图片", fill="#666666", tags="placeholder")
                    self._center_placeholder(canvas)
                else:
                    photo = tk.PhotoImage(master=self, data=preview.ppm_bytes, format="PPM")
                    self._images[key] = photo
                    canvas.create_image(0, 0, anchor="nw", image=photo)
                    canvas.configure(scrollregion=(0, 0, photo.width(), photo.height()))
            self.result_frame.configure(text="嵌入结果" if state.stego is not None else
                                        "提取载体" if state.extracted_image is not None else "结果")
            try:
                used = len(state.input_text.encode("utf-8"))
            except UnicodeEncodeError:
                used = None
            enabled = False
            if state.source is None:
                label = "未加载原图"
            else:
                image = state.source
                cap = capacity_for(image)
                label = f"{image.width} × {image.height} · {image.pixel_format.value} 位 · 已用 {used if used is not None else '编码错误'} / 最大 {cap.max_payload_bytes} 字节"
                if not cap.can_store_header:
                    label += " · 图片不足以容纳帧头"
                enabled = used is not None and cap.can_store_header and used <= cap.max_payload_bytes
            self.capacity_label.configure(text=label)
            self.embed_button.configure(state="normal" if enabled else "disabled")
            self.save_button.configure(state="normal" if state.stego is not None else "disabled")
        finally:
            self._refreshing = False

    def open_source(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), filetypes=[("BMP 图片", "*.bmp")])
        if path and self._confirm_discard():
            self._run(lambda: self.controller.open_source(path), "原图已加载")

    def embed(self):
        if self._confirm_discard():
            self._run(lambda: self.controller.embed(self.input.get("1.0", "end-1c")), "嵌入完成，请另存载体")

    def save(self):
        path = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), defaultextension=".bmp",
                                          filetypes=[("BMP 图片", "*.bmp")], confirmoverwrite=True)
        if path:
            self._run(lambda: self.controller.save_stego(path), "载体已保存")

    def extract(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), filetypes=[("BMP 载体", "*.bmp")])
        if path and self._confirm_discard():
            self._run(lambda: self.controller.extract_from(path), "已从磁盘载体提取并通过 CRC32 校验")

    def close(self):
        if self._confirm_discard():
            self.winfo_toplevel().destroy()


def main():
    # 使用物理像素计量，避免 Windows 缩放将 960×540 放大到超过四分之一屏。
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    root.minsize(800, 480)
    x = max(0, (root.winfo_screenwidth() - 960) // 2)
    y = max(0, (root.winfo_screenheight() - 540) // 2)
    root.geometry(f"960x540+{x}+{y}")
    LabApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
