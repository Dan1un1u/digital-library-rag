"""Language selection changes presentation only and preserves session drafts."""
import streamlit as st
from dlrag.shared.i18n import normalize_language, set_language


def language_selector():
    requested = normalize_language(st.query_params.get('lang', st.session_state.get('ui_language', 'zh')))
    if st.session_state.get('ui_language') != requested:
        st.session_state['ui_language'] = requested

    def remember():
        st.query_params['lang'] = st.session_state['ui_language']

    st.sidebar.selectbox('界面语言 / Interface language', ['zh', 'en'],
        format_func={'zh': '简体中文', 'en': 'English'}.get, key='ui_language', on_change=remember)
    set_language(st.session_state['ui_language'])
