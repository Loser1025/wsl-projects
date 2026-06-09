/**
 * 商談動画アナライザー - フロントエンドJavaScript
 */

// =========================================================
// 状態管理
// =========================================================
const state = {
    selectedFile: null,
    driveUrl: "",
    isAnalyzing: false,
    results: null
};

// =========================================================
// DOM要素
// =========================================================
const elements = {
    // タブ
    tabBtns: document.querySelectorAll(".tab-btn"),
    tabContents: document.querySelectorAll(".tab-content"),
    
    // アップロード
    uploadArea: document.getElementById("uploadArea"),
    fileInput: document.getElementById("fileInput"),
    fileInfo: document.getElementById("fileInfo"),
    fileName: document.querySelector(".file-name"),
    fileSize: document.querySelector(".file-size"),
    removeFile: document.getElementById("removeFile"),
    
    // Google Drive
    driveUrl: document.getElementById("driveUrl"),
    
    // ボタン
    analyzeBtn: document.getElementById("analyzeBtn"),
    reanalyzeBtn: document.getElementById("reanalyzeBtn"),
    
    // セクション
    loadingSection: document.getElementById("loadingSection"),
    resultsSection: document.getElementById("resultsSection"),
    
    // 結果表示
    overallScore: document.getElementById("overallScore"),
    scoreProgress: document.getElementById("scoreProgress"),
    gradeBadge: document.getElementById("gradeBadge"),
    gradeLabel: document.getElementById("gradeLabel"),
    expressionScore: document.getElementById("expressionScore"),
    voiceScore: document.getElementById("voiceScore"),
    expressionBars: document.getElementById("expressionBars"),
    voiceBars: document.getElementById("voiceBars"),
    summaryText: document.getElementById("summaryText"),
    improvementsList: document.getElementById("improvementsList"),
    
    // API状態
    apiStatus: document.getElementById("apiStatus")
};

// =========================================================
// タブ切り替え
// =========================================================
function initTabs() {
    elements.tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const tabId = btn.dataset.tab;
            
            // タブボタンの切り替え
            elements.tabBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            // コンテンツの切り替え
            elements.tabContents.forEach(content => {
                content.classList.remove("active");
                if (content.id === `${tabId}-tab`) {
                    content.classList.add("active");
                }
            });
            
            updateAnalyzeButton();
        });
    });
}

// =========================================================
// ファイルアップロード
// =========================================================
function initUpload() {
    // クリックでファイル選択
    elements.uploadArea.addEventListener("click", () => {
        elements.fileInput.click();
    });
    
    // ファイル選択時
    elements.fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });
    
    // ドラッグ＆ドロップ
    elements.uploadArea.addEventListener("dragover", (e) => {
        e.preventDefault();
        elements.uploadArea.classList.add("drag-over");
    });
    
    elements.uploadArea.addEventListener("dragleave", () => {
        elements.uploadArea.classList.remove("drag-over");
    });
    
    elements.uploadArea.addEventListener("drop", (e) => {
        e.preventDefault();
        elements.uploadArea.classList.remove("drag-over");
        
        if (e.dataTransfer.files.length > 0) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });
    
    // ファイル削除
    elements.removeFile.addEventListener("click", (e) => {
        e.stopPropagation();
        clearFile();
    });
}

function handleFileSelect(file) {
    // 動画ファイルかチェック
    if (!file.type.startsWith("video/")) {
        alert("動画ファイルを選択してください");
        return;
    }
    
    // サイズチェック (500MB)
    if (file.size > 500 * 1024 * 1024) {
        alert("ファイルサイズが大きすぎます（最大500MB）");
        return;
    }
    
    state.selectedFile = file;
    
    // UI更新
    elements.fileName.textContent = file.name;
    elements.fileSize.textContent = formatFileSize(file.size);
    elements.fileInfo.style.display = "flex";
    elements.uploadArea.style.display = "none";
    
    updateAnalyzeButton();
}

function clearFile() {
    state.selectedFile = null;
    elements.fileInput.value = "";
    elements.fileInfo.style.display = "none";
    elements.uploadArea.style.display = "block";
    
    updateAnalyzeButton();
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

// =========================================================
// Google Drive URL
// =========================================================
function initDriveInput() {
    elements.driveUrl.addEventListener("input", (e) => {
        state.driveUrl = e.target.value.trim();
        updateAnalyzeButton();
    });
}

// =========================================================
// 分析ボタン
// =========================================================
function updateAnalyzeButton() {
    const activeTab = document.querySelector(".tab-btn.active").dataset.tab;
    
    if (activeTab === "upload") {
        elements.analyzeBtn.disabled = !state.selectedFile || state.isAnalyzing;
    } else {
        elements.analyzeBtn.disabled = !state.driveUrl || state.isAnalyzing;
    }
}

function initAnalyzeButton() {
    elements.analyzeBtn.addEventListener("click", startAnalysis);
    elements.reanalyzeBtn.addEventListener("click", resetAnalysis);
}

async function startAnalysis() {
    const activeTab = document.querySelector(".tab-btn.active").dataset.tab;
    
    state.isAnalyzing = true;
    updateAnalyzeButton();
    
    // ローディング表示
    elements.loadingSection.style.display = "block";
    elements.resultsSection.style.display = "none";
    
    try {
        let response;
        
        if (activeTab === "upload") {
            response = await analyzeUpload();
        } else {
            response = await analyzeDrive();
        }
        
        // 結果表示
        displayResults(response);
        
    } catch (error) {
        alert("分析中にエラーが発生しました: " + error.message);
    } finally {
        state.isAnalyzing = false;
        updateAnalyzeButton();
        elements.loadingSection.style.display = "none";
    }
}

async function analyzeUpload() {
    const formData = new FormData();
    formData.append("video", state.selectedFile);
    
    const response = await fetch("/api/analyze/upload", {
        method: "POST",
        body: formData
    });
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "分析に失敗しました");
    }
    
    return response.json();
}

async function analyzeDrive() {
    const response = await fetch("/api/analyze/drive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ drive_url: state.driveUrl })
    });
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "分析に失敗しました");
    }
    
    return response.json();
}

function resetAnalysis() {
    elements.resultsSection.style.display = "none";
    clearFile();
    elements.driveUrl.value = "";
    state.driveUrl = "";
}

// =========================================================
// 結果表示
// =========================================================
function displayResults(data) {
    state.results = data;
    
    // 総合スコア
    animateScore(elements.overallScore, data.overall_score || 0);
    
    // スコアサークル
    const circumference = 2 * Math.PI * 45; // r=45
    const offset = circumference - (data.overall_score / 100) * circumference;
    elements.scoreProgress.style.strokeDashoffset = offset;
    
    // スコアに応じた色変更
    const color = getScoreColor(data.overall_score);
    elements.scoreProgress.style.stroke = color;
    
    // グレード
    if (data.grade) {
        elements.gradeBadge.textContent = data.grade.grade;
        elements.gradeBadge.style.background = data.grade.color;
        elements.gradeLabel.textContent = data.grade.label;
    }
    
    // 表情スコア
    if (data.expression) {
        const exprScore = data.expression.total_score || 0;
        elements.expressionScore.textContent = exprScore + "点";
        elements.expressionBars.innerHTML = renderScoreBars(data.expression);
    }
    
    // 声トーンスコア
    if (data.voice_tone) {
        const voiceScore = data.voice_tone.total_score || 0;
        elements.voiceScore.textContent = voiceScore + "点";
        elements.voiceBars.innerHTML = renderScoreBars(data.voice_tone);
    }
    
    // 総合評価
    elements.summaryText.textContent = data.summary || "評価データがありません";
    
    // 改善点
    if (data.improvements && data.improvements.length > 0) {
        elements.improvementsList.innerHTML = data.improvements
            .map(item => `<li><i class="fas fa-exclamation-circle"></i><span>${item}</span></li>`)
            .join("");
    } else {
        elements.improvementsList.innerHTML = "<li>特に改善点はありません</li>";
    }
    
    // 結果セクション表示
    elements.resultsSection.style.display = "block";
    
    // 結果までスクロール
    elements.resultsSection.scrollIntoView({ behavior: "smooth" });
}

function renderScoreBars(scores) {
    const excludeKeys = ["total_score", "error", "message"];
    
    return Object.entries(scores)
        .filter(([key]) => !excludeKeys.includes(key) && typeof scores[key] === "object")
        .map(([key, value]) => {
            const score = value.score || 0;
            const comment = value.comment || "";
            const color = getScoreColor(score);
            
            return `
                <div class="score-bar-item">
                    <div class="bar-label">
                        <span class="bar-name">${formatCategoryName(key)}</span>
                        <span class="bar-score">${score}点</span>
                    </div>
                    <div class="bar-track">
                        <div class="bar-fill" style="width: ${score}%; background: ${color};"></div>
                    </div>
                    ${comment ? `<p class="bar-comment">${comment}</p>` : ""}
                </div>
            `;
        })
        .join("");
}

function formatCategoryName(key) {
    const names = {
        // 表情
        smile_intensity: "笑顔の強さ",
        eye_contact: "アイコンタクト",
        facial_responsiveness: "表情の反応性",
        positive_engagement: "ポジティブ表現",
        professional_appearance: "プロフェッショナル印象",
        consistency: "表情の一貫性",
        // 声トーン
        clarity: "明瞭さ",
        energy_level: "元気・生命力",
        pace_control: "話速コントロール",
        emotional_appropriateness: "感情表現の適切さ",
        confidence: "自信の印象"
    };
    return names[key] || key;
}

function getScoreColor(score) {
    if (score >= 80) return "#4CAF50";
    if (score >= 60) return "#8BC34A";
    if (score >= 40) return "#FFC107";
    if (score >= 20) return "#FF9800";
    return "#F44336";
}

function animateScore(element, target) {
    let current = 0;
    const duration = 1500;
    const steps = 60;
    const increment = target / steps;
    const interval = duration / steps;
    
    const timer = setInterval(() => {
        current += increment;
        if (current >= target) {
            current = target;
            clearInterval(timer);
        }
        element.textContent = Math.round(current);
    }, interval);
}

// =========================================================
// API状態確認
// =========================================================
async function checkApiStatus() {
    try {
        const response = await fetch("/api/status");
        const data = await response.json();
        
        const statusDot = elements.apiStatus.querySelector(".status-dot");
        const statusText = elements.apiStatus.querySelector(".status-text");
        
        if (data.status === "ok") {
            statusDot.classList.add("connected");
            statusText.textContent = `接続OK (キー: ${data.api_keys.available_keys}個)`;
        } else {
            statusDot.classList.add("error");
            statusText.textContent = "接続エラー";
        }
    } catch (error) {
        const statusDot = elements.apiStatus.querySelector(".status-dot");
        const statusText = elements.apiStatus.querySelector(".status-text");
        statusDot.classList.add("error");
        statusText.textContent = "サーバーに接続できません";
    }
}

// =========================================================
// 初期化
// =========================================================
document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initUpload();
    initDriveInput();
    initAnalyzeButton();
    checkApiStatus();
});
