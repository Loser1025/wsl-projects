const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { GoogleGenAI } = require('@google/genai');

const app = express();
const PORT = process.env.PORT || 3000;
const publicPath = path.join(__dirname, '..', 'public');

// ミドルウェア
app.use(cors());
app.use(express.json());
app.use(express.static(publicPath));

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
      total_keys: this.keys.length,
      failed_keys: this.failedKeys.size,
      available_keys: this.keys.length - this.failedKeys.size
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

// URI を使って分析
async function analyzeWithUri(prompt, fileUri, mimeType, apiKey) {
  if (!apiKey) throw new Error('利用可能なAPIキーがありません');
  const { GoogleGenAI, createPartFromUri } = require('@google/genai');
  const ai = new GoogleGenAI({ apiKey });

  const generateTimeout = 180000;
  const response = await Promise.race([
    ai.models.generateContent({
      model: 'gemini-3.1-flash-lite',
      contents: [prompt, createPartFromUri(fileUri, mimeType)],
    }),
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error('コンテンツ生成タイムアウト')), generateTimeout)
    ),
  ]);
  return response.text;
}

async function analyzeUriWithFallback(prompt, fileUri, mimeType) {
  let lastError = null;
  while (keyManager.hasAvailableKey) {
    const apiKey = keyManager.currentKey;
    if (!apiKey) break;
    try {
      const text = await analyzeWithUri(prompt, fileUri, mimeType, apiKey);
      keyManager.recordUsage(apiKey);
      return parseResponse(text);
    } catch (error) {
      console.error(`URI分析エラー: ${error.message}`);
      if (/quota|rate|429/i.test(error.message)) {
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

// バッファを Gemini Files API にアップロードして ACTIVE になるまで待つ
async function uploadToGemini(filePath, mimeType, apiKey) {
  const ai = new GoogleGenAI({ apiKey });
  const data = fs.readFileSync(filePath);
  const blob = new Blob([data], { type: mimeType });

  let file = await ai.files.upload({
    file: blob,
    config: { mimeType, displayName: 'drive_video' },
  });

  let retries = 0;
  while (file.state === 'PROCESSING' && retries < 30) {
    await new Promise(r => setTimeout(r, 3000));
    file = await ai.files.get({ name: file.name });
    retries++;
  }

  if (file.state !== 'ACTIVE') {
    throw new Error(`Gemini ファイル処理失敗: ${file.state}`);
  }
  return file;
}

// ルート
app.get('/', (req, res) => {
  res.sendFile(path.join(publicPath, 'index.html'));
});

// APIステータス
app.get('/api/status', (req, res) => {
  res.json({
    status: 'ok',
    model: 'gemini-3.1-flash-lite',
    api_keys: keyManager.status
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

  let videoPath;
  try {
    const axios = require('axios');
    videoPath = `/tmp/drive_${Date.now()}.mp4`;
    const downloadUrl = `https://drive.google.com/uc?export=download&id=${fileId}`;

    // axios はリダイレクトを自動的に追跡する
    const dlResponse = await axios.get(downloadUrl, {
      responseType: 'arraybuffer',
      maxRedirects: 10,
      timeout: 120000,
      headers: { 'User-Agent': 'Mozilla/5.0' },
    });

    // Google Drive の確認ページ（大容量ファイル）検出
    const ct = dlResponse.headers['content-type'] || '';
    if (ct.includes('text/html')) {
      // confirm トークンを探して再ダウンロード
      const html = Buffer.from(dlResponse.data).toString('utf8');
      const confirmMatch = html.match(/confirm=([0-9A-Za-z_-]+)/);
      if (!confirmMatch) {
        throw new Error('Google Drive のダウンロード確認ページを処理できませんでした。共有設定を確認してください。');
      }
      const confirmUrl = `${downloadUrl}&confirm=${confirmMatch[1]}`;
      const confirmed = await axios.get(confirmUrl, {
        responseType: 'arraybuffer',
        maxRedirects: 10,
        timeout: 120000,
        headers: { 'User-Agent': 'Mozilla/5.0' },
      });
      fs.writeFileSync(videoPath, confirmed.data);
    } else {
      fs.writeFileSync(videoPath, dlResponse.data);
    }

    // 空ファイル検出
    const stat = fs.statSync(videoPath);
    if (stat.size < 1024) {
      throw new Error('動画ファイルのダウンロードに失敗しました（ファイルが空または無効です）。共有設定を確認してください。');
    }

    const apiKey = keyManager.currentKey;
    if (!apiKey) throw new Error('利用可能なAPIキーがありません');

    const mimeType = 'video/mp4';
    const geminiFile = await uploadToGemini(videoPath, mimeType, apiKey);

    let result;
    try {
      const prompt = buildPrompt();
      result = await analyzeUriWithFallback(prompt, geminiFile.uri, mimeType);
    } finally {
      try {
        const ai = new GoogleGenAI({ apiKey });
        await ai.files.delete({ name: geminiFile.name });
      } catch (e) {}
    }

    result.source = 'drive';
    result.drive_url = drive_url;
    res.json(result);
  } catch (error) {
    console.error('分析エラー:', error);
    res.status(500).json({ error: error.message });
  } finally {
    if (videoPath) {
      try { fs.unlinkSync(videoPath); } catch (e) {}
    }
  }
});

// サーバー起動
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`サーバーが起動しました: http://localhost:${PORT}`);
  });
}

module.exports = app;
