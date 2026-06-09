const state = {
    driveUrl: "",
    isAnalyzing: false,
    results: null
};

const elements = {
    driveUrl:        document.getElementById("driveUrl"),
    analyzeBtn:      document.getElementById("analyzeBtn"),
    reanalyzeBtn:    document.getElementById("reanalyzeBtn"),
    loadingSection:  document.getElementById("loadingSection"),
    resultsSection:  document.getElementById("resultsSection"),
    overallScore:    document.getElementById("overallScore"),
    scoreProgress:   document.getElementById("scoreProgress"),
    gradeBadge:      document.getElementById("gradeBadge"),
    gradeLabel:      document.getElementById("gradeLabel"),
    expressionScore: document.getElementById("expressionScore"),
    voiceScore:      document.getElementById("voiceScore"),
    expressionBars:  document.getElementById("expressionBars"),
    voiceBars:       document.getElementById("voiceBars"),
    summaryText:     document.getElementById("summaryText"),
    improvementsList:document.getElementById("improvementsList"),
    apiStatus:       document.getElementById("apiStatus")
};

// =========================================================
// 入力
// =========================================================
function initDriveInput() {
    elements.driveUrl.addEventListener("input", (e) => {
        state.driveUrl = e.target.value.trim();
        updateAnalyzeButton();
    });
}

function updateAnalyzeButton() {
    elements.analyzeBtn.disabled = !state.driveUrl || state.isAnalyzing;
}

function initAnalyzeButton() {
    elements.analyzeBtn.addEventListener("click", startAnalysis);
    elements.reanalyzeBtn.addEventListener("click", resetAnalysis);
}

// =========================================================
// 分析
// =========================================================
async function startAnalysis() {
    state.isAnalyzing = true;
    updateAnalyzeButton();
    elements.loadingSection.style.display = "block";
    elements.resultsSection.style.display = "none";

    try {
        const response = await analyzeDrive();
        displayResults(response);
    } catch (error) {
        alert("分析中にエラーが発生しました: " + error.message);
    } finally {
        state.isAnalyzing = false;
        updateAnalyzeButton();
        elements.loadingSection.style.display = "none";
    }
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
    elements.driveUrl.value = "";
    state.driveUrl = "";
    updateAnalyzeButton();
}

// =========================================================
// 結果表示
// =========================================================
function displayResults(data) {
    state.results = data;

    animateScore(elements.overallScore, data.overall_score || 0);

    const circumference = 2 * Math.PI * 45;
    const offset = circumference - (data.overall_score / 100) * circumference;
    elements.scoreProgress.style.strokeDashoffset = offset;
    elements.scoreProgress.style.stroke = getScoreColor(data.overall_score);

    if (data.grade) {
        elements.gradeBadge.textContent = data.grade.grade;
        elements.gradeBadge.style.background = data.grade.color;
        elements.gradeLabel.textContent = data.grade.label;
    }

    if (data.expression) {
        elements.expressionScore.textContent = (data.expression.total_score || 0) + "点";
        elements.expressionBars.innerHTML = renderScoreBars(data.expression);
    }

    if (data.voice_tone) {
        elements.voiceScore.textContent = (data.voice_tone.total_score || 0) + "点";
        elements.voiceBars.innerHTML = renderScoreBars(data.voice_tone);
    }

    elements.summaryText.textContent = data.summary || "評価データがありません";

    if (data.improvements && data.improvements.length > 0) {
        elements.improvementsList.innerHTML = data.improvements
            .map(item => `<li><i class="fas fa-exclamation-circle"></i><span>${item}</span></li>`)
            .join("");
    } else {
        elements.improvementsList.innerHTML = "<li>特に改善点はありません</li>";
    }

    elements.resultsSection.style.display = "block";
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
                </div>`;
        })
        .join("");
}

function formatCategoryName(key) {
    const names = {
        smile_intensity: "笑顔の強さ", eye_contact: "アイコンタクト",
        facial_responsiveness: "表情の反応性", positive_engagement: "ポジティブ表現",
        professional_appearance: "プロフェッショナル印象", consistency: "表情の一貫性",
        clarity: "明瞭さ", energy_level: "元気・生命力",
        pace_control: "話速コントロール", emotional_appropriateness: "感情表現の適切さ",
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
    const steps = 60;
    const increment = target / steps;
    const interval = 1500 / steps;
    const timer = setInterval(() => {
        current += increment;
        if (current >= target) { current = target; clearInterval(timer); }
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
        const statusDot  = elements.apiStatus.querySelector(".status-dot");
        const statusText = elements.apiStatus.querySelector(".status-text");
        if (data.status === "ok") {
            statusDot.classList.add("connected");
            statusText.textContent = `接続OK (キー: ${data.api_keys.available_keys}個)`;
        } else {
            statusDot.classList.add("error");
            statusText.textContent = "接続エラー";
        }
    } catch {
        elements.apiStatus.querySelector(".status-dot").classList.add("error");
        elements.apiStatus.querySelector(".status-text").textContent = "サーバーに接続できません";
    }
}

// =========================================================
// 初期化
// =========================================================
document.addEventListener("DOMContentLoaded", () => {
    initDriveInput();
    initAnalyzeButton();
    checkApiStatus();
});
