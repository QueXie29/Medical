# 基于Django的智慧医疗问诊与管理系统设计规范

## 1. 技术栈与架构
* **后端**：Python 3.x, Django 5.x, Django ORM
* **前端**：Django Templates, HTML5/CSS3, 原生 JS (Ajax/Fetch), Bootstrap/Tailwind (可选)
* **数据库**：MySQL 8.x (utf8mb4)
* **核心API**：DeepSeek Chat API (用于 AI 预问诊)

## 2. 角色权限 (RBAC) & 账号规则
系统包含 5 种角色（在 User 模型中用 `role` 区分）：
1. **患者 (Patient)**：唯一开放外网注册的角色。前端注册时默认 role=患者，无需强制改密。
2. **主治医生 (Doctor)**：账号前缀 `doc`
3. **护士 (Nurse)**：账号前缀 `nur`
4. **护士长 (Head Nurse)**：账号前缀 `nur_head`
5. **超级管理员 (Admin)**：账号前缀 `admin`
*注：医护和管理员账号由管理员在后台动态创建（只需输入姓名和选择角色）。系统自动按前缀+数字递增生成用户名（如 doc1, doc2），初始密码统一下发为 123456，且首次登录必须强制修改密码！*

## 3. 核心业务流
* **AI 预问诊流**：患者发起对话 -> 调用 DeepSeek -> 生成结构化 `AIReport`。
* **挂号与诊疗流**：患者挂号（关联AI报告） -> 医生接诊（查看报告并诊断） -> 开处方 -> 护士执行。
* **药品采购流**：护士发起药品采购申请 -> 护士长审批 -> 增加库存。

## 4. 开发规范
* 所有表单提交带 CSRF Token。
* 敏感视图必须使用自定义角色装饰器（如 `@doctor_required`）进行权限拦截。