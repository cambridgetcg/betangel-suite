"""GET /api/v1/stream: hand-chunked NDJSON (DESIGN.md 6.5, 8.5; the shared frame interface (2)).

One JSON object per line, each line one HTTP/1.1 chunk, Content-Type application/x-ndjson:

    {"t": "frame", "seq": n, "clock": {...}, "market": {...}, "runners": [...]}    the engine's frames
    {"t": "hb", "seq": n, "paused": bool}       when no line went out for HEARTBEAT_S (paused or idle)
    {"t": "end", "seq": n, "reason": str}       last line: stopped, run_marker, engine_failed, abandoned,
                                                max_session (api/lifetime.py) or superseded

seq in hb and end is the seq of the last frame sent on this stream (0 before the first). A slow reader
skips frames (each frame is the whole state), never lines out of order. The stream ends when the engine
ends, when the tab's token is invalidated (a takeover: superseded), or when the client goes away, which
is noticed within POLL_S; the controller's last stream ending pauses the clock (section 8.6).
Standard library only.
"""

import json
import select
import time

HEARTBEAT_S = 1.0
POLL_S = 0.25


def line(obj):
    return json.dumps(obj, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"


def heartbeat(seq, paused):
    return line({"t": "hb", "seq": seq, "paused": bool(paused)})


def end(seq, reason):
    return line({"t": "end", "seq": seq, "reason": reason})


def chunk(data):
    return b"%x\r\n%s\r\n" % (len(data), data)


def client_gone(connection):
    """True when the peer has closed, or sent anything more: a stream request takes no further input."""
    try:
        readable, _, _ = select.select([connection], [], [], 0)
    except (OSError, ValueError):
        return True
    return bool(readable)


def serve(handler, app, token):
    """Write the stream for token on handler's connection until it ends; the caller has checked the request."""
    engine = app.engine
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson")
    handler.send_header("Transfer-Encoding", "chunked")
    handler.end_headers()
    handler.close_connection = True
    write = handler.wfile.write
    last_seq, paused = 0, True
    last_write = time.monotonic() - HEARTBEAT_S         # idle at the start: the first heartbeat comes at once
    try:
        while True:
            if not app.auth.valid(token):
                write(chunk(end(last_seq, "superseded")))
                break
            published, ended = engine.wait(last_seq, POLL_S)
            if client_gone(handler.connection):
                return
            if published is not None:
                write(chunk(published.line))
                last_seq, paused = published.seq, published.frame["clock"]["paused"]
                last_write = time.monotonic()
                continue
            if ended is not None:
                write(chunk(end(last_seq, ended)))
                break
            if time.monotonic() - last_write >= HEARTBEAT_S:
                write(chunk(heartbeat(last_seq, paused)))
                last_write = time.monotonic()
        write(b"0\r\n\r\n")
    except (OSError, ValueError):
        return                                  # the client went away mid-write: nothing to report
