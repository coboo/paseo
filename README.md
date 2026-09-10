<div align="center">

# 🧭 paseo

[![简体中文](https://img.shields.io/badge/语言-简体中文-red)](README.md)
[![English](https://img.shields.io/badge/Lang-English-blue)](README.en.md)

**面向 A 股个人投资者的指数/ETF 量化系统**
估值仪表盘 · 择时策略实盘跟踪 · 行情监控 · 严肃回测

[![在线演示](https://img.shields.io/badge/🚀_在线演示-baiyunshan.streamlit.app-ff4b4b)](https://baiyunshan.streamlit.app/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.x-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![数据](https://img.shields.io/badge/数据-每日自动更新-0ca30c)](#-数据管线)

</div>

---

## 这是什么

一套**用数据说话**的 A 股指数投资工具：每天自动抓取 58 个数据集（指数行情 / ETF / QDII 净值 / 估值 / 宏观），喂给估值模型、择时策略和回测引擎，最后用一个 Web 应用呈现——

**👉 不用装任何东西，直接打开就用：[baiyunshan.streamlit.app](https://baiyunshan.streamlit.app/)**

## 五个页面

| 页面 | 内容 |
|---|---|
| 🎯 **Faber 策略（实盘）** | 10 月均线择时的实盘视角：当前持仓、距均线位置、下次调仓日。主检验 ✅ / walk-forward ✅ / holdout 实测差幅小，经人工裁决验收 |
| 📡 **行情监控** | 12 指数 + 16 ETF 报价板（新浪/东财实时 + 收盘兜底），**神奇九转日/周/月三级别**（≥7 淡底提示、9 完成位加深），**QDII 溢价率监控**（超 ±3% 门控警示） |
| 📈 **估值仪表盘** | 14 张宏观/估值模型卡（巴菲特指标、ERP、两融、QVIX、股息差、PMI……）→ 标准化 σ 综合分五档评级；底部附 **IC 自证**：综合分与未来 3 年收益秩相关 −0.72 |
| 🔬 **回测工作台** | 双动量 GEM 中美本土化两层回测、参数敏感性热力图、四个基线策略对照 |
| 🗄 **数据浏览器** | 58 个数据集总览：行数/区间/来源一目了然，任意表可画图、可侧栏一键增量更新 |

## 为什么值得关注

- **诚实，不玩幸存者偏差** —— 四个基线策略复现结果公开：GEM ❌ / Faber ✅ / FED ❌ / GTAA ❌。没通过检验的就标 ❌，策略页和文档都如实呈现
- **模型先自证再上桌** —— 估值综合分不是拍脑袋权重：用 expanding 窗口（无前视）对未来 1/3 年收益做 Spearman IC 检验，页面直接展示 IC 表和散点图
- **口径永远明示** —— 每个数字都标注来源与时点（实时/收盘/净值兜底），"没有口径标注的数字不许上页面"是写进设计文档的硬规则
- **数据管线有韧性** —— 每个数据源带主备抓取链（东财 → 新浪/腾讯/中证官网兜底），GitHub Actions 每日自动增量更新，部分失败容忍 + 断点续传
- **QDII 溢价实战纪律** —— 溢价率 = ETF 价 ÷ 单位净值（时点口径），超 ±3% 自动警示，对接"溢价超门控买入顺延"的交易纪律

## 快速开始

```bash
git clone https://github.com/coboo/paseo.git
cd paseo
uv sync
uv run streamlit run app/paseo.py     # 打开五个页面
```

数据已随仓库入库（parquet，约 10MB），克隆即用；手动增量更新：

```bash
PYTHONPATH=src uv run python -m data_module.update          # 全量
PYTHONPATH=src uv run python -m data_module.update cn10y    # 按名称
```

## 技术栈

**Streamlit** 五页应用 · **akshare** 多源抓取（主备兜底链）· **pandas/pyarrow** parquet 存储（raw 层只增不改）· **GitHub Actions** 每日 17:00（北京时间）自动更新提交 · AppTest 页面级回归测试

```
data/raw（58 数据集 parquet）→ src/metrics + src/strategy → data/derived → app/ 五页
```

## 免责声明

本项目仅用于个人投资研究学习，所有策略回测与模型评分**不构成投资建议**。历史表现不代表未来收益，投资有风险，入市需谨慎。

---

<div align="center">
如果这个工具对你有用，欢迎点一颗 ⭐ —— 这是持续更新的最大动力
</div>
