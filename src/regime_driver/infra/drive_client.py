"""DriveClient — the agent-drive abstraction (adaptor seam).

regime-driver's kernel (state machine, watchdog, gates, ledger) drives a
*headless agent* through a small, stable surface: create sessions, send
messages, read replies, abort, list, and consume a push event stream. Today the
only implementation is the opencode server client (``infra/opencode.py``), but
nothing in the kernel should depend on opencode's transport details.

``DriveClient`` is a structural ``typing.Protocol``: any object implementing
this surface (the real ``OpenCodeClient``, the test ``MockClient``, or a future
adapter for another agent) is a valid drive target. The kernel types its
dependencies as ``DriveClient`` so swapping the driven agent is a construction-
site change, not a kernel change.

``Message`` is the transport-neutral message shape (parsed from each agent's
raw reply format by the adapter); it is defined in ``infra/opencode.py`` today
and re-exported here so protocol consumers do not need to import the opencode
module directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .opencode import Message  # re-export: transport-neutral message shape


@runtime_checkable
class DriveClient(Protocol):
    """The agent-drive surface regime-driver's kernel depends on.

    A ``DriveClient`` lets an external orchestrator create isolated sessions on
    a headless agent, drive them node-by-node (send a prompt, wait for the
    assistant's complete reply), inspect/cancel sessions, and observe a push
    event stream for liveness/watchdog signals.
    """

    # -- sessions ------------------------------------------------------------

    def create_session(self, title: str) -> str: ...

    def list_sessions(self) -> list[dict]: ...

    def session_status(self, session_id: str) -> str | None: ...

    def session_status_map(self) -> dict[str, str | None]: ...

    def session_tokens(self, session_id: str) -> tuple[int, int]: ...

    def abort_session(self, session_id: str) -> None: ...

    def delete_session(self, session_id: str) -> None: ...

    # -- messages ------------------------------------------------------------

    def send_message(self, session_id: str, text: str, agent: str) -> None: ...

    def ask_and_get_text(self, session_id: str, prompt: str, agent: str,
                         model: str | None = None) -> str: ...

    def read_messages(self, session_id: str) -> list[Message]: ...

    # -- events (push) -------------------------------------------------------

    def event_stream(self, reconnect: bool = True, max_retries: int | None = None,
                     backoff_sec: float = 2.0): ...

    # -- health --------------------------------------------------------------

    def health(self) -> bool: ...

    def health_info(self) -> dict: ...

    def check_version(self, supported: str | None = None) -> tuple[bool, str | None]: ...
