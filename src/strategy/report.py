"""QuantStats 报告 + 摘要 markdown(设计文档第十节交付物)。

输出:reports/gem_cn_{index,etf}.html(基准 = 沪深300 指数);
失败时退化为自产 HTML 摘要(BacktestResult.summary)。
"""
from __future__ import annotations

from pathlib import Path

from data_module.storage import PROJECT_ROOT, read_raw

from .contract import BacktestResult

REPORTS_DIR = PROJECT_ROOT / "reports"

try:
    import quantstats as qs
    QS_AVAILABLE = True
except ImportError:  # pragma: no cover
    QS_AVAILABLE = False


def _benchmark() -> pd.Series:
    """报告基准:沪深300 指数日收益(与回测同源)。"""
    hs = read_raw("index_daily/index_000300.parquet").set_index("date")["close"]
    return hs.pct_change().dropna()


def write_quantstats_report(res: BacktestResult, out_html: Path) -> Path:
    """单层 QuantStats tearsheet(基准 = 沪深300)。"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    bench = _benchmark().reindex(res.ret.index).fillna(0.0)
    qs.reports.html(res.ret, benchmark=bench, output=str(out_html),
                    title=res.name)
    return out_html


def _fallback_html(res: BacktestResult, out_html: Path) -> Path:
    """QuantStats 不可用/失败时的自产摘要页。"""
    s = res.summary
    rows = "".join(
        f"<tr><td>{k}</td><td>{v if isinstance(v, str) else f'{v:.4f}'}</td></tr>"
        for k, v in s.items())
    out_html.write_text(
        f"<html><head><meta charset='utf-8'><title>{res.name}</title></head>"
        f"<body><h2>{res.name}</h2><p>区间 {res.nav.index.min():%Y-%m-%d} → "
        f"{res.nav.index.max():%Y-%m-%d}</p><table border=1>{rows}</table>"
        f"<p><i>QuantStats 不可用,退化为摘要页</i></p></body></html>",
        encoding="utf-8")
    return out_html


def write_reports(results: dict[str, BacktestResult]) -> list[Path]:
    """全部层的报告。"""
    paths = []
    for key, res in results.items():
        out = REPORTS_DIR / f"gem_cn_{key}.html"
        try:
            if QS_AVAILABLE:
                paths.append(write_quantstats_report(res, out))
                continue
        except Exception as e:  # noqa: BLE001 — 报告失败不阻断回测
            print(f"  [warn] QuantStats 失败({type(e).__name__}: {str(e)[:80]}),退化自产摘要")
        paths.append(_fallback_html(res, out))
    return paths


def summary_markdown(results: dict[str, BacktestResult]) -> str:
    """终端/报告两用的摘要 markdown 表。"""
    lines = ["| 层 | 区间 | 年化 | 最大回撤 | 夏普 | Calmar | 换仓 | QDII跳过 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results.values():
        s = r.summary
        lines.append(
            f"| {r.name} | {r.nav.index.min():%Y-%m-%d}~{r.nav.index.max():%Y-%m-%d} "
            f"| {s['cagr'] * 100:+.2f}% | {s['mdd'] * 100:.1f}% | {s['sharpe']:.2f} "
            f"| {s['calmar']:.2f} | {s['switch_count']} | {s.get('blocked_months', '—')} |")
    return "\n".join(lines)
