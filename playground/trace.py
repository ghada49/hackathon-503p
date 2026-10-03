"""Flushed JSONL events with credential and hidden-reasoning redaction."""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path

_PRIVATE = re.compile(r'authorization|api.?key|credential|password|secret|reasoning|chain.?of.?thought|access.?token', re.I)


class TraceLogger:
    def __init__(self, path: str | Path, *, clock=time.monotonic, started: float | None = None):
        self.clock = clock
        self.started = clock() if started is None else started
        self._secret = os.environ.get('OPENROUTER_API_KEY', '')
        self._file = Path(path).open('w', encoding='utf-8')

    def sanitize(self, value):
        if isinstance(value, dict):
            return {str(k): '[REDACTED]' if _PRIVATE.search(str(k)) else self.sanitize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.sanitize(v) for v in value]
        if isinstance(value, str):
            if self._secret:
                value = value.replace(self._secret, '[REDACTED]')
            return re.sub(r'Bearer\s+\S+', '[REDACTED]', value, flags=re.I)
        return value

    def log(self, stage: str, action: str, result: dict | None = None) -> None:
        event = self.sanitize(dict(t=round(self.clock() - self.started, 6), stage=stage, action=action, result=result or {}))
        self._file.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
        self.flush()

    def flush(self) -> None:
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self.flush()
            self._file.close()
