# Building the custom Prebid Server image

`prebid-server/` no longer runs the stock `prebid/prebid-server` image — it
builds one from source with the `ortbvast` Bouncer and Enricher hooks
(`modules/ortbvast/{bouncer,enricher}`) compiled in, because PBS's Go module
system has no runtime plugin loading (see `ARCHITECTURE.md` §4). This doc is
the build/verification checklist that `ARCHITECTURE.md` §5 points to.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/), with
  network access for the first build (it clones `prebid/prebid-server` from
  GitHub and pulls Go module dependencies).
- On Apple Silicon: no change needed. `docker-compose.yml` already pins
  `platform: linux/amd64` for both services — PBS has no arm64 build, so it
  runs under Rosetta emulation.

## Before you build: verify the unverified assumptions

Everything below was written against Prebid Server's **published docs**
(`docs.prebid.org/prebid-server/developers/add-a-module-go.html`,
`pkg.go.dev/github.com/prebid/prebid-server/v2/hooks/hookstage`), not against
a fetched copy of the `v4.8.0` source tree — GitHub raw fetches were
unavailable in the session that wrote these files. Each file says so inline
(`NOTE ON PROVENANCE`, `VERIFY BEFORE BUILDING`/`VERIFY BEFORE RUNNING`
comments). Treat a clean `docker compose build` as the actual confirmation,
not this doc — but check these three things first, since they're the parts
most likely to have drifted from the docs by `v4.8.0`:

1. **Go import path / module version** — `modules/ortbvast/bouncer/module.go`
   and `modules/ortbvast/enricher/module.go` both import
   `github.com/prebid/prebid-server/v2/hooks/hookstage`. After the
   Dockerfile's clone step, confirm that path still matches the repo's own
   module declaration:

   ```bash
   git clone --depth 1 --branch v4.8.0 https://github.com/prebid/prebid-server.git /tmp/pbs-check
   grep ^module /tmp/pbs-check/go.mod
   ```

   If the major version segment differs (e.g. it's `v3` or unversioned by
   `v4.8.0`), update the import paths in both `module.go` files before
   building — the Go compiler will fail loudly if this is wrong, so a clean
   build is sufficient confirmation this one is fine.

2. **`hookstage` payload/result field shapes** — `bouncer/module.go` assumes
   `hookstage.EntrypointPayload` exposes `Request *http.Request` and `Body
   []byte`; `enricher/module.go` assumes `hookstage.RawAuctionRequestPayload`
   is a `json.RawMessage`-shaped raw body (pre-decode). Both assumptions are
   documented inline next to where they're used. If `go build` fails inside
   the Dockerfile's build stage on a field-access error, this is almost
   certainly why — diff the vendored `hookstage` package at
   `/tmp/pbs-check/hooks/hookstage` against the assumptions above and adjust
   field access in the module code.

3. **`pbs.yaml` hooks config shape** — the `hooks:` block's key names
   (`host_execution_plan` at the top level vs. nested under an
   account/endpoint-specific plan) mirror the JSON example in the same PBS
   docs page, not a config PBS `v4.8.0` was confirmed to parse. If the
   container starts but logs a config parse warning/error for the `hooks:`
   section, cross-check `pbs.yaml`'s shape against
   `/tmp/pbs-check/docs/end-to-end.md` or the vendored hooks config loader
   under `config/`.

You can discard `/tmp/pbs-check` once you've checked these — the Dockerfile
does its own clone during the actual build.

## Build

From `prebid-server/`:

```bash
./start.sh
```

This runs, in order: `docker compose build` (first run clones + compiles all
of Prebid Server with `modules/ortbvast` vendored in — several minutes,
needs network access; later builds are cached unless `modules/ortbvast/` or
`PBS_VERSION` in `docker-compose.yml` change), then `docker compose up -d`,
then polls `http://localhost:8000/status` for up to 2 minutes.

To build without starting the stack (e.g. just to confirm the module code
compiles against a `PBS_VERSION` bump):

```bash
cd prebid-server
docker compose build
```

**If the build fails:** it's almost always one of the two Go-level
assumptions in step 1/2 above. The compiler error will name the missing
field or type — that error is the actual authoritative answer, more so than
anything in this doc.

**If the build succeeds but the container won't start / logs a config
error:** check `docker compose logs -f prebid-server` first; if it's a hooks
config parse error, see step 3 above.

## Verify the running stack

Once `./start.sh` reports both services up:

```bash
curl -sf http://localhost:8000/status
curl -sf http://localhost:2424/status   # prebid-cache
```

Then confirm the hooks actually ran, not just that PBS started — the debug
trace is the only reliable signal for the Enricher, since none of the mock
DSP seats otherwise consume its `user.data[]` mutation:

```bash
curl -s -X POST http://localhost:8000/openrtb2/auction \
  -H "Content-Type: application/json" \
  --data-binary @../examples/flextechads-ortb-request-pbs-test-debug.json \
  | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['ext']['debug'], indent=2))"
```

Look for a `user.data[]` entry from `ortbvast-mock-idsp` in the resolved
request. If it's missing, the Enricher hook either isn't wired into
`host_execution_plan` correctly (step 3 above) or the fixture's `device.ifa`
doesn't match an entry in `cache-config/enricher-profiles.json`.

For the Bouncer, add an IP from `cache-config/bouncer-blocklist.txt` as
`X-Forwarded-For` on a request and confirm you get a rejection (`204`, or a
no-bid response carrying the configured `nbr_code`) instead of a normal
auction response.

For full coverage, run the pytest suite instead of hand-checking curl output
— see `TESTING.md` for what each test covers:

```bash
cd ..   # back to repo root
pip install -r tests/requirements.txt
pytest tests/
```

## Rebuild triggers

| Change | Action needed |
|---|---|
| `modules/ortbvast/{bouncer,enricher}/module.go` | `docker compose build` (compiled into the binary) |
| `PBS_VERSION` in `docker-compose.yml` | `docker compose build` (re-clones at the new tag) |
| `pbs.yaml`, `stored_requests/`, `cache-config/*` | Config/fixtures are loaded at container startup only — `./stop.sh && ./start.sh` is enough, no rebuild |

## Debugging the compiled hooks (Bouncer/Enricher) in VS Code

The pytest suite in `tests/` only exercises the HTTP surface — it can't step
into `modules/ortbvast/{bouncer,enricher}/module.go`, because that code runs
inside a separate Go process in the container, not in the Python test
process. To step into it, run a **second, independent debug session**: a Go
debugger (Delve) attached directly to the containerized `prebid-server`
binary. You'd set a breakpoint in VS Code, then trigger it by sending a
request from anywhere — `curl`, the pytest suite, PyCharm — same as normal;
execution pauses in VS Code, not in whatever sent the request.

This uses a separate debug build (`Dockerfile.debug` / `docker-compose.debug.yml`)
so the normal `./start.sh` image is untouched — the debug image disables Go
compiler optimizations/inlining (required for breakpoints to bind reliably)
and launches the binary under Delve instead of running it directly.

**One-time setup:** install the ["Go" extension](https://marketplace.visualstudio.com/items?itemName=golang.Go)
in VS Code (Extensions icon in the left sidebar, search "Go", the one
published by "Go Team at Google") if you haven't already. `.vscode/launch.json`
at the repo root already has the attach configuration set up — nothing else
to configure.

**Each debugging session:**

1. Open the `ortb-vast` folder itself in VS Code (File → Open Folder... →
   pick the repo root, not a subfolder) — `.vscode/launch.json` is only
   picked up when the folder containing it is the open workspace.
2. Start the debug-enabled stack instead of the normal one:
   ```bash
   cd prebid-server
   ./start-debug.sh
   ```
   This is a normal, fully working PBS instance on `:8000` the moment it
   reports healthy — attaching a debugger is optional, not required for the
   server to run.
3. In `modules/ortbvast/bouncer/module.go`, click in the gutter (the empty
   strip left of the line numbers) next to a line inside
   `HandleEntrypointHook` — e.g. the `if m.filter.mightContain(ip) {` line —
   to set a breakpoint (a red dot appears). Same gesture as PyCharm.
4. Open the **Run and Debug** panel: the sidebar icon that looks like a play
   button with a bug on it (or press `Cmd+Shift+D`). At the top of that
   panel there's a dropdown — select **"Attach to Bouncer/Enricher
   (Docker)"** — then click the green play arrow next to it (or press `F5`).
   VS Code connects to Delve inside the container; a floating debug toolbar
   appears once attached.
5. Trigger the breakpoint however you like — re-run
   `test_bouncer_blocks_known_bad_ip` in PyCharm, or from any terminal:
   ```bash
   curl -s -X POST http://localhost:8000/openrtb2/auction \
     -H "Content-Type: application/json" \
     -H "X-Forwarded-For: 192.0.2.66" \
     --data-binary @../examples/flextechads-ortb-request-pbs-test.json
   ```
   Execution pauses on your breakpoint in VS Code. The floating toolbar's
   icons step over (`F10`), step into (`F11`), step out (`Shift+F11`), and
   continue (`F5`); variables and the call stack show in the left panel.
6. **While paused, the whole server is paused** — Delve halts every
   goroutine on a breakpoint by default, so other requests will hang until
   you resume. Don't leave a session paused if you need the harness usable
   for something else in the meantime.
7. When finished, click the red square (disconnect) in the floating
   toolbar. Because the container was started with Delve's
   `--accept-multiclient`/`--continue` flags, disconnecting does **not**
   stop the server — it keeps serving on `:8000` exactly as before, and you
   can reattach (repeat step 4) at any point without restarting anything.

**Caveat:** breakpoints only resolve to visible source for files that exist
in your local workspace at the same relative path the binary was built
from — i.e. `modules/ortbvast/**`, via the `substitutePath` mapping in
`launch.json`. Prebid Server's own core source (cloned into the container
at build time, not present locally) isn't browsable this way; that's
expected, since the only custom code here is in `modules/ortbvast/`.

**Back to normal:** `./stop.sh` works unchanged for the debug stack too
(same container/service names). Switch back to the regular image with:
```bash
./stop.sh && ./start.sh
```

## Local editor tooling (VS Code): resolving `modules/ortbvast` imports

`modules/ortbvast/{bouncer,enricher}` import `github.com/prebid/prebid-server/v4/...`,
but the repo has no `go.mod` of its own — by design, since the Dockerfile
vendors those two directories directly into a *fresh clone* of
prebid-server's own module tree at build time (see `Dockerfile`), rather
than treating them as a separate dependency. That's correct for the build,
but it means an editor opened on this repo alone has no module context to
resolve those imports against, and gopls (VS Code's Go language server)
reports `BrokenImport` / `cannot find package ... in GOROOT` — it's fallen
back to legacy GOPATH-style resolution, which only ever looks in the
standard library.

Fix: a `go.mod` at the repo root, `require`-ing prebid-server as an ordinary
dependency purely for local tooling. **This must live at the repo root, not
inside `modules/ortbvast/`** — a `go.mod` inside `modules/ortbvast/` would
create a nested module boundary that breaks the Dockerfile's build (the
codegen step that scans `./modules/...` would stop seeing those packages as
part of prebid-server's module). The root `go.mod` is invisible to Docker
either way, since the Dockerfile's `COPY modules/ortbvast ./modules/ortbvast`
only ever copies that one subdirectory.

One-time setup, from a terminal in the repo root (VS Code's own integrated
terminal works — **Terminal → New Terminal**, or `` Ctrl+` ``):

```bash
go mod tidy
```

This downloads prebid-server's module graph (a large application with many
transitive dependencies — expect it to take a minute or two the first time,
cached under `~/go/pkg/mod` afterward) and writes `go.sum`. Once it
finishes, reopen `modules/ortbvast/enricher/module.go` — the import errors
should be gone. If they aren't, reload the window (`Cmd+Shift+P` →
"Developer: Reload Window") to force gopls to pick up the new `go.mod`.

If VS Code prompts "Some tools are missing" (gopls, dlv, etc.) the first
time you open a `.go` file, click **Install All** — that's the Go
extension's own local tooling, unrelated to the `go.mod` fix above, and
only needs to happen once.

## Running everything from VS Code

With the Go import fix above and `.vscode/launch.json` / `.vscode/settings.json`
in place (see the repo's `.vscode/` folder), both debugging paths run from
one editor:

- **Python tests:** the **Testing** panel in the left sidebar (flask/beaker
  icon) lists every `test_*` function once `python.testing.pytestEnabled`
  picks them up — click the debug icon next to any test to run it under
  VS Code's Python debugger, breakpoints and all, no PyCharm needed.
- **Go hooks:** start `./start-debug.sh`, then use the **Run and Debug**
  panel's "Attach to Bouncer/Enricher (Docker)" configuration exactly as
  described above.

Run both at once for the full picture: attach the Go debugger first, set a
breakpoint in `modules/ortbvast/bouncer/module.go`, then debug
`test_bouncer_blocks_known_bad_ip` from the Testing panel — the HTTP
request it sends is what triggers the Go breakpoint. The two debug sessions
are independent (switch between them via the dropdown next to the stop
button in the floating debug toolbar); stopping one doesn't affect the
other.

## Tear down

```bash
cd prebid-server
./stop.sh   # docker compose down
```
