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
  if (debugLogs.length > 200) {
    debugLogs.shift();
  }
}

// KVにログを保存する関数（非同期、即座に実行）
function saveLogToKV(env: Env, message: string): void {
  const entry = `[${formatTime(new Date())}] ${message}`;
  // 即座にKVに保存（awaitしないでfire-and-forget）
  env.PHONE_STORE.get('debug_logs').then(raw => {
    const logs = raw ? JSON.parse(raw) : [];
    logs.push(entry);
    if (logs.length > 200) logs.shift();
    env.PHONE_STORE.put('debug_logs', JSON.stringify(logs));
  }).catch(() => {});
}

// ==========================================
// 型定義
// ==========================================

export interface Env {
  PHONE_STORE: KVNamespace;
  ZOOM_WEBHOOK_SECRET: string;
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
    // 1. 管理画面 GET /
    // ==========================================
    if (url.pathname === '/' && request.method === 'GET') {
      try {
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
        const results = JSON.parse(resultsRaw).reverse();
        const nextPhone = await env.PHONE_STORE.get('next_phone');
        const status = await env.PHONE_STORE.get('system_status') || 'stopped';

        addLog(`[dashboard] index=${currentIndex}/${queue.length}, next=${nextPhone || 'なし'}, results=${results.length}`);
        saveLogToKV(env, `[dashboard] index=${currentIndex}/${queue.length}, next=${nextPhone || 'なし'}, results=${results.length}`);

        const html = getDashboardHTML(queue, currentIndex, results, nextPhone, status);
        return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      } catch (err: any) {
        return new Response('エラー: ' + err.message, { status: 500 });
      }
    }

    // ==========================================
    // 2. CSVアップロード POST /upload
    // ==========================================
    if (url.pathname === '/upload' && request.method === 'POST') {
      try {
        const formData = await request.formData();
        const file = formData.get('csv') as File | null;
        if (!file) return new Response('CSVファイルがありません', { status: 400 });

        const csvText = await file.text();
        const phonePattern = /(?:0\d{1,4}[-\s.]?\d{1,4}[-\s.]?\d{4})/g;
        const matches = csvText.match(phonePattern) || [];

        const cleanNumbers: string[] = [];
        const invalidReasons: Record<string, number> = {};
        const seen = new Set<string>();

        for (const match of matches) {
          let cleaned = match.replace(/\D/g, '');
          let valid = true;
          let reason: string | undefined;

          // +81 プレフィックスの名残（81始まり）を 0 始まりに正規化
          if (cleaned.startsWith('81') && cleaned.length >= 11) {
            cleaned = '0' + cleaned.slice(2);
          }

          if (!cleaned.startsWith('0')) { valid = false; reason = '0で始まらない'; }
          else if (cleaned.length < 10 || cleaned.length > 11) { valid = false; reason = `桁数不足(${cleaned.length}桁)`; }
          else {
            const zoomFormat = '+81' + cleaned.slice(1);
            if (seen.has(zoomFormat)) { valid = false; reason = '重複'; }
            else seen.add(zoomFormat);
          }

          if (valid) cleanNumbers.push(cleaned);
          else invalidReasons[reason!] = (invalidReasons[reason!] || 0) + 1;
        }

        // zoomphonecall:// 用のURI形式で保存
        const zoomCallUris = cleanNumbers.map(n => 'zoomphonecall://+81' + n.slice(1));

        await env.PHONE_STORE.put('queue', JSON.stringify(zoomCallUris));
        await env.PHONE_STORE.put('current_index', '0');
        await env.PHONE_STORE.put('results', '[]');
        await env.PHONE_STORE.put('system_status', 'running');
        if (zoomCallUris.length > 0) {
          await env.PHONE_STORE.put('next_phone', '+81' + cleanNumbers[0].slice(1));
        }

        addLog(`[upload] ${zoomCallUris.length}件保存（${matches.length}件マッチ）`);
        saveLogToKV(env, `[upload] ${zoomCallUris.length}件保存（${matches.length}件マッチ）`);
        return new Response(null, { status: 302, headers: { 'Location': '/' } });
      } catch (err: any) {
        addLog(`[upload] ERROR: ${err.message}`);
        saveLogToKV(env, `[upload] ERROR: ${err.message}`);
        return new Response('エラー: ' + err.message, { status: 500 });
      }
    }

    // ==========================================
    // 3. 次番号を取得 GET /next
    // ==========================================
    if (url.pathname === '/next' && request.method === 'GET') {
      try {
        const nextPhone = await env.PHONE_STORE.get('next_phone');
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const status = await env.PHONE_STORE.get('system_status') || 'stopped';

        if (!nextPhone || currentIndex >= queue.length) {
          const data = JSON.stringify({
            done: true,
            phone: null,
            zoomphonecall_url: null,
            index: currentIndex,
            total: queue.length
          }, null, 2);
          return new Response(data, { headers: { 'Content-Type': 'application/json' } });
        }

        const zoomUrl = queue[currentIndex] || null;
        // next_phone が +81 重複していた場合は正規化
        const normalizedPhone = nextPhone ? '+81' + nextPhone.replace('+81', '') : null;
        const data = JSON.stringify({
          done: false,
          phone: normalizedPhone,
          zoomphonecall_url: zoomUrl,
          index: currentIndex,
          total: queue.length
        }, null, 2);
        return new Response(data, { headers: { 'Content-Type': 'application/json' } });
      } catch (err: any) {
        return new Response(JSON.stringify({ error: err.message }), { status: 500, headers: { 'Content-Type': 'application/json' } });
      }
    }

    // ==========================================
    // 4. Webhook POST /webhook
    // ==========================================
    if (url.pathname === '/webhook' && request.method === 'POST') {
      try {
        const body = await request.json() as any;
        const eventType = body.event;
        saveLogToKV(env, '[webhook] event=' + eventType);
        console.log('[webhook] event=' + eventType);

        if (eventType === 'endpoint.url_validation') {
          const plainToken = body.payload.plainToken;
          const secret = env.ZOOM_WEBHOOK_SECRET;
          const cryptoKey = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
          const signature = await crypto.subtle.sign('HMAC', cryptoKey, new TextEncoder().encode(plainToken));
          const encryptedToken = Array.from(new Uint8Array(signature)).map(b => b.toString(16).padStart(2, '0')).join('');
          return new Response(JSON.stringify({ plainToken, encryptedToken }), { headers: { 'Content-Type': 'application/json' } });
        }

        if (eventType === 'phone.call_ended' || eventType === 'phone_call_ended') {
          const payload = body.payload?.object || body.payload || {};
          saveLogToKV(env, '[webhook] payload=' + JSON.stringify(payload).slice(0, 200));
          console.log('[webhook] payload=' + JSON.stringify(payload).slice(0, 200));

          const calleeNumber = payload.callee_number_number || payload.callee?.phone_number || payload.to?.phone_number || '';
          const duration = payload.duration || payload.talk_time || 0;
          const resultStr = duration > 0 ? 'コネクト' : '不在/応答なし';

          addLog('[webhook] call ended: ' + maskPhoneNumber(calleeNumber) + ', ' + resultStr + ', ' + duration + 's');
          saveLogToKV(env, '[webhook] call ended: ' + maskPhoneNumber(calleeNumber) + ', ' + resultStr + ', ' + duration + 's');

          const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
          const results = JSON.parse(resultsRaw);
          results.push({ phone_number: calleeNumber, result: resultStr, time: new Date().toISOString() });
          await env.PHONE_STORE.put('results', JSON.stringify(results));

          const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
          const nextIndex = parseInt(currentIndexRaw, 10) + 1;
          await env.PHONE_STORE.put('current_index', String(nextIndex));

          const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
          const queue = JSON.parse(queueRaw);

          let nextPhone = null;
          if (nextIndex < queue.length) {
            const rawNum = queue[nextIndex].replace('zoomphonecall://+81', '');
            nextPhone = '+81' + rawNum.replace('+81', '');
            await env.PHONE_STORE.put('next_phone', nextPhone);
            addLog('[webhook] next phone set: ' + maskPhoneNumber(nextPhone));
            saveLogToKV(env, '[webhook] next phone set: ' + maskPhoneNumber(nextPhone));
          } else {
            await env.PHONE_STORE.put('system_status', 'stopped');
            await env.PHONE_STORE.delete('next_phone');
            addLog('[webhook] all done -> stopped');
            saveLogToKV(env, '[webhook] all done -> stopped');
          }

          const respData = { ok: true, nextIndex: nextIndex, queueLen: queue.length, nextPhone: nextPhone };
          return new Response(JSON.stringify(respData), { headers: { 'Content-Type': 'application/json' } });
        }

        return new Response('OK');
      } catch (err: any) {
        addLog('[webhook] ERROR: ' + err.message);
        saveLogToKV(env, '[webhook] ERROR: ' + err.message);
        console.error('[webhook] ERROR:', err.message);
        return new Response('OK');
      }
    }

    // ==========================================
    // 5. スキップ POST /skip
    // ==========================================
    if (url.pathname === '/skip' && request.method === 'POST') {
      try {
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);

        // スキップ記録を追加
        const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
        const results = JSON.parse(resultsRaw);
        const skippedPhone = queue[currentIndex] ? '+81' + queue[currentIndex].replace('zoomphonecall://+81', '') : '不明';
        results.push({ phone_number: skippedPhone, result: 'スキップ', time: new Date().toISOString() });
        await env.PHONE_STORE.put('results', JSON.stringify(results));

        const nextIndex = currentIndex + 1;
        await env.PHONE_STORE.put('current_index', String(nextIndex));

        if (nextIndex < queue.length) {
          const rawNum = queue[nextIndex].replace('zoomphonecall://+81', '');
          const nextPhone = '+81' + rawNum.replace('+81', '');
          await env.PHONE_STORE.put('next_phone', nextPhone);
        } else {
          await env.PHONE_STORE.put('system_status', 'stopped');
          await env.PHONE_STORE.delete('next_phone');
        }

        addLog(`[skip] index=${currentIndex}をスキップ → next=${nextIndex}`);
        saveLogToKV(env, `[skip] index=${currentIndex}をスキップ → next=${nextIndex}`);
        return new Response(null, { status: 302, headers: { 'Location': '/' } });
      } catch (err: any) {
        return new Response('エラー: ' + err.message, { status: 500 });
      }
    }

    // ==========================================
    // 6. リセット POST /reset
    // ==========================================
    if (url.pathname === '/reset' && request.method === 'POST') {
      try {
        // 全データをクリア（完全リセット）
        await env.PHONE_STORE.put('queue', '[]');
        await env.PHONE_STORE.put('current_index', '0');
        await env.PHONE_STORE.put('results', '[]');
        await env.PHONE_STORE.put('system_status', 'stopped');
        await env.PHONE_STORE.delete('next_phone');
        addLog('[reset] 完全リセット完了');
        saveLogToKV(env, '[reset] 完全リセット完了');
        return new Response(null, { status: 302, headers: { 'Location': '/' } });
      } catch (err: any) {
        return new Response('エラー: ' + err.message, { status: 500 });
      }
    }

    // ==========================================
    // 7. 結果CSVダウンロード GET /results
    // ==========================================
    if (url.pathname === '/results' && request.method === 'GET') {
      const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
      const results = JSON.parse(resultsRaw).reverse();
      const bom = '\uFEFF';
      const csv = bom + '電話番号,結果,完了日時\n' + results.map((r: any) => `${r.phone_number},${r.result},${r.time}`).join('\n');
      return new Response(csv, {
        headers: { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': 'attachment; filename="results.csv"' }
      });
    }

    // ==========================================
    // 8. デバッグ GET /debug
    // ==========================================
    if (url.pathname === '/debug' && request.method === 'GET') {
      const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
      const queue = JSON.parse(queueRaw);
      const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
      const currentIndex = parseInt(currentIndexRaw, 10);
      const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
      const results = JSON.parse(resultsRaw);
      const nextPhone = await env.PHONE_STORE.get('next_phone');
      const status = await env.PHONE_STORE.get('system_status') || 'stopped';
      const progressPercent = queue.length > 0 ? Math.round((currentIndex / queue.length) * 100) : 0;
      const kvLogsRaw = await env.PHONE_STORE.get('debug_logs');
      const kvLogs = kvLogsRaw ? JSON.parse(kvLogsRaw) : [];
      const recentLogs = kvLogs.slice(-50).reverse();
      const errorLogs = kvLogs.filter((l: string) => l.includes('[ERROR]')).slice(-20);

      const html = `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8"><title>デバッグ - zoomphonecall</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>
<body class="bg-slate-900 text-slate-100 font-sans min-h-screen p-8">
  <div class="max-w-5xl mx-auto">
    <h1 class="text-2xl font-bold mb-6">🔧 デバッグダッシュボード</h1>
    <a href="/" class="text-blue-400 hover:text-blue-300 text-sm">← 管理画面</a>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6 mb-8">
      <div class="bg-slate-800 rounded-lg p-5">
        <p class="text-slate-400 text-sm">状態</p>
        <p class="text-2xl font-bold ${status === 'running' ? 'text-green-400' : 'text-yellow-400'}">${status}</p>
      </div>
      <div class="bg-slate-800 rounded-lg p-5">
        <p class="text-slate-400 text-sm">進捗</p>
        <p class="text-2xl font-bold">${currentIndex} / ${queue.length} (${progressPercent}%)</p>
      </div>
      <div class="bg-slate-800 rounded-lg p-5">
        <p class="text-slate-400 text-sm">次番号</p>
        <p class="text-xl font-mono text-green-400">${nextPhone || 'なし'}</p>
      </div>
    </div>
    <div class="bg-slate-800 rounded-lg p-5 mb-6">
      <h2 class="font-semibold mb-3">最新ログ</h2>
      <pre class="bg-slate-950 p-4 rounded text-xs font-mono max-h-64 overflow-y-auto">${recentLogs.join('\n') || 'ログなし'}</pre>
      <button onclick="fetch('/debug/clear-logs',{method:'POST'}).then(()=>location.reload())" class="mt-3 px-4 py-2 bg-red-700 hover:bg-red-600 rounded text-sm">ログクリア</button>
    </div>
    ${errorLogs.length > 0 ? `<div class="bg-red-900/30 border border-red-700 rounded-lg p-5"><h2 class="font-semibold text-red-400 mb-3">エラー (${errorLogs.length}件)</h2><pre class="bg-slate-950 p-4 rounded text-xs font-mono max-h-48 overflow-y-auto text-red-300">${errorLogs.join('\n')}</pre></div>` : ''}
  </div>
</body>
</html>`;
      return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    }

    // POST /debug/clear-logs
    if (url.pathname === '/debug/clear-logs' && request.method === 'POST') {
      await env.PHONE_STORE.delete('debug_logs');
      debugLogs.length = 0;
      return new Response('OK');
    }

    return new Response('Not Found', { status: 404 });
  }
};

// ==========================================
// ダッシュボードHTML
// ==========================================

function getDashboardHTML(
  queue: string[],
  current: number,
  results: any[],
  nextPhone: string | null,
  status: string
): string {
  const total = queue.length;
  const progressPercent = total > 0 ? Math.round((current / total) * 100) : 0;
  const isFinished = current >= total || status === 'stopped';
  const displayPhone = nextPhone || '+81' + (queue[current] || '').replace('zoomphonecall://+81', '') || '';
  const zoomUrl = queue[current] || '';

  return `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Zoom Phone クリックToコール</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>
<body class="bg-slate-50 font-sans min-h-screen">
  <div class="max-w-2xl mx-auto px-4 py-8">
    <header class="mb-8 flex justify-between items-center">
      <h1 class="text-2xl font-bold text-slate-700">📞 クリックToコール</h1>
      <a href="/debug" class="text-sm text-blue-500 hover:text-blue-700">🔧 デバッグ</a>
    </header>

    <div id="msg" class="hidden mb-4 p-3 rounded-lg text-sm font-medium"></div>

    ${total === 0 ? `
    <!-- 初期状態: CSVアップロード -->
    <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-8 text-center">
      <p class="text-slate-400 mb-6">CSVファイルをアップロードしてください</p>
      <form method="POST" action="/upload" enctype="multipart/form-data" class="space-y-4">
        <input type="file" name="csv" accept=".csv,.txt" required class="block w-full text-sm text-slate-500 file:mr-4 file:py-3 file:px-6 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer">
        <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-lg">アップロード</button>
      </form>
    </div>
    ` : `
    <!-- 番号セット済み -->
    <div class="space-y-5">
      <!-- 進捗 -->
      <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
        <div class="flex justify-between text-sm text-slate-500 mb-3">
          <span>進捗</span><span class="font-bold text-slate-700 text-lg">${current} / ${total}</span>
        </div>
        <div class="w-full bg-slate-200 rounded-full h-3 mb-5">
          <div class="bg-blue-500 h-3 rounded-full transition-all duration-500" style="width:${progressPercent}%"></div>
        </div>
        <div class="bg-blue-50 rounded-xl p-5 text-center">
          <p class="text-xs text-blue-400 mb-2 font-medium">次の番号</p>
          <p class="text-3xl font-bold text-blue-700 tracking-widest">${displayPhone || '—'}</p>
        </div>
      </div>

      <!-- 操作 -->
      <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-3">
        ${!isFinished && zoomUrl ? `
        <a href="${zoomUrl}" target="_blank" class="block w-full py-5 bg-green-600 hover:bg-green-700 active:bg-green-800 text-white font-bold text-xl rounded-xl text-center shadow-lg shadow-green-100 transition-all">📞 架電する（Zoom起動）</a>
        <div class="grid grid-cols-2 gap-3">
          <button onclick="doSkip()" class="py-3 bg-yellow-500 hover:bg-yellow-600 text-white font-semibold rounded-lg transition-all">⏭ スキップ</button>
          <button onclick="doReset()" class="py-3 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-lg transition-all">🔄 リセット</button>
        </div>
        ` : `
        <div class="text-center py-6">
          <p class="text-2xl font-bold text-green-600 mb-4">✅ 完了</p>
          <button onclick="doReset()" class="py-3 px-8 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg">🔄 もう一度</button>
        </div>
        `}
      </div>
    </div>
    `}

    <!-- 結果履歴 -->
    ${results.length > 0 ? `
    <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 mt-6">
      <div class="flex justify-between items-center mb-4">
        <h2 class="font-semibold text-slate-700">📋 履歴 (${results.length}件)</h2>
        <a href="/results" class="text-sm text-blue-500 hover:text-blue-700">CSV ↓</a>
      </div>
      <table class="w-full text-sm">
        <thead><tr class="border-b border-slate-100 text-slate-400"><th class="py-2 text-left">番号</th><th class="py-2 text-left">結果</th><th class="py-2 text-right">日時</th></tr></thead>
        <tbody>
          ${results.slice(0, 50).map(r => `
          <tr class="border-b border-slate-50">
            <td class="py-2 font-mono">${r.phone_number}</td>
            <td class="py-2"><span class="px-2 py-0.5 rounded text-xs font-medium ${r.result === 'コネクト' ? 'bg-green-100 text-green-700' : r.result === 'スキップ' ? 'bg-yellow-100 text-yellow-700' : 'bg-slate-100 text-slate-600'}">${r.result}</span></td>
            <td class="py-2 text-right text-slate-400 text-xs">${r.time ? new Date(r.time).toLocaleString('ja-JP') : ''}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>
    ` : ''}
  </div>

  <script>
    function show(msg, type) {
      const el = document.getElementById('msg');
      el.textContent = msg;
      el.className = 'mb-4 p-3 rounded-lg text-sm font-medium ' + (type === 'ok' ? 'bg-green-100 text-green-700' : type === 'err' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700');
      el.classList.remove('hidden');
      setTimeout(() => el.classList.add('hidden'), 4000);
    }
    async function doSkip() {
      await fetch('/skip', { method: 'POST' });
      location.reload();
    }
    async function doReset() {
      await fetch('/reset', { method: 'POST' });
      location.reload();
    }
    function makeCall(url) {
      // 新しいウィンドウ/タブで開く（ポップアップブロッカーに引っかかる可能性あり）
      window.open(url, '_blank');

      // フォールバック: location.assignも試す
      setTimeout(() => {
        window.location.assign(url);
      }, 100);
    }
  </script>
</body>
</html>`;
}
