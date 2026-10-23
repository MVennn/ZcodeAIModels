// Package keys finds the three upstream credentials without ever writing them
// to a log or to the health endpoint.
//
// Order per channel (same as the old Node router):
//
//	OC: env OPENCODE_GO_KEY -> provider_config.json (opencode base / providerId)
//	WB: env WB_GATEWAY_KEY   -> provider_config.json (7863 / workbuddy-*) -> gateway config.json
//	QD: env QD_API_KEY       -> qoder .env.local -> provider_config.json (8790 / providerId qoder)
package keys

import (
	"encoding/json"
	"os"
	"regexp"
	"strings"
)

// Set is the three credentials; empty means "not configured".
type Set struct {
	OC, WB, QD string
}

func env(name string) string { return strings.TrimSpace(os.Getenv(name)) }

type providerRule struct {
	ProviderID string `json:"providerId"`
	Config     struct {
		Access struct {
			APIKey string `json:"apiKey"`
		} `json:"access"`
		API struct {
			BaseURL string `json:"baseUrl"`
		} `json:"api"`
	} `json:"config"`
}

type providerFile struct {
	Config struct {
		ProviderConfigRules struct {
			ProviderRules []providerRule `json:"providerRules"`
		} `json:"providerConfigRules"`
	} `json:"config"`
}

func readProviderRules(path string) []providerRule {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var f providerFile
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil
	}
	return f.Config.ProviderConfigRules.ProviderRules
}

func find(ruleSet []providerRule, base *regexp.Regexp, id *regexp.Regexp) string {
	for _, r := range ruleSet {
		baseOK := base != nil && base.MatchString(r.Config.API.BaseURL)
		idOK := id != nil && id.MatchString(r.ProviderID)
		if (baseOK || idOK) && r.Config.Access.APIKey != "" {
			return r.Config.Access.APIKey
		}
	}
	return ""
}

func readEnvFile(path string) map[string]string {
	out := map[string]string{}
	raw, err := os.ReadFile(path)
	if err != nil {
		return out
	}
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(strings.TrimPrefix(line, "\ufeff"))
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		i := strings.Index(line, "=")
		out[strings.TrimSpace(line[:i])] = strings.Trim(strings.TrimSpace(line[i+1:]), `"'`)
	}
	return out
}

func readGatewayKey(path string) string {
	raw, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	var v struct {
		APIKey string `json:"api_key"`
	}
	if err := json.Unmarshal(raw, &v); err != nil {
		return ""
	}
	return v.APIKey
}

var (
	reOCBase = regexp.MustCompile(`(?i)opencode\.ai`)
	reOCID   = regexp.MustCompile(`^opencode-go`)
	reWBBase = regexp.MustCompile(`(?i)(127\.0\.0\.1|localhost):7863`)
	reWBID   = regexp.MustCompile(`^workbuddy-`)
	reQDBase = regexp.MustCompile(`(?i)(127\.0\.0\.1|localhost):8790`)
	reQDID   = regexp.MustCompile(`^qoder$`)
)

// Load resolves all three, falling back to the files the repo already keeps.
func Load(providerConfig, wbGatewayConfig, qoderEnvFile string) Set {
	rules := readProviderRules(providerConfig)
	var s Set
	s.OC = env("OPENCODE_GO_KEY")
	s.WB = env("WB_GATEWAY_KEY")
	s.QD = env("QD_API_KEY")
	if s.OC == "" {
		s.OC = find(rules, reOCBase, reOCID)
	}
	if s.WB == "" {
		s.WB = find(rules, reWBBase, reWBID)
	}
	if s.WB == "" {
		s.WB = readGatewayKey(wbGatewayConfig)
	}
	if s.QD == "" {
		if v := readEnvFile(qoderEnvFile)["QD_API_KEY"]; v != "" {
			s.QD = v
		}
	}
	if s.QD == "" {
		s.QD = find(rules, reQDBase, reQDID)
	}
	return s
}

// For returns the key for a channel name (OC / WB / QD).
func (s Set) For(channel string) string {
	switch channel {
	case "OC":
		return s.OC
	case "WB":
		return s.WB
	case "QD":
		return s.QD
	}
	return ""
}
