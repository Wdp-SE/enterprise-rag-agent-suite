from src.public_scope import is_out_of_scope_public_request


def test_public_scope_guard_only_blocks_explicit_private_organization_requests():
    assert is_out_of_scope_public_request(
        "Can this public corpus show our company's Jira access-approval audit trail?"
    )
    assert is_out_of_scope_public_request("查询公司内部 Jira 审批人的手机号")
    assert is_out_of_scope_public_request("Who in our company approves Jira access requests?")
    assert is_out_of_scope_public_request("Find our internal Jira approval workflow?")
    assert not is_out_of_scope_public_request("What is the Autoware planning module's internal state?")
    assert not is_out_of_scope_public_request("How do I configure a public API endpoint?")
    assert not is_out_of_scope_public_request("How does Jira access approval generally work?")
