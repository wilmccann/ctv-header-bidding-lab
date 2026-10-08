// Package enricher implements a Prebid Server RawAuctionRequest-stage hook
// that decorates an incoming bid request with identity/audience data before
// it reaches stored-request merge or bidder fan-out — i.e. before any DSP,
// mock or real, ever sees the request.
//
// In production this stage would do a point lookup against an in-memory
// NoSQL store (Aerospike / Redis Enterprise / ScyllaDB) co-located with the
// bidding host, keyed by device ID, returning a user/audience profile in
// low-single-digit-millisecond time. This module keeps the same interface
// shape (Lookup(deviceID) (Profile, bool)) against an in-process map seeded
// from a JSON fixture at startup, so swapping in a real client later means
// changing the Builder function, not the hook logic.
//
// Built and tested against Prebid Server v4.8.0, where
// hookstage.RawAuctionRequestPayload is a []byte (the raw, not-yet-decoded
// auction body) — this stage runs before stored-request merge. If you bump
// PBS_VERSION, re-check that type in the new tag's hooks/hookstage package.
package enricher

import (
	"context"
	"encoding/json"
	"os"

	"github.com/prebid/prebid-server/v4/hooks/hookstage"
	"github.com/prebid/prebid-server/v4/modules/moduledeps"
)

// Config is this module's block under hooks.modules.ortbvast.enricher in
// pbs.yaml, e.g.:
//
//	hooks:
//	  modules:
//	    ortbvast:
//	      enricher:
//	        enabled: true
//	        profile_store_path: /etc/config/enricher-profiles.json
//	        segment_provider: ortbvast-mock-idsp
type Config struct {
	ProfileStorePath string `json:"profile_store_path"`
	// SegmentProvider is written into user.data[].name on a match, so
	// downstream bidders can tell which audience source produced a segment.
	SegmentProvider string `json:"segment_provider"`
}

// Profile is the shape stored per device ID in the mock KV store. Kept
// intentionally small/generic (segment id + human-readable name) rather
// than modeling a specific taxonomy, since real audience data providers
// each have their own segment ID scheme.
type Profile struct {
	Segments []Segment `json:"segments"`
}

type Segment struct {
	ID   string `json:"id"`
	Name string `json:"name"` // e.g. "age_25_34", "gender_male", "auto_intenders"
}

// Module holds the seeded mock profile store.
type Module struct {
	store           map[string]Profile // keyed by device.ifa
	segmentProvider string
}

// Builder is called once at startup with this module's config and loads
// the mock profile store fixture into memory. A real deployment would
// instead construct and hold a client to Aerospike/Redis/ScyllaDB here.
func Builder(rawCfg json.RawMessage, _ moduledeps.ModuleDeps) (interface{}, error) {
	cfg := Config{SegmentProvider: "ortbvast-mock-idsp"}
	if len(rawCfg) > 0 {
		if err := json.Unmarshal(rawCfg, &cfg); err != nil {
			return nil, err
		}
	}

	store, err := loadProfileStore(cfg.ProfileStorePath)
	if err != nil {
		return nil, err
	}

	return Module{store: store, segmentProvider: cfg.SegmentProvider}, nil
}

// HandleRawAuctionHook runs on the parsed-but-not-yet-merged auction body.
// It reads device.ifa, does the point lookup, and — on a hit — adds a
// user.data[] segment-provider block via the hook's ChangeSet, which is
// PBS's documented way for a raw_auction_request hook to mutate the
// request in flight (visible afterward in ext.debug.resolvedrequest in
// debug mode, which is how the integration tests confirm this ran without
// needing a real bidder to consume it).
func (m Module) HandleRawAuctionHook(
	_ context.Context,
	_ hookstage.ModuleInvocationContext,
	payload hookstage.RawAuctionRequestPayload,
) (hookstage.HookResult[hookstage.RawAuctionRequestPayload], error) {
	result := hookstage.HookResult[hookstage.RawAuctionRequestPayload]{}

	if len(m.store) == 0 {
		return result, nil
	}

	deviceIFA, err := extractDeviceIFA(payload)
	if err != nil || deviceIFA == "" {
		return result, nil
	}

	profile, found := m.store[deviceIFA]
	if !found || len(profile.Segments) == 0 {
		return result, nil
	}

	provider := m.segmentProvider
	result.ChangeSet.AddMutation(
		func(p hookstage.RawAuctionRequestPayload) (hookstage.RawAuctionRequestPayload, error) {
			return addUserDataSegments(p, provider, profile.Segments)
		},
		hookstage.MutationUpdate,
		"user.data",
	)
	result.DebugMessages = append(result.DebugMessages,
		"ortbvast.enricher: decorated device.ifa="+deviceIFA+" with "+provider)

	return result, nil
}

// extractDeviceIFA pulls device.ifa out of the raw request body without
// fully decoding it into an openrtb2.BidRequest, so this module doesn't
// need to depend on knowing every field PBS itself will later validate.
func extractDeviceIFA(payload hookstage.RawAuctionRequestPayload) (string, error) {
	var partial struct {
		Device struct {
			IFA string `json:"ifa"`
		} `json:"device"`
	}
	if err := json.Unmarshal(payload, &partial); err != nil {
		return "", err
	}
	return partial.Device.IFA, nil
}

// addUserDataSegments appends a user.data[] entry carrying the looked-up
// segments, preserving whatever else was already on the request (including
// any existing user.data providers) by round-tripping through a generic
// map rather than a strict openrtb2.User struct.
func addUserDataSegments(
	payload hookstage.RawAuctionRequestPayload,
	provider string,
	segments []Segment,
) (hookstage.RawAuctionRequestPayload, error) {
	var body map[string]interface{}
	if err := json.Unmarshal(payload, &body); err != nil {
		return payload, err
	}

	user, _ := body["user"].(map[string]interface{})
	if user == nil {
		user = map[string]interface{}{}
	}

	existingData, _ := user["data"].([]interface{})

	segArr := make([]interface{}, 0, len(segments))
	for _, s := range segments {
		segArr = append(segArr, map[string]interface{}{
			"id":   s.ID,
			"name": s.Name,
		})
	}

	dataEntry := map[string]interface{}{
		"name":    provider,
		"segment": segArr,
	}
	user["data"] = append(existingData, dataEntry)
	body["user"] = user

	return json.Marshal(body)
}

func loadProfileStore(path string) (map[string]Profile, error) {
	store := map[string]Profile{}
	if path == "" {
		return store, nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return store, nil
		}
		return nil, err
	}
	if err := json.Unmarshal(data, &store); err != nil {
		return nil, err
	}
	return store, nil
}
