# Proposal 002: Air viewer files

| | |
|---|---|
| Status | Draft for review by Nuance and Astra. Not approved. After both reviews, Yu will be asked to approve the reviewed proposal in writing (rule 10). |
| Date | 2026-10-16 |
| Author | lab-Claude (Claude Code session 03026dfa on the lab MacBook Pro) |
| Reviewers | Nuance (the rule 1 wording; Q-N15), Astra (the two files, their tests, and PR #5 finding 1) |
| Approver | Yu |
| Base | Branch `phase0/viewing` (PR #5) at d9b129e, plus the commit that adds this file. The rule text comes from 0c1335b, e9b1646 and beeb1f4. The self-test changes for Astra's two code questions are a53856a and b1d5082 (section 7). |
| Process | Suite AGENTS.md rule 10; DESIGN.md section 14 (steps 3, 6 and 7 do not apply; see section 9) |
| Request | Yu, 2026-10-16, asked by lab-Claude whether a rule 10 proposal file is also wanted for Q-Y19 option D, answered: "yes to formal proposal". |

**Words.** Yu's words are quoted exactly, with their dates. Nuance's words are quoted as Nuance's: they are context, not Yu's. Anything else is lab-Claude's, unless it says otherwise.

---

## 1. Summary

- **What changes.** AGENTS.md rule 1 and DESIGN.md 3.9 rule 1 gain one sub-bullet, with two points under it. It says that rule 1's network clause does not cover two files: `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`. Both serve the Air end of the R-2 viewer tunnel. Nothing else in rule 1 changes.
- **Why.** DESIGN.md 8.6 item 2 has lab-Claude stage these two files for Yu to use on the Air. Rule 1 bars network code in this repo. The Codex review bot and Astra flagged the conflict on PR #5 (section 3).
- **Where it stands.** The text is on `phase0/viewing` (PR #5). PR #5 is not merged. Its base branch, `phase0/http` (PR #4), still has rule 1 without the sub-bullet.
- **What is asked.** Review by Nuance and Astra, then Yu's written approval of the reviewed proposal (section 10). Lab-Claude does not merge PR #5 before that approval (section 9).
- **Not touched.** The lab-side files of R-2 (`suite-viewer-setup.sh`, `suite-alias.zsh`), the viewer key line and the sshd drop-in. No Betfair, credential or live code.

## 2. Yu's words, and the readings

### 2.1 Yu's words

| Date | Asked | Yu's words |
|---|---|---|
| 2026-10-15 | The Phase 0 packet: R-1..R-7 and Q-Y8 (DESIGN.md 2.2.1) | "Lets go with what you recommended for all." |
| 2026-10-16 | Q-Y19, options A-D (DESIGN.md 15.1) | "Go for D" |
| 2026-10-16 | Lab-Claude asked whether a rule 10 proposal file is also wanted for D | "yes to formal proposal" |

The 2026-10-15 answer approved R-2, among others (DESIGN.md 2.2.1).

### 2.2 What option D says

Lab-Claude wrote options A-D. Option D's text in Q-Y19 (DESIGN.md 15.1):

> **(D)** you record that the R-2 approval already covered the section 8.6 Air files, and rule 1's network clause is reworded to exclude them: a clarification rather than a widening, because the Air-side sentence covers only later code and the draft you approved already had lab-Claude stage both files (section 8.6), though the recorded R-2 ruling names only the viewer-key script and the drop-in. It still rewords a binding rule, so it may need the same proposal process as C.

The reasons in that text are lab-Claude's, not Yu's. Yu's words were "Go for D". DESIGN.md 2.2.1 records the ruling and keeps Yu's words apart from lab-Claude's reading.

### 2.3 Lab-Claude's reading

- Lab-Claude read D, as its text says, as a clarification of R-2 rather than a widening.
- Draft 0.2 (d48f352) is the draft whose R-2 recommendation Yu approved. Its section 8.6 already said: "Lab-Claude stages `tools/stage/suite-viewer-setup.sh` (lab side) and the Air `~/.ssh/config` snippet, and never runs either", and "Lab-Claude stages an Air-side self-test, which Yu or Nuance runs right after installing the key". The recorded R-2 ruling names only the viewer-key script and the drop-in.
- D's text also said the reword "may need the same proposal process as C". Yu has now asked for a formal proposal. This is it.
- This proposal does not decide whether "Go for D" was itself the rule 10 approval. It takes the reworded rule through rule 10's order as written: proposal, review by Nuance and Astra, then Yu's written approval.

### 2.4 Nuance's first view

Nuance wrote to lab-Claude through the mailbox on 2026-10-16 (note 20261016T134105Z, item 5), before this file existed. These are Nuance's words, not Yu's:

- "The rewording that names exactly the two R-2 files as rule 1's single Air-side exception matches Yu's "Go for D", as long as nothing else widens."
- "rule 10 says every widening goes through a proposal, and an exception to rule 1 is a widening."
- "Whether that file is required is Yu's call, not mine."

So Nuance reads the exception as a widening, while lab-Claude read D as a clarification (section 2.3). This proposal goes through rule 10 either way. Section 10 asks Nuance to confirm or change this view as the review.

## 3. The problem

- **Rule 1 before the change** (AGENTS.md; `phase0/http` today): "No credentials, Betfair API, network or live code, and never a "temporary" live endpoint, not even a disabled one. Later live and Air-side code never lives in this repo; it goes in a separate repo that is never cloned on the lab."
- **R-2 needs two Air-side files.** DESIGN.md 8.6 item 2 stages four files under `tools/stage/`. Two of them run on the Air:
  - `air-ssh-config.snippet` is the `Host lab-suite` block for the Air's `~/.ssh/config`. It configures the Air's end of the SSH tunnel.
  - `air-viewer-selftest.sh` is a LAN SSH client. It logs in to the lab with the viewer key and checks that the key cannot do nine things.
- **The conflict.** Rule 1's Air-side sentence speaks of later code. Its "network code" clause is unqualified, and it covers both files (Q-Y19).
- **Who flagged it.**
  - The Codex review bot, inline on PR #5 (2026-10-15, on `tools/stage/air-viewer-selftest.sh`), P1: "Move the Air-side SSH tooling to the separate repository".
  - Astra, in the review of PR #5 at 8b89ee4, finding 1 (P1): "Resolve the rule 1 conflict before merging the Air client code." Astra's fix: "Move the Air program/configuration to the separate repository, or resolve Q-Y19 before merge through the applicable proposal/review process and Yu’s own written ruling, with consistent binding text."
- **What answers it.** Yu chose D, and asked for this proposal (section 2.1). This proposal is the proposal and review step that Astra's fix names. Section 9 sets the order before merge.
- **Earlier replies on PR #5.** Two of lab-Claude's replies on PR #5 came before Yu's "yes to formal proposal". The reply on the Codex thread (2026-10-16 09:16Z) says "Resolved by Yu's ruling on Q-Y19". The reply to Astra's review (2026-10-16 12:47Z) says "Finding 1 is answered by Yu's ruling", and that Yu had not ruled on a proposal file. This proposal replaces that wording. The Codex P1 and Astra's finding 1 are answered through this proposal, its review and Yu's written approval, not by "Go for D" alone.

## 4. The exact text change

### 4.1 AGENTS.md, rule 1

Before (`git show 0c1335b^:AGENTS.md`; the same on `phase0/http` today):

```
1. **Paper-only MVP.** No credentials, Betfair API, network or live code, and never a
   "temporary" live endpoint, not even a disabled one. Later live and Air-side code never lives
   in this repo; it goes in a separate repo that is never cloned on the lab.
```

After (proposed; `phase0/viewing` with the commit that adds this file):

```
1. **Paper-only MVP.** No credentials, Betfair API, network or live code, and never a
   "temporary" live endpoint, not even a disabled one. Later live and Air-side code never lives
   in this repo; it goes in a separate repo that is never cloned on the lab.
   - **The two R-2 viewer files are not network code under this rule (Q-Y19).** Yu chose
     option D on 2026-10-16 ("Go for D"): the R-2 approval already covered the two Air files of
     the viewer setup (DESIGN.md 8.6 item 2), `tools/stage/air-ssh-config.snippet` and
     `tools/stage/air-viewer-selftest.sh`, so the network clause does not cover them. This covers
     these two files and nothing else. Asked by lab-Claude whether a rule 10 proposal was also
     wanted, Yu answered on 2026-10-16: "yes to formal proposal". That proposal,
     `docs/proposals/002-air-viewer-files.md`, records its review and Yu's decision (DESIGN.md
     2.2.1, Q-N15).
     - The limits these files keep (DESIGN.md 8.6): they serve only the viewer tunnel. The
       snippet is the Air's `Host lab-suite` block, and it offers only the viewer key. The
       self-test logs in only to that Host, over LAN SSH by public key only, never a password,
       and uses `nc` only on the Air's own `127.0.0.1`. They hold no credentials and no Betfair
       API code. They run only on the Air, which takes them only from GitHub at the reviewed
       merge commit's SHA. On the lab, only the test harness runs the self-test, with fake `ssh`
       and `nc`.
     - Rule 1 is otherwise unchanged: other Air-side code and all other network code stay barred
       as before. Admitting more, or widening these two files, is a scope widening under rule 10.
```

### 4.2 DESIGN.md 3.9, rule 1

Before (`git show 0c1335b^:docs/DESIGN.md`):

```
  1. **Paper-only MVP.** No credentials, Betfair API, network or live code. Never a "temporary" live endpoint. Later live and Air code never lives in this repo.
```

After (proposed):

```
  1. **Paper-only MVP.** No credentials, Betfair API, network or live code. Never a "temporary" live endpoint. Later live and Air code never lives in this repo.
     - **The two R-2 viewer files are not network code under this rule** (Q-Y19, section 2.2.1). Yu chose option D: the R-2 approval already covered the two Air files of section 8.6 item 2, `tools/stage/air-ssh-config.snippet` and `tools/stage/air-viewer-selftest.sh`, so the network clause does not cover them. This covers these two files and nothing else. Asked by lab-Claude whether a rule 10 proposal was also wanted, Yu answered on 2026-10-16: "yes to formal proposal". That proposal, `docs/proposals/002-air-viewer-files.md`, records its review and Yu's decision (section 2.2.1, Q-N15).
       - The limits these files keep (section 8.6): they serve only the viewer tunnel. The snippet is the Air's `Host lab-suite` block, and it offers only the viewer key. The self-test logs in only to that Host, over LAN SSH by public key only, never a password, and uses `nc` only on the Air's own `127.0.0.1`. They hold no credentials and no Betfair API code. They run only on the Air, which takes them only from GitHub at the reviewed merge commit's SHA; on the lab only the test harness runs the self-test, with fake `ssh` and `nc`.
       - Rule 1 is otherwise unchanged: other Air-side code and all other network code stay barred as before. Admitting more, or widening these two files, is a scope widening under rule 10.
```

### 4.3 When the text takes effect

- The text in 4.1 and 4.2 holds no status. It stays the same after Yu's decision, so Yu approves the final rule text.
- It takes effect on `main` when PR #5 merges. Lab-Claude merges PR #5 only after Yu's written approval (section 9).
- Section 9 step 5 lists what changes after Yu's answer. None of it is rule text.

### 4.4 How the text reached this form

| Commit | Change to the rule 1 text |
|---|---|
| 0c1335b | Added the sub-bullet and its two points. It said "Option D treats this as a clarification of R-2, not a widening" and "Every other Air-side or network file stays barred by this rule." |
| e9b1646 | "LAN SSH offering only the viewer key" became "LAN SSH with the viewer key only, never a password". |
| beeb1f4 | Took "not a widening" out of the binding text and put D's caveat (the rule 10 proposal process) in its place. Replaced "Every other Air-side or network file stays barred", which was broader than the old rule, with "Rule 1 is otherwise unchanged: other Air-side code and all other network code stay barred as before." |
| The commit that adds this file | The caveat sentence now says that Yu, asked by lab-Claude, answered "yes to formal proposal", and points to this file. It holds no status. "With the viewer key only" became "it offers only the viewer key" for the snippet and "by public key only" for the self-test. That is what the code enforces (section 5.6). |

### 4.5 Text that records the ruling

These places record the ruling and point to rule 1. They add no permission of their own:

- DESIGN.md 2.2.1 (the Q-Y19 paragraph), 15.1 (the Q-Y19 row) and 15.2 (Q-N15). These carry the status of this proposal. 2.2.1 and 15.1 also record lab-Claude's commitment not to merge PR #5 before Yu's written approval.
- DESIGN.md 8.6 (the last sentence of "The trust boundary") and `tools/stage/README.md` step 5. Both name this proposal next to Yu's ruling, so neither reads as if "Go for D" alone settled it.

## 5. Safeguards kept

### 5.1 The scope of the exception

- It names two files by path. Nothing else is covered.
- Other Air-side code and all other network code stay barred. Admitting more, or widening these two files, goes through rule 10.
- Neither file holds credentials, Betfair API code or live code.

### 5.2 `air-ssh-config.snippet`

It is 23 lines of ssh config: one `Host lab-suite` block. It is not a program. It does this:

- names one host: `HostName 192.168.50.88`, `User user`, `AddressFamily inet`;
- offers one key: `IdentityFile ~/.ssh/id_ed25519_lab_suite` with `IdentitiesOnly yes`;
- logs in by public key only: `PreferredAuthentications publickey`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no` (e9b1646). The lab's sshd still accepts passwords for other logins. Without these lines, a refused viewer key would end at a `Password:` prompt, and the lab password typed there would open a full shell with no forced command;
- forwards one port: `LocalForward 127.0.0.1:8765 127.0.0.1:8765`, with `ExitOnForwardFailure yes`;
- keeps the key out of the agent and the Keychain: `AddKeysToAgent no`, `UseKeychain no`, `IdentityAgent none`;
- shares no connection: `ControlMaster no`, `ControlPath none`, `ControlPersist no`;
- runs no proxy and no local command: `ProxyCommand none`, `ProxyJump none`, `PermitLocalCommand no`;
- sets `StrictHostKeyChecking yes`, `RequestTTY no` and `ServerAliveInterval 30`.

It names no other host and holds no key or passphrase. It has no `Host *` or `Match` block. It is exactly the DESIGN.md 8.6 block, and a test checks that byte for byte. The block goes at the top of `~/.ssh/config`, above any `Host *` or `Match` block, because ssh keeps the first value it reads (stage README step 5). That protects single-value options only (section 5.6).

### 5.3 `air-viewer-selftest.sh`

It is a POSIX `sh` script without the execute bit. Yu runs `sh air-viewer-selftest.sh`, optionally with `--keep-logs`. Any other argument refuses (`usage`).

**Preflight.** Before any login it runs `ssh -G` for six forms (a53856a). `ssh -G` reads the config and connects nowhere. The forms are:

- the plain form, `ssh -G lab-suite`. That is Yu's daily `ssh lab-suite`, which has no `-o` options, so its authentication lines must come from the config;
- the exact form of each of the five logins: the same `-o` options, forwards, and command or session type that the login then uses. One function builds these arguments for both `ssh -G` and the login. The `-L` ports, the marker and the socket path are fixed before the checks for that reason.

It refuses (exit 2) before any login unless:

- `ssh` and `nc` are on PATH (`no_ssh`, `no_nc`);
- `ssh -G` succeeds for every form (`air_config_unreadable`);
- every form shows the block's host, user, address family, `IdentitiesOnly`, `AddKeysToAgent`, `ExitOnForwardFailure` and `StrictHostKeyChecking` values. `ExitOnForwardFailure` must be `no` in the form of probes 8-9, which pass it with `-o` so that both `-R` answers arrive;
- every form shows the three authentication lines (`air_config_auth`) and the seven hardening lines (`ControlMaster`, `ControlPath`, `ControlPersist`, `IdentityAgent`, `ProxyCommand`, `ProxyJump`, `PermitLocalCommand`);
- every form shows exactly one identity, the viewer key (`air_config_identityfile`), and that key's file exists (`key_missing`);
- every form shows no forward but the Host's `LocalForward` and the probe's own (`air_config_localforward`, `air_config_remoteforward`, `air_config_dynamicforward`). For probe 7 (`-W`) that is none, because ssh drops the config's forwards for `-W`. OpenSSH 10.2's `ssh -G` prints probe 6's `-L` to a Unix socket a second time, as a `dynamicforward` line with the same listen address. That one line is accepted in the form of probes 3-6;
- nothing listens on the Air's port 8765 (`viewer_port_busy`), and it can make its temporary directory (`workdir`).

A refusal in a probe's form names that probe, and says to add `!originalhost lab-suite` to the `Match` line. It does not check `UseKeychain`, `RequestTTY`, `ServerAliveInterval`, `ForwardAgent` or `ForwardX11`. The viewer line's `restrict` refuses agent and X11 forwarding on the lab.

Lab-Claude ran the per-form checks against real `ssh -G` output: OpenSSH 10.2 on the lab, scratch `-F` configs, and a scratch copy of the self-test with a wrapper that refused every login. The snippet alone passed all six forms. Each of these refused: a `Match sessiontype exec` block adding a key; a `Match sessiontype none` block adding a `LocalForward`, or `ClearAllForwardings no`; a `Match command` block adding a `RemoteForward`; a `Match` block above the snippet setting `ControlMaster`; a `Host *` block adding a `DynamicForward`. A `Match` block turning passwords on for exec sessions did not refuse, because the probe's `-o` options win.

**Probes.** It makes five logins, all to `lab-suite`, and nine probes.

- Every login passes `-o PreferredAuthentications=publickey -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no` (beeb1f4). The command line wins over every config block, so a `Match` block cannot bring back a password prompt for `-T`, `-N` or `-W`. These options fix the login method only. The preflight checks keys and forwards for each form.
- Probes 3-9 open no session (`-N`, `-W`). Probes 1-2 send `echo <marker>`, which the forced command refuses. No probe starts an engine.
- It uses `nc` only on the Air's own `127.0.0.1`: to check ports, and to send one fixed line into the probe forwards.
- A probe counts as refused only with evidence from the `ssh -v` log (`authed()` and the probe's own check). The log must show all of these (a53856a):
  - a "Server accepts key" line for the viewer key;
  - no "Will attempt key", "Offering public key" or "Server accepts key" line for any other key;
  - no "Trying private key" line;
  - a successful login ("Authenticated to" or "Authentication succeeded");
  - the lab's refusal of that probe.
- There is no "Trying private key" fallback any more. ssh logs that line only for a key whose public half it cannot read. It always has the viewer key's public half: from the `.pub` file, or else from the private key file, which keeps it unencrypted. So it offers the viewer key, and logs "Server accepts key" when the lab takes it. Lab-Claude checked this on the lab's OpenSSH 10.2 with a scratch passphrase-protected ed25519 key whose `.pub` was deleted: `ssh -v` logged "identity file ... type 2", a loaded key, with no passphrase typed. It ran through a `ProxyCommand` of `/usr/bin/true`, so no connection was made.
- The verdict is PASS (exit 0) only if all nine were refused. FAIL (exit 1) tells Yu to run the undo on the lab at once. Otherwise it is INCONCLUSIVE (exit 3).
- It writes only a temporary directory under `$TMPDIR`, and removes it at exit unless `--keep-logs` is given. The logs hold host, user and key path.

It does not use `sudo`, `/usr/bin/open` or a browser. It does not edit `~/.ssh/config` or any key. It never asks for a secret itself: ssh asks for the key's passphrase. Its own commands name no host but `lab-suite` and the Air's `127.0.0.1`.

### 5.4 How the files reach the Air, and who runs them

- The Air takes the two files only from GitHub, on the Air, at the full SHA of the reviewed merge commit. Not at a branch or tag name, which the lab's own `gh` login could move. Never by AirDrop from the lab (stage README step 5; DESIGN.md 8.6).
- The reason: any lab process running as `user` can change the release copy. A changed snippet could run commands on the Air through `ProxyCommand`, `LocalCommand` or `Match exec`. A self-test from the same copy would not catch it.
- **On the Air.** Yu runs the two files. Nuance may start the self-test, but only Yu types the key's passphrase (AGENTS.md, Phase 0 status D; DESIGN.md 8.6).
- **On the lab.**
  - Lab-Claude stages the files and never runs them (stage README; DESIGN.md 8.6).
  - Yu runs the lab script, which needs sudo; Nuance and lab-Claude do not (DESIGN.md 8.6).
  - Agents never run `open`, `ssh-session` or `--print-url` (AGENTS.md rule 6).
  - Only the test harness runs the self-test. It does so in a temporary HOME, with a fake `ssh` and a fake `nc` that connect nowhere (`tests/test_stage.py`).

### 5.5 What this proposal leaves as it is

- No Betfair credentials on the lab (DESIGN.md 2.3).
- The Air's own agent key stays LAN-only and keeps `no-port-forwarding`. The snippet offers only the viewer key. The self-test refuses to start unless every login's form offers only that key, and counts a probe as unclear when its log names another key. Section 5.6 gives the limits of these checks.
- AGENTS.md rules 2-10. Rule 6 still bars agents from `open`, `ssh-session` and `--print-url`.
- The lab side of R-2: the viewer key line, the sshd drop-in, and their undo.

### 5.6 Limits

These hold at the PR #5 tip. This proposal does not change them. a53856a narrowed the ones about login forms, the `-o` options and keys (section 7).

- Taking the files from GitHub at the SHA is an instruction to Yu. No code enforces it.
- **The logins use other forms than `ssh lab-suite`.** The probe logins send a command for probes 1-2 (`-T`, `-tt`), and open no session for probes 3-9 (`-N`, `-W`). `ssh -G` can differ for them in two ways:
  - A `Match` block above the lab-suite block can set a single-value option first. Yu's daily `ssh lab-suite` relies on the block sitting at the top of `~/.ssh/config`.
  - `IdentityFile`, `LocalForward`, `RemoteForward` and `DynamicForward` add up across blocks. So a `Match sessiontype` or `Match command` block anywhere in `~/.ssh/config` can add a key or a forward to a probe login, wherever the lab-suite block sits.
  - Lab-Claude checked this with `ssh -G` on scratch configs (OpenSSH 10.2; it reads the config and connects nowhere). With the snippet first and a `Match sessiontype exec` block after it, `ssh -G -T lab-suite 'echo x'` listed two identities, while the plain form listed one.
  - Since a53856a the preflight checks each login's own form (section 5.3), so both cases refuse before any login. It cannot see two things. `ssh -G` runs each `Match exec` command again, so a command that answers differently when the login runs is not caught. Nor is a change to `~/.ssh/config` after the preflight.
- **The `-o` options fix only the login method.** They do not fix keys or forwards. The per-form preflight checks those.
- **For keys, the evidence rule is the second check.** The per-form preflight is the first. The rule then needs "Server accepts key" for the viewer key. It counts a probe as unclear when a "Will attempt key", "Offering public key" or "Server accepts key" line names another key, or when any "Trying private key" line appears (section 5.3). It matches the key by its file name (`/id_ed25519_lab_suite` and a space), not by full path or fingerprint.
- **The tests' `ssh` is a fake.** The fake `ssh -G` follows what lab-Claude saw from OpenSSH 10.2 on the lab. No test runs the Air's OpenSSH, which may print some forms differently. The first run on the Air is where that would show.
- **One fixed lab address.** The files name the lab as `192.168.50.88`: `HostName` in the snippet, and `LAB_IP` in the self-test, which refuses any other host name (`air_config_hostname`). On 2026-10-16 the lab's Wi-Fi dropped, and it came back as `192.168.50.93` (Nuance's note 20261016T134105Z, item 6; the lab's `en0` shows the same).
  - While the lab is not at `.88`, `ssh lab-suite` goes to `.88`. `StrictHostKeyChecking yes` refuses any machine there whose host key is not the one `known_hosts` holds for that address. The self-test then sees no login, so it ends INCONCLUSIVE, never PASS.
  - Section 10 asks Yu how to settle the address before the viewer install.
- The self-test confirms the key's limits only when it runs. Any lab process running as `user` could later widen the key by editing `authorized_keys`. Only the root-owned drop-in is out of its reach (DESIGN.md 8.6).
- No code stops the self-test from being run somewhere other than the Air. Its preflight refuses unless `ssh -G` shows the block for every form.

## 6. Evidence required

Reviewers check:

1. The two files at the PR #5 tip do what section 5 says, and nothing more. Read both in full.
2. The rule 1 text in AGENTS.md and in DESIGN.md 3.9 matches section 4. It names exactly two files and says the same in both places.
3. No other file relies on the exception. `tools/stage/` holds those two files, two lab-side files and a README.
4. Draft 0.2 (d48f352), section 8.6, says what section 2.3 quotes from it.
5. The fast tier passes on 3.13 and 3.11 at the tip that carries this proposal (`bin/suite test -j 2` and `bin/suite test --py311 -j 2`), and the hygiene scan is clean.

These tests in `tests/test_stage.py` cover the safeguards:

| Test | What it pins |
|---|---|
| `StagedFilesTests.test_air_snippet_is_exactly_the_design_host_block` | The snippet is the DESIGN.md 8.6 block, byte for byte. That block holds the three authentication lines and the seven hardening lines. |
| `StagedFilesTests.test_staged_files_use_the_viewer_port` | The key's `permitopen`, the `LocalForward` in DESIGN.md and in the snippet, and the self-test's `VIEWER_PORT` all name `sshsession.VIEWER_PORT` (8765). |
| `StagedFilesTests.test_root_steps_only_through_run_root` | Outside comments, the self-test names no `sudo`, no `/usr/bin/open` and no `open http`. |
| `StagedFilesTests.test_every_script_parses_in_every_shell` | The self-test parses in `sh`, `bash` and `dash`. |
| `StagedFilesTests.test_scripts_are_posix_sh_and_not_executable` | The self-test starts with `#!/bin/sh` and has no execute bit. |
| `StagedFilesTests.test_design_texts_were_found` | The DESIGN.md blocks that the other tests compare with were found. |
| `StagedFilesTests.test_readme_walks_through_every_step` | The stage README names both files and every step. |
| `SelfTestScriptTests.test_scenarios` | Against a fake lab: a lab that refuses everything gives PASS (exit 0). One that allows too much gives FAIL (exit 1). No login, or a login where another key was accepted, gives INCONCLUSIVE (exit 3), never PASS. The work directory is removed. The fake `ssh` refuses any login without the three public-key-only `-o` options, so this test fails if `start_ssh` drops them. `ssh -G` ran for the plain form and then for each login's exact arguments, all before the first login. |
| `SelfTestScriptTests.test_the_log_must_show_the_viewer_key_and_no_other` | The lab refuses everything, but the log shows the viewer key tried without an offer, another key tried after the viewer key was accepted, another key offered first, another key listed ("Will attempt key") but never offered because the viewer key was accepted first, or a lone "Server accepts key" line for another key. Each gives INCONCLUSIVE (exit 3), never PASS. The last two each fail if their pattern leaves the evidence rule. |
| `SelfTestScriptTests.test_a_match_block_that_changes_one_form_is_refused` | Sixteen cases, each giving one probe's form only what a `Match` block could give it: another key, another forward, or a single-value option (host, `ControlMaster`, `IdentityAgent`, `ProxyCommand`). Each refuses (exit 2) before any login and names that probe. A control case, a `Match` block turning passwords on for probe 1's form, still gives PASS, because the probe's `-o` options win. The fake `ssh` answers `-G` per form for this. |
| `SelfTestScriptTests.test_preflight_refusals` | These faults refuse (exit 2) before probe 1: no `ssh` or no `nc` on PATH, `ssh -G` failing, a wrong host or user, address family `any`, `IdentitiesOnly no`, `ExitOnForwardFailure no`, `StrictHostKeyChecking accept-new`, a second key, the agent, no `LocalForward`, a `RemoteForward` or a `DynamicForward` from a later `Host *` block, port 8765 in use, no temporary directory, an inherited `ControlMaster`, `ControlPersist` or `ControlPath`, an agent socket, a proxy command, a jump host, a local command, and four password cases (`air_config_auth`: OpenSSH's defaults, password on, keyboard-interactive on, other methods preferred). A bad argument (`usage`) and a missing key (`key_missing`) refuse too. For a second key or a forward in the plain form, the hint says another block adds it and how to keep that block off lab-suite, since moving the block to the top cannot clear it; for a single-value setting it says to move the block to the top. |

**What no test covers.**

- Every refusal code now has a test. b1d5082 added one for each of the nine checks this section used to list as untested: `no_ssh`, `no_nc`, `air_config_unreadable`, `air_config_user`, `air_config_addressfamily`, `air_config_identitiesonly`, `air_config_exitonforwardfailure`, `air_config_stricthostkeychecking` and `workdir`.
- Two branches have none. `usage` is tested for a bad argument, not for a timeout that is not whole seconds. The `ExitOnForwardFailure no` check in the form of probes 8-9 is never refused, because the probe's own `-o` sets it and no config block can change it.
- No test runs a real `ssh` (section 5.6).

Before Yu's first use from the Air, R-2's own evidence still applies: the self-test prints `verdict: PASS (9 of 9 refused)` on the Air.

## 7. Tests that change

The rule text in section 4 does not change. The tests in section 6 are on `phase0/viewing`; e9b1646 and beeb1f4 added the public-key-only cases. The hygiene scanner's whole-checkout test reads this file, as it reads every file.

Astra's two code questions (section 10) are now implemented as separate commits on `phase0/viewing`, for Astra to review:

| Commit | What it changes |
|---|---|
| a53856a | The per-form preflight and the evidence rule without the "Trying private key" fallback (section 5.3). The fake `ssh` answers `ssh -G` per form. New tests: `test_a_match_block_that_changes_one_form_is_refused` and `test_the_log_must_show_the_viewer_key_and_no_other`. `test_scenarios` checks the `ssh -G` calls, and `test_preflight_refusals` gains a `RemoteForward` and a `DynamicForward` case. DESIGN.md 8.6 and `tools/stage/README.md` describe the checks. |
| b1d5082 | A refusal test for each of the nine checks that had none (section 6). |

Fail-before. For each fix, lab-Claude put a scratch copy of the script in place with only that fix taken out, ran the new test and saw it fail, then put the fixed file back (cmp equal):

- without the five per-form `ssh -G` checks, all 16 cases of the `Match` test ran on to a PASS instead of refusing ("(0, []) != (2, ['air_config_identityfile'])" and the like), and `test_scenarios` saw one `ssh -G` call instead of six;
- without the `RemoteForward` or the `DynamicForward` check, its cases ran on to a PASS;
- with the old evidence rule, the three new scenarios gave PASS instead of INCONCLUSIVE ("0 != 3");
- without each of the nine checks, its case failed. `no_ssh` and `no_nc` refused later, as `air_config_unreadable`. `air_config_unreadable` refused as `air_config_hostname`. Without the `workdir` check the run went on and exited 1. The five config checks ran on to a PASS ("(0, []) != (2, [code])").

## 8. Rollback

**If Yu does not approve the reviewed proposal.** PR #5 is then still unmerged (section 9 step 4). On `phase0/viewing`, as new commits:

- put rule 1 back to the "before" text in AGENTS.md and DESIGN.md 3.9;
- take the two Air files out of this repo, by Q-Y19 option A (a separate repo) or option B (the Host block as text in 8.6, and a checklist), as Yu then rules;
- remove or move the tests that use them: `SelfTestScriptTests`, and the snippet and self-test parts of `StagedFilesTests`;
- update every other place that names the two files, the self-test or the ruling:
  - AGENTS.md, Phase 0 status D ("the Air self-test under `tools/stage/`");
  - DESIGN.md: the header Status, 2.2.1, 3.4 (the layout tree), 8.6 (item 2, and "The trust boundary"), 9.4 (two threat rows), 12 (the Phase 0 row and the Phase 0 status), 15.1 (Q-Y19), 15.2 (Q-N15) and 16 (the viewer-key risk row);
  - `tools/stage/README.md`: the file table, "Before you start", and steps 5 and 6;
  - `tools/stage/suite-viewer-setup.sh`: its `next:` line, which tells Yu to run the self-test. This is the rollback's one lab-side code change;
  - the root `README.md`: check that "later Air-side and live work" (0c1335b) still reads right;
  - `grep -rn 'air-viewer-selftest\|air-ssh-config\|Q-Y19\|Air-side self-test\|Air self-test\|two Air files' .` finds them;
- mark this proposal "Not approved".

**If it is reverted after merge.** The same changes, as a new reviewed PR. Nothing installed on the Air changes by itself. On the Air, Yu deletes the `Host lab-suite` block and the self-test copy. To stop viewing from the Air altogether, R-2's own undo applies: `suite-viewer-setup.sh --undo` on the lab, then delete the key pair on the Air (stage README, "Undo").

**What Yu would lose** (from Q-Y19's option texts):

- With A: the port and the Host block are kept in two repos. That repo does not exist yet (Q-N13), and Nuance would have to agree to own it. The snippet and the self-test's port leave this repo, so `tests/test_stage.py` can no longer check them against DESIGN.md 8.6 and the code.
- With B: a hand-read checklist loses the self-test's evidence rule and its `ssh -G` preflight, the public-key-only check included.

Whatever replaces the snippet should keep the three public-key-only lines, because the lab's sshd still accepts passwords.

## 9. Process and order

DESIGN.md section 14's steps, for this proposal:

| Step | Here |
|---|---|
| 1. Lab-Claude writes the proposal | This file. |
| 2. A Collab coordination task for Nuance | To be opened when this file is pushed. |
| 3. Nuance drafts the upstream change | Does not apply. This changes only the suite's own AGENTS.md rule 1 and DESIGN.md 3.9. betangel-research is not touched. |
| 4. Astra reviews | This proposal, with PR #5 (finding 1). Astra's re-review of PR #5 at d9b129e started before this file existed, so lab-Claude asks Astra to review this file as well. |
| 5. Yu approves in writing | After Nuance and Astra have reviewed. |
| 6. Nuance implements upstream | Does not apply, as for step 3. |
| 7. The suite bumps its pin | Does not apply. The pin does not change. |

Rule 10 also asks for Nuance's review. Section 10 asks for it, and so does the PR #5 description.

**Order for PR #5.** This answers Astra's finding 1.

1. Nuance and Astra review this proposal. Astra's review of PR #5 goes on under the routing in AGENTS.md (Q-Y8).
2. Any change from review goes onto `phase0/viewing` as new commits. The rule text and section 4 change together, so the binding text and this proposal stay the same.
3. Yu is asked to approve the reviewed proposal in writing. That reaches lab-Claude in a lab-Claude session Yu types into, or in an acceptance checklist file Yu edits (DESIGN.md 3.9). A relay from Nuance, Astra, the mailbox or Collab is not approval.
4. Lab-Claude does not merge PR #5 before step 3. This is lab-Claude's own commitment, not Yu's words. It keeps Astra's "before merge" without deciding whether "Go for D" was itself the rule 10 approval. DESIGN.md 2.2.1 and the 15.1 Q-Y19 row record it too. Until PR #5 merges, `phase0/http` keeps rule 1 as before.
5. After Yu's answer, one commit records it, before any merge:
   - this file's Status: Yu's words and the date;
   - DESIGN.md 2.2.1 (the Q-Y19 paragraph), the 15.1 Q-Y19 row and its status cell, and 15.2 (Q-N15).

   It changes no rule text. The rule 1 text in section 4 is the text Yu approves.

## 10. Decisions asked

| Who | Asked | Notes |
|---|---|---|
| Nuance | Review this proposal. In particular, the open half of Q-N15: do you agree with the rule 1 wording in section 4? | Yu answered Q-N15's other half on 2026-10-16: "yes to formal proposal". Nuance's first view (section 2.4) supports the wording "as long as nothing else widens". Lab-Claude asks Nuance to confirm or change it as the review. Lab-Claude also asks: should the rule say what "widening these two files" means? Lab-Claude's reading: any change that lets either file reach a machine other than the lab, another port or socket, use another key or login method, hold a secret, or run on the lab outside the test harness. Under that reading, moving the lab's one address (section 5.6) is not a widening, because it is the same machine with the same host key. |
| Astra | Review this proposal with PR #5. Two code questions, asked in this proposal's first draft and now implemented for Astra to review (section 7). (1) Should the self-test run its identity and forward checks on `ssh -G` with each probe's options (`-T` and `-tt` with a command, `-N` with the probe forwards, `-W`), require exactly one identity in each, and drop or tighten the "Trying private key" fallback (section 5.6)? a53856a checks all six forms and drops the fallback, the stricter option; section 5.3 says why a correct setup still passes. Is dropping it right, and is anything missing from the per-form checks? (2) Should the untested refusals in section 6 get test cases? b1d5082 adds one for each of the nine. | It is written to answer PR #5 finding 1 (P1): "resolve Q-Y19 before merge through the applicable proposal/review process and Yu’s own written ruling, with consistent binding text". Does it, once Yu approves? |
| Yu | (1) The lab's address, before the viewer install: reserve `192.168.50.88` for the lab on the router, with no file change, or move the two files, DESIGN.md 8.6 and the tests to the lab's new address (section 5.6)? Does moving that one lab address count as widening these two files? (2) After both reviews, approve the reviewed proposal in writing, or not. | Yu chose D ("Go for D"). Asked by lab-Claude, Yu answered "yes to formal proposal". Approval of the proposal itself comes after review. The router is Yu's; lab-Claude changes no network settings. Question 1 is best answered with question 2. |
