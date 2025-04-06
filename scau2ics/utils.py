"""
工具函数模块 - 提供各种辅助功能
"""

import json
import os
import time
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional, Tuple

import ddddocr
import requests
import urllib3
from PIL import Image

from scau2ics.config import JWXT_URL, logger

# 禁用SSL警告
urllib3.disable_warnings()

# 通用请求头
COMMON_HEADERS = {
    "app": "PCWEB",
    "Accept": "application/json, text/plain",
}

# 验证头
KAPTCHA_HEADERS = {
    **COMMON_HEADERS,
    "KAPTCHA-KEY-GENERATOR-REDIS": "securityKaptchaRedisServiceAdapter",
}


def get_captcha(cookies: Dict[str, str], base_url: str = JWXT_URL) -> str:
    """
    获取验证码并识别

    Args:
        cookies: 会话cookies
        base_url: 基础URL，凌晨时段应使用JWXT_URL_BACKUP
    """
    ocr = ddddocr.DdddOcr(beta=True, show_ad=False)
    timestamp = int(time.time() * 1000)
    captcha_url = f"{base_url}/secService/kaptcha?t={timestamp}&KAPTCHA-KEY-GENERATOR-REDIS=securityKaptchaRedisServiceAdapter"
    r = requests.get(captcha_url, cookies=cookies, verify=False)
    img = Image.open(BytesIO(r.content))
    return ocr.classification(img)


def verify_captcha(
    captcha: str, cookies: Dict[str, str], base_url: str = JWXT_URL
) -> Tuple[bool, Optional[str]]:
    """
    验证验证码是否正确

    Args:
        captcha: 验证码文本
        cookies: 会话cookies
        base_url: 基础URL，凌晨时段应使用JWXT_URL_BACKUP

    Returns:
        元组: (是否成功, 错误消息)
    """
    url = f"{base_url}/secService/kaptcha/check/{captcha}/false"
    rep = requests.post(url, headers=KAPTCHA_HEADERS, cookies=cookies, verify=False)
    result = rep.json()

    if result["errorCode"] != "success":
        return False, result["errorMessage"]
    return True, None


def save_json_cache(file_path: str, data: Dict[str, Any]) -> None:
    """
    保存JSON格式的缓存数据

    Args:
        file_path: 缓存文件路径
        data: 要缓存的数据
    """
    try:
        cache_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data,
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.info(f"数据已缓存到: {file_path}")
    except Exception as e:
        logger.error(f"保存缓存失败: {str(e)}")


def load_json_cache(file_path: str) -> Optional[Dict[str, Any]]:
    """
    从文件加载JSON缓存数据

    Args:
        file_path: 缓存文件路径

    Returns:
        缓存数据或None（如果加载失败）
    """
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        logger.info(
            f"已从缓存加载数据，更新时间: {cache_data.get('timestamp', '未知')}"
        )
        return cache_data
    except Exception as e:
        logger.error(f"加载缓存失败: {str(e)}")
        return None


def get_cache_timestamp(file_path: str) -> Optional[str]:
    """
    获取缓存文件的时间戳

    Args:
        file_path: 缓存文件路径

    Returns:
        时间戳字符串或None
    """
    cache_data = load_json_cache(file_path)
    return cache_data.get("timestamp") if cache_data else None
