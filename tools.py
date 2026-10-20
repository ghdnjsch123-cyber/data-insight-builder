"""
AI Data Insight Builder - Analysis Tools Catalog (tools.py)
Pandas 기반의 12가지 분석 도구 모듈.
모든 함수는 계산 결과와 함께:
- reference_period (기준 시점)
- rows_used (사용한 행 수)
- rows_excluded (제외한 행 수)
- exclusion_reason (제외 이유)
- columns_used (사용한 열)
- unit (단위)
- caution (해석 시 주의사항)
을 반드시 반환하며, 유연한 인자 처리를 위해 **kwargs를 수용합니다.
"""

import glob
import math
import os
import re
import numpy as np
import pandas as pd

# 집계 행(World, 지역, 소득 그룹 등) 탐지 키워드
AGG_KEYWORDS = [
    "world", "oecd members", "oecd", "euro area", "european union",
    "high income", "low income", "middle income", "upper middle income",
    "lower middle income", "income", "area", "total", "dividend",
    "blend", "ida & ibrd", "small states", "africa eastern", "africa western",
    "latin america", "middle east", "sub-saharan", "south asia",
    "central europe", "caribbean", "countries", "least developed"
]

def clean_for_json(obj):
    """NaN, Inf, NumPy 타입을 안전한 표준 JSON 직렬화 가능 객체로 변환"""
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(v) for v in obj]
    elif isinstance(obj, (float, np.floating)):
        if math.isnan(obj) or math.isinf(obj) or np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, (int, np.integer)):
        return int(obj)
    elif pd.isna(obj):
        return None
    return obj

def get_year_columns(df: pd.DataFrame):
    """DataFrame에서 4자리 연도(1800~2100)로 된 열 목록을 반환"""
    year_cols = []
    for c in df.columns:
        c_str = str(c).strip()
        if re.match(r"^(18|19|20)\d{2}$", c_str):
            year_cols.append(c_str)
    return sorted(year_cols)

def get_label_column(df: pd.DataFrame, specified_col=None):
    """라벨(이름)로 사용할 최적의 텍스트 열을 반환"""
    if specified_col and specified_col in df.columns:
        return specified_col
    for c in df.columns:
        c_lower = str(c).lower()
        if any(k in c_lower for k in ["country", "name", "nation", "label", "item", "title"]):
            return str(c)
    year_cols = set(get_year_columns(df))
    for c in df.columns:
        if str(c) not in year_cols:
            return str(c)
    return str(df.columns[0])

def get_aggregate_indices(df: pd.DataFrame, label_column=None):
    """집계 행 후보의 인덱스 집합을 반환"""
    l_col = get_label_column(df, label_column)
    agg_indices = set()
    for idx, val in df[l_col].dropna().items():
        v_lower = str(val).lower()
        if any(k in v_lower for k in AGG_KEYWORDS):
            agg_indices.add(idx)
    return agg_indices

def find_korea_row(df: pd.DataFrame, label_column=None):
    """DataFrame에서 한국 행을 찾아 (라벨명, 행 시리즈) 반환"""
    if df is None or df.empty:
        return None, None
    l_col = get_label_column(df, label_column)
    for cand in ["Korea, Rep.", "Korea", "South Korea", "Republic of Korea", "Korea, Republic of"]:
        matched = df[df[l_col] == cand]
        if not matched.empty:
            return cand, matched.iloc[0]
    matched = df[df[l_col].astype(str).str.lower().str.contains("korea")]
    if not matched.empty:
        return str(matched.iloc[0][l_col]), matched.iloc[0]
    return None, None

def format_bar_chart_with_korea_on_right(chart_data: dict, df: pd.DataFrame, ref_year: str = None, label_column=None):
    """
    모든 막대그래프(bar chart)의 필수 규칙:
    1. 가로 막대(indexAxis: 'y')를 완전히 제거하여 무조건 세로 막대그래프로 렌더링
    2. 그래프의 제일 우측(맨 마지막 바)에 항상 한국(Korea, Rep.)을 배치 및 강조색 부여
    """
    if not chart_data or chart_data.get("type") != "bar":
        return chart_data

    # 가로 막대 옵션 제거 -> 무조건 세로 막대그래프
    if "options" in chart_data and isinstance(chart_data["options"], dict):
        chart_data["options"].pop("indexAxis", None)

    labels = list(chart_data.get("labels", []))
    datasets = chart_data.get("datasets", [])
    if not datasets or not labels:
        return chart_data

    dataset = datasets[0]
    data = list(dataset.get("data", []))
    raw_bg = dataset.get("backgroundColor", "#3b82f6")
    if isinstance(raw_bg, str):
        bg_colors = [raw_bg] * len(labels)
    else:
        bg_colors = list(raw_bg)
        while len(bg_colors) < len(labels):
            bg_colors.append("#3b82f6")

    # 한국이 이미 labels 목록에 있는지 확인
    korea_idx = -1
    for i, lbl in enumerate(labels):
        if "korea" in str(lbl).lower():
            korea_idx = i
            break

    if korea_idx >= 0:
        # 기존 위치에서 빼서 맨 마지막(제일 우측)으로 이동
        k_lbl = labels.pop(korea_idx)
        k_val = data.pop(korea_idx)
        bg_colors.pop(korea_idx)

        display_lbl = k_lbl if "🇰🇷" in k_lbl else f"{k_lbl} 🇰🇷"
        labels.append(display_lbl)
        data.append(k_val)
        bg_colors.append("#dc2626")  # 제일 우측 한국 강조 (크림슨 레드)
    else:
        # 목록에 없는 경우: df에서 한국 데이터 조회하여 맨 우측에 추가
        k_label, k_row = find_korea_row(df, label_column)
        target_year = str(ref_year) if ref_year and str(ref_year) in df.columns else None
        if not target_year:
            year_cols = get_year_columns(df)
            target_year = year_cols[-1] if year_cols else None

        if k_row is not None and target_year and target_year in k_row:
            try:
                k_val = float(k_row[target_year])
                if not math.isnan(k_val):
                    labels.append(f"{k_label} 🇰🇷")
                    data.append(round(k_val, 2))
                    bg_colors.append("#dc2626")  # 제일 우측 한국 강조
            except Exception:
                pass

    chart_data["labels"] = labels
    dataset["data"] = data
    dataset["backgroundColor"] = bg_colors
    return chart_data

def maybe_enrich_with_metadata(df: pd.DataFrame):
    """Country Code 열이 있는 경우 주변 Metadata_Country CSV에서 Region/IncomeGroup을 자동 병합"""
    if "Region" in df.columns or "Country Code" not in df.columns:
        return df

    meta_files = glob.glob(r"data/**/Metadata_Country*.csv", recursive=True)
    if not meta_files:
        return df

    try:
        meta_df = pd.read_csv(meta_files[0], encoding="utf-8-sig")
        cols_to_merge = [c for c in ["Country Code", "Region", "IncomeGroup"] if c in meta_df.columns]
        if len(cols_to_merge) > 1:
            return pd.merge(df, meta_df[cols_to_merge], on="Country Code", how="left")
    except Exception:
        pass
    return df

# ==============================================================================
# 도구 1: reshape_wide_to_long (연도 열을 행으로 접기)
# ==============================================================================
def reshape_wide_to_long(df: pd.DataFrame, id_vars=None, value_name="value", var_name="year", drop_na=True, **kwargs):
    year_cols = get_year_columns(df)
    if not year_cols:
        raise ValueError("변환할 연도 형식의 열(1960~2025 등)을 찾을 수 없습니다.")

    if id_vars is None:
        id_vars = [str(c) for c in df.columns if str(c) not in year_cols and not str(c).startswith("Unnamed:")]

    original_rows = len(df)
    melted = pd.melt(df, id_vars=id_vars, value_vars=year_cols, var_name=var_name, value_name=value_name)

    excluded_count = 0
    if drop_na:
        before_count = len(melted)
        melted = melted.dropna(subset=[value_name])
        excluded_count = before_count - len(melted)

    preview_records = clean_for_json(melted.head(20).to_dict(orient="records"))

    return clean_for_json({
        "tool": "reshape_wide_to_long",
        "result": {
            "total_melted_rows": len(melted),
            "melted_columns": list(melted.columns),
            "sample_records": preview_records
        },
        "chart_data": None,
        "reference_period": f"{year_cols[0]}~{year_cols[-1]} (전체 연도)",
        "rows_used": original_rows,
        "rows_excluded": excluded_count,
        "exclusion_reason": "변환 후 결측치(NaN) 제거" if drop_na else "없음",
        "columns_used": id_vars + [var_name, value_name],
        "unit": "행 수 (Rows)",
        "caution": "연도가 가로 열에서 세로 행으로 재배치되면서 행 수가 크게 증가했습니다. 그룹화 및 시계열 분석에 최적화된 형태입니다."
    })

# ==============================================================================
# 도구 2: quality_report (품질 진단 보고서)
# ==============================================================================
def quality_report(df: pd.DataFrame, **kwargs):
    total_rows = len(df)
    total_cols = len(df.columns)
    columns_str = [str(c) for c in df.columns]

    missing_summary = {}
    for c in df.columns:
        c_str = str(c)
        n_miss = int(df[c].isna().sum())
        missing_summary[c_str] = {
            "missing_count": n_miss,
            "missing_ratio": round(n_miss / total_rows, 4) if total_rows > 0 else 0.0
        }

    duplicate_rows = int(df.duplicated().sum())
    unnamed_cols = [c for c in columns_str if c.startswith("Unnamed:") or not c.strip()]
    empty_cols = [str(c) for c in df.columns if df[c].isna().all()]

    return clean_for_json({
        "tool": "quality_report",
        "result": {
            "total_rows": total_rows,
            "total_columns": total_cols,
            "duplicate_rows": duplicate_rows,
            "unnamed_columns": unnamed_cols,
            "completely_empty_columns": empty_cols,
            "missing_summary": missing_summary
        },
        "chart_data": None,
        "reference_period": "전체 데이터 세트",
        "rows_used": total_rows,
        "rows_excluded": 0,
        "exclusion_reason": "없음 (품질 검사 목적)",
        "columns_used": columns_str,
        "unit": "품질 진단 지표",
        "caution": "이 보고서는 데이터 정제 전 원본 상태를 나타냅니다. 결측치가 많은 열은 분석 전 필터링이 필요합니다."
    })

# ==============================================================================
# 도구 3: year_coverage (연도별 데이터 충실도 및 권장 기준연도)
# ==============================================================================
def year_coverage(df: pd.DataFrame, **kwargs):
    year_cols = get_year_columns(df)
    if not year_cols:
        raise ValueError("데이터에서 4자리 연도 열을 찾을 수 없습니다.")

    total_rows = len(df)
    coverage_list = []
    chart_labels = []
    chart_values = []

    for yc in year_cols:
        series_num = pd.to_numeric(df[yc], errors="coerce")
        filled = int(series_num.notna().sum())
        ratio = round(filled / total_rows, 4) if total_rows > 0 else 0.0
        coverage_list.append({
            "year": yc,
            "filled_count": filled,
            "total_count": total_rows,
            "ratio": ratio
        })
        chart_labels.append(yc)
        chart_values.append(filled)

    valid = [x for x in coverage_list if x["ratio"] >= 0.5]
    recommended_year = valid[-1]["year"] if valid else coverage_list[-1]["year"]

    chart_data = {
        "type": "bar",
        "labels": chart_labels,
        "datasets": [{
            "label": "유효 데이터 개수",
            "data": chart_values,
            "backgroundColor": ["#3b82f6" if y != recommended_year else "#10b981" for y in chart_labels]
        }]
    }

    return clean_for_json({
        "tool": "year_coverage",
        "result": {
            "year_coverage": coverage_list,
            "recommended_reference_period": recommended_year,
            "earliest_year": year_cols[0],
            "latest_year": year_cols[-1]
        },
        "chart_data": chart_data,
        "reference_period": f"{year_cols[0]}~{year_cols[-1]}",
        "rows_used": total_rows,
        "rows_excluded": 0,
        "exclusion_reason": "없음",
        "columns_used": year_cols,
        "unit": "항목 개수 (개)",
        "caution": f"초록색으로 표시된 '{recommended_year}'년이 데이터 충실도 50% 이상을 만족하는 가장 최신 권장 기준연도입니다."
    })

# ==============================================================================
# 도구 4: detect_aggregates (집계 행 후보 탐지)
# ==============================================================================
def detect_aggregates(df: pd.DataFrame, label_column=None, **kwargs):
    l_col = get_label_column(df, label_column)
    total_rows = len(df)
    agg_candidates = []

    for idx, val in df[l_col].dropna().items():
        v_str = str(val).strip()
        v_lower = v_str.lower()
        matched = [k for k in AGG_KEYWORDS if k in v_lower]
        if matched:
            agg_candidates.append({
                "index": int(idx),
                "label": v_str,
                "matched_keyword": matched[0]
            })

    candidate_count = len(agg_candidates)
    ratio = round(candidate_count / total_rows, 4) if total_rows > 0 else 0.0

    return clean_for_json({
        "tool": "detect_aggregates",
        "result": {
            "label_column": l_col,
            "aggregate_count": candidate_count,
            "aggregate_ratio": ratio,
            "candidates": agg_candidates
        },
        "chart_data": {
            "type": "pie",
            "labels": ["순수 개별 항목", "집계 행 후보"],
            "datasets": [{
                "data": [total_rows - candidate_count, candidate_count],
                "backgroundColor": ["#3b82f6", "#f59e0b"]
            }]
        },
        "reference_period": "전체 데이터 세트",
        "rows_used": total_rows,
        "rows_excluded": 0,
        "exclusion_reason": "없음 (탐지 목적)",
        "columns_used": [l_col],
        "unit": "행 수 (개)",
        "caution": "탐지된 집계 행들은 국가 비교 시 왜곡을 유발하므로, 실제 비교 시 'exclude_aggregates=True'로 제외해야 합니다."
    })

# ==============================================================================
# 도구 5: describe_numeric (기술통계: 개수·평균·중앙값·최소·최대·표준편차)
# ==============================================================================
def describe_numeric(df: pd.DataFrame, column=None, reference_period=None, exclude_aggregates=True, **kwargs):
    target_col = column or reference_period
    if not target_col:
        year_cols = get_year_columns(df)
        target_col = year_cols[-1] if year_cols else None

    if not target_col or target_col not in df.columns:
        raise ValueError(f"분석할 숫자 열을 찾을 수 없습니다: {target_col}")

    working_df = df.copy()
    agg_excluded = 0
    if exclude_aggregates:
        agg_idx = get_aggregate_indices(working_df)
        agg_excluded = len(agg_idx)
        working_df = working_df.drop(index=list(agg_idx), errors="ignore")

    series = pd.to_numeric(working_df[target_col], errors="coerce")
    valid_series = series.dropna()
    nan_excluded = len(series) - len(valid_series)

    total_excluded = agg_excluded + nan_excluded
    rows_used = len(valid_series)

    if rows_used == 0:
        raise ValueError(f"'{target_col}' 열에 유효한 숫자 데이터가 없습니다.")

    stats = {
        "column": target_col,
        "count": int(valid_series.count()),
        "mean": round(float(valid_series.mean()), 4),
        "median": round(float(valid_series.median()), 4),
        "std": round(float(valid_series.std()), 4) if len(valid_series) > 1 else 0.0,
        "min": round(float(valid_series.min()), 4),
        "max": round(float(valid_series.max()), 4),
        "q25": round(float(valid_series.quantile(0.25)), 4),
        "q75": round(float(valid_series.quantile(0.75)), 4)
    }

    exclusion_reasons = []
    if agg_excluded > 0:
        exclusion_reasons.append(f"집계 행 {agg_excluded}개 제외")
    if nan_excluded > 0:
        exclusion_reasons.append(f"결측치 {nan_excluded}개 제외")

    return clean_for_json({
        "tool": "describe_numeric",
        "result": stats,
        "chart_data": {
            "type": "bar",
            "labels": ["최소값", "25%", "중앙값(50%)", "평균값", "75%", "최대값"],
            "datasets": [{
                "label": f"{target_col} 기술통계",
                "data": [stats["min"], stats["q25"], stats["median"], stats["mean"], stats["q75"], stats["max"]],
                "backgroundColor": ["#6b7280", "#93c5fd", "#3b82f6", "#10b981", "#93c5fd", "#6b7280"]
            }]
        },
        "reference_period": str(target_col),
        "rows_used": rows_used,
        "rows_excluded": total_excluded,
        "exclusion_reason": ", ".join(exclusion_reasons) if exclusion_reasons else "없음",
        "columns_used": [target_col],
        "unit": "수치 단위 (예: %)",
        "caution": "평균값은 극단값(아웃라이어)에 영향을 많이 받으므로 중앙값과 함께 비교하여 데이터의 치우침을 확인하세요."
    })

# ==============================================================================
# 도구 6: trend_line (선택 항목들의 연도별 추이 선 차트)
# ==============================================================================
def trend_line(df: pd.DataFrame, items=None, label_column=None, start_year=None, end_year=None, exclude_aggregates=False, **kwargs):
    year_cols = get_year_columns(df)
    if not year_cols:
        raise ValueError("추이를 분석할 연도 열을 찾을 수 없습니다.")

    l_col = get_label_column(df, label_column)
    working_df = df.copy()

    if start_year and str(start_year) in year_cols:
        year_cols = [y for y in year_cols if y >= str(start_year)]
    if end_year and str(end_year) in year_cols:
        year_cols = [y for y in year_cols if y <= str(end_year)]

    if not items:
        default_candidates = ["Korea, Rep.", "United States", "China", "World"]
        available_labels = working_df[l_col].dropna().tolist()
        items = [c for c in default_candidates if c in available_labels]
        if not items:
            items = available_labels[:4]

    sub_df = working_df[working_df[l_col].isin(items)].copy()
    if sub_df.empty:
        raise ValueError(f"지정한 항목({items})을 데이터에서 찾을 수 없습니다.")

    datasets = []
    color_palette = ["#ef4444", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6"]

    records_summary = {}
    for i, (_, row) in enumerate(sub_df.iterrows()):
        label_val = str(row[l_col])
        series_vals = [float(row[y]) if pd.notna(row[y]) and str(row[y]).strip() != "" else None for y in year_cols]
        records_summary[label_val] = {y: v for y, v in zip(year_cols, series_vals) if v is not None}
        color = color_palette[i % len(color_palette)]
        datasets.append({
            "label": label_val,
            "data": series_vals,
            "borderColor": color,
            "backgroundColor": color,
            "fill": False,
            "tension": 0.2
        })

    rows_used = len(sub_df)
    rows_excluded = len(df) - rows_used

    return clean_for_json({
        "tool": "trend_line",
        "result": {
            "selected_items": items,
            "years": year_cols,
            "series": records_summary
        },
        "chart_data": {
            "type": "line",
            "labels": year_cols,
            "datasets": datasets
        },
        "reference_period": f"{year_cols[0]}~{year_cols[-1]}",
        "rows_used": rows_used,
        "rows_excluded": rows_excluded,
        "exclusion_reason": "분석 대상으로 선택되지 않은 나머지 항목 제외",
        "columns_used": [l_col] + year_cols,
        "unit": "수치 (예: %)",
        "caution": "연도별 결측치가 있는 구간은 선이 끊기거나 보간될 수 있습니다. 1990년대 이전 데이터는 대부분 0 또는 빈칸입니다."
    })

# ==============================================================================
# 도구 7: top_bottom_n (기준연도 기준 상위·하위 N개 수평 막대)
# ==============================================================================
def top_bottom_n(df: pd.DataFrame, reference_period: str, value_column=None, label_column=None, n=10, exclude_aggregates=True, **kwargs):
    if not reference_period:
        raise ValueError("top_bottom_n 도구는 기준 시점(reference_period)이 필수 파라미터입니다.")

    val_col = value_column or str(reference_period)
    if val_col not in df.columns:
        raise ValueError(f"지정한 기준 시점 열이 데이터에 없습니다: {val_col}")

    l_col = get_label_column(df, label_column)
    working_df = df.copy()

    agg_excluded = 0
    if exclude_aggregates:
        agg_idx = get_aggregate_indices(working_df, l_col)
        agg_excluded = len(agg_idx)
        working_df = working_df.drop(index=list(agg_idx), errors="ignore")

    working_df["_numeric_val"] = pd.to_numeric(working_df[val_col], errors="coerce")
    before_drop = len(working_df)
    valid_df = working_df.dropna(subset=["_numeric_val"]).copy()
    nan_excluded = before_drop - len(valid_df)

    if valid_df.empty:
        raise ValueError(f"'{val_col}' 기준 시점에 유효한 데이터가 1건도 없습니다.")

    sorted_df = valid_df.sort_values(by="_numeric_val", ascending=False)
    n_val = min(int(n), len(sorted_df))

    top_n_df = sorted_df.head(n_val)
    bottom_n_df = sorted_df.tail(n_val).iloc[::-1]

    top_items = [{"rank": i + 1, "label": str(r[l_col]), "value": round(float(r["_numeric_val"]), 4)} for i, (_, r) in enumerate(top_n_df.iterrows())]
    bottom_items = [{"rank": len(sorted_df) - i, "label": str(r[l_col]), "value": round(float(r["_numeric_val"]), 4)} for i, (_, r) in enumerate(bottom_n_df.iterrows())]

    chart_data = {
        "type": "bar",
        "labels": [item["label"] for item in top_items],
        "datasets": [{
            "label": f"{reference_period}년 상위 {n_val}개",
            "data": [item["value"] for item in top_items],
            "backgroundColor": "#3b82f6"
        }]
    }
    # 가로 막대 제거(세로 막대그래프) 및 제일 우측에 항상 한국 포함
    chart_data = format_bar_chart_with_korea_on_right(chart_data, df, reference_period, label_column)

    exclusion_reasons = []
    if agg_excluded > 0:
        exclusion_reasons.append(f"집계 행 {agg_excluded}개 제외")
    if nan_excluded > 0:
        exclusion_reasons.append(f"결측치 {nan_excluded}개 제외")

    return clean_for_json({
        "tool": "top_bottom_n",
        "result": {
            "reference_period": reference_period,
            "total_ranked_count": len(sorted_df),
            "top_n": top_items,
            "bottom_n": bottom_items
        },
        "chart_data": chart_data,
        "reference_period": str(reference_period),
        "rows_used": len(valid_df),
        "rows_excluded": agg_excluded + nan_excluded,
        "exclusion_reason": ", ".join(exclusion_reasons) if exclusion_reasons else "없음",
        "columns_used": [l_col, val_col],
        "unit": "수치 (예: %)",
        "caution": f"{reference_period}년에 유효 데이터가 있는 국가만 순위를 매겼습니다. 상위권에 100%가 나타나는 것은 표본 한계 및 반올림(천장 효과)일 수 있습니다."
    })

# ==============================================================================
# 도구 8: group_summary (그룹별 평균·합계·개수 막대)
# ==============================================================================
def group_summary(df: pd.DataFrame, reference_period: str, group_column=None, value_column=None, agg_func="mean", exclude_aggregates=True, **kwargs):
    if not reference_period:
        raise ValueError("group_summary 도구는 기준 시점(reference_period)이 필수 파라미터입니다.")

    val_col = value_column or str(reference_period)
    if val_col not in df.columns:
        raise ValueError(f"지정한 기준 시점 열이 데이터에 없습니다: {val_col}")

    working_df = maybe_enrich_with_metadata(df.copy())

    grp_col = group_column
    if not grp_col or grp_col not in working_df.columns:
        for candidate in ["Region", "IncomeGroup", "Indicator Name"]:
            if candidate in working_df.columns:
                grp_col = candidate
                break

    if not grp_col or grp_col not in working_df.columns:
        raise ValueError("그룹화할 범주형 열(Region, IncomeGroup 등)을 찾을 수 없습니다.")

    l_col = get_label_column(working_df)
    agg_excluded = 0
    if exclude_aggregates:
        agg_idx = get_aggregate_indices(working_df, l_col)
        agg_excluded = len(agg_idx)
        working_df = working_df.drop(index=list(agg_idx), errors="ignore")

    working_df["_numeric_val"] = pd.to_numeric(working_df[val_col], errors="coerce")
    valid_df = working_df.dropna(subset=[grp_col, "_numeric_val"]).copy()
    nan_excluded = len(working_df) - len(valid_df)

    if valid_df.empty:
        raise ValueError(f"'{grp_col}' 그룹과 '{val_col}' 값의 유효 데이터가 없습니다.")

    grouped = valid_df.groupby(grp_col)["_numeric_val"].agg(
        mean="mean",
        sum="sum",
        count="count",
        median="median"
    ).reset_index()

    sort_key = "mean" if agg_func == "mean" else ("sum" if agg_func == "sum" else "count")
    grouped = grouped.sort_values(by=sort_key, ascending=False)

    summary_list = []
    labels = []
    chart_vals = []
    for _, r in grouped.iterrows():
        g_name = str(r[grp_col])
        labels.append(g_name)
        val_to_plot = round(float(r[sort_key]), 4)
        chart_vals.append(val_to_plot)
        summary_list.append({
            "group": g_name,
            "mean": round(float(r["mean"]), 4),
            "median": round(float(r["median"]), 4),
            "sum": round(float(r["sum"]), 4),
            "count": int(r["count"])
        })

    chart_data = {
        "type": "bar",
        "labels": labels,
        "datasets": [{
            "label": f"{reference_period}년 그룹별 {agg_func.upper()} ({grp_col})",
            "data": chart_vals,
            "backgroundColor": "#3b82f6"
        }]
    }
    # 가로 막대 제거(세로 막대그래프) 및 제일 우측에 항상 한국 포함
    chart_data = format_bar_chart_with_korea_on_right(chart_data, df, reference_period, label_column)

    exclusion_reasons = []
    if agg_excluded > 0:
        exclusion_reasons.append(f"집계 행 {agg_excluded}개 제외")
    if nan_excluded > 0:
        exclusion_reasons.append(f"그룹 미분류/결측치 {nan_excluded}개 제외")

    return clean_for_json({
        "tool": "group_summary",
        "result": {
            "group_column": grp_col,
            "aggregation": agg_func,
            "summary": summary_list
        },
        "chart_data": chart_data,
        "reference_period": str(reference_period),
        "rows_used": len(valid_df),
        "rows_excluded": agg_excluded + nan_excluded,
        "exclusion_reason": ", ".join(exclusion_reasons) if exclusion_reasons else "없음",
        "columns_used": [grp_col, val_col],
        "unit": "수치 (예: %)",
        "caution": "그룹 내 속한 국가들의 단순 산술평균입니다. 인구 규모를 가중치로 둔 인구 가중 평균이 아니라는 점에 주의하세요."
    })

# ==============================================================================
# 도구 9: change_rate (두 시점 사이 변화량·변화율 막대)
# ==============================================================================
def change_rate(df: pd.DataFrame, reference_period: str, base_period: str = None, label_column=None, n=10, exclude_aggregates=True, **kwargs):
    if not reference_period:
        raise ValueError("change_rate 도구는 기준 시점(reference_period)이 필수 파라미터입니다.")

    ref_col = str(reference_period)
    if ref_col not in df.columns:
        raise ValueError(f"기준 시점 열이 없습니다: {ref_col}")

    year_cols = get_year_columns(df)
    base_col = str(base_period) if base_period else None

    if not base_col or base_col not in df.columns:
        if ref_col in year_cols:
            ref_int = int(ref_col)
            candidate_10 = str(ref_int - 10)
            candidate_5 = str(ref_int - 5)
            if candidate_10 in year_cols:
                base_col = candidate_10
            elif candidate_5 in year_cols:
                base_col = candidate_5
            else:
                earlier_years = [y for y in year_cols if y < ref_col]
                base_col = earlier_years[0] if earlier_years else year_cols[0]
        else:
            raise ValueError("비교 대상 시점(base_period)을 지정해야 합니다.")

    l_col = get_label_column(df, label_column)
    working_df = df.copy()

    agg_excluded = 0
    if exclude_aggregates:
        agg_idx = get_aggregate_indices(working_df, l_col)
        agg_excluded = len(agg_idx)
        working_df = working_df.drop(index=list(agg_idx), errors="ignore")

    working_df["_val_ref"] = pd.to_numeric(working_df[ref_col], errors="coerce")
    working_df["_val_base"] = pd.to_numeric(working_df[base_col], errors="coerce")

    before_drop = len(working_df)
    valid_df = working_df.dropna(subset=["_val_ref", "_val_base"]).copy()
    nan_excluded = before_drop - len(valid_df)

    if valid_df.empty:
        raise ValueError(f"'{base_col}'과 '{ref_col}' 두 시점 모두에 값이 있는 행이 없습니다.")

    valid_df["_delta"] = valid_df["_val_ref"] - valid_df["_val_base"]
    valid_df["_pct_change"] = np.where(
        valid_df["_val_base"] > 0,
        ((valid_df["_val_ref"] - valid_df["_val_base"]) / valid_df["_val_base"]) * 100.0,
        np.nan
    )

    sorted_df = valid_df.sort_values(by="_delta", ascending=False)
    n_val = min(int(n), len(sorted_df))
    top_growth = sorted_df.head(n_val)

    items_list = []
    labels = []
    chart_vals = []
    for i, (_, r) in enumerate(top_growth.iterrows()):
        item_name = str(r[l_col])
        delta_val = round(float(r["_delta"]), 4)
        pct_val = round(float(r["_pct_change"]), 2) if pd.notna(r["_pct_change"]) else None
        labels.append(item_name)
        chart_vals.append(delta_val)
        items_list.append({
            "rank": i + 1,
            "label": item_name,
            "base_value": round(float(r["_val_base"]), 4),
            "ref_value": round(float(r["_val_ref"]), 4),
            "delta": delta_val,
            "pct_change": pct_val
        })

    # 한국이 목록에 없으면 한국의 변화량 계산하여 추가
    korea_in_labels = any("korea" in str(l).lower() for l in labels)
    if not korea_in_labels:
        k_lbl, k_row = find_korea_row(working_df, label_column)
        if k_row is not None:
            try:
                k_base = float(k_row[base_col])
                k_ref = float(k_row[ref_col])
                if not (math.isnan(k_base) or math.isnan(k_ref)):
                    k_delta = round(k_ref - k_base, 2)
                    labels.append(f"{k_lbl} 🇰🇷")
                    chart_vals.append(k_delta)
            except Exception:
                pass

    chart_data = {
        "type": "bar",
        "labels": labels,
        "datasets": [{
            "label": f"{base_col}년 대비 {ref_col}년 증가량 (%p)",
            "data": chart_vals,
            "backgroundColor": "#10b981"
        }]
    }
    # 가로 막대 제거(세로 막대그래프) 및 제일 우측에 항상 한국 포함
    chart_data = format_bar_chart_with_korea_on_right(chart_data, df, ref_col, label_column)

    exclusion_reasons = []
    if agg_excluded > 0:
        exclusion_reasons.append(f"집계 행 {agg_excluded}개 제외")
    if nan_excluded > 0:
        exclusion_reasons.append(f"두 시점 중 결측치 {nan_excluded}개 제외")

    return clean_for_json({
        "tool": "change_rate",
        "result": {
            "base_period": base_col,
            "reference_period": ref_col,
            "top_growers": items_list
        },
        "chart_data": chart_data,
        "reference_period": f"{base_col} vs {ref_col}",
        "rows_used": len(valid_df),
        "rows_excluded": agg_excluded + nan_excluded,
        "exclusion_reason": ", ".join(exclusion_reasons) if exclusion_reasons else "없음",
        "columns_used": [l_col, base_col, ref_col],
        "unit": "%p (퍼센트포인트 증가량)",
        "caution": "초기값(기준 시점)이 매우 낮았던 국가는 작은 증가에도 백분율 변화율(%)이 폭발적으로 높게 나타날 수 있으므로 절대 증가량(%p)과 함께 보아야 합니다."
    })

# ==============================================================================
# 도구 10: distribution (구간별 분포 히스토그램)
# ==============================================================================
def distribution(df: pd.DataFrame, reference_period: str, value_column=None, bins=5, exclude_aggregates=True, **kwargs):
    if not reference_period:
        raise ValueError("distribution 도구는 기준 시점(reference_period)이 필수 파라미터입니다.")

    val_col = value_column or str(reference_period)
    if val_col not in df.columns:
        raise ValueError(f"기준 시점 열이 없습니다: {val_col}")

    l_col = get_label_column(df)
    working_df = df.copy()

    agg_excluded = 0
    if exclude_aggregates:
        agg_idx = get_aggregate_indices(working_df, l_col)
        agg_excluded = len(agg_idx)
        working_df = working_df.drop(index=list(agg_idx), errors="ignore")

    working_df["_numeric_val"] = pd.to_numeric(working_df[val_col], errors="coerce")
    before_drop = len(working_df)
    valid_df = working_df.dropna(subset=["_numeric_val"]).copy()
    nan_excluded = before_drop - len(valid_df)

    if valid_df.empty:
        raise ValueError(f"'{val_col}' 기준 시점에 유효 데이터가 없습니다.")

    num_bins = max(3, min(int(bins), 20))
    cat_series, bin_edges = pd.cut(valid_df["_numeric_val"], bins=num_bins, retbins=True)
    counts = cat_series.value_counts(sort=False)

    total_valid = len(valid_df)
    bin_results = []
    labels = []
    data_counts = []

    for interval, count in counts.items():
        left = round(float(interval.left), 2)
        right = round(float(interval.right), 2)
        label_str = f"{left}~{right}%"
        labels.append(label_str)
        data_counts.append(int(count))

        sample_names = valid_df[cat_series == interval][l_col].head(3).tolist()

        bin_results.append({
            "interval": label_str,
            "min_val": left,
            "max_val": right,
            "count": int(count),
            "ratio": round(int(count) / total_valid, 4),
            "sample_items": sample_names
        })

    chart_data = {
        "type": "bar",
        "labels": labels,
        "datasets": [{
            "label": f"{reference_period}년 구간별 국가 분포 (개)",
            "data": data_counts,
            "backgroundColor": "#6366f1"
        }]
    }

    exclusion_reasons = []
    if agg_excluded > 0:
        exclusion_reasons.append(f"집계 행 {agg_excluded}개 제외")
    if nan_excluded > 0:
        exclusion_reasons.append(f"결측치 {nan_excluded}개 제외")

    return clean_for_json({
        "tool": "distribution",
        "result": {
            "bins_count": num_bins,
            "distribution": bin_results
        },
        "chart_data": chart_data,
        "reference_period": str(reference_period),
        "rows_used": total_valid,
        "rows_excluded": agg_excluded + nan_excluded,
        "exclusion_reason": ", ".join(exclusion_reasons) if exclusion_reasons else "없음",
        "columns_used": [val_col],
        "unit": "항목 수 (개)",
        "caution": "분포의 모양(정규분포형, 좌/우 치우침, 양극화)을 통해 데이터의 전반적인 구조를 파악할 수 있습니다."
    })

# ==============================================================================
# 도구 11: correlation_scatter (두 시점/지표 간 상관계수 및 산점도)
# ==============================================================================
def correlation_scatter(df: pd.DataFrame, reference_period: str, x_column: str = None, y_column: str = None, label_column=None, exclude_aggregates=True, **kwargs):
    if not reference_period:
        raise ValueError("correlation_scatter 도구는 기준 시점(reference_period)이 필수 파라미터입니다.")

    year_cols = get_year_columns(df)
    y_col = y_column or str(reference_period)
    x_col = x_column

    if not x_col or x_col not in df.columns:
        if y_col in year_cols:
            target_10 = str(int(y_col) - 10)
            if target_10 in year_cols:
                x_col = target_10
            else:
                earlier = [y for y in year_cols if y < y_col]
                x_col = earlier[0] if earlier else year_cols[0]
        else:
            raise ValueError("비교할 X축 숫자 열을 지정해야 합니다.")

    l_col = get_label_column(df, label_column)
    working_df = df.copy()

    agg_excluded = 0
    if exclude_aggregates:
        agg_idx = get_aggregate_indices(working_df, l_col)
        agg_excluded = len(agg_idx)
        working_df = working_df.drop(index=list(agg_idx), errors="ignore")

    working_df["_x"] = pd.to_numeric(working_df[x_col], errors="coerce")
    working_df["_y"] = pd.to_numeric(working_df[y_col], errors="coerce")

    before_drop = len(working_df)
    valid_df = working_df.dropna(subset=["_x", "_y"]).copy()
    nan_excluded = before_drop - len(valid_df)

    if len(valid_df) < 3:
        raise ValueError("상관계수를 계산하기 위한 유효 데이터 쌍(최소 3개)이 부족합니다.")

    corr_coef = float(valid_df["_x"].corr(valid_df["_y"]))

    points = []
    for _, r in valid_df.iterrows():
        points.append({
            "x": round(float(r["_x"]), 4),
            "y": round(float(r["_y"]), 4),
            "label": str(r[l_col])
        })

    chart_data = {
        "type": "scatter",
        "datasets": [{
            "label": f"{x_col} vs {y_col} 산점도",
            "data": points,
            "backgroundColor": "#3b82f6"
        }]
    }

    exclusion_reasons = []
    if agg_excluded > 0:
        exclusion_reasons.append(f"집계 행 {agg_excluded}개 제외")
    if nan_excluded > 0:
        exclusion_reasons.append(f"X 또는 Y 결측치 {nan_excluded}개 제외")

    strength = "강한 양의 상관관계" if corr_coef >= 0.7 else ("중간 정도의 양의 상관관계" if corr_coef >= 0.4 else "약한 상관관계")

    return clean_for_json({
        "tool": "correlation_scatter",
        "result": {
            "x_column": x_col,
            "y_column": y_col,
            "correlation_coefficient": round(corr_coef, 4),
            "relationship_summary": strength,
            "points_count": len(points)
        },
        "chart_data": chart_data,
        "reference_period": f"{x_col} & {y_col}",
        "rows_used": len(valid_df),
        "rows_excluded": agg_excluded + nan_excluded,
        "exclusion_reason": ", ".join(exclusion_reasons) if exclusion_reasons else "없음",
        "columns_used": [l_col, x_col, y_col],
        "unit": "피어슨 상관계수 (r)",
        "caution": "★ 중요: 상관관계는 결코 인과관계가 아닙니다. 두 변수가 같은 방향으로 움직인다고 해서 한쪽이 다른 쪽의 원인이 되지는 않습니다."
    })

# ==============================================================================
# 도구 12: compare_one_vs_all (특정 항목 vs 전체 평균·중앙값 강조 막대)
# ==============================================================================
def compare_one_vs_all(df: pd.DataFrame, reference_period: str, target_item: str = None, value_column=None, label_column=None, exclude_aggregates=True, **kwargs):
    if not reference_period:
        raise ValueError("compare_one_vs_all 도구는 기준 시점(reference_period)이 필수 파라미터입니다.")

    val_col = value_column or str(reference_period)
    if val_col not in df.columns:
        raise ValueError(f"기준 시점 열이 없습니다: {val_col}")

    l_col = get_label_column(df, label_column)
    working_df = df.copy()

    agg_excluded = 0
    if exclude_aggregates:
        agg_idx = get_aggregate_indices(working_df, l_col)
        agg_excluded = len(agg_idx)
        working_df = working_df.drop(index=list(agg_idx), errors="ignore")

    working_df["_numeric_val"] = pd.to_numeric(working_df[val_col], errors="coerce")
    before_drop = len(working_df)
    valid_df = working_df.dropna(subset=["_numeric_val"]).copy()
    nan_excluded = before_drop - len(valid_df)

    if valid_df.empty:
        raise ValueError(f"'{val_col}' 기준 시점에 유효 데이터가 없습니다.")

    target = target_item
    if not target or target not in valid_df[l_col].values:
        for cand in ["Korea, Rep.", "United States", "Japan", "Germany"]:
            if cand in valid_df[l_col].values:
                target = cand
                break
        if not target:
            target = str(valid_df[l_col].iloc[0])

    target_row = valid_df[valid_df[l_col] == target]
    if target_row.empty:
        raise ValueError(f"비교할 대상 항목 '{target}'을(를) 데이터에서 찾을 수 없습니다.")

    target_val = float(target_row["_numeric_val"].iloc[0])
    mean_val = float(valid_df["_numeric_val"].mean())
    median_val = float(valid_df["_numeric_val"].median())
    min_val = float(valid_df["_numeric_val"].min())
    max_val = float(valid_df["_numeric_val"].max())

    sorted_df = valid_df.sort_values(by="_numeric_val", ascending=False).reset_index(drop=True)
    rank = int(sorted_df[sorted_df[l_col] == target].index[0]) + 1
    total_valid = len(sorted_df)
    percentile = round(((total_valid - rank + 1) / total_valid) * 100.0, 2)

    diff_from_mean = round(target_val - mean_val, 4)
    diff_from_median = round(target_val - median_val, 4)

    # 한국 또는 대상 항목이 제일 우측에 오도록 배치
    is_korea = "korea" in str(target).lower()
    if is_korea:
        labels = ["최솟값", "전체 중앙값", "전체 평균", "최댓값", f"{target} 🇰🇷"]
        data_vals = [round(min_val, 2), round(median_val, 2), round(mean_val, 2), round(max_val, 2), round(target_val, 2)]
        bg_colors = ["#64748b", "#10b981", "#3b82f6", "#94a3b8", "#dc2626"]
    else:
        labels = ["최솟값", "전체 중앙값", "전체 평균", f"{target} (비교대상)"]
        data_vals = [round(min_val, 2), round(median_val, 2), round(mean_val, 2), round(target_val, 2)]
        bg_colors = ["#64748b", "#10b981", "#3b82f6", "#f59e0b"]

    chart_data = {
        "type": "bar",
        "labels": labels,
        "datasets": [{
            "label": f"{reference_period}년 비교 분석",
            "data": data_vals,
            "backgroundColor": bg_colors
        }]
    }
    # 가로 막대 제거(세로 막대그래프) 및 제일 우측에 항상 한국 포함
    chart_data = format_bar_chart_with_korea_on_right(chart_data, df, reference_period, label_column)

    exclusion_reasons = []
    if agg_excluded > 0:
        exclusion_reasons.append(f"집계 행 {agg_excluded}개 제외")
    if nan_excluded > 0:
        exclusion_reasons.append(f"결측치 {nan_excluded}개 제외")

    return clean_for_json({
        "tool": "compare_one_vs_all",
        "result": {
            "target_item": target,
            "target_value": round(target_val, 4),
            "overall_mean": round(mean_val, 4),
            "overall_median": round(median_val, 4),
            "overall_min": round(min_val, 4),
            "overall_max": round(max_val, 4),
            "diff_from_mean": diff_from_mean,
            "diff_from_median": diff_from_median,
            "rank": rank,
            "total_count": total_valid,
            "percentile": percentile
        },
        "chart_data": chart_data,
        "reference_period": str(reference_period),
        "rows_used": total_valid,
        "rows_excluded": agg_excluded + nan_excluded,
        "exclusion_reason": ", ".join(exclusion_reasons) if exclusion_reasons else "없음",
        "columns_used": [l_col, val_col],
        "unit": "수치 (예: %)",
        "caution": f"{target}의 위치를 파악하기 위한 비교입니다. 평균보다 {abs(diff_from_mean):.2f}%p {'높음' if diff_from_mean >= 0 else '낮음'} 상태입니다."
    })
