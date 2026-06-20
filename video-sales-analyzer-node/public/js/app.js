const MAX_CRITERIA_ITEMS = 10;
const INITIAL_CRITERIA_ROWS = 3;
const GAUGE_CIRCUMFERENCE_MAIN = 2 * Math.PI * 120;   // 総合スコアの円周
const GAUGE_CIRCUMFERENCE_MINI = 2 * Math.PI * 58;    // 項目平均スコアの円周
const LOADING_STEPS = ["動画を取得中", "AIエンジンへアップロード中", "映像と音声を解析中", "スコアを集計中"];
const ESTIMATED_DURATION_MS = 70000; // 見込み所要時間（実際の完了で即座に100%へ）
const PROGRESS_CAP_PERCENT = 92;     // 完了までは92%で待機させ、最後に100%へ

const state = {
    driveUrl: "",
    isAnalyzing: false,
    results: null
};

const elements = {
    driveUrl:          document.getElementById("driveUrl"),
    criteriaList:      document.getElementById("criteriaList"),
    addCriteriaBtn:    document.getElementById("addCriteriaBtn"),
    analyzeBtn:        document.getElementById("analyzeBtn"),
    reanalyzeBtn:      document.getElementById("reanalyzeBtn"),
    inputSection:      document.getElementById("inputSection"),
    loadingSection:    document.getElementById("loadingSection"),
    resultsSection:    document.getElementById("resultsSection"),
    loadingPct:        document.getElementById("loadingPct"),
    loadingStepLabel:  document.getElementById("loadingStepLabel"),
    stepList:          document.getElementById("stepList"),
    stepProgressFill:  document.getElementById("stepProgressFill"),
    overallScore:      document.getElementById("overallScore"),
    overallGaugeFill:  document.getElementById("overallGaugeFill"),
    avgGaugeFill:      document.getElementById("avgGaugeFill"),
    avgScoreLabel:     document.getElementById("avgScoreLabel"),
    criteriaCountLabel:document.getElementById("criteriaCountLabel"),
    gradeBadge:        document.getElementById("gradeBadge"),
    gradeLabel:        document.getElementById("gradeLabel"),
    criteriaBars:      document.getElementById("criteriaBars"),
    summaryText:       document.getElementById("summaryText"),
    improvementsList:  document.getElementById("improvementsList"),
    apiStatus:         document.getElementById("apiStatus")
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
// 採点項目（最大10個・自由入力）
// =========================================================
function initCriteriaInputs() {
    for (let i = 0; i < INITIAL_CRITERIA_ROWS; i++) addCriteriaRow();
    elements.addCriteriaBtn.addEventListener("click", () => addCriteriaRow());
}

function addCriteriaRow() {
    const rows = elements.criteriaList.querySelectorAll(".criteria-row");
    if (rows.length >= MAX_CRITERIA_ITEMS) return;

    const row = document.createElement("div");
    row.className = "criteria-row";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "criteria-input";
    input.placeholder = "採点項目を入力（例: 笑顔の自然さ）";
    input.maxLength = 50;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "remove-criteria-btn";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => {
        row.remove();
        updateAddCriteriaBtn();
    });

    row.appendChild(input);
    row.appendChild(removeBtn);
    elements.criteriaList.appendChild(row);
    updateAddCriteriaBtn();
}

function updateAddCriteriaBtn() {
    const count = elements.criteriaList.querySelectorAll(".criteria-row").length;
    elements.addCriteriaBtn.disabled = count >= MAX_CRITERIA_ITEMS;
    elements.addCriteriaBtn.textContent = count >= MAX_CRITERIA_ITEMS
        ? `＋ 項目を追加（最大${MAX_CRITERIA_ITEMS}個）`
        : "＋ 項目を追加";
}

function getCriteriaItems() {
    return Array.from(elements.criteriaList.querySelectorAll(".criteria-input"))
        .map(input => input.value.trim())
        .filter(v => v.length > 0)
        .slice(0, MAX_CRITERIA_ITEMS);
}

// =========================================================
// 分析
// =========================================================
async function startAnalysis() {
    state.isAnalyzing = true;
    updateAnalyzeButton();
    elements.inputSection.style.display = "none";
    elements.resultsSection.style.display = "none";
    elements.loadingSection.style.display = "flex";

    const stopProgress = startProgressSimulation();

    try {
        const response = await analyzeDrive();
        stopProgress();
        await sleep(400);
        displayResults(response);
        elements.loadingSection.style.display = "none";
    } catch (error) {
        stopProgress();
        elements.loadingSection.style.display = "none";
        elements.inputSection.style.display = "block";
        alert("分析中にエラーが発生しました: " + error.message);
    } finally {
        state.isAnalyzing = false;
        updateAnalyzeButton();
    }
}

async function analyzeDrive() {
    const criteria = getCriteriaItems();

    const response = await fetch("/api/analyze/drive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            drive_url: state.driveUrl,
            criteria: criteria
        })
    });
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "分析に失敗しました");
    }
    return response.json();
}

function resetAnalysis() {
    elements.resultsSection.style.display = "none";
    elements.inputSection.style.display = "block";
    elements.driveUrl.value = "";
    state.driveUrl = "";
    updateAnalyzeButton();
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// =========================================================
// ローディング（進捗シミュレーション）
// =========================================================
function startProgressSimulation() {
    const start = performance.now();
    renderLoadingSteps(0);

    const timer = setInterval(() => {
        const elapsed = performance.now() - start;
        const progress = Math.min(PROGRESS_CAP_PERCENT, Math.round((elapsed / ESTIMATED_DURATION_MS) * 100));
        renderLoadingSteps(progress);
    }, 200);

    return function stop() {
        clearInterval(timer);
        renderLoadingSteps(100);
    };
}

function renderLoadingSteps(progress) {
    elements.loadingPct.textContent = progress + "%";
    elements.stepProgressFill.style.width = progress + "%";

    const stepCount = LOADING_STEPS.length;
    const idx = Math.min(stepCount - 1, Math.floor(progress / (100 / stepCount)));
    elements.loadingStepLabel.textContent = LOADING_STEPS[idx];

    elements.stepList.innerHTML = LOADING_STEPS.map((label, i) => {
        const st = i < idx ? "done" : i === idx ? "active" : "todo";
        return `
            <div class="step-row" data-step="${st}">
                <span class="step-dot"></span>
                <span class="step-label-text">${label}</span>
                <span class="step-mark">${st === "done" ? "✓" : ""}</span>
            </div>`;
    }).join("");
}

// =========================================================
// 結果表示
// =========================================================
function displayResults(data) {
    state.results = data;

    const overall = data.overall_score || 0;
    animateNumber(elements.overallScore, overall);
    elements.overallGaugeFill.style.strokeDashoffset =
        GAUGE_CIRCUMFERENCE_MAIN * (1 - overall / 100);

    const scores = Array.isArray(data.scores) ? data.scores : [];
    const avg = scores.length > 0
        ? Math.round(scores.reduce((sum, s) => sum + (s.score || 0), 0) / scores.length)
        : 0;
    animateNumber(elements.avgScoreLabel, avg);
    elements.avgGaugeFill.style.strokeDashoffset =
        GAUGE_CIRCUMFERENCE_MINI * (1 - avg / 100);
    elements.criteriaCountLabel.textContent = `${scores.length} 項目を総合評価`;

    if (data.grade) {
        elements.gradeBadge.textContent = data.grade.grade;
        elements.gradeBadge.style.color = data.grade.color;
        elements.gradeLabel.textContent = data.grade.label;
    }

    elements.criteriaBars.innerHTML = renderCriteriaBars(scores);

    elements.summaryText.textContent = data.summary || "評価データがありません";

    if (data.improvements && data.improvements.length > 0) {
        elements.improvementsList.innerHTML = data.improvements
            .map((text, i) => `
                <li class="improvement-item">
                    <span class="improvement-no">${String(i + 1).padStart(2, "0")}</span>
                    <span class="improvement-text">${escapeHtml(text)}</span>
                </li>`)
            .join("");
    } else {
        elements.improvementsList.innerHTML = '<li class="no-data-text">特に改善点はありません</li>';
    }

    elements.resultsSection.style.display = "block";
    elements.resultsSection.scrollIntoView({ behavior: "smooth" });
}

function renderCriteriaBars(scores) {
    if (!Array.isArray(scores) || scores.length === 0) {
        return '<p class="no-data-text">採点データがありません</p>';
    }
    return scores
        .map(({ item, score, comment }) => {
            const s = score || 0;
            return `
                <div class="score-bar-item">
                    <div class="bar-label">
                        <span class="bar-name">${escapeHtml(item || "")}</span>
                        <span class="bar-score">${s}</span>
                    </div>
                    <div class="bar-track">
                        <div class="bar-fill" style="width: ${s}%;"></div>
                    </div>
                    ${comment ? `<p class="bar-comment">${escapeHtml(comment)}</p>` : ""}
                </div>`;
        })
        .join("");
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function animateNumber(element, target) {
    let current = 0;
    const steps = 60;
    const increment = target / steps;
    const interval = 1200 / steps;
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
    initCriteriaInputs();
    initAnalyzeButton();
    checkApiStatus();
});
