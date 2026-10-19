"""Streamlit entry for the explicitly marked local validation backend only."""
import os
from pathlib import Path
import runpy
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import LocalAPI

st.set_page_config(page_title="DEV 测试馆藏", page_icon="📚", layout="wide")
base = os.environ.get("API_BASE_URL", "http://127.0.0.1:19000")
try:
    marker = LocalAPI(base).request("GET", "/validation/environment")
    if marker.get("validation_only") is not True:
        raise ValueError("Not a validation backend")
except Exception:
    st.error("测试馆藏服务未就绪，请确认连接的是独立 dev 环境。")
    st.stop()
os.environ["API_BASE_URL"] = base
st.warning("DEV 独立测试馆藏 · 正式馆藏保持不变。含用于复现正文质量问题的文献，使用时请结合检测报告核对。")
runpy.run_path(str(ROOT / "app/src/dlrag/ui/app.py"), run_name="__main__")
