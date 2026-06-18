// Gemini APIモデル一覧取得スクリプト
const { GoogleGenAI } = require('@google/genai');

// 環境変数の設定

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

// モデル一覧を取得
async function listModels() {
  try {
    const apiKey = keyManager.currentKey;
    if (!apiKey) {
      throw new Error('APIキーが設定されていません');
    }
    
    console.log('APIキーを使用:', apiKey.substring(0, 8) + '...');
    
    const ai = new GoogleGenAI({ apiKey });
    
    console.log('モデル一覧を取得中...');
    const models = await ai.listModels();
    
    console.log('利用可能なモデル:');
    models.models.forEach(model => {
      console.log(`- ${model.name} (${model.displayName})`);
      console.log(`  入力トークン制限: ${model.inputTokenLimit}`);
      console.log(`  出力トークン制限: ${model.outputTokenLimit}`);
      console.log(`  サポート対象: ${model.supportedGenerationMethods.join(', ')}`);
      console.log('');
    });
    
    return models;
  } catch (error) {
    console.error('モデル一覧取得エラー:');
    console.error('エラーメッセージ:', error.message);
    console.error('エラータイプ:', error.constructor.name);
    console.error('エラースタック:', error.stack);
    
    if (error.response) {
      console.error('レスポンスステータス:', error.response.status);
      console.error('レスポンスデータ:', error.response.data);
    }
    
    throw error;
  }
}

// メイン処理
(async () => {
  try {
    console.log('=== Gemini APIモデル一覧取得 ===');
    await listModels();
  } catch (error) {
    console.error('=== モデル一覧取得失敗 ===');
  }
})();