"""Update nested resume profile JSON bullet text by bullet id."""

from __future__ import annotations

from typing import Any


def patch_bullet_by_id(profile_data: dict[str, Any], bullet_id: str, new_text: str) -> bool:
    changed = False
    for exp in profile_data.get("experience") or []:
        if not isinstance(exp, dict):
            continue
        for b in exp.get("bullets") or []:
            if isinstance(b, dict) and str(b.get("id")) == str(bullet_id):
                b["text"] = new_text
                changed = True
    for pj in profile_data.get("projects") or []:
        if not isinstance(pj, dict):
            continue
        for b in pj.get("bullets") or []:
            if isinstance(b, dict) and str(b.get("id")) == str(bullet_id):
                b["text"] = new_text
                changed = True
    return changed


def bump_skills(profile_data: dict[str, Any], skills: list[str]) -> None:
    cur = set(profile_data.get("skills") or [])
    for s in skills:
        cur.add(s.strip())
    profile_data["skills"] = sorted(cur)
