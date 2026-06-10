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
