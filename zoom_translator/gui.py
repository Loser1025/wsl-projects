import tkinter as tk
from config import Config, default_config


class SubtitleWindow(tk.Tk):
    """tkinterを使用した画面最前面・半透明・ドラッグ移動可能な字幕表示ウィンドウクラス"""

    def __init__(self, config: Config = default_config):
        super().__init__()
        self.config = config

        # ウィンドウの基本設定
        self.overrideredirect(True)  # ウィンドウ装飾（タイトルバーなど）を非表示
        self.attributes("-topmost", True)  # 常に最前面に表示
        self.attributes("-alpha", self.config.WINDOW_ALPHA)  # ウィンドウの透明度を設定

        # 背景色を透過色（透明カラーキー）として指定
        # 注意: OSや環境によっては -transparentcolor が効かない場合がありますが、標準的な実装です。
        try:
            self.attributes("-transparentcolor", self.config.SUBTITLE_BG_COLOR)
        except tk.TclError:
            # プラットフォームでサポートされていない場合は無視
            pass

        self.configure(bg=self.config.SUBTITLE_BG_COLOR)

        # ドラッグ移動用のマウス座標保持変数
        self._drag_data = {"x": 0, "y": 0}

        # ウィンドウの初期サイズと画面下部中央への配置
        window_width = 800
        window_height = 100
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x_position = (screen_width - window_width) // 2
        y_position = screen_height - window_height - 100  # 画面下部から100px上
        self.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")

        # 字幕を表示するラベルの作成
        self.subtitle_label = tk.Label(
            self,
            text="",
            font=(self.config.SUBTITLE_FONT_FAMILY, self.config.SUBTITLE_FONT_SIZE),
            fg=self.config.SUBTITLE_FG_COLOR,
            bg=self.config.SUBTITLE_BG_COLOR,
            wraplength=window_width - 40,
            justify="center",
        )
        self.subtitle_label.pack(expand=True, fill="both", padx=20, pady=10)

        # マウスドラッグによるウィンドウ移動イベントのバインド
        # 背景やラベルのどこをドラッグしても移動できるように設定
        for widget in (self, self.subtitle_label):
            widget.bind("<Button-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)

        # 右クリック（または特定の操作）で終了できるようにする（開発・テスト用にも便利）
        self.bind("<Button-3>", lambda e: self.destroy())

    def _on_drag_start(self, event):
        """ドラッグ開始時のマウス位置を記録する"""
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag_motion(self, event):
        """ドラッグ中のマウス移動量に応じてウィンドウ位置を更新する"""
        delta_x = event.x - self._drag_data["x"]
        delta_y = event.y - self._drag_data["y"]
        new_x = self.winfo_x() + delta_x
        new_y = self.winfo_y() + delta_y
        self.geometry(f"+{new_x}+{new_y}")

    def update_subtitle(self, text: str):
        """別スレッドから安全に呼ばれても、after経由でメインスレッドでラベルのテキストを更新する"""
        self.after(0, lambda: self.subtitle_label.config(text=text))

    def run(self):
        """メインループを開始する"""
        self.mainloop()


if __name__ == "__main__":
    import threading
    import time

    # 単体動作確認用ブロック
    print("SubtitleWindowを起動します。画面下部に半透明の字幕ウィンドウが表示されます。")
    print("ウィンドウをマウスドラッグで移動できます。右クリックで終了します。")

    app = SubtitleWindow()

    # 別スレッドから字幕が安全に更新されるかをテストするダミースレッド
    def dummy_subtitle_updater():
        texts = [
            "Hello, welcome to the Zoom Translator demonstration.",
            "This is a real-time subtitle translation tool.",
            "tkinterデスクトップUIを専門とするGUIエンジニアによる実装です。",
            "画面最前面・半透明・ドラッグ移動可能になっています。",
            "お疲れ様でした！",
        ]
        time.sleep(1)
        for i, text in enumerate(texts):
            app.update_subtitle(f"[{i+1}/5] {text}")
            time.sleep(3)

    threading.Thread(target=dummy_subtitle_updater, daemon=True).start()

    app.run()
