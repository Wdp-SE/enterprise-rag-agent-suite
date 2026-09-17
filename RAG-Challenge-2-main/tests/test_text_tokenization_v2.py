"""Deterministic contract tests for the controlled BM25 tokenizer V2."""

from src.text_tokenization import (
    normalize_technical_text_v2,
    technical_tokenize_v1,
    technical_tokenize_v2,
)


def test_v1_contract_is_preserved():
    assert technical_tokenize_v1("requestTimeout") == ["requesttimeout"]
    assert technical_tokenize_v1("timeout_ms") == ["timeout_ms", "timeout", "ms"]


def test_separator_identifier_contracts():
    assert technical_tokenize_v2("timeout_ms") == ["timeout_ms", "timeout", "ms"]
    assert technical_tokenize_v2("/api/export") == ["/api/export", "api", "export"]
    assert technical_tokenize_v2("REQ-03-21") == ["req-03-21", "req", "03", "21"]
    assert technical_tokenize_v2("XG-GN-SJCL") == [
        "xg-gn-sjcl",
        "xg",
        "gn",
        "sjcl",
    ]
    assert technical_tokenize_v2("module.config.timeout") == [
        "module.config.timeout",
        "module",
        "config",
        "timeout",
    ]


def test_camel_case_contract():
    assert technical_tokenize_v2("requestTimeout") == [
        "requesttimeout",
        "request",
        "timeout",
    ]


def test_numbers_units_chinese_and_mixed_contracts():
    assert technical_tokenize_v2("1000 TPS") == ["1000", "tps"]
    assert technical_tokenize_v2("30 ms") == ["30", "ms"]
    chinese = technical_tokenize_v2("超时配置")
    assert "超时配置" in chinese
    assert "超时" in chinese
    mixed = technical_tokenize_v2("数据处理模块SJCL")
    assert "数据处理模块" in mixed
    assert "sjcl" in mixed


def test_empty_punctuation_repetition_and_fullwidth_contracts():
    assert technical_tokenize_v2("") == []
    assert technical_tokenize_v2("，。！？()") == []
    assert technical_tokenize_v2("timeout_ms timeout_ms") == [
        "timeout_ms",
        "timeout",
        "ms",
        "timeout_ms",
        "timeout",
        "ms",
    ]
    assert technical_tokenize_v2("ｔｉｍｅｏｕｔ＿ｍｓ") == [
        "timeout_ms",
        "timeout",
        "ms",
    ]
    assert technical_tokenize_v2("／ａｐｉ／ｅｘｐｏｒｔ") == [
        "/api/export",
        "api",
        "export",
    ]


def test_query_and_index_paths_are_symmetric_and_whitespace_normalized():
    samples = [
        "requestTimeout",
        "REQ-03-21",
        "数据处理模块SJCL",
        "  module.config.timeout\t30 ms\n",
    ]
    for sample in samples:
        index_tokens = technical_tokenize_v2(sample)
        query_tokens = technical_tokenize_v2(sample)
        assert query_tokens == index_tokens
    assert normalize_technical_text_v2(" a\t b\n c ") == "a b c"


def test_no_recursive_identifier_combinations_or_artificial_boosting():
    tokens = technical_tokenize_v2("XG-GN-SJCL")
    assert "xg-gn" not in tokens
    assert "gn-sjcl" not in tokens
    assert "xg-sjcl" not in tokens
    assert tokens.count("xg-gn-sjcl") == 1
