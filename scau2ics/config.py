"""
配置文件 - 管理应用程序的配置项
"""

import logging
import os

# 基础路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")

# 确保缓存目录存在
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# 教务系统URL
JWXT_URL = "https://jwxt.scau.edu.cn"
JWXT_URL_BACKUP = "https://jwxt-scau-edu-cn-s.vpn.scau.edu.cn"

# 学期配置 - 可根据实际情况调整
CURRENT_SEMESTER = "2024-2025-2"

# 学期列表配置 - 每学期对应开学第一周周一的日期
SEMESTERS = [
    {"value": "2025-02-17", "label": "2024-2025-2"},
    {"value": "2024-09-02", "label": "2024-2025-1"},
    {"value": "2024-02-26", "label": "2023-2024-2"},
]

# 加密配置
ENCRYPTION_SALT = "SCAU2ICS_SALT_FOR_SECURE_URLS"  # 用于URL加密的盐值
URL_EXPIRE_DAYS = 30  # URL有效期（天）

# 日志配置
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("SCAU2ICS")
