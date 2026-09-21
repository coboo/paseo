"""打分 × 后续走势（历史自证）纯函数层——红利低波页「打分 × 后续走势」区块的计算后端。

三个自证视角（范式复刻 src/metrics/validate.py 的 IC 自证：Spearman 秩相关 +
expanding 当时视角，页面侧见 app/valuation_dashboard.py 底部区块）：

- A 五档前瞻收益表：打分分位（纯估值口径）按 TIER_BOUNDS 分五档，统计每档
  **之后** 21/63/126/252 个交易日全收益的中位数 / 胜率 / 样本数；
- B 散点 + Spearman IC：打分分位 vs 未来 h 日收益成对样本 + 秩相关
  （期望方向 IC<0：分位高=贵 → 未来收益低）；
- C 事件研究：打分首次进入极低估区（<20%）的事件日 T，T 后 252 个交易日
  平均累计收益路径 vs 全部交易日等权平均基准路径（tr 全收益 cumprod）。

无未来函数纪律：打分序列直接用 compute_cards 的 series（expanding 当时视角，
T 日信号仅用 T-1 及以前数据）；fwd 标签天然向后；事件"首次进入"只用当日及
以前的打分判定。样本不足（事件数 < min_events）时事件研究返回 ok=False，
由页面显示"样本不足，不可外推"提示（与 DividendCard.non_extrapolatable
纪律一致），不画误导性曲线。

全部纯函数：输入 panel（factors.build_panel 产物）+ 打分分位序列
（0-100），输出 DataFrame / dict，可单测、不落盘（AGENTS.md 规则 5）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from metrics.contract import RATING_LEVELS

from . import factors, score
from .cards import TIER_BOUNDS

HORIZONS = factors.HORIZONS  # (21, 63, 126, 252)
EVENT_WINDOW = 252           # 事件研究路径长度（交易日）
MIN_EVENTS = 5               # 事件数下限：低于此数不画事件曲线（159545 保护）
IC_MIN_N = 30                # 低于此样本量不报 IC（只报 n）


def _bounds(tier: int) -> tuple[float | None, float | None]:
    """五档 → (下界含, 上界不含)；None 表示无穷。档 1: <20 … 档 5: ≥80。"""
    lo = TIER_BOUNDS[tier - 2] if tier >= 2 else None
    hi = TIER_BOUNDS[tier - 1] if tier <= 4 else None
    return lo, hi


def _in_tier(pct: pd.Series, tier: int) -> pd.Series:
    lo, hi = _bounds(tier)
    m = pd.Series(True, index=pct.index)
    if lo is not None:
        m &= pct >= lo
    if hi is not None:
        m &= pct < hi
    return m


def tier_forward_table(panel: pd.DataFrame, score_pct: pd.Series) -> pd.DataFrame:
    """五档前瞻收益表。score_pct：打分分位 0-100（DatetimeIndex，expanding 当时视角）。

    返回行=五档（tier/label/color + 各期限 n/med/win），数值为小数收益
    （展示层 ×100 格式化）；某档某期限无样本时为 NaN。
    """
    df = pd.DataFrame({"pct": score_pct.dropna().astype(float)})
    for h in HORIZONS:
        df[f"fwd_{h}"] = panel[f"fwd_{h}"]
    rows = []
    for tier in range(1, 6):
        row: dict = {"tier": tier, "label": RATING_LEVELS[tier]["label"],
                     "color": RATING_LEVELS[tier]["color"]}
        sub = df[_in_tier(df["pct"], tier)]
        for h in HORIZONS:
            s = sub[f"fwd_{h}"].dropna()
            row[f"n_{h}"] = int(len(s))
            row[f"med_{h}"] = float(s.median()) if len(s) else np.nan
            row[f"win_{h}"] = float((s > 0).mean()) if len(s) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def scatter_ic(panel: pd.DataFrame, score_pct: pd.Series,
               horizon: int) -> dict:
    """散点 + Spearman IC。返回 dict：df(date/pct/fwd 成对样本)、ic、n、覆盖区间。

    IC 期望为负（分位高=贵 → 未来收益低）。n < IC_MIN_N 时 ic=NaN（只报 n）。
    """
    pair = pd.concat([score_pct.dropna().rename("pct"),
                      panel[f"fwd_{horizon}"].rename("fwd")], axis=1).dropna()
    out = pair.reset_index()
    out.columns = ["date", "pct", "fwd"]  # 索引名不统一，按位置命名
    ic = float(spearmanr(out["pct"], out["fwd"]).statistic) \
        if len(out) >= IC_MIN_N else float("nan")
    return {"df": out, "ic": ic, "n": int(len(out)),
            "coverage_start": f"{out['date'].min():%Y-%m}" if len(out) else "",
            "coverage_end": f"{out['date'].max():%Y-%m}" if len(out) else ""}


def event_study(panel: pd.DataFrame, score_pct: pd.Series,
                threshold: float = TIER_BOUNDS[0], window: int = EVENT_WINDOW,
                min_events: int = MIN_EVENTS) -> dict:
    """事件研究：打分首次进入 <threshold% 的事件日 T 后 window 日平均累计收益路径。

    事件口径：T 日打分 < threshold 且 T-1 日不在区内（连续在区间只取首次进入日，
    避免重叠事件过度重复）；事件后不足 window 个交易日的样本不计入（尾部截断，
    防止不完整路径拉偏均值）——计数进 n_skipped_incomplete。基准 = 全部交易日
    等权平均的同期累计收益（同一 tr 序列、同一窗口）。

    ok = 完整窗口事件数 >= min_events；否则页面须显示样本不足提示、不画曲线。
    """
    s = score_pct.dropna().astype(float)
    inside = s < threshold
    first = inside & ~inside.shift(1, fill_value=False)
    event_dates = s.index[first]

    tr = panel["tr"].dropna()
    log_tr = np.log(tr.values)
    pos = tr.index.get_indexer(event_dates)
    pos = pos[pos >= 0]
    full = pos[pos + window < len(tr)]  # 完整窗口才算入事件
    n_skipped = int(len(pos) - len(full))

    base: dict = {"ok": False, "n_events": int(len(full)),
                  "n_skipped_incomplete": n_skipped, "window": window,
                  "threshold": threshold}
    if len(full) < min_events:
        return base

    k = np.arange(window + 1)
    # 事件路径：各事件日归一（T 日=0 收益）后等权平均
    paths = np.exp(log_tr[full[:, None] + k] - log_tr[full[:, None]]) - 1.0
    event_path = pd.Series(paths.mean(axis=0), index=k)
    # 基准路径：全部起始日等权平均（同一窗口，同为全收益 cumprod 口径）
    n0 = len(log_tr) - window
    baseline_path = pd.Series(
        [float(np.exp(log_tr[j:j + n0] - log_tr[:n0]).mean()) - 1.0
         for j in k], index=k)

    base.update(
        ok=True,
        event_path=event_path, baseline_path=baseline_path,
        first_event=f"{tr.index[full[0]]:%Y-%m-%d}",
        last_event=f"{tr.index[full[-1]]:%Y-%m-%d}",
    )
    return base


def compute_self_check() -> dict[str, dict]:
    """三件套编排：建面板 → 纯估值口径冻结打分 → 逐标的 A/B/C 结果 dict。

    页面 @st.cache_data 包装本函数（不落盘）。四标的键 = cards.ORDER。
    """
    panels = factors.build_panels()
    scores, _ = score.score_valuation_only(panels)
    out: dict[str, dict] = {}
    for code in score.INSTRUMENTS:
        s = scores[code]["score_pct"] * 100  # 0-100 分位，expanding 当时视角
        panel = panels[code]
        out[code] = {
            "tier": tier_forward_table(panel, s),
            "scatter": {h: scatter_ic(panel, s, h) for h in HORIZONS},
            "event": event_study(panel, s),
        }
    return out
