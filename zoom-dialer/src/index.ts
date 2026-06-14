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

export interface Env {
  PHONE_STORE: KVNamespace;
  ZOOM_ACCOUNT_ID: string;
  ZOOM_CLIENT_ID: string;
  ZOOM_CLIENT_SECRET: string;
  ZOOM_USER_ID: string;
  ZOOM_WEBHOOK_SECRET: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // ==========================================
    // 1. WEBアプリの画面表示 (GET /)
    // ==========================================
    if (url.pathname === '/' && request.method === 'GET') {
      const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
      const queue = JSON.parse(queueRaw);
      const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
      const currentIndex = parseInt(currentIndexRaw, 10);
      const systemStatus = await env.PHONE_STORE.get('system_status') || 'stopped';
      const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
      const results = JSON.parse(resultsRaw).reverse();

      addLog(`[dashboard] 表示: status=${systemStatus}, index=${currentIndex}, results=${results.length}件`);

      const html = getAdminDashboardHTML(queue.length, currentIndex, systemStatus, results);
      return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    }

    // ==========================================
    // 2. CSVアップロード処理 (POST /upload)
    // ==========================================
    if (url.pathname === '/upload' && request.method === 'POST') {
      try {
        addLog('[upload] リクエスト受信');
        const formData = await request.formData();
        const file = formData.get('csv') as File | null;
        if (!file) {
          console.error('[ERROR] CSVファイルがフォームに含まれていません');
          addLog('[upload] ERROR: ファイルなし');
          return new Response('CSVファイルがありません', { status: 400 });
        }

        addLog(`[upload] ファイル受信: name=${file.name}, size=${file.size}bytes`);
        const csvText = await file.text();
        const phonePattern = /(?:0\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{4})/g;
        const matches = csvText.match(phonePattern) || [];
        addLog(`[upload] 正規表現マッチ件数: ${matches.length}`);

        const cleanNumbers: string[] = [];
        let excludedCount = 0;
        for (const match of matches) {
          const cleanNum = match.replace(/\D/g, '');
          if ((cleanNum.length === 10 || cleanNum.length === 11) && cleanNum.startsWith('0')) {
            const zoomFormat = '+81' + cleanNum.slice(1);
            if (!cleanNumbers.includes(zoomFormat)) cleanNumbers.push(zoomFormat);
          } else {
            excludedCount++;
          }
        }
        addLog(`[upload] バリデーション通過: ${cleanNumbers.length}件, 除外: ${excludedCount}件`);

        if (cleanNumbers.length === 0) {
          addLog('[upload] ERROR: 有効な電話番号が0件');
          return new Response('<script>alert("有効な電話番号が見つかりませんでした。"); location.href="/";</script>', { headers: { 'Content-Type': 'text/html' } });
        }

        await env.PHONE_STORE.put('queue', JSON.stringify(cleanNumbers));
        await env.PHONE_STORE.put('results', JSON.stringify([]));
        await env.PHONE_STORE.put('current_index', '0');
        await env.PHONE_STORE.put('system_status', 'running');
        addLog(`[upload] KV保存完了: queue=${cleanNumbers.length}件, current_index=0, status=running`);

        const token = await getZoomToken(env);
        addLog(`[upload] 初回架電を開始: ${maskPhoneNumber(cleanNumbers[0])}`);
        await triggerZoomCall(token, env.ZOOM_USER_ID, cleanNumbers[0]);

        addLog('[upload] 処理完了 → リダイレクト');
        return Response.redirect(url.origin, 303);
      } catch (err: any) {
        console.error('[ERROR] upload 処理で例外:', err.message, err.stack);
        addLog(`[upload] ERROR: ${err.message}`);
        return new Response(
          `<script>alert("アップロード処理中にエラーが発生しました: ${err.message}"); location.href="/";</script>`,
          { headers: { 'Content-Type': 'text/html' }, status: 500 }
        );
      }
    }

    // ==========================================
    // 3. 一時停止 / 再開の制御 (POST /toggle-status)
    // ==========================================
    if (url.pathname === '/toggle-status' && request.method === 'POST') {
      try {
        addLog('[toggle-status] リクエスト受信');
        const currentStatus = await env.PHONE_STORE.get('system_status') || 'stopped';
        let newStatus = 'stopped';

        if (currentStatus === 'running') {
          newStatus = 'paused';
          addLog(`[toggle-status] ${currentStatus} → ${newStatus}`);
        } else if (currentStatus === 'paused') {
          newStatus = 'running';
          addLog(`[toggle-status] ${currentStatus} → ${newStatus}`);

          const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
          const queue = JSON.parse(queueRaw);
          const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
          const currentIndex = parseInt(currentIndexRaw, 10);

          if (currentIndex < queue.length) {
            addLog(`[toggle-status] 再開: index=${currentIndex}, ${maskPhoneNumber(queue[currentIndex])}`);
            const token = await getZoomToken(env);
            await triggerZoomCall(token, env.ZOOM_USER_ID, queue[currentIndex]);
          } else {
            addLog('[toggle-status] キュー終了済みのため架電不要');
          }
        } else {
          addLog(`[toggle-status] ${currentStatus} → stopped (デフォルト)`);
        }

        await env.PHONE_STORE.put('system_status', newStatus);
        return Response.redirect(url.origin, 303);
      } catch (err: any) {
        console.error('[ERROR] toggle-status 処理で例外:', err.message, err.stack);
        addLog(`[toggle-status] ERROR: ${err.message}`);
        return Response.redirect(url.origin, 303);
      }
    }

    // ==========================================
    // 4. Zoom Webhook受付 (POST /webhook)
    // ==========================================
    if (url.pathname === '/webhook' && request.method === 'POST') {
      try {
        addLog('[webhook] リクエスト受信');
        const body = await request.json() as any;
        addLog(`[webhook] イベント種別: ${body.event}`);

        if (body.event === 'endpoint.url_validation') {
          addLog('[webhook] URL検証リクエストを処理');
          const encryptedToken = await cryptoHmacSha256(body.payload.plainToken, env.ZOOM_WEBHOOK_SECRET);
          return new Response(JSON.stringify({ plainToken: body.payload.plainToken, encryptedToken }), {
            headers: { 'Content-Type': 'application/json' }
          });
        }

        if (body.event === 'phone.call_ended') {
          const callLog = body.payload.object;
          const lastPhone = callLog.callee_number_number || callLog.caller_number_number;
          const resultStatus = callLog.result;
          const statusJapanese = resultStatus === 'completed' ? 'コネクト' : '不在/応答なし';
          addLog(`[webhook] 通話終了: ${maskPhoneNumber(lastPhone)}, 結果=${statusJapanese}`);

          const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
          const results = JSON.parse(resultsRaw);
          results.push({ phone_number: lastPhone, result: statusJapanese, time: new Date().toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }) });
          await env.PHONE_STORE.put('results', JSON.stringify(results));

          const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
          const nextIndex = parseInt(currentIndexRaw, 10) + 1;
          await env.PHONE_STORE.put('current_index', nextIndex.toString());

          const systemStatus = await env.PHONE_STORE.get('system_status') || 'stopped';
          const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
          const queue = JSON.parse(queueRaw);

          if (systemStatus === 'running' && nextIndex < queue.length) {
            const nextPhone = queue[nextIndex];
            addLog(`[webhook] 次番号へ遷移: index=${nextIndex}, ${maskPhoneNumber(nextPhone)}`);
            const token = await getZoomToken(env);
            await triggerZoomCall(token, env.ZOOM_USER_ID, nextPhone);
          } else if (nextIndex >= queue.length) {
            await env.PHONE_STORE.put('system_status', 'stopped');
            addLog('[webhook] キュー消化完了 → system_status=stopped');
          } else {
            addLog(`[webhook] 架電スキップ: status=${systemStatus}, nextIndex=${nextIndex}`);
          }

          return new Response('Webhook Processed', { status: 200 });
        }

        addLog(`[webhook] 未処理イベント: ${body.event}`);
        return new Response('Event Ignored', { status: 200 });
      } catch (err: any) {
        console.error('[ERROR] webhook 処理で例外:', err.message, err.stack);
        addLog(`[webhook] ERROR: ${err.message}`);
        return new Response('Internal Server Error', { status: 500 });
      }
    }

    // ==========================================
    // 5. 結果CSVのダウンロード (GET /results)
    // ==========================================
    if (url.pathname === '/results' && request.method === 'GET') {
      try {
        addLog('[results] リクエスト受信');
        const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
        const results = JSON.parse(resultsRaw);
        addLog(`[results] 結果件数: ${results.length}件`);

        let csvString = '﻿電話番号,結果,架電日時\n';
        for (const row of results) {
          csvString += `"${row.phone_number}","${row.result}","${row.time}"\n`;
        }

        return new Response(csvString, {
          headers: {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': 'attachment; filename="zoom_call_results.csv"'
          }
        });
      } catch (err: any) {
        console.error('[ERROR] results 処理で例外:', err.message, err.stack);
        addLog(`[results] ERROR: ${err.message}`);
        return new Response('Error generating CSV', { status: 500 });
      }
    }

    // ==========================================
    // 6. デバッグ用APIエンドポイント
    // ==========================================

    // GET /debug/logs — 全ログを返す
    if (url.pathname === '/debug/logs' && request.method === 'GET') {
      addLog('[debug] /debug/logs リクエスト受信');
      return new Response(
        JSON.stringify({ logs: debugLogs, count: debugLogs.length }),
        { headers: { 'Content-Type': 'application/json' } }
      );
    }

    // GET /debug/status — システム状態サマリー + 最新5件ログ
    if (url.pathname === '/debug/status' && request.method === 'GET') {
      try {
        const systemStatus = await env.PHONE_STORE.get('system_status') || 'stopped';
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
        const results = JSON.parse(resultsRaw);

        return new Response(
          JSON.stringify({
            system_status: systemStatus,
            current_index: currentIndex,
            queue_length: queue.length,
            results_length: results.length,
            recent_logs: debugLogs.slice(-5)
          }),
          { headers: { 'Content-Type': 'application/json' } }
        );
      } catch (err: any) {
        console.error('[ERROR] debug/status 例外:', err.message);
        return new Response(
          JSON.stringify({ error: err.message }),
          { status: 500, headers: { 'Content-Type': 'application/json' } }
        );
      }
    }

    // POST /debug/clear-logs — ログを全消去
    if (url.pathname === '/debug/clear-logs' && request.method === 'POST') {
      debugLogs.length = 0;
      addLog('[debug] ログを消去');
      return new Response(
        JSON.stringify({ message: 'Logs cleared', count: 0 }),
        { headers: { 'Content-Type': 'application/json' } }
      );
    }

    return new Response('Not Found', { status: 404 });
  }
};

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

async function triggerZoomCall(token: string, userId: string, phoneNumber: string) {
  try {
    const url = `https://api.zoom.us/v2/phone/users/${userId}/commands/dial`;
    addLog(`[triggerZoomCall] APIリクエスト: ${maskPhoneNumber(phoneNumber)}`);
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ call_number: phoneNumber })
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

async function cryptoHmacSha256(plainToken: string, secret: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(plainToken));
  return Array.from(new Uint8Array(signature)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function getAdminDashboardHTML(total: number, current: number, status: string, results: any[]): string {
  const statusLabels: Record<string, string> = { running: '🟢 稼働中 (自動発信中)', paused: '🟡 一時停止中', stopped: '⚪ 停止・未開始' };
  const statusBtnTexts: Record<string, string> = { running: '一時停止する', paused: '自動架電を再開する', stopped: 'リスト未読み込み' };
  const btnColor = status === 'running' ? 'bg-amber-500 hover:bg-amber-600' : 'bg-emerald-500 hover:bg-emerald-600';
  
  return `
  <!DOCTYPE html>
  <html lang="ja">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zoom Phone 自動架電ダッシュボード</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  </head>
  <body class="bg-slate-50 text-slate-800 font-sans min-h-screen">
    <div class="max-w-4xl mx-auto px-4 py-8">
      <header class="mb-8 border-b border-slate-200 pb-4 flex justify-between items-center">
        <h1 class="text-2xl font-bold text-slate-900">📞 Zoom Phone 架電オートメーション</h1>
        <span class="text-sm bg-slate-200 px-3 py-1 rounded-full text-slate-700">Powered by Cloudflare</span>
      </header>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div class="bg-white p-6 rounded-xl border border-slate-200">
          <p class="text-sm text-slate-500 font-medium mb-1">システム状態</p>
          <p class="text-lg font-bold">${statusLabels[status] || status}</p>
          ${status !== 'stopped' ? `
            <form action="/toggle-status" method="POST" class="mt-4">
              <button class="w-full ${btnColor} text-white font-semibold py-2 px-4 rounded-lg cursor-pointer text-sm">
                ${statusBtnTexts[status]}
              </button>
            </form>
          ` : ''}
        </div>

        <div class="bg-white p-6 rounded-xl border border-slate-200">
          <p class="text-sm text-slate-500 font-medium mb-1">現在の進捗</p>
          <p class="text-3xl font-black text-slate-900">${total > 0 ? `${current} <span class="text-sm font-normal text-slate-400">/ ${total} 件</span>` : '0 件'}</p>
          <div class="w-full bg-slate-100 rounded-full h-2.5 mt-4">
            <div class="bg-indigo-600 h-2.5 rounded-full" style="width: ${total > 0 ? (current / total) * 100 : 0}%"></div>
          </div>
        </div>

        <div class="bg-white p-6 rounded-xl border border-slate-200 flex flex-col justify-between">
          <div>
            <p class="text-sm text-slate-500 font-medium mb-1">データ出力</p>
            <p class="text-xs text-slate-400">現在までの結果をリアルタイムに出力します</p>
          </div>
          <a href="/results" class="w-full text-center bg-slate-900 text-white font-semibold py-2 px-4 rounded-lg inline-block text-sm mt-4">
            📥 結果CSVをダウンロード
          </a>
        </div>
      </div>

      <div class="bg-white p-6 rounded-xl border border-slate-200 mb-8">
        <h2 class="text-base font-bold mb-3 text-slate-900">📂 新規架電リストのアップロード</h2>
        <form action="/upload" method="POST" enctype="multipart/form-data" class="flex flex-col sm:flex-row gap-3">
          <input type="file" name="csv" accept=".csv" required class="flex-1 block w-full text-sm border border-slate-200 rounded-lg p-1">
          <button type="submit" class="bg-indigo-600 text-white font-semibold py-2 px-6 rounded-lg text-sm">
            読み込み ＆ 架電スタート
          </button>
        </form>
      </div>

      <div class="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div class="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
          <h2 class="text-base font-bold text-slate-900">📋 架電結果履歴</h2>
          <button onclick="location.reload()" class="text-xs text-indigo-600 font-medium">🔄 画面を更新する</button>
        </div>
        <div class="overflow-x-auto max-h-96">
          <table class="w-full text-left border-collapse text-sm">
            <thead>
              <tr class="bg-slate-50 text-slate-500 font-semibold border-b border-slate-100">
                <th class="px-6 py-3">電話番号</th>
                <th class="px-6 py-3">結果</th>
                <th class="px-6 py-3">完了日時</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              ${results.length === 0 ? `
                <tr>
                  <td colspan="3" class="px-6 py-8 text-center text-slate-400">まだ通話データがありません。</td>
                </tr>
              ` : results.map((r: any) => `
                <tr class="hover:bg-slate-50/50">
                  <td class="px-6 py-4 font-mono font-medium text-slate-900">${r.phone_number}</td>
                  <td class="px-6 py-4">
                    <span class="px-2.5 py-1 rounded-full text-xs font-bold ${r.result === 'コネクト' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}">
                      ${r.result}
                    </span>
                  </td>
                  <td class="px-6 py-4 text-slate-500">${r.time}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  </body>
  </html>
  `;
}
