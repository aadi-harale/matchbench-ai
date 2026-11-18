import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import DATA
from .db import EvidenceRow, PreferenceEvent, ProfileVersion, User
from .ranking import city
from .schemas import PreferencePatch, Preferences, Profile


class VersionConflict(ValueError):
    pass


def load_json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def profile_at(session: Session, user: User, version: int | None = None) -> tuple[int, Profile]:
    query = select(ProfileVersion).where(ProfileVersion.user_id == user.id)
    if version is not None:
        query = query.where(ProfileVersion.version == version)
    row = session.scalar(query.order_by(ProfileVersion.version.desc()).limit(1))
    if not row:
        return 0, Profile()
    entries = list(session.scalars(
        select(EvidenceRow.detail).where(EvidenceRow.profile_id == row.id).order_by(EvidenceRow.id)
    ))
    return row.version, Profile.model_validate(row.facts | {"evidence": entries})


def write_profile(session: Session, user: User, profile: Profile, expected: int) -> int:
    session.get(User, user.id, with_for_update=True)
    version, _ = profile_at(session, user)
    if expected != version:
        raise VersionConflict("The profile changed. Reload it, then retry.")
    row = ProfileVersion(user_id=user.id, version=version + 1, facts=profile.model_dump(
        mode="json", exclude={"evidence"},
    ))
    session.add(row)
    session.flush()
    session.add_all([
        EvidenceRow(profile_id=row.id, evidence_key=item.id, skill=item.skill, detail=item.model_dump(mode="json"))
        for item in profile.evidence
    ])
    return row.version


def preference_at(session: Session, user: User, version: int | None = None) -> tuple[int, Preferences]:
    if version == 0:
        return 0, Preferences()
    query = select(PreferenceEvent).where(PreferenceEvent.user_id == user.id)
    if version is not None:
        query = query.where(PreferenceEvent.version == version)
    row = session.scalar(query.order_by(PreferenceEvent.version.desc()).limit(1))
    return (row.version, Preferences.model_validate(row.state)) if row else (0, Preferences())


def apply_changes(preferences: Preferences, changes: list[PreferencePatch]) -> Preferences:
    state = preferences.model_dump()
    defaults = Preferences().model_dump()
    for change in changes:
        key, operation, value = change.field, change.operation, change.value
        if operation == "clear":
            if value is not None:
                raise ValueError("A clear operation takes no value.")
            state[key] = defaults[key]
        elif operation == "set":
            state[key] = value
        else:
            if key not in state or not isinstance(state[key], list) or not isinstance(value, str):
                raise ValueError("Add and remove require one value in a list preference.")
            canonical = city if key in {"locations", "excluded_locations"} else str.casefold
            values = [entry for entry in state[key] if canonical(entry) != canonical(value)]
            state[key] = values + [value] if operation == "add" else values
    updated = Preferences.model_validate(state)
    if {city(value) for value in updated.locations} & {city(value) for value in updated.excluded_locations}:
        raise ValueError("The same city is both accepted and excluded.")
    return updated


def write_preferences(
    session: Session, user: User, changes: list[PreferencePatch], expected: int,
    *, source: str, source_text: str | None = None,
) -> tuple[int, Preferences]:
    session.get(User, user.id, with_for_update=True)
    version, current = preference_at(session, user)
    if version != expected:
        raise VersionConflict("Preferences changed. Review a fresh proposal.")
    updated = apply_changes(current, changes)
    if updated == current:
        return version, current
    previous = session.scalar(select(PreferenceEvent.id).where(
        PreferenceEvent.user_id == user.id, PreferenceEvent.version == version
    ))
    session.add(PreferenceEvent(
        user_id=user.id, version=version + 1, patch=[patch.model_dump(mode="json") for patch in changes],
        state=updated.model_dump(mode="json"), supersedes=previous, source=source, source_text=source_text,
    ))
    session.flush()
    return version + 1, updated


def seed_candidate(session: Session, user: User) -> None:
    write_profile(session, user, Profile.model_validate(load_json("demo_profile.json")), 0)
    initial = Preferences.model_validate(load_json("demo_preferences.json"))
    changes = [PreferencePatch.model_validate({"field": key, "operation": "set", "value": value})
               for key, value in initial.model_dump(exclude_defaults=True).items()]
    write_preferences(session, user, changes, 0, source="demo setup")


def event_view(row: PreferenceEvent) -> dict[str, Any]:
    return dict(id=row.id, version=row.version, patch=row.patch, state=row.state, supersedes=row.supersedes,
                source=row.source, source_text=row.source_text, created_at=row.created_at)
