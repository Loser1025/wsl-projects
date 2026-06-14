// ==========================================
// デバッグログ機構
// ==========================================

const debugLogs: string[] = [];

function maskPhoneNumber(phone: string): string {
  if (phone.length <= 4) return '****';
  return phone.slice(0, 3) + '****' + phone.slice(-4);
}

function formatTime(date: Date): string {
  const h = date.getHours().toString().padStart(2, '0');
  const m = date.getMinutes().toString().padStart(2, '0');
  const s = date.getSeconds().toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function addLog(message: string): void {
  const entry = `[${formatTime(new Date())}] ${message}`;
  debugLogs.push(entry);
  if (debugLogs.length > 100) {
    debugLogs.shift();
  }
}

// ==========================================
// 型定義
// ==========================================

export interface Env {
  PHONE_STORE: KVNamespace;
  ZOOM_ACCOUNT_ID: string;
  ZOOM_CLIENT_ID: string;
  ZOOM_CLIENT_SECRET: string;
  ZOOM_USER_ID: string;
  ZOOM_WEBHOOK_SECRET: string;
  ZOOM_CALLER_NUMBER: string;
}

interface PhoneValidationDetail {
  raw: string;
  cleaned: string;
  digitCount: number;
  valid: boolean;
  reason?: string;
}

interface UploadDebugResult {
  timestamp: string;
  filename: string;
  fileSize: number;
  csvPreview: string;
  totalMatched: number;
  validCount: number;
  invalidCount: number;
  invalidReasons: Record<string, number>;
  firstFewValid: string[];
  sampleRawMatches: string[];
  validationDetails: PhoneValidationDetail[];
  success: boolean;
  errorMessage?: string;
}

// ==========================================
// メインハンドラ
// ==========================================

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // ==========================================
    // 1. 管理画面 (GET /)
    // ==========================================
    if (url.pathname === '/' && request.method === 'GET') {
      try {
        const systemStatus = await env.PHONE_STORE.get('system_status') || 'stopped';
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
        const results = JSON.parse(resultsRaw).reverse();
        const nextPhone = await env.PHONE_STORE.get('next_phone');

        const lastUploadResultRaw = await env.PHONE_STORE.get('last_upload_result');
        let lastUploadResult: UploadDebugResult | null = null;
        if (lastUploadResultRaw) {
          try { lastUploadResult = JSON.parse(lastUploadResultRaw); } catch { /* ignore */ }
        }

        addLog(`[dashboard] status=${systemStatus}, index=${currentIndex}/${queue.length}, results=${results.length}`);
        const html = getAdminDashboardHTML(queue, currentIndex, systemStatus, results, nextPhone, lastUploadResult);
        return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      } catch (err: any) {
        return new Response(`エラー: ${err.message}`, { status: 500 });
      }
    }

    // ==========================================
    // 2. CSVアップロード (POST /upload)
    // ==========================================
    if (url.pathname === '/upload' && request.method === 'POST') {
      try {
        addLog('[upload] リクエスト受信');
        const formData = await request.formData();
        const file = formData.get('csv') as File | null;
        if (!file) return new Response('CSVファイルがありません', { status: 400 });

        const csvText = await file.text();
        addLog(`[upload] ファイル受信: ${file.name}, ${file.size}バイト`);

        const phonePattern = /(?:0\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{4})/g;
        const matches = csvText.match(phonePattern) || [];
        addLog(`[upload] 正規表現マッチ: ${matches.length}件`);

        const validationDetails: PhoneValidationDetail[] = [];
        const cleanNumbers: string[] = [];
        const invalidReasons: Record<string, number> = {};
        const seen = new Set<string>();

        for (const match of matches) {
          const cleaned = match.replace(/\D/g, '');
          let valid = true;
          let reason: string | undefined;

          if (!cleaned.startsWith('0')) {
            valid = false; reason = '0で始まらない';
          } else if (cleaned.length < 10 || cleaned.length > 11) {
            valid = false; reason = `桁数不足(${cleaned.length}桁)`;
          } else {
            const zoomFormat = '+81' + cleaned.slice(1);
            if (seen.has(zoomFormat)) {
              valid = false; reason = '重複';
            } else {
              seen.add(zoomFormat);
            }
          }

          validationDetails.push({ raw: match, cleaned, digitCount: cleaned.length, valid, reason });

          if (valid) {
            cleanNumbers.push(cleaned);
          } else {
            invalidReasons[reason!] = (invalidReasons[reason!] || 0) + 1;
          }
        }

        const zoomFormatNumbers = cleanNumbers.map(n => '+81' + n.slice(1));
        addLog(`[upload] バリデーション: 通過=${zoomFormatNumbers.length}, 除外=${Object.values(invalidReasons).reduce((a,b)=>a+b,0)}`);

        await env.PHONE_STORE.put('queue', JSON.stringify(zoomFormatNumbers));
        await env.PHONE_STORE.put('current_index', '0');
        await env.PHONE_STORE.put('results', '[]');
        await env.PHONE_STORE.put('system_status', 'running');
        if (zoomFormatNumbers.length > 0) {
          await env.PHONE_STORE.put('next_phone', zoomFormatNumbers[0]);
        }
        addLog(`[upload] KV保存完了: queue=${zoomFormatNumbers.length}件`);

        const uploadResult: UploadDebugResult = {
          timestamp: new Date().toISOString(),
          filename: file.name,
          fileSize: file.size,
          csvPreview: csvText.slice(0, 200),
          totalMatched: matches.length,
          validCount: zoomFormatNumbers.length,
          invalidCount: Object.values(invalidReasons).reduce((a, b) => a + b, 0),
          invalidReasons,
          firstFewValid: zoomFormatNumbers.slice(0, 3).map(maskPhoneNumber),
          sampleRawMatches: matches.slice(0, 5),
          validationDetails,
          success: zoomFormatNumbers.length > 0,
          errorMessage: zoomFormatNumbers.length === 0 ? '有効な電話番号がありませんでした' : undefined
        };
        await env.PHONE_STORE.put('last_upload_result', JSON.stringify(uploadResult));

        return new Response(null, { status: 302, headers: { 'Location': '/' } });
      } catch (err: any) {
        console.error('[ERROR] upload:', err);
        addLog(`[upload] ERROR: ${err.message}`);
        return new Response(`エラー: ${err.message}`, { status: 500 });
      }
    }

    // ==========================================
    // 3. 架電実行 (POST /dial)
    // ==========================================
    if (url.pathname === '/dial' && request.method === 'POST') {
      try {
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        const nextPhoneRaw = await env.PHONE_STORE.get('next_phone');

        const targetPhone = nextPhoneRaw || queue[currentIndex] || null;
        if (!targetPhone) {
          return new Response(JSON.stringify({ success: false, message: '架電対象の番号がありません' }), { headers: { 'Content-Type': 'application/json' } });
        }

        addLog(`[dial] 架電実行: ${maskPhoneNumber(targetPhone)}`);
        const token = await getZoomToken(env);
        await triggerZoomCall(token, env.ZOOM_USER_ID, targetPhone, env.ZOOM_CALLER_NUMBER);
        return new Response(JSON.stringify({ success: true, message: '架電しました', phone: targetPhone }), { headers: { 'Content-Type': 'application/json' } });
      } catch (err: any) {
        return new Response(JSON.stringify({ success: false, message: err.message }), { headers: { 'Content-Type': 'application/json' } });
      }
    }

    // ==========================================
    // 4. スキップ (POST /pause)
    // ==========================================
    if (url.pathname === '/pause' && request.method === 'POST') {
      try {
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        const skippedPhone = queue[currentIndex];

        const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
        const results = JSON.parse(resultsRaw);
        results.push({ phone_number: skippedPhone, result: 'スキップ', time: new Date().toISOString() });

        const nextIndex = currentIndex + 1;
        await env.PHONE_STORE.put('current_index', String(nextIndex));
        await env.PHONE_STORE.put('results', JSON.stringify(results));

        if (nextIndex < queue.length) {
          await env.PHONE_STORE.put('next_phone', queue[nextIndex]);
        } else {
          await env.PHONE_STORE.put('system_status', 'stopped');
          await env.PHONE_STORE.delete('next_phone');
        }

        return new Response(JSON.stringify({ success: true, skipped: skippedPhone, next_phone: queue[nextIndex] || null }), { headers: { 'Content-Type': 'application/json' } });
      } catch (err: any) {
        return new Response(JSON.stringify({ success: false, message: err.message }), { headers: { 'Content-Type': 'application/json' } });
      }
    }

    // ==========================================
    // 5. リセット (POST /reset)
    // ==========================================
    if (url.pathname === '/reset' && request.method === 'POST') {
      try {
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        await env.PHONE_STORE.put('current_index', '0');
        await env.PHONE_STORE.put('results', '[]');
        await env.PHONE_STORE.put('system_status', 'running');
        await env.PHONE_STORE.delete('next_phone');
        if (queue.length > 0) {
          await env.PHONE_STORE.put('next_phone', queue[0]);
        }
        addLog('[reset] リセット完了');
        return new Response(JSON.stringify({ success: true }), { headers: { 'Content-Type': 'application/json' } });
      } catch (err: any) {
        return new Response(JSON.stringify({ success: false, message: err.message }), { headers: { 'Content-Type': 'application/json' } });
      }
    }

    // ==========================================
    // 6. Webhook (POST /webhook)
    // ==========================================
    if (url.pathname === '/webhook' && request.method === 'POST') {
      try {
        const body = await request.json() as any;
        const eventType = body.event;

        addLog(`[webhook] イベント受信: ${eventType}`);

        if (eventType === 'endpoint.url_validation') {
          const plainToken = body.payload.plainToken;
          const secret = env.ZOOM_WEBHOOK_SECRET;
          const cryptoKey = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
          const signature = await crypto.subtle.sign('HMAC', cryptoKey, new TextEncoder().encode(plainToken));
          const encryptedToken = Array.from(new Uint8Array(signature)).map(b => b.toString(16).padStart(2, '0')).join('');
          return new Response(JSON.stringify({ plainToken, encryptedToken }), { headers: { 'Content-Type': 'application/json' } });
        }

        if (eventType === 'phone.call_ended' || eventType === 'phone_call_ended') {
          const callLog = body.payload?.object || body.payload || {};
          const calleeNumber = callLog.callee_number_number || callLog.callee?.phone_number || callLog.to?.phone_number || '';
          const callerNumber = callLog.caller_number_number || callLog.caller?.phone_number || callLog.from?.phone_number || '';
          const duration = callLog.duration || callLog.talk_time || 0;

          addLog(`[webhook] 通話終了: caller=${maskPhoneNumber(callerNumber)}, callee=${maskPhoneNumber(calleeNumber)}, duration=${duration}s`);

          const connected = duration > 0 || callLog.result === 'connected' || callLog.disconnect_type === 'call_end';

          const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
          const results = JSON.parse(resultsRaw);
          results.push({
            phone_number: calleeNumber,
            result: connected ? 'コネクト' : '不在/応答なし',
            time: new Date().toISOString()
          });
          await env.PHONE_STORE.put('results', JSON.stringify(results));

          const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
          const currentIndex = parseInt(currentIndexRaw, 10);
          const nextIndex = currentIndex + 1;
          await env.PHONE_STORE.put('current_index', String(nextIndex));

          const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
          const queue = JSON.parse(queueRaw);

          if (nextIndex < queue.length) {
            await env.PHONE_STORE.put('next_phone', queue[nextIndex]);
            addLog(`[webhook] → index=${nextIndex}, 次番号=${maskPhoneNumber(queue[nextIndex])}, 架電は手動です`);
          } else {
            await env.PHONE_STORE.put('system_status', 'stopped');
            await env.PHONE_STORE.delete('next_phone');
            addLog('[webhook] 全番号完了 → stopped');
          }
        }

        return new Response('OK');
      } catch (err: any) {
        console.error('[ERROR] webhook:', err);
        addLog(`[webhook] ERROR: ${err.message}`);
        return new Response('OK');
      }
    }

    // ==========================================
    // 7. 結果ダウンロード (GET /results)
    // ==========================================
    if (url.pathname === '/results' && request.method === 'GET') {
      const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
      const results = JSON.parse(resultsRaw).reverse();
      const bom = '\uFEFF';
      const csv = bom + '電話番号,結果,完了日時\n' + results.map((r: any) => `${r.phone_number},${r.result},${r.time}`).join('\n');
      return new Response(csv, { headers: { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': 'attachment; filename="results.csv"' } });
    }

    // ==========================================
    // 8. デバッグエンドポイント
    // ==========================================
    if (url.pathname === '/debug/logs' && request.method === 'GET') {
      return new Response(JSON.stringify({ logs: debugLogs, count: debugLogs.length }), { headers: { 'Content-Type': 'application/json' } });
    }

    if (url.pathname === '/debug/status' && request.method === 'GET') {
      const systemStatus = await env.PHONE_STORE.get('system_status') || 'stopped';
      const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
      const currentIndex = parseInt(currentIndexRaw, 10);
      const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
      const queue = JSON.parse(queueRaw);
      const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
      const results = JSON.parse(resultsRaw);
      const nextPhone = await env.PHONE_STORE.get('next_phone');

      const zoomVars: (keyof Env)[] = ['ZOOM_ACCOUNT_ID', 'ZOOM_CLIENT_ID', 'ZOOM_CLIENT_SECRET', 'ZOOM_USER_ID', 'ZOOM_WEBHOOK_SECRET', 'ZOOM_CALLER_NUMBER'];
      const env_check: Record<string, string> = {};
      for (const key of zoomVars) {
        const val = env[key];
        if (val === undefined || val === null) env_check[key] = '❌ 未設定';
        else if (val === '') env_check[key] = '⚠️ 空文字';
        else env_check[key] = `✅ 設定済み (${String(val).slice(0, 4)}...)`;
      }
      env_check['PHONE_STORE'] = (env.PHONE_STORE && typeof env.PHONE_STORE === 'object') ? '✅ 設定済み' : '❌ 未設定';

      const accountId = env.ZOOM_ACCOUNT_ID || '';
      const clientId = env.ZOOM_CLIENT_ID || '';

      return new Response(JSON.stringify({
        status: systemStatus,
        current_index: currentIndex,
        queue_length: queue.length,
        results_count: results.length,
        next_phone: nextPhone,
        env_check,
        token_preview: {
          accountId: accountId ? accountId.slice(0, 4) + '...' : '(未設定)',
          clientId: clientId ? clientId.slice(0, 4) + '...' : '(未設定)'
        },
        recent_logs: debugLogs.slice(-5).reverse()
      }, null, 2), { headers: { 'Content-Type': 'application/json' } });
    }

    if (url.pathname === '/debug/clear-logs' && request.method === 'POST') {
      debugLogs.length = 0;
      return new Response(JSON.stringify({ success: true }), { headers: { 'Content-Type': 'application/json' } });
    }

    if (url.pathname === '/debug' && request.method === 'GET') {
      // デバッグダッシュボード画面（manage画面のリンクから遷移）
      const systemStatus = await env.PHONE_STORE.get('system_status') || 'stopped';
      const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
      const currentIndex = parseInt(currentIndexRaw, 10);
      const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
      const queue = JSON.parse(queueRaw);
      const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
      const results = JSON.parse(resultsRaw);
      const nextPhone = await env.PHONE_STORE.get('next_phone');

      let zoomApiStatus = '🟢 接続成功';
      let zoomApiDetail = '';
      try {
        const token = await getZoomToken(env);
        zoomApiDetail = `トークン取得成功 (${token.length}文字)`;
      } catch (err: any) {
        zoomApiStatus = '🔴 接続失敗';
        zoomApiDetail = err.message || '不明なエラー';
      }

      const recentLogs = debugLogs.slice(-50).reverse();
      const errorLogs = debugLogs.filter(l => l.includes('[ERROR]')).slice(-20);
      const progressPercent = queue.length > 0 ? Math.round((currentIndex / queue.length) * 100) : 0;

      const html = `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>デバッグダッシュボード - Zoom Phone</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>
<body class="bg-slate-900 text-slate-100 font-sans min-h-screen">
  <div class="max-w-6xl mx-auto px-4 py-8">
    <header class="mb-8 border-b border-slate-700 pb-4 flex justify-between items-center">
      <h1 class="text-2xl font-bold">🔧 デバッグダッシュボード</h1>
      <a href="/" class="text-blue-400 hover:text-blue-300 text-sm">← 管理画面に戻る</a>
    </header>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
      <div class="bg-slate-800 rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-4 text-slate-300">システム状態</h2>
        <div class="space-y-2">
          <p>ステータス: <span class="font-mono ${systemStatus === 'running' ? 'text-green-400' : 'text-yellow-400'}">${systemStatus}</span></p>
          <p>進捗: <span class="font-mono">${currentIndex} / ${queue.length}</span> (${progressPercent}%)</p>
          <p>結果件数: <span class="font-mono">${results.length}</span></p>
          <p>次番号: <span class="font-mono text-green-400">${nextPhone || 'なし'}</span></p>
        </div>
      </div>
      <div class="bg-slate-800 rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-4 text-slate-300">Zoom API接続</h2>
        <p class="mb-1">${zoomApiStatus}</p>
        <p class="text-sm text-slate-400">${zoomApiDetail}</p>
      </div>
    </div>

    <div class="bg-slate-800 rounded-lg p-6 mb-8">
      <h2 class="text-lg font-semibold mb-4 text-slate-300">最新ログ (最新50件)</h2>
      <pre class="bg-slate-950 p-4 rounded text-sm overflow-x-auto max-h-64 overflow-y-auto font-mono text-xs">${recentLogs.join('\\n') || 'ログなし'}</pre>
      <form method="POST" action="/debug/clear-logs" class="mt-4">
        <button type="submit" class="px-4 py-2 bg-red-700 hover:bg-red-600 rounded text-sm">ログクリア</button>
        <button type="button" onclick="location.reload()" class="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded text-sm ml-2">リロード</button>
      </form>
    </div>

    ${errorLogs.length > 0 ? `
    <div class="bg-red-900/30 border border-red-700 rounded-lg p-6">
      <h2 class="text-lg font-semibold mb-4 text-red-400">エラーログ (${errorLogs.length}件)</h2>
      <pre class="bg-slate-950 p-4 rounded text-sm overflow-x-auto max-h-48 overflow-y-auto font-mono text-xs text-red-300">${errorLogs.join('\\n')}</pre>
    </div>
    ` : ''}
  </div>
</body>
</html>`;
      return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    }

    return new Response('Not Found', { status: 404 });
  }
};

// ==========================================
// ヘルパー関数
// ==========================================

async function getZoomToken(env: Env): Promise<string> {
  try {
    addLog('[getZoomToken] トークン取得リクエスト送信');
    const url = `https://zoom.us/oauth/token?grant_type=account_credentials&account_id=${env.ZOOM_ACCOUNT_ID}`;
    const credentials = btoa(`${env.ZOOM_CLIENT_ID}:${env.ZOOM_CLIENT_SECRET}`);
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': `Basic ${credentials}`, 'Content-Type': 'application/x-www-form-urlencoded' }
    });
    const data = await response.json() as any;
    if (!response.ok) {
      console.error(`[ERROR] getZoomToken: status=${response.status}, body=${JSON.stringify(data)}`);
      addLog(`[getZoomToken] ERROR: status=${response.status}, error=${data.error || 'unknown'}`);
      throw new Error(`Zoom OAuth failed: ${response.status}`);
    }
    addLog(`[getZoomToken] トークン取得成功`);
    return data.access_token;
  } catch (err: any) {
    console.error('[ERROR] getZoomToken 例外:', err.message, err.stack);
    addLog(`[getZoomToken] ERROR: ${err.message}`);
    throw err;
  }
}

async function triggerZoomCall(token: string, userId: string, phoneNumber: string, fromNumber: string) {
  try {
    const url = `https://api.zoom.us/v2/phone/users/${userId}/calls`;
    addLog(`[triggerZoomCall] 発信元: ${maskPhoneNumber(fromNumber)} → 発信先: ${maskPhoneNumber(phoneNumber)}`);
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: { phone_number: fromNumber },
        to: { phone_number: phoneNumber }
      })
    });
    const responseText = await response.text();
    if (!response.ok) {
      console.error(`[ERROR] triggerZoomCall: status=${response.status}, body=${responseText}`);
      addLog(`[triggerZoomCall] ERROR: status=${response.status}, body=${responseText}`);
    } else {
      addLog(`[triggerZoomCall] 成功: status=${response.status}`);
    }
  } catch (err: any) {
    console.error('[ERROR] triggerZoomCall 例外:', err.message, err.stack);
    addLog(`[triggerZoomCall] ERROR: ${err.message}`);
  }
}

// ==========================================
// ダッシュボードHTML生成
// ==========================================

function getAdminDashboardHTML(
  queue: string[],
  current: number,
  status: string,
  results: any[],
  nextPhone: string | null,
  uploadResult: UploadDebugResult | null
): string {
  const total = queue.length;
  const progressPercent = total > 0 ? Math.round((current / total) * 100) : 0;
  const displayPhone = nextPhone || queue[current] || '';
  const isFinished = current >= total;

  return `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Zoom Phone クリックToコール</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>
<body class="bg-slate-50 text-slate-800 font-sans min-h-screen">
  <div class="max-w-4xl mx-auto px-4 py-8">
    <header class="mb-8 flex justify-between items-center">
      <h1 class="text-2xl font-bold text-slate-700">📞 Zoom Phone クリックToコール</h1>
      <a href="/debug" class="text-sm text-blue-500 hover:text-blue-700">🔧 デバッグ</a>
    </header>

    <div id="message" class="mb-4 hidden p-3 rounded-lg text-sm font-medium"></div>

    ${total === 0 ? `
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-8 text-center">
      <p class="text-slate-500 mb-6 text-lg">CSVファイルをアップロードして開始してください</p>
      <form method="POST" action="/upload" enctype="multipart/form-data" class="space-y-4">
        <input type="file" name="csv" accept=".csv,.txt" required class="block w-full text-sm text-slate-500 file:mr-4 file:py-3 file:px-6 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer">
        <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg">CSVをアップロード</button>
      </form>
      <p class="text-xs text-slate-400 mt-4">※ アップロード後、最初の番号がセットされます。架電は手動ボタンで行います。</p>
    </div>
    ` : `
    <div class="space-y-6">
      <!-- 状態カード -->
      <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <div class="flex justify-between items-center mb-4">
          <span class="text-slate-500 text-sm">進捗</span>
          <span class="text-2xl font-bold">${current} <span class="text-slate-400 text-lg">/ ${total}</span></span>
        </div>
        <div class="w-full bg-slate-200 rounded-full h-3 mb-6">
          <div class="bg-blue-500 h-3 rounded-full transition-all" style="width: ${progressPercent}%"></div>
        </div>
        <div class="bg-blue-50 rounded-lg p-4 text-center">
          <p class="text-xs text-blue-400 mb-1">次の番号</p>
          <p class="text-3xl font-bold text-blue-700 tracking-wider">${displayPhone || '—'}</p>
        </div>
      </div>

      <!-- 操作ボタン -->
      <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-3">
        ${!isFinished ? `
        <button onclick="doDial()" class="w-full py-4 bg-green-600 hover:bg-green-700 active:bg-green-800 text-white font-bold text-xl rounded-xl shadow-lg shadow-green-200 transition-all">📞 架電する</button>
        <div class="grid grid-cols-2 gap-3">
          <button onclick="doPause()" class="py-3 bg-yellow-500 hover:bg-yellow-600 text-white font-semibold rounded-lg">⏭ スキップ</button>
          <button onclick="doReset()" class="py-3 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-lg">🔄 リセット</button>
        </div>
        ` : `
        <div class="text-center py-6">
          <p class="text-2xl font-bold text-green-600 mb-4">✅ 全番号完了</p>
          <button onclick="doReset()" class="py-3 px-8 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg">🔄 最初からやり直す</button>
        </div>
        `}
      </div>
    </div>
    `}

    ${uploadResult ? `
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mt-6">
      <h2 class="font-semibold mb-3 text-slate-700">📄 アップロード結果</h2>
      <div class="grid grid-cols-2 gap-4 text-sm mb-4">
        <div><span class="text-slate-500">ファイル:</span> ${uploadResult.filename}</div>
        <div><span class="text-slate-500">マッチ:</span> ${uploadResult.totalMatched}件</div>
        <div><span class="text-green-600">通過:</span> ${uploadResult.validCount}件</div>
        <div><span class="text-red-500">除外:</span> ${uploadResult.invalidCount}件</div>
      </div>
    </div>
    ` : ''}

    <!-- 結果履歴 -->
    ${results.length > 0 ? `
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mt-6">
      <div class="flex justify-between items-center mb-4">
        <h2 class="font-semibold text-slate-700">📋 結果履歴 (${results.length}件)</h2>
        <a href="/results" class="text-sm text-blue-500 hover:text-blue-700">CSVダウンロード ↓</a>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead><tr class="border-b text-slate-500"><th class="py-2 text-left">電話番号</th><th class="py-2 text-left">結果</th><th class="py-2 text-right">日時</th></tr></thead>
          <tbody>
            ${results.slice(0, 50).map(r => `
            <tr class="border-b border-slate-100">
              <td class="py-2 font-mono">${r.phone_number}</td>
              <td class="py-2"><span class="px-2 py-0.5 rounded text-xs font-medium ${r.result === 'コネクト' ? 'bg-green-100 text-green-700' : r.result === 'スキップ' ? 'bg-yellow-100 text-yellow-700' : 'bg-slate-100 text-slate-600'}">${r.result}</span></td>
              <td class="py-2 text-right text-slate-400">${r.time ? new Date(r.time).toLocaleString('ja-JP') : ''}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>
    ` : ''}
  </div>

  <script>
    function showMessage(msg, type) {
      const el = document.getElementById('message');
      el.textContent = msg;
      el.className = 'mb-4 p-3 rounded-lg text-sm font-medium ' + (type === 'success' ? 'bg-green-100 text-green-700' : type === 'error' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700');
      el.classList.remove('hidden');
      setTimeout(() => el.classList.add('hidden'), 5000);
    }

    async function doDial() {
      try {
        const res = await fetch('/dial', { method: 'POST' });
        const data = await res.json();
        showMessage(data.success ? '📞 架電しました: ' + (data.phone || '') : '❌ 架電失敗: ' + data.message, data.success ? 'success' : 'error');
        if (data.success) setTimeout(() => location.reload(), 1500);
      } catch (e) { showMessage('❌ エラー: ' + e.message, 'error'); }
    }

    async function doPause() {
      try {
        const res = await fetch('/pause', { method: 'POST' });
        const data = await res.json();
        showMessage(data.success ? '⏭ スキップしました' : '❌ ' + data.message, data.success ? 'success' : 'error');
        if (data.success) setTimeout(() => location.reload(), 800);
      } catch (e) { showMessage('❌ エラー: ' + e.message, 'error'); }
    }

    async function doReset() {
      try {
        const res = await fetch('/reset', { method: 'POST' });
        const data = await res.json();
        if (data.success) location.reload();
        else showMessage('❌ ' + data.message, 'error');
      } catch (e) { showMessage('❌ エラー: ' + e.message, 'error'); }
    }
  </script>
</body>
</html>`;
}
