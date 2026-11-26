"""Drive Streamlit's scheduled QA fragment in AppTest."""
import pytest


def wait_for_ui_answer(app):
    # AppTest does not run the browser's automatic fragment timer.
    for _ in range(20):
        assert not app.exception
        if "pending_ask" not in app.session_state:
            return
        app.run()
    pytest.fail("The QA fragment did not finish")
