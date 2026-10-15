"""The local API (DESIGN.md section 9): the loopback HTTP server, its closed route table and command enum,
bootstrap codes and session tokens, the NDJSON frame stream, the static UI and the control socket.

    server.py   the ThreadingHTTPServer subclass and request handler (9.1-9.3), and run(): engine startup,
                the single-instance lock, the /usr/bin/open call of `open`, seal(), shutdown
    routes.py   the closed route table, the command and query enums, request schemas, nonces, the App
    auth.py     single-use bootstrap codes, session tokens, the controller tab
    stream.py   the hand-chunked NDJSON stream with heartbeats
    static.py   the UI files, mapped from ui/manifest.json by exact name
    control.py  run/control.sock: attach, new_code, pause and stop for same-uid peers; the stop command

Importing betangel_suite.api imports nothing else; cli.py imports these modules only inside the serve,
open and stop handlers, so the other commands never load socket or http.
"""
