const express = require('express');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { GoogleGenAI } = require('@google/genai');

const app = express();
const PORT = process.env.PORT || 3000;

// ミドルウェア
app.use(cors());
app.use(express.json());

// 静的ファイル配信
const publicPath = path.join(__dirname, '..', 'public');
app.use(express.static(publicPath, {
  etag: false,
  lastModified: false
}));

// ファイルアップロード設定
const upload = multer({
  dest: '/tmp/uploads/',
  limits: { fileSize: 4 * 1024 * 1024 }, // 4MB (Vercel制限)
  fileFilter: (req, file, cb) => {
    if (file.originalname.match(/\.(mp4|avi|mov|mkv|webm)$/i)) {
      cb(null, true);
    } else {
      cb(new Error('対応していないファイル形式です'));
    }
  }
});

// APIキー管理
class APIKeyManager {
  constructor() {
    this.keys = [];
    for (let i = 1; i <= 10; i++) {
      const key = process.env[`GEMINI_KEY_${i}`];
      if (key) this.keys.push(key);
    }
    this.currentIndex = 0;
    this.failedKeys = new Set();
    this.usage = {};
    // デバッグログ
    console.log(`APIキー読み込み: ${this.keys.length}個検出`);
    if (this.keys.length > 0) {
      console.log(`最初のキー: ${this.keys[0].substring(0, 8)}...`);
    }
  }

  get currentKey() {
    const available = this.keys.filter(k => !this.failedKeys.has(k));
    if (!available.length) return null;
    return available[this.currentIndex % available.length];
  }

  markFailed(key) {
    this.failedKeys.add(key);
  }

  rotateKey() {
    this.currentIndex++;
  }

  recordUsage(key) {
    this.usage[key] = (this.usage[key] || 0) + 1;
  }

  get hasAvailableKey() {
    return this.failedKeys.size < this.keys.length;
  }

  get status() {
    return {
      totalKeys: this.keys.length,
      failedKeys: this.failedKeys.size,
      availableKeys: this.keys.length - this.failedKeys.size
    };
  }
}

const keyManager = new APIKeyManager();

// グレード判定
const GRADE_THRESHOLDS = [
  { grade: 'S', min: 90, label: '優秀', color: '#4CAF50' },
  { grade: 'A', min: 80, label: '良好', color: '#8BC34A' },
  { grade: 'B', min: 70, label: '標準', color: '#FFC107' },
  { grade: 'C', min: 60, label: 'やや改善必要', color: '#FF9800' },
  { grade: 'D', min: 0, label: '改善必要', color: '#F44336' }
];

// 分析プロンプト
function buildPrompt() {
  return `あなたはオンライン商談の専門アナリストです。
提供された動画フレーム画像を分析し、以下の観点で0-100点のスコアを付けてください。

## 表情分析 (50%)
- 笑顔の強さ・自然さ
- アイコンタクト（カメラ目線）
- 表情の反応性
- ポジティブな表情（頷き、共感表現）
- プロフェッショナルな印象
- 表情の一貫性

## 声のトーン分析 (50%)
- 明瞭さ（聞き取りやすさ）
- 元気・生命力（声の張り）
- 話速のコントロール
- 感情表現の適切さ
- 自信の印象

以下のJSON形式で回答してください：
{
  "expression": {
    "smile_intensity": {"score": <0-100>, "comment": "<理由>"},
    "eye_contact": {"score": <0-100>, "comment": "<理由>"},
    "facial_responsiveness": {"score": <0-100>, "comment": "<理由>"},
    "positive_engagement": {"score": <0-100>, "comment": "<理由>"},
    "professional_appearance": {"score": <0-100>, "comment": "<理由>"},
    "consistency": {"score": <0-100>, "comment": "<理由>"},
    "total_score": <0-100>
  },
  "voice_tone": {
    "clarity": {"score": <0-100>, "comment": "<理由>"},
    "energy_level": {"score": <0-100>, "comment": "<理由>"},
    "pace_control": {"score": <0-100>, "comment": "<理由>"},
    "emotional_appropriateness": {"score": <0-100>, "comment": "<理由>"},
    "confidence": {"score": <0-100>, "comment": "<理由>"},
    "total_score": <0-100>
  },
  "overall_score": <0-100>,
  "summary": "<総合評価コメント>",
  "improvements": ["<改善点1>", "<改善点2>", "<改善点3>"]
}`;
}

// レスポンス解析
function parseResponse(text) {
  try {
    let jsonText = text.trim();
    
    // デバッグログ: 元のレスポンスをファイルに保存
    const fs = require('fs');
    const debugDir = path.join(__dirname, '..', 'debug-responses');
    try {
      if (!fs.existsSync(debugDir)) {
        fs.mkdirSync(debugDir, { recursive: true });
      }
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      fs.writeFileSync(`${debugDir}/response_${timestamp}.txt`, text);
      console.log(`デバッグファイル保存: ${debugDir}/response_${timestamp}.txt`);
    } catch (e) {
      console.error('デバッグファイル保存エラー:', e.message);
    }
    
    // コードブロックの抽出（より堅牢な処理）
    if (jsonText.includes('```json')) {
      const match = jsonText.match(/```json\s*([\s\S]*?)\s*```/);
      if (match && match[1]) {
        jsonText = match[1].trim();
        console.log('JSONコードブロックを抽出しました');
      } else {
        console.log('JSONコードブロックの抽出に失敗しました');
      }
    } else if (jsonText.includes('```')) {
      const match = jsonText.match(/```\s*([\s\S]*?)\s*```/);
      if (match && match[1]) {
        jsonText = match[1].trim();
        console.log('コードブロックを抽出しました');
      } else {
        console.log('コードブロックの抽出に失敗しました');
      }
    }
    
    // JSONパース
    console.log('JSONパースを試みます...');
    console.log('パース対象テキスト:', jsonText.substring(0, 200));
    
    const result = JSON.parse(jsonText);

    result.overall_score = Math.max(0, Math.min(100, parseInt(result.overall_score) || 0));

    for (const grade of GRADE_THRESHOLDS) {
      if (result.overall_score >= grade.min) {
        result.grade = grade;
        break;
      }
    }

    console.log('パース成功:', result);
    return result;
  } catch (error) {
    console.error('JSONパースエラー:', error);
    console.error('エラータイプ:', error.constructor.name);
    console.error('エラースタック:', error.stack);
    console.error('問題のあるテキスト（先頭500文字）:', text.substring(0, 500));
    console.error('問題のあるテキスト（末尾500文字）:', text.length > 500 ? text.substring(text.length - 500) : '');
    
    return {
      error: true,
      message: 'レスポンスの解析に失敗しました: ' + error.message,
      error_type: error.constructor.name,
      expression: { total_score: 0 },
      voice_tone: { total_score: 0 },
      overall_score: 0,
      grade: GRADE_THRESHOLDS[GRADE_THRESHOLDS.length - 1],
      debug_info: {
        text_length: text.length,
        text_preview: text.substring(0, 200),
        error_stack: error.stack
      }
    };
  }
}

// Gemini APIで分析（Files API使用）
async function analyzeWithGemini(prompt, videoBuffer, apiKey) {
  if (!apiKey) throw new Error('利用可能なAPIキーがありません');

  const { GoogleGenAI } = require('@google/genai');
  const ai = new GoogleGenAI({ apiKey });

  // 一時ファイルに書き込む
  const tmpPath = `/tmp/video_${Date.now()}.mp4`;
  fs.writeFileSync(tmpPath, videoBuffer);

  try {
    // Files APIでアップロード（タイムアウト: 60秒）
    const uploadTimeout = 60000;
    const fileUploadPromise = ai.files.upload({
      file: tmpPath,
      config: {
        displayName: 'video_analysis.mp4',
        mimeType: 'video/mp4',
      },
    });
    
    const file = await Promise.race([
      fileUploadPromise,
      new Promise((_, reject) => 
        setTimeout(() => reject(new Error('ファイルアップロードタイムアウト')), uploadTimeout)
      )
    ]);

    // ファイルがACTIVEになるまで待機（タイムアウト: 120秒）
    const processingTimeout = 120000;
    const startTime = Date.now();
    let fileState = await ai.files.get({ name: file.name });
    
    while (fileState.state === 'PROCESSING') {
      if (Date.now() - startTime > processingTimeout) {
        throw new Error('ファイル処理タイムアウト');
      }
      await new Promise(resolve => setTimeout(resolve, 5000));
      fileState = await ai.files.get({ name: file.name });
    }

    if (fileState.state !== 'ACTIVE') {
      throw new Error('ファイルの処理に失敗しました');
    }

    // generateContentで分析（タイムアウト: 180秒）
    const { createPartFromUri } = require('@google/genai');
    
    const generateTimeout = 180000;
    const generatePromise = ai.models.generateContent({
      model: 'gemma-4-31b-it',
      contents: [
        prompt,
        createPartFromUri(fileState.uri, fileState.mimeType),
      ],
    });
    
    const response = await Promise.race([
      generatePromise,
      new Promise((_, reject) => 
        setTimeout(() => reject(new Error('コンテンツ生成タイムアウト')), generateTimeout)
      )
    ]);

    // ファイルを削除
    await ai.files.delete({ name: file.name });

    return response.text;
  } finally {
    // 一時ファイル削除
    try { fs.unlinkSync(tmpPath); } catch (e) {}
  }
}

// フォールバック付き分析
async function analyzeWithFallback(prompt, videoBuffer) {
  let lastError = null;

  console.log(`分析開始: 利用可能キー数=${keyManager.keys.length}`);

  while (keyManager.hasAvailableKey) {
    const apiKey = keyManager.currentKey;
    console.log(`使用するキー: ${apiKey ? apiKey.substring(0, 8) + '...' : 'null'}`);
    if (!apiKey) break;

    try {
      const responseText = await analyzeWithGemini(prompt, videoBuffer, apiKey);
      keyManager.recordUsage(apiKey);
      return parseResponse(responseText);
    } catch (error) {
      console.error(`APIエラー: ${error.message}`);
      const errorMsg = error.message.toLowerCase();

      if (errorMsg.includes('quota') || errorMsg.includes('rate') || errorMsg.includes('429')) {
        keyManager.markFailed(apiKey);
        keyManager.rotateKey();
        lastError = error;
        continue;
      }

      lastError = error;
      break;
    }
  }

  throw lastError || new Error('分析に失敗しました');
}

// ルート
app.get('/', (req, res) => {
  res.sendFile(path.join(publicPath, 'index.html'));
});

// APIステータス
app.get('/api/status', (req, res) => {
  res.json({
    status: 'ok',
    model: 'gemma-4-31b-it',
    api_keys: keyManager.status
  });
});

// ファイルアップロード分析
app.post('/api/analyze/upload', (req, res) => {
  upload.single('video')(req, res, async (err) => {
    if (err) {
      console.error('アップロードエラー:', err.message);

      if (err.code === 'LIMIT_FILE_SIZE') {
        return res.status(413).json({
          error: 'ファイルサイズが大きすぎます。4.5MB以下のファイルを選択してください。'
        });
      }

      return res.status(400).json({ error: err.message });
    }

    if (!req.file) {
      return res.status(400).json({ error: '動画ファイルが選択されていません' });
    }

    try {
      const videoBuffer = fs.readFileSync(req.file.path);

      const prompt = buildPrompt();
      const result = await analyzeWithFallback(prompt, videoBuffer);

      result.source = 'upload';
      result.filename = req.file.originalname;

      res.json(result);
    } catch (error) {
      console.error('分析エラー:', error);
      res.status(500).json({ error: error.message });
    } finally {
      if (req.file && req.file.path) {
        try { fs.unlinkSync(req.file.path); } catch (e) {}
      }
    }
  });
});

// Google Drive分析
app.post('/api/analyze/drive', async (req, res) => {
  const { drive_url } = req.body;
  if (!drive_url) {
    return res.status(400).json({ error: 'Google DriveのURLを入力してください' });
  }

  const match = drive_url.match(/\/d\/([a-zA-Z0-9_-]+)|id=([a-zA-Z0-9_-]+)/);
  const fileId = match ? (match[1] || match[2]) : null;

  if (!fileId) {
    return res.status(400).json({ error: '無効なGoogle Drive URLです' });
  }

  try {
    const https = require('https');
    const videoPath = `/tmp/drive_${Date.now()}.mp4`;

    await new Promise((resolve, reject) => {
      const file = fs.createWriteStream(videoPath);
      const url = `https://drive.google.com/uc?export=download&id=${fileId}`;

      https.get(url, (response) => {
        response.pipe(file);
        file.on('finish', () => { file.close(); resolve(); });
      }).on('error', reject);
    });

    const videoBuffer = fs.readFileSync(videoPath);

    const prompt = buildPrompt();
    const result = await analyzeWithFallback(prompt, videoBuffer);

    result.source = 'drive';
    result.drive_url = drive_url;

    res.json(result);
  } catch (error) {
    console.error('分析エラー:', error);
    res.status(500).json({ error: error.message });
  }
});

// サーバー起動
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`サーバーが起動しました: http://localhost:${PORT}`);
  });
}

module.exports = app;
