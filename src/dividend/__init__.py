"""红利低波簇研究模块（dividend-research 迁入，src/dividend/）。

四只红利低波 ETF（563020/H30269、515450/净值代理、159307/930955、159545/净值代理）
的估值因子研究：因子面板、IC/分层验证、冻结权重打分、概率与样本外检验、宏观否决留档。

核心结论见 dividend-research/HANDOFF.md（2026-09-18）：
幸存 4 因子家族（反转/盈利收益率利差/−PE/股息率分位），
打分 = expanding z × ≤2023 样本内 ICIR 权重（永久冻结）。

数据全部经 data_module.storage 读 data/raw parquet；指标结果不落盘，
由各函数返回 DataFrame（AGENTS.md 规则 5）。
"""
from . import cards, charts, factors, ic, layered, macro, score, validate

__all__ = ["cards", "charts", "factors", "ic", "layered", "macro", "score", "validate"]
