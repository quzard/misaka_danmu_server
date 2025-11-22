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
        "baseUrlPlaceholder": "https://api.deepseek.com (默认)",
        "supportBalance": True,  # 是否支持余额查询
        "balanceApiPath": "/user/balance",  # 余额查询API路径
        "balanceResponseParser": "deepseek",  # 余额响应解析器类型
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
        "defaultModel": "Qwen/Qwen2.5-7B-Instruct",
        "modelPlaceholder": "Qwen/Qwen2.5-7B-Instruct, deepseek-ai/DeepSeek-V2.5",
        "baseUrlPlaceholder": "https://api.siliconflow.cn/v1 (默认)",
        "supportBalance": True,  # 支持余额查询
        "balanceApiPath": "/user/info",  # 余额查询API路径
        "balanceResponseParser": "siliconflow",  # 余额响应解析器类型
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
        "baseUrlPlaceholder": "https://api.openai.com/v1 (默认) 或自定义兼容接口",
        "supportBalance": False,
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
        "defaultModel": "gemini-1.5-flash",
        "modelPlaceholder": "gemini-1.5-flash, gemini-1.5-pro, gemini-2.0-flash-exp",
        "baseUrlPlaceholder": "留空 (使用官方 SDK)",
        "supportBalance": False,  # Gemini 不支持余额查询
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

