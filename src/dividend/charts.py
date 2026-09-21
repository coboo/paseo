"""研究报告图表生成（dividend-research make_charts.py 迁移版，去 daimon_runtime 依赖）。

matplotlib + 中文字体（macOS PingFang SC / Arial Unicode MS）。
fig1 估值历史 / fig2 因子ICIR / fig3 打分分布 / fig4 打分时序。
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

# 中文字体设置（macOS）
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

NAMES = {"H30269": "红利低波(563020)", "930955": "红利低波100(159307)",
         "515450": "标普红利低波50(515450)", "159545": "恒生红利低波(159545)"}


def make_charts(panels: dict[str, pd.DataFrame],
                scores: dict[str, pd.DataFrame],
                scores_val: dict[str, pd.DataFrame],
                layered: pd.DataFrame,
                out_dir: str | Path) -> list[Path]:
    """生成 4 张研究图表到 out_dir，返回文件路径列表。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    # ---- 图1: H30269/930955 估值核心指标历史 + 当前位置 ----
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for j, code in enumerate(["H30269", "930955"]):
        df = panels[code]
        ax = axes[0][j]
        ax.plot(df.index, df["dv"] * 100, lw=0.8, label="股息率(重建)")
        ax.plot(df.index, df["cgb10"] * 100, lw=0.8, label="10Y国债")
        ax.set_ylabel("%")
        ax.set_title(f"{NAMES[code]}：股息率 vs 10Y国债")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax = axes[1][j]
        ax.plot(df.index, df["erp"] * 100, lw=0.9, color="darkred")
        ax.axhline(df["erp"].median() * 100, ls="--", lw=0.8, color="gray", label="中位数")
        cur = df["erp"].iloc[-1] * 100
        ax.axhline(cur, ls=":", lw=0.8, color="red", label=f"当前 {cur:.2f}%")
        ax.set_ylabel("%")
        ax.set_title(f"{NAMES[code]}：股债利差 ERP（当前历史分位 {df['erp_pct'].iloc[-1]:.0%}）")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    p = out / "fig1_valuation_history.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    # ---- 图2: 因子ICIR(126d)对比 ----
    ic126 = layered[layered["h"] == 126].copy()
    ic126["label"] = ic126["instrument"] + ":" + ic126["factor"]
    piv = ic126.pivot_table(index="label", values="ICIR_ann").sort_values("ICIR_ann")
    fig, ax = plt.subplots(figsize=(10, 7))
    colors = ["#c0392b" if v < 1 else ("#e67e22" if v < 2 else "#27ae60") for v in piv["ICIR_ann"]]
    ax.barh(piv.index, piv["ICIR_ann"], color=colors)
    ax.axvline(1, ls="--", color="gray", lw=0.8)
    ax.set_xlabel("滚动504日ICIR(年化, 126日口径)")
    ax.set_title("因子显著性总览（绿=强 ICIR≥2，橙=中，红=弱）")
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()
    p = out / "fig2_factor_icir.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    # ---- 图3: 双口径当前打分仪表（历史分布 + 当前位置）----
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.6))
    for ax, code in zip(axes, NAMES):
        s_full = scores[code]["score_z"]
        s_val = scores_val[code]["score_z"]
        ax.hist(s_full.dropna(), bins=40, alpha=0.5, label="含动量版", density=True)
        ax.hist(s_val.dropna(), bins=40, alpha=0.5, label="估值纯因子版", density=True)
        ax.axvline(s_full.iloc[-1], color="tab:blue", lw=2)
        ax.axvline(s_val.iloc[-1], color="tab:orange", lw=2)
        ax.set_title(NAMES[code], fontsize=10)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
    fig.suptitle("当前打分在历史分布中的位置（竖线=当前值）", y=1.02)
    fig.tight_layout()
    p = out / "fig3_score_distribution.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    # ---- 图4: score_z 时序 vs 未来252日收益 ----
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    for code in ["H30269", "930955"]:
        sc = scores[code]
        axes[0].plot(sc.index, sc["score_z"], lw=0.8, label=NAMES[code])
        axes[1].plot(sc.index, sc["fwd_252"] * 100, lw=0.8, alpha=0.7)
    axes[0].axhline(0, color="gray", lw=0.6)
    axes[0].set_ylabel("score_z")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)
    axes[0].set_title("合成打分（上）与未来252日全收益%（下）")
    axes[1].axhline(0, color="gray", lw=0.6)
    axes[1].set_ylabel("fwd 252d %")
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    p = out / "fig4_score_timeseries.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    return saved
