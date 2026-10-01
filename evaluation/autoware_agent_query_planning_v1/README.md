# Autoware Agent 查询规划评测 V1

本评测只验证变更描述进入 Agent 后的确定性前置规划：变更类型分类、检索子问题覆盖、4 条查询硬上限，以及明确企业私有问题的公开语料范围拦截。它不调用 RAG 或生成模型，不代表检索召回、影响分析正确率、答案准确率、幻觉率或线上延迟。

用例共 28 条，覆盖 14 个文档族，中英文各 14 条；22 条标为 DEV，6 条标为 HOLDOUT。每个文档族只属于一个分割。用例和语料清单指纹锁在 `split_lock.json`，更改案例应创建新的评测版本，不应覆盖 V1。

这轮规则修复期间曾查看 HOLDOUT 逐例结果以定位误分类和范围漏检。因此，虽然文件仍保留原始 22/6 分割和哈希，当前 HOLDOUT 已不再是本轮实现的独立无偏验证集。V1 的修复后全量数字只能描述这批已检查用例上的确定性行为；要对外声称泛化能力，应先发布实现，再建立未用于规则调试的新评测版本与留出集。

当前规则在这 28 条固定用例上：变更类型分类 28/28，公开范围判定 28/28，检索子问题必需内容覆盖 56/56，查询预算符合率 28/28。以上是规则契约自测，不是生产业务表现，也不意味着用户自然语言都能正确分类。

从仓库根目录复现：

```powershell
python evaluation/autoware_agent_query_planning_v1/run_evaluation.py --split all
python evaluation/autoware_agent_query_planning_v1/run_evaluation.py --split dev
python evaluation/autoware_agent_query_planning_v1/run_evaluation.py --split holdout
python -m pytest evaluation/autoware_agent_query_planning_v1/test_evaluation.py -q
```

评测输入只有公开 Autoware 资料范围和人工编写的假设请求。当前 Agent 使用规则对变更请求做前置分类和最多 4 个检索子问题；最终候选仍必须绑定本次检索证据，语言对应关系未经核实会标为待核验，且由人工负责决策。
