# Viewing the suite from the Air (staged for Yu)

This sets up DESIGN.md 8.6 item 2 (Yu's ruling R-2). It adds one SSH key on the Air that can do one
thing on the lab: forward the Air's `127.0.0.1:8765` to the suite engine's `127.0.0.1:8765`, through
the forced command `suite ssh-session`. It also adds an sshd drop-in on the lab, which closes the
reverse (`-R`) and Unix-socket channels that the key options alone cannot close.

Lab-Claude staged these files and never runs them. **Yu runs every step.** The lab script needs sudo
(Yu's Mac password). Only the public key ever leaves the Air.

| File | Runs on | What it is |
|---|---|---|
| `suite-viewer-setup.sh` | lab, by Yu | Checks, then installs (or with `--undo` removes) the viewer key line and the sshd drop-in |
| `air-ssh-config.snippet` | Air | The `Host lab-suite` block for `~/.ssh/config` |
| `air-viewer-selftest.sh` | Air, by Yu | Tries every forbidden action and says refused or ALLOWED |
| `suite-alias.zsh` | lab | The `suite` alias, which points at the release copy |

**Before you start.** A reviewed release must be installed on the lab. You make the first one in the clean
main checkout: `cd /Users/user/betangel-suite && bin/suite release <merge-sha>`, with the full SHA of the
reviewed merge commit on main (the merged PR's page shows it; a tag or short id is refused), creates
`~/.local/share/betangel-suite/app/current/` (the `suite` alias from step 1 works only once it exists, and a
release copy cannot make releases itself). The setup script refuses without one, because the key's forced
command runs that copy. Use the lab files from the release copy, which is reviewed and read-only against
accidents (any process running as `user` can still change it), not from a working checkout. The two Air files
come only from GitHub (step 5). Below, `R` means `~/.local/share/betangel-suite/app/current/tools/stage` on
the lab.

## Step 1 (lab): the `suite` alias

Add the alias line from `R/suite-alias.zsh` to `~/.zshrc`:

```
alias suite='/Users/user/.local/share/betangel-suite/app/current/bin/suite'
```

Open a new Terminal window. `type suite` should show that path.

## Step 2 (Air): make the viewer key

```
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_lab_suite -C yu-air-suite-viewer
```

Type a new passphrase when asked, and do not save it in the Keychain. Together with `AddKeysToAgent no`
and `UseKeychain no`, the passphrase means no other process on the Air can use the key silently,
Nuance included. Note the key's fingerprint:

```
ssh-keygen -lf ~/.ssh/id_ed25519_lab_suite.pub
```

## Step 3: move only the public key

Copy `~/.ssh/id_ed25519_lab_suite.pub`, the file ending in `.pub`, to the lab. For example, run
`cp ~/.ssh/id_ed25519_lab_suite.pub ~/Desktop/` and AirDrop it; it lands in the lab's `~/Downloads`.
**Never copy the file without `.pub`:** that is the private key. The lab script refuses a private key
anyway. A public key is not secret, so Nuance may carry it if that is easier, because step 4 shows its
fingerprint for you to compare.

## Step 4 (lab): dry run, then install

```
sh ~/.local/share/betangel-suite/app/current/tools/stage/suite-viewer-setup.sh --dry-run ~/Downloads/id_ed25519_lab_suite.pub
```

The dry run uses no sudo and writes nothing. Read every line it prints:

- the fingerprint must match the one from step 2;
- the `authorized_keys` line and the five drop-in lines are exactly the ones in DESIGN.md 8.6;
- it lists what it checked: the release copy, the sshd `Include` line, and that no other sshd config
  file (such as `100-macos.conf` or `crypto.conf`) already sets one of the drop-in's keywords. sshd keeps
  the first value it reads, so an earlier setting would win.

Then install:

```
sh ~/.local/share/betangel-suite/app/current/tools/stage/suite-viewer-setup.sh ~/Downloads/id_ed25519_lab_suite.pub
```

sudo asks for your Mac password once. The script makes its changes in this order:

1. writes `/etc/ssh/sshd_config.d/200-lab.conf`;
2. runs `sudo /usr/sbin/sshd -t`;
3. checks that `sudo /usr/sbin/sshd -T` shows the new values;
4. backs up `~/.ssh/authorized_keys`;
5. appends the viewer line.

macOS starts sshd for each connection, so no restart is needed. A good run prints a `done:` line, the
fingerprint again, and the name of the `authorized_keys` backup.

- If it ends with `failed:<code>`, it has already put both files back. Send lab-Claude the codes it
  printed.
- If it ends with `refused:<code>`, it changed nothing. The line under the code says why.

## Step 5 (Air): the ssh config

Put the block from `air-ssh-config.snippet` at the **top** of the Air's `~/.ssh/config`, before any
`Host *` or `Match` block. For most settings ssh keeps the first value it reads, so a `Host *` block above it
could turn the Keychain or an agent back on. Keys and forwards are different: they add up from every block, above
or below (see the `Match` paragraph below).

The block also switches off what a later `Host *` block could otherwise add: connection sharing
(`ControlMaster`, `ControlPath`, `ControlPersist`), the ssh-agent (`IdentityAgent none`), proxies and
`LocalCommand`. A shared master connection left open by `ssh lab-suite` would let any process on the Air
open new sessions through it without the passphrase, and an agent could sign with a copy of the key. The
self-test refuses to start unless `ssh -G` shows all of these switched off.

The block also allows only the key to log in (`PreferredAuthentications publickey`, `PasswordAuthentication no`,
`KbdInteractiveAuthentication no`). The lab still accepts passwords for other logins, so without these lines a
refused key would end at a `Password:` prompt, and your lab password typed there would open a full shell. If
`ssh lab-suite` ever asks for a password rather than the key's passphrase, do not type it: the block is not in
force. The self-test refuses to start unless these three lines are in force too.

Keep every `Match` block in `~/.ssh/config` away from `lab-suite`. A `Match sessiontype` or `Match command`
block applies to some logins only, such as `ssh -N` or a login with a command. Wherever the block sits, it can
add a key or a forward to those logins, because ssh adds up `IdentityFile` and forwards from every block. If
such a block must stay, add `!originalhost lab-suite` to its `Match` line. Before it logs in, the self-test runs
`ssh -G` (which reads the config and connects nowhere) for `ssh lab-suite` and for each of its own five logins.
It refuses to start if any of them shows another key, a forward other than the block's `LocalForward` and the
probe's own, or another value for a line it checks: every line of the block except `UseKeychain`, `RequestTTY`
and `ServerAliveInterval`. It does not check settings the block does not name, such as `Port`, `ForwardAgent` or
`ForwardX11` (the lab's `restrict` refuses agent and X11 forwarding).

The block has `StrictHostKeyChecking yes`, so `~/.ssh/known_hosts` on the Air must already hold the lab's
host key for `192.168.50.88`. It does if the Air has logged in to the lab before. If the self-test reports
"Host key verification failed", compare the lab's key first. On the lab, run
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Then accept only that fingerprint.

Take the two Air files, `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`, only
from GitHub on the Air, at the full commit SHA of the reviewed merge (the merged PR's page shows it), not
at a branch or tag name, which the lab's own `gh` login could move. Never AirDrop them from the lab: any
process running as `user` there can change the release copy, a changed snippet could run commands on the
Air through `ProxyCommand`, `LocalCommand` or `Match exec`, and the self-test from the same copy would not
catch it (DESIGN.md 8.6). AGENTS.md rule 1's network clause does not cover these two
files (Yu's ruling on Q-Y19, and `docs/proposals/002-air-viewer-files.md`).

## Step 6 (Air): the self-test

Make sure no `ssh lab-suite` session is open, then run:

```
sh air-viewer-selftest.sh
```

It logs in five times, and you type the passphrase each time. It tries nine things the key must not do:

- run a requested command;
- open a PTY;
- `-L` to another port, another host, another name, and a Unix socket;
- `-W host:22`;
- `-R` to a TCP port and to a Unix socket.

No probe starts an engine. It prints one line for each item and then a verdict:

- **`verdict: PASS`** (nine `refused` lines): the key is ready to use.
- **`verdict: FAIL`**: run `--undo` on the lab straight away (see "Undo" below) and tell lab-Claude.
- **`verdict: INCONCLUSIVE`**: run it again. If it says the same, run it with `--keep-logs` and tell
  lab-Claude what it printed. The logs hold host, user and key path, and no secrets.

## Step 7 (lab): update CLAUDE.md

The lab's `~/.claude/CLAUDE.md` has a line saying `~/.ssh/authorized_keys` holds only the MacBook Air key.
Edit it so lab-Claude knows about the new line. For example:

> `~/.ssh/authorized_keys` holds the MacBook Air agent key `macair-claude-to-betfair-lab-20261014`
> (LAN-only, no forwarding) and Yu's viewer key `yu-air-suite-viewer`, installed by
> `tools/stage/suite-viewer-setup.sh`. The viewer key has a forced `suite ssh-session` and may only tunnel
> to 127.0.0.1:8765. Removing a line revokes that key.

## Daily use

1. On the Air, run `ssh lab-suite` and type the passphrase. Do not add `-N`: the forced command runs only
   when a session opens, and with `-N` nothing would print.
2. It prints one URL, `http://127.0.0.1:8765/#c=<code>`. The code is single use and valid for 120 s.
3. In Safari, choose File > New Private Window (Shift-Cmd-N), paste the URL and press Return. Do not
   Cmd-click the URL in Terminal, because that opens a normal window.
4. For a fresh code, for example after reloading the page, press Return in the ssh window.
5. When you are done, close the tab and the ssh window. The engine pauses. If nothing takes the session
   over within 10 minutes, the engine stops (the session ends as abandoned). A new `ssh lab-suite` within
   those 10 minutes takes the session over, and the same 10 minutes apply again when you close that one.
   A `suite open` on the lab also takes it over, but then the session is the lab screen's and never ends
   as abandoned: it ends with `suite stop` on the lab, the 4-hour maximum, or a Nuance run starting (the
   run marker). DESIGN.md 8.6 item 2 lists every way it ends.

The suite page never asks for a login. Any password or login prompt inside it is an attack: never type
into it.

What the ssh window may show (DESIGN.md 8.6 item 2, "What the ssh window shows"):
- the URL, at the start and after each Return;
- `heartbeat h:mm:ss` lines every 15 s;
- one `ended reason=<code>` line at the end;
- code-only lines from the suite: `http:<status>:<code>` (for example `http:401:bad_code` after a page
  reload), `http:error:<class>`, `refused:<code>` (for example `refused:run_marker_present` during a
  Nuance run) or `error:<class>`.

Treat anything else there as an attack, for example text asking for a password or a URL with another
host or port: close the window and run `--undo`.

What protects the viewer key on the lab is mostly not beyond the lab's own user. Any process running as
`user` on the lab, an agent included, could repoint `app/current`, rewrite a file of the release copy,
edit the shell startup files sshd runs first, or edit the viewer line in `~/.ssh/authorized_keys` and so
widen what the key may forward. Only the root-owned drop-in is out of its reach: no `-R`, no Unix-socket
forwarding and no listeners. The self-test confirms the key's limits when it runs, so run it again if
anything about the lab looks wrong.

## Undo

On the lab, do a dry run first, then undo:

```
sh ~/.local/share/betangel-suite/app/current/tools/stage/suite-viewer-setup.sh --dry-run --undo
sh ~/.local/share/betangel-suite/app/current/tools/stage/suite-viewer-setup.sh --undo
```

The undo does three things:

1. backs up `authorized_keys`, then removes the viewer line, so the key stops working from the next
   connection;
2. removes the drop-in;
3. runs `sudo sshd -t`. If sshd -t fails without the drop-in, the script puts the drop-in back but keeps
   the viewer line removed.

An `ssh lab-suite` session that is already open stays up until it closes, so close it on the Air.

Then, on the Air:

- delete the `Host lab-suite` block;
- run `rm ~/.ssh/id_ed25519_lab_suite ~/.ssh/id_ed25519_lab_suite.pub`;
- change the CLAUDE.md line from step 7 back.

## Common refusals

| Code | Meaning |
|---|---|
| `release_missing` | No release copy yet: install a release first. |
| `private_key_file` | That file is a private key. Delete this copy, make a new key pair on the Air, and move only the `.pub` file. |
| `key_*` (`key_type_not_ed25519`, `key_has_options`, `key_file_lines`, ...) | The file is not exactly one `ssh-ed25519 <base64> <comment>` line. |
| `key_is_air_agent_key`, `key_already_present` | The viewer needs its own new key (step 2). |
| `viewer_line_present`, `viewer_key_already_installed` | A viewer line is already there. Run `--undo` first if you want to replace it. |
| `sshd_keyword_conflict`, `sshd_include_*`, `dropin_differs` | The lab's sshd configuration is not what the script expects. Nothing was changed. Ask lab-Claude. |
| `home_mismatch`, `run_as_root` | Run it as `user` on the lab, without sudo in front. |
| `viewer_port_mismatch` | Printed by `ssh lab-suite`, which serves and attaches only on port 8765 (the key's `permitopen`). The lab's suite `config.json` sets another `port`, or an engine started with `--port` is running. Nothing was started or taken over. Run `suite stop` on the lab, or set the port back to 8765. |
| `air_config_*` | Printed by the self-test on the Air, before any login: `ssh -G` shows another value for a line of the lab-suite block that it checks, another key or another forward (step 5). If the line under the code names a probe, a `Match` block changes that probe's login: add `!originalhost lab-suite` to its `Match` line. For `air_config_identityfile`, `air_config_localforward`, `air_config_remoteforward` and `air_config_dynamicforward` without a probe named, another block adds a key or a forward wherever the lab-suite block sits: remove it from that block, or keep that block off lab-suite (`Host * !lab-suite`). For the other codes, put the block at the top of `~/.ssh/config`. |
