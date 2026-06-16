// ==========================================
// 型定義
// ==========================================

export interface Env {
  PHONE_STORE: KVNamespace;
  ZOOM_WEBHOOK_SECRET: string;
  ASSETS: { fetch: (request: Request) => Promise<Response> };
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

interface LastEventInfo {
  last_event: string | null;
  last_result: string | null;
  last_event_time: string | null;
  call_phase: string | null;
}

function emptyLastEventInfo(): LastEventInfo {
  return {
    last_event: null,
    last_result: null,
    last_event_time: null,
    call_phase: null
  };
}

async function getLastEventInfoFromKV(env: Env): Promise<LastEventInfo> {
  try {
    const raw = await env.PHONE_STORE.get('last_event_info');
    if (!raw) return emptyLastEventInfo();
    const parsed = JSON.parse(raw) as Partial<LastEventInfo>;
    return {
      last_event: parsed.last_event ?? null,
      last_result: parsed.last_result ?? null,
      last_event_time: parsed.last_event_time ?? null,
      call_phase: parsed.call_phase ?? null
    };
  } catch {
    return emptyLastEventInfo();
  }
}

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatDateTime(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('ja-JP');
}

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
async function saveLogToKV(env: Env, message: string): Promise<void> {
  const entry = `[${formatTime(new Date())}] ${message}`;
  const raw = await env.PHONE_STORE.get('debug_logs');
  const logs = raw ? JSON.parse(raw) : [];
  logs.push(entry);
  if (logs.length > 200) logs.shift();
  await env.PHONE_STORE.put('debug_logs', JSON.stringify(logs));
}

// ==========================================
// ステータス表示用関数
// ==========================================

function getStatusDisplay(status: string, current: number, total: number, nextPhone: string | null): string {
  if (status === 'calling') {
    return `通話中: ${nextPhone || '不明'} <button onclick="skipCall()">スキップ</button>`;
  } else if (status === 'stopped') {
    return current >= total ? '完了' : '停止中';
  } else {
    return `待機中: 次は ${nextPhone || 'なし'} <button onclick="skipCall()">スキップ</button> <button onclick="resetIndex()">リセット</button>`;
  }
}

function getLogsHtml(results: any[]): string {
  return results.map(result => {
    const time = new Date(result.timestamp).toLocaleTimeString();
    const phone = result.phone || '不明';
    const status = result.status || '不明';
    return `[${time}] ${phone}: ${status}`;
  }).join('\n');
}

// ==========================================
// ダッシュボードHTML
// ==========================================

function getDashboardHTML(
  queue: string[],
  current: number,
  results: any[],
  nextPhone: string | null,
  status: string,
  lastEventInfo: LastEventInfo
): string {
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
    <div id="screen-root">
      <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-8 text-center">
        <p class="text-slate-400 mb-6">CSVファイルをアップロードしてください</p>
        <form method="POST" action="/upload" enctype="multipart/form-data" class="space-y-4">
          <input type="file" name="csv" accept=".csv,.txt" required class="block w-full text-sm text-slate-500 file:mr-4 file:py-3 file:px-6 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer">
          <button type="submit" class="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-lg">アップロード</button>
        </form>
      </div>
    </div>
  </div>

  <script>
    // 初期データを取得して反映
    fetch('/api/dashboard-data')
      .then(res => res.json())
      .then(data => {
        document.getElementById('queue').value = data.queue.join('\n');
        document.getElementById('status').textContent = data.statusDisplay;
        document.getElementById('logs').value = data.logsHtml;
      });
  </script>
</body>
</html>`;
}

// ==========================================
// メインハンドラ
// ==========================================

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // ==========================================
    // 1. ダッシュボードデータを提供するエンドポイント GET /api/dashboard-data
    // ==========================================
    if (url.pathname === '/api/dashboard-data' && request.method === 'GET') {
      try {
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
        const results = JSON.parse(resultsRaw);
        const nextPhone = await env.PHONE_STORE.get('next_phone');
        const status = await env.PHONE_STORE.get('system_status') || 'stopped';
        const lastEventInfo = await getLastEventInfoFromKV(env);

        const initialData = {
          queue,
          currentIndex,
          results,
          nextPhone,
          statusDisplay: getStatusDisplay(status, currentIndex, queue.length, nextPhone),
          logsHtml: getLogsHtml(results),
        };
        return new Response(JSON.stringify(initialData), {
          headers: { 'Content-Type': 'application/json' },
        });
      } catch (err: any) {
        return new Response('エラー: ' + err.message, { status: 500 });
      }
    }

    // ==========================================
    // 2. 管理画面 GET /
    // ==========================================
    if (url.pathname === '/' && request.method === 'GET') {
      try {
        const queueRaw = await env.PHONE_STORE.get('queue') || '[]';
        const queue = JSON.parse(queueRaw);
        const currentIndexRaw = await env.PHONE_STORE.get('current_index') || '0';
        const currentIndex = parseInt(currentIndexRaw, 10);
        const resultsRaw = await env.PHONE_STORE.get('results') || '[]';
        const results = JSON.parse(resultsRaw);
        const nextPhone = await env.PHONE_STORE.get('next_phone');
        const status = await env.PHONE_STORE.get('system_status') || 'stopped';
        const lastEventInfo = await getLastEventInfoFromKV(env);

        addLog(`[dashboard] index=${currentIndex}/${queue.length}, next=${nextPhone || 'なし'}, results=${results.length}`);
        await saveLogToKV(env, `[dashboard] index=${currentIndex}/${queue.length}, next=${nextPhone || 'なし'}, results=${results.length}`);

        const html = getDashboardHTML(queue, currentIndex, results, nextPhone, status, lastEventInfo);
        return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      } catch (err: any) {
        return new Response('エラー: ' + err.message, { status: 500 });
      }
    }

    // その他のエンドポイントは既存の処理を維持
    // ... 既存の処理 ...
  }
};