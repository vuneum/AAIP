"""
AAIP SDK Test Suite
Tests for client, models, PoE, and adapters.
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from aaip import AAIPClient, AsyncAAIPClient, AgentManifest, ProofOfExecution, PoETrace, PoETraceStep
from aaip.models import EvaluationResponse, DiscoveryResult


# ─────────────────────────────────────────────
# AgentManifest tests
# ─────────────────────────────────────────────

class TestAgentManifest:
    def test_basic_manifest(self):
        m = AgentManifest(
            agent_name="TestAgent",
            owner="TestCo",
            endpoint="https://api.test.com/agent",
            capabilities=["code_analysis", "translation"],
            framework="langchain",
        )
        assert m.agent_name == "TestAgent"
        assert "code_analysis" in m.capabilities
        assert m.framework == "langchain"

    def test_to_dict_excludes_empty(self):
        m = AgentManifest(agent_name="A", owner="B", endpoint="https://x.com")
        d = m.to_dict()
        assert "agent_name" in d
        assert "payment" not in d  # None excluded

    def test_from_dict(self):
        data = {
            "agent_name": "X",
            "owner": "Y",
            "endpoint": "https://x.com",
            "capabilities": ["search"],
        }
        m = AgentManifest.from_dict(data)
        assert m.agent_name == "X"
        assert m.capabilities == ["search"]


# ─────────────────────────────────────────────
# PoE Trace tests
# ─────────────────────────────────────────────

class TestPoETrace:
    def test_create_trace(self):
        trace = PoETrace(
            task_id="t-001",
            agent_id="co/agent/abc",
            task_description="Test task",
            started_at_ms=int(time.time() * 1000),
            completed_at_ms=0,
        )
        assert trace.task_id == "t-001"
        assert trace.step_count == 0

    def test_add_tool_call(self):
        trace = PoETrace(
            task_id="t-001",
            agent_id="co/agent/abc",
            task_description="Test",
            started_at_ms=int(time.time() * 1000),
            completed_at_ms=0,
        )
        trace.add_tool_call("web_search", {"q": "test"}, {"results": []}, latency_ms=100)
        assert trace.total_tool_calls == 1
        assert len(trace.tool_calls) == 1

    def test_add_reasoning(self):
        trace = PoETrace(
            task_id="t-001",
            agent_id="co/agent/abc",
            task_description="Test",
            started_at_ms=int(time.time() * 1000),
            completed_at_ms=0,
        )
        trace.add_reasoning("I should search for more data")
        assert len(trace.reasoning_steps) == 1

    def test_compute_hash_deterministic(self):
        trace = PoETrace(
            task_id="t-001",
            agent_id="co/agent/abc",
            task_description="Test",
            started_at_ms=1000,
            completed_at_ms=2000,
        )
        h1 = trace.compute_hash()
        h2 = trace.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_hash_changes_with_steps(self):
        trace = PoETrace(
            task_id="t-001",
            agent_id="co/agent/abc",
            task_description="Test",
            started_at_ms=1000,
            completed_at_ms=2000,
        )
        h1 = trace.compute_hash()
        trace.add_tool_call("tool", {}, {})
        h2 = trace.compute_hash()
        assert h1 != h2  # Hash must change when steps are added

    def test_to_dict_includes_poe_hash(self):
        trace = PoETrace(
            task_id="t-001",
            agent_id="co/agent/abc",
            task_description="Test",
            started_at_ms=1000,
            completed_at_ms=2000,
        )
        d = trace.to_dict()
        assert "poe_hash" in d
        assert len(d["poe_hash"]) == 64


# ─────────────────────────────────────────────
# ProofOfExecution context manager tests
# ─────────────────────────────────────────────

class TestProofOfExecution:
    def test_context_manager(self):
        with ProofOfExecution("t-001", "co/agent/abc", "Test") as poe:
            poe.tool("search", {"q": "test"}, {"results": [1, 2]}, latency_ms=50)
            poe.reason("Found 2 results")
            poe.llm_call("gpt-4o", tokens_in=100, tokens_out=200, latency_ms=300)

        assert poe.trace.total_tool_calls == 1
        assert poe.trace.total_llm_calls == 1
        assert poe.trace.completed_at_ms > 0

    def test_hash_available_after_context(self):
        with ProofOfExecution("t-001", "co/agent/abc") as poe:
            poe.tool("search", {}, {})

        assert len(poe.hash) == 64

    def test_summary(self):
        with ProofOfExecution("t-001", "co/agent/abc", "Test") as poe:
            poe.tool("t1", {}, {})
            poe.tool("t2", {}, {})

        s = poe.summary
        assert s["tool_calls"] == 2
        assert s["steps"] == 2
        assert "poe_hash" in s

    def test_api_call_tracking(self):
        with ProofOfExecution("t-001", "co/agent/abc") as poe:
            poe.api_call("https://api.example.com/data", latency_ms=80)

        assert poe.trace.total_api_calls == 1

    def test_retrieval_tracking(self):
        with ProofOfExecution("t-001", "co/agent/abc") as poe:
            poe.retrieval("vector_db", items_found=5, latency_ms=20)

        assert poe.trace.step_count == 1


# ─────────────────────────────────────────────
# track_tool decorator tests
# ─────────────────────────────────────────────

class TestTrackToolDecorator:
    def test_sync_decorator(self):
        from aaip import track_tool
        with ProofOfExecution("t-001", "co/agent/abc") as poe:
            @track_tool(poe, "my_tool")
            def my_func(x):
                return x * 2

            result = my_func(5)

        assert result == 10
        assert poe.trace.total_tool_calls == 1

    @pytest.mark.asyncio
    async def test_async_decorator(self):
        from aaip import track_tool
        with ProofOfExecution("t-001", "co/agent/abc") as poe:
            @track_tool(poe, "async_tool")
            async def async_func(x):
                return x + 1

            result = await async_func(10)

        assert result == 11
        assert poe.trace.total_tool_calls == 1


# ─────────────────────────────────────────────
# EvaluationResponse tests
# ─────────────────────────────────────────────

class TestEvaluationResponse:
    def test_grade_elite(self):
        r = EvaluationResponse(
            evaluation_id="e-001",
            agent_id="co/agent/abc",
            task_domain="coding",
            judge_scores={"gpt-4": 96, "claude": 97},
            final_score=96.5,
            score_variance=0.5,
            agreement_level="high",
        )
        assert r.grade == "Elite"
        assert r.passed is True

    def test_grade_unrated(self):
        r = EvaluationResponse(
            evaluation_id="e-002",
            agent_id="co/agent/abc",
            task_domain="general",
            judge_scores={"gpt-4": 50},
            final_score=55.0,
            score_variance=5.0,
            agreement_level="low",
        )
        assert r.grade == "Unrated"
        assert r.passed is False


# ─────────────────────────────────────────────
# Client tests (mocked)
# ─────────────────────────────────────────────

class TestAAIPClient:
    def test_client_init_from_env(self, monkeypatch):
        monkeypatch.setenv("AAIP_API_KEY", "test-key-123")
        from aaip.client import AAIPClient
        client = AAIPClient()
        assert client.api_key == "test-key-123"

    def test_client_headers_include_auth(self):
        from aaip.client import _BaseClient
        c = _BaseClient(api_key="sk-test")
        h = c._headers()
        assert h["Authorization"] == "Bearer sk-test"
        assert "User-Agent" in h

    def test_client_headers_no_auth_when_no_key(self):
        from aaip.client import _BaseClient
        c = _BaseClient(api_key="")
        h = c._headers()
        assert "Authorization" not in h


# ─────────────────────────────────────────────
# Framework adapter unit tests
# ─────────────────────────────────────────────

class TestLangChainAdapter:
    def test_register_langchain_agent(self):
        from aaip.adapters.langchain import register_langchain_agent
        from aaip import AAIPClient

        mock_client = MagicMock(spec=AAIPClient)
        mock_client.register.return_value = {"aaip_agent_id": "co/agent/abc123"}

        result = register_langchain_agent(
            client=mock_client,
            agent_name="TestAgent",
            owner="TestCo",
            endpoint="https://api.test.com",
            capabilities=["code_analysis"],
        )

        mock_client.register.assert_called_once()
        call_args = mock_client.register.call_args[0][0]
        assert call_args.framework == "langchain"
        assert "code_analysis" in call_args.capabilities


class TestCrewAIAdapter:
    def test_register_crew(self):
        from aaip.adapters.crewai import register_crew
        from aaip import AAIPClient

        mock_client = MagicMock(spec=AAIPClient)
        mock_client.register.return_value = {"aaip_agent_id": "co/crew/abc123"}

        mock_crew = MagicMock()
        mock_agent = MagicMock()
        mock_agent.role = "Research Analyst"
        mock_crew.agents = [mock_agent]

        result = register_crew(
            client=mock_client,
            crew=mock_crew,
            agent_name="ResearchCrew",
            owner="TestCo",
            endpoint="https://api.test.com",
        )

        mock_client.register.assert_called_once()
        call_args = mock_client.register.call_args[0][0]
        assert call_args.framework == "crewai"
        assert "research_analyst" in call_args.capabilities
