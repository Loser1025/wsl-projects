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
    
    try {
  const response = await ai.models.generateContent({
    model: 'gemini-3.1-flash-lite',
    contents: [
      prompt,
      createPartFromUri(fileState.uri, fileState.mimeType),
    ],
  });
      
      console.log('コンテンツ生成完了');
      console.log('レスポンス:', response);
      return response.text;
    } catch (error) {
      console.error('Gemini APIエラー詳細:');
      console.error('エラーメッセージ:', error.message);
      console.error('エラータイプ:', error.constructor.name);
      console.error('エラースタック:', error.stack);
      
      // エラーレスポンスを確認
      if (error.response) {
        console.error('レスポンスステータス:', error.response.status);
        console.error('レスポンスデータ:', error.response.data);
        console.error('レスポンスヘッダー:', error.response.headers);
      }
      
      throw error;
    }
    
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
  console.log('=== Google Driveダウンロード開始 ===');
  console.log('入力URL:', url);
  
  try {
    // URLからファイルIDを抽出
    const match = url.match(/\/d\/([a-zA-Z0-9_-]+)|id=([a-zA-Z0-9_-]+)/);
    const fileId = match ? (match[1] || match[2]) : null;
    
    if (!fileId) {
      throw new Error('無効なGoogle Drive URLです。ファイルIDが見つかりません。');
    }
    
    console.log('抽出されたファイルID:', fileId);
    
    const videoPath = path.join(__dirname, 'downloaded_video.mp4');
    console.log('保存先:', videoPath);
    
    // ダウンロードURLを構築
    const driveUrl = `https://drive.google.com/uc?export=download&id=${fileId}`;
    console.log('ダウンロードURL:', driveUrl);
    
    return new Promise((resolve, reject) => {
      const file = fs.createWriteStream(videoPath);
      
      console.log('HTTPリクエストを送信中...');
      const request = https.get(driveUrl, (response) => {
        console.log('=== レスポンス受信 ===');
        console.log('ステータスコード:', response.statusCode);
        console.log('ステータスメッセージ:', response.statusMessage);
        console.log('コンテンツタイプ:', response.headers['content-type']);
        console.log('コンテンツ長:', response.headers['content-length']);
        console.log('全ヘッダー:', JSON.stringify(response.headers, null, 2));
        
  // リダイレクトを処理
  if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
    console.log('リダイレクト先:', response.headers.location);
    console.log('リダイレクト先にアクセスします...');
  
    // リダイレクト先にアクセス
    const redirectUrl = response.headers.location;
    const redirectRequest = https.get(redirectUrl, (redirectResponse) => {
      console.log('リダイレクト先のレスポンス:');
      console.log('ステータスコード:', redirectResponse.statusCode);
      console.log('コンテンツタイプ:', redirectResponse.headers['content-type']);
    
      if (redirectResponse.statusCode >= 400) {
        let errorData = '';
        redirectResponse.on('data', chunk => errorData += chunk);
        redirectResponse.on('end', () => {
          console.error('リダイレクト先のエラーレスポンス:', errorData);
          reject(new Error(`リダイレクト先でエラーが発生しました: ${redirectResponse.statusCode}`));
        });
        return;
      }
    
      // リダイレクト先のコンテンツをダウンロード
      redirectResponse.pipe(file);
      file.on('finish', () => {
        file.close();
        console.log('リダイレクト先からのダウンロード完了');
      
        const stats = fs.statSync(videoPath);
        console.log('ダウンロードされたファイルサイズ:', stats.size, 'バイト');
      
        if (stats.size === 0) {
          console.error('警告: リダイレクト先からダウンロードされたファイルが空です');
          reject(new Error('リダイレクト先からダウンロードされたファイルが空です'));
        } else {
          console.log('ファイルが正常にダウンロードされました');
          resolve(fs.readFileSync(videoPath));
        }
      });
    });
  
    redirectRequest.on('error', (err) => {
      console.error('リダイレクト先のリクエストエラー:', err.message);
      reject(err);
    });
  
    return;
  }
        
        // エラーステータスを処理
        if (response.statusCode >= 400) {
          let errorData = '';
          response.on('data', chunk => errorData += chunk);
          response.on('end', () => {
            console.error('エラーレスポンスボディ:', errorData);
            reject(new Error(`HTTPエラー ${response.statusCode}: ${response.statusMessage}\n${errorData}`));
          });
          return;
        }
        
        // ダウンロード進捗を監視
        let downloadedBytes = 0;
        response.on('data', (chunk) => {
          downloadedBytes += chunk.length;
          if (downloadedBytes % (1024 * 1024) === 0) {
            console.log(`ダウンロード中: ${downloadedBytes / (1024 * 1024)} MB`);
          }
        });
        
        response.pipe(file);
        
        file.on('finish', () => {
          file.close();
          console.log('ダウンロード完了');
          
          // ファイルサイズを確認
          const stats = fs.statSync(videoPath);
          console.log('ダウンロードされたファイルサイズ:', stats.size, 'バイト');
          
          if (stats.size === 0) {
            console.error('警告: ダウンロードされたファイルが空です');
            reject(new Error('ダウンロードされたファイルが空です。共有設定またはURLを確認してください。'));
          } else {
            console.log('ファイルが正常にダウンロードされました');
            resolve(fs.readFileSync(videoPath));
          }
        });
        
        file.on('error', (err) => {
          console.error('ファイル書き込みエラー:', err.message);
          reject(err);
        });
      });
      
      request.on('error', (err) => {
        console.error('HTTPリクエストエラー:', err.message);
        console.error('エラータイプ:', err.code);
        console.error('エラースタック:', err.stack);
        reject(err);
      });
      
      request.on('timeout', () => {
        console.error('リクエストタイムアウト');
        request.destroy();
        reject(new Error('ダウンロードタイムアウト'));
      });
      
      // 30秒でタイムアウト
      request.setTimeout(30000, () => {
        console.error('30秒経過しました。タイムアウト。');
        request.destroy();
        reject(new Error('ダウンロードタイムアウト（30秒）'));
      });
    });
  } catch (error) {
    console.error('ダウンロード処理中に例外が発生:', error.message);
    console.error('エラースタック:', error.stack);
    throw error;
  }
}

// メイン処理
(async () => {
  try {
    console.log('=== Gemini APIテスト開始 ===');
    
    // Google Driveから動画をダウンロード
    const videoBuffer = await downloadFromDrive('https://drive.google.com/file/d/1jY-yxjADzmCANlIFtHaZdSZNjGrGGKxQ/view?usp=sharing');
    console.log('動画サイズ:', videoBuffer.length, 'バイト');
    
    // 分析を実行
    const prompt = buildPrompt();
    const apiKey = keyManager.currentKey;
    const responseText = await analyzeWithGemini(prompt, videoBuffer, apiKey);
    
    console.log('=== 分析結果 ===');
    console.log(responseText);
    
    // JSONパースを試みる
    try {
      // レスポンスからJSONを抽出
      let jsonText = responseText;
      if (jsonText.includes('```json')) {
        const match = jsonText.match(/```json\s*([\s\S]*?)\s*```/);
        if (match && match[1]) {
          jsonText = match[1].trim();
        }
      } else if (jsonText.includes('```')) {
        const match = jsonText.match(/```\s*([\s\S]*?)\s*```/);
        if (match && match[1]) {
          jsonText = match[1].trim();
        }
      }
      
      const result = JSON.parse(jsonText);
      console.log('=== パース成功 ===');
      console.log('総合スコア:', result.overall_score);
      console.log('表情スコア:', result.expression.total_score);
      console.log('声トーンスコア:', result.voice_tone.total_score);
      console.log('総合評価:', result.summary);
      console.log('改善点:');
      result.improvements.forEach((item, index) => {
        console.log(`${index + 1}. ${item}`);
      });
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