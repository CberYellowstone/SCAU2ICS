"""
SCAU2ICS Web服务 - 提供Web API生成ICS文件
"""

import json
from datetime import datetime
from datetime import time as dt_time
from typing import Any, Dict, Optional, Tuple

from flask import Flask, Response, request

from scau2ics.config import logger
from scau2ics.ics import generate_ics
from scau2ics.student import Student

app = Flask(__name__)

# 常量
NIGHT_START = dt_time(0, 0)
NIGHT_END = dt_time(7, 0)
REQUIRED_FIELDS = ["userCode", "jwxt_password", "first_monday_date"]


@app.route("/generate_ics", methods=["POST"])
def handle_generate_ics():
    """处理ICS生成请求"""
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
    """首页，提供简单的使用说明"""
    return """
    <html>
        <head>
            <title>SCAU2ICS - 华南农业大学课表导出为ICS日历</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
                h1 { color: #4CAF50; }
                code { background-color: #f5f5f5; padding: 2px 4px; border-radius: 4px; }
                pre { background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }
            </style>
        </head>
        <body>
            <h1>SCAU2ICS - 华南农业大学课表导出为ICS日历</h1>
            <p>使用POST请求访问 <code>/generate_ics</code> 接口生成ICS文件。</p>
            <h2>请求格式示例:</h2>
            <pre>
{
    "userCode": "2023XXXXXXXX",
    "jwxt_password": "教务系统密码",
    "sso_password": "统一身份认证密码（可选）",
    "first_monday_date": "2025-02-17"
}
            </pre>
            <p>其中 <code>sso_password</code> 是可选的，但在0点至7点之间需要提供。</p>
            <p><code>first_monday_date</code> 是开学第一周的周一日期，格式为YYYY-MM-DD</p>
            <p>更多信息请访问 <a href="https://github.com/yourusername/SCAU2ICS">GitHub项目</a></p>
        </body>
    </html>
    """


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
