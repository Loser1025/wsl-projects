/**
 * compress_and_send.js
 * FFmpeg.wasm を使って動画をブラウザ上で圧縮するモジュール。
 * 依存: window.FFmpegWASM (@ffmpeg/ffmpeg UMD), window.FFmpegUtil (@ffmpeg/util UMD)
 */

const COMPRESS_THRESHOLD = 4 * 1024 * 1024; // 4MB 超えたら圧縮

let _ffmpeg = null;
let _ffmpegLoadPromise = null;

/**
 * FFmpeg.wasm を初期化（初回のみ。以降はキャッシュ済みインスタンスを返す）
 */
async function loadFFmpeg(onStatus) {
    if (_ffmpeg) return _ffmpeg;
    if (_ffmpegLoadPromise) return _ffmpegLoadPromise;

    _ffmpegLoadPromise = (async () => {
        if (onStatus) onStatus(0, 'FFmpeg を読み込み中...');

        const { FFmpeg } = FFmpegWASM;
        const { toBlobURL } = FFmpegUtil;
        const ffmpeg = new FFmpeg();

        const base = 'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.6/dist/umd';
        await ffmpeg.load({
            coreURL: await toBlobURL(`${base}/ffmpeg-core.js`,   'text/javascript'),
            wasmURL: await toBlobURL(`${base}/ffmpeg-core.wasm`, 'application/wasm'),
        });

        _ffmpeg = ffmpeg;
        return ffmpeg;
    })();

    return _ffmpegLoadPromise;
}

/**
 * 動画ファイルをブラウザ上で圧縮する（360p, CRF 28, モノラル音声）
 * @param {File}     file       - 入力動画ファイル
 * @param {Function} onProgress - (percent: number, message: string) => void
 * @returns {Promise<Blob>} 圧縮後の動画 Blob
 */
async function compressVideo(file, onProgress) {
    const notify = (pct, msg) => onProgress && onProgress(pct, msg);

    notify(0, 'FFmpeg を読み込み中...');
    const ffmpeg = await loadFFmpeg(notify);

    // 進捗コールバックを登録（前の登録を上書きして多重登録を防ぐ）
    ffmpeg.off('progress');
    ffmpeg.on('progress', ({ progress }) => {
        const pct = Math.round(10 + Math.min(progress, 1) * 80);
        notify(pct, `圧縮中... ${pct}%`);
    });

    const { fetchFile } = FFmpegUtil;
    const ts = Date.now();
    const inputName  = `in_${ts}.mp4`;
    const outputName = `out_${ts}.mp4`;

    notify(5, '動画データを読み込み中...');
    await ffmpeg.writeFile(inputName, await fetchFile(file));

    notify(10, '動画を圧縮中（しばらくお待ちください）...');
    await ffmpeg.exec([
        '-i', inputName,
        '-vf', 'scale=-2:360',    // 360p にリスケール
        '-c:v', 'libx264',
        '-crf', '28',             // 品質係数（大きいほど小さい）
        '-preset', 'veryfast',
        '-c:a', 'aac',
        '-b:a', '64k',
        '-ac', '1',               // モノラルで音声サイズ削減
        '-movflags', '+faststart', // ストリーミング最適化
        outputName,
    ]);

    notify(92, '圧縮完了、ファイルを準備中...');
    const data = await ffmpeg.readFile(outputName);

    // 一時ファイル削除
    try { await ffmpeg.deleteFile(inputName);  } catch (_) {}
    try { await ffmpeg.deleteFile(outputName); } catch (_) {}

    notify(100, '圧縮完了');
    return new Blob([data.buffer], { type: 'video/mp4' });
}

/**
 * アップロード用の動画を返す。
 * 4MB 以下ならそのまま返し、超えていれば FFmpeg.wasm で圧縮してから返す。
 * @param {File}     file
 * @param {Function} onProgress - (percent: number, message: string) => void
 * @returns {Promise<File|Blob>}
 */
async function getVideoForUpload(file, onProgress) {
    if (file.size <= COMPRESS_THRESHOLD) {
        onProgress && onProgress(100, 'そのままアップロードします');
        return file;
    }
    const compressed = await compressVideo(file, onProgress);
    const baseName = file.name.replace(/\.[^.]+$/, '');
    return new File([compressed], `${baseName}_compressed.mp4`, { type: 'video/mp4' });
}

const MAX_CHUNK_SIZE = 8 * 1024 * 1024; // 8MB チャンクサイズ
const MAX_RETRIES = 3;

/**
 * 指数バックオフ付きリトライヘルパー
 * @param {Function} fn - 実行する非同期関数
 * @param {number} maxRetries - 最大リトライ回数
 * @returns {Promise<any>}
 */
async function retryWithBackoff(fn, maxRetries = MAX_RETRIES) {
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            return await fn();
        } catch (error) {
            if (attempt === maxRetries) throw error;
            const delay = Math.pow(2, attempt) * 1000;
            await new Promise(resolve => setTimeout(resolve, delay));
        }
    }
}

/**
 * 動画を圧縮して Gemini Files API に直接アップロードし、分析をリクエストする
 * @param {File}     file       - 動画ファイル
 * @param {Function} [onProgress] - 進捗コールバック (percent: number, message: string) => void
 * @returns {Promise<object>} 分析結果
 */
async function compressAndSendToGemini(file, onProgress) {
    const notify = (pct, msg) => onProgress && onProgress(pct, msg);
    notify(0, '動画を準備中...');

    try {
        // ステップ1: 圧縮
        const videoBlob = await getVideoForUpload(file, onProgress);
        notify(30, '圧縮完了、アップロード準備中...');

        const mimeType = videoBlob.type || 'video/mp4';
        const size = videoBlob.size;
        const displayName = file.name || 'video.mp4';

        // ステップ2: アップロードセッション初期化
        notify(32, 'アップロードセッションを初期化中...');
        const initResponse = await retryWithBackoff(async () => {
            const res = await fetch('/api/upload/init', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mimeType, size, displayName }),
            });
            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.error || `セッション初期化に失敗しました (${res.status})`);
            }
            return res.json();
        });

        const { uploadUrl, expiresAt } = initResponse;
        if (!uploadUrl) {
            throw new Error('アップロード URL が取得できませんでした');
        }

        // ステップ3: Resumable Upload で Gemini に直接アップロード
        notify(35, 'Gemini にアップロード中...');
        const totalSize = size;
        let offset = 0;

        while (offset < totalSize) {
            const end = Math.min(offset + MAX_CHUNK_SIZE, totalSize);
            const chunk = videoBlob.slice(offset, end);
            const isFinal = end === totalSize;
            const contentLength = end - offset;

            const uploadHeaders = {
                'Content-Length': String(contentLength),
                'X-Goog-Upload-Offset': String(offset),
                'X-Goog-Upload-Command': isFinal ? 'upload, finalize' : 'upload',
            };

            await retryWithBackoff(async () => {
                const res = await fetch(uploadUrl, {
                    method: 'POST',
                    headers: uploadHeaders,
                    body: chunk,
                });
                if (!res.ok && res.status !== 308) {
                    throw new Error(`アップロードチャンクに失敗しました (${res.status})`);
                }
                return res;
            });

            offset = end;

            // 進捗報告: 35%〜90% の範囲
            if (!isFinal) {
                const uploadProgress = 35 + Math.round((offset / totalSize) * 55);
                notify(Math.min(uploadProgress, 89), `アップロード中... ${Math.min(uploadProgress, 89)}%`);
            }
        }

        notify(90, 'アップロード完了、確認中...');

        // ステップ4: アップロード完了確認
        const completeResponse = await retryWithBackoff(async () => {
            const res = await fetch('/api/upload/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fileName: displayName }),
            });
            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.error || `アップロード完了確認に失敗しました (${res.status})`);
            }
            return res.json();
        });

        const { fileUri, fileName, state, mimeType: resultMimeType } = completeResponse;
        if (!fileUri) {
            throw new Error('ファイル URI が取得できませんでした');
        }

        notify(95, '分析をリクエスト中...');

        // ステップ5: 分析リクエスト
        const criteria = getCriteriaItems();
        const analyzeResponse = await retryWithBackoff(async () => {
            const res = await fetch('/api/analyze/direct', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fileUri, mimeType: resultMimeType || mimeType, criteria }),
            });
            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.error || `分析リクエストに失敗しました (${res.status})`);
            }
            return res.json();
        });

        notify(100, '分析完了');
        return analyzeResponse;
    } catch (error) {
        notify(100, 'エラーが発生しました');
        return { error: error.message };
    }
}

// グローバルにエクスポート
if (typeof window !== 'undefined') {
    window.compressAndSendToGemini = compressAndSendToGemini;
}
