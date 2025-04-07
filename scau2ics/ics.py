"""
ICS 生成模块 - 提供课表到ICS日历文件的转换功能
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from scau2ics.config import logger
from scau2ics.student import CourseInfo, Student

# ICS常量
ICS_FILE_HEADER = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//SCAU2ICS//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
]
ICS_FILE_FOOTER = ["END:VCALENDAR"]

# 时区信息
TIMEZONE = "Asia/Shanghai"


def generate_ics(student: Student, semester: str) -> str:
    """
    生成ICS日历文件字符串

    Args:
        student: 学生对象
        semester: 学期代码，必须提供

    Returns:
        ICS文件内容的字符串
    """
    # 获取第一周周一的日期（直接获取datetime对象）
    first_monday = student.get_first_monday_date(semester)

    # 获取课程表
    course_schedule = student.get_course_schedule(semester)
    courses_dict = student.parse_course_schedule(course_schedule)
    logger.info(f"获取到 {first_monday.strftime('%Y-%m-%d')} 作为第一周周一")

    # 获取缓存更新时间，传递学期参数
    cache_update_time = student.get_cache_update_time(
        semester
    ) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 构建ICS内容
    ics_content = ICS_FILE_HEADER.copy()

    # 添加课表更新时间提示事件
    add_update_time_events(ics_content, cache_update_time)

    # 添加课程事件
    add_course_events(ics_content, courses_dict, first_monday, student)

    # 添加文件尾
    ics_content.extend(ICS_FILE_FOOTER)

    return "\n".join(ics_content)


def add_update_time_events(ics_content: List[str], cache_update_time: str) -> None:
    """
    添加显示更新时间的事件

    Args:
        ics_content: ICS内容列表
        cache_update_time: 缓存更新时间
    """
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    # 更新通知事件的基本属性
    summary = f"课表数据更新于 {cache_update_time}"
    description = "此事件显示课表数据最后从教务系统获取的时间"

    # 添加今天和明天的更新时间事件
    for day in [today, tomorrow]:
        event_dt = datetime.combine(day, datetime.min.time()).replace(hour=7, minute=0)
        event_end_dt = event_dt.replace(minute=30)

        event = [
            "BEGIN:VEVENT",
            f"UID:{str(uuid.uuid4())}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            f"DTSTART;TZID={TIMEZONE}:{event_dt.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID={TIMEZONE}:{event_end_dt.strftime('%Y%m%dT%H%M%S')}",
            "END:VEVENT",
        ]
        ics_content.extend(event)


def add_course_events(
    ics_content: List[str],
    courses_dict: Dict[str, CourseInfo],
    first_monday: datetime,
    student: Student,
) -> None:
    """
    添加课程事件

    Args:
        ics_content: ICS内容列表
        courses_dict: 课程信息字典
        first_monday: 第一周周一日期
        student: 学生对象（用于解析周次）
    """
    for _, course_info in courses_dict.items():
        # 解析排课周次
        weeks = student.parse_course_weeks(course_info.course_weeks)

        # 解析上课和下课时间
        try:
            start_hour, start_minute = map(int, course_info.start_time.split(":"))
            end_hour, end_minute = map(int, course_info.end_time.split(":"))
        except Exception as e:
            logger.error(f"解析上课时间失败: {e}")
            logger.warning(f"课程 {course_info.course_name} 的上课时间格式不正确")
            continue

        # 准备事件信息
        course_type = f"({course_info.course_type})" if course_info.course_type else ""
        group_name = f"[{course_info.group_name}]" if course_info.group_name else ""

        event_props = {
            "summary": f"{course_info.course_name}{course_type}{group_name}",
            "description": f"{course_info.teacher_name} | {course_info.class_name}",
            "location": course_info.classroom,
            "day_of_week": course_info.day_of_week,
            "start_hour": start_hour,
            "start_minute": start_minute,
            "end_hour": end_hour,
            "end_minute": end_minute,
        }

        # 为每个连续周次创建单独的事件
        for start_week, end_week in weeks:
            create_course_event(
                ics_content,
                first_monday,
                start_week,
                end_week,
                **event_props,
            )


def create_course_event(
    ics_content: List[str],
    first_monday: datetime,
    start_week: int,
    end_week: int,
    summary: str,
    description: str,
    location: str,
    day_of_week: int,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> None:
    """
    创建单个课程事件

    Args:
        ics_content: ICS内容列表
        first_monday: 第一周周一日期
        start_week: 开始周次
        end_week: 结束周次
        summary: 事件标题
        description: 事件描述
        location: 事件地点
        day_of_week: 星期几（0-6）
        start_hour: 开始小时
        start_minute: 开始分钟
        end_hour: 结束小时
        end_minute: 结束分钟
    """
    # 计算事件时间
    event_start_date = first_monday + timedelta(days=day_of_week, weeks=start_week - 1)
    event_start = event_start_date.replace(hour=start_hour, minute=start_minute)
    event_end = event_start_date.replace(hour=end_hour, minute=end_minute)

    # 格式化日期时间
    start_str = event_start.strftime("%Y%m%dT%H%M%S")
    end_str = event_end.strftime("%Y%m%dT%H%M%S")

    # 创建事件
    event = [
        "BEGIN:VEVENT",
        f"UID:{str(uuid.uuid4())}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description}",
        f"LOCATION:{location}",
        f"DTSTART;TZID={TIMEZONE}:{start_str}",
        f"DTEND;TZID={TIMEZONE}:{end_str}",
    ]

    # 添加重复规则
    if start_week != end_week:
        repeat_count = end_week - start_week + 1
        event.append(f"RRULE:FREQ=WEEKLY;COUNT={repeat_count}")

    event.append("END:VEVENT")
    ics_content.extend(event)
