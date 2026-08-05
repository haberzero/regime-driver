"""Role registry (pure domain): user-registered role instances.

Per v4, developer/reviewer are NOT kernel concepts — they are user-specialized
role instances. The kernel only knows role ids. A Role bundles the opencode
agent name, the lifecycle policy, skill resources, and work directory.

This is pure domain: no I/O. Registration is done by the user/application.
"""

from __future__ import annotations

from dataclasses import dataclass

from .policy import RolePolicy, developer_policy, reviewer_policy


@dataclass
class Role:
    """One user-registered role instance."""

    id: str
    agent: str
    policy: RolePolicy
    skills_dir: str | None = None
    work_dir: str | None = None
    description: str = ""


class RoleRegistry:
    """Holds registered roles keyed by id."""

    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}

    def register(self, role: Role) -> "RoleRegistry":
        self._roles[role.id] = role
        return self

    def get(self, role_id: str) -> Role:
        try:
            return self._roles[role_id]
        except KeyError:
            raise KeyError(f"role '{role_id}' not registered") from None

    def has(self, role_id: str) -> bool:
        return role_id in self._roles

    def ids(self) -> list[str]:
        return list(self._roles)


def default_roles() -> RoleRegistry:
    """Default registry with a developer and a reviewer (user-specialized)."""
    return RoleRegistry() \
        .register(Role(id="developer", agent="developer", policy=developer_policy(),
                       description="Performs work; permissive capacity thresholds")) \
        .register(Role(id="reviewer", agent="reviewer", policy=reviewer_policy(),
                       description="Judges; stricter capacity thresholds"))