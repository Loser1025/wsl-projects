// ==========================================
// デバッグログ機構
// ==========================================

// ==========================================
// デバッグログ機構
// ==========================================

const debugLogs: string[] = [];

// ==========================================
// アップロードデバッグ結果の型定義
// ==========================================

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
// 環境変数チェック用ヘルパー
// ==========================================

interface EnvCheckResult {
  [key: string]: string;
}

function checkEnvVariables(env: Env): { env_check: EnvCheckResult; token_preview: { accountId: string; clientId: string } } {
  const env_check: EnvCheckResult = {};

  // Zoom 環境変数のチェック
  const zoomVars: (keyof Env)[] = ['ZOOM_ACCOUNT_ID', 'ZOOM_CLIENT_ID', 'ZOOM_CLIENT_SECRET', 'ZOOM_USER_ID', 'ZOOM_WEBHOOK_SECRET'];
  for (const key of zoomVars) {
    const val = env[key];
    if (val === undefined || val === null) {
      env_check[key] = '❌ 未設定';
    } else if (val === '') {
      env_check[key] = '⚠️ 空文字';
    } else {
      const preview = String(val).slice(0, 4);
      env_check[key] = `✅ 設定済み (先頭4文字: ${preview}...)`;
    }
  }

  // PHONE_STORE バインディングの存在確認
  if (env.PHONE_STORE && typeof env.PHONE_STORE === 'object') {
    env_check['PHONE_STORE'] = '✅ 設定済み';
  } else {
    env_check['PHONE_STORE'] = '❌ 未設定';
  }

  // トークンリクエスト用プレビュー
  const accountId = env.ZOOM_ACCOUNT_ID || '';
  const clientId = env.ZOOM_CLIENT_ID || '';
  const token_preview = {
    accountId: accountId ? accountId.slice(0, 4) + '...' : '(未設定)',
    clientId: clientId ? clientId.slice(0, 4) + '...' : '(未設定)'
  };

  return { env_check, token_preview };
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

      // 最終アップロード結果を取得
      const lastUploadResultRaw = await env.PHONE_STORE.get('last_upload_result');
      let lastUploadResult: UploadDebugResult | null = null;
      if (lastUploadResultRaw) {
        try {
          lastUploadResult = JSON.parse(lastUploadResultRaw);
        } catch {
          // パースエラーは無視
        }
      }

      addLog(`[dashboard] 表示: status=${systemStatus}, index=${currentIndex}, results=${results.length}件`);

      const html = getAdminDashboardHTML(queue.length, currentIndex, systemStatus, results, lastUploadResult);
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
        const csvPreview = csvText.slice(0, 200);
        const phonePattern = /(?:0\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{4})/g;
        const matches = csvText.match(phonePattern) || [];
        addLog(`[upload] 正規表現マッチ件数: ${matches.length}`);

        // ==========================================
        // バリデーション詳細の記録
        // ==========================================
        const validationDetails: PhoneValidationDetail[] = [];
        const invalidReasons: Record<string, number> = {};
        const cleanNumbers: string[] = [];
        const seenNumbers = new Set<string>();

        for (const match of matches) {
          const cleanNum = match.replace(/\D/g, '');
          const digitCount = cleanNum.length;

          // バリデーション理由の判定
          let valid = true;
          let reason: string | undefined;

          if (digitCount < 10) {
            valid = false;
            reason = '桁数不足';
          } else if (digitCount > 11) {
            valid = false;
            reason = '桁数超過';
          } else if (!cleanNum.startsWith('0')) {
            valid = false;
            reason = '0で始まらない';
          }

          if (valid) {
            const zoomFormat = '+81' + cleanNum.slice(1);
            if (seenNumbers.has(zoomFormat)) {
              valid = false;
              reason = '重複';
            } else {
              seenNumbers.add(zoomFormat);
            }
          }

          validationDetails.push({
            raw: match,
            cleaned: cleanNum,
            digitCount,
            valid,
            reason
          });

          if (valid) {
            cleanNumbers.push(match.replace(/\D/g, ''));
          } else {
            invalidReasons[reason!] = (invalidReasons[reason!] || 0) + 1;
          }
        }

        // 重複排除後の cleanNumbers を再構築（+81形式）
        const finalCleanNumbers = cleanNumbers.map(n => {
          // 既に +81 形式になっているはず
          return n.startsWith('+81') ? n : '+81' + n.slice(1);
        });

        addLog(`[upload] バリデーション通過: ${finalCleanNumbers.length}件, 除外: ${Object.values(invalidReasons).reduce((a, b) => a + b, 0)}件`);

        // ==========================================
        // デバッグ結果の構築
        // ==========================================
        const debugResult: UploadDebugResult = {
          timestamp: new Date().toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }),
          filename: file.name,
          fileSize: file.size,
          csvPreview,
          totalMatched: matches.length,
          validCount: finalCleanNumbers.length,
          invalidCount: Object.values(invalidReasons).reduce((a, b) => a + b, 0),
          invalidReasons,
          firstFewValid: finalCleanNumbers.slice(0, 3).map(n => maskPhoneNumber(n)),
          sampleRawMatches: matches.slice(0, 5),
          validationDetails,
          success: finalCleanNumbers.length > 0
        };

        if (finalCleanNumbers.length === 0) {
          debugResult.success = false;
          debugResult.errorMessage = matches.length === 0
            ? '正規表現にマッチする電話番号がCSV内に見つかりませんでした'
            : `正規表現マッチ ${matches.length} 件のうち、バリデーション通過が0件でした`;

          // 失敗結果をKVに保存
          await env.PHONE_STORE.put('last_upload_result', JSON.stringify(debugResult));
          addLog(`[upload] ERROR: ${debugResult.errorMessage}`);

          return new Response(
            `<script>
              alert("有効な電話番号が見つかりませんでした。\\n\\nマッチ数: ${matches.length}件\\n通過: 0件\\n\\nCSV先頭200文字:\\n${csvPreview.replace(/'/g, "\\'").replace(/\n/g, '\\n')}");
              location.href="/";
            </script>`,
            { headers: { 'Content-Type': 'text/html' } }
          );
        }

        // 成功時: 正しい+81形式で保存
        const zoomFormatNumbers = finalCleanNumbers.map(n => {
          const digits = n.replace(/\D/g, ''); // 数字のみ
          return '+81' + digits.slice(1); // 先頭の0を+81に
        });

        await env.PHONE_STORE.put('queue', JSON.stringify(zoomFormatNumbers));
        await env.PHONE_STORE.put('results', JSON.stringify([]));
        await env.PHONE_STORE.put('current_index', '0');
        await env.PHONE_STORE.put('system_status', 'running');
        // 成功結果をKVに保存
        await env.PHONE_STORE.put('last_upload_result', JSON.stringify(debugResult));
        addLog(`[upload] KV保存完了: queue=${zoomFormatNumbers.length}件, current_index=0, status=running`);

        const token = await getZoomToken(env);
        addLog(`[upload] 初回架電を開始: ${maskPhoneNumber(zoomFormatNumbers[0])}`);
        await triggerZoomCall(token, env.ZOOM_USER_ID, zoomFormatNumbers[0]);

        addLog('[upload] 処理完了 → リダイレクト');
        return Response.redirect(url.origin, 303);
      } catch (err: any) {
        console.error('[ERROR] upload 処理で例外:', err.message, err.stack);
        addLog(`[upload] ERROR: ${err.message}`);

        // エラー結果をKVに保存
        const errorDebugResult: UploadDebugResult = {
          timestamp: new Date().toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }),
          filename: 'unknown',
          fileSize: 0,
          csvPreview: '',
          totalMatched: 0,
          validCount: 0,
          invalidCount: 0,
          invalidReasons: {},
          firstFewValid: [],
          sampleRawMatches: [],
          validationDetails: [],
          success: false,
          errorMessage: err.message
        };
        await env.PHONE_STORE.put('last_upload_result', JSON.stringify(errorDebugResult));

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

        const { env_check, token_preview } = checkEnvVariables(env);

        return new Response(
          JSON.stringify({
            system_status: systemStatus,
            current_index: currentIndex,
            queue_length: queue.length,
            results_length: results.length,
            recent_logs: debugLogs.slice(-5),
            env_check,
            token_preview
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

    // ==========================================
    // 9. デバッグダッシュボード (GET /debug)
    // ==========================================
    if (url.pathname === '/debug' && request.method === 'GET') {
      const systemStatus = await env.PHONE_STORE.get('system_status') || 'stopped';
      const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
      const currentIndex = parseInt(currentIndexRaw, 10);
      const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
      const queue = JSON.parse(queueRaw);
      const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
      const results = JSON.parse(resultsRaw);

      const lastUploadResultRaw = await env.PHONE_STORE.get('last_upload_result');
      let lastUploadResult: UploadDebugResult | null = null;
      if (lastUploadResultRaw) {
        try {
          lastUploadResult = JSON.parse(lastUploadResultRaw);
        } catch { /* パースエラーは無視 */ }
      }

      // Zoom API接続テスト
      let zoomApiStatus = '🟢 接続成功';
      let zoomApiDetail = '';
      try {
        const token = await getZoomToken(env);
        zoomApiDetail = `トークン取得成功 (${token.length}文字)`;
      } catch (err: any) {
        zoomApiStatus = '🔴 接続失敗';
        zoomApiDetail = err.message || '不明なエラー';
      }

      const { env_check, token_preview } = checkEnvVariables(env);

      const recentLogs = debugLogs.slice(-50).reverse();
      const errorLogs = debugLogs.filter(l => l.includes('[ERROR]')).slice(-20);
      const progressPercent = queue.length > 0 ? Math.round((currentIndex / queue.length) * 100) : 0;
      const lastUploadSummary = lastUploadResult
        ? `${lastUploadResult.filename} (${lastUploadResult.validCount}件通過 / ${lastUploadResult.invalidCount}件除外)`
        : 'なし';

      // 環境変数チェックHTML生成
      const envCheckRows = Object.entries(env_check).map(([key, value]) => {
        let colorClass = 'text-rose-400';
        if (value.startsWith('✅')) colorClass = 'text-emerald-400';
        else if (value.startsWith('⚠️')) colorClass = 'text-amber-400';
        return `<tr class="border-b border-slate-700"><td class="py-2 px-3 text-slate-300 font-mono text-xs">${key}</td><td class="py-2 px-3 ${colorClass} text-xs font-medium">${value}</td></tr>`;
      }).join('');

      const html = `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>デバッグダッシュボード - Zoom Phone 自動架電</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>
<body class="bg-slate-900 text-slate-100 font-sans min-h-screen">
  <div class="max-w-6xl mx-auto px-4 py-8">
    <header class="mb-8 border-b border-slate-700 pb-4 flex justify-between items-center">
      <div class="flex items-center gap-4">
        <h1 class="text-2xl font-bold text-white">🔧 デバッグダッシュボード</h1>
        <a href="/" class="text-sm bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded-full text-slate-300">← 管理画面に戻る</a>
      </div>
      <span class="text-sm bg-amber-600/20 text-amber-400 px-3 py-1 rounded-full border border-amber-600/30">DEBUG</span>
    </header>

    <!-- システムステータス -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
      <div class="bg-slate-800 p-5 rounded-xl border border-slate-700">
        <p class="text-xs text-slate-400 font-medium mb-1">システム状態</p>
        <p class="text-lg font-bold ${systemStatus === 'running' ? 'text-emerald-400' : systemStatus === 'paused' ? 'text-amber-400' : 'text-slate-500'}">${systemStatus === 'running' ? '🟢 稼働中' : systemStatus === 'paused' ? '🟡 一時停止' : '⚪ 停止'}</p>
      </div>
      <div class="bg-slate-800 p-5 rounded-xl border border-slate-700">
        <p class="text-xs text-slate-400 font-medium mb-1">キュー / インデックス</p>
        <p class="text-2xl font-black text-white">${currentIndex} <span class="text-sm font-normal text-slate-500">/ ${queue.length}</span></p>
      </div>
      <div class="bg-slate-800 p-5 rounded-xl border border-slate-700">
        <p class="text-xs text-slate-400 font-medium mb-1">進捗率</p>
        <p class="text-2xl font-black text-indigo-400">${progressPercent}%</p>
        <div class="w-full bg-slate-700 rounded-full h-1.5 mt-2">
          <div class="bg-indigo-500 h-1.5 rounded-full" style="width: ${progressPercent}%"></div>
        </div>
      </div>
      <div class="bg-slate-800 p-5 rounded-xl border border-slate-700">
        <p class="text-xs text-slate-400 font-medium mb-1">Zoom API接続</p>
        <p class="text-sm font-bold">${zoomApiStatus}</p>
        <p class="text-xs text-slate-500 mt-1">${zoomApiDetail}</p>
      </div>
    </div>

    <!-- 環境変数チェック -->
    <div class="bg-slate-800 p-6 rounded-xl border border-slate-700 mb-8">
      <h2 class="text-base font-bold mb-3 text-white">🔑 環境変数チェック</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b border-slate-600">
              <th class="py-2 px-3 text-slate-400 font-medium text-xs">変数名</th>
              <th class="py-2 px-3 text-slate-400 font-medium text-xs">状態</th>
            </tr>
          </thead>
          <tbody>
            ${envCheckRows}
          </tbody>
        </table>
      </div>
      <div class="mt-4 pt-4 border-t border-slate-700">
        <p class="text-xs text-slate-400 font-medium mb-2">トークンリクエスト用プレビュー</p>
        <div class="grid grid-cols-2 gap-4 text-xs">
          <div>
            <span class="text-slate-500">accountId:</span>
            <span class="text-slate-300 font-mono ml-2">${token_preview.accountId}</span>
          </div>
          <div>
            <span class="text-slate-500">clientId:</span>
            <span class="text-slate-300 font-mono ml-2">${token_preview.clientId}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <!-- 最終アップロード結果 -->
      <div class="bg-slate-800 p-6 rounded-xl border border-slate-700">
        <h2 class="text-base font-bold mb-3 text-white">📂 最終アップロード結果</h2>
        ${lastUploadResult ? `
          <div class="space-y-2 text-sm">
            <div class="flex justify-between"><span class="text-slate-400">ファイル名</span><span class="text-slate-200">${lastUploadResult.filename}</span></div>
            <div class="flex justify-between"><span class="text-slate-400">実行日時</span><span class="text-slate-200">${lastUploadResult.timestamp}</span></div>
            <div class="flex justify-between"><span class="text-slate-400">マッチ総数</span><span class="text-slate-200">${lastUploadResult.totalMatched} 件</span></div>
            <div class="flex justify-between"><span class="text-slate-400">有効 / 除外</span><span class="text-emerald-400">${lastUploadResult.validCount} 件</span> / <span class="text-rose-400">${lastUploadResult.invalidCount} 件</span></div>
            ${lastUploadResult.errorMessage ? `<p class="text-rose-400 mt-2 text-xs">⚠ ${lastUploadResult.errorMessage}</p>` : ''}
            ${Object.keys(lastUploadResult.invalidReasons).length > 0 ? `
              <div class="flex flex-wrap gap-1 mt-2">
                ${Object.entries(lastUploadResult.invalidReasons).map(([r, c]) => `<span class="bg-rose-900/30 text-rose-300 px-2 py-0.5 rounded text-xs">${r}: ${c}件</span>`).join('')}
              </div>
            ` : ''}
          </div>
        ` : '<p class="text-slate-500 text-sm">まだアップロード記録がありません</p>'}
      </div>

      <!-- 最近のエラー一覧 -->
      <div class="bg-slate-800 p-6 rounded-xl border border-slate-700">
        <h2 class="text-base font-bold mb-3 text-white">⚠️ 最近のエラー (${errorLogs.length}件)</h2>
        ${errorLogs.length > 0 ? `
          <div class="space-y-1 max-h-72 overflow-y-auto">
            ${errorLogs.map(l => `<div class="text-xs font-mono text-rose-400 bg-slate-900/50 px-3 py-1.5 rounded border-l-2 border-rose-500">${l}</div>`).join('')}
          </div>
        ` : '<p class="text-slate-500 text-sm">エラーは記録されていません</p>'}
      </div>
    </div>

    <!-- デバッグログ -->
    <div class="bg-slate-800 p-6 rounded-xl border border-slate-700 mt-6">
      <div class="flex justify-between items-center mb-3">
        <h2 class="text-base font-bold text-white">📋 デバッグログ (最新${recentLogs.length}件)</h2>
        <form action="/debug/clear-logs" method="POST" class="inline">
          <button type="submit" class="text-xs bg-slate-700 hover:bg-rose-600 text-slate-300 hover:text-white px-3 py-1 rounded cursor-pointer transition-colors">🗑️ ログを消去</button>
        </form>
        <button onclick="location.reload()" class="text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 px-3 py-1 rounded cursor-pointer">🔄 リロード</button>
      </div>
      <pre class="bg-slate-950 p-4 rounded-lg text-xs font-mono text-slate-300 max-h-96 overflow-y-auto whitespace-pre-wrap leading-relaxed border border-slate-700">${recentLogs.join('\n') || '(ログなし)'}</pre>
    </div>

    <footer class="mt-8 border-t border-slate-700 pt-4 flex justify-between items-center">
      <a href="/" class="text-sm text-slate-400 hover:text-white">← 管理画面に戻る</a>
      <span class="text-xs text-slate-600">Zoom Phone Auto-Dialer Debug Dashboard</span>
    </footer>
  </div>
</body>
</html>`;

      addLog('[debug] ダッシュボード表示');
      return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
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
    const url = `https://api.zoom.us/v2/phone/commands/dial`;
    addLog(`[triggerZoomCall] APIリクエスト: ${maskPhoneNumber(phoneNumber)}`);
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        call_number: phoneNumber
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

async function cryptoHmacSha256(plainToken: string, secret: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(plainToken));
  return Array.from(new Uint8Array(signature)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function getAdminDashboardHTML(total: number, current: number, status: string, results: any[], uploadResult: UploadDebugResult | null = null): string {
  const statusLabels: Record<string, string> = { running: '🟢 稼働中 (自動発信中)', paused: '🟡 一時停止中', stopped: '⚪ 停止・未開始' };
  const statusBtnTexts: Record<string, string> = { running: '一時停止する', paused: '自動架電を再開する', stopped: 'リスト未読み込み' };
  const btnColor = status === 'running' ? 'bg-amber-500 hover:bg-amber-600' : 'bg-emerald-500 hover:bg-emerald-600';

  // 最終アップロード結果セクションのHTML生成
  let uploadResultHTML = '';
  if (uploadResult) {
    const resultColor = uploadResult.success ? 'border-emerald-200 bg-emerald-50/30' : 'border-rose-200 bg-rose-50/30';
    const resultIcon = uploadResult.success ? '✅' : '❌';
    const resultTitle = uploadResult.success ? '最終アップロード結果（成功）' : '最終アップロード結果（失敗）';

    // 除外理由の内訳
    const invalidReasonsHTML = Object.keys(uploadResult.invalidReasons).length > 0
      ? Object.entries(uploadResult.invalidReasons).map(([reason, count]) =>
          `<span class="inline-block bg-rose-100 text-rose-700 px-2 py-0.5 rounded text-xs mr-1 mb-1">${reason}: ${count}件</span>`
        ).join('')
      : '<span class="text-slate-400 text-xs">なし</span>';

    // 有効番号サンプル
    const firstFewValidHTML = uploadResult.firstFewValid.length > 0
      ? uploadResult.firstFewValid.map(n => `<span class="inline-block bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded text-xs mr-1 mb-1 font-mono">${n}</span>`).join('')
      : '<span class="text-slate-400 text-xs">なし</span>';

    // マッチした生文字列サンプル
    const sampleRawMatchesHTML = uploadResult.sampleRawMatches.length > 0
      ? uploadResult.sampleRawMatches.map(n => `<span class="inline-block bg-slate-100 text-slate-700 px-2 py-0.5 rounded text-xs mr-1 mb-1 font-mono">${n}</span>`).join('')
      : '<span class="text-slate-400 text-xs">なし</span>';

    uploadResultHTML = `
      <div class="bg-white p-6 rounded-xl border ${resultColor} mb-8">
        <h2 class="text-base font-bold mb-3 text-slate-900">${resultIcon} ${resultTitle}</h2>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <p class="text-slate-500 font-medium mb-1">実行日時</p>
            <p class="text-slate-900">${uploadResult.timestamp}</p>
          </div>
          <div>
            <p class="text-slate-500 font-medium mb-1">ファイル名</p>
            <p class="text-slate-900">${uploadResult.filename} (${uploadResult.fileSize.toLocaleString()} bytes)</p>
          </div>
          <div>
            <p class="text-slate-500 font-medium mb-1">正規表現マッチ総数</p>
            <p class="text-slate-900 font-bold">${uploadResult.totalMatched} 件</p>
          </div>
          <div>
            <p class="text-slate-500 font-medium mb-1">バリデーション結果</p>
            <p class="text-slate-900">
              <span class="text-emerald-600 font-bold">${uploadResult.validCount} 件通過</span>
              ${uploadResult.invalidCount > 0 ? ` / <span class="text-rose-600 font-bold">${uploadResult.invalidCount} 件除外</span>` : ''}
            </p>
          </div>
          <div class="md:col-span-2">
            <p class="text-slate-500 font-medium mb-1">除外理由の内訳</p>
            <div class="flex flex-wrap">${invalidReasonsHTML}</div>
          </div>
          <div class="md:col-span-2">
            <p class="text-slate-500 font-medium mb-1">有効番号サンプル（先頭3件、マスク表示）</p>
            <div class="flex flex-wrap">${firstFewValidHTML}</div>
          </div>
          <div class="md:col-span-2">
            <p class="text-slate-500 font-medium mb-1">マッチした生文字列サンプル（先頭5件）</p>
            <div class="flex flex-wrap">${sampleRawMatchesHTML}</div>
          </div>
          <div class="md:col-span-2">
            <p class="text-slate-500 font-medium mb-1">CSV先頭200文字</p>
            <pre class="bg-slate-100 p-2 rounded text-xs text-slate-700 overflow-x-auto whitespace-pre-wrap">${uploadResult.csvPreview || '(空)'}</pre>
          </div>
          ${uploadResult.errorMessage ? `
          <div class="md:col-span-2">
            <p class="text-slate-500 font-medium mb-1">エラーメッセージ</p>
            <p class="text-rose-600">${uploadResult.errorMessage}</p>
          </div>
          ` : ''}
          ${!uploadResult.success && uploadResult.totalMatched === 0 ? `
          <div class="md:col-span-2">
            <p class="text-slate-500 font-medium mb-1">推奨フォーマット</p>
            <pre class="bg-slate-100 p-2 rounded text-xs text-slate-700">電話番号
090-1234-5678
080-9876-5432
07012345678</pre>
          </div>
          ` : ''}
        </div>
      </div>
    `;
  }
  
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
        <div class="flex items-center gap-3">
          <a href="/debug" class="text-sm bg-amber-100 text-amber-700 hover:bg-amber-200 px-3 py-1 rounded-full font-medium">🔧 デバッグ</a>
          <span class="text-sm bg-slate-200 px-3 py-1 rounded-full text-slate-700">Powered by Cloudflare</span>
        </div>
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

      ${uploadResultHTML}

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
