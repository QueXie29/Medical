# 智慧医疗问诊与管理系统 — 安装部署与使用说明

> **版本**：与仓库当前代码同步  
> **最后更新**：2026-06-17

---

## 目录

1. [系统简介](#1-系统简介)
2. [环境要求](#2-环境要求)
3. [安装与部署](#3-安装与部署)
   - 3.1 [获取源码](#31-获取源码)
   - 3.2 [创建 Python 虚拟环境](#32-创建-python-虚拟环境)
   - 3.3 [安装 Python 依赖](#33-安装-python-依赖)
   - 3.4 [数据库配置（MySQL）](#34-数据库配置mysql)
   - 3.5 [环境变量配置](#35-环境变量配置)
   - 3.6 [初始化数据库（迁移）](#36-初始化数据库迁移)
   - 3.7 [创建超级管理员](#37-创建超级管理员)
   - 3.8 [收集静态文件（生产环境）](#38-收集静态文件生产环境)
   - 3.9 [启动开发服务器](#39-启动开发服务器)
4. [生产环境部署建议](#4-生产环境部署建议)
5. [系统使用说明](#5-系统使用说明)
   - 5.1 [系统角色与权限概览](#51-系统角色与权限概览)
   - 5.2 [系统入口地址](#52-系统入口地址)
   - 5.3 [管理员操作指南](#53-管理员操作指南)
   - 5.4 [患者操作指南](#54-患者操作指南)
   - 5.5 [医生操作指南](#55-医生操作指南)
   - 5.6 [护士操作指南](#56-护士操作指南)
   - 5.7 [护士长操作指南](#57-护士长操作指南)
6. [数据库表结构总览](#6-数据库表结构总览)
7. [常见问题与排错](#7-常见问题与排错)
8. [安全注意事项](#8-安全注意事项)

---

## 1. 系统简介

本系统是一套基于 **Django 5.x** 的 **HIS（Hospital Information System）智慧医疗问诊与管理系统**，采用 **MySQL 8.x** 作为后端数据库，前端使用 **Django 模板引擎** 结合 **Bootstrap 5**、**Font Awesome 6** 和 **Chart.js** 构建。

系统覆盖以下核心业务流程：

- **患者端**：注册登录、邮箱验证码、AI 智能预问诊（基于 DeepSeek 大模型）、科室与排班浏览、在线挂号预约、个人资料管理、账单查询、病历查看
- **医生端**：待接诊队列管理、查看 AI 预问诊报告、录入诊断与病历、开具电子处方
- **护士端**：患者分诊与体征录入、处方发药执行、药品采购申请
- **护士长端**：药品库存查看、采购申请审批
- **管理端**：员工账号管理、患者账号运维、科室/排班/药品/厂商维护、订单流水查看、财务统计、操作日志审计、医院门户配置

---

## 2. 环境要求

在安装前，请确保满足以下软件环境要求：

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| **操作系统** | Windows 10/11、Linux、macOS | 均可，本文以 Windows PowerShell 为例 |
| **Python** | 3.10 及以上 | 需与 Django 5.x 兼容 |
| **MySQL** | 8.0 及以上 | 字符集须为 `utf8mb4` |
| **pip** | 最新版 | 随 Python 附带，建议升级 |
| **Git**（可选） | 任意版本 | 用于克隆源码 |

> **提示**：系统使用 `PyMySQL` 作为 MySQL 驱动，无需额外安装 C 语言编译的 `mysqlclient` 库。

---

## 3. 安装与部署

### 3.1 获取源码

**方式一：Git 克隆**

```powershell
git clone <仓库地址> Medical
cd Medical
```

**方式二：直接下载**

下载源码压缩包并解压到目标目录，进入项目根目录（包含 `manage.py` 文件的目录）。

### 3.2 创建 Python 虚拟环境

在项目根目录下执行：

```powershell
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境（Windows PowerShell）
.\.venv\Scripts\Activate.ps1

# 激活虚拟环境（Windows CMD）
.\.venv\Scripts\activate.bat

# 激活虚拟环境（Linux / macOS）
source .venv/bin/activate
```

激活成功后，命令行前方会出现 `(.venv)` 前缀标识。

### 3.3 安装 Python 依赖

```powershell
pip install -r requirements.txt
```

`requirements.txt` 包含以下核心依赖：

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| `Django` | ≥5.0, <6 | Web 框架 |
| `PyMySQL` | ≥1.1.0 | MySQL 数据库驱动 |
| `Pillow` | ≥10.0.0 | 图像处理（用于上传头像、门户图片等） |

> **注意**：如果 pip 版本较旧，建议先执行 `pip install --upgrade pip`。

### 3.4 数据库配置（MySQL）

#### 3.4.1 安装 MySQL

如尚未安装 MySQL，请先安装 **MySQL 8.0** 或更高版本。

- **Windows**：访问 [MySQL 官网](https://dev.mysql.com/downloads/installer/) 下载 MySQL Installer
- **Linux（Ubuntu/Debian）**：`sudo apt install mysql-server`
- **macOS**：`brew install mysql`

#### 3.4.2 创建数据库

登录 MySQL 客户端，执行以下 SQL 语句创建专用数据库：

```sql
-- 创建数据库，使用 utf8mb4 字符集
CREATE DATABASE medical
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
```

**（可选）创建专用数据库用户**（生产环境推荐）：

```sql
-- 创建用户
CREATE USER 'medical_user'@'localhost' IDENTIFIED BY '你的强密码';

-- 授权
GRANT ALL PRIVILEGES ON medical.* TO 'medical_user'@'localhost';

-- 刷新权限
FLUSH PRIVILEGES;
```

#### 3.4.3 数据库连接配置

数据库连接通过环境变量配置，详见下一节。系统在 `Medical/settings.py` 中的数据库配置如下：

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",     # MySQL 后端
        "NAME":     os.environ.get("MYSQL_DATABASE", "medical"),
        "USER":     os.environ.get("MYSQL_USER", "root"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
        "HOST":     os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "PORT":     os.environ.get("MYSQL_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}
```

> **关键参数说明**：
> - `charset: utf8mb4`：支持完整 Unicode（含 Emoji 等4字节字符）
> - `STRICT_TRANS_TABLES`：严格模式，数据插入时不允许隐式截断

### 3.5 环境变量配置

项目根目录下提供了 `.env.example` 文件作为模板。请复制一份为 `.env` 并填入实际值：

```powershell
copy .env.example .env
```

然后编辑 `.env` 文件：

```ini
# ============== Django 核心 ==============
# Django 密钥（生产环境必须替换为随机字符串！）
DJANGO_SECRET_KEY=你的随机密钥字符串

# 调试模式（生产环境必须设为 false）
DJANGO_DEBUG=true

# 允许访问的域名/IP（逗号分隔）
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# ============== MySQL 数据库 ==============
MYSQL_DATABASE=medical
MYSQL_USER=root
MYSQL_PASSWORD=你的MySQL密码
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306

# ============== QQ 邮箱验证码（可选） ==============
# 用于注册验证码和找回密码功能
# 需要在 QQ 邮箱设置中开启 POP3/SMTP 服务并获取授权码
QQ_EMAIL=你的QQ邮箱@qq.com
QQ_EMAIL_AUTH_CODE=你的SMTP授权码

# ============== DeepSeek AI（可选） ==============
# 用于 AI 智能预问诊功能
DEEPSEEK_API_KEY=你的DeepSeek API Key
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT=120
```

**环境变量完整说明表**：

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `DJANGO_SECRET_KEY` | 生产必填 | 内置不安全值 | Django 密钥，用于加密签名。**生产环境必须设置为随机字符串** |
| `DJANGO_DEBUG` | 否 | `true` | 调试模式开关。**生产环境必须设为 `false`** |
| `DJANGO_ALLOWED_HOSTS` | 生产必填 | `localhost,127.0.0.1` | 允许的域名或 IP，逗号分隔 |
| `MYSQL_DATABASE` | 否 | `medical` | MySQL 数据库名 |
| `MYSQL_USER` | 否 | `root` | MySQL 用户名 |
| `MYSQL_PASSWORD` | 是 | 空 | MySQL 密码 |
| `MYSQL_HOST` | 否 | `127.0.0.1` | MySQL 服务器地址 |
| `MYSQL_PORT` | 否 | `3306` | MySQL 端口号 |
| `QQ_EMAIL` | 否 | 空 | QQ 邮箱地址，用于发送验证码邮件 |
| `QQ_EMAIL_AUTH_CODE` | 否 | 空 | QQ 邮箱 SMTP 授权码（非 QQ 登录密码） |
| `DEEPSEEK_API_KEY` | 否 | 空 | DeepSeek Chat API 密钥 |
| `DEEPSEEK_API_BASE` | 否 | `https://api.deepseek.com` | DeepSeek API 请求地址 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-chat` | 使用的 DeepSeek 模型名称 |
| `DEEPSEEK_TIMEOUT` | 否 | `120` | API 请求超时时间（秒） |

> **QQ 邮箱授权码获取方法**：登录 QQ 邮箱网页版 → 设置 → 账户 → 开启 POP3/SMTP 服务 → 按提示生成授权码。如果不配置邮箱，系统会回退到控制台后端输出（邮件内容会打印在终端中），不影响其他功能使用。

### 3.6 初始化数据库（迁移）

确保虚拟环境已激活、`.env` 已配置、MySQL 服务正在运行，然后执行数据库迁移命令来创建所有数据表：

```powershell
python manage.py migrate
```

成功后会输出类似以下信息：

```
Operations to perform:
  Apply all migrations: admin, auth, contenttypes, core, sessions
Running migrations:
  Applying contenttypes.0001_initial... OK
  Applying core.0001_initial... OK
  ...
```

> **迁移失败排查**：如果提示数据库连接错误，请检查 MySQL 是否启动、`.env` 中的数据库名称/用户/密码是否正确、数据库是否已创建。

### 3.7 创建超级管理员

执行以下命令创建系统超级管理员账号：

```powershell
python manage.py createsuperuser
```

按提示输入用户名、邮箱和密码。该账号将拥有系统最高权限，可登录 Django Admin（`/sys-admin/`）和自定义管理后台（`/manage/`）。

### 3.8 收集静态文件（生产环境）

如果部署到生产环境，需要收集静态文件：

```powershell
python manage.py collectstatic
```

静态文件将被收集到项目根目录下的 `staticfiles/` 目录中，供 Nginx 等 Web 服务器直接提供服务。

> 开发环境下无需执行此步骤，Django 开发服务器会自动提供静态文件。

### 3.9 启动开发服务器

```powershell
python manage.py runserver
```

默认监听 `http://127.0.0.1:8000`。如需指定端口或允许外部访问：

```powershell
# 指定端口
python manage.py runserver 9000

# 允许局域网访问（需同时在 DJANGO_ALLOWED_HOSTS 中添加对应 IP）
python manage.py runserver 0.0.0.0:8000
```

启动成功后，打开浏览器即可访问系统。

---

## 4. 生产环境部署建议

对于生产环境部署，建议采用以下方案：

| 组件 | 推荐方案 | 说明 |
|------|---------|------|
| **Web 服务器** | Nginx | 反向代理 + 静态文件服务 |
| **WSGI 服务器** | Gunicorn / uWSGI | 替代 Django 内置开发服务器 |
| **数据库** | MySQL 8.x | 使用独立数据库账号，限制权限 |
| **进程管理** | systemd / Supervisor | 后台守护进程 |
| **HTTPS** | Let's Encrypt | 强制使用 HTTPS |

**关键配置清单**：

- [ ] 设置 `DJANGO_DEBUG=false`
- [ ] 生成随机 `DJANGO_SECRET_KEY`（可用 `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` 生成）
- [ ] 设置 `DJANGO_ALLOWED_HOSTS` 为实际域名
- [ ] 执行 `python manage.py collectstatic`
- [ ] 使用独立 MySQL 数据库账号（非 root）
- [ ] 配置 Nginx 代理静态文件和媒体文件
- [ ] 不要将 `.env` 文件提交到版本库

---

## 5. 系统使用说明

### 5.1 系统角色与权限概览

系统包含 **5 种用户角色**，各角色权限范围如下：

| 角色 | 标识 | 创建方式 | 用户名格式 | 主要功能 |
|------|------|---------|-----------|---------|
| **患者** | `patient` | 前台自行注册 | 自定义 | 预问诊、挂号、充值、查看病历/账单 |
| **医生** | `doctor` | 管理员创建 | `doc1`, `doc2`… | 候诊队列、接诊、录入病历、开具处方 |
| **护士** | `nurse` | 管理员创建 | `nur1`, `nur2`… | 分诊体征录入、发药、采购申请 |
| **护士长** | `head_nurse` | 管理员创建 | `nur_head1`… | 库存管理、采购审批 |
| **管理员** | `admin` | 管理员创建 / `createsuperuser` | `admin1`… | 全部管理功能 |

> **说明**：医护和管理账号由管理员创建后会生成初始密码，首次登录后系统会**强制要求修改密码**。

### 5.2 系统入口地址

以默认端口 8000 运行为例：

| 页面 | 地址 | 说明 |
|------|------|------|
| **门户首页** | `http://127.0.0.1:8000/portal/` | 公开访问，展示医院信息 |
| **登录页** | `http://127.0.0.1:8000/accounts/login/` | 所有用户统一登录入口 |
| **注册页** | `http://127.0.0.1:8000/accounts/register/` | 仅患者可注册 |
| **找回密码** | `http://127.0.0.1:8000/accounts/forgot-password/` | 通过邮箱验证码重置 |
| **管理后台** | `http://127.0.0.1:8000/manage/dashboard/` | 管理员专用 |
| **Django Admin** | `http://127.0.0.1:8000/sys-admin/` | 超级管理员底层数据管理 |

> **登录逻辑**：用户登录后，系统会根据角色自动跳转到对应的工作台页面。也可直接访问根路径 `http://127.0.0.1:8000/`，已登录用户会按角色自动分发。

### 5.3 管理员操作指南

管理员登录后进入 **管理仪表盘**（`/manage/dashboard/`），可进行以下操作：

#### 5.3.1 仪表盘与统计

- **管理仪表盘**：查看系统整体数据概览，包括预约趋势图表
- **财务统计**（`/manage/financial-stats/`）：查看营收统计、科室分布图表
- **订单流水**（`/manage/orders/`）：查看所有挂号费、药费、充值订单记录
- **操作日志**（`/manage/operation-logs/`）：审计全系统操作记录

#### 5.3.2 人员管理

- **员工管理**（`/manage/employees/`）：
  - 点击「新建员工」选择角色（医生/护士/护士长/管理员）
  - 系统自动按角色生成用户名（如 `doc1`、`nur1`）
  - 分配所属科室（医护必须）
  - 创建后将获得初始密码，员工首次登录需修改密码

- **患者账号管理**（`/manage/patient-accounts/`）：
  - 查看所有患者账号
  - 启用/禁用患者账号
  - 重置患者密码

- **患者档案**（`/manage/patients/`）：查看患者详细信息

#### 5.3.3 基础数据维护

- **科室管理**（`/manage/departments/`）：新增、编辑、删除科室
- **药品管理**（`/manage/drugs/`）：新增、编辑、删除药品信息（名称、规格、单位、价格、库存、厂商）
- **生产厂家**（`/manage/manufacturers/`）：维护药品生产厂家信息
- **排班管理**（`/manage/schedules/`）：
  - 发布排班：指定医生、科室、日期、班次（上午/下午）、号源数量、挂号费
  - 编辑/删除排班

#### 5.3.4 业务数据查看

- **预约列表**（`/manage/appointments/`）：查看全院预约记录及详情
- **预问诊报告**（`/manage/ai-reports/`）：查看患者 AI 预问诊报告
- **病历列表**（`/manage/medical-records/`）：查看全院电子病历
- **处方列表**（`/manage/prescriptions/`）：查看全院处方记录
- **采购申请**（`/manage/purchase-requests/`）：查看护士提交的采购申请

#### 5.3.5 门户配置

- **医院门户设置**（`/manage/hospital-setting/`）：配置门户首页的医院名称、标语、首页展示图片

### 5.4 患者操作指南

#### 5.4.1 注册与登录

1. 访问注册页 `/accounts/register/`
2. 填写用户名、邮箱、密码
3. 如果系统配置了 QQ 邮箱，将通过邮箱接收验证码完成注册
4. 注册成功后使用用户名或邮箱均可登录

#### 5.4.2 AI 智能预问诊

1. 登录后进入「智能预问诊」页面（`/app/patient/ai-triage/`）
2. 与 AI 进行多轮对话，描述症状
3. AI 基于 DeepSeek 大模型分析病情，给出初步判断
4. 对话结束后系统自动生成**预问诊报告**（AIReport），包含：
   - 症状摘要
   - 结构化分析内容
   - 推荐就诊科室
5. 报告可在「我的报告」列表中查看、删除

#### 5.4.3 预约挂号

1. 浏览科室列表（`/app/patient/departments/`）或找医生（`/app/patient/doctors/`）
2. 查看该科室/医生的可预约排班
3. 选择排班后进入挂号页面
4. 可选择关联一份 AI 预问诊报告（方便医生参考）
5. 确认挂号并支付（从账户余额扣除）
6. 在「我的预约」中查看预约状态（待就诊 → 已确认 → 就诊中 → 已完成）
7. 可取消未就诊的预约

#### 5.4.4 个人中心

- **个人资料**（`/app/patient/me/profile/`）：完善真实姓名、性别、年龄、手机号、地址
- **修改密码**（`/app/patient/me/password/`）
- **账户充值**（`/app/patient/me/recharge/`）：为账户余额充值
- **我的账单**（`/app/patient/me/orders/`）：查看挂号费、药费、充值等订单记录
- **我的病历**：在预约详情中查看医生录入的病历内容

### 5.5 医生操作指南

医生登录后进入 **医生工作台**（`/app/doctor/dashboard/`）：

1. **候诊队列**（`/app/doctor/queue/`）：查看当日分配给自己的待接诊患者列表
2. **接诊**（点击患者进入接诊页）：
   - 查看患者基本信息和体征记录（护士已录入的体温、血压、心率等）
   - 查看患者的 AI 预问诊报告（如有关联）
   - 录入**电子病历**：主诉、现病史、诊断结果、处理意见
   - 开具**电子处方**：选择药品、用量、用法说明
   - 处方签署后状态变为「已签署」，等待护士发药

### 5.6 护士操作指南

护士登录后可进入以下功能：

1. **分诊与体征录入**（`/app/nurse/triage/`）：
   - 查看待分诊的患者列表
   - 为患者录入体征信息：体温、血压、心率
   - 录入完成后患者进入医生候诊队列

2. **处方发药**（`/app/nurse/prescriptions/`）：
   - 查看「已签署」状态的处方列表
   - 核对处方内容后执行发药操作
   - 发药时系统自动扣减药品库存
   - 处方状态变更为「已发药」

3. **药品采购申请**（`/app/nurse/purchase/`）：
   - 当药品库存不足时，提交采购申请
   - 选择药品、填写采购数量和申请原因
   - 申请提交后等待护士长审批

### 5.7 护士长操作指南

护士长登录后进入 **护士长工作台**（`/app/head-nurse/dashboard/`）：

1. **药品库存**（`/app/head-nurse/inventory/`）：查看全部药品当前库存情况
2. **采购审批**（`/app/head-nurse/purchase/`）：
   - 查看护士提交的采购申请列表
   - 审批操作：通过或驳回
   - 通过后系统自动增加对应药品的库存数量
   - 可填写审批意见
3. **生产厂家管理**（`/manage/manufacturers/`）：护士长也有权限管理生产厂家信息

---

## 6. 数据库表结构总览

系统通过 Django ORM 自动建表，迁移执行后将创建以下核心业务表：

| 数据表 | 对应模型 | 用途说明 |
|--------|---------|---------|
| `core_user` | `User` | 用户表（继承 Django AbstractUser），包含角色、科室、余额等字段 |
| `core_hospitalsetting` | `HospitalSetting` | 医院门户设置（单例，pk=1） |
| `core_emailverifyrecord` | `EmailVerifyRecord` | 邮箱验证码记录 |
| `core_department` | `Department` | 科室表 |
| `core_manufacturer` | `Manufacturer` | 药品生产厂家 |
| `core_drug` | `Drug` | 药品表（含库存、价格、关联厂家） |
| `core_schedule` | `Schedule` | 医生排班表（含号源容量和挂号价格） |
| `core_appointment` | `Appointment` | 预约挂号记录 |
| `core_aireport` | `AIReport` | AI 预问诊报告（含结构化 JSON 数据） |
| `core_vitalsign` | `VitalSign` | 患者体征记录（一对一关联预约） |
| `core_medicalrecord` | `MedicalRecord` | 电子病历（一对一关联预约） |
| `core_prescription` | `Prescription` | 电子处方 |
| `core_prescriptionline` | `PrescriptionLine` | 处方明细行（药品+用量） |
| `core_order` | `Order` | 订单/账单流水（挂号费/药费/充值） |
| `core_purchaserequest` | `PurchaseRequest` | 药品采购申请 |
| `core_operationlog` | `OperationLog` | 系统操作审计日志 |

此外还有 Django 自带的 `auth_*`、`django_session`、`django_content_type` 等系统表。

> **E-R 关系要点**：
> - `User` → `Department`（多对一）：医护人员归属科室
> - `Schedule` → `User`（医生）+ `Department`：排班关联
> - `Appointment` → `User`（患者）+ `Schedule` + `AIReport`（可选）
> - `MedicalRecord` / `VitalSign` → `Appointment`（一对一）
> - `Prescription` → `MedicalRecord` → `PrescriptionLine` → `Drug`
> - `PurchaseRequest` → `Drug` + `User`（申请人）+ `User`（审批人）
> - `Order` → `User`（患者）+ `Appointment`/`Prescription`（可选关联）

---

## 7. 常见问题与排错

### Q1: `pip install` 报错找不到 MySQL 头文件

**原因**：本项目使用 `PyMySQL`（纯 Python 实现），不需要 `mysqlclient` 及其 C 依赖。  
**解决**：确认 `requirements.txt` 中只有 `PyMySQL`，不要额外安装 `mysqlclient`。

### Q2: 迁移时报 `Access denied for user 'root'@'localhost'`

**原因**：MySQL 用户名或密码配置错误。  
**解决**：检查 `.env` 文件中 `MYSQL_USER` 和 `MYSQL_PASSWORD` 是否与 MySQL 实际配置一致。

### Q3: 迁移时报 `Unknown database 'medical'`

**原因**：数据库尚未创建。  
**解决**：登录 MySQL 执行 `CREATE DATABASE medical DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`。

### Q4: 发送验证码邮件失败

**原因**：QQ 邮箱或授权码未配置/配置错误。  
**解决**：
1. 确认 `.env` 中 `QQ_EMAIL` 和 `QQ_EMAIL_AUTH_CODE` 已正确填写
2. 确认 QQ 邮箱已开启 POP3/SMTP 服务
3. 授权码不是 QQ 登录密码，需在 QQ 邮箱设置中单独生成
4. 如果不需要邮件功能，留空即可，系统会将邮件内容输出到终端控制台

### Q5: AI 预问诊无响应

**原因**：DeepSeek API Key 未配置或余额不足。  
**解决**：
1. 确认 `.env` 中 `DEEPSEEK_API_KEY` 已填写有效的 API Key
2. 登录 [DeepSeek 平台](https://platform.deepseek.com/) 确认账户余额
3. 如超时可适当增大 `DEEPSEEK_TIMEOUT` 值

### Q6: 页面样式丢失（CSS/JS 不加载）

**原因**：开发模式下通常不会出现，生产环境可能是静态文件未收集。  
**解决**：
1. 开发模式确认 `DJANGO_DEBUG=true`
2. 生产环境执行 `python manage.py collectstatic` 并配置 Nginx 代理 `staticfiles/` 目录

### Q7: 登录后一直跳转到修改密码页面

**原因**：管理员创建的医护账号首次登录必须修改初始密码，这是系统安全策略。  
**解决**：这是正常行为，修改密码后即可正常使用系统。

---

## 8. 安全注意事项

1. **永远不要将 `.env` 文件提交到 Git 仓库**（已在 `.gitignore` 中排除）
2. **生产环境必须关闭调试模式**：`DJANGO_DEBUG=false`
3. **生产环境必须设置强随机密钥**：使用 Django 工具生成：
   ```python
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
4. **使用独立数据库账号**：不要在生产环境使用 `root` 用户
5. **保护敏感信息**：数据库密码、邮箱授权码、API Key、Django Secret Key 等不要暴露
6. **媒体文件安全**：`media/` 目录中的用户上传文件不应提交到版本库
7. **强制 HTTPS**：生产环境应配置 SSL 证书，强制使用 HTTPS 传输
8. **定期备份数据库**：使用 `mysqldump` 等工具定期备份数据

---

> **文档结束** — 如有疑问请参考项目中的 `README.md` 和 `spec.md` 设计文档。
