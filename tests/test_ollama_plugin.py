import os

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.runtime.runner import AgentRunner
from app.registry import AgentRegistry
from app.sdk.contracts import AgentMetadata, AgentRequest
from app.storage.repository import ExecutionRepository
from plugins.examples.ollama_text_summarizer import agent


class FakeModel:
    async def generate(self, prompt: str) -> str:
        assert "Quarterly review" in prompt
        return "Quarterly review summary"


@pytest.mark.asyncio
async def test_ollama_plugin_uses_fake_model_without_network(monkeypatch):
    monkeypatch.setattr(agent, "OllamaClient", lambda settings=None: FakeModel())
    registry = AgentRegistry()
    registry.register(AgentMetadata(id="ollama_test", name="Ollama Test"), agent.run)
    result = await AgentRunner(registry).run(
        "ollama_test",
        AgentRequest(run_id="ollama-run", inputs={"text": "Quarterly review is next Tuesday."}),
    )
    assert result.status == "succeeded"
    assert result.output["summary"] == "Quarterly review summary"
    assert result.metadata["execution_id"]
    assert result.metadata["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_ollama_unavailable_becomes_a_traceable_failed_result(monkeypatch):
    async def unavailable(self, prompt):
        raise agent.OllamaUnavailableError("Ollama is unavailable for test")
    monkeypatch.setattr(agent.OllamaClient, "generate", unavailable)
    registry = AgentRegistry()
    registry.register(AgentMetadata(id="ollama_unavailable", name="Ollama Unavailable"), agent.run)
    result = await AgentRunner(registry).run(
        "ollama_unavailable",
        AgentRequest(run_id="ollama-failed", inputs={"text": "Some text"}),
    )
    assert result.status == "failed"
    assert result.error.code == "OllamaUnavailableError"
    assert "unavailable" in result.error.message
    assert result.metadata["duration_ms"] >= 0


def test_ollama_agent_is_discovered_and_runs_through_api_with_fake_model(tmp_path, monkeypatch):
    async def fake_generate(self, prompt):
        return "Fake API summary"
    monkeypatch.setattr(agent.OllamaClient, "generate", fake_generate)
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "ollama-api.db")))) as client:
        agents = client.get("/v1/agents").json()
        assert any(item["id"] == "ollama_text_summarizer" for item in agents)
        workflow = {"id":"ollama_api_flow","nodes":[
            {"id":"summarize","type":"agent","agent_id":"ollama_text_summarizer","input_mappings":{"text":{"path":"workflow_input.text"}}},
            {"id":"draft","type":"agent","agent_id":"email_reply_writer","input_mappings":{"email_summary":{"path":"node_outputs.summarize.summary"}}}],
            "edges":[{"from":"summarize","to":"draft"}]}
        assert client.post("/v1/workflows", json=workflow).status_code == 200
        response = client.post("/v1/runs", json={"workflow_id":"ollama_api_flow","inputs":{"text":"Local model test"}})
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "succeeded"
        assert body["payload"]["node_outputs"]["draft"]["draft"] == "Thanks for the update regarding: Fake API summary"
        events = client.get(f"/v1/runs/{body['run_id']}/events").json()
        assert [event["node_id"] for event in events] == ["summarize", "draft"]


@pytest.mark.skipif(os.getenv("RUN_OLLAMA_TESTS") != "1", reason="set RUN_OLLAMA_TESTS=1 to test a live local Ollama service")
@pytest.mark.asyncio
async def test_live_ollama_integration_is_optional():
    result = await agent.run(
        AgentRequest(run_id="ollama-live", inputs={"text": "A short live integration test."}),
        None,
    )
    assert result["summary"]

