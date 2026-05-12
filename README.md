# Medical 智慧医疗问诊与管理系统

基于 Django 5 的智慧医疗问诊与医院业务管理系统，覆盖患者注册、AI 预问诊、挂号预约、医生接诊、电子病历、处方执行、药品库存、采购审批和后台运营管理等流程。

## 功能特性

- 多角色权限：患者、医生、护士、护士长、管理员。
- 患者端：注册登录、邮箱验证码、AI 预问诊、科室/医生/排班浏览、在线挂号、个人资料、订单和病历查询。
- 医生端：待接诊队列、查看 AI 报告、录入诊断、开具处方。
- 护士端：分诊体征录入、处方发药、药品采购申请。
- 护士长端：库存查看、采购申请审批。
- 管理端：员工账号、患者账号、科室、排班、药品、厂商、订单流水、操作日志、门户配置等管理。
- AI 能力：接入 DeepSeek Chat API，生成多轮预问诊回复和结构化 `AIReport`。

## 技术栈

- Python 3.x
- Django 5.x
- MySQL 8.x / utf8mb4
- Django Templates
- PyMySQL
- Pillow

## 项目结构

```text
Medical/              Django 项目配置
core/                 核心业务应用、模型、视图、服务和迁移
templates/            页面模板
static/               静态资源
media/                本地上传文件目录，默认不提交到 Git
requirements.txt      Python 依赖
spec.md               系统设计规范
```

## 本地运行

1. 创建并启用虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. 安装依赖：

```powershell
pip install -r requirements.txt
```

3. 创建 MySQL 数据库：

```sql
CREATE DATABASE medical DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

4. 配置环境变量，可参考 `.env.example`。PowerShell 示例：

```powershell
$env:DJANGO_SECRET_KEY = "your-secret-key"
$env:MYSQL_DATABASE = "medical"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = "your-mysql-password"
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_PORT = "3306"
$env:DEEPSEEK_API_KEY = "your-deepseek-api-key"
```

如需启用 QQ 邮箱验证码，请额外设置：

```powershell
$env:QQ_EMAIL = "your@qq.com"
$env:QQ_EMAIL_AUTH_CODE = "your-smtp-auth-code"
```

5. 执行迁移并创建管理员：

```powershell
python manage.py migrate
python manage.py createsuperuser
```

6. 启动开发服务器：

```powershell
python manage.py runserver
```

访问地址：

- 门户首页：`http://127.0.0.1:8000/portal/`
- 登录页：`http://127.0.0.1:8000/accounts/login/`
- 管理后台：`http://127.0.0.1:8000/manage/dashboard/`
- Django Admin：`http://127.0.0.1:8000/sys-admin/`

## 账号规则

患者可在前台自行注册。医生、护士、护士长和管理员账号由管理员创建，系统按角色前缀自动生成用户名，例如 `doc1`、`nur1`、`nur_head1`、`admin1`。医护和管理账号首次登录后需要修改初始密码。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `DJANGO_SECRET_KEY` | Django 密钥，生产环境必须设置 |
| `DJANGO_DEBUG` | 是否开启调试模式 |
| `DJANGO_ALLOWED_HOSTS` | 允许访问的域名/IP，逗号分隔 |
| `MYSQL_DATABASE` | MySQL 数据库名 |
| `MYSQL_USER` | MySQL 用户名 |
| `MYSQL_PASSWORD` | MySQL 密码 |
| `MYSQL_HOST` | MySQL 地址 |
| `MYSQL_PORT` | MySQL 端口 |
| `QQ_EMAIL` | QQ 邮箱账号，用于发送验证码 |
| `QQ_EMAIL_AUTH_CODE` | QQ 邮箱 SMTP 授权码 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `DEEPSEEK_API_BASE` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | DeepSeek 模型名 |
| `DEEPSEEK_TIMEOUT` | API 请求超时时间 |

## 安全说明

请不要将 `.env`、数据库文件、上传文件、邮箱授权码、API Key 或 GitHub Token 提交到仓库。生产环境应关闭 `DJANGO_DEBUG`，设置强随机 `DJANGO_SECRET_KEY`，并使用独立数据库账号。
