"""
SCAU2ICS Web服务 - 提供Web API生成ICS文件及CalDAV服务
"""

# 标准库导入
import base64
import binascii
import hashlib
import json
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from typing import Dict, Optional

# 第三方库导入
import cryptography
from cryptography.fernet import Fernet
from flask import Flask, Response, render_template, request, url_for

# 本地模块导入
from scau2ics.caldav import (
    caldav_auth,
    generate_config,
    handle_caldav,
    set_decrypt_function,
)
from scau2ics.config import ENCRYPTION_SALT, URL_EXPIRE_DAYS, logger
from scau2ics.ics import generate_ics
from scau2ics.student import Student
from scau2ics.utils import generate_semesters

app = Flask(__name__)

# 常量
NIGHT_START = dt_time(0, 0)
NIGHT_END = dt_time(7, 0)
REQUIRED_FIELDS = ["userCode", "jwxt_password", "semester"]


# 加密工具函数
def generate_key_from_salt(salt: str) -> bytes:
    """从盐值生成Fernet密钥"""
    # 使用盐值和固定字符串生成SHA256哈希，然后base64编码作为密钥
    digest = hashlib.sha256(salt.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_data(data: Dict, expire_days: Optional[int] = None) -> str:
    """
    加密数据

    Args:
        data: 要加密的数据字典
        expire_days: 过期天数，None表示使用默认配置，0表示永不过期
    """
    key = generate_key_from_salt(ENCRYPTION_SALT)
    fernet = Fernet(key)

    # 添加过期时间（如果需要）
    if expire_days != 0:  # 0表示永不过期
        days = expire_days if expire_days is not None else URL_EXPIRE_DAYS
        expiry = datetime.now() + timedelta(days=days)
        data["expires"] = expiry.isoformat()
    # 不设置expires字段表示永不过期

    # 加密JSON数据
    json_data = json.dumps(data)
    encrypted = fernet.encrypt(json_data.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_data(encrypted_token: str) -> Dict:
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


# 设置CalDAV解密函数
set_decrypt_function(decrypt_data)


def _validate_request_data(data: Dict) -> Optional[Response]:
    """验证请求数据，如果有错误则返回错误响应，否则返回None"""
    if not data:
        return Response("请求数据不能为空", status=400)

    # 验证必要参数
    missing_fields = [field for field in REQUIRED_FIELDS if field not in data]
    if missing_fields:
        return Response(f"缺少必要参数: {', '.join(missing_fields)}", status=400)

    return None


def _extract_user_data(data: Dict) -> tuple:
    """从请求数据中提取用户相关信息"""
    user_code = data["userCode"]
    jwxt_password = data["jwxt_password"]
    sso_password = data.get("sso_password", "")
    semester = data["semester"]

    return (user_code, jwxt_password, sso_password, semester)


def _generate_ics_for_user(
    user_code: str,
    jwxt_password: str,
    sso_password: str,
    semester: str,
    is_from_url: bool = False,
) -> Response:
    """为用户生成ICS文件，处理各种异常情况"""
    is_sso_needed = _is_night_time()

    try:
        # 尝试创建学生对象并生成ICS
        student = Student(user_code, jwxt_password, sso_password)
        ics_content = generate_ics(student, semester)
        source = "加密URL" if is_from_url else "直接请求"
        logger.info(f"成功通过{source}为用户 {user_code} 生成ICS")
        return _create_ics_response(ics_content, user_code)
    except Exception as e:
        # 处理生成失败的情况
        logger.error(f"生成ICS时发生错误: {str(e)}")
        return _handle_generation_error(
            e,
            user_code,
            jwxt_password,
            is_sso_needed,
            sso_password,
            semester,
        )


@app.route("/generate_url", methods=["POST"])
def handle_generate_url():
    """处理生成加密URL的请求"""
    try:
        # 解析并验证请求数据
        data = request.json
        validation_error = _validate_request_data(data)
        if validation_error:
            return validation_error

        # 获取过期天数参数（如果有）
        expire_days = data.pop("expire_days", None)
        try:
            if expire_days is not None:
                expire_days = int(expire_days)
        except (ValueError, TypeError):
            return Response("expire_days必须是整数", status=400)

        # 加密数据并构建URL
        encrypted_token = encrypt_data(data, expire_days)
        url = url_for("handle_generate_ics_get", token=encrypted_token, _external=True)

        # 构建响应
        response_data = {"url": url}
        # 添加过期信息到响应
        if expire_days == 0:
            response_data["expires"] = "永不过期"
        elif expire_days is not None:
            expiry_date = (datetime.now() + timedelta(days=expire_days)).strftime(
                "%Y-%m-%d"
            )
            response_data["expires"] = f"{expire_days}天 ({expiry_date})"
        else:
            expiry_date = (datetime.now() + timedelta(days=URL_EXPIRE_DAYS)).strftime(
                "%Y-%m-%d"
            )
            response_data["expires"] = f"{URL_EXPIRE_DAYS}天 ({expiry_date})"

        return Response(json.dumps(response_data), mimetype="application/json")

    except Exception as e:
        logger.error(f"生成URL时发生错误: {str(e)}")
        return Response(f"生成URL时发生错误: {str(e)}", status=500)


@app.route("/generate_ics", methods=["POST"])
def handle_generate_ics():
    """处理ICS生成请求 (POST方法)"""
    try:
        # 解析和验证请求数据
        data = request.json
        validation_error = _validate_request_data(data)
        if validation_error:
            return validation_error

        # 提取用户相关信息
        user_code, jwxt_password, sso_password, semester = _extract_user_data(data)

        # 生成ICS文件
        return _generate_ics_for_user(user_code, jwxt_password, sso_password, semester)

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

        # 验证必要参数
        validation_error = _validate_request_data(data)
        if validation_error:
            return validation_error

        # 提取用户相关信息
        user_code, jwxt_password, sso_password, semester = _extract_user_data(data)

        # 生成ICS文件
        return _generate_ics_for_user(
            user_code,
            jwxt_password,
            sso_password,
            semester,
            is_from_url=True,
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
    is_sso_needed: bool,
    sso_password: str,
    semester: str,
) -> Response:
    """处理ICS生成错误"""
    # 检查是否是缺少SSO密码导致的错误
    if is_sso_needed and not sso_password and "需要提供统一身份认证密码" in str(error):
        logger.warning(f"用户 {user_code} 在需要SSO的时段未提供SSO密码，尝试使用缓存")

        # 尝试从缓存创建学生对象
        try:
            student = Student(user_code, jwxt_password, "")
            ics_content = generate_ics(student, semester)
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
    return render_template(
        "index.html", SEMESTERS=generate_semesters(), URL_EXPIRE_DAYS=URL_EXPIRE_DAYS
    )


@app.route("/generate_caldav_config", methods=["POST"])
def generate_caldav_config():
    """生成CalDAV配置"""
    try:
        # 解析请求数据
        data = request.json
        validation_error = _validate_request_data(data)
        if validation_error:
            return validation_error

        # 使用caldav模块的函数生成配置
        config = generate_config(encrypt_data, data, request.url_root)

        # 返回配置信息
        return Response(json.dumps(config), mimetype="application/json")

    except Exception as e:
        logger.error(f"生成CalDAV配置时发生错误: {str(e)}")
        return Response(f"生成CalDAV配置时发生错误: {str(e)}", status=500)


@app.route("/caldav/", methods=["PROPFIND", "OPTIONS"])
@app.route("/caldav/<user_code>/", methods=["PROPFIND", "OPTIONS"])
@app.route(
    "/caldav/<user_code>/calendar/",
    methods=["GET", "PROPFIND", "REPORT", "OPTIONS"],
)
@app.route(
    "/caldav/<user_code>/calendar/<path:resource_path>",
    methods=["GET", "PROPFIND", "REPORT", "OPTIONS"],
)
def caldav_routes(user_code=None, resource_path=None):
    """处理CalDAV请求"""
    # 记录请求信息
    logger.info(f"收到CalDAV请求: {request.method} {request.path}")
    if "Authorization" in request.headers:
        logger.info(
            f"请求包含Authorization头: {request.headers['Authorization'][:10]}..."
        )
    else:
        logger.info("请求不包含Authorization头")

    # 对于OPTIONS请求，始终允许，无需认证
    if request.method == "OPTIONS":
        return handle_caldav(user_code, resource_path)

    # 检查是否有Authorization头
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        # 没有提供认证信息，返回401要求认证
        logger.info(f"未提供认证信息，返回401")
        return Response(
            "需要认证",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="SCAU课表日历"'},
        )

    # 如果有认证信息，交给caldav_auth验证
    user_data = caldav_auth.current_user()
    if user_data is None:
        # 认证信息无效
        logger.info(f"认证信息无效，返回401")
        return Response(
            "认证失败",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="SCAU课表日历"'},
        )

    # 认证成功，记录用户信息
    logger.info(f"认证成功: 用户={user_data.get('userCode')}")

    # 如果访问特定用户的资源，验证用户身份
    if user_code and user_data.get("userCode") != user_code:
        logger.warning(f"用户{user_data.get('userCode')}尝试访问{user_code}的资源")
        return Response("访问被拒绝", status=403)

    # 认证通过，处理请求
    return handle_caldav(user_code, resource_path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
