# Retrospective: Delve breakpoints not firing under Docker on Apple Silicon

**Date:** 2026-08-25
**Component:** `prebid-server/Dockerfile.debug`, `prebid-server/docker-compose.debug.yml`, `.vscode/launch.json`
**Status:** Resolved

## Summary

Remote debugging `modules/ortbvast/bouncer`'s `HandleEntrypointHook` via VS
Code + Delve, attached to the `Dockerfile.debug` container, appeared to
connect successfully (debug toolbar live, session stayed up) but breakpoints
never fired, even while triggering the exact code path repeatedly. Root
cause: the debug container was running under Rosetta 2 emulation
(`platform: linux/amd64` inherited from the non-debug `docker-compose.yml`,
running on an arm64 host), and Delve's `ptrace`-based breakpoint mechanism
does not reliably work against a Rosetta-translated process. Fixed by
pinning the debug build to `platform: linux/arm64` — safe to do because,
unlike the production image, `Dockerfile.debug` compiles Prebid Server from
source rather than depending on a prebuilt amd64-only binary.

## Symptoms

- VS Code's "Attach to Bouncer/Enricher (Docker)" launch config connected
  cleanly: the debug toolbar appeared and stayed live, which normally only
  happens for a genuine attach, not a failed one.
- The target code path was provably executing: sending a request with a
  blocklisted IP in `X-Forwarded-For` returned `{"nbr":2}` — a custom
  no-bid-reason code that only `HandleEntrypointHook`'s reject branch could
  have produced.
- Despite both of the above, a breakpoint set on `module.go:111`
  (`result.Reject = true`) never paused execution. The Call Stack panel
  stayed empty across repeated attempts.
- `dlv connect` from a plain terminal showed a genuinely live Delve session
  (banner, responsive to Ctrl+C) but gave no reliable way to confirm
  breakpoint state via typed commands (inconsistent echo in an interactive
  PTY; a piped, non-PTY `docker exec -i` attempt produced zero output at
  all).
- A Python pytest test (`test_bouncer_blocks_known_bad_ip`, `requests.post(
  ..., timeout=10)`) kept passing — evidence in hindsight, since a genuinely
  hit breakpoint would have frozen that request past the 10s client timeout
  and produced a `ReadTimeout` error, not a pass.

## Investigation

Several plausible hypotheses were raised and ruled out in turn:

1. **VS Code Go extension adapter mismatch (`dlv-dap` vs. legacy).**
   Checked against the actual `golang/vscode-go` docs: `"mode": "remote"`
   already defaults to the legacy debug adapter (dlv-dap has no "remote"
   mode at all), and `apiVersion` already defaults to `2`, matching the
   server's `--api-version=2` flag. Not the cause.

2. **`substitutePath` mismatch.** The build stage's `WORKDIR /src` matches
   `substitutePath`'s `"to": "/src"` mapping, and no `-trimpath` flag is
   used, so DWARF paths should be absolute and correct. Deprioritized in
   favor of a more direct test.

3. **`showLog`/`logOutput` in launch.json.** Added to try to see the
   `CreateBreakpoint` RPC call from VS Code's side, but produced zero
   output even after fixing schema issues (the setting wants a JSON array,
   e.g. `["rpc", "debugger"]`, not a comma-joined string — and even then,
   some extension versions only accept a single string value). Root cause
   of *this* dead end: `showLog`/`logOutput` only apply when the debug
   adapter spawns `dlv` itself (local launch/attach). In `"mode": "remote"`,
   the adapter only opens a socket to an already-running, independently
   launched `dlv` process — there is no pipe to that process's stdout for
   the extension to print through. This setting was a no-op for this setup.

4. **Missing local `dlv` binary.** The Go extension had been complaining
   the local `dlv` tool wasn't installed; it was installed mid-investigation.
   Did not resolve the issue on its own, though it may matter for other
   extension features.

The decisive move was adding logging directly at the source — Delve's own
`--log --log-output=rpc,debugger` flags on the **server** side (the
container's `ENTRYPOINT`), since its stdout is captured by `docker logs`
regardless of which client attaches. That log immediately surfaced the real
signal:

```
2026-08-25T22:26:31Z info layer=debugger launching process with args: [/usr/local/bin/prebid-server]
2026-08-25T22:26:31Z debug layer=debugger Adding target 18 "/usr/bin/rosetta-wrapper /usr/local/bin/prebid-server /usr/local/bin/prebid-server"
```

The target process was being launched through `/usr/bin/rosetta-wrapper`.
Confirmed with `docker image inspect ... --format '{{.Architecture}}'`
(`amd64`) against `uname -m` on the host (`arm64`), and traced to an
explicit `platform: linux/amd64` pin in `prebid-server/docker-compose.yml`
— inherited by the debug overlay since `docker-compose.debug.yml` didn't
override it.

## Root cause

`docker-compose.yml` pins `platform: linux/amd64` with the comment "PBS has
no arm64 build; runs under Rosetta emulation on Apple Silicon." That's true
for the **production** service, which historically ran a prebuilt
`prebid/prebid-server` image with no arm64 tag. But `Dockerfile.debug`
compiles Prebid Server from source using `golang:1.25-bookworm`, a genuine
multi-arch base image with a native arm64 variant — the amd64 pin was
unnecessary baggage inherited from the compose file it overlays, not an
actual constraint of the debug build.

Running the debug target under Rosetta 2 emulation meant Delve's
`ptrace`-based breakpoint mechanism (writing an `INT3` into the target's
memory and relying on the resulting `SIGTRAP` being delivered back to the
tracer) had to survive an extra binary-translation layer between the
debugger and the debuggee. The TCP/JSON-RPC control channel worked fine
(plain sockets, unaffected by emulation), and normal execution worked fine
(`continue` ran the binary to completion correctly), which is exactly why
every other signal looked healthy — but breakpoint traps never made it back
to Delve.

## Fix

Added an explicit `platform: linux/arm64` override in
`prebid-server/docker-compose.debug.yml`, scoped to the debug overlay only
— the production `docker-compose.yml` pin is untouched, since that service
still depends on the prebuilt amd64-only image path the original comment
describes.

```yaml
services:
  prebid-server:
    platform: linux/arm64
    build:
      dockerfile: prebid-server/Dockerfile.debug
    ports:
      - "2345:2345"
```

After rebuilding, `docker image inspect` confirmed `arm64/linux`, and the
server log showed the target launching directly (`Adding target 18
"/usr/local/bin/prebid-server"`, no `rosetta-wrapper`). Breakpoints in
`modules/ortbvast/bouncer/module.go` bound and fired immediately on the
next attach.

## Verification

- Restarted the "Attach to Bouncer/Enricher (Docker)" VS Code session
  against the rebuilt arm64 container.
- Set a breakpoint at `module.go:111`; VS Code's Call Stack panel showed
  "Paused On Breakpoint" on the next matching request, with a full,
  correct stack (`bouncer.Module.HandleEntrypointHook` → PBS's hook
  executor → the HTTP handler goroutine).
- Confirmed the pytest test now fails with a client-side timeout while a
  breakpoint holds the request open — the mirror image of the false
  "passing" signal that helped surface the bug in the first place.

## Lessons / preventive notes

- **On Apple Silicon, always check for a `platform: linux/amd64` pin before
  assuming a `ptrace`-based debugger (Delve, gdb, lldb) should work.**
  Rosetta emulation degrades or breaks these tools in ways that look like
  "everything connected fine, but nothing happens" rather than a clear
  error — the failure mode is silent, not loud.
- **A platform pin justified for a prebuilt/vendor image does not
  automatically apply to a from-source build layered on top of it.**
  `docker-compose.debug.yml` inherited the amd64 pin by omission, not by
  intent. Any debug/dev overlay of a compose file should be checked for
  which base-file settings it's silently inheriting.
- **A client-side request timeout is a legitimate way to falsify "did the
  breakpoint actually pause the server."** If a breakpoint is hit, the
  in-flight request freezes; if the request completes (or the test cleanly
  passes/fails on its own assertions) inside the timeout window, the
  breakpoint did not fire, full stop — this is a cheap, VS Code-independent
  signal.
- **`showLog`/`logOutput` in a Go `"mode": "remote"` launch.json config are
  a dead end** — they only apply to a locally-spawned `dlv`. For a
  genuinely remote, independently-launched headless server, add `--log
  --log-output=<components>` directly to its own launch flags and read
  `docker logs` instead.
- Debugging the debugger benefits from the same instinct as debugging the
  target: find a signal that's independent of the layer you suspect is
  lying to you (VS Code's UI, in this case) rather than iterating inside
  that same layer.
