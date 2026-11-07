from __future__ import annotations

import json
import pytest
import httpx
from pydantic import BaseModel

from app.llm.contracts import (
    LLMError,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMAuthenticationError,
    LLMCapabilityError,
    LLMInvalidRequestError,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ModelCapabilities,
    ModelConfiguration,
)
from app.llm.base import LLMProvider
from app.llm.client import LLMClient
from app.llm.registry import LLMProviderRegistry, get_default_llm_registry
from app.llm.providers.ollama import OllamaProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.providers.anthropic import AnthropicProvider
from app.runtime.runner import AgentRunner
from app.registry import AgentRegistry
from app.sdk.contracts import AgentMetadata, AgentRequest, AgentResult
from app.sdk.context import AgentContext


# ==============================================================================
# Mock Providers for Behavioral Unit Tests
# ==============================================================================

class MockProvider(LLMProvider):
    def __init__(self, provider_name: str, response_text: str = "Mock response", capabilities: ModelCapabilities | None = None):
        self._name = provider_name
        self.response_text = response_text
        self.calls: list[tuple[ModelConfiguration, LLMRequest]] = []
        self._caps = capabilities or ModelCapabilities(
            text=True,
            image=True,
            pdf=False,
            structured_output=True,
            tool_calling=True,
            streaming=True,
        )

    @property
    def provider_name(self) -> str:
        return self._name

    def get_capabilities(self, model: str) -> ModelCapabilities:
        return self._caps

    async def generate(self, config: ModelConfiguration, request: LLMRequest) -> LLMResponse:
        self.calls.append((config, request))
        return LLMResponse(
            content=self.response_text,
            usage=LLMUsage(prompt_tokens=15, completion_tokens=25, total_tokens=40),
            provider=self._name,
            model=config.model,
        )

    async def stream(self, config: ModelConfiguration, request: LLMRequest):
        from app.llm.contracts import LLMStreamChunk
        self.calls.append((config, request))
        yield LLMStreamChunk(delta="Hello ")
        yield LLMStreamChunk(delta="World", done=True)


class FailingProvider(LLMProvider):
    def __init__(self, provider_name: str, error_to_raise: Exception):
        self._name = provider_name
        self.error_to_raise = error_to_raise
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._name

    def get_capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(text=True, structured_output=True)

    async def generate(self, config: ModelConfiguration, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        raise self.error_to_raise

    async def stream(self, config: ModelConfiguration, request: LLMRequest):
        self.call_count += 1
        raise self.error_to_raise
        yield  # make it a generator


# ==============================================================================
# 1. Registry & Profile Tests
# ==============================================================================

def test_registry_registers_and_lists_providers():
    registry = LLMProviderRegistry()
    mock_ollama = MockProvider("ollama")
    mock_gemini = MockProvider("gemini")
    registry.register_provider("ollama", mock_ollama)
    registry.register_provider("gemini", mock_gemini)

    assert "ollama" in registry.list_providers()
    assert "gemini" in registry.list_providers()
    assert registry.get_provider("ollama") == mock_ollama
    assert registry.get_provider("gemini") == mock_gemini


def test_registry_unknown_provider_raises():
    registry = LLMProviderRegistry()
    with pytest.raises(LLMError, match="Unknown LLM provider 'unsupported'"):
        registry.get_provider("unsupported")


def test_profile_configuration_and_fallback_to_default():
    registry = LLMProviderRegistry()
    mock_p = MockProvider("ollama")
    registry.register_provider("ollama", mock_p)

    default_cfg = ModelConfiguration(provider="ollama", model="qwen3.5:4b")
    doc_cfg = ModelConfiguration(provider="ollama", model="llama3.2")

    registry.register_profile("default", default_cfg)
    registry.register_profile("document_analysis", doc_cfg)

    # Direct retrieval
    assert registry.get_profile("document_analysis").model == "llama3.2"
    # Fallback to default when profile not explicitly registered
    assert registry.get_profile("non_existent_profile").model == "qwen3.5:4b"


def test_load_profiles_from_yaml_file(tmp_path):
    yaml_content = """
llm_profiles:
  document_analysis:
    provider: ollama
    model: qwen3.5:4b
    timeout_seconds: 45.0
    temperature: 0.1
    fallback:
      enabled: true
      models:
        - provider: gemini
          model: gemini-1.5-flash
          api_key_env: GEMINI_API_KEY
  foundation_research:
    provider: openai
    model: gpt-4o-mini
    api_key_env: OPENAI_API_KEY
"""
    p = tmp_path / "test_profiles.yaml"
    p.write_text(yaml_content, encoding="utf-8")

    registry = LLMProviderRegistry()
    registry.load_profiles_from_file(p)

    doc_cfg = registry.get_profile("document_analysis")
    assert doc_cfg.provider == "ollama"
    assert doc_cfg.model == "qwen3.5:4b"
    assert doc_cfg.timeout_seconds == 45.0
    assert doc_cfg.temperature == 0.1
    assert len(doc_cfg.fallback_models) == 1
    assert doc_cfg.fallback_models[0].provider == "gemini"
    assert doc_cfg.fallback_models[0].api_key_env == "GEMINI_API_KEY"

    research_cfg = registry.get_profile("foundation_research")
    assert research_cfg.provider == "openai"
    assert research_cfg.model == "gpt-4o-mini"


# ==============================================================================
# 2. Model Switching Without Code Changes
# ==============================================================================

@pytest.mark.asyncio
async def test_switching_provider_through_configuration_alone():
    """Demonstrate that changing profile configuration switches backend model with 0 agent changes."""
    registry = LLMProviderRegistry()
    ollama = MockProvider("ollama", response_text="Generated by Ollama Qwen")
    gemini = MockProvider("gemini", response_text="Generated by Gemini 1.5 Flash")
    registry.register_provider("ollama", ollama)
    registry.register_provider("gemini", gemini)

    # 1. Configured to Ollama
    registry.register_profile("document_analysis", ModelConfiguration(provider="ollama", model="qwen3.5:4b"))
    client = registry.get("document_analysis")
    res1 = await client.generate("Analyze this document")
    assert res1.provider == "ollama"
    assert res1.content == "Generated by Ollama Qwen"

    # 2. Re-configured to Gemini in config without changing client/agent code
    registry.register_profile("document_analysis", ModelConfiguration(provider="gemini", model="gemini-1.5-flash"))
    client2 = registry.get("document_analysis")
    res2 = await client2.generate("Analyze this document")
    assert res2.provider == "gemini"
    assert res2.content == "Generated by Gemini 1.5 Flash"


# ==============================================================================
# 3. Structured Output Compatibility
# ==============================================================================

class DocumentSummary(BaseModel):
    title: str
    key_points: list[str]
    confidence_score: float


@pytest.mark.asyncio
async def test_generate_structured_with_pydantic_schema():
    registry = LLMProviderRegistry()
    sample_json = json.dumps({
        "title": "Agent Platform Architecture",
        "key_points": ["Model-agnostic", "Plugin-based", "LangGraph integrated"],
        "confidence_score": 0.98
    })
    # Wrap in markdown fence to also test markdown fence stripping
    mock_p = MockProvider("ollama", response_text=f"```json\n{sample_json}\n```")
    registry.register_provider("ollama", mock_p)
    registry.register_profile("default", ModelConfiguration(provider="ollama", model="qwen3.5:4b"))

    client = registry.get("default")
    result = await client.generate_structured(DocumentSummary, "Summarize architecture doc")

    assert isinstance(result, DocumentSummary)
    assert result.title == "Agent Platform Architecture"
    assert len(result.key_points) == 3
    assert result.confidence_score == 0.98


@pytest.mark.asyncio
async def test_generate_structured_with_dict_schema():
    registry = LLMProviderRegistry()
    sample_json = json.dumps({"decision": "approved", "reason": "all checks passed"})
    mock_p = MockProvider("ollama", response_text=sample_json)
    registry.register_provider("ollama", mock_p)
    registry.register_profile("default", ModelConfiguration(provider="ollama", model="qwen3.5:4b"))

    client = registry.get("default")
    schema_dict = {"type": "object", "properties": {"decision": {"type": "string"}}}
    result = await client.generate_structured(schema_dict, "Review this decision")

    assert isinstance(result, dict)
    assert result["decision"] == "approved"
    assert result["reason"] == "all checks passed"


# ==============================================================================
# 4. Model Capabilities Validation
# ==============================================================================

@pytest.mark.asyncio
async def test_capability_validation_rejects_unsupported_vision_request():
    registry = LLMProviderRegistry()
    # A model that only supports text, no image
    text_only_caps = ModelCapabilities(text=True, image=False)
    mock_p = MockProvider("ollama", capabilities=text_only_caps)
    registry.register_provider("ollama", mock_p)
    registry.register_profile("default", ModelConfiguration(
        provider="ollama",
        model="qwen3.5:4b",
        capabilities=text_only_caps,
    ))

    client = registry.get("default")
    multimodal_message = LLMMessage.user([
        {"type": "text", "text": "What is in this diagram?"},
        {"type": "image_url", "image_url": "https://example.com/diagram.png"},
    ])

    with pytest.raises(LLMCapabilityError) as exc_info:
        await client.generate([multimodal_message])

    assert "does not support requested capability 'image'" in str(exc_info.value)
    # Ensure provider was never called
    assert len(mock_p.calls) == 0


@pytest.mark.asyncio
async def test_capability_validation_rejects_unsupported_tool_calling():
    registry = LLMProviderRegistry()
    no_tools_caps = ModelCapabilities(text=True, tool_calling=False)
    mock_p = MockProvider("ollama", capabilities=no_tools_caps)
    registry.register_provider("ollama", mock_p)
    registry.register_profile("default", ModelConfiguration(
        provider="ollama",
        model="qwen3.5:4b",
        capabilities=no_tools_caps,
    ))

    client = registry.get("default")
    with pytest.raises(LLMCapabilityError, match="does not support requested capability 'tool_calling'"):
        await client.generate("Run search", tools=[{"type": "function", "function": {"name": "search"}}])

    assert len(mock_p.calls) == 0


# ==============================================================================
# 5. Model Fallback & Error Classification
# ==============================================================================

@pytest.mark.asyncio
async def test_fallback_on_transient_unavailable_error():
    """When primary provider is unavailable, automatically fallback to secondary."""
    registry = LLMProviderRegistry()
    failing_ollama = FailingProvider("ollama", LLMUnavailableError("Connection refused on port 11434"))
    working_gemini = MockProvider("gemini", response_text="Fallback response from Gemini")
    registry.register_provider("ollama", failing_ollama)
    registry.register_provider("gemini", working_gemini)

    config_with_fallback = ModelConfiguration(
        provider="ollama",
        model="qwen3.5:4b",
        fallback_models=[
            ModelConfiguration(provider="gemini", model="gemini-1.5-flash")
        ],
    )
    registry.register_profile("document_analysis", config_with_fallback)

    client = registry.get("document_analysis")
    response = await client.generate("Summarize report")

    assert response.provider == "gemini"
    assert response.model == "gemini-1.5-flash"
    assert response.content == "Fallback response from Gemini"
    assert response.fallback_used is True
    assert "fallback_attempts" in response.metadata
    assert response.metadata["fallback_attempts"][0]["model"] == "ollama/qwen3.5:4b"
    assert response.metadata["fallback_attempts"][0]["error_type"] == "LLMUnavailableError"


@pytest.mark.asyncio
async def test_fallback_on_transient_timeout_error():
    """When primary model times out, automatically fallback to secondary."""
    registry = LLMProviderRegistry()
    timing_out_ollama = FailingProvider("ollama", LLMTimeoutError("Request timed out after 60s"))
    working_backup = MockProvider("ollama_backup", response_text="Fast response from backup model")
    registry.register_provider("ollama", timing_out_ollama)
    registry.register_provider("ollama_backup", working_backup)

    config_with_fallback = ModelConfiguration(
        provider="ollama",
        model="qwen3.5:4b",
        fallback_models=[
            ModelConfiguration(provider="ollama_backup", model="llama3.2")
        ],
    )
    registry.register_profile("document_analysis", config_with_fallback)

    client = registry.get("document_analysis")
    response = await client.generate("Analyze text")

    assert response.fallback_used is True
    assert response.provider == "ollama_backup"
    assert response.model == "llama3.2"


@pytest.mark.asyncio
async def test_no_fallback_on_permanent_auth_error():
    """Authentication errors should NOT fallback because credentials are invalid."""
    registry = LLMProviderRegistry()
    auth_failing_gemini = FailingProvider("gemini", LLMAuthenticationError("Invalid API Key"))
    backup_provider = MockProvider("openai", response_text="Should not be called")
    registry.register_provider("gemini", auth_failing_gemini)
    registry.register_provider("openai", backup_provider)

    config = ModelConfiguration(
        provider="gemini",
        model="gemini-1.5-flash",
        fallback_models=[
            ModelConfiguration(provider="openai", model="gpt-4o")
        ],
    )
    registry.register_profile("default", config)

    client = registry.get("default")
    with pytest.raises(LLMAuthenticationError, match="Invalid API Key"):
        await client.generate("Hello")

    # Backup was not called
    assert len(backup_provider.calls) == 0


@pytest.mark.asyncio
async def test_all_models_fail_raises_aggregated_unavailable_error():
    registry = LLMProviderRegistry()
    failing1 = FailingProvider("ollama", LLMUnavailableError("Ollama down"))
    failing2 = FailingProvider("gemini", LLMUnavailableError("Gemini 503"))
    registry.register_provider("ollama", failing1)
    registry.register_provider("gemini", failing2)

    config = ModelConfiguration(
        provider="ollama",
        model="qwen3.5:4b",
        fallback_models=[
            ModelConfiguration(provider="gemini", model="gemini-1.5-flash")
        ],
    )
    registry.register_profile("default", config)

    client = registry.get("default")
    with pytest.raises(LLMUnavailableError, match="All configured models failed for profile"):
        await client.generate("Hello")


# ==============================================================================
# 6. Token Accounting & Usage Metadata
# ==============================================================================

@pytest.mark.asyncio
async def test_token_accounting_metadata():
    registry = LLMProviderRegistry()
    mock_p = MockProvider("ollama", response_text="Done")
    registry.register_provider("ollama", mock_p)
    registry.register_profile("default", ModelConfiguration(provider="ollama", model="qwen3.5:4b"))

    client = registry.get("default")
    res = await client.generate("Test prompt")
    assert res.usage.prompt_tokens == 15
    assert res.usage.completion_tokens == 25
    assert res.usage.total_tokens == 40


# ==============================================================================
# 7. Credential Protection
# ==============================================================================

def test_api_key_never_stored_in_yaml_or_exposed_in_safe_repr(monkeypatch):
    monkeypatch.setenv("TEST_GEMINI_KEY", "secret-key-12345")

    cfg = ModelConfiguration(
        provider="gemini",
        model="gemini-1.5-flash",
        api_key_env="TEST_GEMINI_KEY",
    )

    # API key is resolved dynamically
    assert cfg.get_api_key() == "secret-key-12345"

    # safe_repr does not expose the key string
    safe = cfg.safe_repr()
    assert "secret-key-12345" not in str(safe)
    assert safe["api_key_configured"] is True
    assert safe["api_key_env"] == "TEST_GEMINI_KEY"


# ==============================================================================
# 8. LangGraph & AgentContext Dependency Injection
# ==============================================================================

@pytest.mark.asyncio
async def test_agent_execution_via_agent_runner_with_dependency_injected_llm():
    """Verify that an agent can request `context.get_llm('document_analysis')` and run cleanly

    via AgentRunner with NO hardcoded model or provider in agent code.
    """
    # 1. Setup Registry and Profile
    llm_registry = LLMProviderRegistry()
    mock_p = MockProvider("ollama", response_text="Extracted document insights")
    llm_registry.register_provider("ollama", mock_p)
    llm_registry.register_profile(
        "document_analysis",
        ModelConfiguration(provider="ollama", model="qwen3.5:4b", temperature=0.2)
    )

    # 2. Define an Agent using Model-Agnostic LLM Interface
    async def sample_doc_analyzer(request: AgentRequest, context: AgentContext) -> dict:
        # Agent has ZERO reference to Ollama or Gemini!
        llm = context.get_llm("document_analysis")
        prompt = f"Analyze: {request.inputs.get('text')}"
        response = await llm.generate(prompt)
        return {
            "analysis": response.content,
            "provider_used": response.provider,
            "model_used": response.model,
            "tokens": response.usage.total_tokens,
        }

    # 3. Register Agent with Platform
    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentMetadata(id="doc_analyzer_agent", name="Document Analyzer"),
        sample_doc_analyzer,
    )

    # 4. Execute via AgentRunner with injected llm_registry
    runner = AgentRunner(registry=agent_registry, llm_registry=llm_registry)
    result = await runner.run(
        "doc_analyzer_agent",
        AgentRequest(run_id="run-001", inputs={"text": "System architecture document"}),
    )

    assert result.status == "succeeded"
    assert result.output["analysis"] == "Extracted document insights"
    assert result.output["provider_used"] == "ollama"
    assert result.output["model_used"] == "qwen3.5:4b"
    assert result.output["tokens"] == 40
    assert result.metadata["execution_id"]


# ==============================================================================
# 9. Real Provider Protocol & HTTP Payload Formatting (MockTransport)
# ==============================================================================

@pytest.mark.asyncio
async def test_ollama_provider_request_formatting_and_response_parsing():
    """Verify OllamaProvider constructs correct /api/chat payload and extracts usage."""
    captured_request = {}

    def mock_ollama_transport(request: httpx.Request) -> httpx.Response:
        captured_request["method"] = request.method
        captured_request["url"] = str(request.url)
        captured_request["body"] = json.loads(request.read())

        response_body = {
            "model": "qwen3.5:4b",
            "message": {
                "role": "assistant",
                "content": '{"summary": "Ollama success"}',
            },
            "prompt_eval_count": 18,
            "eval_count": 22,
            "done": True,
        }
        return httpx.Response(200, json=response_body)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_ollama_transport))
    provider = OllamaProvider(client=mock_client)

    cfg = ModelConfiguration(
        provider="ollama",
        model="qwen3.5:4b",
        api_base="http://localhost:11434",
        temperature=0.3,
        max_tokens=1000,
    )
    req = LLMRequest(
        messages=[LLMMessage.system("Be concise"), LLMMessage.user("Hello")],
        temperature=0.3,
        max_tokens=1000,
        response_format={"type": "json_object"},
    )

    response = await provider.generate(cfg, req)

    # Verify HTTP request
    assert captured_request["method"] == "POST"
    assert captured_request["url"] == "http://localhost:11434/api/chat"
    assert captured_request["body"]["model"] == "qwen3.5:4b"
    assert captured_request["body"]["format"] == "json"
    assert captured_request["body"]["options"]["temperature"] == 0.3
    assert captured_request["body"]["options"]["num_predict"] == 1000
    assert len(captured_request["body"]["messages"]) == 2

    # Verify Response mapping
    assert response.content == '{"summary": "Ollama success"}'
    assert response.usage.prompt_tokens == 18
    assert response.usage.completion_tokens == 22
    assert response.usage.total_tokens == 40
    assert response.structured_output == {"summary": "Ollama success"}


@pytest.mark.asyncio
async def test_gemini_provider_request_formatting_and_response_parsing(monkeypatch):
    """Verify GeminiProvider formats Google Generative Language REST API request."""
    monkeypatch.setenv("MOCK_GEMINI_KEY", "AIzaSyTestKey123")
    captured_request = {}

    def mock_gemini_transport(request: httpx.Request) -> httpx.Response:
        captured_request["method"] = request.method
        captured_request["url"] = str(request.url)
        captured_request["headers"] = dict(request.headers)
        captured_request["body"] = json.loads(request.read())

        response_body = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Gemini answer text"}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 30,
                "totalTokenCount": 50,
            },
        }
        return httpx.Response(200, json=response_body)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_gemini_transport))
    provider = GeminiProvider(client=mock_client)

    cfg = ModelConfiguration(
        provider="gemini",
        model="gemini-1.5-flash",
        api_key_env="MOCK_GEMINI_KEY",
        temperature=0.4,
    )
    req = LLMRequest(
        messages=[LLMMessage.system("You are an assistant"), LLMMessage.user("Hello Gemini")],
        temperature=0.4,
    )

    response = await provider.generate(cfg, req)

    assert captured_request["method"] == "POST"
    assert "models/gemini-1.5-flash:generateContent" in captured_request["url"]
    assert captured_request["headers"]["x-goog-api-key"] == "AIzaSyTestKey123"
    assert captured_request["body"]["systemInstruction"]["parts"][0]["text"] == "You are an assistant"
    assert captured_request["body"]["contents"][0]["parts"][0]["text"] == "Hello Gemini"

    assert response.content == "Gemini answer text"
    assert response.usage.prompt_tokens == 20
    assert response.usage.completion_tokens == 30
    assert response.usage.total_tokens == 50


@pytest.mark.asyncio
async def test_gemini_missing_api_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("UNSET_GEMINI_KEY", raising=False)
    provider = GeminiProvider()
    cfg = ModelConfiguration(provider="gemini", model="gemini-1.5-flash", api_key_env="UNSET_GEMINI_KEY")
    req = LLMRequest(messages=[LLMMessage.user("Hello")])

    with pytest.raises(LLMAuthenticationError, match="No API key found in environment variable 'UNSET_GEMINI_KEY'"):
        await provider.generate(cfg, req)


@pytest.mark.asyncio
async def test_openai_provider_request_formatting_and_response_parsing(monkeypatch):
    """Verify OpenAIProvider formats standard /chat/completions payload and maps usage."""
    monkeypatch.setenv("MOCK_OPENAI_KEY", "sk-proj-test123")
    captured = {}

    def mock_openai_transport(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "OpenAI answer"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 18, "total_tokens": 30},
        })

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_openai_transport))
    provider = OpenAIProvider(client=mock_client)

    cfg = ModelConfiguration(provider="openai", model="gpt-4o-mini", api_key_env="MOCK_OPENAI_KEY")
    req = LLMRequest(messages=[LLMMessage.user("Test prompt")])
    response = await provider.generate(cfg, req)

    assert "chat/completions" in captured["url"]
    assert captured["headers"]["authorization"] == "Bearer sk-proj-test123"
    assert captured["body"]["model"] == "gpt-4o-mini"
    assert response.content == "OpenAI answer"
    assert response.usage.total_tokens == 30


@pytest.mark.asyncio
async def test_anthropic_provider_request_formatting_and_response_parsing(monkeypatch):
    """Verify AnthropicProvider formats /messages payload with system instructions and headers."""
    monkeypatch.setenv("MOCK_ANTHROPIC_KEY", "sk-ant-test123")
    captured = {}

    def mock_anthropic_transport(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "Claude answer"}],
            "usage": {"input_tokens": 25, "output_tokens": 35},
        })

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_anthropic_transport))
    provider = AnthropicProvider(client=mock_client)

    cfg = ModelConfiguration(provider="anthropic", model="claude-3-5-sonnet", api_key_env="MOCK_ANTHROPIC_KEY")
    req = LLMRequest(messages=[LLMMessage.system("Act as tester"), LLMMessage.user("Hello Claude")])
    response = await provider.generate(cfg, req)

    assert "v1/messages" in captured["url"]
    assert captured["headers"]["x-api-key"] == "sk-ant-test123"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["system"] == "Act as tester"
    assert captured["body"]["model"] == "claude-3-5-sonnet"
    assert response.content == "Claude answer"
    assert response.usage.prompt_tokens == 25
    assert response.usage.completion_tokens == 35
    assert response.usage.total_tokens == 60


