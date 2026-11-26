from pathlib import Path
from threading import Event

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from qa_ui import wait_for_ui_answer
from test_ask_jobs import wait_done


APP = Path(__file__).parents[2] / "src/dlrag/ui/app.py"
QUESTION = "我想了解旋转量化"
CHOICES = ["向量检索中的旋转量化", "机器学习中的旋转量化"]
CONFIRM = "补充后重新提问"


@pytest.mark.parametrize("options,fail_poll,custom_mode", [
    (CHOICES, False, None),
    ([], True, None),
    (CHOICES, False, "only"),
    (CHOICES, True, "override"),
], ids=["choice", "text-retry", "custom-only", "custom-overrides-and-retries"])
def test_clarification_is_submitted_once_and_resumes_polling(client, imported, monkeypatch, options, fail_poll, custom_mode):
    result = client.post("/ask", json={"question": "BM25"}).json()
    assert result["status"] == "answered"
    clarification = {
        **result, "request_id": "initial-answer", "status": "needs_clarification",
        "claims": [], "coverage": [], "evidence": [],
        "clarification_question": "你想了解哪个领域中的旋转量化？",
        "clarification_options": options,
        "query_plan": {**result["query_plan"], "original_query": QUESTION, "intent": "clarify"},
    }
    follow_ups, polls = [], []

    def local_api(base, method, path, **kwargs):
        if method == "POST" and path == "/ask/jobs":
            body = kwargs["json"]
            if body["question"] == QUESTION:
                return {"job_id": "initial"}
            follow_ups.append((body, kwargs.get("headers", {}).get("Idempotency-Key")))
            return {"job_id": f"follow-up-{len(follow_ups)}"}
        if method == "GET" and path.startswith("/ask/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            answer = clarification if job_id == "initial" else result
            stage = "done"
            if job_id != "initial":
                polls.append(job_id)
                if len(polls) <= 3:
                    stage, answer = "evidence_selection", None
                if fail_poll and len(polls) == 4:
                    return {"_failure": {"code": "CONNECTION_ERROR", "message": "测试连接中断"}}
            return {"job_id": job_id, "stage": stage, "stages": ["queued", stage],
                    "elapsed_seconds": 15.3, "answer": answer}
        return client.request(method, path, **kwargs).json()

    monkeypatch.setattr("dlrag.ui.client.call_api", local_api)
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    app.radio(key="navigation_page").set_value("搜索与问答").run()
    app.radio(key="query_action").set_value("问答")
    app.selectbox(key="query_mode").set_value("vector")
    app.text_input(key="filter_year_from").set_value("2024")
    app.text_area(key="query_question").set_value(QUESTION)
    next(b for b in app.button if b.label == "提交").click().run()
    wait_for_ui_answer(app)

    app.text_input(key="filter_year_from").set_value("2020").run()
    use_radio = options and not custom_mode
    label = "请选择" if use_radio else "补充说明"
    choice = "大语言模型的 4 位权重量化里，旋转为什么能减少离群值？" if custom_mode else CHOICES[1]

    if custom_mode == "only":
        next(b for b in app.button if b.label == CONFIRM).click().run()
        assert not follow_ups
        assert any("请选择一个选项或填写补充说明" in item.value for item in app.warning)
    elif custom_mode == "override":
        next(r for r in app.radio if r.label == "请选择").set_value(CHOICES[0])

    def choice_widget():
        widgets = app.radio if use_radio else app.text_input
        return next(w for w in widgets if w.label == label)

    old_choice = choice_widget().set_value(choice)
    old_confirm = next(b for b in app.button if b.label == CONFIRM)
    old_submit = next(b for b in app.button if b.label == "提交")
    old_confirm.click().run()
    app.run()
    visible_choice = choice_widget().value
    assert app.selectbox(key="query_mode").value == "vector"
    disabled = (choice_widget().proto.disabled,
                next(b for b in app.button if b.label == CONFIRM).proto.disabled,
                next(b for b in app.button if b.label == "提交").proto.disabled)
    assert app.session_state["last_progress"]["stage"] == "evidence_selection"

    # Use the pre-rerun controls to deliver an event issued before they became disabled.
    old_choice.set_value(CHOICES[0])
    old_confirm.click().run()
    assert len(follow_ups) == 1, f"Repeated confirmation created {len(follow_ups)} jobs"
    assert disabled == (True, True, True)
    assert visible_choice == choice
    assert follow_ups[0][0]["question"] == f"{QUESTION}\n补充选择：{choice}"
    assert follow_ups[0][0]["filters"]["year_from"] == 2024
    assert follow_ups[0][1]

    old_confirm.set_value(False)
    old_submit.click().run()
    wait_for_ui_answer(app)
    assert app.radio(key="query_action").value == "问答"
    assert app.text_area(key="query_question").value == QUESTION
    assert app.selectbox(key="query_mode").value == "vector"
    assert polls == ["follow-up-1"] * 4
    assert len(follow_ups) == 1
    assert not next(b for b in app.button if b.label == "提交").proto.disabled
    if fail_poll:
        assert any("测试连接中断" in item.value for item in app.error)
        assert not choice_widget().proto.disabled
        assert choice_widget().value == choice
        if custom_mode == "override":
            assert next(r for r in app.radio if r.label == "请选择").value == CHOICES[0]
        old_submit.set_value(False)
        old_confirm.click().run()
        assert len(follow_ups) == 1
        next(b for b in app.button if b.label == CONFIRM).click().run()
        wait_for_ui_answer(app)
        assert len(follow_ups) == 2
        assert follow_ups[1][1] != follow_ups[0][1]
        assert not app.error
    assert app.session_state["answer"]["status"] == "answered"
    assert all(b.label != CONFIRM for b in app.button)
    assert not app.exception


def test_rerun_before_post_response_reuses_accepted_job(client, imported, monkeypatch):
    submissions = []

    def local_api(base, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if method == "POST" and path == "/ask/jobs":
            submissions.append((kwargs.get("headers", {}).get("Idempotency-Key"), response.json()["job_id"]))
            if len(submissions) == 1:
                # The backend has accepted the job; the script stops before saving its ID.
                st.stop()
        return response.json()

    monkeypatch.setattr("dlrag.ui.client.call_api", local_api)
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    app.radio(key="navigation_page").set_value("搜索与问答").run()
    app.radio(key="query_action").set_value("问答")
    app.text_area(key="query_question").set_value("BM25")
    next(b for b in app.button if b.label == "提交").click().run()
    assert len(submissions) == 1
    wait_for_ui_answer(app)

    assert not app.exception
    assert len(submissions) == 2
    key, job_id = submissions[0]
    assert key and submissions[1] == (key, job_id)
    assert app.session_state["last_progress"]["job_id"] == job_id
    assert app.session_state["answer"]["status"] == "answered"
    assert list(client.app.state.ask_jobs.jobs) == [job_id]


def test_ask_retry_key_reuses_job_before_and_after_completion(client, services, imported):
    client.app.state.ask_jobs.capacity = 1
    entered, release = Event(), Event()
    original = services.qa.ask
    executions = []

    def blocked(request, progress):
        executions.append(request["question"])
        entered.set()
        assert release.wait(5)
        return original(request)

    services.qa.ask_with_progress = blocked
    body = {"question": "BM25"}
    headers = {"Idempotency-Key": "clarification-submission"}

    try:
        first = client.post("/ask/jobs", json=body, headers=headers)
        assert first.status_code == 202
        job_id = first.json()["job_id"]
        assert entered.wait(2)
        duplicate = client.post("/ask/jobs", json=body, headers=headers)
        assert duplicate.status_code == 202
        assert duplicate.json() == first.json()
        collision = client.post("/ask/jobs", json={"question": "另一个问题"}, headers=headers)
        assert collision.status_code == 422
        assert collision.json()["error"]["code"] == "INVALID_REQUEST"
    finally:
        release.set()

    assert wait_done(client, job_id)["answer"]["status"] == "answered"
    assert client.post("/ask/jobs", json=body, headers=headers).json() == first.json()
    assert executions == ["BM25"]
    independent = client.post("/ask/jobs", json=body).json()["job_id"]
    assert independent != job_id
    wait_done(client, independent)
