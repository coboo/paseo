"""ETF 对标的指数的长期跟踪差检验。

检验逻辑（对应设计文档"同指数选基规则"第 3 条：净值对全收益指数的长期跟踪差最小）：
- A 股 ETF：前复权市价 vs 标的指数（价格指数），重叠期对比年化收益差与日收益偏差；
- QDII：基金净值 vs 海外指数(本币)×汇率 的干净价格（信号-执行分离纪律）；
- 黄金：518880 前复权 vs AU9999 晚盘基准价；
- 债券：511260 前复权 vs 中债国债财富指数(7-10Y)（即拼接所用指数）；
- 511360 短融：无公开指数日线，仅报告自身年化；159545 的标的就是其净值兜底序列，跳过。

输出：终端表格 + reports/tracking_check.md

用法：PYTHONPATH=src uv run python -m data_module.tracking_check
"""
import pandas as pd

from .storage import PROJECT_ROOT, read_raw

TRADING_DAYS = 252


def _ret_stats(df: pd.DataFrame, col: str) -> pd.Series:
    return df.set_index("date")[col].sort_index().pct_change()


def _annualized(close: pd.Series) -> float:
    """由价格序列算年化收益。"""
    close = close.dropna().sort_index()
    if len(close) < 2:
        return float("nan")
    days = (close.index[-1] - close.index[0]).days
    if days <= 0:
        return float("nan")
    return (close.iloc[-1] / close.iloc[0]) ** (365.25 / days) - 1.0


def track_pair(etf_close: pd.Series, bench_close: pd.Series) -> dict:
    """重叠期跟踪差：年化收益差 + 日收益偏差统计。输入为 date-indexed 价格序列。"""
    m = pd.concat([etf_close.rename("etf"), bench_close.rename("bench")], axis=1).dropna()
    if len(m) < 30:
        return {"overlap_days": len(m)}
    r_etf = m["etf"].pct_change().dropna()
    r_bench = m["bench"].pct_change().dropna()
    diff = r_etf - r_bench
    return {
        "overlap_days": len(m),
        "start": m.index[0],
        "end": m.index[-1],
        "ann_etf": _annualized(m["etf"]),
        "ann_bench": _annualized(m["bench"]),
        "ann_diff": _annualized(m["etf"]) - _annualized(m["bench"]),
        "daily_diff_mean_bp": diff.mean() * 1e4,   # 日均偏差（基点）
        "daily_diff_std_bp": diff.std() * 1e4,     # 跟踪误差（基点/日）
    }


def _fx_series(name: str) -> pd.Series:
    return read_raw(f"fx/{name}.parquet").set_index("date")["close"].sort_index()


def _clean_price(index_file: str, fx_name: str | None) -> pd.Series:
    """QDII 干净价格：海外指数(本币) × 汇率；指数缺失日用前值，汇率前向填充。"""
    idx = read_raw(f"index_global/{index_file.removesuffix('.parquet')}.parquet") \
        .set_index("date")["close"].sort_index()
    if fx_name is None:
        return idx
    fx = _fx_series(fx_name)
    cal = idx.index.union(fx.index).sort_values()
    idx = idx.reindex(cal).ffill()
    fx = fx.reindex(cal).ffill()
    return (idx * fx).dropna()


def main() -> int:
    rows = []

    # ---- A 股 ETF vs 标的指数（前复权市价 vs 价格指数）
    a_pairs = [
        ("510310", "沪深300ETF", "index_daily/index_000300.parquet"),
        ("510580", "中证500ETF", "index_daily/index_000905.parquet"),
        ("159633", "中证1000ETF", "index_daily/index_000852.parquet"),
        ("159915", "创业板ETF", "index_daily/index_399006.parquet"),
        ("563020", "红利低波ETF", "index_daily/index_H30269.parquet"),
    ]
    for code, name, idx_file in a_pairs:
        etf = read_raw(f"etf_daily/etf_qfq_{code}.parquet").set_index("date")["close"]
        bench = read_raw(idx_file).set_index("date")["close"]
        st = track_pair(etf, bench)
        st.update(code=code, name=name, bench=idx_file.split("_")[-1].split(".")[0],
                  method="ETF前复权 vs 指数")
        rows.append(st)

    # ---- QDII：基金净值 vs 海外指数×汇率（信号-执行分离）
    qdii = [
        ("513500", "标普500ETF", "spx_inx.parquet", "usdcny"),
        ("513100", "纳指ETF", "ndx_ndx.parquet", "usdcny"),
        ("513880", "日经225ETF", "n225_n225.parquet", "jpycny"),
    ]
    for code, name, idx_file, fx in qdii:
        # 用累计净值：单位净值在份额拆分日跳变（如 513100 于 2022-01-13 拆分），累计净值连续
        nav = read_raw(f"etf_nav/nav_{code}.parquet").set_index("date")["acc_nav"]
        clean = _clean_price(idx_file, fx)
        st = track_pair(nav, clean)
        st.update(code=code, name=name, bench=f"{idx_file.split('.')[0]}×{fx}",
                  method="累计净值 vs 指数×汇率")
        rows.append(st)

    # ---- 黄金：518880 前复权 vs AU9999 晚盘基准价
    try:
        etf = read_raw("etf_daily/etf_qfq_518880.parquet").set_index("date")["close"]
        au = read_raw("gold/au9999_sge.parquet").set_index("date")["bench_pm"]
        st = track_pair(etf, au)
        st.update(code="518880", name="黄金ETF", bench="AU9999晚盘价",
                  method="ETF前复权 vs 上金所基准价")
        rows.append(st)
    except FileNotFoundError:
        pass

    # ---- 债券：511260 前复权 vs 中债国债财富指数(7-10Y)
    try:
        etf = read_raw("etf_daily/etf_qfq_511260.parquet").set_index("date")["close"]
        bond = read_raw("bond_index/cbond_treasury_wealth_7_10y.parquet").set_index("date")["close"]
        st = track_pair(etf, bond)
        st.update(code="511260", name="十年国债ETF", bench="中债国债财富7-10Y",
                  method="ETF前复权 vs 财富指数")
        rows.append(st)
    except FileNotFoundError:
        pass

    # ---- 输出
    lines = []
    header = f"{'代码':<7}{'名称':<10}{'重叠天数':>7} {'区间':<24}{'ETF年化':>8}{'基准年化':>8}{'年化差':>8}{'日均偏差bp':>10}{'日TE(bp)':>9}  方法"
    lines.append(header)
    lines.append("-" * len(header) * 2)
    for st in rows:
        if st.get("overlap_days", 0) < 30:
            line = f"{st['code']:<7}{st['name']:<10} 重叠数据不足（{st.get('overlap_days', 0)} 天），跳过"
        else:
            line = (f"{st['code']:<7}{st['name']:<10}{st['overlap_days']:>7} "
                    f"{st['start']:%Y-%m-%d}~{st['end']:%Y-%m-%d} "
                    f"{st['ann_etf']:>7.2%} {st['ann_bench']:>7.2%} {st['ann_diff']:>+7.2%}"
                    f"{st['daily_diff_mean_bp']:>10.2f}{st['daily_diff_std_bp']:>9.2f}  {st['method']}")
        lines.append(line)
    lines.append("")
    lines.append("说明：年化差 = ETF 年化 − 基准年化。A股基准为价格指数（不含股息），ETF 年化略高于指数为正常"
                 "（股息再投资）；QDII 基准为指数×汇率干净价格。")
    lines.append("跳过：159545（其标的 HSHYLV 即以其净值兜底，无法自证）；511360（现金腿，无公开指数日线）。")

    report = "\n".join(lines)
    print(report)

    out = PROJECT_ROOT / "reports" / "tracking_check.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# ETF 跟踪差检验\n\n```\n" + report + "\n```\n", encoding="utf-8")
    print(f"\n报告已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
