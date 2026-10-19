"""D 装配层：把统一 Settings 转成 C 的 SiliconFlowLLM。不实现生成逻辑。"""
from dlrag.qa.llm_client import SiliconFlowLLM

def create_client(settings):
    return SiliconFlowLLM(
        api_key=settings.llm_api_key.get_secret_value() or settings.siliconflow_api_key.get_secret_value(),
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout=float(settings.llm_timeout_seconds),
        max_output_tokens=settings.llm_max_output_tokens,
        context_window_tokens=settings.llm_context_window_tokens,
        enable_thinking=settings.llm_enable_thinking,
    )
