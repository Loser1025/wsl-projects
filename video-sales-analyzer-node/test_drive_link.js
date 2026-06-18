// Google Driveリンクテストスクリプト
const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');

// 環境変数の設定

// サーバーの起動を待つ
setTimeout(async () => {
  try {
    console.log('Google Driveリンクテストを開始します...');
    console.log('テストURL:', 'https://drive.google.com/file/d/1x7M1OveggRz2PZM-n9b3o_t-HJYxDYer/view?usp=drive_link');
    
    const response = await axios.post('http://localhost:3000/api/analyze/drive', {
      drive_url: 'https://drive.google.com/file/d/1x7M1OveggRz2PZM-n9b3o_t-HJYxDYer/view?usp=drive_link'
    });
    
    console.log('テスト成功！');
    console.log('レスポンス:', JSON.stringify(response.data, null, 2));
  } catch (error) {
    console.error('テスト失敗:', error.message);
    if (error.response) {
      console.error('レスポンスデータ:', error.response.data);
      console.error('ステータスコード:', error.response.status);
    }
  }
}, 5000); // サーバー起動を5秒待機