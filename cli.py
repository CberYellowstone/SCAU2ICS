#!/usr/bin/env python3
"""
SCAU2ICS 命令行工具 - 用于从命令行生成ICS文件
"""
import argparse
import os
import sys
from datetime import datetime

from scau2ics.config import logger
from scau2ics.ics import generate_ics
from scau2ics.student import Student


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="SCAU2ICS - 华南农业大学课表导出为ICS日历文件"
    )
    parser.add_argument("--user-code", "-u", required=True, help="学号")
    parser.add_argument("--jwxt-password", "-j", required=True, help="教务系统密码")
    parser.add_argument(
        "--sso-password",
        "-s",
        help="统一身份认证密码（可选，在凌晨0点至早上7点之间需要）",
    )
    parser.add_argument(
        "--semester", "-m", required=True, help="学期代码，如2024-2025-2"
    )
    parser.add_argument("--output", "-o", help='输出文件路径，默认为"我的课表.ics"')

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 输出文件名
    output_file = args.output or f"{args.user_code}_课表.ics"

    try:
        # 创建学生对象
        student = Student(args.user_code, args.jwxt_password, args.sso_password or "")

        # 生成ICS内容
        logger.info(f"正在为学号 {args.user_code} 生成ICS文件...")
        ics_content = generate_ics(student, args.semester)

        # 保存ICS文件
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(ics_content)

        logger.info(f"已生成ICS文件: {os.path.abspath(output_file)}")
        return 0

    except Exception as e:
        logger.error(f"生成ICS文件时发生错误: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
