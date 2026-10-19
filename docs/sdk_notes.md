# SDK notes

Pre-filled on 17 and 18 Oct 2026 by running crewai 1.15.28, pydantic 2.12.5 (pinned by CrewAI), streamlit 1.66.0 and google-genai 2.31.0 in a throwaway Python 3.13.16 environment. **The coding agent must re-run the probe below against the versions `uv` installs and correct this file where anything differs.** Anything not listed here is unverified: do not guess.

## Verified imports
```python
import os
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"   # set before importing crewai
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
from crewai.llms.base_llm import BaseLLM
```

## Verified behaviour
| Topic | Result |
|---|---|
| Gemini LLM | `LLM(model="gemini/gemini-3.8-flash", api_key=...)` constructs the native Gemini provider class (no network at construction). `gemini-3.8-flash` is listed Stable on the official Gemini models page (17 Oct 2026). Free-tier rate limits are not verified: read the rate-limit page before T14. |
| Fake LLM | Subclass `BaseLLM`: `llm_type: str = "scripted"`, `__init__` calls `super().__init__(model="x")`, implement `call(self, messages, tools=None, callbacks=None, available_functions=None, from_task=None, from_agent=None, response_model=None, **kw)` returning text, and `supports_function_calling()` returning `False`. |
| Token usage | In `call`, `self._track_token_usage_internal({"prompt_tokens": n, "completion_tokens": m, "total_tokens": n+m})`. Read per instance with `llm.get_token_usage_summary().total_tokens`. Crew total is `result.token_usage.total_tokens`. Per-agent tracking works with one LLM instance per agent. |
| Tools offline | With `supports_function_calling() == False`, CrewAI uses the text ReAct format. A scripted reply `Thought: ...\nAction: get_stock\nAction Input: {"sku": "S1"}` made CrewAI run the real `@tool` function; the next scripted reply `Thought: I now know the final answer\nFinal Answer: {"qty": 7}` finished the task. Two LLM calls for one tool use. |
| Structured output | `Task(output_pydantic=Model)`: a reply that is valid JSON for the model gives `result.pydantic`; both bare JSON and `Final Answer: {...}` worked. |
| Malformed output | A reply with a wrong type (`{"qty": "many"}`) makes `kickoff()` raise `pydantic.ValidationError`. |
| Guardrail | `Task(guardrail=fn, guardrail_max_retries=n)`; `fn(output)` returns `(True, output)` to pass or `(False, "message")` to retry. With `guardrail_max_retries=1` and a function that always fails, the LLM was called twice and `kickoff()` raised `Exception("Task failed guardrail validation after 1 retries. Last error: <message>")`. |
| Stopping the crew | An exception raised inside `Crew(task_callback=fn)` propagates out of `kickoff()`; the next task is never started (probe: LLM B received 0 calls). |
| Context | `Task(context=[earlier_task])` passes earlier outputs; two sequential tasks with two agents and `output_pydantic` returned `tasks_output[i].pydantic` for each. |
| Crew options | `Crew(..., process=Process.sequential, tracing=False)` accepted. `Agent(allow_delegation=False, max_iter=n, max_rpm=n, verbose=False)` accepted. |
| `@tool` | `from crewai.tools import tool`; `@tool("name")` on a typed function with a docstring gives a tool object whose `args_schema` lists the parameters. |
| OTel packages exist | `opentelemetry-instrumentation-crewai` and `opentelemetry-instrumentation-google-generativeai` (0.62.4) are on PyPI. Whether they give complete LangSmith traces of Gemini calls under CrewAI is **not verified**: T13 reads the LangSmith docs page for CrewAI tracing and T14 checks the real traces. |

## Not verified (decide with evidence, record in `docs/decisions.md` or `docs/open_questions.md`)
1. Whether CrewAI's native Gemini provider reports token usage including Gemini "thoughts" tokens (T14 compares with the Gemini usage page).
2. Native function-calling behaviour under Gemini (the offline probe uses the ReAct text format). Live runs (T14) may differ; Gemini 3 models may require "thought signatures" to be passed back between function-call turns, so check the Gemini function-calling docs and the real behaviour before claiming it works.
3. Whether `OTEL_SDK_DISABLED=true` must be unset for LangSmith tracing; the order of tracer setup versus `CREWAI_DISABLE_TELEMETRY`.
4. Gemini free-tier rate limits and data-use terms; Azure welcome-offer terms (not needed for this repo).
5. Behaviour on Python 3.14 (CrewAI requires < 3.14): do not use it.

## Probe (re-run; run it with `uv run python -I probe.py` from a scratch folder, not committed)
```python
import os
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
from crewai.llms.base_llm import BaseLLM
from pydantic import BaseModel

CALLED = []

@tool("get_stock")
def get_stock(sku: str) -> str:
    """Return on-hand stock for a SKU."""
    CALLED.append(sku)
    return '{"on_hand": 7}'

class Out(BaseModel):
    qty: int

class Scripted(BaseLLM):
    llm_type: str = "scripted"

    def __init__(self, replies):
        super().__init__(model="scripted")
        self._r = list(replies)

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None, **kw):
        self._track_token_usage_internal({"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55})
        return self._r.pop(0)

    def supports_function_calling(self):
        return False

# 1) Gemini LLM constructs offline
g = LLM(model="gemini/gemini-3.8-flash", api_key="dummy")
print("gemini LLM:", type(g).__module__, type(g).__name__)

# 2) tool runs through the ReAct text format
llm = Scripted(['Thought: need stock\nAction: get_stock\nAction Input: {"sku": "S1"}',
                'Thought: I now know the final answer\nFinal Answer: {"qty": 7}'])
a = Agent(role="Inv", goal="g", backstory="b", llm=llm, tools=[get_stock], allow_delegation=False, max_iter=4)
t = Task(description="Plan {sku}", expected_output="json", agent=a, output_pydantic=Out)
r = Crew(agents=[a], tasks=[t], process=Process.sequential, tracing=False).kickoff(inputs={"sku": "S1"})
print("tool called:", CALLED, "| pydantic:", r.pydantic, "| usage:", llm.get_token_usage_summary().total_tokens)

# 3) guardrail failure raises after retries
def always_fail(out):
    return (False, "bad qty")
llm2 = Scripted(['{"qty": 1}', '{"qty": 1}', '{"qty": 1}'])
a2 = Agent(role="A", goal="g", backstory="b", llm=llm2, allow_delegation=False)
t2 = Task(description="one", expected_output="json", agent=a2, output_pydantic=Out,
          guardrail=always_fail, guardrail_max_retries=1)
try:
    Crew(agents=[a2], tasks=[t2], process=Process.sequential, tracing=False).kickoff()
except Exception as e:
    print("guardrail exhausted:", type(e).__name__, str(e)[:80])

# 4) exception in task_callback stops the crew
class Boom(Exception):
    pass

def cb(output):
    raise Boom("budget")

la, lb = Scripted(['{"qty": 1}']), Scripted(['{"qty": 2}'])
x = Agent(role="X", goal="g", backstory="b", llm=la, allow_delegation=False)
y = Agent(role="Y", goal="g", backstory="b", llm=lb, allow_delegation=False)
t_x = Task(description="x", expected_output="json", agent=x, output_pydantic=Out)
t_y = Task(description="y", expected_output="json", agent=y, output_pydantic=Out, context=[t_x])
try:
    Crew(agents=[x, y], tasks=[t_x, t_y], process=Process.sequential, tracing=False, task_callback=cb).kickoff()
except Boom:
    print("task_callback exception propagated; second agent replies left:", len(lb._r))

# 5) wrong type from the LLM raises ValidationError
bad = Scripted(['{"qty": "many"}'])
a3 = Agent(role="A", goal="g", backstory="b", llm=bad, allow_delegation=False)
t3 = Task(description="one", expected_output="json", agent=a3, output_pydantic=Out)
try:
    Crew(agents=[a3], tasks=[t3], process=Process.sequential, tracing=False).kickoff()
except Exception as e:
    print("malformed output:", type(e).__name__)
```
Expected output (order as above; warnings may appear): `gemini LLM: crewai.llms.providers.gemini.completion GeminiCompletion`; `tool called: ['S1'] | pydantic: qty=7 | usage: 110`; `guardrail exhausted: Exception Task failed guardrail validation after 1 retries...`; `task_callback exception propagated; second agent replies left: 1`; `malformed output: ValidationError`.
