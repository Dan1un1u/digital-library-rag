"""UI 只经 HTTP 调用后端；不加载模型、数据库或服务实例。"""
import httpx


def call_api(base, method, path, **kwargs):
    try:
        response = httpx.request(method, base.rstrip("/") + path, timeout=300, trust_env=False, **kwargs)
        data = response.json()
        if response.is_error and not (path == "/ask" and data.get("status") == "error"):
            return {"_failure": data.get("error", {"code": "SERVICE_ERROR", "message": "服务未能处理请求"})}
        return data
    except (httpx.HTTPError, ValueError):
        return {"_failure": {"code": "CONNECTION_ERROR", "message": "无法连接后端，请确认后端已启动、地址正确，或查看本地终端。"}}


def citation_numbers(answer):
    return {item["evidence_id"]: n for n, item in enumerate(answer["evidence"], 1)}


def clarified_question(original, choice):
    return original + "\n补充选择：" + choice
