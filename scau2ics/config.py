"""
配置文件 - 管理应用程序的配置项
"""

import logging
import os
from datetime import datetime

# 基础路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")

# 确保缓存目录存在
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# 教务系统URL
JWXT_URL = "https://jwxt.scau.edu.cn"
JWXT_URL_BACKUP = "https://jwxt-scau-edu-cn-s.vpn.scau.edu.cn"

# 加密配置
ENCRYPTION_SALT = "SCAU2ICS_SALT_FOR_SECURE_URLS"  # 用于URL加密的盐值
URL_EXPIRE_DAYS = 30  # URL有效期（天）

# 预置的过滤词字典，整数 -> 字符串
PRESET_FILTERS = {0: "重修", 1: "免听", 2: "实验"}

# 日志配置
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("SCAU2ICS")

CLASS_TIMES = {
    "01": ("08:00", "08:40"),
    "02": ("08:45", "09:25"),
    "03": ("09:55", "10:35"),
    "04": ("10:40", "11:20"),
    "05": ("11:25", "12:05"),
    "06": ("12:40", "13:20"),
    "07": ("13:25", "14:05"),
    "08": ("14:30", "15:10"),
    "09": ("15:15", "15:55"),
    "10": ("16:25", "17:05"),
    "11": ("17:10", "17:50"),
    "12": ("17:55", "18:35"),
    "13": ("19:30", "20:10"),
    "14": ("20:15", "20:55"),
    "15": ("21:00", "21:40"),
}
