# Building the custom Prebid Server image

`prebid-server/` doesn't run the stock `prebid/prebid-server` image — it
builds one from source with the `ortbvast` Bouncer and Enricher hooks
(`modules/ortbvast/{bouncer,enricher}`) compiled in, because PBS's Go module
system has no runtime plugin loading (see `docs/ARCHITECTURE.md` §4). This
doc covers building, verifying, debugging, and upgrading that image.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/), with
  network access for the first build (it clones `prebid/prebid-server` from
  GitHub and pulls Go module dependencies).
- Works on both amd64 and arm64 (Apple Silicon) hosts. The PBS image is
  compiled natively for your machine; only the `prebid-cache` sidecar is
  pinned to `linux/amd64` (it has no arm64 image) and runs under emulation
  on Apple Silicon.

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

If the container builds but won't start, check
`docker compose logs -f prebid-server` first.

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
`host_execution_plan` in `pbs.yaml` or the fixture's `device.ifa` doesn't
match an entry in `cache-config/enricher-profiles.json`.

For the Bouncer, add an IP from `cache-config/bouncer-blocklist.txt` as
`X-Forwarded-For` on a request. A blocked request comes back as HTTP 200
with an empty response carrying the configured no-bid reason —
`{"id": "...", "nbr": 2}` — instead of a normal auction response.

For full coverage, run the pytest suite instead of hand-checking curl output
— see `docs/TESTING.md` for what each test covers:

```bash
cd ..   # back to repo root
pip install -r tests/requirements.txt
pytest tests/
```

## Rebuild triggers

| Change | Action needed |
|---|---|
| `modules/ortbvast/{bouncer,enricher}/module.go` | `docker compose build` (compiled into the binary) |
| `PBS_VERSION` in `docker-compose.yml` | `docker compose build` (re-clones at the new tag) — see "Upgrading Prebid Server" below |
| `pbs.yaml`, `stored_requests/`, `cache-config/*` | Config/fixtures are loaded at container startup only — `docker compose restart prebid-server` (or `./stop.sh && ./start.sh`) is enough, no rebuild |

## Upgrading Prebid Server

Everything here is built and tested against PBS **v4.8.0**. To move to a
newer tag, update `PBS_VERSION` in `docker-compose.yml` and both
Dockerfiles, then check, in order:

1. **Go import path** — the modules import
   `github.com/prebid/prebid-server/v4/...`. If the new tag's `go.mod`
   declares a different major version, update the imports in both
   `module.go` files and the `require` line in the root `go.mod`.
2. **Go toolchain** — the Dockerfiles build on `golang:1.25-bookworm`. Match
   the new tag's `go.mod` `go` directive if it's newer.
3. **Hook payload types** — the modules depend on
   `hookstage.EntrypointPayload` exposing `Request *http.Request` and on
   `hookstage.RawAuctionRequestPayload` being the raw `[]byte` body. A
   compile error in the Dockerfile's build stage will name the field or type
   that changed.
4. **Behavior** — run `pytest tests/`. The suite pins down behavior that
   has changed between PBS releases before (account-required semantics,
   unprefixed vs. per-bidder targeting keys, stored-response validation).

## Debugging the compiled hooks (Bouncer/Enricher) in VS Code

The pytest suite in `tests/` only exercises the HTTP surface — it can't step
into `modules/ortbvast/{bouncer,enricher}/module.go`, because that code runs
inside a separate Go process in the container, not in the Python test
process. To step into it, run a **second, independent debug session**: a Go
debugger (Delve) attached directly to the containerized `prebid-server`
binary. You'd set a breakpoint in VS Code, then trigger it by sending a
request from anywhere — `curl`, the pytest suite, another IDE — same as
normal; execution pauses in VS Code, not in whatever sent the request.

This uses a separate debug build (`Dockerfile.debug` / `docker-compose.debug.yml`)
so the normal `./start.sh` image is untouched — the debug image disables Go
compiler optimizations/inlining (required for breakpoints to bind reliably)
and launches the binary under Delve instead of running it directly.

**One-time setup:** install the ["Go" extension](https://marketplace.visualstudio.com/items?itemName=golang.Go)
in VS Code (Extensions icon in the left sidebar, search "Go", the one
published by "Go Team at Google") if you haven't already. The repo's
`.vscode/launch.json` already has the attach configuration set up — nothing
else to configure.

**Each debugging session:**

1. Open the repo root itself in VS Code (File → Open Folder... → pick the
   repo root, not a subfolder) — `.vscode/launch.json` is only picked up
   when the folder containing it is the open workspace.
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
   to set a breakpoint (a red dot appears).
4. Open the **Run and Debug** panel: the sidebar icon that looks like a play
   button with a bug on it (or press `Cmd+Shift+D`). At the top of that
   panel there's a dropdown — select **"Attach to Bouncer/Enricher
   (Docker)"** — then click the green play arrow next to it (or press `F5`).
   VS Code connects to Delve inside the container; a floating debug toolbar
   appears once attached.
5. Trigger the breakpoint however you like — run
   `test_bouncer_blocks_known_bad_ip`, or from any terminal:
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

**Caveats:**

- Breakpoints only resolve to visible source for files that exist in your
  local workspace at the same relative path the binary was built from —
  i.e. `modules/ortbvast/**`, via the `substitutePath` mapping in
  `launch.json`. Prebid Server's own core source (cloned into the container
  at build time, not present locally) isn't browsable this way; that's
  expected, since the only custom code here is in `modules/ortbvast/`.
- Delve needs the container running natively on your host's architecture;
  breakpoints silently fail to fire under Rosetta emulation. See
  `docs/RETROSPECTIVE-delve-debugging.md` for how that showed up and was
  diagnosed.
- Delve's own logs (RPC calls such as `CreateBreakpoint`) go to
  `docker compose logs prebid-server`, not to VS Code — `showLog`/`logOutput`
  in `launch.json` have no effect when attaching to a remote headless
  server.

**Back to normal:** `./stop.sh` works unchanged for the debug stack too
(same container/service names). Switch back to the regular image with:
```bash
./stop.sh && ./start.sh
```

## Local editor tooling: resolving `modules/ortbvast` imports

`modules/ortbvast/{bouncer,enricher}` import `github.com/prebid/prebid-server/v4/...`.
The Dockerfile vendors those two directories directly into a *fresh clone*
of prebid-server's own module tree at build time, so the build doesn't need
anything else. For local editing, the repo root has its own `go.mod`
`require`-ing prebid-server as an ordinary dependency, purely so gopls (VS
Code's Go language server) and `go build`/`go vet` can resolve those
imports.

**It must live at the repo root, not inside `modules/ortbvast/`** — a
`go.mod` inside `modules/ortbvast/` would create a nested module boundary
that breaks the Dockerfile's build (the codegen step that scans
`./modules/...` would stop seeing those packages as part of prebid-server's
module). The root `go.mod` is invisible to Docker, since the Dockerfile's
`COPY modules/ortbvast ./modules/ortbvast` only copies that one
subdirectory.

The first time you open a `.go` file, gopls downloads prebid-server's module
graph (a large application with many transitive dependencies — a minute or
two, cached under `~/go/pkg/mod` afterward). To check from a terminal:

```bash
go build ./modules/... && go vet ./modules/...
```

If VS Code prompts "Some tools are missing" (gopls, dlv, etc.) the first
time you open a `.go` file, click **Install All** — that's the Go
extension's own local tooling, and only needs to happen once.

**Optional: editable prebid-server source.** By default, "Go to Definition"
on anything from `hookstage`/`moduledeps` opens a read-only copy in the
module cache. To browse and edit a real checkout instead, clone
prebid-server next to this repo and add a local `go.work` (gitignored)
redirecting to it — see the comment at the top of `go.mod` for the exact
contents.

## Running everything from VS Code

With the repo's `.vscode/launch.json` and `.vscode/settings.json` in place,
both debugging paths run from one editor:

- **Python tests:** `settings.json` points VS Code at `.venv/bin/python` and
  enables pytest, so create the venv first
  (`python3 -m venv .venv && .venv/bin/pip install -r tests/requirements.txt`).
  The **Testing** panel in the left sidebar (flask/beaker icon) then lists
  every `test_*` function — click the debug icon next to any test to run it
  under VS Code's Python debugger, breakpoints and all.
- **Go hooks:** start `./start-debug.sh`, then use the **Run and Debug**
  panel's "Attach to Bouncer/Enricher (Docker)" configuration exactly as
  described above.

Run both at once for the full picture: attach the Go debugger first, set a
breakpoint in `modules/ortbvast/bouncer/module.go`, then debug
`test_bouncer_blocks_known_bad_ip` from the Testing panel — the HTTP
request it sends is what triggers the Go breakpoint. The two debug sessions
are independent (switch between them via the dropdown next to the stop
button in the floating debug toolbar); stopping one doesn't affect the
other. Note the test uses a 10-second request timeout, so it will fail with
a `ReadTimeout` if you stay paused on the Go breakpoint longer than that.

## Tear down

```bash
cd prebid-server
./stop.sh   # docker compose down
```
