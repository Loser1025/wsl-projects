// REST APIを使用してモデル一覧を取得
const axios = require('axios');

// 環境変数の設定
process.env.GEMINI_KEY_1 = 'AIzaSyBaWBGu5jWgZnvYcMwnbPX_uEzbDBfIYHU';

// APIキー管理
class APIKeyManager {
  constructor() {
    this.keys = [];
    for (let i = 1; i <= 10; i++) {
      const key = process.env[`GEMINI_KEY_${i}`];
      if (key) this.keys.push(key);
    }
  }

  get currentKey() {
    return this.keys[0];
  }
}

const keyManager = new APIKeyManager();

// REST APIを使用してモデル一覧を取得
async function listModels() {
  try {
    const apiKey = keyManager.currentKey;
    if (!apiKey) {
      throw new Error('APIキーが設定されていません');
    }
    
    console.log('APIキーを使用:', apiKey.substring(0, 8) + '...');
    
    // REST APIエンドポイント
    const url = 'https://generativelanguage.googleapis.com/v1beta/models';
    
    console.log('REST APIエンドポイント:', url);
    console.log('モデル一覧を取得中...');
    
    const response = await axios.get(url, {
      headers: {
        'Content-Type': 'application/json',
        'x-goog-api-key': apiKey
      }
    });
    
    console.log('利用可能なモデル:');
    response.data.models.forEach(model => {
      console.log(`- ${model.name}`);
      console.log(`  表示名: ${model.displayName}`);
      console.log(`  入力トークン制限: ${model.inputTokenLimit}`);
      console.log(`  出力トークン制限: ${model.outputTokenLimit}`);
      console.log(`  サポート対象: ${model.supportedGenerationMethods.join(', ')}`);
      console.log('');
    });
    
    return response.data;
  } catch (error) {
    console.error('モデル一覧取得エラー:');
    console.error('エラーメッセージ:', error.message);
    console.error('エラータイプ:', error.constructor.name);
    console.error('エラースタック:', error.stack);
    
    if (error.response) {
      console.error('レスポンスステータス:', error.response.status);
      console.error('レスポンスデータ:', JSON.stringify(error.response.data, null, 2));
      console.error('レスポンスヘッダー:', error.response.headers);
    }
    
    throw error;
  }
}

// メイン処理
(async () => {
  try {
    console.log('=== REST APIモデル一覧取得 ===');
    await listModels();
  } catch (error) {
    console.error('=== モデル一覧取得失敗 ===');
  }
})();