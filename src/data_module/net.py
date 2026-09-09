"""网络层：akshare 兼容补丁 + 带退避的重试抓取。

当前网络环境（2026-08）对东财部分子域名不稳定：
- 80.push2.eastmoney.com 经系统代理无法连通（index_zh_a_hist 的代码表查询受影响），
  替换为 push2.eastmoney.com 主域名；
- 东财接口整体偶发断连，所有抓取统一走 retry_fetch 多次重试。
"""
import random
import time

import akshare as ak


def patch_akshare() -> None:
    """打补丁：把 index_zh_a_hist 依赖的代码表查询换到可达的东财主域名。"""
    import akshare.index.index_zh_em as zh_em
    from akshare.utils.func import fetch_paginated_data

    def _code_id_map() -> dict:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "100", "po": "1", "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "b:MK0010,m:1+t:1,m:0 t:5,m:1+s:3,m:0+t:5,m:2",
            "fields": "f3,f12,f13",
        }
        df = fetch_paginated_data(url, params)
        return dict(zip(df["f12"], df["f13"]))

    zh_em.index_code_id_map_em = _code_id_map


def retry_fetch(fn, *args, retries: int = 8, base_sleep: float = 2.0, **kw):
    """指数退避 + 抖动重试；东财/新浪限流与断连常见，重跑即断点续传。"""
    last_exc = None
    for i in range(retries):
        try:
            return fn(*args, **kw)
        except Exception as e:  # noqa: BLE001 - 网络错误类型繁多，统一重试
            last_exc = e
            sleep_s = base_sleep * (1.6**i) + random.uniform(0, 1.5)
            print(f"    [重试 {i + 1}/{retries}] {type(e).__name__}: {str(e)[:100]}，{sleep_s:.1f}s 后重试")
            time.sleep(sleep_s)
    raise last_exc


# 打补丁在 import 时生效一次即可
patch_akshare()
