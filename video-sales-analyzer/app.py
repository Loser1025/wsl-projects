"""
オンライン商談動画分析 Webアプリケーション
Gemma 4 (Gemini API) を使用して表情・声トーンをスコア化
"""

import os
import json
import time
import tempfile
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_from_directory
from google import genai
from google.genai import types

from config.settings import (
    API_KEYS, MODEL_NAME, FRAME_COUNT,
    FRAME_WIDTH, FRAME_HEIGHT, MAX_CONTENT_LENGTH,
    ALLOWED_EXTENSIONS, HOST, PORT, DEBUG
)
from config.score_criteria import (
    EXPRESSION_CRITERIA, VOICE_TONE_CRITERIA,
    GRADE_THRESHOLDS, ANALYSIS_PROMPT_TEMPLATE
)

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Vercelの/tmpディレクトリを使用（読み取り専用ファイルシステム対応）
if os.environ.get("VERCEL"):
    app.config["UPLOAD_FOLDER"] = "/tmp/uploads"
else:
    app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")

try:
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
except OSError:
    pass  # 読み取り専用ファイルシステムの場合は無視

# ============================================================
# APIキー管理（フォールバック対応）
# ============================================================
class APIKeyManager:
    """複数APIキーを管理し、フォールバックを提供"""
    
    def __init__(self, api_keys: List[str]):
        self._keys = api_keys
        self._current_index = 0
        self._failed_keys: set = set()
        self._key_usage: Dict[str, int] = {key: 0 for key in api_keys}
    
    @property
    def current_key(self) -> Optional[str]:
        """現在使用中のAPIキーを返す"""
        if not self._keys:
            return None
        available_keys = [k for k in self._keys if k not in self._failed_keys]
        if not available_keys:
            return None
        return available_keys[self._current_index % len(available_keys)]
    
    def mark_failed(self, key: str):
        """キーを失敗としてマーク"""
        self._failed_keys.add(key)
        logger.warning(f"APIキーを失敗としてマーク: {key[:8]}...")
    
    def rotate_key(self):
        """次のキーに切り替え"""
        self._current_index += 1
        available = [k for k in self._keys if k not in self._failed_keys]
        if available:
            new_key = available[self._current_index % len(available)]
            logger.info(f"APIキーを切り替え: {new_key[:8]}...")
            return new_key
        return None
    
    def record_usage(self, key: str):
        """キーの使用回数を記録"""
        if key in self._key_usage:
            self._key_usage[key] += 1
    
    @property
    def has_available_key(self) -> bool:
        return len(self._failed_keys) < len(self._keys)
    
    def get_status(self) -> Dict:
        return {
            "total_keys": len(self._keys),
            "failed_keys": len(self._failed_keys),
            "available_keys": len(self._keys) - len(self._failed_keys),
            "usage": {k[:8] + "...": v for k, v in self._key_usage.items()}
        }

# APIキーマネージャー初期化
key_manager = APIKeyManager(API_KEYS)

# ============================================================
# 動画処理ユーティリティ
# ============================================================
class VideoProcessor:
    """動画からフレームと音声を抽出"""
    
    @staticmethod
    def extract_frames(video_path: str, num_frames: int = FRAME_COUNT) -> List[bytes]:
        """動画からフレーム画像を抽出"""
        import cv2
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError("動画を開けませんでした")
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            cap.release()
            raise ValueError("動画にフレームが含まれていません")
        
        # 等間隔でフレームを抽出
        frame_indices = [
            int(total_frames * i / (num_frames + 1))
            for i in range(1, num_frames + 1)
        ]
        
        frames = []
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                # リサイズ
                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
                # JPEGにエンコード
                _, buffer = cv2.imencode(".jpg", frame)
                frames.append(buffer.tobytes())
        
        cap.release()
        return frames
    
    @staticmethod
    def extract_audio(video_path: str) -> Optional[str]:
        """動画から音声を抽出して一時ファイルに保存"""
        try:
            from moviepy.editor import VideoFileClip
            
            clip = VideoFileClip(video_path)
            if clip.audio is None:
                return None
            
            audio_path = tempfile.mktemp(suffix=".wav")
            clip.audio.write_audiofile(audio_path, logger=None)
            clip.close()
            return audio_path
        except Exception as e:
            logger.warning(f"音声抽出に失敗: {e}")
            return None
    
    @staticmethod
    def get_video_info(video_path: str) -> Dict[str, Any]:
        """動画の基本情報を取得"""
        import cv2
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {}
        
        info = {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": cap.get(cv2.CAP_PROP_FPS),
            "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            "duration": int(cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS))
            if cap.get(cv2.CAP_PROP_FPS) > 0 else 0
        }
        cap.release()
        return info

# ============================================================
# Gemini API 分析エンジン
# ============================================================
class SalesAnalyzer:
    """Gemma 4 (Gemini API) を使用した商談分析エンジン"""
    
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.api_key = api_key
    
    def _build_prompt(self) -> str:
        """分析用プロンプトを構築"""
        expression_desc = "\n".join([
            f"- {v['description']}: {v['rubric']}"
            for v in EXPRESSION_CRITERIA["categories"].values()
        ])
        voice_desc = "\n".join([
            f"- {v['description']}: {v['rubric']}"
            for v in VOICE_TONE_CRITERIA["categories"].values()
        ])
        
        return ANALYSIS_PROMPT_TEMPLATE.format(
            expression_criteria=expression_desc,
            voice_tone_criteria=voice_desc
        )
    
    def analyze_video(self, video_path: str) -> Dict[str, Any]:
        """動画を分析してスコアを返す"""
        # フレーム抽出
        logger.info("フレーム抽出中...")
        frames = VideoProcessor.extract_frames(video_path)
        
        # 音声抽出
        logger.info("音声抽出中...")
        audio_path = VideoProcessor.extract_audio(video_path)
        
        # プロンプト構築
        prompt = self._build_prompt()
        
        # API呼び出し（リトライ付き）
        result = self._call_api_with_retry(prompt, frames, audio_path)
        
        # 一時ファイル削除
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        
        return result
    
    def _call_api_with_retry(
        self, prompt: str, frames: List[bytes], audio_path: Optional[str]
    ) -> Dict[str, Any]:
        """API呼び出し（リトライ付き）"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # コンテンツ構築（新しいSDK形式）
                contents = []
                
                # テキストプロンプト
                contents.append(prompt)
                
                # フレーム画像を追加
                for frame_bytes in frames:
                    contents.append(
                        types.Part.from_bytes(
                            data=frame_bytes,
                            mime_type="image/jpeg"
                        )
                    )
                
                # 音声を追加（あれば）
                if audio_path and os.path.exists(audio_path):
                    with open(audio_path, "rb") as f:
                        audio_data = f.read()
                    contents.append(
                        types.Part.from_bytes(
                            data=audio_data,
                            mime_type="audio/wav"
                        )
                    )
                
                # API呼び出し
                logger.info(f"API呼び出し中... (試行 {attempt + 1}/{max_retries})")
                response = self.client.models.generate_content(
                    model=MODEL_NAME,
                    contents=contents,
                )
                
                # レスポンス解析
                return self._parse_response(response.text)
                
            except Exception as e:
                logger.error(f"API呼び出しエラー (試行 {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                else:
                    raise
    
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """APIレスポンスをパース"""
        # JSON部分を抽出
        try:
            # ```json ... ``` の形式を処理
            text = response_text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            result = json.loads(text)
            
            # スコアの正規化（0-100範囲に）
            result = self._normalize_scores(result)
            
            # グレード判定
            overall = result.get("overall_score", 0)
            result["grade"] = self._determine_grade(overall)
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"JSONパースエラー: {e}")
            logger.error(f"レスポンス: {response_text[:500]}")
            return self._create_error_response("レスポンスの解析に失敗しました")
    
    def _normalize_scores(self, result: Dict) -> Dict:
        """スコアを0-100範囲に正規化"""
        for section in ["expression", "voice_tone"]:
            if section in result and isinstance(result[section], dict):
                for key, value in result[section].items():
                    if isinstance(value, dict) and "score" in value:
                        value["score"] = max(0, min(100, int(value["score"])))
        
        if "overall_score" in result:
            result["overall_score"] = max(0, min(100, int(result["overall_score"])))
        
        return result
    
    def _determine_grade(self, score: int) -> Dict:
        """スコアからグレードを判定"""
        for grade, info in GRADE_THRESHOLDS.items():
            if score >= info["min"]:
                return {"grade": grade, **info}
        return {"grade": "D", **GRADE_THRESHOLDS["D"]}
    
    def _create_error_response(self, message: str) -> Dict:
        """エラーレスポンスを作成"""
        return {
            "error": True,
            "message": message,
            "expression": {"total_score": 0},
            "voice_tone": {"total_score": 0},
            "overall_score": 0,
            "grade": {"grade": "D", "label": "エラー", "color": "#9E9E9E"}
        }

# ============================================================
# Google Drive連携
# ============================================================
class GoogleDriveHandler:
    """Google Driveから動画をダウンロード"""
    
    @staticmethod
    def extract_file_id(drive_url: str) -> Optional[str]:
        """Google Drive URLからファイルIDを抽出"""
        import re
        
        patterns = [
            r"/d/([a-zA-Z0-9_-]+)",  # https://drive.google.com/file/d/FILE_ID/view
            r"id=([a-zA-Z0-9_-]+)",  # https://drive.google.com/uc?id=FILE_ID
            r"open\?id=([a-zA-Z0-9_-]+)",  # https://drive.google.com/open?id=FILE_ID
        ]
        
        for pattern in patterns:
            match = re.search(pattern, drive_url)
            if match:
                return match.group(1)
        return None
    
    @staticmethod
    def download_video(file_id: str, output_path: str) -> bool:
        """Google Driveから動画をダウンロード"""
        import requests
        
        # 直接ダウンロードURL
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        session = requests.Session()
        response = session.get(url, stream=True)
        
        # 大容量ファイルの確認トークンを処理
        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                url = f"https://drive.google.com/uc?export=download&confirm={value}&id={file_id}"
                response = session.get(url, stream=True)
                break
        
        # ダウンロード
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=32768):
                    f.write(chunk)
            return True
        return False

# ============================================================
# Flask ルート
# ============================================================

@app.route("/")
def index():
    """メインページ"""
    return render_template("index.html")

@app.route("/api/analyze/upload", methods=["POST"])
def analyze_upload():
    """アップロードされた動画を分析"""
    if "video" not in request.files:
        return jsonify({"error": "動画ファイルが選択されていません"}), 400
    
    file = request.files["video"]
    if file.filename == "":
        return jsonify({"error": "ファイル名が空です"}), 400
    
    # 拡張子チェック
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"対応していないファイル形式です: {ext}"}), 400
    
    # ファイル保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"upload_{timestamp}.{ext}"
    video_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(video_path)
    
    try:
        # 分析実行
        result = _analyze_with_fallback(video_path)
        result["source"] = "upload"
        result["filename"] = file.filename
        return jsonify(result)
    except Exception as e:
        logger.error(f"分析エラー: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # 一時ファイル削除
        if os.path.exists(video_path):
            os.remove(video_path)

@app.route("/api/analyze/drive", methods=["POST"])
def analyze_drive():
    """Google Driveの動画を分析"""
    data = request.get_json()
    if not data or "drive_url" not in data:
        return jsonify({"error": "Google DriveのURLを入力してください"}), 400
    
    drive_url = data["drive_url"]
    file_id = GoogleDriveHandler.extract_file_id(drive_url)
    
    if not file_id:
        return jsonify({"error": "無効なGoogle Drive URLです"}), 400
    
    # ダウンロード
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = os.path.join(app.config["UPLOAD_FOLDER"], f"drive_{timestamp}.mp4")
    
    if not GoogleDriveHandler.download_video(file_id, video_path):
        return jsonify({"error": "Google Driveからダウンロードできませんでした"}), 400
    
    try:
        # 分析実行
        result = _analyze_with_fallback(video_path)
        result["source"] = "drive"
        result["drive_url"] = drive_url
        return jsonify(result)
    except Exception as e:
        logger.error(f"分析エラー: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # 一時ファイル削除
        if os.path.exists(video_path):
            os.remove(video_path)

@app.route("/api/status")
def api_status():
    """API ステータス確認"""
    return jsonify({
        "status": "ok",
        "model": MODEL_NAME,
        "api_keys": key_manager.get_status()
    })

def _analyze_with_fallback(video_path: str) -> Dict[str, Any]:
    """APIキーフォールバック付きで分析を実行"""
    if not key_manager.has_available_key:
        raise ValueError("利用可能なAPIキーがありません")
    
    last_error = None
    
    while key_manager.has_available_key:
        api_key = key_manager.current_key
        if not api_key:
            break
        
        try:
            analyzer = SalesAnalyzer(api_key)
            result = analyzer.analyze_video(video_path)
            key_manager.record_usage(api_key)
            return result
            
        except Exception as e:
            error_msg = str(e).lower()
            # クォータ制限や認証エラーの場合
            if "quota" in error_msg or "rate" in error_msg or "429" in error_msg:
                key_manager.mark_failed(api_key)
                key_manager.rotate_key()
                last_error = e
                continue
            # その他のエラーは再試行
            last_error = e
            break
    
    raise last_error or ValueError("分析に失敗しました")

# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    if not API_KEYS:
        logger.warning("APIキーが設定されていません。環境変数 GEMINI_API_KEYS を設定してください。")
        logger.warning("例: export GEMINI_API_KEYS='key1,key2,key3'")
    
    app.run(host=HOST, port=PORT, debug=DEBUG)
