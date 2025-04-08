# SCAU2ICS

华南农业大学课表导出为ICS日历文件工具

## 项目简介

SCAU2ICS 是一个用于将华南农业大学教务系统课表导出为 ICS 日历文件的工具。通过 ICS 文件，您可以将课表导入到各种日历应用（如 Google Calendar、Outlook、Apple Calendar 等），方便地查看和管理您的课程安排。

## 主要功能

- 从教务系统获取课表数据
- 将课表转换为标准 ICS 日历文件
- 支持命令行方式和 Web API 方式使用
- 提供缓存机制，在网络不可用时依然可以生成 ICS 文件
- 自动处理凌晨时段的统一身份认证
- 支持按关键词过滤课程
- 支持生成带有效期的共享链接

## 安装

1. 克隆仓库：

```bash
git clone https://github.com/yourusername/SCAU2ICS.git
cd SCAU2ICS
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 安装 Playwright：

```bash
playwright install firefox
```

## 使用方法

### 命令行方式

```bash
python cli.py --user-code 学号 --jwxt-password 教务系统密码 --semester 2024-2025-2 [--sso-password 统一身份认证密码] [--output 输出文件路径]
```

参数说明：

- `--user-code` 或 `-u`: 学号
- `--jwxt-password` 或 `-j`: 教务系统密码
- `--sso-password` 或 `-s`: 统一身份认证密码（可选，在凌晨0点至早上7点之间需要）
- `--semester` 或 `-m`: 学期代码，如 2024-2025-2
- `--output` 或 `-o`: 输出文件路径，默认为"学号_课表.ics"

### Web API 方式

1. 启动 Web 服务：

```bash
python server.py
```

2. 发送 POST 请求生成ICS文件：

```
POST http://localhost:5000/generate_ics
Content-Type: application/json

{
    "userCode": "2023XXXXXXXX",
    "jwxt_password": "教务系统密码",
    "sso_password": "统一身份认证密码（可选）",
    "semester": "2024-2025-2",
    "filter_keywords": [0, 1, "实验课", "讨论课"],
    "expire_days": 30
}
```

3. 发送 POST 请求生成共享链接：

```
POST http://localhost:5000/generate_url
Content-Type: application/json

{
    "userCode": "2023XXXXXXXX",
    "jwxt_password": "教务系统密码",
    "sso_password": "统一身份认证密码（可选）",
    "semester": "2024-2025-2",
    "filter_keywords": [0, 1, "实验课", "讨论课"],
    "expire_days": 30
}
```

参数说明：

- `userCode`: 学号
- `jwxt_password`: 教务系统密码
- `sso_password`: 统一身份认证密码（可选，在凌晨0点至早上7点之间需要）
- `semester`: 学期代码，如 2024-2025-2
- `filter_keywords`: 过滤关键词列表，用于排除包含关键词的课程。可传入整数调用预置关键词
- `expire_days`: 链接有效期，单位为天，0表示永不过期

### Web 界面

启动服务后，访问 <http://localhost:5000> 即可使用网页界面导出课表。

## 注意事项

- 在凌晨0点至早上7点之间，教务系统需要通过统一身份认证访问，因此需要提供统一身份认证密码
- 为确保隐私安全，请勿在公共设备上存储密码
- 本工具会缓存课表数据，以便在无法连接教务系统时使用
- 通过共享链接生成的 ICS 文件可以在有效期内直接下载，无需再次输入密码

## 项目结构

```
SCAU2ICS/
├── scau2ics/           # 主要代码包
│   ├── __init__.py     # 包初始化文件
│   ├── config.py       # 配置文件
│   ├── student.py      # Student类及课表数据获取功能
│   ├── browser.py      # 浏览器自动化相关功能
│   ├── ics.py          # ICS生成相关功能
│   └── utils.py        # 通用工具函数
├── server.py           # Flask Web服务
├── cli.py              # 命令行工具
├── templates/          # Web界面模板
│   └── index.html      # 首页模板
├── cache/              # 缓存目录
├── requirements.txt    # 依赖项
├── LICENSE             # 许可证文件
└── README.md           # 项目说明
```

## 许可证

[AGPLv3](https://www.gnu.org/licenses/agpl-3.0.html)
