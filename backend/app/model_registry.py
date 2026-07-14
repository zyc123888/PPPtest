from __future__ import annotations


CASE_GENERATION_MODEL_OPTIONS: tuple[dict[str, str], ...] = (
    {"provider": "OpenAI", "label": "GPT-5.5", "value": "gpt-5.5", "base_url": "https://api.openai.com/v1"},
    {"provider": "OpenAI", "label": "GPT-5.4", "value": "gpt-5.4", "base_url": "https://api.openai.com/v1"},
    {"provider": "Ollama", "label": "gpt-oss:120b", "value": "gpt-oss:120b", "base_url": "https://ollama.com/v1"},
    {"provider": "Ollama", "label": "glm-5.1", "value": "glm-5.1", "base_url": "https://ollama.com/v1"},
    {"provider": "Ollama", "label": "kimi-k2.6", "value": "kimi-k2.6", "base_url": "https://ollama.com/v1"},
    {"provider": "Ollama", "label": "minimax-m3", "value": "minimax-m3", "base_url": "https://ollama.com/v1"},
    {"provider": "Ollama", "label": "qwen3.5", "value": "qwen3.5", "base_url": "https://ollama.com/v1"},
    {"provider": "Qwen", "label": "qwen3.7-plus", "value": "qwen3.7-plus", "base_url": "https://coding.dashscope.aliyuncs.com/v1"},
    {"provider": "Qwen", "label": "qwen3.6-plus", "value": "qwen3.6-plus", "base_url": "https://coding.dashscope.aliyuncs.com/v1"},
    {"provider": "Qwen", "label": "qwen3.5-plus", "value": "qwen3.5-plus", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    {"provider": "Qwen", "label": "qwen-max", "value": "qwen-max", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    {"provider": "DeepSeek", "label": "deepseek-chat", "value": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
    {"provider": "DeepSeek", "label": "deepseek-reasoner", "value": "deepseek-reasoner", "base_url": "https://api.deepseek.com/v1"},
    {"provider": "GLM", "label": "glm-4.5", "value": "glm-4.5", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    {"provider": "GLM", "label": "glm-4.5-air", "value": "glm-4.5-air", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    {"provider": "Custom", "label": "自定义 OpenAI 兼容模型", "value": "custom-openai-compatible", "base_url": ""},
)


def case_generation_model_options() -> list[dict[str, str]]:
    return [dict(item) for item in CASE_GENERATION_MODEL_OPTIONS]
