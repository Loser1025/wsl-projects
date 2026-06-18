const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { GoogleGenAI } = require('@google/genai');

const app = express();
const PORT = process.env.PORT || 3000;
const publicPath = path.join(__dirname, '..', 'public');

// ミドルウェア
app.use((req, res, next) => {
  console.log(`[REQUEST] ${req.method} ${req.url}`);
  next();
});

app.use(cors());
app.use(express.json());
app.use(express.static(publicPath));

  // APIキー管理
class APIKeyManager {
  constructor() {
    this.keys = [];
    console.log('[DEBUG] APIキー読み込み開始');
    for (let i = 1; i <= 10; i++) {
      const key = process.env[`GEMINI_KEY_${i}`];
      if (key) {
        this.keys.push(key);
        console.log(`[DEBUG] GEMINI_KEY_${i} 読み込み成功`);
      }
    }
    this.currentIndex = 0;
    this.failedKeys = new Set();
    this.usage = {};
    // デバッグログ
    console.log(`[DEBUG] APIキー総数: ${this.keys.length}個`);
    if (this.keys.length > 0) {
      console.log(`[DEBUG] 最初のキーの頭: ${this.keys[0].substring(0, 8)}...`);
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
    const debugDir = '/tmp/debug-responses';
    try {
      if (!fs.existsSync(debugDir)) {
        fs.mkdirSync(debugDir, { recursive: true });
      }
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      fs.writeFileSync(`${debugDir}/response_${timestamp}.txt`, text);
      console.log(`デバッグファイル保存: ${debugDir}/response_${timestamp}.txt`);
    } catch (e) {
      console.warn(`[WARN] デバッグ用ディレクトリ作成失敗: ${debugDir}, エラー: ${e.message}`);
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
  // 1. 受信ログと環境変数チェック
  console.log('--- Request received: /api/analyze/drive ---');
  console.log('[DEBUG] 環境変数の確認:');
  for (let i = 1; i <= 3; i++) {
    console.log(`GEMINI_KEY_${i}: ${process.env[`GEMINI_KEY_${i}`] ? '設定済み' : '未設定'}`);
  }

  // 2. 全体を try-catch でラップ
  let videoPath; // スコープ修正
  try {
    const { drive_url } = req.body;
    if (!drive_url) {
      return res.status(400).json({ error: 'Google DriveのURLを入力してください' });
    }

    const match = drive_url.match(/\/d\/([a-zA-Z0-9_-]+)/);
    const fileId = match ? match[1] : null;

    if (!fileId) {
      return res.status(400).json({ error: '無効なGoogle Drive URLです' });
    }

    const axios = require('axios');
const { CookieJar } = require('tough-cookie');

const jar = new CookieJar();
const client = axios.create({
    maxRedirects: 10,
    headers: { 'User-Agent': 'Mozilla/5.0' }
});
    videoPath = `/tmp/drive_${Date.now()}.mp4`;

    // 改善：ダウンロード用URL生成
    let downloadUrl = `https://drive.google.com/uc?export=download&id=${fileId}`; console.log(`[DEBUG] ダウンロード URL: ${downloadUrl}`);

    console.log(`[DEBUG] 変換後のダウンロード用URL: ${downloadUrl}`);

    // axios はリダイレクトを自動的に追跡する
    // 修正: confirm=no_virus_check を初期リクエストに追加し、トークンを確実に取得する
    let initialUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=no_virus_check`;
    console.log(`[DEBUG] 初回リクエスト URL: ${initialUrl}`);
    
    const dlResponse = await client.get(initialUrl, {
      responseType: 'arraybuffer',
      maxRedirects: 10,
      timeout: 120000,
      headers: { 
        'User-Agent': 'Mozilla/5.0',
        'Cookie': jar.getCookieStringSync(initialUrl)
      },
    });

    // レスポンスからCookieを保存
    const setCookies = dlResponse.headers['set-cookie'];
    if (setCookies) {
      setCookies.forEach(cookie => jar.setCookieSync(cookie, initialUrl));
    }
    console.log(`[DEBUG] 初回リクエスト後、保存されたCookie: ${JSON.stringify(await jar.getCookies(initialUrl))}`);


    console.log(`[DEBUG] HTTPステータスコード: ${dlResponse.status}`);
    
    const html = Buffer.from(dlResponse.data).toString('utf8');
    const confirmMatch = html.match(/name="confirm" value="([0-9A-Za-z_-]+)"/);
    const uuidMatch = html.match(/name="uuid" value="([0-9A-Fa-f-]+)"/);
    
    if (confirmMatch) {
      const token = confirmMatch[1];
      const uuid = uuidMatch ? uuidMatch[1] : '';
      console.log(`[DEBUG] confirm token 発見: ${token}, uuid 発見: ${uuid}`);
      // Google Driveのダウンロード用URL構造を再現
      const confirmUrl = `https://drive.usercontent.google.com/download?id=${fileId}&export=download&confirm=${token}&uuid=${uuid}`;
      console.log(`[DEBUG] 再リクエスト実行URL: ${confirmUrl}`);
      console.log(`[DEBUG] 送信するCookie: ${JSON.stringify(await jar.getCookies(confirmUrl))}`);
      
      const confirmed = await client.get(confirmUrl, {
        responseType: 'arraybuffer',
        maxRedirects: 10,
        timeout: 120000,
        headers: { 
          'User-Agent': 'Mozilla/5.0', 
          'Referer': 'https://drive.google.com/',
          'Cookie': jar.getCookieStringSync(confirmUrl) 
        },
      });
      console.log(`[DEBUG] 確認後のHTTPステータスコード: ${confirmed.status}`);
      
      // 2436 bytes (警告HTML) チェック
      if (Buffer.byteLength(confirmed.data) === 2436) {
          console.error("DEBUG: 警告HTMLがダウンロードされました。中身の一部:");
          console.error(confirmed.data.toString().substring(0, 500));
          throw new Error("Download failed: Received warning page instead of file.");
      }
      
      fs.writeFileSync(videoPath, confirmed.data);
      const stats = fs.statSync(videoPath);
      console.log(`[INFO] ダウンロード完了: ファイルサイズ = ${stats.size} bytes`);

    } else {
      console.log(`[DEBUG] トークンなし、dlResponse.dataを使用`);
      
      // トークンなしの場合もサイズチェック
      if (Buffer.byteLength(dlResponse.data) === 2436) {
          console.error("DEBUG: 警告HTMLがダウンロードされました(tokenなし)。中身の一部:");
          console.error(dlResponse.data.toString().substring(0, 500));
          throw new Error("Download failed: Received warning page instead of file.");
      }
      
      fs.writeFileSync(videoPath, dlResponse.data);
    }

    // 空ファイル検出
    console.log(`[DEBUG] ダウンロード完了。パス: ${videoPath}, サイズ: ${fs.statSync(videoPath).size} bytes`);
    const stat = fs.statSync(videoPath);
    if (stat.size < 1024) {
      throw new Error('動画ファイルのダウンロードに失敗しました（ファイルが空または無効です）。共有設定を確認してください。');
    }

    const apiKey = keyManager.currentKey;
    if (!apiKey) throw new Error('利用可能なAPIキーがありません');

    const mimeType = 'video/mp4';
    console.log(`[DEBUG] Geminiへアップロード開始: ${videoPath}`);
    const geminiFile = await uploadToGemini(videoPath, mimeType, apiKey);
    console.log(`[DEBUG] アップロード完了: ${geminiFile.name}`);

    let result;
    try {
      const prompt = buildPrompt();
      console.log(`[DEBUG] 分析開始 (Gemini)`);
      result = await analyzeUriWithFallback(prompt, geminiFile.uri, mimeType);
      console.log(`[DEBUG] 分析完了`);
    } catch (error) {
      console.error(`[ERROR] 分析中のエラー:`, error);
      throw error;
    } finally {
      try {
        console.log(`[DEBUG] Geminiファイル削除: ${geminiFile.name}`);
        const ai = new GoogleGenAI({ apiKey });
        await ai.files.delete({ name: geminiFile.name });
      } catch (e) {
        console.error(`[ERROR] ファイル削除失敗:`, e);
      }
    }

    result.source = 'drive';
    result.drive_url = drive_url;
    res.json(result);
  } catch (error) {
    console.error(`[ERROR] API処理失敗:`, error);
    console.error(`Stack Trace:`, error.stack);
    res.status(500).json({ error: 'サーバー内部エラー: ' + error.message });
  } finally {
    if (videoPath) {
      try {
        console.log(`[DEBUG] 一時ファイル削除: ${videoPath}`);
        fs.unlinkSync(videoPath);
      } catch (e) {
        console.error(`[ERROR] 一時ファイル削除失敗:`, e);
      }
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
