from local_agent.error_knowledge import diagnose_error


def test_name_error_returns_bounded_diagnostic_without_auto_fix():
    result = diagnose_error("NameError: name 'result' is not defined")
    assert result["rule_id"] == "python-name-error"
    assert result["auto_fix_allowed"] is False
    assert result["escalate"] is False
    assert result["next_steps"]


def test_auth_failure_escalates_and_never_requests_secret():
    result = diagnose_error("HTTP 403 Forbidden")
    assert result["rule_id"] == "http-auth-or-permission"
    assert result["escalate"] is True
    assert "token itself" in " ".join(result["next_steps"])


def test_unknown_error_escalates():
    result = diagnose_error("The moon is made of cheese")
    assert result["rule_id"] == "unknown-or-unmatched"
    assert result["escalate"] is True
    assert result["auto_fix_allowed"] is False


def test_rate_limit_recommends_backoff():
    result = diagnose_error("HTTP 429 rate limit exceeded")
    assert result["rule_id"] == "http-rate-limit"
    assert result["escalate"] is False
    assert any("backoff" in step.lower() for step in result["next_steps"])


def test_diagnostic_bounds_input_length():
    result = diagnose_error("x" * 100_000)
    assert result["rule_id"] == "unknown-or-unmatched"
