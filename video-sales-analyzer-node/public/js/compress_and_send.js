// フロントエンドでの圧縮と直接送信
async function compressAndSendToGemini(file) {
  // 動画を圧縮
  const compressedFile = await compressVideo(file);

  // 圧縮した動画を直接Gemini APIに送信
  const response = await fetch('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent', {
    method: 'POST',
    body: JSON.stringify({
      contents: [
        {
          parts: [
            { text: buildPrompt() },
            {
              file_data: {
                mime_type: 'video/mp4',
                file_uri: URL.createObjectURL(compressedFile)
              }
            }
          ]
        }
      ]
    }),
    headers: {
      'Content-Type': 'application/json',
      'x-goog-api-key': process.env.GEMINI_KEY_1
    }
  });

  const result = await response.json();
  return parseResponse(result);
}

// 動画を圧縮する関数
async function compressVideo(file) {
  return new Promise((resolve) => {
    const video = document.createElement('video');
    video.src = URL.createObjectURL(file);
    video.onloadedmetadata = () => {
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      canvas.toBlob((blob) => {
        resolve(blob);
      }, 'video/mp4', 0.7); // 圧縮率を0.7に設定
    };
  });
}

// プロンプトを生成する関数
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

// レスポンスをパースする関数
function parseResponse(text) {
  try {
    let jsonText = text.trim();
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
    return result;
  } catch (error) {
    console.error('JSONパースエラー:', error);
    return {
      error: true,
      message: 'レスポンスの解析に失敗しました',
      expression: { total_score: 0 },
      voice_tone: { total_score: 0 },
      overall_score: 0
    };
  }
}