"""
SCAU2ICS CalDAV 服务模块 - 提供 CalDAV 服务功能
"""

import base64
import json
import logging
import os
from datetime import datetime

from flask import Response, request
from flask_httpauth import HTTPBasicAuth

from scau2ics.config import logger
from scau2ics.ics import generate_ics
from scau2ics.student import Student

# 创建CalDAV认证对象
caldav_auth = HTTPBasicAuth()

# CalDAV XML命名空间
DAV_NS = {
    "D": "DAV:",
    "C": "urn:ietf:params:xml:ns:caldav",
    "CS": "http://calendarserver.org/ns/",
    "ICAL": "http://apple.com/ns/ical/",
}


# CalDAV认证回调
@caldav_auth.verify_password
def verify_caldav_password(username, password):
    """验证CalDAV认证"""
    try:
        # 记录认证尝试
        logger.info(f"尝试验证用户: {username}")

        # 检查解密函数是否已设置
        decrypt_data = getattr(verify_caldav_password, "decrypt_data", None)
        if not decrypt_data:
            logger.error("CalDAV认证失败: decrypt_data函数未设置")
            return False

        try:
            # 尝试解密密码
            data = decrypt_data(password)
            logger.info(f"成功解密用户数据: {username}")
        except Exception as e:
            logger.error(f"解密用户数据失败: {str(e)}")
            return False

        # 验证用户名是否匹配
        if data.get("userCode") != username:
            logger.warning(
                f"CalDAV认证失败: 用户名不匹配 (提供的: {username}, 解密的: {data.get('userCode')})"
            )
            return False

        # 检查密码是否存在
        if "jwxt_password" not in data:
            logger.warning(f"CalDAV认证失败: 缺少必要的密码信息 {username}")
            return False

        # 认证成功，返回用户数据
        logger.info(f"CalDAV认证成功: 用户 {username}")
        return data
    except Exception as e:
        logger.error(f"CalDAV认证过程发生异常: {str(e)}")
        return False


# 设置解密函数
def set_decrypt_function(decrypt_func):
    """设置解密函数"""
    logger.info("设置CalDAV解密函数")
    setattr(verify_caldav_password, "decrypt_data", decrypt_func)


# 生成CalDAV密码令牌
def generate_caldav_password(
    encrypt_data, user_code, jwxt_password, sso_password="", semester=""
):
    """生成CalDAV密码令牌"""
    logger.info(f"为用户 {user_code} 生成CalDAV密码令牌")

    data = {
        "userCode": user_code,
        "jwxt_password": jwxt_password,
        "sso_password": sso_password,
        "semester": semester,
        "created_at": datetime.now().isoformat(),
    }

    token = encrypt_data(data)
    logger.info(f"令牌生成成功: {token[:10]}...")
    return token


# 处理CalDAV OPTIONS请求
def _handle_options():
    """处理OPTIONS请求"""
    logger.info("处理OPTIONS请求")

    response = Response("")
    response.headers.add("DAV", "1, 2, 3, calendar-access")
    response.headers.add("Allow", "OPTIONS, GET, PROPFIND, REPORT")
    response.headers.add("Content-Length", "0")
    return response


# 处理CalDAV PROPFIND请求
def _handle_propfind(user_code, resource_path):
    """处理PROPFIND请求"""
    try:
        # 记录请求详情以便调试
        depth = request.headers.get("Depth", "0")
        logger.info(
            f"处理PROPFIND请求: user_code={user_code}, path={resource_path}, depth={depth}"
        )

        # 构建基本的多状态XML响应 - 注意不要使用中文字符，避免编码问题
        xml_response = """<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" xmlns:CS="http://calendarserver.org/ns/" xmlns:ICAL="http://apple.com/ns/ical/">"""

        # 根据请求路径构建不同的响应
        if user_code is None:
            # 根目录
            xml_response += """
  <D:response>
    <D:href>/caldav/</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:displayname>Calendar Root</D:displayname>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""

            # 如果深度大于0，添加用户目录
            if depth != "0":
                xml_response += f"""
  <D:response>
    <D:href>/caldav/{user_code}/</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:displayname>User Calendar</D:displayname>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""

        elif resource_path is None:
            # 用户目录
            xml_response += f"""
  <D:response>
    <D:href>/caldav/{user_code}/</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:displayname>User Calendar</D:displayname>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""

            # 如果深度大于0，添加日历集合
            if depth != "0":
                xml_response += f"""
  <D:response>
    <D:href>/caldav/{user_code}/calendar/</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype>
          <D:collection/>
          <C:calendar/>
        </D:resourcetype>
        <D:displayname>SCAU Schedule</D:displayname>
        <C:calendar-description>SCAU Schedule - {user_code}</C:calendar-description>
        <ICAL:calendar-color>#0082C9</ICAL:calendar-color>
        <C:supported-calendar-component-set>
          <C:comp name="VEVENT"/>
        </C:supported-calendar-component-set>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""

        elif resource_path == "calendar/" or resource_path == "calendar":
            # 日历集合
            user_data = caldav_auth.current_user()
            semester_info = user_data.get("semester", "")
            display_name = f"SCAU Schedule - {user_code}"
            if semester_info:
                display_name = f"{display_name} - {semester_info}"

            xml_response += f"""
  <D:response>
    <D:href>/caldav/{user_code}/calendar/</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype>
          <D:collection/>
          <C:calendar/>
        </D:resourcetype>
        <D:displayname>{display_name}</D:displayname>
        <C:calendar-description>SCAU Schedule - {user_code}</C:calendar-description>
        <ICAL:calendar-color>#0082C9</ICAL:calendar-color>
        <C:supported-calendar-component-set>
          <C:comp name="VEVENT"/>
        </C:supported-calendar-component-set>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""

            # 如果深度大于0，添加日历文件
            if depth != "0":
                xml_response += f"""
  <D:response>
    <D:href>/caldav/{user_code}/calendar/calendar.ics</D:href>
    <D:propstat>
      <D:prop>
        <D:getcontenttype>text/calendar; charset=utf-8</D:getcontenttype>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""

        else:
            # 日历资源，如calendar.ics文件
            xml_response += f"""
  <D:response>
    <D:href>/caldav/{user_code}/calendar/{resource_path}</D:href>
    <D:propstat>
      <D:prop>
        <D:getcontenttype>text/calendar; charset=utf-8</D:getcontenttype>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""

        # 关闭XML标签
        xml_response += """
</D:multistatus>"""

        # 返回XML响应
        response = Response(xml_response, mimetype="application/xml")
        response.headers.add("Content-Type", "application/xml; charset=utf-8")
        return response

    except Exception as e:
        logger.error(f"处理PROPFIND请求错误: {str(e)}")
        return Response(f"处理PROPFIND请求错误", status=500)


# 处理CalDAV REPORT请求
def _handle_report(user_code, resource_path):
    """处理REPORT请求"""
    try:
        logger.info(
            f"处理REPORT请求: user_code={user_code}, resource_path={resource_path}"
        )

        # 获取用户认证信息并生成ICS内容
        user_data = caldav_auth.current_user()

        if user_data is None:
            logger.error("处理REPORT请求时未能获取用户数据")
            return Response(
                "Authentication required",
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="SCAU Calendar"'},
            )

        ics_content = _generate_ics_content(
            user_code,
            user_data.get("jwxt_password", ""),
            user_data.get("sso_password", ""),
            user_data.get("semester", ""),
        )

        # 构建XML响应 - 不直接包含ICS内容，避免XML解析问题
        xml_response = f"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response>
    <D:href>/caldav/{user_code}/calendar/calendar.ics</D:href>
    <D:propstat>
      <D:prop>
        <D:getetag>"etag-{datetime.now().isoformat()}"</D:getetag>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>"""

        # 返回XML响应
        response = Response(xml_response, mimetype="application/xml")
        response.headers.add("Content-Type", "application/xml; charset=utf-8")
        return response

    except Exception as e:
        logger.error(f"处理REPORT请求错误: {str(e)}")
        return Response("Error processing REPORT request", status=500)


# 处理CalDAV GET请求
def _handle_get(user_code, resource_path):
    """处理GET请求"""
    try:
        logger.info(
            f"处理GET请求: user_code={user_code}, resource_path={resource_path}"
        )

        # 获取用户认证信息并生成ICS内容
        user_data = caldav_auth.current_user()

        if user_data is None:
            logger.error("处理GET请求时未能获取用户数据")
            return Response(
                "认证失败",
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="SCAU课表日历"'},
            )

        ics_content = _generate_ics_content(
            user_code,
            user_data.get("jwxt_password", ""),
            user_data.get("sso_password", ""),
            user_data.get("semester", ""),
        )

        # 返回ICS文件内容
        response = Response(ics_content, mimetype="text/calendar")
        response.headers.add("Content-Type", "text/calendar; charset=utf-8")
        return response

    except Exception as e:
        logger.error(f"处理GET请求错误: {str(e)}")
        return Response(f"处理GET请求错误: {str(e)}", status=500)


# 从Student对象生成ICS内容
def _generate_ics_content(user_code, jwxt_password, sso_password, semester):
    """从Student对象生成ICS内容"""
    try:
        logger.info(f"为用户 {user_code} 生成ICS内容, 学期: {semester}")

        # 创建Student对象并生成ICS内容
        student = Student(user_code, jwxt_password, sso_password)
        ics_content = generate_ics(student, semester)

        logger.info(f"成功生成ICS内容，长度: {len(ics_content)}")
        return ics_content
    except Exception as e:
        logger.error(f"生成ICS内容失败: {str(e)}")
        raise


# 处理CalDAV请求的主函数
def handle_caldav(user_code=None, resource_path=None):
    """处理CalDAV请求"""
    # 记录请求详情
    logger.info(
        f"收到CalDAV请求: method={request.method}, user_code={user_code}, path={resource_path}"
    )

    # OPTIONS 请求特殊处理
    if request.method == "OPTIONS":
        return _handle_options()

    # 根据请求方法分发处理
    if request.method == "PROPFIND":
        return _handle_propfind(user_code, resource_path)
    elif request.method == "REPORT":
        return _handle_report(user_code, resource_path)
    elif request.method == "GET":
        return _handle_get(user_code, resource_path)
    else:
        return Response("不支持的方法", status=405)


# 生成CalDAV配置的API函数
def generate_config(encrypt_data, request_data, request_url_root):
    """生成CalDAV配置"""
    try:
        # 获取参数
        user_code = request_data["userCode"]
        jwxt_password = request_data["jwxt_password"]
        sso_password = request_data.get("sso_password", "")
        semester = request_data.get("semester", "")

        logger.info(f"生成用户 {user_code} 的CalDAV配置, 学期: {semester}")

        # 生成CalDAV密码
        caldav_password = generate_caldav_password(
            encrypt_data,
            user_code,
            jwxt_password,
            sso_password,
            semester,
        )

        # 构建CalDAV URL（确保以/结尾）
        caldav_url = f"{request_url_root}caldav/{user_code}/calendar/"

        # 返回配置信息
        config = {
            "caldav_url": caldav_url,
            "username": user_code,
            "password": caldav_password,
        }

        logger.info(f"成功生成CalDAV配置: {caldav_url}")
        return config

    except Exception as e:
        logger.error(f"生成CalDAV配置时发生错误: {str(e)}")
        raise
