import datetime as dt
from dataclasses import dataclass


@dataclass
class IncomingMessage:
    text: str
    sender: str
    timestamp: dt.datetime
    is_from_me: bool
