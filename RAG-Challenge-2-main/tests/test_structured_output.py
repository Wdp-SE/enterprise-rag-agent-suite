from pydantic import BaseModel
import pytest

import src.api_requests as api_requests


class ExampleResponse(BaseModel):
    final_answer: str
    relevant_pages: list[int]


class FakeGeneration:
    content = ""
    last_kwargs = None

    @classmethod
    def call(cls, **kwargs):
        cls.last_kwargs = kwargs
        return {
            "output": {"choices": [{"message": {"content": cls.content}}]},
            "usage": {"input_tokens": 12, "output_tokens": 7},
        }


class FakeDashscope:
    api_key = None
    Generation = FakeGeneration


def test_qwen_json_is_parsed_and_validated(monkeypatch):
    monkeypatch.setattr(api_requests, "dashscope", FakeDashscope)
    FakeGeneration.content = '{"final_answer":"通过","relevant_pages":[3]}'

    processor = api_requests.BaseDashscopeProcessor()
    result = processor.send_message(
        is_structured=True,
        response_format=ExampleResponse,
    )

    assert result == {"final_answer": "通过", "relevant_pages": [3]}
    assert processor.response_data == {
        "model": "qwen-turbo",
        "input_tokens": 12,
        "output_tokens": 7,
    }
    system_message = FakeGeneration.last_kwargs["messages"][0]["content"]
    assert "Return only one JSON object" in system_message
    assert "final_answer" in system_message


def test_qwen_code_fenced_json_is_compatible(monkeypatch):
    monkeypatch.setattr(api_requests, "dashscope", FakeDashscope)
    FakeGeneration.content = '```json\n{"final_answer":"N/A","relevant_pages":[]}\n```'

    processor = api_requests.BaseDashscopeProcessor()
    result = processor.send_message(
        is_structured=True,
        response_format=ExampleResponse,
    )

    assert result["final_answer"] == "N/A"
    assert result["relevant_pages"] == []


def test_plain_string_response_remains_a_string(monkeypatch):
    monkeypatch.setattr(api_requests, "dashscope", FakeDashscope)
    FakeGeneration.content = "普通文本响应"

    processor = api_requests.BaseDashscopeProcessor()

    assert processor.send_message(is_structured=False) == "普通文本响应"


def test_dashscope_does_not_print_api_key(monkeypatch, capsys):
    secret = "do-not-print-this-key"
    monkeypatch.setattr(api_requests, "dashscope", FakeDashscope)
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    FakeGeneration.content = "安全响应"

    processor = api_requests.BaseDashscopeProcessor()
    processor.send_message(is_structured=False)

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_dashscope_provider_error_is_not_hidden_by_content_parser(monkeypatch):
    class ErrorGeneration:
        @staticmethod
        def call(**kwargs):
            return {
                "status_code": 403,
                "code": "AccessDenied",
                "message": "model access denied",
                "request_id": "safe-request-id",
                "output": None,
            }

    class ErrorDashscope:
        api_key = None
        Generation = ErrorGeneration

    monkeypatch.setattr(api_requests, "dashscope", ErrorDashscope)
    processor = api_requests.BaseDashscopeProcessor()

    with pytest.raises(RuntimeError, match="AccessDenied"):
        processor.send_message(is_structured=False)
