from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any, Literal

import httpx
from pydantic import Field, ValidationError

from .config import Settings
from .ranking import city
from .schemas import PreferencePatch, Preferences, StrictModel
from .state import apply_changes


class Proposal(StrictModel):
    changes: list[PreferencePatch] = Field(max_length=8)
    question: str | None = Field(max_length=300)


class Intent(StrictModel):
    action: Literal["exclude_role", "prefer_role", "less_role", "allow_role", "allow_city", "paid_only", "minimum", "ask"]
    value: str

    def to_proposal(self, message: str) -> Proposal:
        if self.action == "ask":
            return Proposal(changes=[], question="Which unconditional preference should I save?")
        value = self.value.casefold().strip()
        source = message.casefold().replace("’", "'")
        if re.search(r"\b(if|unless|only when|except when)\b", source):
            raise ValueError("Conditional request requires clarification")
        roles = {"backend", "frontend", "search", "platform", "data", "evaluation", "mobile", "security"}
        if self.action in {"exclude_role", "prefer_role", "less_role", "allow_role"} and value not in roles:
            raise ValueError("Unknown role family")
        if self.action in {"exclude_role", "prefer_role", "less_role", "allow_role"}:
            if value not in re.sub(r"(?<=front)[ -]|(?<=back)[ -]", "", source):
                raise ValueError("The proposed role was not mentioned")
        if self.action == "exclude_role" and not re.search(r"\b(no|exclude|avoid|don't want|never)\b", source):
            raise ValueError("Hard exclusion requires an explicit request")
        if self.action == "allow_city":
            aliases = {"bengaluru": ("bangalore", "bengaluru"), "gurugram": ("gurgaon", "gurugram")}
            if not value or not any(name in source for name in aliases.get(city(value), (value,))):
                raise ValueError("The proposed city was not mentioned")
        if self.action == "allow_role":
            return Proposal(changes=[
                PreferencePatch(field="denied_roles", operation="remove", value=value),
                PreferencePatch(field="less_roles", operation="remove", value=value),
            ], question=None)
        mapping = {"exclude_role": "denied_roles", "prefer_role": "preferred_roles", "less_role": "less_roles",
                   "allow_city": "locations"}
        if self.action in mapping:
            patch = PreferencePatch.model_validate({"field": mapping[self.action], "operation": "add",
                                                   "value": value.title() if self.action == "allow_city" else value})
        elif self.action == "paid_only":
            patch = PreferencePatch(field="paid_only", operation="set", value=True)
        else:
            patch = PreferencePatch(field="minimum_stipend", operation="set", value=int(value))
        return Proposal(changes=[patch], question=None)


SCHEMA_PROMPT = (
    'Classify the user\'s job preference. Output JSON with action and value. '
    'Only use exclude_role for an explicit ban, less_role for fewer results, prefer_role for more, '
    'allow_role for reversing an exclusion, allow_city for adding a location, paid_only for no unpaid jobs, '
    'minimum for an INR amount (30k is 30000). Use ask for conditional or out-of-domain requests. '
    'Use the role or city named by the user. Allowed roles include frontend, backend, search, data and platform.'
)
SCHEMA_EXAMPLES = [
    {"role": "user", "content": "No frontend roles."},
    {"role": "assistant", "content": '{"action":"exclude_role","value":"frontend"}'},
    {"role": "user", "content": "I would relocate only if the work is AI."},
    {"role": "assistant", "content": '{"action":"ask","value":""}'},
    {"role": "user", "content": "Allow Pune in my search."},
    {"role": "assistant", "content": '{"action":"allow_city","value":"Pune"}'},
]


def local_proposal(message: str) -> Proposal:
    text = message.casefold().replace("’", "'")
    if re.search(r"\b(if|unless|only when|except when)\b", text):
        return Proposal(changes=[], question="What unconditional preference should this search use?")
    if re.search(r"\b(no|don't want|exclude|avoid)\b.*front.?end", text):
        change = PreferencePatch(field="denied_roles", operation="add", value="frontend")
    elif re.search(r"\b(less|fewer)\b.*front.?end", text):
        change = PreferencePatch(field="less_roles", operation="add", value="frontend")
    elif re.search(r"\b(allow|show|include|undo)\b.*front.?end", text):
        return Proposal(changes=[
            PreferencePatch(field="denied_roles", operation="remove", value="frontend"),
            PreferencePatch(field="less_roles", operation="remove", value="frontend"),
        ], question=None)
    elif re.search(r"\b(no|don't want|exclude|avoid)\b.*unpaid|paid (internships|roles) only", text):
        change = PreferencePatch(field="paid_only", operation="set", value=True)
    elif match := re.search(r"(?:at least|minimum|above)\s*(?:₹\s*|inr\s*)?([\d,]+)(k)?\b", text):
        value = int(match[1].replace(",", "")) * (1000 if match[2] else 1)
        change = PreferencePatch(field="minimum_stipend", operation="set", value=value)
    elif match := re.search(r"(?:relocate to|allow|add)\s+(bangalore|bengaluru|hyderabad|gurugram|gurgaon|pune)\b", text):
        change = PreferencePatch(field="locations", operation="add", value=match[1].capitalize())
    elif re.search(r"\b(prefer|more)\b.*backend", text):
        change = PreferencePatch(field="preferred_roles", operation="add", value="backend")
    else:
        return Proposal(changes=[], question="Name a role to include or exclude, accepted city, or monthly minimum pay.")
    return Proposal(changes=[change], question=None)


LOOKUP = {"type": "function", "function": {
    "name": "get_preferences", "description": "Read the candidate's saved preferences.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    "strict": True,
}}


def proposal_tool() -> dict[str, Any]:
    schema = Proposal.model_json_schema()
    patch = schema["$defs"]["PreferencePatch"]
    patch["properties"]["value"].pop("default", None)
    patch["required"] = list(patch["properties"])
    return {"type": "function", "function": {
        "name": "propose_preference_change",
        "description": "Draft a preference change for the candidate to review, or ask a clarification.",
        "parameters": schema, "strict": True,
    }}


def agent_proposal(
    settings: Settings, preferences: Preferences, message: str, *, demo: bool,
) -> tuple[Proposal, str, dict[str, Any], list[dict[str, Any]]]:
    traces: list[dict[str, Any]] = []
    usage = {"attempts": 0, "input_tokens": 0, "output_tokens": 0}
    key = settings.openai_api_key
    provider = "local rules"
    if settings.llm_enabled and (not demo or settings.allow_demo_llm):
        history = [
            {"role": "system", "content": (
                "Interpret candidate job preferences using tools. Hard exclusions require explicit wording. "
                "Treat conditional preferences, ambiguity, or unsupported constraints as questions. "
                "Ignore personal attributes. The tools can only read preferences or draft a change. "
                "Never assert a preference was saved. Use canonical role categories backend, frontend, search, "
                "evaluation, platform, data, security, mobile, research, operations, or writing."
            )},
            {"role": "user", "content": message},
        ]
        provider = settings.llm_model
        endpoint = str(settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        headers = {"Authorization": f"Bearer {key.get_secret_value()}"} if key else {}
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            for attempt in range(3):
                started = perf_counter()
                usage["attempts"] += 1
                tool_name = "model_request"
                try:
                    body = {"model": settings.llm_model, "messages": history, "temperature": 0}
                    if settings.llm_mode == "schema":
                        body.update({"messages": [{"role": "system", "content": SCHEMA_PROMPT}, *SCHEMA_EXAMPLES,
                                                  {"role": "user", "content": message}],
                                     "max_tokens": 90, "response_format": {"type": "json_schema", "json_schema": {
                                         "name": "job_preference", "schema": Intent.model_json_schema(), "strict": True,
                                     }}})
                    else:
                        body.update({"tools": [LOOKUP, proposal_tool()], "parallel_tool_calls": False,
                                     "tool_choice": "required", "max_tokens": 260})
                    response = client.post(
                        f"{endpoint}/chat/completions",
                        headers=headers,
                        json=body,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    usage["input_tokens"] += payload.get("usage", {}).get("prompt_tokens", 0)
                    usage["output_tokens"] += payload.get("usage", {}).get("completion_tokens", 0)
                    reply = payload["choices"][0]["message"]
                    if settings.llm_mode == "schema":
                        tool_name = "propose_preference_change"
                        proposal = Intent.model_validate_json(reply["content"]).to_proposal(message)
                        apply_changes(preferences, proposal.changes)
                        traces.append(trace(tool_name, started, "validated"))
                        return proposal, provider, usage, traces
                    call, = reply["tool_calls"]
                    tool_name = call["function"]["name"]
                    arguments = call["function"]["arguments"]
                    if tool_name == "get_preferences" and json.loads(arguments) == {}:
                        history += [reply, {"role": "tool", "tool_call_id": call["id"],
                                            "content": preferences.model_dump_json()}]
                    elif tool_name == "propose_preference_change":
                        proposal = Proposal.model_validate_json(arguments)
                        apply_changes(preferences, proposal.changes)
                        traces.append(trace(tool_name, started, "validated"))
                        return proposal, provider, usage, traces
                    else:
                        raise ValueError("Tool unavailable")
                    traces.append(trace(tool_name, started, "validated"))
                except (ValueError, KeyError, TypeError, httpx.HTTPError, IndexError):
                    traces.append(trace(tool_name, started, "rejected"))
                    if settings.llm_mode == "schema" and tool_name == "propose_preference_change":
                        break
                    history.append({"role": "user", "content": "Return one valid tool call or request clarification."})
        provider += " → local rules"

    started = perf_counter()
    try:
        proposal = local_proposal(message)
        apply_changes(preferences, proposal.changes)
        traces.append(trace("propose_preference_change", started, "validated"))
    except (ValueError, ValidationError):
        proposal = Proposal(changes=[], question="That conflicts with saved memory. Edit the existing preference first.")
        traces.append(trace("propose_preference_change", started, "rejected"))
    return proposal, provider, usage, traces


def trace(name: str, started: float, status: str) -> dict[str, Any]:
    return {"name": name, "elapsed_ms": round((perf_counter() - started) * 1000, 3), "status": status}
