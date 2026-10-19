"""Session lifetime: pause unless watched (DESIGN.md 8.6 item 2, I-19), kept by every engine process.

One Lifetime per engine. It knows two things the clock alone does not: who took the session over last (a
terminal viewer, that is ssh-session, or a page opened by open), and how long the session has run.

- A takeover (open, ssh-session, or a control attach) starts a new viewer, named by a fresh viewer token:
  secrets.token_hex(VIEWER_TOKEN_BYTES), 128 random bits, told only to the caller that took the session over
  (ssh-session keeps it in memory and never prints it). Only the newest viewer's token may ask for codes, report
  heartbeats or report itself away; an older one is superseded. Until round 5 the viewer was named by a small
  generation number (1, 2, ...), which any process of this user could guess and then mint codes with
  (viewer_code) without being told; a token it was never told it cannot guess (lab-Claude's decision in round 5,
  on round 4b's question). The control socket's new_code still mints codes for any same-uid caller (DESIGN.md
  9.4).
- A terminal viewer reports a heartbeat every 15 s (sshsession.HEARTBEAT_S). It goes away when it reports
  stdin EOF or a failed write (away()), or when no heartbeat arrived for viewer_timeout_s (a viewer that died
  without saying so). The engine pauses then (check() asks for it once), and the session is kept.
- Nobody watching means: the terminal viewer is away and no stream is open (no tab is connected). Once nobody
  has watched for grace_s (config watch_grace_s, default 600), the session ends as "abandoned". A takeover
  within the grace, an open stream, or a late heartbeat keeps it.
- A page opened by open (no terminal) never makes the session abandoned: the lab's own screen is watched by
  Yu at the lab, and its tab's stream already pauses the clock when it drops.
- Every session ends as "max_session" once it has run max_session_s (config, default 14400 = 4 h), watched or
  not.

The clock is injectable (seconds, monotonic), so tests drive grace and maximum time without waiting. Nothing
here prints or logs a code, a session token or a viewer token; it holds only the newest viewer's token, which it
compares in constant time (hmac.compare_digest). Standard library only.
"""

import hmac
import re
import secrets
import threading
import time

VIEWER_TIMEOUT_S = 60.0             # four missed 15 s heartbeats
VIEWER_TOKEN_BYTES = 16             # a viewer token: secrets.token_hex, 32 lowercase hex digits
VIEWER_RE = re.compile(r"[0-9a-f]{%d}" % (2 * VIEWER_TOKEN_BYTES))
ENDS = ("abandoned", "max_session")


def viewer_ok(value):
    """A viewer token's shape, as takeover() makes it: a str of 32 lowercase hex digits (never an int or bytes)."""
    return type(value) is str and bool(VIEWER_RE.fullmatch(value))


class Lifetime:

    def __init__(self, *, grace_s, max_session_s, clock=time.monotonic, viewer_timeout_s=VIEWER_TIMEOUT_S):
        for value in (grace_s, max_session_s, viewer_timeout_s):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
                raise ValueError("lifetime limits must be positive numbers")
        self.grace_s = grace_s
        self.max_session_s = max_session_s
        self.viewer_timeout_s = viewer_timeout_s
        self._clock = clock
        self._lock = threading.Lock()
        self._started = clock()
        self._generation = 0            # takeovers so far (counts only; never a viewer's name)
        self._viewer = None             # the newest viewer's token
        self._terminal = False          # the newest viewer is a terminal (ssh-session)
        self._seen = None               # its last heartbeat (clock seconds)
        self._away = False
        self._unwatched_since = None
        self._ended = None

    # --- viewers ------------------------------------------------------------------------------------

    def takeover(self, *, terminal):
        """A new viewer took the session over; returns its token, fresh from secrets.token_hex. Any grace is
        cancelled, and every earlier viewer's token is superseded."""
        with self._lock:
            self._generation += 1
            self._viewer = secrets.token_hex(VIEWER_TOKEN_BYTES)
            self._terminal = bool(terminal)
            self._seen = self._clock()
            self._away = False
            self._unwatched_since = None
            return self._viewer

    def current(self, viewer):
        """True when viewer is the newest viewer's token and a terminal's (it may ask for a fresh code)."""
        with self._lock:
            return self._is_current(viewer)

    def heartbeat(self, viewer):
        """The terminal viewer is there; False when it has been superseded."""
        with self._lock:
            if not self._is_current(viewer):
                return False
            self._seen = self._clock()
            self._away = False                  # a late heartbeat after a timeout: it is evidently there
            self._unwatched_since = None
            return True

    def away(self, viewer):
        """The terminal viewer saw stdin EOF or a failed write; False when it has been superseded."""
        with self._lock:
            if not self._is_current(viewer):
                return False
            self._away = True
            return True

    def _is_current(self, viewer):
        return (viewer_ok(viewer) and self._viewer is not None and hmac.compare_digest(viewer, self._viewer)
                and self._terminal and self._ended is None)

    # --- the engine's periodic check ----------------------------------------------------------------

    def check(self, streams_open):
        """(end reason or None, pause now): called by the engine's main loop a few times a second.

        streams_open is True while any tab's stream is connected. The pause flag is True once, when a terminal
        viewer is found silent for viewer_timeout_s (an away() report pauses through its caller instead).
        """
        now = self._clock()
        with self._lock:
            if self._ended is not None:
                return self._ended, False
            if now - self._started >= self.max_session_s:
                self._ended = "max_session"
                return self._ended, False
            if not self._terminal:
                return None, False
            pause = False
            if not self._away and now - self._seen >= self.viewer_timeout_s:
                self._away, pause = True, True
            if not self._away or streams_open:
                self._unwatched_since = None
            elif self._unwatched_since is None:
                self._unwatched_since = now
            elif now - self._unwatched_since >= self.grace_s:
                self._ended = "abandoned"
            return self._ended, pause

    def counts(self):
        """Counts and flags only, for diagnostics and tests."""
        now = self._clock()
        with self._lock:
            return {"generation": self._generation, "terminal": self._terminal, "away": self._away,
                    "unwatched": self._unwatched_since is not None, "elapsed_s": int(now - self._started),
                    "ended": self._ended}
