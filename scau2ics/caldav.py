"""
SCAU2ICS CalDAV 服务模块 - 基于WsgiDAV实现纯虚拟CalDAV服务
"""

import base64
import json
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from flask import Response, request
from flask_httpauth import HTTPBasicAuth
# WsgiDAV导入
from wsgidav import wsgidav_app
from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider
from wsgidav.dc.simple_dc import SimpleDomainController
from wsgidav.util import get_content_length

from scau2ics.config import logger
from scau2ics.ics import generate_ics
from scau2ics.student import Student

# 创建CalDAV认证对象
caldav_auth = HTTPBasicAuth()

# XML命名空间定义
NAMESPACES = {
    "DAV:": "D:",
    "urn:ietf:params:xml:ns:caldav": "C:",
    "http://apple.com/ns/ical/": "ICAL:",
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


# 虚拟CalDAV提供者
class VirtualCalDAVProvider(DAVProvider):
    """纯虚拟CalDAV提供者，不使用文件系统"""

    def __init__(self):
        super().__init__()
        self.user_cache = {}  # 可选的内存缓存

    def get_resource_inst(self, path, environ):
        """根据路径返回相应的虚拟资源"""
        logger.info(f"获取资源: {path}")

        # 解析路径 (如 /202325310229/calendar/)
        path_parts = path.strip("/").split("/")

        if len(path_parts) == 0 or path_parts[0] == "":
            logger.info("返回根路径")
            # 根路径，返回根集合
            return VirtualRootCollection(path, environ)

        user_code = path_parts[0]

        # 获取用户数据（从environ中）
        user_data = environ.get("scau2ics.user_data", {})
        logger.info(f"用户数据: {user_data}")

        if len(path_parts) == 1:
            # 用户路径 (/202325310229)
            return VirtualUserCollection(path, environ, user_code)

        if len(path_parts) >= 2 and path_parts[1] == "calendar":
            if len(path_parts) == 2 or (len(path_parts) == 3 and path_parts[2] == ""):
                # 日历路径 (/202325310229/calendar or /202325310229/calendar/)
                logger.info("返回日历集合")
                return VirtualCalendarCollection(path, environ, user_code, user_data)
            else:
                # 日历资源 (/202325310229/calendar/events.ics)
                return VirtualCalendarResource(path, environ, user_code, user_data)

        return None  # 未知路径返回None


# 虚拟根集合
class VirtualRootCollection(DAVCollection):
    """根集合，显示所有用户"""

    def __init__(self, path, environ):
        super().__init__(path, environ)
        self.environ = environ

    def get_display_info(self):
        return {"type": "虚拟根目录"}

    def get_member_names(self):
        """返回所有用户名称"""
        # 从环境中获取当前用户，只显示当前用户
        user_data = self.environ.get("scau2ics.user_data", {})
        user_code = user_data.get("userCode")
        return [user_code] if user_code else []

    def get_member(self, name):
        """获取指定名称的成员"""
        user_data = self.environ.get("scau2ics.user_data", {})
        user_code = user_data.get("userCode")
        if user_code and name == user_code:
            path = f"/{name}"
            return VirtualUserCollection(path, self.environ, name)
        return None

    def get_properties(self, mode=None, name_list=None):
        """返回集合属性

        Args:
            mode: 属性模式 ("allprop", "named", ...)
            name_list: 如果mode="named"，需要返回的属性名称列表
        """
        props = {
            "D:displayname": "SCAU2ICS日历",
            "D:resourcetype": "<D:collection/>",
        }

        # 如果mode是named，只返回请求的属性
        if mode == "named" and name_list:
            return {k: v for k, v in props.items() if k in name_list}
        return props


# 虚拟用户集合
class VirtualUserCollection(DAVCollection):
    """用户集合，包含日历集合"""

    def __init__(self, path, environ, user_code):
        super().__init__(path, environ)
        self.user_code = user_code
        self.environ = environ

    def get_display_info(self):
        return {"type": "用户目录"}

    def get_member_names(self):
        """返回成员名称列表"""
        return ["calendar"]

    def get_member(self, name):
        """获取指定名称的成员"""
        if name == "calendar":
            path = f"{self.path}/calendar"
            user_data = self.environ.get("scau2ics.user_data", {})
            return VirtualCalendarCollection(
                path, self.environ, self.user_code, user_data
            )
        return None

    def get_properties(self, mode=None, name_list=None):
        """返回集合属性

        Args:
            mode: 属性模式 ("allprop", "named", ...)
            name_list: 如果mode="named"，需要返回的属性名称列表
        """
        # 记录请求的属性
        if name_list:
            logger.info(f"获取用户集合属性，模式: {mode}, 名称列表: {name_list}")

        # 基本属性
        props = {
            "{DAV:}displayname": f"用户 {self.user_code}",
            "{DAV:}resourcetype": "<D:collection/>",
            # calendar-home-set 应该指向用户的主目录，即当前集合
            # 确保使用正确的路径，考虑 mount_path
            "{urn:ietf:params:xml:ns:caldav}calendar-home-set": f"<D:href>{self.get_href()}</D:href>",
        }
        logger.info(
            f"添加calendar-home-set属性: {props['{urn:ietf:params:xml:ns:caldav}calendar-home-set']}"
        )

        # 日志记录返回的属性
        if mode == "named" and name_list:
            result = {k: v for k, v in props.items() if k in name_list}
        else:
            result = props

        logger.info(f"返回用户集合属性: {result}")
        return result


# 虚拟日历集合
class VirtualCalendarCollection(DAVCollection):
    """日历集合，动态生成"""

    def __init__(self, path, environ, user_code, user_data):
        logger.info(f"创建日历集合: {path}, 用户: {user_code}")
        super().__init__(path, environ)
        self.user_code = user_code
        self.user_data = user_data
        self.environ = environ

    def get_display_info(self):
        return {"type": "日历集合"}

    def get_member_names(self):
        """返回成员名称列表"""
        # 确保至少返回一个固定的日历文件名
        logger.info("获取成员名称列表")
        return ["calendar.ics"]

    def get_member(self, name):
        """获取指定名称的成员"""
        logger.info(f"获取成员: {name}")
        if name == "calendar.ics":
            path = f"{self.path}/{name}"
            return VirtualCalendarResource(
                path, self.environ, self.user_code, self.user_data
            )
        return None

    def get_properties(self, mode=None, name_list=None):
        """返回日历属性 (修正：返回字典)

        Args:
            mode: 属性模式 ("allprop", "named", ...)
            name_list: 如果mode="named"，需要返回的属性名称列表
        """
        logger.info(f"获取日历属性，模式: {mode}, 名称列表: {name_list}")
        semester = self.user_data.get("semester", "")
        display_name = f"SCAU课表 - {self.user_code}"
        if semester:
            display_name = f"{display_name} - {semester}"

        # 属性以字典形式返回
        props = {
            "{DAV:}displayname": display_name,
            "{DAV:}resourcetype": "<D:collection/><C:calendar/>",
            "{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set": "<C:comp name='VEVENT'/>",
            "{urn:ietf:params:xml:ns:caldav}calendar-description": f"华南农业大学课表 {self.user_code}",
            "{http://apple.com/ns/ical/}calendar-color": "#0082C9",
            "{urn:ietf:params:xml:ns:caldav}calendar-timezone": "",  # 时区信息，可以根据需要添加
            "{DAV:}owner": f"<D:href>/caldav/{self.user_code}/</D:href>",  # 指向用户集合
        }

        # 如果mode是named，只返回请求的属性
        if mode == "named" and name_list:
            result = {k: v for k, v in props.items() if k in name_list}
            logger.info(f"日历集合返回属性(筛选后): {result}")
            return result

        logger.info(f"日历集合返回属性(全部): {props}")
        return props


# 虚拟日历资源
class VirtualCalendarResource(DAVNonCollection):
    """日历资源，动态生成ICS内容"""

    def __init__(self, path, environ, user_code, user_data):
        super().__init__(path, environ)
        self.user_code = user_code
        self.user_data = user_data
        self.environ = environ
        self._content = None  # 延迟初始化内容
        self._etag = None

    def get_content(self):
        """获取ICS内容（动态生成，修正：返回可迭代对象）"""
        if self._content is None:
            # 只在需要时生成ICS内容
            self._content = self._generate_ics_content()
        # WSGI需要返回可迭代的字节串
        return [self._content]

    def get_content_length(self):
        """获取内容长度"""
        content = self.get_content()
        return len(content[0]) if content else 0

    def get_content_type(self):
        """返回内容类型"""
        return "text/calendar; charset=utf-8"

    def get_creation_date(self):
        """返回创建日期"""
        return datetime.now()

    def get_last_modified(self):
        """返回最后修改日期"""
        return datetime.now()

    def get_etag(self):
        """返回ETag"""
        if self._etag is None:
            # 生成一个基于内容的ETag
            self._etag = f'"{uuid.uuid4().hex}"'
        return self._etag

    def _generate_ics_content(self):
        """生成ICS内容"""
        try:
            # 从用户数据中提取信息
            jwxt_password = self.user_data.get("jwxt_password", "")
            sso_password = self.user_data.get("sso_password", "")
            semester = self.user_data.get("semester", "")

            # 创建Student对象并生成ICS内容
            student = Student(self.user_code, jwxt_password, sso_password)
            ics_content = generate_ics(student, semester)

            logger.info(
                f"为用户 {self.user_code} 生成ICS内容成功，长度: {len(ics_content)}"
            )
            return ics_content.encode("utf-8")  # 返回字节
        except Exception as e:
            logger.error(f"生成ICS内容失败: {str(e)}")
            # 返回简单的错误ICS
            error_ics = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//SCAU2ICS//ERROR//\r\nEND:VCALENDAR\r\n"
            return error_ics.encode("utf-8")

    def get_properties(self, mode=None, name_list=None):
        """返回资源属性 (修正：添加resourcetype，getcontentlength转为字符串)

        Args:
            mode: 属性模式 ("allprop", "named", ...)
            name_list: 如果mode="named"，需要返回的属性名称列表
        """
        props = {
            "{DAV:}displayname": "calendar.ics",
            "{DAV:}resourcetype": "",  # 非集合资源类型为空
            "{DAV:}getcontenttype": self.get_content_type(),
            "{DAV:}getcontentlength": str(
                self.get_content_length()
            ),  # 属性值应为字符串
            "{DAV:}getetag": self.get_etag(),
            "{DAV:}getlastmodified": self.get_last_modified().strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            ),
        }

        # 如果mode是named，只返回请求的属性
        if mode == "named" and name_list:
            return {k: v for k, v in props.items() if k in name_list}
        return props


# 创建WsgiDAV应用
def create_caldav_app():
    """创建WsgiDAV应用"""
    config = {
        "provider_mapping": {"/": VirtualCalDAVProvider()},
        "mount_path": "/caldav",
        "verbose": 1,
        # 完全禁用认证 - 因为我们已经在Flask层面处理了认证
        "http_authenticator": {
            "accept_basic": False,
            "accept_digest": False,
            "default_to_digest": False,
            "trusted_auth_header": None,
        },
        # 简单域控制器配置
        "simple_dc": {
            "user_mapping": {"*": True},  # 允许所有访问
        },
        "logging": {
            "enable_loggers": [],
        },
        "lock_storage": None,  # 不需要锁管理（只读）
    }
    return wsgidav_app.WsgiDAVApp(config)


# 全局应用实例
caldav_app = create_caldav_app()


# 处理CalDAV请求
def handle_caldav(user_code=None, resource_path=None):
    """处理CalDAV请求"""
    # 对于OPTIONS请求，特殊处理提供正确的headers
    if request.method == "OPTIONS":
        response = Response("")
        response.headers.add("DAV", "1, 2, 3, calendar-access")
        response.headers.add(
            "Allow",
            "OPTIONS, GET, PROPFIND, REPORT",
        )
        response.headers.add("Content-Length", "0")
        return response

    # 获取用户认证信息
    user_data = caldav_auth.current_user()
    if user_data is None:
        logger.error("处理CalDAV请求时未能获取用户数据")
        return Response(
            "Authentication required",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="SCAU Calendar"'},
        )

    try:
        # 准备环境变量
        environ = request.environ.copy()

        # 添加用户信息到环境
        environ["scau2ics.user_data"] = user_data

        # 修改路径
        if resource_path:
            path_info = f"/{user_code}/calendar/{resource_path}"
        elif user_code:
            path_info = f"/{user_code}/calendar/"
        else:
            path_info = "/"
        environ["PATH_INFO"] = path_info

        logger.info(f"准备处理CalDAV请求: PATH_INFO={path_info}")

        # 调用WsgiDAV应用
        def start_response(status, headers, exc_info=None):
            """WSGI响应函数

            Args:
                status: HTTP状态码字符串，如 "200 OK"
                headers: HTTP头部列表，每个元素为(name, value)元组
                exc_info: 可选的异常信息，用于错误处理
            """
            nonlocal response_status, response_headers
            response_status = status
            response_headers = headers
            return lambda x: None

        # 初始化响应变量
        response_status = "200 OK"
        response_headers = []

        # 收集响应体
        body_parts = []
        for chunk in caldav_app(environ, start_response):
            if chunk:
                body_parts.append(
                    chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
                )

        # 组合响应体
        body = b"".join(body_parts)

        # 提取状态码
        status_code = int(response_status.split()[0])

        # 创建Flask响应
        response = Response(body, status=status_code)

        # 添加响应头
        for name, value in response_headers:
            response.headers.add(name, value)

        logger.info(f"CalDAV响应: 状态={status_code}, 内容长度={len(body)}")
        return response

    except Exception as e:
        logger.error(f"处理CalDAV请求失败: {str(e)}")
        import traceback

        logger.error(traceback.format_exc())
        return Response(f"处理CalDAV请求失败: {str(e)}", status=500)


# 生成CalDAV配置
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
