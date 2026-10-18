import json
import requests
import pytest
from dlrag.qa import ProjectError, SiliconFlowLLM


class Response:
    status_code = 200
    def __init__(self, body=None):
        self.body = body or {"choices": [{"finish_reason": "stop", "message": {"content": '{"status":"ok"}'}}],
                            "usage": {"total_tokens": 12}}
    def json(self):
        return self.body


class Session:
    def __init__(self, result=None):
        self.result, self.calls = result or Response(), []
    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_request_protocol_and_safe_record():
    s = Session()
    client = SiliconFlowLLM(api_key="private-test-key", session=s)
    assert s.calls == []
    assert client.generate_json("JSON please", {"question": "test"}) == {"status": "ok"}
    args, kwargs = s.calls[0]
    assert args[0].endswith("/v1/chat/completions") and kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 60 and kwargs["json"]["response_format"] == {"type": "json_object"}
    assert kwargs["json"]["messages"][1]["content"] == '{"question":"test"}'
    assert "private-test-key" not in json.dumps(client.records) + json.dumps(client.get_config())
    assert client.records[0]["usage"]["total_tokens"] == 12


@pytest.mark.parametrize("status,code", [(401, "MODEL_NOT_CONFIGURED"), (403, "MODEL_NOT_CONFIGURED"),
    (429, "MODEL_UNAVAILABLE"), (500, "MODEL_UNAVAILABLE"), (302, "MODEL_UNAVAILABLE")])
def test_http_errors_no_retry_no_leak(status, code):
    response = Response()
    response.status_code = status
    s = Session(response)
    client = SiliconFlowLLM("secret", session=s)
    with pytest.raises(ProjectError) as e:
        client.generate_json("JSON", {})
    assert e.value.code == code and len(s.calls) == 1
    assert "secret" not in str(e.value)


@pytest.mark.parametrize("error,code", [(requests.Timeout("secret"), "MODEL_TIMEOUT"),
                                      (requests.ConnectionError("secret"), "MODEL_UNAVAILABLE")])
def test_network_errors(error, code):
    client = SiliconFlowLLM("key", session=Session(error))
    with pytest.raises(ProjectError) as e:
        client.generate_json("JSON", {})
    assert e.value.code == code and "secret" not in str(e.value)


@pytest.mark.parametrize("body", [{"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "[]"}}]}])
def test_malformed_response(body):
    client = SiliconFlowLLM("key", session=Session(Response(body)))
    with pytest.raises(ProjectError) as e:
        client.generate_json("JSON", {})
    assert e.value.code == "OUTPUT_VALIDATION_FAILED"


def test_missing_key_no_network():
    s = Session()
    client = SiliconFlowLLM(session=s)
    with pytest.raises(ProjectError) as e:
        client.generate_json("JSON", {})
    assert e.value.code == "MODEL_NOT_CONFIGURED" and not s.calls


def test_context_bound_no_network():
    s = Session()
    client = SiliconFlowLLM("key", context_window_tokens=1100, session=s)
    with pytest.raises(ProjectError) as e:
        client.generate_json("JSON", {"x": "文" * 2000})
    assert e.value.code == "INVALID_REQUEST" and not s.calls


@pytest.mark.parametrize("config", [{"base_url": "http://example.com"}, {"base_url": "https://a:b@example.com"},
    {"base_url": "https://example.com?a=1"}, {"timeout": float("nan")}, {"timeout": True}, {"model": ""}])
def test_invalid_config(config):
    with pytest.raises(ProjectError):
        SiliconFlowLLM(**config)
