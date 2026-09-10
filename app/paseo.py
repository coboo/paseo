"""paseo 统一入口(单一命令进入全部页面,侧栏切换)。

用法:uv run streamlit run app/paseo.py

页面文件原位不动(各自的 AppTest 测试仍直接指向原文件);本入口仅做导航。
"""
from pathlib import Path

import streamlit as st

_HERE = Path(__file__).resolve().parent

st.set_page_config(page_title="paseo · 指数ETF量化系统", page_icon="🧭", layout="wide")

pages = [
    st.Page(_HERE / "faber_strategy.py", title="🎯 Faber 策略(实盘)", default=True,
            url_path="faber"),
    st.Page(_HERE / "market_monitor.py", title="📡 行情监控", url_path="market"),
    st.Page(_HERE / "valuation_dashboard.py", title="📈 估值仪表盘", url_path="valuation"),
    st.Page(_HERE / "gem_backtest.py", title="🔬 回测工作台", url_path="backtest"),
    st.Page(_HERE / "browse_data.py", title="🗄 数据浏览器", url_path="data"),
]
st.navigation(pages).run()
