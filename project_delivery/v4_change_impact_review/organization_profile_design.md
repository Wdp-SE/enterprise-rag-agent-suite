# OrganizationProfile 设计

## 目的

企业之间常变化的是编号格式、文档类型名称、章节别名和版本状态文本。V4 将这些变化放在 `OrganizationProfile`，核心 Parser、Domain、Retriever 和 Agent 只处理规范化结果，不包含 `if company == ...` 分支。

## 首版字段

- `organization_id`：业务归属标识。
- `identifier_patterns`：各 EngineeringItemType 的正则规则。
- `document_type_mapping`：企业文档名到统一类型的映射。
- `section_aliases`：企业章节名到规范章节名的映射。
- `version_status_mapping`：企业版本状态到 ACTIVE/SUPERSEDED 等状态的映射。

首版不含审批策略、权限策略、租户策略、组织树、用户管理或工作流定义。因此 `organization_id + project_id` 只是 Scope 和来源字段，不是数据库级隔离，也不构成多租户系统。

## 适配边界

```text
企业原始 DOCX
  → OrganizationProfile
  → DocxEngineeringParser / IdentifierExtractor
  → 规范 Section Path + external_identifier + item_type
  → 稳定 EngineeringItem / Diff / Retriever / Agent
```

## 两套夹具

- `demo_company_a`：`REQ-023 / DES-014 / API-008 / TC-102 / OPS-006`，用于完整 Demo。
- `demo_company_b`：覆盖 `PRD-PAY-...`、`CASE-PAY-...` 和“业务需求/技术方案/接口定义/验收场景”等别名，只用于适配测试。

测试证明切换 Profile 后编号识别、文档类型映射、章节规范化和 EngineeringItem 建立仍工作，而核心领域与工作流代码不变。公司 B 没有第二套 UI、数据库、RAG Pipeline 或 Workflow。

## 明确边界

正则配置需要代码审查和测试；恶意或灾难性回溯规则不应由终端用户任意编辑。图片、流程图和复杂公式只标记 `requires_manual_complex_content_review`，首版不会自动修改。
