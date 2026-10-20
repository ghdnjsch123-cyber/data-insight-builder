import csv
import glob
import io
import json
import logging
import os
import re
from flask import Flask, jsonify, render_template, request
import numpy as np
import pandas as pd
from dotenv import load_dotenv

import tools

# .env 환경변수 로드
load_dotenv()

# 로깅 설정 (print() 사용 금지 규정 준수)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DataInsightBuilder")

app = Flask(__name__)

# 파일 업로드 용량 제한 설정 (기본 10MB)
max_mb = int(os.getenv("MAX_UPLOAD_MB", 10))
app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024

# 메모리에 보관할 단일 데이터셋 저장소 (서버 재시작 시 초기화됨)
current_dataset = {
    "df": None,
    "filename": None,
    "diagnosis": None,
    "last_run": None,
    "chat_history": []
}

# 12가지 공인 도구 카탈로그 정의
TOOL_CATALOG = {
    "reshape_wide_to_long": "가로형 연도 열들을 세로형(Long) 행으로 접기",
    "quality_report": "결측치·중복·이상한 열 이름 품질 진단 보고서",
    "year_coverage": "연도별 값 개수와 권장 기준연도 계산",
    "detect_aggregates": "World, 소득 그룹 등 집계 행 후보 탐지",
    "describe_numeric": "개수·평균·중앙값·최소·최대·표준편차 기술통계",
    "trend_line": "선택 항목들의 연도별 시계열 추이 (선 차트)",
    "top_bottom_n": "기준연도 기준 상위·하위 N개 순위 (수평 막대)",
    "group_summary": "대륙/소득 등 그룹별 평균·합계·개수 (막대)",
    "change_rate": "두 시점 사이 변화량(%p)과 변화율(%) (막대)",
    "distribution": "수치 구간별 빈도 분포 (히스토그램)",
    "correlation_scatter": "두 시점/변수 간 피어슨 상관계수 (산점도)",
    "compare_one_vs_all": "특정 항목(한국 등) vs 전체 평균·중앙값 (강조 막대)"
}

@app.route("/", methods=["GET"])
def index():
    logger.info("[REQUEST] GET /")
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    logger.info("[REQUEST] GET /health")
    raw_key = os.getenv("GEMINI_API_KEY", "").strip()
    is_key_set = bool(raw_key and raw_key != "your_gemini_api_key_here")
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    return jsonify({
        "status": "ok",
        "api_key_configured": is_key_set,
        "model": model_name
    })

def detect_encoding_and_decode(raw_bytes: bytes):
    encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]
    for enc in encodings:
        try:
            text = raw_bytes.decode(enc)
            logger.info(f"[ENCODING] {enc} 성공")
            return text, enc
        except UnicodeDecodeError:
            logger.info(f"[ENCODING] {enc} 실패, 다음 인코딩 시도")
            continue
    return None, None

def detect_header_skiprows(text: str):
    lines = text.splitlines()
    if not lines:
        return 0

    max_cols = 0
    header_idx = 0

    for idx, line in enumerate(lines[:25]):
        trimmed = line.strip()
        if not trimmed:
            continue
        try:
            row = list(csv.reader([trimmed]))[0]
            if len(row) > max_cols:
                max_cols = len(row)
                header_idx = idx
        except Exception:
            continue

    logger.info(f"[HEADER] 헤더 줄 감지 결과 (건너뛴 줄 수: {header_idx}줄)")
    return header_idx

def clean_for_json(obj):
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(v) for v in obj]
    elif isinstance(obj, (float, np.floating)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, (int, np.integer)):
        return int(obj)
    elif pd.isna(obj):
        return None
    return obj

def get_indicator_metadata():
    meta_files = glob.glob(r"data/**/Metadata_Indicator*.csv", recursive=True)
    if meta_files:
        try:
            m_df = pd.read_csv(meta_files[0], encoding="utf-8-sig")
            return {
                "indicator_code": str(m_df.get("INDICATOR_CODE", ["IT.NET.USER.ZS"])[0]),
                "indicator_name": str(m_df.get("INDICATOR_NAME", ["Individuals using the Internet (% of population)"])[0]),
                "source_note": str(m_df.get("SOURCE_NOTE", ["Internet users are individuals who have used the Internet (from any location) in the last 3 months."])[0]),
                "source_org": str(m_df.get("SOURCE_ORGANIZATION", ["World Telecommunication/ICT Indicators Database, International Telecommunication Union (ITU)"])[0])
            }
        except Exception:
            pass
    return {
        "indicator_code": "IT.NET.USER.ZS",
        "indicator_name": "인구 대비 인터넷 이용자 비율 (%)",
        "source_note": "지난 3개월 동안 어떤 장소에서든 인터넷을 사용한 개인의 비율 (ITU 권고 기준)",
        "source_org": "World Bank / ITU"
    }

@app.route("/inspect", methods=["POST"])
def inspect():
    logger.info("[REQUEST] POST /inspect")

    if "file" not in request.files:
        logger.warning("[ERROR] 파일 미선택")
        return jsonify({"error": "업로드할 CSV 파일을 선택해 주세요."}), 400

    file = request.files["file"]
    if not file or not file.filename:
        logger.warning("[ERROR] 빈 파일명")
        return jsonify({"error": "선택된 파일이 없습니다."}), 400

    filename = file.filename
    if not filename.lower().endswith(".csv"):
        logger.warning(f"[ERROR] CSV 아님: {filename}")
        return jsonify({"error": "CSV 파일(.csv)만 업로드할 수 있습니다."}), 400

    raw_bytes = file.read()
    file_size = len(raw_bytes)
    logger.info(f"[FILE] name={filename} size={file_size} bytes")

    if file_size == 0:
        logger.warning("[ERROR] 빈 파일")
        return jsonify({"error": "업로드한 파일의 내용이 비어 있습니다."}), 400

    text, successful_encoding = detect_encoding_and_decode(raw_bytes)
    if text is None:
        logger.error("[ERROR] 인코딩 전부 실패")
        return jsonify({"error": "지원하는 인코딩(utf-8-sig, utf-8, cp949, euc-kr)으로 파일을 읽을 수 없습니다."}), 400

    skiprows = detect_header_skiprows(text)

    try:
        df = pd.read_csv(io.StringIO(text), skiprows=skiprows)
    except Exception as e:
        logger.error(f"[ERROR] 파싱 실패: {str(e)}")
        return jsonify({"error": f"CSV 파일 파싱에 실패했습니다: {str(e)}"}), 400

    rows_count, cols_count = df.shape
    columns = [str(c) for c in df.columns]
    logger.info(f"[CSV] parsing 완료 rows={rows_count} columns={cols_count}")

    dtypes = {str(c): str(df[c].dtype) for c in df.columns}

    year_date_columns = []
    for c in df.columns:
        c_str = str(c).strip()
        if re.match(r"^(18|19|20)\d{2}$", c_str):
            year_date_columns.append(c_str)

    numeric_columns = []
    text_columns = []
    for c in df.columns:
        col_str = str(c)
        if col_str in year_date_columns:
            continue
        num_series = pd.to_numeric(df[c], errors="coerce")
        non_null_count = num_series.notna().sum()
        if non_null_count > rows_count * 0.4 and non_null_count > 0:
            numeric_columns.append(col_str)
        else:
            text_columns.append(col_str)

    missing_values = {}
    for c in df.columns:
        col_str = str(c)
        null_count = int(df[c].isna().sum())
        null_ratio = round(null_count / rows_count, 4) if rows_count > 0 else 0.0
        missing_values[col_str] = {
            "count": null_count,
            "ratio": null_ratio
        }

    duplicate_rows_count = int(df.duplicated().sum())
    unnamed_columns = [c for c in columns if c.startswith("Unnamed:") or not c.strip()]
    empty_columns = [str(c) for c in df.columns if df[c].isna().all()]

    year_coverage = []
    recommended_reference_period = None

    if year_date_columns:
        for yc in sorted(year_date_columns):
            num_vals = pd.to_numeric(df[yc], errors="coerce")
            filled_cnt = int(num_vals.notna().sum())
            ratio = round(filled_cnt / rows_count, 4) if rows_count > 0 else 0.0
            year_coverage.append({
                "year": yc,
                "filled_count": filled_cnt,
                "total_count": rows_count,
                "ratio": ratio
            })

        sufficient_years = [y for y in year_coverage if y["ratio"] >= 0.5]
        if sufficient_years:
            recommended_reference_period = sufficient_years[-1]["year"]
        elif year_coverage:
            best_year = max(year_coverage, key=lambda x: x["filled_count"])
            recommended_reference_period = best_year["year"]

    agg_keywords = [
        "world", "oecd members", "oecd", "euro area", "european union",
        "high income", "low income", "middle income", "income", "area",
        "total", "dividend", "blend", "ida & ibrd", "small states",
        "africa eastern", "africa western", "latin america", "middle east",
        "sub-saharan", "south asia", "central europe", "caribbean", "countries"
    ]
    label_col = text_columns[0] if text_columns else df.columns[0]
    aggregate_row_candidates = []

    for idx, val in df[label_col].dropna().items():
        v_str = str(val).strip()
        v_lower = v_str.lower()
        matched = [k for k in agg_keywords if k in v_lower]
        if matched:
            aggregate_row_candidates.append({
                "index": int(idx),
                "label": v_str,
                "matched_keyword": matched[0]
            })

    df_preview = df.head(10).copy()
    preview = clean_for_json(df_preview.to_dict(orient="records"))

    warnings = []
    if skiprows > 0:
        warnings.append(f"상단 {skiprows}개의 안내문/메타데이터 행을 건너뛰고 {skiprows + 1}번째 행을 열 이름(헤더)으로 감지했습니다.")
    if unnamed_columns:
        warnings.append(f"이름이 없거나 비어있는 Unnamed 열이 {len(unnamed_columns)}개 감지되었습니다: {unnamed_columns}")
    if empty_columns:
        warnings.append(f"전체 행이 비어 있는 열이 {len(empty_columns)}개 있습니다.")
    if duplicate_rows_count > 0:
        warnings.append(f"완전히 동일한 중복 행이 {duplicate_rows_count}개 발견되었습니다.")
    if aggregate_row_candidates:
        warnings.append(f"개별 항목(국가 등)이 아닌 합계/지역 묶음으로 추정되는 집계 행이 {len(aggregate_row_candidates)}개 감지되었습니다. (분석 시 왜곡 방지를 위해 제외 권장)")
    if year_coverage and recommended_reference_period:
        latest_year = year_coverage[-1]["year"]
        if latest_year != recommended_reference_period:
            warnings.append(f"가장 최근 연도 열은 '{latest_year}'이나, 채워진 데이터가 부족하여(채움률: {year_coverage[-1]['ratio']*100:.1f}%) 데이터가 충분한 '{recommended_reference_period}'을 권장 기준연도로 제안합니다.")

    diagnosis = {
        "filename": filename,
        "file_size": file_size,
        "encoding": successful_encoding,
        "skipped_rows": skiprows,
        "rows_count": rows_count,
        "cols_count": cols_count,
        "columns": columns,
        "dtypes": dtypes,
        "numeric_columns": numeric_columns,
        "text_columns": text_columns,
        "year_date_columns": year_date_columns,
        "missing_values": missing_values,
        "duplicate_rows_count": duplicate_rows_count,
        "unnamed_columns": unnamed_columns,
        "empty_columns": empty_columns,
        "year_coverage": year_coverage,
        "recommended_reference_period": recommended_reference_period,
        "aggregate_row_candidates_count": len(aggregate_row_candidates),
        "aggregate_row_candidates": aggregate_row_candidates[:20],
        "preview": preview,
        "warnings": warnings,
        "memory_notice": "업로드된 데이터는 서버 메모리에만 임시 보관되며 서버 재시작 시 초기화됩니다."
    }

    current_dataset["df"] = df
    current_dataset["filename"] = filename
    current_dataset["diagnosis"] = diagnosis
    current_dataset["last_run"] = None
    current_dataset["chat_history"] = []

    logger.info(f"[DIAGNOSE] 진단 완료 warnings={len(warnings)}")

    return jsonify({
        "success": True,
        "diagnosis": diagnosis
    })

# ==============================================================================
# POST /suggest - Gemini AI 기반 분석 도구 제안
# ==============================================================================
@app.route("/suggest", methods=["POST"])
def suggest():
    logger.info("[REQUEST] POST /suggest")

    if current_dataset["df"] is None or current_dataset["diagnosis"] is None:
        logger.warning("[ERROR] 데이터셋 미로드 상태에서 제안 요청")
        return jsonify({"error": "먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] API Key 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 유효한 GEMINI_API_KEY를 입력해 주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    diag = current_dataset["diagnosis"]

    prompt_payload = {
        "dataset_summary": {
            "filename": diag["filename"],
            "rows_count": diag["rows_count"],
            "cols_count": diag["cols_count"],
            "text_columns": diag["text_columns"][:5],
            "year_columns_range": f"{diag['year_date_columns'][0]}~{diag['year_date_columns'][-1]}" if diag["year_date_columns"] else "없음",
            "recommended_reference_period": diag["recommended_reference_period"],
            "aggregate_candidates_count": diag["aggregate_row_candidates_count"]
        },
        "available_tool_catalog": TOOL_CATALOG
    }

    system_instruction = (
        "당신은 초보자를 위한 데이터 분석 멘토 AI입니다.\n"
        "제공된 데이터셋 요약 정보와 사용 가능한 12가지 도구 카탈로그(available_tool_catalog)만 사용하여, "
        "이 데이터셋에서 실행 가능한 가장 가치 있는 분석 3~5가지를 제안하세요.\n\n"
        "절대 규칙:\n"
        "1. 카탈로그에 없는 도구는 절대 제안하지 마세요.\n"
        "2. 데이터셋에 존재하지 않는 열 이름을 params에 넣지 마세요.\n"
        "3. 7~12번 도구는 reference_period가 필수입니다. 권장 기준연도(예: 2024)를 적극 활용하세요.\n"
        "4. 오직 순수 JSON 형식으로만 응답해야 합니다. 마크다운 따옴표(```json) 없이 원본 JSON만 출력하세요.\n"
        "5. why는 초보자가 이해하기 쉽게 왜 이 분석이 의미 있는지 설명하고, caution은 해석 시 주의할 점을 적으세요.\n\n"
        "출력 JSON 스키마:\n"
        "{\n"
        '  "suggestions": [\n'
        "    {\n"
        '      "tool": "도구명 (카탈로그에 존재하는 정확한 이름)",\n'
        '      "params": {"reference_period": "2024", "exclude_aggregates": true, ...},\n'
        '      "reference_period": "2024",\n'
        '      "why": "초보자를 위한 분석 추천 이유",\n'
        '      "caution": "해석 시 주의사항"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    full_prompt = f"{system_instruction}\n\n데이터셋 정보:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
    logger.info(f"[AI] suggest 요청 시작 (model={model_name})")

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=full_prompt,
            config={"response_mime_type": "application/json"}
        )
        raw_text = response.text.strip()
        logger.info("[AI] suggest 응답 수신 완료")
    except Exception as e:
        err_msg = str(e)
        logger.error(f"[ERROR] Gemini API 호출 실패: {err_msg}")
        if "API_KEY_INVALID" in err_msg or "400" in err_msg or "403" in err_msg:
            return jsonify({"error": "Gemini API 인증에 실패했습니다. .env 파일의 GEMINI_API_KEY가 올바른지 확인해 주세요."}), 401
        elif "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            return jsonify({"error": "Gemini API 요청 시간이 초과되었습니다 (API Timeout). 잠시 후 다시 시도해 주세요."}), 504
        return jsonify({"error": f"Gemini API 호출 중 네트워크 또는 서버 오류가 발생했습니다: {err_msg}"}), 500

    try:
        cleaned_json = raw_text
        if cleaned_json.startswith("```"):
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", cleaned_json)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

        data = json.loads(cleaned_json)
        raw_suggestions = data.get("suggestions", [])
        logger.info(f"[AI] JSON 파싱 결과: {len(raw_suggestions)}개 제안 수신")
    except Exception as e:
        logger.error(f"[ERROR] Gemini 응답 JSON 파싱 실패: {str(e)} | 원문: {raw_text[:200]}")
        return jsonify({"error": "Gemini의 응답을 JSON으로 파싱하는 데 실패했습니다."}), 502

    valid_suggestions = []
    for s in raw_suggestions:
        tool_name = s.get("tool")
        if tool_name in TOOL_CATALOG:
            if "params" not in s or not isinstance(s["params"], dict):
                s["params"] = {}
            if "reference_period" not in s:
                s["reference_period"] = s["params"].get("reference_period", diag.get("recommended_reference_period", "2024"))
            valid_suggestions.append(s)
        else:
            logger.warning(f"[AI] 카탈로그에 없는 승인되지 않은 도구 제안 무시: {tool_name}")

    if not valid_suggestions:
        logger.warning("[AI] 유효한 제안 도구가 0개임")
        return jsonify({"error": "Gemini가 유효한 카탈로그 도구를 제안하지 못했습니다. 다시 시도해 주세요."}), 502

    return jsonify({
        "success": True,
        "suggestions": valid_suggestions[:5]
    })

# ==============================================================================
# POST /run - 선택된 도구를 Pandas로 실제 계산 (절대 규칙: Gemini에게 계산시키지 않음)
# ==============================================================================
@app.route("/run", methods=["POST"])
def run_tool():
    logger.info("[REQUEST] POST /run")

    if current_dataset["df"] is None:
        logger.warning("[ERROR] 데이터셋 미로드 상태에서 /run 요청")
        return jsonify({"error": "먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    tool_name = req_data.get("tool")
    params = req_data.get("params", {})

    if not tool_name or tool_name not in TOOL_CATALOG:
        logger.warning(f"[ERROR] 카탈로그에 없는 도구 요청: {tool_name}")
        return jsonify({"error": f"도구 목록에 없는 도구 요청입니다: {tool_name}"}), 400

    needs_ref_period = [
        "top_bottom_n", "group_summary", "change_rate",
        "distribution", "correlation_scatter", "compare_one_vs_all"
    ]
    if tool_name in needs_ref_period:
        ref_period = params.get("reference_period")
        if not ref_period:
            rec_period = current_dataset["diagnosis"].get("recommended_reference_period")
            if rec_period:
                params["reference_period"] = rec_period
                logger.info(f"[PARAM] 기준 시점 미입력으로 권장 기준연도 자동 적용: {rec_period}")
            else:
                logger.warning(f"[ERROR] 도구 {tool_name}에 기준 시점 미입력")
                return jsonify({"error": f"'{tool_name}' 도구는 기준 시점(reference_period)이 필수입니다."}), 400

    df = current_dataset["df"]

    try:
        tool_fn = getattr(tools, tool_name)
        result = tool_fn(df, **params)
    except TypeError as te:
        logger.error(f"[ERROR] 파라미터 전달 오류: {str(te)}")
        return jsonify({"error": f"도구 실행 파라미터가 올바르지 않습니다: {str(te)}"}), 400
    except ValueError as ve:
        logger.error(f"[ERROR] 도구 계산 중 값 오류: {str(ve)}")
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"[ERROR] 도구 실행 실패 ({tool_name}): {str(e)}", exc_info=True)
        return jsonify({"error": f"분석 실행 중 오류가 발생했습니다: {str(e)}"}), 500

    logger.info(f"[TOOL] name={tool_name} params={params} rows_used={result.get('rows_used')} rows_excluded={result.get('rows_excluded')}")
    if result.get("chart_data") and result["chart_data"].get("type") == "bar":
        tools.format_bar_chart_with_korea_on_right(result["chart_data"], df, params.get("reference_period"))
    current_dataset["last_run"] = result

    return jsonify({
        "success": True,
        "calculation": result
    })

# ==============================================================================
# POST /explain - Pandas 계산 결과만 Gemini에 전달하여 해석 생성 (모드 A/B)
# ==============================================================================
@app.route("/explain", methods=["POST"])
def explain():
    logger.info("[REQUEST] POST /explain")

    if current_dataset["df"] is None or current_dataset["diagnosis"] is None:
        logger.warning("[ERROR] 데이터셋 미로드 상태에서 /explain 요청")
        return jsonify({"error": "먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] API Key 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 유효한 GEMINI_API_KEY를 입력해 주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    req_data = request.get_json(silent=True) or {}
    mode = str(req_data.get("mode", "B")).upper()
    if mode not in ["A", "B"]:
        mode = "B"

    calculation = req_data.get("calculation") or current_dataset.get("last_run")
    if mode == "B" and not calculation:
        logger.warning("[ERROR] 모드 B 실행 시 계산 결과 누락")
        return jsonify({"error": "먼저 분석 도구(/run)를 실행하여 계산 결과를 얻은 후 해석을 요청해 주세요."}), 400

    diag = current_dataset["diagnosis"]
    meta_info = get_indicator_metadata()

    if mode == "A":
        logger.info(f"[AI] explain 요청 시작 (모드 A, model={model_name})")
        prompt = (
            "당신은 일반 AI입니다. 아래 데이터셋 정보를 보고 이 데이터를 분석해서 종합 보고서를 써주세요.\n\n"
            f"파일명: {diag['filename']}\n"
            f"행 수: {diag['rows_count']}, 열 수: {diag['cols_count']}\n"
            f"열 목록: {', '.join(diag['columns'][:15])} ...\n"
            "자유롭게 데이터 분석 보고서를 작성하세요."
        )
    else:
        logger.info(f"[AI] explain 요청 시작 (모드 B, model={model_name})")
        system_rules = (
            "당신은 공인된 수석 데이터 분석관입니다. "
            "절대 규칙: 오직 제공된 Pandas 계산 결과(calculation_data)에 있는 수치만 사용하여 해석 보고서를 작성하세요.\n\n"
            "엄격한 8대 작성 규칙:\n"
            "1. 제공된 계산 결과에 있는 숫자만 사용한다.\n"
            "2. 직접 임의로 암산하거나 추정하지 않는다.\n"
            "3. 데이터에 없는 가상의 국가, 연도, 열을 언급하지 않는다.\n"
            "4. 기준 시점(reference_period)과 제외된 행 수(rows_excluded) 및 제외 사유를 반드시 본문에 명시한다.\n"
            "5. 상관관계를 결코 인과관계로 표현하지 않는다.\n"
            "6. 지표의 공식 정의와 출처를 보고서 앞부분에 명확히 표기한다.\n"
            "7. 확인할 수 없는 것은 솔직하게 '이 데이터로는 확인할 수 없다'라고 쓴다.\n"
            "8. 중학생도 이해할 수 있게 쉬운 한국어로 쓰되, 통계적 정확성을 절대 희생하지 않는다.\n\n"
            "반드시 아래의 마크다운 섹션 제목(##) 형식을 그대로 지켜서 출력하세요:\n"
            "## 무엇을 봤는가\n"
            "## 데이터 출처와 정의\n"
            "## 기준 시점과 제외된 항목\n"
            "## 계산 결과\n"
            "## 읽어낼 수 있는 것\n"
            "## 이 데이터로는 알 수 없는 것\n"
            "## 다음에 확인해볼 것\n"
        )

        prompt_payload = {
            "metadata_and_indicator": meta_info,
            "calculation_data": {
                "tool": calculation.get("tool"),
                "reference_period": calculation.get("reference_period"),
                "rows_used": calculation.get("rows_used"),
                "rows_excluded": calculation.get("rows_excluded"),
                "exclusion_reason": calculation.get("exclusion_reason"),
                "columns_used": calculation.get("columns_used"),
                "unit": calculation.get("unit"),
                "caution": calculation.get("caution"),
                "result": calculation.get("result")
            }
        }

        prompt = f"{system_rules}\n\n[입력 데이터]:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        explanation_text = response.text.strip()
        logger.info(f"[AI] explain 응답 수신 완료 (모드 {mode})")
    except Exception as e:
        err_msg = str(e)
        logger.error(f"[ERROR] Gemini API 호출 실패 ({mode}): {err_msg}")
        if "API_KEY_INVALID" in err_msg or "400" in err_msg or "403" in err_msg:
            return jsonify({"error": "Gemini API 인증에 실패했습니다. .env 파일의 GEMINI_API_KEY가 올바른지 확인해 주세요."}), 401
        elif "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            return jsonify({"error": "Gemini API 요청 시간이 초과되었습니다 (API Timeout). 잠시 후 다시 시도해 주세요."}), 504
        return jsonify({"error": f"Gemini API 호출 중 오류가 발생했습니다: {err_msg}"}), 500

    return jsonify({
        "success": True,
        "mode": mode,
        "explanation": explanation_text
    })

# ==============================================================================
# POST /chat - 분석 결과를 바탕으로 한 대화형 후속 질의응답
# ==============================================================================
@app.route("/chat", methods=["POST"])
def chat():
    logger.info("[REQUEST] POST /chat")

    if current_dataset["df"] is None:
        return jsonify({"error": "먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일의 GEMINI_API_KEY를 확인해 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    user_message = req_data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    diag = current_dataset["diagnosis"]
    calc = current_dataset.get("last_run")
    meta_info = get_indicator_metadata()

    system_instruction = (
        "당신은 'AI Data Insight Builder'의 친절한 데이터 분석 조교입니다.\n"
        "사용자가 방금 수행한 데이터 분석 결과와 통계 지표에 대해 후속 질문을 하고 있습니다.\n\n"
        "답변 규칙:\n"
        "1. 반드시 제공된 [데이터 진단 정보], [지표 출처 및 정의], 그리고 [최근 Pandas 계산 결과]를 기반으로 정확하게 답변하세요.\n"
        "2. 계산 결과에 나와 있지 않은 숫자를 거짓으로 꾸며내지(추정/환각) 마세요.\n"
        "3. 만약 사용자가 현재 분석 결과로 답할 수 없는 질문(예: 다른 지표나 다른 분석)을 하면, "
        "'현재 계산 결과로는 알 수 없습니다'라고 밝히고, 12가지 도구 카탈로그 중 어떤 도구를 실행하면 확인할 수 있는지 안내해 주세요.\n"
        "4. 중학생도 이해할 수 있도록 존댓말로 친절하고 명쾌하게 답변하세요. 마크다운 서식을 사용하여 가독성을 높이세요."
    )

    context_data = {
        "dataset_summary": {
            "filename": diag["filename"],
            "total_rows": diag["rows_count"],
            "recommended_period": diag["recommended_reference_period"],
            "aggregate_rows_count": diag["aggregate_row_candidates_count"]
        },
        "indicator_metadata": meta_info,
        "latest_pandas_calculation": calc if calc else "아직 특정 도구를 실행하지 않은 상태입니다.",
        "user_question": user_message
    }

    full_prompt = f"{system_instruction}\n\n[현재 분석 컨텍스트]:\n{json.dumps(context_data, ensure_ascii=False, indent=2)}\n\n사용자 질문: {user_message}"
    logger.info(f"[AI] chat 요청 시작 (model={model_name})")

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=full_prompt
        )
        reply_text = response.text.strip()
        logger.info("[AI] chat 응답 수신 완료")
    except Exception as e:
        err_msg = str(e)
        logger.error(f"[ERROR] Gemini Chat 호출 실패: {err_msg}")
        if "API_KEY_INVALID" in err_msg or "400" in err_msg or "403" in err_msg:
            return jsonify({"error": "Gemini API 인증에 실패했습니다. .env 파일의 GEMINI_API_KEY가 올바른지 확인해 주세요."}), 401
        elif "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            return jsonify({"error": "응답 시간이 초과되었습니다. 잠시 후 다시 질문해 주세요."}), 504
        return jsonify({"error": f"답변 생성 중 오류가 발생했습니다: {err_msg}"}), 500

    return jsonify({
        "success": True,
        "reply": reply_text
    })

# ==============================================================================
# POST /ask - AI 추천 전 사전 자연어 질문 처리 (항상 한국과 비교 + 시각화 제공)
# ==============================================================================
def calculate_korea_context(df: pd.DataFrame, ref_year: str = None):
    """
    데이터셋에서 한국(Korea, Rep.)의 수치, 순위, 전 세계 평균 및 중앙값 비교 정보를 계산
    """
    if df is None or df.empty:
        return None

    label_col = tools.get_label_column(df)
    korea_label = None
    for cand in ["Korea, Rep.", "Korea", "South Korea", "Republic of Korea", "Korea, Republic of"]:
        if cand in df[label_col].values:
            korea_label = cand
            break

    if not korea_label:
        matches = df[df[label_col].astype(str).str.lower().str.contains("korea")][label_col].values
        if len(matches) > 0:
            korea_label = matches[0]

    year_cols = tools.get_year_columns(df)
    target_year = str(ref_year) if ref_year and str(ref_year) in df.columns else (year_cols[-1] if year_cols else None)

    if not target_year:
        return None

    agg_idx = tools.get_aggregate_indices(df, label_col)
    clean_df = df.drop(index=list(agg_idx), errors="ignore").copy()
    clean_df["_val"] = pd.to_numeric(clean_df[target_year], errors="coerce")
    valid_df = clean_df.dropna(subset=["_val"]).sort_values(by="_val", ascending=False).reset_index(drop=True)

    world_mean = round(float(valid_df["_val"].mean()), 2) if not valid_df.empty else 0.0
    world_median = round(float(valid_df["_val"].median()), 2) if not valid_df.empty else 0.0
    total_valid_countries = len(valid_df)

    korea_row = valid_df[valid_df[label_col] == korea_label] if korea_label else pd.DataFrame()

    if not korea_row.empty:
        korea_rank = int(korea_row.index[0]) + 1
        korea_val = round(float(korea_row["_val"].iloc[0]), 2)
        diff_mean = round(korea_val - world_mean, 2)
        diff_median = round(korea_val - world_median, 2)

        return {
            "found": True,
            "label": korea_label,
            "year": target_year,
            "value": korea_val,
            "rank": korea_rank,
            "total_countries": total_valid_countries,
            "world_mean": world_mean,
            "world_median": world_median,
            "diff_from_mean": diff_mean,
            "diff_from_median": diff_median,
            "summary_sentence": f"한국({korea_label})의 {target_year}년 수치는 {korea_val}%(전체 {total_valid_countries}개국 중 {korea_rank}위)이며, 세계 평균({world_mean}%)보다 {abs(diff_mean):.2f}%p {'높습니다' if diff_mean >= 0 else '낮습니다'}."
        }
    else:
        return {
            "found": False,
            "year": target_year,
            "world_mean": world_mean,
            "world_median": world_median,
            "total_countries": total_valid_countries,
            "summary_sentence": f"한국의 데이터는 {target_year}년 기준 유효 수치를 찾을 수 없으나, 세계 평균은 {world_mean}%, 중앙값은 {world_median}%입니다."
        }

@app.route("/ask", methods=["POST"])
def ask():
    logger.info("[REQUEST] POST /ask")
    if current_dataset["df"] is None:
        return jsonify({"error": "먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일의 GEMINI_API_KEY를 확인해 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    query = req_data.get("query", "").strip()
    if not query:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    df = current_dataset["df"]
    diag = current_dataset["diagnosis"]
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    rec_year = diag.get("recommended_reference_period", "2024")
    meta_info = get_indicator_metadata()

    # 한국 비교 데이터 항상 계산
    korea_info = calculate_korea_context(df, rec_year)

    # Gemini 라우팅 프롬프트
    intent_prompt = (
        "당신은 데이터 분석 질문 라우터입니다.\n"
        "사용자의 질문을 읽고, 아래 12가지 카탈로그 도구 중 가장 적합한 도구 1개와 실행 파라미터(JSON)를 결정하세요.\n\n"
        "[도구 카탈로그]:\n"
        "- top_bottom_n: 상위/하위 랭킹, 가장 높은/낮은 국가 (params: reference_period, n=10, exclude_aggregates=true)\n"
        "- compare_one_vs_all: 특정 국가와 전체 평균 비교 (params: reference_period, target_item='Korea, Rep.', exclude_aggregates=true)\n"
        "- trend_line: 연도별 변화 추이 (params: items=['Korea, Rep.', 'United States', 'World', 'Japan'], exclude_aggregates=false)\n"
        "- group_summary: 대륙/소득별 비교 (params: reference_period, exclude_aggregates=false)\n"
        "- change_rate: 성장폭, 가장 많이 오른 국가 (params: start_period, end_period, exclude_aggregates=true)\n"
        "- distribution: 보급률 구간별 국가 빈도 (params: reference_period, exclude_aggregates=true)\n"
        "- correlation_scatter: 과거와 현재 상관관계 (params: x_col, y_col, exclude_aggregates=true)\n"
        "- describe_numeric: 기초 통계 (params: column)\n\n"
        f"사용자 질문: \"{query}\"\n"
        f"권장 기준연도: \"{rec_year}\"\n\n"
        "규칙:\n"
        "1. 질문 내용에 적합한 1개 도구만 선택하세요.\n"
        f"2. reference_period는 특별한 연도 언급이 없으면 \"{rec_year}\"를 사용하세요.\n"
        "3. 한국과의 비교 질문이거나 전반적 비교 질문인 경우 compare_one_vs_all 또는 top_bottom_n을 선호하세요.\n"
        "4. 순수 JSON 형식만 반환하세요:\n"
        "{\"tool\": \"도구명\", \"params\": { ... }}\n"
    )

    from google import genai
    client = genai.Client(api_key=api_key)

    selected_tool = "compare_one_vs_all"
    tool_params = {"reference_period": rec_year, "target_item": "Korea, Rep.", "exclude_aggregates": True}

    try:
        res_intent = client.models.generate_content(
            model=model_name,
            contents=intent_prompt,
            config={"response_mime_type": "application/json"}
        )
        intent_json = json.loads(res_intent.text.strip())
        tool_candidate = intent_json.get("tool")
        if tool_candidate in TOOL_CATALOG:
            selected_tool = tool_candidate
            tool_params = intent_json.get("params", {})
    except Exception as e:
        logger.warning(f"[ASK] 도구 라우팅 오류, 기본값 compare_one_vs_all 사용: {e}")

    if "reference_period" not in tool_params and selected_tool in ["top_bottom_n", "compare_one_vs_all", "distribution", "group_summary"]:
        tool_params["reference_period"] = rec_year
    if "exclude_aggregates" not in tool_params:
        tool_params["exclude_aggregates"] = True

    try:
        tool_fn = getattr(tools, selected_tool)
        calc_result = tool_fn(df, **tool_params)
    except Exception as e:
        logger.error(f"[ASK] 도구 {selected_tool} 실행 실패: {e}")
        calc_result = tools.compare_one_vs_all(df, reference_period=rec_year, target_item="Korea, Rep.", exclude_aggregates=True)
        selected_tool = "compare_one_vs_all"

    # 모든 막대그래프는 가로가 아닌 세로 막대그래프로 강제하고 제일 우측에 항상 한국 포함
    if calc_result.get("chart_data") and calc_result["chart_data"].get("type") == "bar":
        tools.format_bar_chart_with_korea_on_right(calc_result["chart_data"], df, rec_year)

    # 답변 생성 프롬프트 (말 + 한국 비교 필수)
    answer_prompt = (
        "당신은 중학생부터 일반인까지 누구나 쉽게 이해할 수 있도록 친절하게 설명하는 최고 수준의 데이터 분석 멘토입니다.\n"
        f"사용자가 다음과 같이 질문했습니다:\n\n"
        f"사용자 질문: \"{query}\"\n\n"
        "Python Pandas로 실제 데이터를 정밀 계산한 결과:\n"
        f"- 분석 도구: {selected_tool} ({TOOL_CATALOG.get(selected_tool, '')})\n"
        f"- 기준 연도: {calc_result.get('reference_period')}\n"
        f"- 계산 수치 결과: {json.dumps(calc_result.get('result'), ensure_ascii=False)}\n"
        f"- 한국(Korea, Rep.) 비교 데이터: {json.dumps(korea_info, ensure_ascii=False)}\n"
        f"- 지표명: {meta_info.get('indicator_name')} ({meta_info.get('indicator_code')})\n\n"
        "[답변 작성 필수 지침]:\n"
        "1. 사용자의 질문에 대해 명쾌하고 따뜻한 어조(존댓말)로 답변하세요.\n"
        "2. ★핵심 요구사항: 질문에 대한 답변과 함께, 반드시 한국(Korea, Rep.)의 수치, 순위, 세계 평균과의 격차를 비교하여 상세히 설명하세요! "
        "(예: '우리나라 한국의 2024년 인터넷 보급률은 98.4%로 전 세계 X위에 해당하며, 세계 평균(72.5%)보다 25.9%p 높아 세계 최상위 수준입니다.')\n"
        "3. 제공된 계산 결과에 나온 숫자만 인용하고, 절대 숫자를 거짓으로 꾸며내지 마세요.\n"
        "4. 마크다운 형식(소제목, 글머리 기호, 굵은 글씨 등)을 활용하여 가독성을 극대화하세요.\n"
        "5. 답변 끝부분에 아래의 [시각화 자료 보기] 버튼을 누르면 그래프와 상세 수치를 직접 확인할 수 있음을 친절하게 덧붙이세요."
    )

    try:
        res_answer = client.models.generate_content(
            model=model_name,
            contents=answer_prompt
        )
        answer_text = res_answer.text.strip()
    except Exception as e:
        logger.error(f"[ASK] 답변 생성 오류: {e}")
        answer_text = f"계산 결과:\n\n{korea_info.get('summary_sentence', '') if korea_info else ''}\n\n(답변 텍스트 생성 중 오류: {str(e)})"

    # 전역에 최근 계산 및 대화 기록 보관
    current_dataset["last_run"] = calc_result
    current_dataset["chat_history"].append({"user": query, "ai": answer_text})

    return jsonify({
        "success": True,
        "query": query,
        "answer": answer_text,
        "tool_used": selected_tool,
        "korea_info": korea_info,
        "calculation": calc_result
    })

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    logger.info(f"Starting server on http://127.0.0.1:5000 (debug={debug_mode})")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
