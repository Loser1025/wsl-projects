// Gemini API直接テストスクリプト
const { GoogleGenAI } = require('@google/genai');
const fs = require('fs');
const https = require('https');
const path = require('path');

// 環境変数の設定
process.env.GEMINI_KEY_1 = 'AIzaSyBaWBGu5jWgZnvYcMwnbPX_uEzbDBfIYHU';
process.env.GEMINI_KEY_2 = 'AIzaSyBSKMJKgDzHtYVxCMl0ftQFRoPOqJmNl1Y';
process.env.GEMINI_KEY_3 = 'AIzaSyCd9WZdcnv_ycWf-YE_IaAEm22revgv49w';

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
  }

  get currentKey() {
    const available = this.keys.filter(k => !this.failedKeys.has(k));
    if (available.length === 0) return null;
    return available[this.currentIndex % available.length];
  }
}

const keyManager = new APIKeyManager();

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

// Gemini APIで分析
async function analyzeWithGemini(prompt, videoBuffer, apiKey) {
  console.log('Gemini API分析を開始します...');
  console.log('使用するAPIキー:', apiKey.substring(0, 8) + '...');
  
  const ai = new GoogleGenAI({ apiKey });
  
  // 一時ファイルに書き込む
  const tmpPath = path.join(__dirname, 'test_video.mp4');
  fs.writeFileSync(tmpPath, videoBuffer);
  console.log('一時ファイルを作成:', tmpPath);
  
  try {
    // Files APIでアップロード
    console.log('ファイルをアップロード中...');
    const file = await ai.files.upload({
      file: tmpPath,
      config: {
        displayName: 'video_analysis.mp4',
        mimeType: 'video/mp4',
      },
    });
    console.log('ファイルアップロード完了:', file.name);

    // ファイルがACTIVEになるまで待機
    console.log('ファイル処理を待機中...');
    let fileState = await ai.files.get({ name: file.name });
    while (fileState.state === 'PROCESSING') {
      console.log('ファイル処理中...');
      await new Promise(resolve => setTimeout(resolve, 5000));
      fileState = await ai.files.get({ name: file.name });
    }
    
    if (fileState.state !== 'ACTIVE') {
      throw new Error('ファイルの処理に失敗しました');
    }
    console.log('ファイル処理完了');

    // generateContentで分析
    console.log('コンテンツ生成中...');
    const { createPartFromUri } = require('@google/genai');
    
    const response = await ai.models.generateContent({
      model: 'gemma-4-31b-it',
      contents: [
        prompt,
        createPartFromUri(fileState.uri, fileState.mimeType),
      ],
    });
    
    console.log('コンテンツ生成完了');
    
    // ファイルを削除
    await ai.files.delete({ name: file.name });
    console.log('ファイルを削除');

    return response.text;
  } finally {
    // 一時ファイル削除
    try {
      fs.unlinkSync(tmpPath);
      console.log('一時ファイルを削除');
    } catch (e) {
      console.error('一時ファイル削除エラー:', e.message);
    }
  }
}

// Google Driveから動画をダウンロード
async function downloadFromDrive(url) {
  console.log('Google Driveから動画をダウンロード中...');
  console.log('URL:', url);
  
  const match = url.match(/\/d\/([a-zA-Z0-9_-]+)|id=([a-zA-Z0-9_-]+)/);
  const fileId = match ? (match[1] || match[2]) : null;
  
  if (!fileId) {
    throw new Error('無効なGoogle Drive URLです');
  }
  
  console.log('ファイルID:', fileId);
  
  const videoPath = path.join(__dirname, 'downloaded_video.mp4');
  
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(videoPath);
    const driveUrl = `https://drive.google.com/uc?export=download&id=${fileId}`;
    
    console.log('ダウンロードURL:', driveUrl);
    
    https.get(driveUrl, (response) => {
      console.log('ステータスコード:', response.statusCode);
      console.log('コンテンツタイプ:', response.headers['content-type']);
      
      response.pipe(file);
      file.on('finish', () => {
        file.close();
        console.log('ダウンロード完了:', videoPath);
        resolve(fs.readFileSync(videoPath));
      });
    }).on('error', (err) => {
      console.error('ダウンロードエラー:', err.message);
      reject(err);
    });
  });
}

// メイン処理
(async () => {
  try {
    console.log('=== Gemini APIテスト開始 ===');
    
    // Google Driveから動画をダウンロード
    const videoBuffer = await downloadFromDrive('https://drive.google.com/file/d/1x7M1OveggRz2PZM-n9b3o_t-HJYxDYer/view?usp=sharing');
    console.log('動画サイズ:', videoBuffer.length, 'バイト');
    
    // 分析を実行
    const prompt = buildPrompt();
    const apiKey = keyManager.currentKey;
    const responseText = await analyzeWithGemini(prompt, videoBuffer, apiKey);
    
    console.log('=== 分析結果 ===');
    console.log(responseText);
    
    // JSONパースを試みる
    try {
      const result = JSON.parse(responseText);
      console.log('=== パース成功 ===');
      console.log('総合スコア:', result.overall_score);
    } catch (parseError) {
      console.error('=== JSONパースエラー ===');
      console.error(parseError.message);
      console.log('レスポンステキスト（先頭500文字）:', responseText.substring(0, 500));
    }
    
  } catch (error) {
    console.error('=== テスト失敗 ===');
    console.error('エラー:', error.message);
    console.error('スタック:', error.stack);
  }
})();