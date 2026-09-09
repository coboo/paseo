"""债券腿拼接：511260（十年国债ETF）上市前用中债国债财富指数延长。

拼接方法（设计文档第七节第 4 条：收益率对齐，非价格直接接）：
1. 分别计算 511260 前复权收盘价与中债国债财富指数(7-10Y)的日收益率；
2. 拼接日 T0 = 511260 有数据的首个交易日；
3. T0 之前逐日用指数日收益率，T0 起用 ETF 日收益率：
       r_spliced[t] = r_index[t]   (t <  T0)
       r_spliced[t] = r_etf[t]     (t >= T0)
   价格水平绝不直接相接，只把两段"收益率序列"缝在一起；
4. 由 r_spliced 累乘得到可追溯的净值序列 close（起点=1）。
重叠期用于一致性检查：报告拼接窗口两端日收益率波动率与相关性，
若指数与 ETF 走势差异过大需在报告里提示。

产出：data/derived/aligned/bond_leg_spliced_511260.parquet
      列：date, close（拼接净值）, ret（日收益率）, source（index/etf）

用法：PYTHONPATH=src uv run python -m data_module.bond_splice
"""
import pandas as pd

from .storage import DERIVED_DIR, read_raw, save_derived

ETF_CODE = "511260"


def build_spliced_bond_leg() -> tuple[pd.DataFrame, dict]:
    etf = read_raw(f"etf_daily/etf_qfq_{ETF_CODE}.parquet")[["date", "close"]]
    idx = read_raw("bond_index/cbond_treasury_wealth_7_10y.parquet")[["date", "close"]]

    t0 = etf["date"].min()  # 511260 上市首日（2017 年）

    # 拼接日历 = 指数与 ETF 交易日并集（两者都是工作日频率，先外连接再前向填充缺口）
    px = pd.concat([
        idx.assign(src="index"),
        etf.assign(src="etf"),
    ]).sort_values("date")
    cal = pd.DataFrame({"date": sorted(set(idx["date"]) | set(etf["date"]))})
    px_idx = idx.set_index("date")["close"].rename("px_index")
    px_etf = etf.set_index("date")["close"].rename("px_etf")
    panel = cal.set_index("date").join(px_idx).join(px_etf)

    # 日收益率：指数段 / ETF 段各自 pct_change（段内首个值 NaN）
    r_index = panel["px_index"].pct_change()
    r_etf = panel["px_etf"].pct_change()

    # 收益率对齐拼接：T0 前用指数收益率，T0 起用 ETF 收益率
    r_spliced = r_index.where(panel.index < t0, r_etf)
    src = pd.Series("index", index=panel.index).where(panel.index < t0, "etf")

    # 一致性检查：511260 上市后的重叠期，指数 vs ETF 日收益率相关性与波动率
    # （511260 上市初期流动性差，相关性低属正常现象，故分窗口报告）
    check = {"windows": {}}
    r_all = panel[["px_index", "px_etf"]].dropna().pct_change().dropna()
    cutoff = r_all.index[-1] - pd.DateOffset(years=3)
    for label, seg in [("近3年", r_all.loc[cutoff:]), ("全部重叠期", r_all)]:
        if len(seg) > 60:
            check["windows"][label] = {
                "days": int(len(seg)),
                "corr": float(seg["px_index"].corr(seg["px_etf"])),
                "vol_index_ann": float(seg["px_index"].std() * 252**0.5),
                "vol_etf_ann": float(seg["px_etf"].std() * 252**0.5),
            }

    out = pd.DataFrame({
        "date": panel.index,
        "ret": r_spliced.fillna(0.0).values,
        "source": src.values,
    })
    out["close"] = (1.0 + out["ret"]).cumprod()
    out = out[["date", "close", "ret", "source"]].reset_index(drop=True)
    check["splice_date"] = str(t0.date())
    return out, check


def main() -> int:
    out, check = build_spliced_bond_leg()
    path = save_derived(out, "aligned/bond_leg_spliced_511260.parquet")
    print(f"已写出 {path}")
    print(f"拼接日（511260 首个交易日）: {check['splice_date']}")
    print(f"拼接净值区间: {out['date'].min():%Y-%m-%d} ~ {out['date'].max():%Y-%m-%d}，共 {len(out)} 天")
    if check.get("windows"):
        for label, w in check["windows"].items():
            print(f"一致性检查[{label}]：重叠 {w['days']} 天，"
                  f"日收益率相关系数 {w['corr']:.3f}，"
                  f"年化波动率 指数 {w['vol_index_ann']:.2%} / ETF {w['vol_etf_ann']:.2%}")
    else:
        print("警告：拼接窗口无重叠数据，无法做一致性检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
