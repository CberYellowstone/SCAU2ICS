"""
学生模块 - 提供学生课表数据获取与处理功能
"""

import datetime
import os
import re
from collections import namedtuple
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from scau2ics.browser import get_browser_manager
from scau2ics.config import CACHE_DIR, CLASS_TIMES, JWXT_URL, JWXT_URL_BACKUP, logger
from scau2ics.utils import (
    get_cache_timestamp,
    get_captcha,
    load_json_cache,
    save_json_cache,
    verify_captcha,
)

# 常量定义
TZ_UTC8 = timezone(timedelta(hours=8))
NIGHT_START = datetime.time(0, 0)
NIGHT_END = datetime.time(7, 0)
PKGL_ID = "W134dad10002bJ"  # 教务系统常量

# 课程信息数据结构
CourseInfo = namedtuple(
    "CourseInfo",
    [
        "course_name",
        "class_name",
        "course_id",
        "course_weeks",
        "teacher_name",
        "classroom",
        "start_time",
        "end_time",
        "course_type",
        "group_name",
        "day_of_week",
    ],
)


class Student:
    """学生类，处理学生认证和课表获取"""

    def __init__(
        self, userCode: str, jwxt_password: str, sso_password: str = ""
    ) -> None:
        """
        初始化学生对象

        Args:
            userCode: 学号
            jwxt_password: 教务系统密码
            sso_password: 统一身份认证密码（可选）
        """
        self.userCode = userCode
        self.jwxt_password = jwxt_password
        self.sso_password = sso_password
        self.base_cache_file = os.path.join(CACHE_DIR, f"cache_{userCode}")
        self.token: Optional[str] = None
        self.cookies: Optional[Dict[str, str]] = None
        self.session: Optional[str] = None
        self.is_night_mode = self._is_night_time()
        self.base_url = JWXT_URL_BACKUP if self.is_night_mode else JWXT_URL

        # 尝试登录，登录失败时尝试使用缓存
        self._initialize_session()

    def _get_cache_file_for_semester(self, semester: str) -> str:
        """获取特定学期的缓存文件路径"""
        return f"{self.base_cache_file}_{semester}.json"

    def _is_night_time(self) -> bool:
        """判断当前是否为夜间时段（0点至7点）"""
        current_time = datetime.datetime.now(TZ_UTC8).time()
        return NIGHT_START <= current_time <= NIGHT_END

    def _initialize_session(self) -> None:
        """初始化会话，尝试登录或使用缓存"""
        try:
            self._setup_session()
            success, message = self.do_login()
            if not success:
                logger.error(f"登录失败: {message}")
                self._try_use_cache()
        except Exception as e:
            logger.error(f"初始化会话失败: {str(e)}")
            self._try_use_cache(str(e))

    def _try_use_cache(self, error_msg: str = "") -> None:
        """尝试使用缓存数据"""
        # 检查是否存在任何学期的缓存文件
        cache_files = [
            f for f in os.listdir(CACHE_DIR) if f.startswith(f"cache_{self.userCode}_")
        ]
        if cache_files:
            logger.info(f"找到缓存数据: {cache_files}")
        else:
            msg = "无法登录且没有找到缓存数据"
            if error_msg:
                msg += f": {error_msg}"
            raise Exception(msg)

    def _setup_session(self) -> None:
        """根据时间段设置会话"""
        if self.is_night_mode:
            self._setup_night_session()
        else:
            self._setup_day_session()

    def _setup_night_session(self) -> None:
        """设置夜间模式会话（使用SSO登录）"""
        if not self.sso_password:
            logger.warning("在夜间模式下需要提供统一身份认证密码，将尝试使用缓存")
            self.session = ""
            self.cookies = {"SESSION": "", "token": "", "casLogin": ""}
            return

        try:
            browser_mgr = get_browser_manager()
            self.session, self.cookies = browser_mgr.perform_sso_login(
                f"{self.base_url}/", self.userCode, self.sso_password
            )
            logger.info(f"统一身份认证登录成功: {self.userCode}")
        except Exception as e:
            logger.error(f"统一身份认证登录失败: {str(e)}")
            raise

    def _setup_day_session(self) -> None:
        """设置日间模式会话"""
        login_url = f"{self.base_url}/"
        r = requests.get(login_url, verify=False)
        session_cookie = r.headers.get("Set-Cookie", "")

        # 使用split提取SESSION值，更简洁可靠
        session_parts = [p for p in session_cookie.split(";") if "SESSION=" in p]
        if session_parts:
            self.session = session_parts[0].split("=")[1]
        else:
            self.session = ""
            logger.warning("未能从响应中提取SESSION值")

        self.cookies = {"SESSION": self.session, "token": "", "casLogin": ""}

    def do_login(self) -> Tuple[bool, Optional[str]]:
        """执行登录操作，返回(成功状态, 错误消息)"""
        if self.cookies is None:
            return False, "会话未初始化，cookies为空"

        captcha = get_captcha(self.cookies, self.base_url)
        success, message = verify_captcha(captcha, self.cookies, self.base_url)
        if not success:
            return False, f"验证码错误: {message}"

        login_url = f"{self.base_url}/secService/login"
        headers = {
            "KAPTCHA-KEY-GENERATOR-REDIS": "securityKaptchaRedisServiceAdapter",
            "app": "PCWEB",
            "Accept": "application/json, text/plain",
        }
        data = {
            "userCode": self.userCode,
            "password": self.jwxt_password,
            "kaptcha": captcha,
            "userCodeType": "account",
        }

        rep = requests.post(
            login_url, json=data, cookies=self.cookies, headers=headers, verify=False
        )
        result = rep.json()

        if result["errorCode"] != "success":
            return False, result["errorMessage"]

        self.token = result["data"]["token"]
        if self.token is not None:
            self.cookies["token"] = self.token
        return True, None

    def get_user_info(self) -> Dict[str, Any]:
        """获取用户信息"""
        timestamp = int(datetime.datetime.now().timestamp() * 1000)
        url = f"{self.base_url}/secService/assert.json?resourceCode=resourceCode&apiCode=framework.sign.controller.SignController.asserts&t={timestamp}"
        headers = {
            "TOKEN": self.token,
            "Accept": "application/json, text/plain",
            "app": "PCWEB",
        }
        rep = requests.get(url, headers=headers, cookies=self.cookies, verify=False)
        return rep.json()

    def get_first_monday_date(self, semester: str) -> datetime.datetime:
        """
        获取学期的第一周周一日期

        Args:
            semester: 学期代码，必须提供

        Returns:
            datetime.datetime: 第一周周一的日期（datetime对象）
        """
        url = f"{self.base_url}/resService/jwxtpt/v1/jczy/educationInfo_jxzlInfo/findWeekCalendarListHnnydx?resourceCode=XSMH1701&apiCode=jw.jczy.educationinfo.controller.WeekCalendarInfoController.findWeekCalendarListHnnydx"
        headers = {
            "TOKEN": self.token,
            "Accept": "application/json, text/plain",
            "app": "PCWEB",
        }
        data = {"xnxq": semester}
        rep = requests.post(
            url, headers=headers, cookies=self.cookies, json=data, verify=False
        )
        result = rep.json()
        if result["errorCode"] != "success":
            raise Exception(f"获取第一周星期一日期失败: {result['errorMessage']}")
        # date["rq"] 是 形如 "1739203200000" 的时间戳
        dates = sorted(
            [date["rq"] for date in result["data"] if date["jxzlys_name"] != "非上课"]
        )
        # 获取第一个日期，最小的即为第一周星期一的日期
        first_monday_timestamp = dates[0]
        first_monday_date = datetime.datetime.fromtimestamp(
            first_monday_timestamp / 1000, TZ_UTC8
        )
        return first_monday_date

    def get_course_schedule(self, semester) -> Optional[Dict[str, Any]]:
        """
        获取学生课表数据，出错时尝试使用缓存

        Args:
            semester: 学期代码，必须提供
        """
        try:
            # 确保必须提供学期
            if semester is None:
                raise ValueError("必须提供学期参数")

            # 获取特定学期的缓存文件
            cache_file = self._get_cache_file_for_semester(semester)

            course_schedule = self._fetch_course_schedule(semester)
            # 保存到特定学期的缓存文件
            save_json_cache(cache_file, course_schedule)
            return course_schedule
        except Exception as e:
            logger.error(f"获取课表失败: {str(e)}")
            return self._load_cached_schedule(semester, str(e))

    def _fetch_course_schedule(self, semester) -> Dict[str, Any]:
        """
        从教务系统获取课表数据

        Args:
            semester: 学期代码，必须提供
        """
        # 确保必须提供学期
        if semester is None:
            raise ValueError("必须提供学期参数")

        url = f"{self.base_url}/resService/jwxtpt/v1/xsd/xsdqxxkb_info/searchOneXskbList?resourceCode=XSMH0701&apiCode=jw.xsd.xsdInfo.controller.XsdQxxkbController.searchOneXskbList"
        headers = {
            "TOKEN": self.token,
            "Accept": "application/json, text/plain",
            "app": "PCWEB",
        }
        data = {
            "jczy013id": semester,
            "pkgl002id": PKGL_ID,
            "zt": "2",
            "sctype": "hnnydx",
        }
        rep = requests.post(
            url, headers=headers, cookies=self.cookies, json=data, verify=False
        )
        return rep.json()

    def _load_cached_schedule(
        self, semester: str, error_msg: str
    ) -> Optional[Dict[str, Any]]:
        """从缓存加载课表数据"""
        cache_file = self._get_cache_file_for_semester(semester)
        if os.path.exists(cache_file):
            logger.info(f"从缓存加载课表数据: {cache_file}")
            cache_data = load_json_cache(cache_file)
            if cache_data and "data" in cache_data:
                return cache_data["data"]

        raise Exception(f"获取课表失败，且无可用缓存: {error_msg}")

    def get_start_end_time(self, class_numbers: str) -> Tuple[str, str]:
        """
        获取课程的开始和结束时间

        Args:
            class_numbers: 课程节次字符串，如"303,304,305"
        """
        class_numbers = re.sub(r"\s+", "", class_numbers)
        class_nums_list = class_numbers.split(",")
        start_time = CLASS_TIMES[class_nums_list[0][-2:]][0]
        end_time = CLASS_TIMES[class_nums_list[-1][-2:]][-1]
        return start_time, end_time

    def parse_course_schedule(
        self, course_schedule: Optional[Dict[str, Any]]
    ) -> Dict[str, CourseInfo]:
        """解析课表数据为CourseInfo对象字典"""
        if not course_schedule or "data" not in course_schedule:
            return {}

        courses_dict = {}
        for course in course_schedule["data"]:
            # 提取星期几（0-6，其中0代表周一）
            day_of_week = int(course.get("pksj", "10000")[0]) - 1

            course_info = CourseInfo(
                course_name=course["kc_name"],
                class_name=course["ktmc_name"],
                course_id=course["id"],
                course_weeks=course["pkzc_1"],
                teacher_name=course["teachernames"],
                classroom=course["js_name"],
                start_time=course["djkssj"],
                end_time=course["djjssj"],
                course_type=course["xslx_name_1"],
                group_name=course["fzmc_name"],
                day_of_week=day_of_week,
            )
            # start_time 和 end_time 有可能是空字符串，此时需要fallback使用pksjmx字段配合get_start_end_time方法
            if not course_info.start_time or not course_info.end_time:
                logger.warning(
                    f"课程 {course_info.course_name} 的上课时间或下课时间为空，尝试从pksjmx字段获取"
                )
                class_numbers = course["pksjmx"]
                start_time, end_time = self.get_start_end_time(class_numbers)
                logger.warning(
                    f"使用pksjmx字段获取的上课时间: {start_time}, 下课时间: {end_time}"
                )
                course_info = course_info._replace(
                    start_time=start_time, end_time=end_time
                )
            courses_dict[course["id"]] = course_info

        return courses_dict

    def get_cache_update_time(self, semester: str) -> Optional[str]:
        """
        获取缓存的更新时间

        Args:
            semester: 学期代码
        """
        cache_file = self._get_cache_file_for_semester(semester)
        return get_cache_timestamp(cache_file)

    def parse_course_weeks(self, course_weeks: str) -> List[Tuple[int, int]]:
        """
        解析排课周次

        Args:
            course_weeks: 排课周次字符串，如"1-8,10,12-13"

        Returns:
            周次列表，每个元素为(开始周，结束周)的元组
        """
        weeks = []
        for week_range in course_weeks.split(","):
            if "-" in week_range:
                start, end = map(int, week_range.split("-"))
                weeks.append((start, end))
            else:
                week = int(week_range)
                weeks.append((week, week))
        return weeks

    def print_course_schedule(self, semester) -> None:
        """
        打印课表信息（用于调试）

        Args:
            semester: 学期代码，必须提供
        """
        course_schedule = self.get_course_schedule(semester)
        courses_dict = self.parse_course_schedule(course_schedule)

        for _, course_info in courses_dict.items():
            print(
                f"课程ID: {course_info.course_id}\n"
                f"课程名称: {course_info.course_name}\n"
                f"班级名称: {course_info.class_name}\n"
                f"教师名称: {course_info.teacher_name}\n"
                f"教室名称: {course_info.classroom}\n"
                f"开始时间: {course_info.start_time}\n"
                f"结束时间: {course_info.end_time}\n"
                f"课程类型: {course_info.course_type}\n"
                f"分组: {course_info.group_name}\n"
                f"排课周次: {course_info.course_weeks}\n"
                f"星期: {course_info.day_of_week+1}\n"
            )
