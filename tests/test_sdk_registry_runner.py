import pytest

from app.registry import AgentRegistry
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentMetadata, AgentRequest
from plugins.examples.deterministic_agent import run


def make_registry():
    registry = AgentRegistry()
    registry.register(AgentMetadata(id="echo_agent", name="Echo"), run)
    return registry


@pytest.mark.asyncio
async def test_runner_executes_deterministic_agent():
    result = await AgentRunner(make_registry()).run("echo_agent", AgentRequest(run_id="r1", inputs={"message": "hello"}))
    assert result.status == "succeeded"
    assert result.output["message"] == "hello"
    assert result.metadata["execution_id"]


def test_registry_rejects_duplicates_and_untrusted_entrypoints():
    registry = make_registry()
    with pytest.raises(ValueError):
        registry.register(AgentMetadata(id="echo_agent", name="Duplicate"), run)
    with pytest.raises(ValueError):
        registry.register_entrypoint(AgentMetadata(id="bad_agent", name="Bad"), "os:path")


@pytest.mark.asyncio
async def test_runner_normalizes_failures():
    def broken(request, context):
        raise RuntimeError("boom")
    registry = AgentRegistry()
    registry.register(AgentMetadata(id="broken_agent", name="Broken"), broken)
    result = await AgentRunner(registry).run("broken_agent", AgentRequest(run_id="r2"))
    assert result.status == "failed"
    assert result.error.code == "RuntimeError"
    assert result.metadata["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_runner_preserves_duration_for_explicit_failed_result():
    def rejected(request, context):
        from app.sdk.contracts import AgentResult, ErrorInfo
        return AgentResult(status="failed", error=ErrorInfo(code="Rejected", message="not accepted"))
    registry = AgentRegistry()
    registry.register(AgentMetadata(id="rejected_agent", name="Rejected"), rejected)
    result = await AgentRunner(registry).run("rejected_agent", AgentRequest(run_id="r-explicit"))
    assert result.status == "failed"
    assert result.metadata["execution_id"]
    assert result.metadata["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_unrelated_third_agent_needs_no_core_changes():
    registry = make_registry()
    def reverse(request, context):
        return {"value": request.inputs["value"][::-1]}
    registry.register(AgentMetadata(id="unrelated_reverse", name="Reverse"), reverse)
    result = await AgentRunner(registry).run("unrelated_reverse", AgentRequest(run_id="r3", inputs={"value": "abc"}))
    assert result.output["value"] == "cba"

