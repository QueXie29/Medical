# HIS 智慧医疗系统 — 设计说明（Design Doc / Spec）

> 本文档依据仓库内实际代码（`Medical/`、`core/`、`templates/` 等）整理，描述系统目标、架构、数据与路由；不包含实现代码。

---

## 1. 概述

本项目是基于 **Django 单体应用** 的 **HIS 智慧医疗** Web 系统：在同一套用户与权限模型下，为患者提供门户（注册登录、预问诊、挂号、账单、个人信息）、为医护提供分诊/接诊/处方/发药工作台，为管理员提供主数据与业务数据维护、财务统计与操作审计，数据持久化于 **MySQL**。

---

## 2. 技术栈

| 类别 | 技术 / 依赖 | 版本或说明（以仓库为准） |
|------|----------------|--------------------------|
| 语言 | Python | 与 Django 5 兼容（`requirements.txt` 未钉死小版本） |
| Web 框架 | Django | `>=5.0,<6`（`requirements.txt`） |
| 数据库 | MySQL | `django.db.backends.mysql`，`utf8mb4`，`STRICT_TRANS_TABLES`（`Medical/settings.py`） |
| MySQL 驱动 | PyMySQL | `>=1.1.0` |
| 图像处理 | Pillow | `>=10.0.0`（媒体字段等） |
| 模板 | Django Templates | `TEMPLATES.DIRS` 指向项目根下 `templates/` |
| 前端 UI | Bootstrap 5、Font Awesome 6 | 通过 CDN 在 `templates/base.html` 等中引入 |
| 图表 | Chart.js | 管理仪表盘、财务统计等页通过 CDN 引入 |
| 邮件 | SMTP（QQ 邮箱）或控制台后端 | 由 `QQ_EMAIL` / `QQ_EMAIL_AUTH_CODE` 环境变量控制 |
| 外部 AI | DeepSeek（OpenAI 兼容 HTTP） | `DEEPSEEK_API_KEY`、`DEEPSEEK_API_BASE`、`DEEPSEEK_MODEL`、`DEEPSEEK_TIMEOUT`（`settings.py`），逻辑在 `core/services/deepseek_service.py` |
| 原生后台 | Django Admin | 根 URL 挂载于 `sys-admin/`（`Medical/urls.py`），与业务 `/manage/` 区分 |

---

## 3. 整体架构

### 3.1 请求与数据流

**浏览器** → **Nginx/WSGI（未在仓库配置，部署层）** → **Django URL 路由**（`Medical/urls.py` → `include("core.urls")`）→ **视图**（`core/views/` 下按角色与域拆分）→ **ORM（`core/models.py`）** → **MySQL**；认证与会话由 **`django.contrib.auth`**、自定义 **`AUTH_USER_MODEL`** 与 **`EmailOrUsernameModelBackend`** 完成；全局门户文案由 **`core.context_processors.hospital_portal`** 注入模板；部分交互（验证码、找回密码、AI 对话）为 **JSON / Fetch** 与表单 POST 并存。

### 3.2 项目目录树（主要部分）

```text
Medical/
├── Medical/
│   ├── settings.py       # 数据库、邮件、DeepSeek、中间件、认证后端等
│   ├── urls.py           # sys-admin + include(core.urls)
│   └── wsgi.py
├── manage.py
├── requirements.txt
├── spec.md               # 本设计文档
├── core/
│   ├── models.py
│   ├── urls.py
│   ├── forms.py
│   ├── backends.py
│   ├── middleware.py
│   ├── utils.py
│   ├── context_processors.py
│   ├── decorators.py
│   ├── admin.py
│   ├── apps.py
│   ├── services/
│   │   └── deepseek_service.py
│   ├── migrations/
│   └── views/
│       ├── auth_views.py
│       ├── patient_views.py
│       ├── admin_views.py
│       ├── doctor_views.py
│       ├── nurse_views.py
│       ├── headnurse_views.py
│       └── manufacturer_views.py
├── templates/            # 全局模板
├── static/
└── media/
```

---

## 4. 数据模型（按模块，列表描述）

### 4.1 用户与枚举

- **`UserRole`（TextChoices，非表）**  
  `patient`、`doctor`、`nurse`、`head_nurse`、`admin`。

- **`Gender`（TextChoices，非表）**  
  `M` / `F`。

- **`User`（继承 `AbstractUser`）**  
  - **业务字段**：`email`（`EmailField`，`unique=True`，`null=True`，`blank=True`，自定义重复提示）、`role`、`real_name`、`gender`、`age`、`phone`、`address`、`must_change_password`、`balance`、`department`（**外键 → `Department`**，`SET_NULL`，`related_name='staff_users'`）。  
  - **关系**：作为外键目标出现在预约、病历、订单、操作日志、排班（医生）等。  
  - **约束与行为**：`UniqueConstraint` 无额外组合约束于 User 本体；`clean`/`save` 将邮箱空字符串规范为 `NULL`，避免与 `unique` 在空串上冲突。

- **`CustomUserManager`**  
  创建用户时默认 `role=patient`，创建超级用户时默认 `role=admin`，保证 `createsuperuser` 可用。

### 4.2 门户与验证码

- **`HospitalSetting`**  
  单例语义（`save` 固定 `pk=1`，`delete` 禁止）：`hospital_name`、`hero_title`、`hero_image`（`ImageField`，`upload_to='portal/'`，可空）。

- **`EmailVerifyRecord`**  
  无外键：`email`、`code`、`created_at`；用于注册/找回密码等验证码暂存。

### 4.3 主数据与药品

- **`Department`**  
  `name`、`code`（`unique=True`，可空）、`description`、`is_active`、`created_at`。

- **`Manufacturer`**  
  `name`、联系人/电话/地址、时间戳。

- **`Drug`**  
  `name`、`generic_name`、`specification`、`unit`、`stock_quantity`、`price`、**`manufacturer`**（**外键 → `Manufacturer`**，`SET_NULL`）、时间戳。

### 4.4 排班与预约

- **`Schedule`**  
  **`doctor`**（**外键 → `User`**，限制主治角色）、**`department`**（**外键 → `Department`**）、`work_date`、`shift`（上午/下午枚举）、`total_capacity`、`is_active`、`price`、`remark`、`created_at`。  
  - **约束**：`UniqueConstraint(fields=[doctor, department, work_date, shift], name=uniq_schedule_doctor_dept_date_shift)`。

- **`Appointment`**  
  **`patient`**（**外键 → `User`**，患者）、**`schedule`**（**外键 → `Schedule`**，级联）、**`ai_report`**（**外键 → `AIReport`**，`SET_NULL`，可空）、`status`（待就诊/已确认/就诊中/已完成/已取消）、`remark`、`amount_paid`、时间戳。

### 4.5 预问诊

- **`AIReport`**  
  **`patient`**（**外键 → `User`**，患者）、`title`、`summary`、`structured_content`（JSON）、`raw_llm_response`、**`recommended_department`**（**外键 → `Department`**，`SET_NULL`）、时间戳。

### 4.6 就诊链

- **`VitalSign`**  
  **`appointment`**：**一对一 → `Appointment`**（级联删除）；`temperature`、`blood_pressure`、`heart_rate`、`recorded_at`（`auto_now`）。

- **`MedicalRecord`**  
  **`appointment`**：**一对一 → `Appointment`**；**`patient`**（**外键 → `User`**）；**`doctor`**（**外键 → `User`**，`PROTECT`）；主诉、现病史、诊断、处理意见、时间戳。

- **`Prescription`**  
  **`medical_record`**（**外键 → `MedicalRecord`**）；**`doctor`**（**外键 → `User`**，`PROTECT`）；`status`（草稿/已签署/已发药/已作废）、`notes`、`execution_note`、`executed_at`、时间戳。

- **`PrescriptionLine`**  
  **`prescription`**（**外键 → `Prescription`**，`related_name='lines'`）；**`drug`**（**外键 → `Drug`**，`PROTECT`）；`quantity`、`dosage_instruction`、`remark`。

### 4.7 财务与供应链

- **`Order`**  
  **`patient`**（**外键 → `User`**）；`order_type`（挂号费/药费/充值）、`amount`、`status`（已支付/已退款）、`description`；**`appointment`**、**`prescription`**（均可空，`SET_NULL`）；`created_at`；**Meta** 默认按 `-created_at` 排序。

- **`PurchaseRequest`**  
  **`drug`**（**外键 → `Drug`**）；**`requester`**（**外键 → `User`**，护士）；**`reviewer`**（**外键 → `User`**，护士长，可空）；`quantity`、`status`（待审批/已通过/已驳回）、`reason`、`review_comment`、`created_at`、`reviewed_at`。

### 4.8 审计

- **`OperationLog`**  
  **`user`**（**外键 → `User`**，`SET_NULL`，可空）、`action_type`（CREATE/UPDATE/DELETE/LOGIN）、`module`、`description`、`ip_address`、`created_at`；**Meta** 默认 `-created_at`。

---

## 5. 路由与视图

**认证列约定**  
- **公开**：未登录可访问（或仅重定向，不产生业务写操作）。  
- **需登录**：必须已认证；若视图另有角色装饰器，在「说明」中体现。  
- **HTTP**：以视图默认为准；表单类 CBV 为 **GET + POST**；仅声明 `http_method_names` 的为表中方法。

| URL 路径 | HTTP 方法 | 功能说明 | 认证 |
|----------|-----------|----------|------|
| `/` | GET | 根路径：已登录按角色跳转工作台；未登录跳转登录页 | 未登录可进但会被重定向 |
| `/portal/` | GET | 患者门户大厅 | 公开 |
| `/accounts/register/` | GET、POST | 患者注册 | 公开 |
| `/api/send-code/` | POST | 发送邮箱验证码（注册/找回密码） | 公开（CSRF 保护） |
| `/accounts/login/` | GET、POST | 登录（用户名或邮箱） | 公开 |
| `/accounts/forgot-password/` | GET、POST | 找回密码（含 JSON 提交） | 公开 |
| `/accounts/logout/` | POST | 退出登录 | 需登录 |
| `/accounts/password/change/` | GET、POST | 首次/强制修改密码等 | 需登录 |
| `/manage/dashboard/` | GET | 管理仪表盘与图表 | 需登录且管理员（或超管） |
| `/manage/financial-stats/` | GET | 财务营收统计与图表 | 同上 |
| `/manage/orders/` | GET | 订单流水列表 | 同上 |
| `/manage/hospital-setting/` | GET、POST | 医院门户单例配置 | 同上 |
| `/manage/operation-logs/` | GET | 系统操作日志 | 同上 |
| `/manage/patients/` | GET | 患者档案列表 | 同上 |
| `/manage/patients/<int:pk>/` | GET | 患者档案详情 | 同上 |
| `/manage/patient-accounts/` | GET | 患者账号运维列表 | 同上 |
| `/manage/patient-accounts/<int:pk>/toggle-active/` | POST | 切换患者账号启用状态 | 同上 |
| `/manage/patient-accounts/<int:pk>/reset-password/` | POST | 重置患者密码 | 同上 |
| `/manage/api/doctors-by-department/` | GET | 按科室返回医生 JSON | 同上 |
| `/manage/employees/` | GET | 员工列表 | 同上 |
| `/manage/employees/create/` | GET、POST | 新建员工 | 同上 |
| `/manage/employees/<int:pk>/edit/` | GET、POST | 编辑员工 | 同上 |
| `/manage/employees/<int:pk>/delete/` | GET、POST | 删除员工 | 同上 |
| `/manage/departments/` | GET | 科室列表 | 同上 |
| `/manage/departments/new/` | GET、POST | 新建科室 | 同上 |
| `/manage/departments/<int:pk>/edit/` | GET、POST | 编辑科室 | 同上 |
| `/manage/departments/<int:pk>/delete/` | GET、POST | 删除科室 | 同上 |
| `/manage/drugs/` | GET | 药品列表 | 同上 |
| `/manage/drugs/new/` | GET、POST | 新建药品 | 同上 |
| `/manage/drugs/<int:pk>/edit/` | GET、POST | 编辑药品 | 同上 |
| `/manage/drugs/<int:pk>/delete/` | GET、POST | 删除药品 | 同上 |
| `/manage/manufacturers/` | GET | 生产厂家列表 | 需登录且管理员或护士长 |
| `/manage/manufacturers/new/` | GET、POST | 新建厂家 | 同上 |
| `/manage/manufacturers/<int:pk>/edit/` | GET、POST | 编辑厂家 | 同上 |
| `/manage/manufacturers/<int:pk>/delete/` | GET、POST | 删除厂家 | 同上 |
| `/manage/schedules/` | GET | 排班列表 | 需登录且管理员 |
| `/manage/schedules/publish/` | GET、POST | 发布排班 | 同上 |
| `/manage/schedules/<int:pk>/edit/` | GET、POST | 编辑排班 | 同上 |
| `/manage/schedules/<int:pk>/delete/` | GET、POST | 删除排班 | 同上 |
| `/manage/appointments/` | GET | 预约列表 | 同上 |
| `/manage/appointments/<int:pk>/` | GET | 预约详情 | 同上 |
| `/manage/ai-reports/` | GET | 预问诊报告列表 | 同上 |
| `/manage/ai-reports/<int:pk>/` | GET | 预问诊报告详情 | 同上 |
| `/manage/medical-records/` | GET | 病历列表 | 同上 |
| `/manage/medical-records/<int:pk>/` | GET | 病历详情 | 同上 |
| `/manage/prescriptions/` | GET | 处方列表 | 同上 |
| `/manage/prescriptions/<int:pk>/` | GET | 处方详情 | 同上 |
| `/manage/purchase-requests/` | GET | 采购申请列表 | 同上 |
| `/manage/purchase-requests/<int:pk>/` | GET | 采购申请详情 | 同上 |
| `/manage/` | GET | 重定向至管理仪表盘 | 依目标需登录 |
| `/app/patient/me/` | GET | 重定向至个人资料编辑 | 需登录（患者） |
| `/app/patient/me/profile/` | GET、POST | 患者完善个人信息 | 需登录（患者） |
| `/app/patient/me/password/` | GET、POST | 患者修改密码 | 需登录（患者） |
| `/app/patient/me/recharge/` | POST | 账户充值 | 需登录（患者） |
| `/app/patient/profile/` | GET | 旧个人中心 URL 重定向 | 公开（立即重定向） |
| `/app/patient/departments/` | GET | 科室列表（患者端） | 需登录（患者） |
| `/app/patient/doctors/` | GET | 找医生 | 需登录（患者） |
| `/app/patient/doctors/<int:doctor_id>/schedules/` | GET | 某医生可预约排班 | 需登录（患者） |
| `/app/patient/appointments/` | GET | 旧预约入口重定向 | 公开 |
| `/app/patient/departments/<int:department_id>/schedules/` | GET | 科室下排班 | 需登录（患者） |
| `/app/patient/schedules/<int:schedule_id>/book/` | GET、POST | 预约挂号 | 需登录（患者） |
| `/app/patient/my-appointments/` | GET | 我的预约 | 需登录（患者） |
| `/app/patient/me/orders/` | GET | 我的账单 | 需登录（患者） |
| `/app/patient/medical-records/<int:pk>/` | GET | 患者查看病历详情 | 需登录（患者） |
| `/app/patient/my-appointments/<int:pk>/cancel/` | POST | 取消预约 | 需登录（患者） |
| `/app/patient/reports/` | GET | 预问诊报告列表 | 需登录（患者） |
| `/app/patient/reports/<int:pk>/` | GET | 预问诊报告详情 | 需登录（患者） |
| `/app/patient/reports/<int:pk>/delete/` | GET、POST | 删除预问诊报告 | 需登录（患者） |
| `/app/patient/ai-triage/` | GET | 智能预问诊对话页 | 需登录（患者） |
| `/app/patient/ai-triage/api/send/` | POST | 发送对话消息 | 需登录（患者） |
| `/app/patient/ai-triage/api/finish/` | POST | 结束对话并生成报告 | 需登录（患者） |
| `/app/patient/` | GET | 旧患者门户根路径重定向 | 公开 |
| `/app/doctor/dashboard/` | GET | 医生工作台 | 需登录（医生） |
| `/app/doctor/queue/` | GET | 医生候诊队列 | 需登录（医生） |
| `/app/doctor/appointments/<int:pk>/consult/` | GET、POST | 医生接诊（病历与处方） | 需登录（医生） |
| `/app/nurse/triage/` | GET | 护士分诊列表 | 需登录（护士） |
| `/app/nurse/triage/<int:pk>/vitals/` | GET、POST | 体征录入 | 需登录（护士） |
| `/app/nurse/prescriptions/` | GET | 发药列表 | 需登录（护士） |
| `/app/nurse/prescriptions/<int:pk>/dispense/` | GET、POST | 发药执行 | 需登录（护士） |
| `/app/nurse/purchase/` | GET、POST | 采购申请提交 | 需登录（护士） |
| `/app/head-nurse/dashboard/` | GET | 护士长工作台 | 需登录（护士长） |
| `/app/head-nurse/inventory/` | GET | 药品库存视图 | 需登录（护士长） |
| `/app/head-nurse/purchase/` | GET | 采购审批列表 | 需登录（护士长） |
| `/app/head-nurse/purchase/<int:pk>/decide/` | GET、POST | 采购审批决策 | 需登录（护士长） |
| `/sys-admin/` | * | Django 自带 Admin | Django Admin 权限体系 |

---

## 6. 模板与页面（每个文件一句话）

### 6.1 全局

- **`templates/base.html`**：全站主框架（顶栏、侧栏、Font Awesome、主内容区）。  
- **`templates/base_patient.html`**：患者端导航与主内容区，与患者大厅等共用。  
- **`templates/core/base.html`**：管理端/表单页卡片与表单基础样式，继承 `base.html`。

### 6.2 认证与员工开户

- **`templates/core/auth/login.html`**：登录页。  
- **`templates/core/auth/register.html`**：患者注册与邮箱验证码。  
- **`templates/core/auth/forgot_password.html`**：找回密码（邮箱验证码 + 新密码）。  
- **`templates/core/auth/change_initial_password.html`**：非患者或默认模板下的首次改密页。  
- **`templates/core/admin/create_employee.html`**：管理员创建医护账号。  
- **`templates/core/portal/placeholder.html`**：门户占位页。

### 6.3 患者端（`templates/patient/`）

- **`lobby.html`**：门户大厅。  
- **`department_list.html`**：科室列表与进入排班。  
- **`doctor_list.html`**：找医生及科室筛选。  
- **`doctor_schedule_booking.html`**：某医生可预约排班列表。  
- **`schedule_list.html`**：某科室下排班列表。  
- **`appointment_book.html`**：选择排班后的挂号下单。  
- **`appointment_list.html`**：我的预约列表。  
- **`center_appointments.html`**：个人中心语境下的预约相关展示。  
- **`personal_center.html`**：个人中心布局与侧栏。  
- **`center_profile.html`**：完善个人信息。  
- **`center_password.html`**：登录后修改密码。  
- **`force_password.html`**：首次/强制改密（患者模板分支）。  
- **`center_orders.html`**：我的账单/订单。  
- **`medical_record_detail.html`**：患者查看本人病历。  
- **`report_list.html`**：预问诊报告列表。  
- **`center_reports.html`**：个人中心与报告入口结合。  
- **`report_detail.html`**：预问诊报告详情。  
- **`report_confirm_delete.html`**：删除报告确认。  
- **`ai_chat.html`**：智能预问诊对话界面。  
- **`dashboard.html`**：患者仪表盘页（若路由使用）。

### 6.4 医生 / 护士 / 护士长

- **`templates/doctor/dashboard.html`**：医生工作台概览。  
- **`templates/doctor/queue_list.html`**：候诊队列。  
- **`templates/doctor/consult.html`**：接诊（病历与处方）。  
- **`templates/doctor/includes/appointment_status_cell.html`**：预约状态单元格片段。  
- **`templates/nurse/triage_list.html`**：分诊列表。  
- **`templates/nurse/vital_sign_form.html`**：体征录入表单。  
- **`templates/nurse/prescription_list.html`**：待发药处方列表。  
- **`templates/nurse/purchase_request.html`**：药品采购申请表单。  
- **`templates/headnurse/dashboard.html`**：护士长工作台。  
- **`templates/headnurse/drug_inventory.html`**：库存视图。  
- **`templates/headnurse/purchase_list.html`**：采购审批列表与操作。

### 6.5 管理端自定义页（`templates/admin/`）

- **`dashboard.html`**：管理仪表盘与预约趋势图。  
- **`financial_stats.html`**：财务营收与科室分布图。  
- **`patient_account_list.html`**：患者账号运维与搜索。  
- **`patient_detail.html`**：管理端患者档案详情。  
- **`operation_log_list.html`**：操作审计日志列表。  
- **`order_list.html`**：订单流水列表。  
- **`schedule_list.html` / `schedule_form.html`**：排班列表与表单。  
- **`base_site.html` / `index.html`**：Admin 相关轻量入口或样式。

### 6.6 管理端 CRUD 与业务列表（`templates/manage/`）

- **`patient_list.html` / `patient_detail.html`**：患者档案列表与详情。  
- **`department_list.html` / `department_form.html` / `department_confirm_delete.html`**：科室维护与删除确认。  
- **`drug_list.html` / `drug_form.html` / `drug_confirm_delete.html`**：药品维护与删除确认。  
- **`manufacturer_list.html` / `manufacturer_form.html` / `manufacturer_confirm_delete.html`**：生产厂家维护与删除确认。  
- **`schedule_list.html` / `schedule_edit.html` / `schedule_confirm_delete.html` / `schedule_publish.html`**：排班列表、编辑、删除确认、发布。  
- **`appointment_list.html` / `appointment_detail.html`**：全院预约列表与详情。  
- **`ai_report_list.html` / `ai_report_detail.html`**：预问诊报告列表与详情。  
- **`medical_record_list.html` / `medical_record_detail.html`**：病历列表与详情。  
- **`prescription_list.html` / `prescription_detail.html`**：处方列表与详情。  
- **`purchase_request_list.html` / `purchase_request_detail.html`**：采购申请列表与详情。  
- **`staff_list.html` / `staff_edit.html` / `staff_confirm_delete.html`**：员工列表、编辑、删除确认。  
- **`hospital_setting.html`**：医院门户单例配置表单。

---

## 7. 后台与管理功能

- **自定义管理端（`/manage/...`）**：在单应用内实现仪表盘、财务统计、订单、医院门户配置、操作日志、患者档案与患者账号运维、员工与科室/药品/厂家/排班/预约/病历/处方/预问诊报告/采购等全流程只读或 CRUD；访问由 **`admin_required`** 或 **`admin_or_headnurse_required`**（生产厂家等）控制。  
- **Django Admin（`/sys-admin/`）**：沿用 Django 自带模型管理与权限，路径与业务 `/manage/` 隔离。

---

## 8. 关键设计决策（5–8 条）

1. **单应用 `core` 承载全部业务**：降低跨应用依赖与部署复杂度，适合单体交付与毕设规模。  
2. **`AUTH_USER_MODEL` 扩展 `AbstractUser` + `role` 字段**：一张用户表区分患者与医护，登录与授权逻辑集中。  
3. **`EmailOrUsernameModelBackend`**：患者倾向邮箱、医护倾向系统用户名，同一登录入口提升可用性。  
4. **`ForcePasswordChangeMiddleware`**：对 `must_change_password` 为真的账号限制除改密、登出外的访问，降低初始口令风险。  
5. **根路径 `/` 角色分发与 `/portal/` 患者大厅分离**：未登录可浏览大厅导航；已登录用户直达各自工作台。  
6. **`Order` 统一挂号费、药费、充值流水**：财务统计与订单列表可同源聚合，便于扩展对账。  
7. **`Schedule` 上医生+科室+日期+班次唯一约束**：从数据层避免重复排班与号源冲突。  
8. **`AIReport` 与 `Appointment` 可选关联**：支持先预问诊再挂号或传统直接挂号。  
9. **DeepSeek 配置与调用封装在 `deepseek_service`**：密钥与超时与视图解耦，便于更换模型或限流。  
10. **`OperationLog` 旁路写入（失败不阻断主流程）**：满足审计需求同时控制对核心路径的影响。

---

*文档版本：与仓库当前结构同步；若路由或模型变更，请同步更新本文件。*
