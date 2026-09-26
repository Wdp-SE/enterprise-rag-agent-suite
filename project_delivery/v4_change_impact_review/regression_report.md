# V4 回归报告

## 最终结果

| 检查 | 结果 |
|---|---|
| RAG 全量回归 | PASS，47 passed |
| Agent 全量回归 | PASS，97 passed |
| UI 全量回归 | PASS，16 passed |
| Safe Business / Human Review | PASS，Agent 全量业务测试覆盖 |
| Checkpoint / Resume | PASS，含 V3 章节恢复与 V4 Patch 幂等恢复 |
| Evidence Freshness | PASS，过期 Evidence 阻断专项测试 |
| Agent ↔ RAG HTTP | PASS，真实 V4 HTTP 评测闭环 |
| Streamlit Smoke | PASS，health 200/ok，首页 200 且识别为 Streamlit |
| Versioned RAG E2E | PASS，ACTIVE 默认查询、历史显式查询、Diff |
| Offline Runtime Smoke | PASS，Artifact COMPLETE，DENSE_ONLY + SECTION_PATH，无在线生成 |
| pip check | PASS，RAG 与 Agent/UI 均无破损依赖 |
| compile/import | PASS，RAG、Agent、UI 与正式模块导入通过 |
| Secret Scan | PASS，242 个文本文件，0 potential match |
| git diff --check | PASS |

UI 测试出现既有 `pytest_asyncio` 配置弃用提示，以及本机 `.pytest_cache` 无写权限提示；测试本身 16/16 通过，不影响 Runtime 或交付代码。

## V4 A–O 验收

| 项 | 验收证据 | 结果 |
|---|---|---|
| A | 公司 A/B Profile 的编号、类型、章节解析测试 | PASS |
| B | Profile 切换只换 JSON 夹具，核心代码不分公司 | PASS |
| C | EngineeringItem ADDED/MODIFIED/REMOVED/UNCHANGED | PASS |
| D | EXPLICIT_TRACE/CONFIRMED 与 RETRIEVAL_SUGGESTION/SUGGESTED 分离 | PASS |
| E | 只支持指定 `paragraph:<index>` 替换 | PASS |
| F | 无 APPROVE 时执行器拒绝应用 | PASS |
| G | 版本、Anchor、原文或哈希变化返回 CONFLICT | PASS |
| H | Checkpoint Resume 返回 SKIPPED_ALREADY_APPLIED | PASS |
| I | Evidence 版本/内容/Scope 失效阻断 Patch | PASS |
| J | Candidate 全部校验成功后才 activate | PASS |
| K | Candidate 失败时旧 ACTIVE 保留 | PASS |
| L | 激活后默认查询命中 `design-v2` | PASS |
| M | 显式历史 Scope 命中 `design-v1` | PASS |
| N | 原始 DOCX SHA-256 前后一致 | PASS |
| O | Patch 关联 Evidence ID 与 Review Record | PASS |

## 运行记录

固定评测：7 个 RAG Case 全部通过，Agent Golden Impact Precision/Recall 均为 1.0，P95 109.513 ms。真实 HTTP 完整闭环完成 Candidate ACTIVE，RAG Call Count 9。V3 离线 E2E 使用临时目录，不改用户业务数据。
