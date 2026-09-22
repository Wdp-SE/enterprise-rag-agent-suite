# Patch Review 与安全发布设计

## 局部 Patch

V4 只实现 `REPLACE_PARAGRAPH`。Patch 保存目标文档、基线版本、Section、`paragraph:<index>` Anchor、原文与哈希、建议文本、原因、Evidence、Scope 指纹、审核状态和幂等键。原始 DOCX 先复制到任务目录，所有修改只写 Candidate 文件。

## Human Review

- `APPROVE`：进入可应用状态。
- `EDIT`：保存人工修改，但必须再次确认后才能应用。
- `REJECT`：该 Patch 永不应用。

没有已批准 Patch 时，执行器 fail-closed；单审核人模型继续复用既有边界，没有扩展多级审批或 RBAC。

## 应用前检查

顺序检查 Scope fingerprint、Evidence 存在性、Evidence content hash、Evidence 当前版本、base_version_id、Anchor、原文和 original_content_hash。任何一步不一致都返回阻断或 `CONFLICT`，不会静默覆盖。

## 幂等与 Resume

幂等键由 `patch_id + base_version_id + target_anchor + original_content_hash` 的稳定信息形成。Checkpoint 持久化成功键；Resume 或重复调用发现已应用键时返回 `SKIPPED_ALREADY_APPLIED`，不再次修改 DOCX。

## Candidate Version

```text
Approved Patch
→ Candidate DOCX
→ DOCX package validation
→ Section parse
→ Chunk generation
→ Embedding / index validation
→ expected approved content validation
→ VALIDATED
→ explicit activate
→ ACTIVE
```

构建过程使用既有 VersionLifecycleService 的增量处理和 Embedding cache。Candidate 使用 `activate=False` 入库；所有验证成功后才单独调用 activate。构建或激活失败时旧 ACTIVE 保持有效。历史版本仍在版本目录中，可通过显式 version scope 查询。

## Evidence Freshness

恢复执行会重新检查 Evidence 版本、内容哈希和 Scope；目标版本或段落变化产生 Conflict。当前实现只阻断依赖失效 Evidence 的 Patch，不删除 Checkpoint，也不覆盖原文，便于人工重新生成或确认。
