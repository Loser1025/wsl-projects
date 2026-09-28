function base64url(bytes) {
  let binary = '';
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  for (let i = 0; i < arr.length; i++) binary += String.fromCharCode(arr[i]);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function base64urlFromString(str) { return base64url(new TextEncoder().encode(str)); }
function pemToDer(pem) {
  const b64 = pem.replace(/-----BEGIN PRIVATE KEY-----/, '').replace(/-----END PRIVATE KEY-----/, '').replace(/\s+/g, '');
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function getAccessToken(env) {
  const key = await crypto.subtle.importKey('pkcs8', pemToDer(env.GOOGLE_SERVICE_ACCOUNT_KEY.replace(/\\n/g, '\n')), { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['sign']);
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: 'RS256', typ: 'JWT' };
  const claims = { iss: env.GOOGLE_SERVICE_ACCOUNT_EMAIL, scope: 'https://www.googleapis.com/auth/spreadsheets', aud: 'https://oauth2.googleapis.com/token', exp: now + 3600, iat: now };
  const signingInput = base64urlFromString(JSON.stringify(header)) + '.' + base64urlFromString(JSON.stringify(claims));
  const signature = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key, new TextEncoder().encode(signingInput));
  const jwt = signingInput + '.' + base64url(signature);
  const tokenRes = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'grant_type=' + encodeURIComponent('urn:ietf:params:oauth:grant-type:jwt-bearer') + '&assertion=' + jwt,
  });
  const tokenJson = await tokenRes.json();
  if (!tokenJson.access_token) throw new Error('token_error: ' + JSON.stringify(tokenJson));
  return tokenJson.access_token;
}

const REQUIRED_FIELDS = ['postal', 'address', 'name', 'kana', 'dob', 'gender', 'bloodType', 'height', 'weight', 'pregnancy', 'breastfeeding', 'nationality', 'passportNumber'];

async function notifyTelegram(env, text) {
  const token = env.TELEGRAM_BOT_TOKEN;
  const chatId = env.TELEGRAM_CHAT_ID;
  const threadId = env.TELEGRAM_QUESTIONNAIRE_THREAD_ID;
  if (!token || !chatId) return;
  try {
    await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, message_thread_id: threadId ? Number(threadId) : undefined, text }),
    });
  } catch (err) {
    console.error('telegram_notify_failed', err);
  }
}

export async function onRequestPost({ request, env }) {
  let body;
  try { body = await request.json(); } catch { return new Response(JSON.stringify({ error: 'invalid_json' }), { status: 400 }); }

  for (const field of REQUIRED_FIELDS) {
    if (!body[field]) return new Response(JSON.stringify({ error: `missing_field:${field}` }), { status: 400 });
  }

  try {
    const accessToken = await getAccessToken(env);
    const row = [
      new Date().toISOString(),
      body.postal, body.address, body.name, body.kana, body.dob, body.gender, body.bloodType, body.height, body.weight,
      body.visitHistory, body.referral, body.interest, body.payment,
      body.symptomConcern, body.majorHistory, body.medicalHistory, body.chronicOngoing, body.currentMeds, body.allergies, body.metalImplant,
      body.cancerStatus, body.cancerYears, body.otherDiseaseName,
      body.pregnancy, body.breastfeeding, body.pillUse, body.childbirth, body.childbirthDetail, body.finalConcern,
      body.nationality, body.passportNumber,
    ].map((v) => v ?? '');

    const range = encodeURIComponent('問診票（韓国）!A:AZ');
    const sheetsRes = await fetch(
      `https://sheets.googleapis.com/v4/spreadsheets/${env.GOOGLE_SHEET_ID}/values/${range}:append?valueInputOption=USER_ENTERED`,
      { method: 'POST', headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ values: [row] }) }
    );
    if (!sheetsRes.ok) {
      console.error('sheets_error', await sheetsRes.text());
      return new Response(JSON.stringify({ error: 'sheet_write_failed' }), { status: 500 });
    }
    await notifyTelegram(
      env,
      `🩺 新しい問診回答が届きました（韓国）\n\n` +
      `・氏名： ${body.name}（${body.kana}）\n` +
      `・国籍： ${body.nationality}\n` +
      `・パスポート番号： ${body.passportNumber}\n` +
      `・生年月日： ${body.dob}\n` +
      `・性別： ${body.gender}\n` +
      `・ご来院歴： ${body.visitHistory || '-'}\n` +
      `・ご希望メニュー： ${body.interest || '-'}`
    );

    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  } catch (err) {
    console.error(err);
    return new Response(JSON.stringify({ error: 'internal_error', message: String(err) }), { status: 500 });
  }
}
