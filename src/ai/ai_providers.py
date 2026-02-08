#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI提供商配置管理"""

from typing import Dict, List, Any


# AI提供商配置
AI_PROVIDERS = {
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "displayName": "DeepSeek (推荐)",
        "description": "DeepSeek AI - 性价比高的国产大模型",
        "defaultBaseUrl": "https://api.deepseek.com",
        "defaultModel": "deepseek-chat",
        "modelPlaceholder": "deepseek-chat",
        "availableModels": [
            {"value": "deepseek-chat", "label": "deepseek-chat (推荐)", "description": "DeepSeek V3.2 对话模型 - 非思考模式"},
            {"value": "deepseek-reasoner", "label": "deepseek-reasoner", "description": "DeepSeek V3.2 推理模型 - 思考模式"}
        ],
        "baseUrlPlaceholder": "https://api.deepseek.com (默认)",
        "supportBalance": True,  # 是否支持余额查询
        "balanceApiPath": "/user/balance",  # 余额查询API路径
        "balanceResponseParser": "deepseek",  # 余额响应解析器类型
        "modelsApiPath": "/models",  # 模型列表API路径
        "apiKeyPrefix": "sk-",
        "website": "https://platform.deepseek.com",
        "order": 1
    },
    "siliconflow": {
        "id": "siliconflow",
        "name": "SiliconFlow",
        "displayName": "SiliconFlow 硅基流动",
        "description": "硅基流动 - 支持多种开源大模型",
        "defaultBaseUrl": "https://api.siliconflow.cn/v1",
        "defaultModel": "Qwen/Qwen3-8B",
        "modelPlaceholder": "Qwen/Qwen3-8B, deepseek-ai/DeepSeek-V3.2-Exp, Qwen/Qwen3-235B-A22B",
        "availableModels": [
            {"value": "Qwen/Qwen3-8B", "label": "Qwen3-8B (推荐免费)", "description": "通义千问3代 8B 模型 - 免费"},
            {"value": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B", "label": "DeepSeek-R1-Distill-Qwen-7B (免费)", "description": "DeepSeek R1 蒸馏版 7B - 免费"},
            {"value": "Qwen/Qwen3-32B", "label": "Qwen3-32B", "description": "通义千问3代 32B 模型"},
            {"value": "deepseek-ai/DeepSeek-V3.2-Exp", "label": "DeepSeek-V3.2-Exp (付费推荐版)", "description": "DeepSeek V3.2 实验版"},
            {"value": "deepseek-ai/DeepSeek-V3", "label": "DeepSeek-V3", "description": "DeepSeek V3 模型"},
            {"value": "deepseek-ai/DeepSeek-R1", "label": "DeepSeek-R1", "description": "DeepSeek R1 推理模型"}
        ],
        "baseUrlPlaceholder": "https://api.siliconflow.cn/v1 (默认)",
        "supportBalance": True,  # 支持余额查询
        "balanceApiPath": "/user/info",  # 余额查询API路径
        "balanceResponseParser": "siliconflow",  # 余额响应解析器类型
        "modelsApiPath": "/models",  # 模型列表API路径
        "apiKeyPrefix": "sk-",
        "website": "https://siliconflow.cn",
        "order": 2
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "displayName": "OpenAI (兼容接口)",
        "description": "OpenAI 或兼容 OpenAI API 的第三方服务",
        "defaultBaseUrl": "https://api.openai.com/v1",
        "defaultModel": "gpt-4-turbo",
        "modelPlaceholder": "gpt-4, gpt-4-turbo, gpt-3.5-turbo",
        "availableModels": [
            {"value": "gpt-4o", "label": "GPT-4o (推荐)", "description": "GPT-4 Omni 多模态模型"},
            {"value": "gpt-4o-mini", "label": "GPT-4o-mini", "description": "GPT-4 Omni 轻量版"},
            {"value": "gpt-4-turbo", "label": "GPT-4 Turbo", "description": "GPT-4 Turbo 模型"},
            {"value": "gpt-4", "label": "GPT-4", "description": "GPT-4 标准模型"},
            {"value": "gpt-3.5-turbo", "label": "GPT-3.5 Turbo", "description": "GPT-3.5 Turbo 模型"}
        ],
        "baseUrlPlaceholder": "https://api.openai.com/v1 (默认) 或自定义兼容接口",
        "supportBalance": False,
        "modelsApiPath": "/models",  # 模型列表API路径
        "apiKeyPrefix": "sk-",
        "website": "https://platform.openai.com",
        "order": 3
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "displayName": "Google Gemini",
        "description": "Google Gemini - Google 的多模态 AI 模型 (使用官方 SDK)",
        "defaultBaseUrl": "",  # Gemini 使用官方 SDK,不需要 Base URL
        "defaultModel": "gemini-2.5-flash",
        "modelPlaceholder": "gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-pro-preview",
        "availableModels": [
            {"value": "gemini-3-pro-preview", "label": "Gemini 3 Pro Preview (最新)", "description": "最智能的模型，支持多模态理解"},
            {"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash (推荐)", "description": "第三代工作马模型，1M上下文"},
            {"value": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite", "description": "超快速模型，成本效率高"}
        ],
        "baseUrlPlaceholder": "留空 (使用官方 SDK)",
        "supportBalance": False,  # Gemini 不支持余额查询
        "modelsApiPath": "https://generativelanguage.googleapis.com/v1/models",  # Gemini 使用完整URL
        "apiKeyPrefix": "AI",  # Gemini API Key 通常以 AI 开头
        "website": "https://ai.google.dev",
        "order": 4
    }
}


def get_all_providers() -> List[Dict[str, Any]]:
    """
    获取所有AI提供商配置列表
    
    Returns:
        提供商配置列表,按order排序
    """
    providers = list(AI_PROVIDERS.values())
    providers.sort(key=lambda x: x.get("order", 999))
    return providers


def get_provider_config(provider_id: str) -> Dict[str, Any]:
    """
    获取指定提供商的配置
    
    Args:
        provider_id: 提供商ID
        
    Returns:
        提供商配置字典,如果不存在则返回None
    """
    return AI_PROVIDERS.get(provider_id)


def get_provider_ids() -> List[str]:
    """
    获取所有提供商ID列表
    
    Returns:
        提供商ID列表
    """
    return list(AI_PROVIDERS.keys())


def is_provider_supported(provider_id: str) -> bool:
    """
    检查提供商是否支持
    
    Args:
        provider_id: 提供商ID
        
    Returns:
        是否支持
    """
    return provider_id in AI_PROVIDERS


def get_default_base_url(provider_id: str) -> str:
    """
    获取提供商的默认Base URL
    
    Args:
        provider_id: 提供商ID
        
    Returns:
        默认Base URL,如果不存在则返回空字符串
    """
    config = get_provider_config(provider_id)
    return config.get("defaultBaseUrl", "") if config else ""


def get_default_model(provider_id: str) -> str:
    """
    获取提供商的默认模型
    
    Args:
        provider_id: 提供商ID
        
    Returns:
        默认模型名称,如果不存在则返回空字符串
    """
    config = get_provider_config(provider_id)
    return config.get("defaultModel", "") if config else ""


def supports_balance_query(provider_id: str) -> bool:
    """
    检查提供商是否支持余额查询
    
    Args:
        provider_id: 提供商ID
        
    Returns:
        是否支持余额查询
    """
    config = get_provider_config(provider_id)
    return config.get("supportBalance", False) if config else False

