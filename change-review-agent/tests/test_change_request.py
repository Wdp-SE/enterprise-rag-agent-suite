from app.change_request import (
    build_request_plan,
    classify_change_type,
    is_out_of_scope_public_request,
)


def test_comma_joined_change_and_verification_are_planned_separately():
    summary = "将任务最大并发从 500 调整到 800，同时核对默认配置和重试行为是否需要同步。"

    plan = build_request_plan(summary)

    clause_queries = [row["query"] for row in plan["queries"] if row["kind"] == "change_clause"]
    assert plan["change_type"] == "parameter_config"
    assert len(plan["queries"]) <= 4
    assert any("最大并发" in query for query in clause_queries)
    assert any("重试行为" in query for query in clause_queries)


def test_planner_keeps_full_request_and_hard_query_bound_after_expansion():
    summary = (
        "调整 API 异步任务状态字段，同时核对调用方兼容性，更新请求示例，"
        "补充版本升级说明，并安排回归验证。"
    )

    plan = build_request_plan(summary)

    assert plan["queries"][0]["query"] == summary
    assert plan["queries"][0]["search_query"].startswith(summary)
    assert len(plan["queries"]) <= 4
    assert plan["query_limit"] == 4
    assert all(row["query"].strip() for row in plan["queries"])


def test_parameter_change_is_not_misclassified_by_context_words():
    summary = "工作流里的全局参数和本地参数同名时，核对最终取值优先级。"

    assert classify_change_type(summary) == "parameter_config"


def test_unrelated_audit_log_columns_do_not_become_api_contract_changes():
    summary = "监控审计日志包含用户名、操作类型和延迟字段。"

    assert classify_change_type(summary) == "general"


def test_identity_api_mention_with_security_context_is_security_change():
    summary = "Does the API provide OIDC group-to-role sync? Check the official API and security docs."

    assert classify_change_type(summary) == "security_permission"


def test_explicit_recovery_behavior_remains_a_workflow_change():
    summary = "调整工作流失败后的节点恢复策略，并检查重试行为。"

    assert classify_change_type(summary) == "workflow_behavior"


def test_autoware_planning_behavior_change_gets_domain_specific_category():
    summary = "Review the Goal Planner pull-out trajectory behavior around obstacles and the drivable area."

    plan = build_request_plan(summary)

    assert plan["change_type"] == "planning_behavior"
    assert plan["change_type_label"] == "规划 / 轨迹行为变更"
    assert "规划" in plan["retrieval_focus"]


def test_explicit_planner_parameter_change_keeps_parameter_category():
    summary = "Adjust the Goal Planner obstacle-stop threshold parameter in the YAML config."

    assert classify_change_type(summary) == "parameter_config"


def test_quartz_schedule_default_is_not_misclassified_as_parameter_configuration():
    summary = "missed_fire_policy 对 schedule 的默认行为是什么；核对 Quartz 配置和默认值。"

    assert classify_change_type(summary) == "workflow_behavior"


def test_primary_planning_change_is_not_overridden_by_a_secondary_threshold_check():
    summary = "变更轨迹校验器对不可行驶区域的判定；核对校验阈值和规划器调用链。"

    assert classify_change_type(summary) == "planning_behavior"


def test_autoware_right_of_way_and_ros_topic_are_classified_by_domain():
    assert classify_change_type("调整 Intersection 模块的路权判断逻辑。") == "planning_behavior"
    assert classify_change_type("Change a ROS topic name and message type.") == "interface_compatibility"


def test_subworkflow_query_keeps_user_text_and_adds_search_only_alias():
    summary = "子工作流参数如何传递；核对下游 Shell 节点的 setValue 示例。"

    plan = build_request_plan(summary)

    clause = next(row for row in plan["queries"] if row["kind"] == "change_clause")
    assert "SubWorkflow" not in clause["query"]
    assert "SubWorkflow task" in clause["search_query"]
    assert clause["search_query"].count("SubWorkflow task parent child workflow") == 1


def test_condition_and_dependency_terms_get_targeted_english_search_terms():
    summary = "新增条件分支并调整任务依赖；核对 DAG 工作流定义。"

    plan = build_request_plan(summary)

    expanded = " ".join(row["search_query"] for row in plan["queries"])
    assert "condition branch" in expanded
    assert "task dependency" in expanded
    assert "workflow definition task conditions" in expanded


def test_scope_guard_detects_private_company_data_without_blocking_public_docs():
    assert is_out_of_scope_public_request(
        "Apache DolphinScheduler 是否内置经纬恒润的内部车辆温度采集 API？"
    )
    assert is_out_of_scope_public_request("查询公司内部 Jira 审批人的手机号和私有工单权限")
    assert not is_out_of_scope_public_request("DolphinScheduler 的内部工作流状态如何恢复？")
    assert not is_out_of_scope_public_request("What is the API server health-check endpoint?")
    assert is_out_of_scope_public_request(
        "Check whether Autoware contains our internal company Jira approver list."
    )
    assert is_out_of_scope_public_request(
        "Can this public corpus show our company's Jira access-approval audit trail?"
    )


def test_english_question_and_follow_up_check_become_separate_agent_queries():
    plan = build_request_plan(
        "Does the API expose a signed audit record? Check the official API contract."
    )

    assert len(plan["queries"]) == 3
    assert any("signed audit record" in row["query"] for row in plan["queries"])
    assert any("official API contract" in row["query"] for row in plan["queries"])
