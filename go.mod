// This go.mod exists ONLY so Go tooling (gopls, go build/vet) can resolve
// modules/ortbvast/{bouncer,enricher}'s imports of prebid-server's
// hooks/hookstage and modules/moduledeps packages for local editing,
// autocomplete, and error-checking. Without a go.mod anywhere above those
// files, gopls has no module context and reports "cannot find package ...
// in GOROOT".
//
// It has NO effect on the actual Docker build: prebid-server/Dockerfile
// clones prebid-server fresh into its own build stage and COPYs only
// modules/ortbvast/ into that clone's existing module tree (see
// prebid-server/Dockerfile and prebid-server/README-build.md) — this file
// and go.sum are never read by Docker; only the modules/ortbvast/
// subdirectory is part of the build context copy.
//
// For "Go to Definition" into editable prebid-server source instead of the
// read-only module cache copy, clone prebid-server (at v4.8.0) next to this
// repo and create a local, gitignored go.work at the repo root:
//
//   go 1.25.0
//   use .
//   replace github.com/prebid/prebid-server/v4 => ../prebid-server
//
// gopls and the go command pick it up automatically; without it, everything
// resolves from the public module cache.
module ortb-vast

go 1.25.0

require github.com/prebid/prebid-server/v4 v4.8.0

require (
	github.com/asaskevich/govalidator v0.0.0-20210307081110-f21760c49a8d // indirect
	github.com/buger/jsonparser v1.1.2 // indirect
	github.com/davecgh/go-spew v1.1.1 // indirect
	github.com/fsnotify/fsnotify v1.5.4 // indirect
	github.com/golang/glog v1.2.5 // indirect
	github.com/hashicorp/hcl v1.0.0 // indirect
	github.com/json-iterator/go v1.1.12 // indirect
	github.com/magiconair/properties v1.8.6 // indirect
	github.com/mitchellh/mapstructure v1.5.0 // indirect
	github.com/modern-go/concurrent v0.0.0-20180306012644-bacd9c7ef1dd // indirect
	github.com/modern-go/reflect2 v1.0.2 // indirect
	github.com/pelletier/go-toml v1.9.5 // indirect
	github.com/pelletier/go-toml/v2 v2.0.1 // indirect
	github.com/pkg/errors v0.9.1 // indirect
	github.com/pmezard/go-difflib v1.0.0 // indirect
	github.com/prebid/go-gdpr v1.12.0 // indirect
	github.com/prebid/openrtb/v20 v20.3.0 // indirect
	github.com/rcrowley/go-metrics v0.0.0-20201227073835-cf1acfcdf475 // indirect
	github.com/spf13/afero v1.8.2 // indirect
	github.com/spf13/cast v1.5.0 // indirect
	github.com/spf13/jwalterweatherman v1.1.0 // indirect
	github.com/spf13/pflag v1.0.5 // indirect
	github.com/spf13/viper v1.12.0 // indirect
	github.com/stretchr/objx v0.5.0 // indirect
	github.com/stretchr/testify v1.8.4 // indirect
	github.com/subosito/gotenv v1.3.0 // indirect
	github.com/tidwall/gjson v1.17.1 // indirect
	github.com/tidwall/match v1.1.1 // indirect
	github.com/tidwall/pretty v1.2.0 // indirect
	github.com/xeipuuv/gojsonpointer v0.0.0-20180127040702-4e3ac2762d5f // indirect
	github.com/xeipuuv/gojsonreference v0.0.0-20180127040603-bd5ef7bd5415 // indirect
	github.com/xeipuuv/gojsonschema v1.2.0 // indirect
	golang.org/x/sys v0.45.0 // indirect
	golang.org/x/text v0.37.0 // indirect
	gopkg.in/evanphx/json-patch.v5 v5.9.0 // indirect
	gopkg.in/ini.v1 v1.66.4 // indirect
	gopkg.in/yaml.v2 v2.4.0 // indirect
	gopkg.in/yaml.v3 v3.0.1 // indirect
)
