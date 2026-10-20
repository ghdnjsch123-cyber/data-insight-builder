/**
 * AI Data Insight Builder - Frontend Logic (app.js)
 * Vanilla JavaScript 기반 이벤트 핸들링 및 Chart.js / Marked.js 연동
 */

// 전역 차트 인스턴스 보관
let currentChartInstance = null;
let askChartInstance = null;
let lastAskData = null;
// 진단 데이터 및 마지막 계산 결과 보관
let lastDiagnosis = null;
let lastCalculation = null;
let lastReportMarkdown = "";
let chatHistoryRecords = [];
// PWA 설치 프롬프트 보관
let deferredInstallPrompt = null;

// ==============================================================================
// 1. 초기화 및 페이지 로드
// ==============================================================================
document.addEventListener("DOMContentLoaded", () => {
    console.log("[PAGE] 페이지 로드 완료");
    if (window.Chart) {
        Chart.defaults.color = "#cbd5e1";
        Chart.defaults.borderColor = "rgba(212, 175, 55, 0.15)";
        Chart.defaults.font.family = "'Noto Serif KR', serif";
    }
    initPwa();
    checkServerHealth();
    initUploadEvents();
    initAskEvents();
    initActionEvents();
    initChatEvents();
});

// PWA 서비스 워커 등록 및 설치 프롬프트 제어
function initPwa() {
    const btnInstall = document.getElementById("btnPwaInstall");
    const offlineBanner = document.getElementById("offlineBanner");

    // 1. 서비스 워커 등록
    if ("serviceWorker" in navigator) {
        window.addEventListener("load", () => {
            navigator.serviceWorker.register("/sw.js")
                .then(reg => {
                    console.log("[PWA] Service Worker 등록 성공 (Scope:", reg.scope, ")");
                })
                .catch(err => {
                    console.error("[PWA] Service Worker 등록 실패:", err);
                });
        });
    }

    // 2. 브라우저 PWA 설치 가능 감지 (beforeinstallprompt)
    window.addEventListener("beforeinstallprompt", (e) => {
        // 브라우저 기본 미니 정보바 방지
        e.preventDefault();
        deferredInstallPrompt = e;
        console.log("[PWA] 앱 설치 가능 이벤트 감지 (beforeinstallprompt)");

        if (btnInstall) {
            btnInstall.style.display = "inline-block";
            btnInstall.addEventListener("click", async () => {
                if (!deferredInstallPrompt) return;
                btnInstall.style.display = "none";
                deferredInstallPrompt.prompt();
                const choiceResult = await deferredInstallPrompt.userChoice;
                console.log("[PWA] 사용자 설치 선택:", choiceResult.outcome);
                deferredInstallPrompt = null;
            });
        }
    });

    // 3. 앱 설치 완료 감지
    window.addEventListener("appinstalled", () => {
        console.log("[PWA] 나자릭 앱이 시스템에 성공적으로 설치되었습니다!");
        if (btnInstall) btnInstall.style.display = "none";
        deferredInstallPrompt = null;
    });

    // 4. 온라인/오프라인 상태 모니터링
    function updateOnlineStatus() {
        if (!navigator.onLine) {
            console.warn("[PWA] 오프라인 상태 감지");
            if (offlineBanner) offlineBanner.style.display = "block";
        } else {
            console.log("[PWA] 온라인 상태 복구");
            if (offlineBanner) offlineBanner.style.display = "none";
        }
    }

    window.addEventListener("online", updateOnlineStatus);
    window.addEventListener("offline", updateOnlineStatus);
    updateOnlineStatus();
}

// 서버 헬스체크 및 API 키 설정 상태 확인
async function checkServerHealth() {
    const badgeServer = document.getElementById("badgeServer");
    const badgeApiKey = document.getElementById("badgeApiKey");
    const badgeModel = document.getElementById("badgeModel");

    try {
        const res = await fetch("/health");
        if (!res.ok) throw new Error("서버 응답 오류");
        const data = await res.json();

        badgeServer.className = "badge badge-success";
        badgeServer.textContent = "서버 정상 연결";

        if (data.api_key_configured) {
            badgeApiKey.className = "badge badge-success";
            badgeApiKey.textContent = "API Key 설정 완료";
        } else {
            badgeApiKey.className = "badge badge-warning";
            badgeApiKey.textContent = "API Key 미설정 (.env)";
        }

        badgeModel.textContent = `Model: ${data.model || "gemini-2.5-flash"}`;
    } catch (err) {
        console.error("[ERROR] 헬스체크 실패:", err);
        badgeServer.className = "badge badge-danger";
        badgeServer.textContent = "서버 오프라인";
        badgeApiKey.className = "badge badge-danger";
        badgeApiKey.textContent = "연결 끊김";
    }
}

// ==============================================================================
// 2. 파일 업로드 및 진단 이벤트
// ==============================================================================
function initUploadEvents() {
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");

    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handleFileUpload(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFileUpload(e.target.files[0]);
        }
    });
}

async function handleFileUpload(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
        alert("CSV 파일(.csv)만 업로드할 수 있습니다.");
        console.error("[ERROR] 확장자 불일치:", file.name);
        return;
    }

    console.log(`[UPLOAD] 파일 선택 (파일명: ${file.name}, 크기: ${(file.size / 1024).toFixed(1)} KB)`);

    const dropZone = document.getElementById("dropZone");
    const uploadProgress = document.getElementById("uploadProgress");
    const uploadStatusText = document.getElementById("uploadStatusText");

    dropZone.style.display = "none";
    uploadProgress.style.display = "flex";
    uploadStatusText.textContent = `"${file.name}" 파일을 분석하고 진단하는 중...`;

    const formData = new FormData();
    formData.append("file", file);

    console.log("[INSPECT] 진단 요청 시작");

    try {
        const res = await fetch("/inspect", {
            method: "POST",
            body: formData
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || "파일 진단 중 오류가 발생했습니다.");
        }

        lastDiagnosis = data.diagnosis;
        console.log(`[INSPECT] 진단 응답 수신 (행 수: ${lastDiagnosis.rows_count}, 열 수: ${lastDiagnosis.cols_count}, 경고 수: ${lastDiagnosis.warnings.length})`);

        renderDiagnosis(lastDiagnosis);

        // 후속 단계 섹션 노출
        document.getElementById("sectionDiagnosis").style.display = "block";
        document.getElementById("sectionAsk").style.display = "block";
        document.getElementById("sectionSuggest").style.display = "block";
        document.getElementById("sectionChat").style.display = "block";

        if (lastDiagnosis.recommended_reference_period) {
            document.getElementById("inputRefPeriod").value = lastDiagnosis.recommended_reference_period;
        }

    } catch (err) {
        console.error("[ERROR] 진단 오류 발생:", err);
        alert(`진단 실패: ${err.message}`);
        dropZone.style.display = "block";
    } finally {
        uploadProgress.style.display = "none";
    }
}

function renderDiagnosis(diag) {
    document.getElementById("diagFilename").textContent = diag.filename;
    document.getElementById("diagEncoding").textContent = `${diag.encoding} (${diag.skipped_rows}줄 건너뜀)`;
    document.getElementById("diagShape").textContent = `${diag.rows_count.toLocaleString()}행 × ${diag.cols_count}열`;
    document.getElementById("diagRecYear").textContent = diag.recommended_reference_period || "감지안됨";

    const warningContainer = document.getElementById("warningContainer");
    const warningList = document.getElementById("warningList");
    warningList.innerHTML = "";

    if (diag.warnings && diag.warnings.length > 0) {
        diag.warnings.forEach(w => {
            const li = document.createElement("li");
            li.textContent = w;
            warningList.appendChild(li);
        });
        warningContainer.style.display = "block";
    } else {
        warningContainer.style.display = "none";
    }

    renderPreviewTable(diag.columns, diag.preview);
}

function renderPreviewTable(columns, previewRows) {
    const container = document.getElementById("previewTableContainer");
    if (!previewRows || previewRows.length === 0) {
        container.innerHTML = "<p>미리보기 데이터가 없습니다.</p>";
        return;
    }

    let html = "<table><thead><tr>";
    const displayCols = columns.slice(0, 10);
    displayCols.forEach(col => {
        html += `<th>${escapeHtml(col)}</th>`;
    });
    if (columns.length > 10) html += `<th>... (+${columns.length - 10}열)</th>`;
    html += "</tr></thead><tbody>";

    previewRows.forEach(row => {
        html += "<tr>";
        displayCols.forEach(col => {
            const val = row[col] !== null && row[col] !== undefined ? row[col] : "";
            html += `<td>${escapeHtml(String(val))}</td>`;
        });
        if (columns.length > 10) html += "<td>...</td>";
        html += "</tr>";
    });
    html += "</tbody></table>";

    container.innerHTML = html;
}

// ==============================================================================
// 3. 자연어 질문 분석 & 시각화 토글 (Step 3: POST /ask)
// ==============================================================================
function initAskEvents() {
    const askForm = document.getElementById("askForm");
    const askInput = document.getElementById("askInput");
    const chips = document.querySelectorAll(".ask-chip");
    const btnToggleAskViz = document.getElementById("btnToggleAskViz");

    chips.forEach(chip => {
        chip.addEventListener("click", () => {
            const query = chip.getAttribute("data-query");
            askInput.value = query;
            handleAskSubmit(query);
        });
    });

    askForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = askInput.value.trim();
        if (text) {
            handleAskSubmit(text);
        }
    });

    if (btnToggleAskViz) {
        btnToggleAskViz.addEventListener("click", toggleAskViz);
    }
}

async function handleAskSubmit(query) {
    if (!query) return;

    const askInput = document.getElementById("askInput");
    const btnSubmit = document.getElementById("btnAskSubmit");
    const askProgress = document.getElementById("askProgress");
    const askStatusText = document.getElementById("askStatusText");
    const askResultContainer = document.getElementById("askResultContainer");
    const askAnswerContent = document.getElementById("askAnswerContent");
    const askToolBadge = document.getElementById("askToolBadge");
    const askKoreaBanner = document.getElementById("askKoreaBanner");
    const askKoreaSummaryText = document.getElementById("askKoreaSummaryText");
    const askVizDrawer = document.getElementById("askVizDrawer");
    const btnToggleAskViz = document.getElementById("btnToggleAskViz");

    btnSubmit.disabled = true;
    askProgress.style.display = "flex";
    askStatusText.textContent = `"${query}" - 데이터를 계산하고 한국과 비교 분석하는 중...`;
    askResultContainer.style.display = "none";
    askVizDrawer.style.display = "none";
    btnToggleAskViz.textContent = "📊 시각화 자료 (그래프 & 상세 표) 보기 ▼";

    console.log(`[ASK] 자연어 질문 요청: "${query}"`);

    try {
        const res = await fetch("/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: jsonStringifySafe({ query: query })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || "질문 분석에 실패했습니다.");
        }

        console.log(`[ASK] 응답 수신 완료 (도구: ${data.tool_used})`);
        lastAskData = data;
        lastCalculation = data.calculation;

        // AI 답변 텍스트 렌더링
        askAnswerContent.innerHTML = marked.parse(data.answer || "");
        askToolBadge.textContent = "분석 도구: " + getToolDisplayName(data.tool_used);

        // 한국 비교 요약 배너
        if (data.korea_info && data.korea_info.summary_sentence) {
            askKoreaBanner.style.display = "flex";
            askKoreaSummaryText.textContent = data.korea_info.summary_sentence;
        } else {
            askKoreaBanner.style.display = "none";
        }

        askResultContainer.style.display = "flex";
        document.getElementById("sectionExport").style.display = "block";

        // 결과 영역으로 부드럽게 스크롤
        askResultContainer.scrollIntoView({ behavior: "smooth", block: "start" });

        // 대화 기록에 저장
        chatHistoryRecords.push({ question: query, reply: data.answer });

    } catch (err) {
        console.error("[ERROR] 자연어 질문 오류:", err);
        alert(`질문 분석 오류: ${err.message}`);
    } finally {
        btnSubmit.disabled = false;
        askProgress.style.display = "none";
    }
}

function toggleAskViz() {
    const askVizDrawer = document.getElementById("askVizDrawer");
    const btnToggle = document.getElementById("btnToggleAskViz");

    if (askVizDrawer.style.display === "none" || !askVizDrawer.style.display) {
        askVizDrawer.style.display = "flex";
        btnToggle.textContent = "▲ 시각화 자료 접기";

        if (lastAskData && lastAskData.calculation) {
            if (lastAskData.calculation.chart_data) {
                renderAskChart(lastAskData.calculation.chart_data);
            }
            renderAskTable(lastAskData.calculation.result);
        }
    } else {
        askVizDrawer.style.display = "none";
        btnToggle.textContent = "📊 시각화 자료 (그래프 & 상세 표) 보기 ▼";
    }
}

// ==============================================================================
// 차트 세로축(Y축) 지능형 스케일링 & 막대 수치 표시 플러그인
// ==============================================================================
function calculateSmartYScale(chartType, datasets) {
    if (chartType !== "bar" || !datasets || !datasets.length) {
        return { beginAtZero: true };
    }
    const dataVals = (datasets[0].data || []).filter(v => typeof v === "number" && !isNaN(v));
    if (!dataVals.length) return { beginAtZero: true };

    const minVal = Math.min(...dataVals);
    const maxVal = Math.max(...dataVals);
    const range = maxVal - minVal;

    // 만약 상위권 국가들처럼 값이 50 이상이고 차이가 30 이하로 촘촘하다면,
    // Y축 하단 기준점을 끌어올려 막대 높이 차이가 확연히 드러나도록 스케일링
    if (minVal >= 50 && range <= 30) {
        const paddingBottom = Math.max(2, range * 0.6);
        const yMin = Math.max(0, Math.floor(minVal - paddingBottom));
        const yMax = Math.min(106, Math.ceil(maxVal + 4)); // 상단 수치 라벨 공간
        return {
            beginAtZero: false,
            min: yMin,
            max: yMax
        };
    } else if (range > 0) {
        return {
            beginAtZero: minVal >= 0,
            max: Math.ceil(maxVal * 1.12)
        };
    }
    return { beginAtZero: true };
}

const barValueLabelsPlugin = {
    id: "barValueLabelsPlugin",
    afterDatasetsDraw(chart) {
        const { ctx } = chart;
        chart.data.datasets.forEach((dataset, i) => {
            const meta = chart.getDatasetMeta(i);
            if (meta.hidden || meta.type !== "bar") return;
            meta.data.forEach((element, index) => {
                const val = dataset.data[index];
                if (val === null || val === undefined || isNaN(val)) return;

                const labelText = typeof val === "number" ? `${val}%` : String(val);
                ctx.save();
                const lbl = (chart.data.labels && chart.data.labels[index]) || "";
                const isKorea = lbl.toLowerCase().includes("korea");

                if (isKorea) {
                    ctx.font = "bold 13px 'Noto Serif KR', sans-serif";
                    ctx.fillStyle = "#fde047"; // 한국 막대: 빛나는 황금빛
                } else {
                    ctx.font = "bold 11px 'Noto Serif KR', sans-serif";
                    ctx.fillStyle = "#f8fafc"; // 일반 막대: 선명한 화이트
                }

                ctx.textAlign = "center";
                ctx.textBaseline = "bottom";
                ctx.fillText(labelText, element.x, element.y - 5);
                ctx.restore();
            });
        });
    }
};

function renderAskChart(chartData) {
    const canvas = document.getElementById("askChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    if (askChartInstance) {
        askChartInstance.destroy();
        askChartInstance = null;
    }

    // 막대그래프는 가로가 아닌 세로 막대그래프로 강제하고, 항상 한국을 제일 우측에 배치
    if (chartData.type === "bar") {
        ensureKoreaOnRight(chartData);
        if (chartData.options) delete chartData.options.indexAxis;
    }

    const chartType = chartData.type || "bar";
    const smartY = calculateSmartYScale(chartType, chartData.datasets);

    const chartConfig = {
        type: chartType,
        data: {
            labels: chartData.labels || [],
            datasets: chartData.datasets || []
        },
        plugins: chartType === "bar" ? [barValueLabelsPlugin] : [],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: {
                    top: 26,
                    bottom: 6
                }
            },
            plugins: {
                legend: {
                    display: chartType !== "bar" || (chartData.datasets && chartData.datasets.length > 1),
                    position: "top"
                }
            },
            scales: chartType === "pie" ? {} : {
                x: {
                    grid: { display: false },
                    ticks: {
                        color: "#cbd5e1",
                        maxRotation: 45,
                        minRotation: 0,
                        autoSkip: false
                    }
                },
                y: {
                    beginAtZero: smartY.beginAtZero,
                    min: smartY.min,
                    max: smartY.max,
                    ticks: {
                        color: "#cbd5e1",
                        callback: function(value) {
                            return value + "%";
                        }
                    },
                    grid: { color: "rgba(212, 175, 55, 0.12)" }
                }
            }
        }
    };

    askChartInstance = new Chart(ctx, chartConfig);
    console.log("[ASK_CHART] 자연어 분석 시각화 세로 막대 차트 렌더 완료 (세로축 확대, 수치 라벨 표기)");
}

function renderAskTable(resObj) {
    const container = document.getElementById("askTableContainer");
    if (!container || !resObj) return;

    if (resObj.top_n) {
        let html = "<h4>🏆 상위 랭킹</h4><table><thead><tr><th>순위</th><th>항목(국가)</th><th>수치</th></tr></thead><tbody>";
        resObj.top_n.forEach(item => {
            const isKorea = item.label && item.label.toLowerCase().includes("korea");
            html += `<tr ${isKorea ? "style='background-color:#eff6ff; font-weight:bold;'" : ""}><td>${item.rank}</td><td>${escapeHtml(item.label)}${isKorea ? " 🇰🇷 (우리나라)" : ""}</td><td>${item.value}%</td></tr>`;
        });
        html += "</tbody></table>";

        if (resObj.bottom_n && resObj.bottom_n.length > 0) {
            html += "<h4 style='margin-top:16px;'>🔻 하위 랭킹</h4><table><thead><tr><th>순위</th><th>항목(국가)</th><th>수치</th></tr></thead><tbody>";
            resObj.bottom_n.forEach(item => {
                html += `<tr><td>${item.rank}</td><td>${escapeHtml(item.label)}</td><td>${item.value}%</td></tr>`;
            });
            html += "</tbody></table>";
        }
        container.innerHTML = html;
        return;
    }

    if (resObj.summary) {
        let html = "<table><thead><tr><th>그룹명</th><th>평균</th><th>중앙값</th><th>국가 수</th></tr></thead><tbody>";
        resObj.summary.forEach(item => {
            html += `<tr><td><strong>${escapeHtml(item.group)}</strong></td><td>${item.mean}</td><td>${item.median}</td><td>${item.count}개국</td></tr>`;
        });
        html += "</tbody></table>";
        container.innerHTML = html;
        return;
    }

    let html = "<table><thead><tr><th>통계 지표 항목</th><th>계산된 수치 값</th></tr></thead><tbody>";
    for (const [key, val] of Object.entries(resObj)) {
        if (typeof val === "object" && val !== null) continue;
        const label = translateStatKey(key);
        html += `<tr><td><strong>${escapeHtml(label)}</strong></td><td>${escapeHtml(String(val))}</td></tr>`;
    }
    html += "</tbody></table>";
    container.innerHTML = html;
}

// ==============================================================================
// 4. 버튼 인터랙션 (제안 요청, 도구 실행, 보고서 생성)
// ==============================================================================
function initActionEvents() {
    const btnGetSuggestions = document.getElementById("btnGetSuggestions");
    const selectTool = document.getElementById("selectTool");
    const btnRunTool = document.getElementById("btnRunTool");
    const btnGenerateReport = document.getElementById("btnGenerateReport");
    const btnDownloadReportMd = document.getElementById("btnDownloadReportMd");
    const btnDownloadFullMd = document.getElementById("btnDownloadFullMd");

    selectTool.addEventListener("change", (e) => {
        const tool = e.target.value;
        const targetGroup = document.getElementById("groupTargetItem");
        if (tool === "compare_one_vs_all") {
            targetGroup.style.display = "flex";
        } else {
            targetGroup.style.display = "none";
        }
    });

    btnGetSuggestions.addEventListener("click", handleGetSuggestions);
    btnRunTool.addEventListener("click", handleRunTool);
    btnGenerateReport.addEventListener("click", handleGenerateReport);

    if (btnDownloadReportMd) {
        btnDownloadReportMd.addEventListener("click", handleDownloadReportMd);
    }
    if (btnDownloadFullMd) {
        btnDownloadFullMd.addEventListener("click", handleDownloadFullMd);
    }
}

async function handleGetSuggestions() {
    const btn = document.getElementById("btnGetSuggestions");
    const container = document.getElementById("suggestionCards");

    btn.disabled = true;
    btn.textContent = "⏳ Gemini가 추천 목록을 생성하는 중...";
    console.log("[SUGGEST] 제안 요청 시작");

    try {
        const res = await fetch("/suggest", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || "AI 추천을 가져오지 못했습니다.");
        }

        console.log(`[SUGGEST] 응답 수신 (제안 개수: ${data.suggestions.length}개)`);
        renderSuggestionCards(data.suggestions);
        container.style.display = "grid";

    } catch (err) {
        console.error("[ERROR] 제안 요청 실패:", err);
        alert(`제안 오류: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = "🤖 Gemini에게 맞춤 분석 추천받기";
    }
}

function renderSuggestionCards(suggestions) {
    const container = document.getElementById("suggestionCards");
    container.innerHTML = "";

    suggestions.forEach((item, idx) => {
        const card = document.createElement("div");
        card.className = "suggest-card";
        const badgeTitle = getToolShortBadge(item.tool);
        const fullTitle = getToolDisplayName(item.tool);

        card.innerHTML = `
            <div>
                <div class="card-top">
                    <span class="suggest-tool-badge">${escapeHtml(badgeTitle)}</span>
                    <span style="font-size: 0.75rem; color: #64748b;">기준: ${escapeHtml(item.reference_period || "최신")}</span>
                </div>
                <h4>추천 ${idx + 1}: ${escapeHtml(fullTitle)}</h4>
                <p class="suggest-why">💡 ${escapeHtml(item.why)}</p>
            </div>
            <div class="suggest-caution">
                ⚠️ ${escapeHtml(item.caution || "")}
            </div>
        `;

        card.addEventListener("click", () => {
            document.querySelectorAll(".suggest-card").forEach(c => c.classList.remove("active"));
            card.classList.add("active");

            const selectTool = document.getElementById("selectTool");
            selectTool.value = item.tool;
            selectTool.dispatchEvent(new Event("change"));

            if (item.params && item.params.reference_period) {
                document.getElementById("inputRefPeriod").value = item.params.reference_period;
            } else if (item.reference_period) {
                document.getElementById("inputRefPeriod").value = item.reference_period;
            }

            if (item.params && item.params.target_item) {
                document.getElementById("inputTargetItem").value = item.params.target_item;
            }

            document.getElementById("btnRunTool").scrollIntoView({ behavior: "smooth", block: "center" });
        });

        container.appendChild(card);
    });
}

function getToolShortBadge(tool) {
    const badges = {
        "top_bottom_n": "🏆 상위·하위 순위",
        "compare_one_vs_all": "🎯 국가 vs 평균",
        "trend_line": "📈 시계열 추이선",
        "group_summary": "🌍 그룹별 평균",
        "change_rate": "🚀 성장률/변화량",
        "distribution": "📊 구간별 빈도",
        "correlation_scatter": "🔍 상관관계",
        "describe_numeric": "📐 기초 통계",
        "year_coverage": "📅 데이터 충실도",
        "detect_aggregates": "🏷️ 집계 행 탐지",
        "reshape_wide_to_long": "🔄 형태 변환",
        "quality_report": "📋 품질 보고서"
    };
    return badges[tool] || tool;
}

function getToolDisplayName(tool) {
    const names = {
        "top_bottom_n": "상위·하위 국가 순위 비교",
        "compare_one_vs_all": "특정 국가(한국) vs 전체 평균 비교",
        "trend_line": "주요 국가 연도별 변화 추이선",
        "group_summary": "대륙 및 소득 그룹별 평균 집계",
        "change_rate": "기간별 성장폭·변화량 계산",
        "distribution": "수치 구간별 국가 빈도 분포",
        "correlation_scatter": "두 시점 간 상관관계 산점도",
        "describe_numeric": "전체 데이터 기초 통계 요약",
        "year_coverage": "연도별 데이터 수집 충실도 분석",
        "detect_aggregates": "World 등 대륙/소득 집계 행 탐지",
        "reshape_wide_to_long": "가로형 데이터를 세로형으로 변환",
        "quality_report": "결측치 및 데이터 품질 보고서"
    };
    return names[tool] || tool;
}

// ==============================================================================
// 4. Pandas 도구 실행 (/run) & Chart.js 렌더링
// ==============================================================================
async function handleRunTool() {
    const toolName = document.getElementById("selectTool").value;
    if (!toolName) {
        alert("실행할 분석 도구를 선택해 주세요.");
        return;
    }

    const refPeriod = document.getElementById("inputRefPeriod").value.trim();
    const targetItem = document.getElementById("inputTargetItem").value.trim();
    const excludeAgg = document.getElementById("chkExcludeAggregates").checked;

    const params = {
        exclude_aggregates: excludeAgg
    };

    if (refPeriod) params.reference_period = refPeriod;
    if (targetItem && toolName === "compare_one_vs_all") params.target_item = targetItem;

    console.log(`[RUN] 도구 실행 시작 (도구명: ${toolName}, 기준시점: ${refPeriod || "자동"})`);

    const btn = document.getElementById("btnRunTool");
    btn.disabled = true;
    btn.textContent = "⏳ Pandas가 계산하는 중...";

    try {
        const res = await fetch("/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: jsonStringifySafe({ tool: toolName, params })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || "분석 실행에 실패했습니다.");
        }

        lastCalculation = data.calculation;
        console.log(`[RUN] 결과 수신 완료 (사용한 행: ${lastCalculation.rows_used}, 제외된 행: ${lastCalculation.rows_excluded})`);

        renderCalculationResult(lastCalculation);

        document.getElementById("sectionResult").style.display = "block";
        document.getElementById("sectionExplain").style.display = "block";
        document.getElementById("sectionChat").style.display = "block";
        document.getElementById("sectionExport").style.display = "block";
        document.getElementById("sectionResult").scrollIntoView({ behavior: "smooth", block: "start" });

    } catch (err) {
        console.error("[ERROR] 도구 실행 오류:", err);
        alert(`실행 오류: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = "▶ Pandas 분석 계산 실행";
    }
}

function renderCalculationResult(calc) {
    document.getElementById("resRefPeriod").textContent = calc.reference_period || "-";
    document.getElementById("resRowsUsed").textContent = (calc.rows_used || 0).toLocaleString();
    document.getElementById("resRowsExcluded").textContent = (calc.rows_excluded || 0).toLocaleString();
    document.getElementById("resExclusionReason").textContent = calc.exclusion_reason || "없음";
    document.getElementById("resUnit").textContent = calc.unit || "수치";
    document.getElementById("resCautionText").textContent = calc.caution || "없음";

    const chartContainer = document.getElementById("chartContainer");
    if (calc.chart_data && calc.chart_data.datasets && calc.chart_data.datasets.length > 0) {
        chartContainer.style.display = "block";
        renderChartJs(calc.chart_data);
    } else {
        chartContainer.style.display = "none";
    }

    renderResultTable(calc.result);
}

function ensureKoreaOnRight(chartData) {
    if (!chartData || chartData.type !== "bar") return chartData;
    const labels = chartData.labels || [];
    const datasets = chartData.datasets || [];
    if (!datasets.length || !labels.length) return chartData;

    const data = datasets[0].data || [];
    let bg = datasets[0].backgroundColor;
    let bgList = Array.isArray(bg) ? [...bg] : Array(labels.length).fill(bg || "#3b82f6");

    let koreaIdx = -1;
    for (let i = 0; i < labels.length; i++) {
        if (labels[i] && labels[i].toLowerCase().includes("korea")) {
            koreaIdx = i;
            break;
        }
    }

    if (koreaIdx >= 0 && koreaIdx !== labels.length - 1) {
        const kLabel = labels.splice(koreaIdx, 1)[0];
        const kVal = data.splice(koreaIdx, 1)[0];
        const kBg = bgList.splice(koreaIdx, 1)[0];

        const displayLabel = kLabel.includes("🇰🇷") ? kLabel : `${kLabel} 🇰🇷`;
        labels.push(displayLabel);
        data.push(kVal);
        bgList.push("#dc2626"); // 제일 우측 한국 강조
    }

    chartData.labels = labels;
    datasets[0].data = data;
    datasets[0].backgroundColor = bgList;
    return chartData;
}

function renderChartJs(chartData) {
    const canvas = document.getElementById("insightChart");
    const ctx = canvas.getContext("2d");

    if (currentChartInstance) {
        currentChartInstance.destroy();
        currentChartInstance = null;
    }

    // 막대그래프는 가로가 아닌 세로 막대그래프로 강제하고, 항상 한국을 제일 우측에 배치
    if (chartData.type === "bar") {
        ensureKoreaOnRight(chartData);
        if (chartData.options) delete chartData.options.indexAxis;
    }

    const chartType = chartData.type || "bar";
    const smartY = calculateSmartYScale(chartType, chartData.datasets);

    const chartConfig = {
        type: chartType,
        data: {
            labels: chartData.labels || [],
            datasets: chartData.datasets || []
        },
        plugins: chartType === "bar" ? [barValueLabelsPlugin] : [],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: {
                    top: 26,
                    bottom: 6
                }
            },
            plugins: {
                legend: {
                    display: chartType !== "bar" || (chartData.datasets && chartData.datasets.length > 1),
                    position: "top"
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || "";
                            if (label) label += ": ";
                            if (context.raw !== null && typeof context.raw === "object" && context.raw.y !== undefined) {
                                label += `(${context.raw.x}, ${context.raw.y})`;
                            } else if (context.parsed && context.parsed.y !== undefined) {
                                label += context.parsed.y;
                            } else if (context.raw !== null) {
                                label += context.raw;
                            }
                            return label;
                        }
                    }
                }
            },
            scales: chartType === "pie" ? {} : {
                x: {
                    grid: { display: false },
                    ticks: {
                        color: "#cbd5e1",
                        maxRotation: 45,
                        minRotation: 0,
                        autoSkip: false
                    }
                },
                y: {
                    beginAtZero: smartY.beginAtZero,
                    min: smartY.min,
                    max: smartY.max,
                    ticks: {
                        color: "#cbd5e1",
                        callback: function(value) {
                            return value + "%";
                        }
                    },
                    grid: { color: "rgba(212, 175, 55, 0.12)" }
                }
            }
        }
    };

    currentChartInstance = new Chart(ctx, chartConfig);
    console.log(`[CHART] 차트 렌더 완료 (세로축 확대, 수치 라벨 표기, 차트 종류: ${chartType})`);
}

function renderResultTable(resObj) {
    const container = document.getElementById("calcTableContainer");
    if (!resObj) {
        container.innerHTML = "<p>표시할 계산 수치가 없습니다.</p>";
        return;
    }

    if (resObj.top_n) {
        let html = "<h4>🏆 상위 랭킹</h4><table><thead><tr><th>순위</th><th>항목(국가)</th><th>수치</th></tr></thead><tbody>";
        resObj.top_n.forEach(item => {
            html += `<tr><td>${item.rank}</td><td><strong>${escapeHtml(item.label)}</strong></td><td>${item.value}%</td></tr>`;
        });
        html += "</tbody></table>";

        if (resObj.bottom_n && resObj.bottom_n.length > 0) {
            html += "<h4 style='margin-top:16px;'>🔻 하위 랭킹</h4><table><thead><tr><th>순위</th><th>항목(국가)</th><th>수치</th></tr></thead><tbody>";
            resObj.bottom_n.forEach(item => {
                html += `<tr><td>${item.rank}</td><td><strong>${escapeHtml(item.label)}</strong></td><td>${item.value}%</td></tr>`;
            });
            html += "</tbody></table>";
        }
        container.innerHTML = html;
        return;
    }

    if (resObj.summary) {
        let html = "<table><thead><tr><th>그룹명</th><th>평균</th><th>중앙값</th><th>국가 수</th></tr></thead><tbody>";
        resObj.summary.forEach(item => {
            html += `<tr><td><strong>${escapeHtml(item.group)}</strong></td><td>${item.mean}</td><td>${item.median}</td><td>${item.count}개국</td></tr>`;
        });
        html += "</tbody></table>";
        container.innerHTML = html;
        return;
    }

    let html = "<table><thead><tr><th>통계 지표 항목</th><th>계산된 수치 값</th></tr></thead><tbody>";
    for (const [key, val] of Object.entries(resObj)) {
        if (typeof val === "object" && val !== null) continue;
        const label = translateStatKey(key);
        html += `<tr><td><strong>${escapeHtml(label)}</strong></td><td>${escapeHtml(String(val))}</td></tr>`;
    }
    html += "</tbody></table>";
    container.innerHTML = html;
}

function translateStatKey(key) {
    const dict = {
        "count": "데이터 개수 (유효 국가 수)",
        "mean": "평균값 (Mean)",
        "std": "표준편차 (Standard Deviation)",
        "min": "최솟값 (Min)",
        "25%": "1사분위수 (하위 25%)",
        "50%": "중앙값 (50% Median)",
        "75%": "3사분위수 (상위 25%)",
        "max": "최댓값 (Max)",
        "median": "중앙값 (Median)",
        "pearson_r": "피어슨 상관계수 (r)",
        "start_year": "시작 연도",
        "end_year": "종료 연도",
        "target_item": "비교 대상 항목 (국가명)",
        "target_value": "대상 국가 수치",
        "overall_mean": "전체 평균 수치",
        "overall_median": "전체 중앙값 수치",
        "difference_from_mean": "전체 평균 대비 격차",
        "difference_from_median": "전체 중앙값 대비 격차"
    };
    return dict[key] || key;
}

// ==============================================================================
// 5. Gemini AI 결과 해석 보고서 (/explain)
// ==============================================================================
async function handleGenerateReport() {
    const selectedMode = document.querySelector('input[name="explainMode"]:checked').value;
    const btn = document.getElementById("btnGenerateReport");
    const reportContainer = document.getElementById("reportContainer");
    const reportContent = document.getElementById("reportContent");
    const reportModeBadge = document.getElementById("reportModeBadge");

    console.log(`[EXPLAIN] 해석 요청 시작 (모드: ${selectedMode})`);
    btn.disabled = true;
    btn.textContent = `⏳ Gemini가 ${selectedMode} 보고서를 작성하는 중...`;

    try {
        const res = await fetch("/explain", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: jsonStringifySafe({
                mode: selectedMode,
                calculation: lastCalculation
            })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || "해석 보고서 생성에 실패했습니다.");
        }

        console.log(`[EXPLAIN] 해석 응답 수신 완료 (모드: ${data.mode})`);

        lastReportMarkdown = data.explanation || "";

        if (data.mode === "B") {
            reportModeBadge.className = "badge badge-success";
            reportModeBadge.textContent = "모드 B: Pandas 계산 기반 정식 보고서";
        } else {
            reportModeBadge.className = "badge badge-warning";
            reportModeBadge.textContent = "모드 A: 계산 수치 없는 AI 상상 보고서 (비교용)";
        }

        reportContent.innerHTML = marked.parse(lastReportMarkdown);
        reportContainer.style.display = "block";
        document.getElementById("sectionExport").style.display = "block";
        reportContainer.scrollIntoView({ behavior: "smooth", block: "start" });

    } catch (err) {
        console.error("[ERROR] 해석 보고서 생성 오류:", err);
        alert(`보고서 생성 실패: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = "📑 Gemini 해석 보고서 생성";
    }
}

// ==============================================================================
// 6. 대화형 AI 질의응답 (POST /chat)
// ==============================================================================
function initChatEvents() {
    const chatForm = document.getElementById("chatForm");
    const chatInput = document.getElementById("chatInput");
    const chips = document.querySelectorAll(".chat-chip");

    // 추천 질문 칩 클릭
    chips.forEach(chip => {
        chip.addEventListener("click", () => {
            const question = chip.getAttribute("data-question");
            chatInput.value = question;
            submitChatMessage(question);
        });
    });

    // 폼 서밋
    chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = chatInput.value.trim();
        if (text) {
            submitChatMessage(text);
        }
    });
}

async function submitChatMessage(text) {
    const chatInput = document.getElementById("chatInput");
    const chatMessages = document.getElementById("chatMessages");
    const btnSend = document.getElementById("btnSendChat");

    chatInput.value = "";
    btnSend.disabled = true;

    // 사용자 메시지 말풍선 추가
    appendChatMessage("user", text);
    console.log(`[CHAT] 후속 질문 전송: "${text}"`);

    // 로딩 말풍선 임시 추가
    const loadingElem = appendChatMessage("ai", "<em>답변을 생각하는 중입니다...</em>");

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: jsonStringifySafe({ message: text })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || "답변을 가져오지 못했습니다.");
        }

        console.log("[CHAT] AI 응답 수신 완료");
        chatHistoryRecords.push({ question: text, reply: data.reply || "" });

        // 로딩 말풍선을 실제 답변(마크다운 렌더링)으로 교체
        const bubble = loadingElem.querySelector(".msg-bubble");
        bubble.innerHTML = marked.parse(data.reply || "");

        // Step 7 내보내기 섹션 표시 보장
        document.getElementById("sectionExport").style.display = "block";

    } catch (err) {
        console.error("[ERROR] 채팅 오류:", err);
        const bubble = loadingElem.querySelector(".msg-bubble");
        bubble.innerHTML = `<span style="color:#ef4444;">오류가 발생했습니다: ${escapeHtml(err.message)}</span>`;
    } finally {
        btnSend.disabled = false;
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
}

function appendChatMessage(sender, htmlContent) {
    const chatMessages = document.getElementById("chatMessages");
    const msgDiv = document.createElement("div");
    msgDiv.className = `chat-msg ${sender === "user" ? "user-msg" : "ai-msg"}`;

    const avatar = sender === "user" ? "👤" : "🤖";
    msgDiv.innerHTML = `
        <div class="msg-avatar">${avatar}</div>
        <div class="msg-bubble">${sender === "user" ? escapeHtml(htmlContent) : htmlContent}</div>
    `;

    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return msgDiv;
}

// ==============================================================================
// 7. 마크다운(.md) 보고서 다운로드 기능
// ==============================================================================
function downloadMarkdownFile(content, filename) {
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    console.log(`[DOWNLOAD] 마크다운 파일 다운로드 완료: ${filename}`);
}

function handleDownloadReportMd() {
    if (!lastReportMarkdown) {
        alert("아직 생성된 AI 해석 보고서가 없습니다. 먼저 5단계에서 보고서를 생성해 주세요.");
        return;
    }
    const fileBase = lastDiagnosis ? lastDiagnosis.filename.replace(/\.csv$/i, "") : "데이터";
    const refPeriod = lastCalculation ? lastCalculation.reference_period : "";
    const filename = `AI_해석보고서_${fileBase}_${refPeriod || "전체"}_${new Date().toISOString().slice(0, 10)}.md`;
    downloadMarkdownFile(lastReportMarkdown, filename);
}

function handleDownloadFullMd() {
    if (!lastDiagnosis && !lastCalculation && !lastReportMarkdown) {
        alert("다운로드할 분석 결과가 없습니다. 먼저 데이터 진단 및 분석을 수행해 주세요.");
        return;
    }

    const now = new Date();
    const dateStr = now.toLocaleString("ko-KR");
    const fileBase = lastDiagnosis ? lastDiagnosis.filename.replace(/\.csv$/i, "") : "데이터";
    const refPeriod = lastCalculation ? lastCalculation.reference_period : (lastDiagnosis ? lastDiagnosis.recommended_reference_period : "");

    let md = `# 📊 [데이터 분석 종합 보고서] ${fileBase}\n\n`;
    md += `> **생성 일시:** ${dateStr}\n`;
    md += `> **분석 시스템:** AI Data Insight Builder (Python Pandas 연산 + Gemini AI 지능형 해석)\n\n`;
    md += `---\n\n`;

    // 1. 데이터셋 진단 개요
    md += `## 1. 📋 데이터셋 진단 개요\n\n`;
    if (lastDiagnosis) {
        md += `- **파일명**: \`${lastDiagnosis.filename}\`\n`;
        md += `- **데이터 규모**: ${lastDiagnosis.rows_count.toLocaleString()}행 × ${lastDiagnosis.cols_count}열\n`;
        md += `- **문자 인코딩**: ${lastDiagnosis.encoding} (상단 건너뛴 행: ${lastDiagnosis.skipped_rows}행)\n`;
        md += `- **권장 기준연도**: ${lastDiagnosis.recommended_reference_period || "미지정"}\n`;
        md += `- **감지된 집계 행**: 약 ${lastDiagnosis.aggregate_row_candidates_count || 0}개 (World, 소득 그룹 등)\n\n`;
    } else {
        md += `*진단 데이터 없음*\n\n`;
    }

    // 2. Pandas 정밀 계산 결과
    md += `## 2. ⚡ Python Pandas 정밀 계산 결과\n\n`;
    if (lastCalculation) {
        const toolNameKo = getToolDisplayName(lastCalculation.tool);
        md += `- **분석 도구**: **${toolNameKo}** (\`${lastCalculation.tool}\`)\n`;
        md += `- **기준 시점**: **${lastCalculation.reference_period || "자동"}**\n`;
        md += `- **사용한 행 수**: ${(lastCalculation.rows_used || 0).toLocaleString()}개\n`;
        md += `- **제외된 행 수**: ${(lastCalculation.rows_excluded || 0).toLocaleString()}개 (제외 사유: ${lastCalculation.exclusion_reason || "없음"})\n`;
        md += `- **단위**: ${lastCalculation.unit || "수치"}\n`;
        md += `- **해석 주의사항**: ${lastCalculation.caution || "없음"}\n\n`;

        // 계산 결과 상세 테이블 마크다운 변환
        if (lastCalculation.result) {
            const res = lastCalculation.result;
            if (res.top_n) {
                md += `### 🏆 상위 순위 (Top)\n\n`;
                md += `| 순위 | 국가/항목명 | 수치 |\n|:---:|:---|:---:|\n`;
                res.top_n.forEach(item => {
                    md += `| ${item.rank} | ${item.label} | ${item.value}% |\n`;
                });
                md += `\n`;
            }
            if (res.bottom_n && res.bottom_n.length > 0) {
                md += `### 🔻 하위 순위 (Bottom)\n\n`;
                md += `| 순위 | 국가/항목명 | 수치 |\n|:---:|:---|:---:|\n`;
                res.bottom_n.forEach(item => {
                    md += `| ${item.rank} | ${item.label} | ${item.value}% |\n`;
                });
                md += `\n`;
            }
            if (res.summary) {
                md += `### 🌍 그룹별 집계 요약\n\n`;
                md += `| 그룹명 | 평균 | 중앙값 | 국가 수 |\n|:---|:---:|:---:|:---:|\n`;
                res.summary.forEach(item => {
                    md += `| ${item.group} | ${item.mean} | ${item.median} | ${item.count}개국 |\n`;
                });
                md += `\n`;
            }
            if (!res.top_n && !res.summary) {
                md += `### 📊 상세 통계 지표\n\n`;
                md += `| 통계 지표 항목 | 수치 값 |\n|:---|:---:|\n`;
                for (const [key, val] of Object.entries(res)) {
                    if (typeof val === "object" && val !== null) continue;
                    md += `| ${translateStatKey(key)} | ${val} |\n`;
                }
                md += `\n`;
            }
        }
    } else {
        md += `*실행된 분석 계산 결과 없음*\n\n`;
    }

    // 3. Gemini AI 해석 보고서
    md += `---\n\n## 3. 📑 Gemini AI 종합 해석 보고서\n\n`;
    if (lastReportMarkdown) {
        md += `${lastReportMarkdown}\n\n`;
    } else {
        md += `*아직 생성된 AI 보고서가 없습니다.*\n\n`;
    }

    // 4. 후속 질의응답 (Q&A 대화 내역)
    if (chatHistoryRecords.length > 0) {
        md += `---\n\n## 4. 💬 후속 질의응답 (AI 대화 내역)\n\n`;
        chatHistoryRecords.forEach((item, idx) => {
            md += `### Q${idx + 1}. ${item.question}\n\n`;
            md += `**답변:**\n\n${item.reply}\n\n`;
        });
    }

    const downloadFileName = `종합분석보고서_${fileBase}_${refPeriod || "전체"}_${now.toISOString().slice(0, 10).replace(/-/g, "")}.md`;
    downloadMarkdownFile(md, downloadFileName);
}

// ==============================================================================
// 유틸리티
// ==============================================================================
function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function jsonStringifySafe(obj) {
    return JSON.stringify(obj, (key, value) => {
        if (typeof value === "number" && (isNaN(value) || !isFinite(value))) {
            return null;
        }
        return value;
    });
}
