"""Language selection changes presentation only and preserves session drafts."""
import streamlit as st
from dlrag.shared.i18n import normalize_language, set_language


def refresh_choices():
    # Streamlit's browser retains formatted strings for selected options. Explicit
    # assignment sends the same canonical values again with the new labels.
    for key in ('navigation_page', 'library_section', 'management_section',
                'browse_domain', 'query_action', 'query_mode', 'upload_domain', 'upload_language'):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def language_selector():
    requested = normalize_language(st.query_params.get('lang', st.session_state.get('ui_language', 'zh')))
    if st.session_state.get('ui_language') != requested:
        refresh_choices()
        st.session_state['ui_language'] = requested

    def remember():
        st.query_params['lang'] = st.session_state['ui_language']
        refresh_choices()

    st.sidebar.selectbox('界面语言 / Interface language', ['zh', 'en'],
        format_func={'zh': '简体中文', 'en': 'English'}.get, key='ui_language', on_change=remember)
    set_language(st.session_state['ui_language'])
