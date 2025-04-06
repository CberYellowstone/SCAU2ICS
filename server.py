"""
SCAU2ICS Web服务 - 提供Web API生成ICS文件
"""

import base64
import binascii
import hashlib
import json
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

import cryptography
from cryptography.fernet import Fernet
from flask import Flask, Response, render_template, request, url_for

from scau2ics.config import ENCRYPTION_SALT, SEMESTERS, URL_EXPIRE_DAYS, logger
from scau2ics.ics import generate_ics
from scau2ics.student import Student

app = Flask(__name__)

# 常量
NIGHT_START = dt_time(0, 0)
NIGHT_END = dt_time(7, 0)
REQUIRED_FIELDS = ["userCode", "jwxt_password", "first_monday_date"]


# 加密工具函数
def generate_key_from_salt(salt):
    """从盐值生成Fernet密钥"""
    # 使用盐值和固定字符串生成SHA256哈希，然后base64编码作为密钥
    digest = hashlib.sha256(salt.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_data(data):
    """加密数据"""
    key = generate_key_from_salt(ENCRYPTION_SALT)
    fernet = Fernet(key)

    # 添加过期时间
    expiry = datetime.now() + timedelta(days=URL_EXPIRE_DAYS)
    data["expires"] = expiry.isoformat()

    # 加密JSON数据
    json_data = json.dumps(data)
    encrypted = fernet.encrypt(json_data.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_data(encrypted_token):
    """解密数据"""
    key = generate_key_from_salt(ENCRYPTION_SALT)
    fernet = Fernet(key)

    try:
        # 解码并解密
        decoded = base64.urlsafe_b64decode(encrypted_token)
        decrypted_data = fernet.decrypt(decoded).decode()
        data = json.loads(decrypted_data)

        # 检查过期时间
        if "expires" in data:
            expiry = datetime.fromisoformat(data["expires"])
            if datetime.now() > expiry:
                raise ValueError("URL已过期")

        return data
    except (binascii.Error, cryptography.fernet.InvalidToken) as e:
        logger.error(f"解密失败: {str(e)}")
        raise ValueError(f"无效或已过期的URL: {str(e)}")


@app.route("/generate_url", methods=["POST"])
def handle_generate_url():
    """处理生成加密URL的请求"""
    try:
        # 解析请求数据
        data = request.json
        if not data:
            return Response("请求数据不能为空", status=400)

        # 验证必要参数
        missing_fields = [field for field in REQUIRED_FIELDS if field not in data]
        if missing_fields:
            return Response(f"缺少必要参数: {', '.join(missing_fields)}", status=400)

        # 加密数据
        encrypted_token = encrypt_data(data)

        # 构建URL
        url = url_for("handle_generate_ics_get", token=encrypted_token, _external=True)

        return Response(json.dumps({"url": url}), mimetype="application/json")

    except Exception as e:
        logger.error(f"生成URL时发生错误: {str(e)}")
        return Response(f"生成URL时发生错误: {str(e)}", status=500)


@app.route("/generate_ics", methods=["POST"])
def handle_generate_ics():
    """处理ICS生成请求 (POST方法)"""
    try:
        # 解析和验证请求数据
        data = request.json
        if not data:
            return Response("请求数据不能为空", status=400)

        # 验证必要参数
        missing_fields = [field for field in REQUIRED_FIELDS if field not in data]
        if missing_fields:
            return Response(f"缺少必要参数: {', '.join(missing_fields)}", status=400)

        # 获取参数
        user_code = data["userCode"]
        jwxt_password = data["jwxt_password"]
        sso_password = data.get("sso_password", "")
        first_monday_date = data["first_monday_date"]

        # 检查是否需要SSO登录(夜间时段)
        is_sso_needed = _is_night_time()

        try:
            # 尝试创建学生对象并生成ICS
            student = Student(user_code, jwxt_password, sso_password)
            ics_content = generate_ics(student, first_monday_date)
            logger.info(f"成功为用户 {user_code} 生成ICS")
            return _create_ics_response(ics_content, user_code)
        except Exception as e:
            # 处理生成失败的情况
            logger.error(f"生成ICS时发生错误: {str(e)}")
            return _handle_generation_error(
                e,
                user_code,
                jwxt_password,
                first_monday_date,
                is_sso_needed,
                sso_password,
            )

    except Exception as e:
        # 处理请求解析异常
        logger.error(f"处理请求时发生错误: {str(e)}")
        return Response(f"处理请求时发生错误: {str(e)}", status=500)


@app.route("/generate_ics/<token>", methods=["GET"])
def handle_generate_ics_get(token):
    """处理ICS生成请求 (GET方法，使用加密token)"""
    try:
        # 解密token获取参数
        try:
            data = decrypt_data(token)
        except ValueError as e:
            return Response(f"无效或已过期的URL: {str(e)}", status=400)

        # 获取参数
        user_code = data["userCode"]
        jwxt_password = data["jwxt_password"]
        sso_password = data.get("sso_password", "")
        first_monday_date = data["first_monday_date"]

        # 检查是否需要SSO登录(夜间时段)
        is_sso_needed = _is_night_time()

        try:
            # 尝试创建学生对象并生成ICS
            student = Student(user_code, jwxt_password, sso_password)
            ics_content = generate_ics(student, first_monday_date)
            logger.info(f"成功通过加密URL为用户 {user_code} 生成ICS")
            return _create_ics_response(ics_content, user_code)
        except Exception as e:
            # 处理生成失败的情况
            logger.error(f"通过加密URL生成ICS时发生错误: {str(e)}")
            return _handle_generation_error(
                e,
                user_code,
                jwxt_password,
                first_monday_date,
                is_sso_needed,
                sso_password,
            )

    except Exception as e:
        # 处理解析异常
        logger.error(f"处理加密URL请求时发生错误: {str(e)}")
        return Response(f"处理加密URL请求时发生错误: {str(e)}", status=500)


def _is_night_time() -> bool:
    """判断当前是否为夜间时段(0点至7点)"""
    current_time = datetime.now().time()
    return NIGHT_START <= current_time <= NIGHT_END


def _create_ics_response(ics_content: str, user_code: str) -> Response:
    """创建ICS文件响应"""
    return Response(
        ics_content,
        mimetype="text/calendar",
        headers={
            "Content-Disposition": f"attachment; filename={user_code}_schedule.ics"
        },
    )


def _handle_generation_error(
    error: Exception,
    user_code: str,
    jwxt_password: str,
    first_monday_date: str,
    is_sso_needed: bool,
    sso_password: str,
) -> Response:
    """处理ICS生成错误"""
    # 检查是否是缺少SSO密码导致的错误
    if is_sso_needed and not sso_password and "需要提供统一身份认证密码" in str(error):
        logger.warning(f"用户 {user_code} 在需要SSO的时段未提供SSO密码，尝试使用缓存")

        # 尝试从缓存创建学生对象
        try:
            student = Student(user_code, jwxt_password, "")
            ics_content = generate_ics(student, first_monday_date)
            logger.info(f"成功从缓存为用户 {user_code} 生成ICS")
            return _create_ics_response(ics_content, user_code)
        except Exception as cache_error:
            logger.error(f"从缓存生成ICS失败: {str(cache_error)}")
            return Response(
                f"无法生成ICS (缓存读取失败)。如果现在是0点至7点之间，需要提供sso_password。错误: {str(cache_error)}",
                status=500,
            )

    # 其他类型的错误
    return Response(f"生成ICS时发生错误: {str(error)}", status=500)


@app.route("/", methods=["GET"])
def index():
    """首页，提供简单的使用说明和表单"""
    return render_template("index.html", SEMESTERS=SEMESTERS)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
