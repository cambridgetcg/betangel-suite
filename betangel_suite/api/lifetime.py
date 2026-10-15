"""Session lifetime: pause unless watched (DESIGN.md 8.6 item 2, I-19), kept by every engine process.

One Lifetime per engine. It knows two things the clock alone does not: who took the session over last (a
terminal viewer, that is ssh-session, or a page opened by open), and how long the session has run.

- A takeover (open, ssh-session, or a control attach) starts a new viewer generation. Only the newest
  generation may ask for codes, report heartbeats or report itself away; an older one is superseded.
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
here prints, logs or holds a code or a token. Standard library only.
"""

import threading
import time

VIEWER_TIMEOUT_S = 60.0             # four missed 15 s heartbeats
ENDS = ("abandoned", "max_session")


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
        self._generation = 0
        self._terminal = False          # the newest viewer is a terminal (ssh-session)
        self._seen = None               # its last heartbeat (clock seconds)
        self._away = False
        self._unwatched_since = None
        self._ended = None

    # --- viewers ------------------------------------------------------------------------------------

    def takeover(self, *, terminal):
        """A new viewer took the session over; returns its generation (1, 2, ...). Any grace is cancelled."""
        with self._lock:
            self._generation += 1
            self._terminal = bool(terminal)
            self._seen = self._clock()
            self._away = False
            self._unwatched_since = None
            return self._generation

    def current(self, generation):
        """True when generation is the newest viewer and a terminal (it may ask for a fresh code)."""
        with self._lock:
            return self._is_current(generation)

    def heartbeat(self, generation):
        """The terminal viewer is there; False when it has been superseded."""
        with self._lock:
            if not self._is_current(generation):
                return False
            self._seen = self._clock()
            self._away = False                  # a late heartbeat after a timeout: it is evidently there
            self._unwatched_since = None
            return True

    def away(self, generation):
        """The terminal viewer saw stdin EOF or a failed write; False when it has been superseded."""
        with self._lock:
            if not self._is_current(generation):
                return False
            self._away = True
            return True

    def _is_current(self, generation):
        return (type(generation) is int and generation > 0 and generation == self._generation
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
