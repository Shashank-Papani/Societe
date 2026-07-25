from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailMessage:
    to_address: str
    subject: str
    text_body: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...
