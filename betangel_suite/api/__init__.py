"""The local API (DESIGN.md section 9): the loopback HTTP server, its closed route table and command enum,
bootstrap codes and session tokens, the NDJSON frame stream, the static UI and the control socket.

    server.py   the ThreadingHTTPServer subclass and request handler (9.1-9.3), and run(): engine startup,
                the single-instance lock, the /usr/bin/open call of `open`, seal(), shutdown
    routes.py   the closed route table, the command and query enums, request schemas, nonces, the App
    auth.py     single-use bootstrap codes, session tokens, the controller tab
    stream.py   the hand-chunked NDJSON stream with heartbeats
    static.py   the UI files, mapped from ui/manifest.json by exact name
    control.py  run/control.sock: attach, new_code, pause and stop, and the ssh-session viewer's commands, for
                same-uid peers; the stop command
    lifetime.py pause unless watched (Phase 0c): viewer generations, the grace and the maximum session time
    sshsession.py  bin/suite ssh-session (Phase 0c): the viewer's terminal, in the engine's process or attached

Importing betangel_suite.api imports nothing else; cli.py imports these modules only inside the serve,
open, ssh-session and stop handlers (and test, for the engine lock), so the other commands never load socket
or http.
"""
