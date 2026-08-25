// Package bouncer implements a Prebid Server Entrypoint-stage hook that
// rejects inbound auction requests whose source IP appears in a Bloom
// filter of known-bad addresses — before the request body is parsed.
//
// This is intentionally the earliest hook stage available: a Bloom filter
// lookup is a handful of bit-array reads against in-process memory, so
// running it pre-JSON-parse means bad traffic never pays the unmarshal
// cost, and a "no" answer is exact (a Bloom filter never lets bad traffic
// through by mistake — its only error mode is an occasional false
// positive on good traffic, tunable via false_positive_rate below).
//
// NOTE ON PROVENANCE: this targets Prebid Server's documented Hooks/Modules
// framework (docs.prebid.org/prebid-server/developers/add-a-module-go.html,
// pkg.go.dev/github.com/prebid/prebid-server/v4/hooks/hookstage). The
// hookstage.Entrypoint interface and HookResult[T]/ModuleInvocationContext
// shapes were confirmed against that documentation; the exact field names
// on hookstage.EntrypointPayload (assumed here: Request *http.Request,
// Body []byte) were NOT verifiable against source during authoring because
// GitHub raw fetches were unavailable in that session. Before `go build`,
// diff this against the vendored hookstage package for your PBS version —
// go.mod will resolve exactly which prebid-server version/commit you're
// building modules against — and adjust field access if it doesn't compile.
package bouncer

import (
	"context"
	"encoding/json"
	"hash/fnv"
	"math"
	"net"
	"net/http"
	"os"
	"strings"

	"github.com/prebid/prebid-server/v4/hooks/hookstage"
	"github.com/prebid/prebid-server/v4/modules/moduledeps"
)

// Config is this module's block under hooks.modules.ortbvast.bouncer in
// pbs.yaml (or an account-level override), e.g.:
//
//	hooks:
//	  modules:
//	    ortbvast:
//	      bouncer:
//	        enabled: true
//	        blocklist_path: /etc/config/bouncer-blocklist.txt
//	        false_positive_rate: 0.001
//	        nbr_code: 2
type Config struct {
	BlocklistPath     string  `json:"blocklist_path"`
	FalsePositiveRate float64 `json:"false_positive_rate"`
	// NBRCode is the IAB "no bid reason" code returned when a request is
	// rejected. 2 = "Invalid Request" is a reasonable default for blocked
	// traffic; some deployments prefer a dedicated vendor-specific code.
	NBRCode int `json:"nbr_code"`
}

// Module holds the Bloom filter built once at startup from Config.
type Module struct {
	filter  *bloomFilter
	nbrCode int
}

// Builder is called once at server startup with this module's config and
// returns the instance PBS will invoke on every request at the configured
// stage. Signature matches the pattern used across prebid-server's built-in
// modules (modules/<vendor>/<name>/module.go).
func Builder(rawCfg json.RawMessage, _ moduledeps.ModuleDeps) (interface{}, error) {
	cfg := Config{FalsePositiveRate: 0.001, NBRCode: 2}
	if len(rawCfg) > 0 {
		if err := json.Unmarshal(rawCfg, &cfg); err != nil {
			return nil, err
		}
	}

	ips, err := loadBlocklist(cfg.BlocklistPath)
	if err != nil {
		return nil, err
	}

	filter := newBloomFilter(len(ips), cfg.FalsePositiveRate)
	for _, ip := range ips {
		filter.add(ip)
	}

	return Module{filter: filter, nbrCode: cfg.NBRCode}, nil
}

// HandleEntrypointHook is called before the request body is parsed. It
// reads only the connection's source IP (preferring X-Forwarded-For, since
// STV/CTV traffic typically arrives through a CDN or LB), checks it
// against the Bloom filter, and rejects the request outright on a hit.
func (m Module) HandleEntrypointHook(
	_ context.Context,
	_ hookstage.ModuleInvocationContext,
	payload hookstage.EntrypointPayload,
) (hookstage.HookResult[hookstage.EntrypointPayload], error) {
	result := hookstage.HookResult[hookstage.EntrypointPayload]{}

	if m.filter == nil {
		return result, nil
	}

	ip := clientIP(payload.Request)
	if ip == "" {
		return result, nil
	}

	if m.filter.mightContain(ip) {
		result.Reject = true
		result.NbrCode = m.nbrCode
		result.Message = "source IP present in bad-actor bloom filter"
		result.DebugMessages = append(result.DebugMessages,
			"ortbvast.bouncer: rejected ip="+ip)
	}

	return result, nil
}

func clientIP(r *http.Request) string {
	if r == nil {
		return ""
	}
	if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
		// Leftmost address is the original client by convention.
		parts := strings.SplitN(fwd, ",", 2)
		return strings.TrimSpace(parts[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func loadBlocklist(path string) ([]string, error) {
	if path == "" {
		return nil, nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var ips []string
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		ips = append(ips, line)
	}
	return ips, nil
}

// --- minimal in-process Bloom filter (Kirsch-Mitzenmacher double hashing) ---
//
// Deliberately dependency-free: adding a third-party Bloom filter package
// means updating go.sum for a from-source PBS build, which is extra surface
// area for a demo module. This implementation is a standard bit-array +
// double-hashing filter, sized from the expected item count and target
// false-positive rate at construction time.

type bloomFilter struct {
	bits []uint64
	m    uint64 // number of bits
	k    uint64 // number of hash functions
}

func newBloomFilter(expectedItems int, falsePositiveRate float64) *bloomFilter {
	n := expectedItems
	if n < 1 {
		n = 1
	}
	p := falsePositiveRate
	if p <= 0 || p >= 1 {
		p = 0.001
	}

	// m = -(n * ln(p)) / (ln(2)^2), k = (m/n) * ln(2)
	ln2 := math.Ln2
	m := uint64(math.Ceil(-(float64(n) * math.Log(p)) / (ln2 * ln2)))
	if m < 64 {
		m = 64
	}
	k := uint64(math.Round((float64(m) / float64(n)) * ln2))
	if k < 1 {
		k = 1
	}
	if k > 16 {
		k = 16 // cap hash count; diminishing returns past this for our scale
	}

	return &bloomFilter{
		bits: make([]uint64, (m+63)/64),
		m:    m,
		k:    k,
	}
}

func (f *bloomFilter) add(item string) {
	h1, h2 := f.hashes(item)
	for i := uint64(0); i < f.k; i++ {
		f.setBit((h1 + i*h2) % f.m)
	}
}

func (f *bloomFilter) mightContain(item string) bool {
	h1, h2 := f.hashes(item)
	for i := uint64(0); i < f.k; i++ {
		if !f.getBit((h1 + i*h2) % f.m) {
			return false
		}
	}
	return true
}

func (f *bloomFilter) hashes(item string) (uint64, uint64) {
	h1 := fnv.New64a()
	_, _ = h1.Write([]byte(item))
	sum1 := h1.Sum64()

	h2 := fnv.New64()
	_, _ = h2.Write([]byte(item))
	sum2 := h2.Sum64()
	if sum2 == 0 {
		sum2 = 1 // avoid degenerate all-same-bucket case when h2 is 0
	}
	return sum1, sum2
}

func (f *bloomFilter) setBit(pos uint64) {
	f.bits[pos/64] |= 1 << (pos % 64)
}

func (f *bloomFilter) getBit(pos uint64) bool {
	return f.bits[pos/64]&(1<<(pos%64)) != 0
}
