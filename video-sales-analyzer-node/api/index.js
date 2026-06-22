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
  { grade: 'S', min: 90, label: '優秀', color: '#ffd400' },
  { grade: 'A', min: 80, label: '良好', color: '#ff5a1e' },
  { grade: 'B', min: 70, label: '標準', color: '#ff8a3d' },
  { grade: 'C', min: 60, label: 'やや改善必要', color: '#ff1233' },
  { grade: 'D', min: 0, label: '改善必要', color: '#ff1233' }
];

// 採点項目の最大数
const MAX_CRITERIA_ITEMS = 10;

// 分析プロンプト（最大10個の採点項目を動的に組み込む。未入力時はAI自身に項目を考えさせる）
function buildPrompt(criteriaItems) {
  const items = Array.isArray(criteriaItems) && criteriaItems.length > 0
    ? criteriaItems.slice(0, MAX_CRITERIA_ITEMS)
    : null;

  if (!items) {
    return `あなたは動画分析の専門アナリストです。
提供された動画フレーム画像の内容をよく理解し、この動画を評価するのに最も適した採点項目を、あなた自身で最大${MAX_CRITERIA_ITEMS}個考えてください（動画の種類・目的に応じて柔軟に選んでください。例: 商談動画なら表情や説明の分かりやすさ、プレゼン動画なら構成や話し方、スポーツ動画ならフォームや技術など）。
その上で、考案した採点項目それぞれについて0-100点のスコアを付けてください。

以下のJSON形式で回答してください：
{
  "scores": [
    {"item": "<あなたが考えた採点項目1>", "score": <0-100>, "comment": "<理由>"}
    ... (動画の内容に応じて適切な数、最大${MAX_CRITERIA_ITEMS}個)
  ],
  "overall_score": <0-100（各項目を踏まえた総合点）>,
  "summary": "<総合評価コメント。どのような観点で評価したかにも触れる>",
  "improvements": ["<改善点1>", "<改善点2>", "<改善点3>"]
}`;
  }

  const itemsList = items.map((item, i) => `${i + 1}. ${item}`).join('\n');
  const scoresExample = items
    .map(item => `    {"item": "${item}", "score": <0-100>, "comment": "<理由>"}`)
    .join(',\n');
  return `あなたは動画分析の専門アナリストです。
提供された動画フレーム画像を分析し、以下の採点項目それぞれについて0-100点のスコアを付けてください。

## 採点項目
${itemsList}

以下のJSON形式で回答してください（scoresは採点項目と同じ順序・同じ件数で返してください）：
{
  "scores": [
${scoresExample}
  ],
  "overall_score": <0-100（各項目を踏まえた総合点）>,
  "summary": "<総合評価コメント>",
  "improvements": ["<改善点1>", "<改善点2>", "<改善点3>"]
}`;
}

// 比較分析プロンプト（2本の動画を「動画A」「動画B」として比較させる。未入力時はAI自身に項目を考えさせる）
function buildComparePrompt(criteriaItems) {
  const items = Array.isArray(criteriaItems) && criteriaItems.length > 0
    ? criteriaItems.slice(0, MAX_CRITERIA_ITEMS)
    : null;

  if (!items) {
    return `あなたは動画分析の専門アナリストです。
これから2本の動画を提示します。1本目を「動画A」、2本目を「動画B」とします。
まず両方の動画の内容をよく理解し、この2本を比較するのに最も適した採点項目を、あなた自身で最大${MAX_CRITERIA_ITEMS}個考えてください。
その上で、考案した採点項目それぞれについて、A・B個別に0-100点のスコアを付け、さらにどちらが総合的に優れているかを比較してください。

以下のJSON形式で回答してください（videoAとvideoBのscoresは必ず同じ採点項目・同じ順序・同じ件数にしてください）：
{
  "videoA": {
    "scores": [
      {"item": "<あなたが考えた採点項目1>", "score": <0-100>, "comment": "<理由>"}
      ... (内容に応じて適切な数、最大${MAX_CRITERIA_ITEMS}個)
    ],
    "overall_score": <0-100>
  },
  "videoB": {
    "scores": [
      {"item": "<videoAと同じ採点項目1>", "score": <0-100>, "comment": "<理由>"}
      ...
    ],
    "overall_score": <0-100>
  },
  "winner": "<総合的に優れている方。'A' か 'B'、ほぼ同等なら 'tie'>",
  "summary": "<2本を比較した総合コメント。どのような観点で評価したか、それぞれの強み・弱みの違いも含める>",
  "improvements": ["<比較から見えた改善点1>", "<改善点2>", "<改善点3>"]
}`;
  }

  const itemsList = items.map((item, i) => `${i + 1}. ${item}`).join('\n');
  const scoresExample = items
    .map(item => `      {"item": "${item}", "score": <0-100>, "comment": "<理由>"}`)
    .join(',\n');
  return `あなたは動画分析の専門アナリストです。
これから2本の動画を提示します。1本目を「動画A」、2本目を「動画B」として、以下の採点項目それぞれについて0-100点でA・B個別に採点し、さらにどちらが総合的に優れているかを比較してください。

## 採点項目
${itemsList}

以下のJSON形式で回答してください（scoresは採点項目と同じ順序・同じ件数で、A・Bそれぞれ返してください）：
{
  "videoA": {
    "scores": [
${scoresExample}
    ],
    "overall_score": <0-100>
  },
  "videoB": {
    "scores": [
${scoresExample}
    ],
    "overall_score": <0-100>
  },
  "winner": "<総合的に優れている方。'A' か 'B'、ほぼ同等なら 'tie'>",
  "summary": "<2本を比較した総合コメント。それぞれの強み・弱みの違いを含める>",
  "improvements": ["<比較から見えた改善点1>", "<改善点2>", "<改善点3>"]
}`;
}

// 比較レスポンス解析
function parseCompareResponse(text) {
  try {
    let jsonText = text.trim();

    if (jsonText.includes('```json')) {
      const match = jsonText.match(/```json\s*([\s\S]*?)\s*```/);
      if (match && match[1]) jsonText = match[1].trim();
    } else if (jsonText.includes('```')) {
      const match = jsonText.match(/```\s*([\s\S]*?)\s*```/);
      if (match && match[1]) jsonText = match[1].trim();
    }

    const result = JSON.parse(jsonText);

    const normalizeSide = (side) => {
      const overall = Math.max(0, Math.min(100, parseInt(side && side.overall_score) || 0));
      const scores = Array.isArray(side && side.scores) ? side.scores.map(s => ({
        item: String((s && s.item) || ''),
        score: Math.max(0, Math.min(100, parseInt(s && s.score) || 0)),
        comment: String((s && s.comment) || ''),
      })) : [];
      return { overall_score: overall, scores };
    };

    const videoA = normalizeSide(result.videoA);
    const videoB = normalizeSide(result.videoB);
    let winner = String(result.winner || '').trim().toUpperCase();
    if (winner !== 'A' && winner !== 'B') winner = 'TIE';

    return {
      mode: 'compare',
      videoA,
      videoB,
      winner,
      summary: String(result.summary || ''),
      improvements: Array.isArray(result.improvements) ? result.improvements : [],
    };
  } catch (error) {
    console.error('比較レスポンス解析エラー:', error);
    return {
      mode: 'compare',
      error: true,
      message: '比較結果の解析に失敗しました: ' + error.message,
      videoA: { overall_score: 0, scores: [] },
      videoB: { overall_score: 0, scores: [] },
      winner: 'TIE',
      summary: '',
      improvements: [],
    };
  }
}

// レスポンス解析
function parseResponse(text) {
  try {
    let jsonText = text.trim();


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
    if (!Array.isArray(result.scores)) {
      result.scores = [];
    }
    result.scores = result.scores.map(s => ({
      item: String((s && s.item) || ''),
      score: Math.max(0, Math.min(100, parseInt(s && s.score) || 0)),
      comment: String((s && s.comment) || ''),
    }));

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
      scores: [],
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

// 長尺動画でもトークン量を抑えるため、解像度を下げ（mediaResolution、最低のLOW=64トークン/フレーム）、
// フレームサンプリングを間引く（videoMetadata.fps, 既定1.0→0.2 = 5秒に1フレーム）。
// 動画自体の再エンコードや分割は行わず、Gemini側の取り込み設定のみで容量を削減する。
function makeVideoPart(fileUri, mimeType) {
  const { createPartFromUri } = require('@google/genai');
  return Object.assign(
    createPartFromUri(fileUri, mimeType, 'MEDIA_RESOLUTION_LOW'),
    { videoMetadata: { fps: 0.2 } }
  );
}

// URI を使って分析
async function analyzeWithUri(prompt, fileUri, mimeType, apiKey) {
  if (!apiKey) throw new Error('利用可能なAPIキーがありません');
  const ai = new GoogleGenAI({ apiKey });

  const generateTimeout = 180000;
  const response = await Promise.race([
    ai.models.generateContent({
      model: 'gemini-3.1-flash-lite',
      contents: [prompt, makeVideoPart(fileUri, mimeType)],
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

// 2本の動画を1回のリクエストに同時に渡して比較分析する
async function compareWithUri(prompt, fileUriA, fileUriB, mimeType, apiKey) {
  if (!apiKey) throw new Error('利用可能なAPIキーがありません');
  const ai = new GoogleGenAI({ apiKey });

  const generateTimeout = 180000;
  const response = await Promise.race([
    ai.models.generateContent({
      model: 'gemini-3.1-flash-lite',
      contents: [
        prompt,
        makeVideoPart(fileUriA, mimeType),
        makeVideoPart(fileUriB, mimeType),
      ],
    }),
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error('コンテンツ生成タイムアウト')), generateTimeout)
    ),
  ]);
  return response.text;
}

async function compareUriWithFallback(prompt, fileUriA, fileUriB, mimeType) {
  let lastError = null;
  while (keyManager.hasAvailableKey) {
    const apiKey = keyManager.currentKey;
    if (!apiKey) break;
    try {
      const text = await compareWithUri(prompt, fileUriA, fileUriB, mimeType, apiKey);
      keyManager.recordUsage(apiKey);
      return parseCompareResponse(text);
    } catch (error) {
      console.error(`比較分析エラー: ${error.message}`);
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
  throw lastError || new Error('比較分析に失敗しました');
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
  while (file.state === 'PROCESSING' && retries < 90) {
    await new Promise(r => setTimeout(r, 3000));
    file = await ai.files.get({ name: file.name });
    retries++;
  }

  if (file.state !== 'ACTIVE') {
    throw new Error(`Gemini ファイル処理失敗: ${file.state}`);
  }
  return file;
}

// Google Drive の共有リンクから動画をダウンロードし、ローカルの一時ファイルパスを返す
async function downloadDriveVideo(driveUrl) {
  const match = driveUrl.match(/\/d\/([a-zA-Z0-9_-]+)/);
  const fileId = match ? match[1] : null;
  if (!fileId) {
    throw new Error('無効なGoogle Drive URLです');
  }

  const axios = require('axios');
  const { CookieJar } = require('tough-cookie');
  const jar = new CookieJar();
  const client = axios.create({
    maxRedirects: 10,
    headers: { 'User-Agent': 'Mozilla/5.0' }
  });

  const videoPath = `/tmp/drive_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.mp4`;

  const initialUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=no_virus_check`;
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

  const setCookies = dlResponse.headers['set-cookie'];
  if (setCookies) {
    setCookies.forEach(cookie => jar.setCookieSync(cookie, initialUrl));
  }

  const html = Buffer.from(dlResponse.data).toString('utf8');
  const confirmMatch = html.match(/name="confirm" value="([0-9A-Za-z_-]+)"/);
  const uuidMatch = html.match(/name="uuid" value="([0-9A-Fa-f-]+)"/);

  if (confirmMatch) {
    const token = confirmMatch[1];
    const uuid = uuidMatch ? uuidMatch[1] : '';
    const confirmUrl = `https://drive.usercontent.google.com/download?id=${fileId}&export=download&confirm=${token}&uuid=${uuid}`;
    console.log(`[DEBUG] 再リクエスト実行URL: ${confirmUrl}`);

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

    if (Buffer.byteLength(confirmed.data) === 2436) {
      throw new Error('Download failed: Received warning page instead of file.');
    }
    fs.writeFileSync(videoPath, confirmed.data);
  } else {
    if (Buffer.byteLength(dlResponse.data) === 2436) {
      throw new Error('Download failed: Received warning page instead of file.');
    }
    fs.writeFileSync(videoPath, dlResponse.data);
  }

  const stat = fs.statSync(videoPath);
  if (stat.size < 1024) {
    fs.unlinkSync(videoPath);
    throw new Error('動画ファイルのダウンロードに失敗しました（ファイルが空または無効です）。共有設定を確認してください。');
  }
  console.log(`[INFO] ダウンロード完了: ${videoPath}, サイズ = ${stat.size} bytes`);
  return videoPath;
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

// Google Drive分析（1本=単体分析 / 2本=比較分析）
app.post('/api/analyze/drive', async (req, res) => {
  // 1. 受信ログと環境変数チェック
  console.log('--- Request received: /api/analyze/drive ---');
  console.log('[DEBUG] 環境変数の確認:');
  for (let i = 1; i <= 3; i++) {
    console.log(`GEMINI_KEY_${i}: ${process.env[`GEMINI_KEY_${i}`] ? '設定済み' : '未設定'}`);
  }

  const videoPaths = [];   // 後始末対象の一時ファイル（成功分のみ随時追加）
  const geminiFiles = [];  // 後始末対象のGeminiアップロード済みファイル（成功分のみ随時追加）
  let uploadApiKey = null;

  try {
    const { drive_url, drive_url_2, criteria } = req.body;
    if (!drive_url) {
      return res.status(400).json({ error: 'Google DriveのURLを入力してください' });
    }
    if (!/\/d\/([a-zA-Z0-9_-]+)/.test(drive_url)) {
      return res.status(400).json({ error: '無効なGoogle Drive URLです' });
    }
    const criteriaItems = Array.isArray(criteria)
      ? criteria.map(c => String(c).trim()).filter(c => c.length > 0).slice(0, MAX_CRITERIA_ITEMS)
      : [];
    const compareUrl = typeof drive_url_2 === 'string' ? drive_url_2.trim() : '';
    if (compareUrl && !/\/d\/([a-zA-Z0-9_-]+)/.test(compareUrl)) {
      return res.status(400).json({ error: '無効なGoogle Drive URLです（比較動画）' });
    }
    const isCompare = compareUrl.length > 0;

    uploadApiKey = keyManager.currentKey;
    if (!uploadApiKey) throw new Error('利用可能なAPIキーがありません');
    const mimeType = 'video/mp4';

    if (!isCompare) {
      // ── 単体分析 ──────────────────────────────
      console.log(`[DEBUG] ダウンロード開始: ${drive_url}`);
      const videoPath = await downloadDriveVideo(drive_url);
      videoPaths.push(videoPath);

      console.log(`[DEBUG] Geminiへアップロード開始: ${videoPath}`);
      const geminiFile = await uploadToGemini(videoPath, mimeType, uploadApiKey);
      geminiFiles.push(geminiFile);
      console.log(`[DEBUG] アップロード完了: ${geminiFile.name}`);

      const prompt = buildPrompt(criteriaItems);
      console.log('[DEBUG] 分析開始 (Gemini)');
      const result = await analyzeUriWithFallback(prompt, geminiFile.uri, mimeType);
      console.log('[DEBUG] 分析完了');

      result.source = 'drive';
      result.drive_url = drive_url;
      res.json(result);
    } else {
      // ── 比較分析（2本を並列でダウンロード・アップロードし、1回のリクエストで比較）──
      console.log(`[DEBUG] 比較モード: 2本の動画を並列処理します (${drive_url} / ${compareUrl})`);

      const trackedDownload = async (url) => {
        const p = await downloadDriveVideo(url);
        videoPaths.push(p); // 成功した時点で即座に後始末対象へ（片方失敗時も漏れなく削除するため）
        return p;
      };
      const trackedUpload = async (videoPath) => {
        const f = await uploadToGemini(videoPath, mimeType, uploadApiKey);
        geminiFiles.push(f);
        return f;
      };

      const [pathA, pathB] = await Promise.all([
        trackedDownload(drive_url),
        trackedDownload(compareUrl),
      ]);

      console.log('[DEBUG] Geminiへ並列アップロード開始');
      const [fileA, fileB] = await Promise.all([
        trackedUpload(pathA),
        trackedUpload(pathB),
      ]);
      console.log(`[DEBUG] アップロード完了: ${fileA.name}, ${fileB.name}`);

      const prompt = buildComparePrompt(criteriaItems);
      console.log('[DEBUG] 比較分析開始 (Gemini)');
      const result = await compareUriWithFallback(prompt, fileA.uri, fileB.uri, mimeType);
      console.log('[DEBUG] 比較分析完了');

      result.drive_url = drive_url;
      result.drive_url_2 = compareUrl;
      res.json(result);
    }
  } catch (error) {
    console.error(`[ERROR] API処理失敗:`, error);
    console.error(`Stack Trace:`, error.stack);
    res.status(500).json({ error: 'サーバー内部エラー: ' + error.message });
  } finally {
    if (uploadApiKey) {
      for (const gf of geminiFiles) {
        try {
          console.log(`[DEBUG] Geminiファイル削除: ${gf.name}`);
          const ai = new GoogleGenAI({ apiKey: uploadApiKey });
          await ai.files.delete({ name: gf.name });
        } catch (e) {
          console.error(`[ERROR] Geminiファイル削除失敗:`, e);
        }
      }
    }
    for (const vp of videoPaths) {
      try {
        console.log(`[DEBUG] 一時ファイル削除: ${vp}`);
        fs.unlinkSync(vp);
      } catch (e) {
        console.error(`[ERROR] 一時ファイル削除失敗:`, e);
      }
    }
  }
});

// ──────────────────────────────────────────────
// 直接アップロードエンドポイント
// ──────────────────────────────────────────────

const UPLOAD_MAX_SIZE = 100 * 1024 * 1024; // 100MB
const ALLOWED_MIME_TYPES = [
  'video/mp4',
  'video/webm',
  'video/quicktime',
  'video/x-msvideo',
];

// POST /api/upload/init — resumable upload セッション初期化
app.post('/api/upload/init', async (req, res) => {
  try {
    const { mimeType, size, displayName } = req.body;

    // バリデーション
    if (!mimeType) {
      return res.status(400).json({ error: 'mimeType は必須です' });
    }
    if (typeof size !== 'number' || size <= 0) {
      return res.status(400).json({ error: 'size は正の数値で指定してください' });
    }
    if (size > UPLOAD_MAX_SIZE) {
      return res.status(400).json({ error: `ファイルサイズは ${UPLOAD_MAX_SIZE / (1024 * 1024)}MB 以下にしてください` });
    }
    if (!ALLOWED_MIME_TYPES.includes(mimeType)) {
      return res.status(400).json({ error: `許可されていないファイル形式です。許可: ${ALLOWED_MIME_TYPES.join(', ')}` });
    }

    const apiKey = keyManager.currentKey;
    if (!apiKey) {
      return res.status(503).json({ error: '利用可能なAPIキーがありません' });
    }

    // resumable upload セッション初期化
    const axios = require('axios');
    const uploadInitUrl = 'https://generativelanguage.googleapis.com/upload/v1beta/files';
    const initResponse = await axios.post(
      uploadInitUrl,
      {
        file: {
          mimeType,
          displayName: displayName || '',
        },
      },
      {
        headers: {
          'x-goog-api-key': apiKey,
          'X-Goog-Upload-Protocol': 'resumable',
          'X-Goog-Upload-Command': 'start',
          'X-Goog-Upload-Header-Content-Length': String(size),
          'X-Goog-Upload-Header-Content-Type': mimeType,
          'Content-Type': 'application/json',
        },
        validateStatus: () => true,
      }
    );

    if (initResponse.status !== 200) {
      console.error(`[ERROR] Upload init failed: status=${initResponse.status}`);
      return res.status(502).json({ error: 'アップロードセッションの初期化に失敗しました' });
    }

    const uploadUrl = initResponse.headers['x-goog-upload-url'];
    if (!uploadUrl) {
      console.error('[ERROR] x-goog-upload-url がレスポンスヘッダーに含まれていません');
      return res.status(502).json({ error: 'アップロードURLの取得に失敗しました' });
    }

    // セッション有効期限（デフォルト1時間）
    const expiresAt = Date.now() + 3600000;

    res.json({ uploadUrl, mimeType, expiresAt });
  } catch (error) {
    console.error('[ERROR] /api/upload/init:', error.message);
    res.status(500).json({ error: 'アップロード初期化中にサーバーエラーが発生しました' });
  }
});

// POST /api/upload/complete — アップロード完了確認
app.post('/api/upload/complete', async (req, res) => {
  try {
    const { fileName } = req.body;

    if (!fileName || typeof fileName !== 'string') {
      return res.status(400).json({ error: 'fileName は必須です' });
    }

    const apiKey = keyManager.currentKey;
    if (!apiKey) {
      return res.status(503).json({ error: '利用可能なAPIキーがありません' });
    }

    const { GoogleGenAI } = require('@google/genai');
    const ai = new GoogleGenAI({ apiKey });

    // ACTIVE になるまでポーリング（最大 60 秒 = 20回 × 3秒）
    const maxRetries = 20;
    const retryInterval = 3000;
    let fileState = 'PROCESSING';
    let fileInfo = null;

    for (let i = 0; i < maxRetries; i++) {
      try {
        fileInfo = await ai.files.get({ name: fileName });
        fileState = fileInfo.state || fileInfo.status || 'UNKNOWN';

        if (fileState === 'ACTIVE') {
          break;
        }
        if (fileState === 'FAILED') {
          return res.status(500).json({ error: 'ファイルの処理に失敗しました' });
        }
      } catch (e) {
        console.error(`[ERROR] files.get 試行 ${i + 1} 失敗:`, e.message);
      }

      if (i < maxRetries - 1) {
        await new Promise(resolve => setTimeout(resolve, retryInterval));
      }
    }

    if (fileState !== 'ACTIVE') {
      return res.status(202).json({
        state: fileState,
        message: 'ファイルはまだ処理中です。後でもう一度確認してください。',
        fileName,
      });
    }

    res.json({
      fileUri: fileInfo.uri || fileInfo.name,
      fileName: fileInfo.name,
      state: fileState,
      mimeType: fileInfo.mimeType,
    });
  } catch (error) {
    console.error('[ERROR] /api/upload/complete:', error.message);
    res.status(500).json({ error: 'アップロード完了確認中にサーバーエラーが発生しました' });
  }
});

// POST /api/analyze/direct — 直接アップロード済みファイルの分析
app.post('/api/analyze/direct', async (req, res) => {
  try {
    const { fileUri, mimeType, criteria } = req.body;

    if (!fileUri || typeof fileUri !== 'string') {
      return res.status(400).json({ error: 'fileUri は必須です' });
    }

    const criteriaItems = Array.isArray(criteria)
      ? criteria.map(c => String(c).trim()).filter(c => c.length > 0).slice(0, MAX_CRITERIA_ITEMS)
      : [];

    const prompt = buildPrompt(criteriaItems);
    const effectiveMimeType = mimeType || 'video/mp4';

    const result = await analyzeUriWithFallback(prompt, fileUri, effectiveMimeType);
    result.source = 'direct_upload';

    res.json(result);
  } catch (error) {
    console.error('[ERROR] /api/analyze/direct:', error.message);
    res.status(500).json({ error: '分析中にサーバーエラーが発生しました' });
  }
});

// サーバー起動
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`サーバーが起動しました: http://localhost:${PORT}`);
  });
}

module.exports = app;
module.exports.buildPrompt = buildPrompt;
module.exports.buildComparePrompt = buildComparePrompt;
