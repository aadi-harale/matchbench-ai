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
    action: Literal[
        "exclude_role", "prefer_role", "less_role", "allow_role", "allow_city", "exclude_city",
        "prefer_work_mode", "relocation", "exclude_company", "prefer_skill", "paid_only", "minimum", "ask",
    ]
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
        if self.action in {"allow_city", "exclude_city"}:
            aliases = {"bengaluru": ("bangalore", "bengaluru"), "gurugram": ("gurgaon", "gurugram")}
            if not value or not any(name in source for name in aliases.get(city(value), (value,))):
                raise ValueError("The proposed city was not mentioned")
        if self.action == "allow_role":
            return Proposal(changes=[
                PreferencePatch(field="denied_roles", operation="remove", value=value),
                PreferencePatch(field="less_roles", operation="remove", value=value),
            ], question=None)
        mapping = {
            "exclude_role": "denied_roles", "prefer_role": "preferred_roles", "less_role": "less_roles",
            "allow_city": "locations", "exclude_city": "excluded_locations",
            "prefer_work_mode": "preferred_work_modes", "exclude_company": "denied_companies",
            "prefer_skill": "preferred_skills",
        }
        if self.action in mapping:
            patch = PreferencePatch.model_validate({"field": mapping[self.action], "operation": "add",
                                                   "value": value.title() if self.action in {
                                                       "allow_city", "exclude_city", "exclude_company",
                                                   } else value})
        elif self.action == "paid_only":
            patch = PreferencePatch(field="paid_only", operation="set", value=True)
        elif self.action == "relocation":
            patch = PreferencePatch(field="allow_relocation", operation="set", value=value in {"yes", "true"})
        else:
            patch = PreferencePatch(field="minimum_stipend", operation="set", value=int(value))
        return Proposal(changes=[patch], question=None)


SCHEMA_PROMPT = (
    'Classify the user\'s job preference. Output JSON with action and value. '
    'Only use exclude_role for an explicit ban, less_role for fewer results, prefer_role for more, '
    'allow_role for reversing an exclusion, allow_city for adding a location, paid_only for no unpaid jobs, '
    'exclude_city for a rejected location, prefer_work_mode for remote/hybrid/on-site, relocation for yes/no, '
    'exclude_company for an explicitly named employer, prefer_skill for an explicitly prioritized technology, '
    'minimum for an INR amount (30k is 30000). Use ask for conditional, temporary, do-not-store, protected-attribute, '
    'interest-without-preference, multi-change, or out-of-domain requests. '
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
    if re.search(r"\b(if|unless|only when|except when|for now|temporar(?:y|ily)|this search only)\b", text):
        return Proposal(changes=[], question="What unconditional preference should this search use?")
    if re.search(r"\b(don't|do not)\s+(save|store|remember)\b", text):
        return Proposal(changes=[], question="Should I apply this only to the current search without saving it?")
    if re.search(r"\b(gender|religion|religious|age|marital|married|caste|ethnicity)\b", text):
        return Proposal(changes=[], question="Protected personal attributes are not ranking preferences.")
    if re.search(r"\b(interested in|learning|want to learn|curious about)\b", text):
        return Proposal(changes=[], question="Should I prioritize jobs using that technology, without treating it as experience?")

    changes: list[PreferencePatch] = []
    roles = "frontend|backend|search|platform|data|evaluation|mobile|security|research|operations|writing"
    if match := re.search(rf"\b({roles})\b", text.replace("front-end", "frontend").replace("back-end", "backend")):
        role = match[1]
        if re.search(r"\b(no|don't want|exclude|avoid|never)\b", text):
            changes.append(PreferencePatch(field="denied_roles", operation="add", value=role))
        elif re.search(r"\b(less|fewer)\b", text):
            changes.append(PreferencePatch(field="less_roles", operation="add", value=role))
        elif re.search(r"\b(undo)\b", text) or (
            re.search(r"\b(allow|show|include|okay again|ok again)\b", text) and "again" in text
        ):
            changes.extend([
                PreferencePatch(field="denied_roles", operation="remove", value=role),
                PreferencePatch(field="less_roles", operation="remove", value=role),
            ])
        elif re.search(r"\b(prefer|more|prioriti[sz]e|rank .*higher)\b", text):
            changes.append(PreferencePatch(field="preferred_roles", operation="add", value=role))

    if re.search(r"\b(no|don't want|exclude|avoid)\b.*unpaid|paid (internships|roles|jobs) only", text):
        changes.append(PreferencePatch(field="paid_only", operation="set", value=True))
    if match := re.search(r"(?:at least|minimum|above)\s*(?:is|to)?\s*(?:₹\s*|inr\s*)?([\d,]+)(k)?\b", text):
        amount = int(match[1].replace(",", "")) * (1000 if match[2] else 1)
        changes.append(PreferencePatch(field="minimum_stipend", operation="set", value=amount))

    cities = "bangalore|bengaluru|hyderabad|gurugram|gurgaon|pune|mumbai|delhi|chennai"
    if match := re.search(rf"\b({cities})\b", text):
        location = match[1].title()
        if re.search(r"\b(don't|do not|exclude|avoid|not in)\b", text):
            changes.append(PreferencePatch(field="excluded_locations", operation="add", value=location))
        elif re.search(r"\b(okay again|ok again|acceptable again)\b", text):
            changes.append(PreferencePatch(field="excluded_locations", operation="remove", value=location))
        elif re.search(r"\b(relocate to|allow|add|include|open to|accepted cities?)\b", text):
            changes.append(PreferencePatch(field="locations", operation="add", value=location))

    if re.search(r"\b(can|will|open to) relocate\b", text):
        changes.append(PreferencePatch(field="allow_relocation", operation="set", value=True))
    elif re.search(r"\b(can't|cannot|won't|not able to) relocate\b", text):
        changes.append(PreferencePatch(field="allow_relocation", operation="set", value=False))

    if match := re.search(r"\b(prefer|prioriti[sz]e|more)\b.*\b(remote|hybrid|on-site|onsite)\b", text):
        mode = "on-site" if match[2] == "onsite" else match[2]
        changes.append(PreferencePatch(field="preferred_work_modes", operation="add", value=mode))

    if match := re.search(r"\b(?:don't show|do not show|exclude|avoid)\b.*\b(?:jobs|roles)\s+from\s+([a-z0-9][a-z0-9 &.-]{1,60})[.!]?$", text):
        changes.append(PreferencePatch(field="denied_companies", operation="add", value=match[1].strip(" .").title()))

    if match := re.search(r"\b(?:prefer|prioriti[sz]e)\b.*\b(kubernetes|redis|fastapi|python|postgresql|docker)\b", text):
        changes.append(PreferencePatch(field="preferred_skills", operation="add", value=match[1].title()))

    unique: dict[tuple[str, str, str], PreferencePatch] = {}
    for change in changes:
        unique[(change.field, change.operation, str(change.value).casefold())] = change
    if not unique:
        return Proposal(changes=[], question="Name a role to include or exclude, accepted city, or monthly minimum pay.")
    return Proposal(changes=list(unique.values()), question=None)


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
