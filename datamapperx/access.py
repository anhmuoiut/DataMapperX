"""Whether this copy of the program may still be used.

The owner controls it from one file in the repository, ``status.json``::

    {"disabled": false, "message": ""}

Set ``disabled`` to ``true`` (and write a ``message`` if you like) and every copy stops the next time it looks at
the file, which is when it starts and then once an hour. Nothing here knows about tkinter or the network: the window
hands in the answer it got (or the failure) and gets back what to show.

Three rules keep this fair and hard to dodge:

* A copy that has been told to stop stays stopped, even with no network, until a check says it may run again.
* A copy that cannot read the file may keep running for ``OFFLINE_GRACE_DAYS`` after the last time it could (the first
  start counts as such a time), so a trip or an outage does not lock anyone out. After that it must be able to check.
* Only a clear ``"disabled": true`` stops a copy straight away. A missing file, a network error or a typo is only a
  failed check and counts against the grace period, so a slip in the file cannot switch everyone off at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import APP_TITLE
from .settings import Settings
from .updater import Status

OFFLINE_GRACE_DAYS = 14
RECHECK_MS = 60 * 60 * 1000  # while the window stays open, look again every hour
_DAY = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class Block:
    """The program must not be used. ``kind`` is ``"disabled"`` (the owner said so) or ``"unverified"``."""

    kind: str
    title: str
    heading: str
    message: str


def _disabled(message: str) -> Block:
    return Block(
        kind="disabled",
        title=f"{APP_TITLE} is switched off",
        heading="This program has been switched off",
        message=message or "Please contact the person who gave you this program.",
    )


def _unverified(days: int) -> Block:
    return Block(
        kind="unverified",
        title=f"{APP_TITLE} needs a connection",
        heading="This copy could not be checked",
        message=(
            f"{APP_TITLE} has to confirm now and then that it may still be used, and it has not managed to for "
            f"{days} days. Connect to the network (or the VPN), then choose Check again."
        ),
    )


def begin(settings: Settings, now: float) -> None:
    """On the very first start there is no earlier check, so the offline allowance starts now."""
    if settings.verified_at <= 0:
        settings.verified_at = now


def current_block(settings: Settings, now: float) -> Block | None:
    """The verdict from what is remembered alone. It is also the answer when a check could not be made."""
    if settings.deactivated:
        return _disabled(settings.deactivated_message)
    if settings.verified_at > 0:
        idle = now - settings.verified_at
        if idle > OFFLINE_GRACE_DAYS * _DAY:
            return _unverified(int(idle // _DAY))
    return None


def record_status(settings: Settings, status: Status, now: float) -> Block | None:
    """Remember what ``status.json`` said and return the block, if it says to stop."""
    settings.verified_at = now
    settings.deactivated = status.disabled
    settings.deactivated_message = status.message if status.disabled else ""
    return current_block(settings, now)
