"""Transient UI state must not leak across pages or independent tasks."""
QUESTION_STATE = ("last_progress", "answer", "search_result", "selected_evidence", "answer_filters", "last_request_id")


def reset_question(state):
    for key in QUESTION_STATE:
        state.pop(key, None)


def reset_upload(state, keep_file=False):
    for key in list(state):
        if key.startswith("upload_") and not (keep_file and key == "upload_pdf"):
            state.pop(key, None)


def reset_view(state):
    reset_question(state)
    reset_upload(state)
