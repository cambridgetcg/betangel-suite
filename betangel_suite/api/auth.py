"""Bootstrap codes, session tokens and the controller tab (DESIGN.md 9.2 items 1 and 8).

- A bootstrap code is secrets.token_urlsafe(16), valid for CODE_TTL_S seconds and invalidated on first use.
  open, ssh-session, a takeover (control attach or attach_viewer), new_code and viewer_code each issue one. A
  code leaves the engine only in open's /usr/bin/open argv at startup, on the stdout of open --print-url or
  ssh-session (Yu's), or through the control socket to a same-uid peer; nothing here prints or logs one.
- POST /api/v1/bootstrap exchanges a code for a session token, secrets.token_urlsafe(32). Tokens live in
  this object only (never on disk) and are compared with hmac.compare_digest.
- Both values go through upstream secret.register (passed in as `register`), so any upstream journal or
  receipt write that contains one is refused.
- A takeover (issue_code(takeover=True)) invalidates every earlier code and token.
- One controller tab (9.2 item 8): the token that bootstrapped while no controller tab was watching (no live
  stream) becomes the controller; any other token is read-only until it claims control (claim), which makes
  the previous controller read-only in turn.

Standard library only.
"""

import hmac
import re
import secrets
import threading
import time

CODE_BYTES = 16
TOKEN_BYTES = 32
CODE_TTL_S = 120
MAX_CODES = 8
MAX_TOKENS = 8
MAX_STREAMS_PER_TOKEN = 2
CODE_RE = re.compile(r"[A-Za-z0-9_-]{22}")
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")


def _same(a, b):
    """Constant-time equality of two texts (bytes, so non-ASCII input cannot raise)."""
    return hmac.compare_digest(a.encode("utf-8", "surrogateescape"), b.encode("utf-8", "surrogateescape"))


class Auth:

    def __init__(self, *, register, clock=time.monotonic):
        self._register = register
        self._clock = clock
        self._lock = threading.Lock()
        self._codes = {}            # code -> expiry (clock seconds); insertion order is issue order
        self._tokens = {}           # token -> issue order number; insertion order is issue order
        self._streams = {}          # token -> live stream count
        self._controller = None
        self._issued = 0

    def issue_code(self, *, takeover=False):
        """A fresh single-use code; with takeover, every earlier code and token is invalidated first."""
        code = secrets.token_urlsafe(CODE_BYTES)
        self._register(code)
        now = self._clock()
        with self._lock:
            if takeover:
                self._codes.clear()
                self._tokens.clear()
                self._streams.clear()
                self._controller = None
            for old in [c for c, expiry in self._codes.items() if expiry <= now]:
                del self._codes[old]
            while len(self._codes) >= MAX_CODES:
                del self._codes[next(iter(self._codes))]
            self._codes[code] = now + CODE_TTL_S
        return code

    def exchange(self, presented):
        """The new session token for a valid, unexpired, unused code (which is then dead); else None."""
        if not isinstance(presented, str) or not CODE_RE.fullmatch(presented):
            return None
        now = self._clock()
        with self._lock:
            match = None
            for code, expiry in self._codes.items():
                if _same(code, presented) and expiry > now:
                    match = code
            if match is None:
                return None
            del self._codes[match]
            token = secrets.token_urlsafe(TOKEN_BYTES)
            self._register(token)
            while len(self._tokens) >= MAX_TOKENS:
                oldest = next(iter(self._tokens))
                del self._tokens[oldest]
                self._streams.pop(oldest, None)
                if self._controller == oldest:
                    self._controller = None
            self._issued += 1
            self._tokens[token] = self._issued
            if self._controller is None or not self._streams.get(self._controller):
                self._controller = token
            return token

    def check(self, header):
        """The session token named by an Authorization header value ("Bearer <token>"), or None."""
        if not isinstance(header, str) or not header.startswith("Bearer "):
            return None
        presented = header[len("Bearer "):]
        if not TOKEN_RE.fullmatch(presented):
            return None
        with self._lock:
            found = None
            for token in self._tokens:
                if _same(token, presented):
                    found = token
            return found

    def valid(self, token):
        with self._lock:
            return token in self._tokens

    def claim(self, token):
        """claim_control: token becomes the controller (the previous one is read-only from now on); False if invalid."""
        with self._lock:
            if token not in self._tokens:
                return False
            self._controller = token
            return True

    def is_controller(self, token):
        with self._lock:
            return token is not None and token == self._controller and token in self._tokens

    def stream_started(self, token):
        """True when a new stream of token is accepted (a valid token below MAX_STREAMS_PER_TOKEN streams)."""
        with self._lock:
            if token not in self._tokens:
                return False
            count = self._streams.get(token, 0)
            if count >= MAX_STREAMS_PER_TOKEN:
                return False
            self._streams[token] = count + 1
            return True

    def stream_ended(self, token):
        with self._lock:
            count = self._streams.get(token, 0)
            if count <= 1:
                self._streams.pop(token, None)
            else:
                self._streams[token] = count - 1

    def controller_watching(self):
        """True while the controller tab has a live stream (the clock may run only then; section 8.6)."""
        with self._lock:
            return self._controller is not None and self._streams.get(self._controller, 0) > 0

    def streams_open(self):
        """True while any tab's stream is connected (somebody is watching; api/lifetime.py)."""
        with self._lock:
            return any(count > 0 for count in self._streams.values())

    def counts(self):
        """(live codes, tokens, live streams): counts only, for diagnostics and tests."""
        now = self._clock()
        with self._lock:
            return (sum(1 for expiry in self._codes.values() if expiry > now), len(self._tokens),
                    sum(self._streams.values()))
