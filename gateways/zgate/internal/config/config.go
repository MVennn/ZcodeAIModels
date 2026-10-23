// Package config loads zgate.json and applies defaults, env overrides and
// path expansion. Nothing here knows about HTTP or child processes.
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// Log says where zgate and its children write.
type Log struct {
	Dir   string `json:"dir"`
	File  string `json:"file"`
	MaxMB int    `json:"maxMB"`
}

// Upstream is one channel: where it lives and which child (if any) serves it.
type Upstream struct {
	Base   string `json:"base"`
	Child  string `json:"child"`
	KeyEnv string `json:"keyEnv"`
}

// Child is a local upstream process zgate supervises.
type Child struct {
	Policy              string   `json:"policy"` // always | ondemand
	IdleSeconds         int      `json:"idleSeconds"`
	Exe                 string   `json:"exe"`
	Args                []string `json:"args"`
	Cwd                 string   `json:"cwd"`
	Port                int      `json:"port"`
	Health              string   `json:"health"`
	StartTimeoutSeconds int      `json:"startTimeoutSeconds"`
	// Windows are local-time "HH:MM-HH:MM" ranges during which the child is
	// treated as policy=always (sign-in / keepalive slots). Empty means never.
	Windows []string `json:"windows"`
}

// Config is the whole file.
type Config struct {
	Listen          string              `json:"listen"`
	AliasMap        string              `json:"aliasMap"`
	ProviderConfig  string              `json:"providerConfig"`
	WBGatewayConfig string              `json:"wbGatewayConfig"`
	QoderEnvFile    string              `json:"qoderEnvFile"`
	Session         string              `json:"session"`
	Log             Log                 `json:"log"`
	Upstreams       map[string]Upstream `json:"upstreams"`
	Children        map[string]Child    `json:"children"`

	Path string `json:"-"`
	Dir  string `json:"-"`
}

// Load reads path (or the default next to the binary) and normalises it.
func Load(path string) (*Config, error) {
	if path == "" {
		path = os.Getenv("ZGATE_CONFIG")
	}
	if path == "" {
		exe, err := os.Executable()
		if err == nil {
			path = filepath.Join(filepath.Dir(exe), "zgate.json")
		}
	}
	if path == "" {
		path = "zgate.json"
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读不到配置 %s: %w", path, err)
	}
	var cfg Config
	if err := json.Unmarshal(raw, &cfg); err != nil {
		return nil, fmt.Errorf("配置不是合法 JSON（%s）: %w", path, err)
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		abs = path
	}
	cfg.Path = abs
	cfg.Dir = filepath.Dir(abs)
	cfg.applyDefaults()
	if err := cfg.resolvePaths(); err != nil {
		return nil, err
	}
	return &cfg, nil
}

func (c *Config) applyDefaults() {
	if c.Listen == "" {
		c.Listen = "127.0.0.1:7871"
	}
	if v := os.Getenv("ZGATE_LISTEN"); v != "" {
		c.Listen = v
	}
	if c.AliasMap == "" {
		c.AliasMap = "~/.zcode/v2/model-alias-map.json"
	}
	if v := os.Getenv("UNIFIED_MODEL_MAP"); v != "" {
		c.AliasMap = v
	}
	if c.ProviderConfig == "" {
		c.ProviderConfig = "~/.zcode/v2/provider_config.json"
	}
	if v := os.Getenv("ZCODE_PERSONAL_PROVIDER_CONFIG_FILE"); v != "" {
		c.ProviderConfig = v
	}
	if c.WBGatewayConfig == "" {
		c.WBGatewayConfig = "../upstream/workbuddy/config.json"
	}
	if c.QoderEnvFile == "" {
		c.QoderEnvFile = "../../providers/qoder/.env.local"
	}
	if c.Session == "" {
		c.Session = os.Getenv("OPENCODE_SESSION")
	}
	if c.Session == "" {
		c.Session = "unified-router"
	}
	if c.Log.Dir == "" {
		c.Log.Dir = filepath.Join(os.Getenv("LOCALAPPDATA"), "ZCodeGateway")
	}
	if c.Log.File == "" {
		c.Log.File = "zgate.log"
	}
	if c.Log.MaxMB <= 0 {
		c.Log.MaxMB = 5
	}
	if c.Upstreams == nil {
		c.Upstreams = map[string]Upstream{}
	}
	if _, ok := c.Upstreams["OC"]; !ok {
		c.Upstreams["OC"] = Upstream{Base: "https://opencode.ai/zen/go/v1", KeyEnv: "OPENCODE_GO_KEY"}
	}
	if u, ok := c.Upstreams["WB"]; !ok {
		c.Upstreams["WB"] = Upstream{Base: "http://127.0.0.1:7863/v1", Child: "workbuddy", KeyEnv: "WB_GATEWAY_KEY"}
	} else if u.KeyEnv == "" {
		u.KeyEnv = "WB_GATEWAY_KEY"
		c.Upstreams["WB"] = u
	}
	if u, ok := c.Upstreams["QD"]; !ok {
		c.Upstreams["QD"] = Upstream{Base: "http://127.0.0.1:8790/v1", Child: "qoder", KeyEnv: "QD_API_KEY"}
	} else if u.KeyEnv == "" {
		u.KeyEnv = "QD_API_KEY"
		c.Upstreams["QD"] = u
	}
	for name, child := range c.Children {
		if child.Policy == "" {
			child.Policy = "ondemand"
		}
		if child.Policy != "always" && child.Policy != "ondemand" {
			child.Policy = "ondemand"
		}
		if child.IdleSeconds <= 0 {
			child.IdleSeconds = 900
		}
		if child.StartTimeoutSeconds <= 0 {
			child.StartTimeoutSeconds = 25
		}
		c.Children[name] = child
	}
}

func (c *Config) resolvePaths() error {
	for name, u := range c.Upstreams {
		u.Base = strings.TrimRight(expandEnv(u.Base), "/")
		c.Upstreams[name] = u
	}
	for name, child := range c.Children {
		child.Exe = c.resolveExe(child.Exe)
		child.Cwd = c.resolve(child.Cwd)
		args := make([]string, len(child.Args))
		for i, a := range child.Args {
			args[i] = c.resolveArg(a)
		}
		child.Args = args
		c.Children[name] = child
	}
	c.AliasMap = c.resolve(c.AliasMap)
	c.ProviderConfig = c.resolve(c.ProviderConfig)
	c.WBGatewayConfig = c.resolve(c.WBGatewayConfig)
	c.QoderEnvFile = c.resolve(c.QoderEnvFile)
	c.Log.Dir = c.resolve(c.Log.Dir)
	return nil
}

func (c *Config) resolve(p string) string {
	if p == "" {
		return ""
	}
	p = expandEnv(p)
	if strings.HasPrefix(p, "~") {
		if home, err := os.UserHomeDir(); err == nil {
			p = filepath.Join(home, strings.TrimPrefix(strings.TrimPrefix(p, "~"), string(os.PathSeparator)))
		}
	}
	if !filepath.IsAbs(p) {
		p = filepath.Join(c.Dir, p)
	}
	return filepath.Clean(p)
}

// resolveExe resolves a path, but leaves a bare command name ("python") alone so
// the OS keeps doing PATH lookup for it.
func (c *Config) resolveExe(p string) string {
	p = expandEnv(p)
	if p == "" {
		return ""
	}
	if filepath.Base(p) == p && !strings.HasPrefix(p, "~") {
		return p
	}
	return c.resolve(p)
}

// resolveArg resolves path-looking arguments and leaves flags alone.
//
// Flags are skipped (leading "-", and also Windows-style "/c"), and so are bare
// words: a path argument must be absolute, start with "." or contain a
// separator. That keeps "../upstream/qoder/qoder_proxy.py" working without
// turning cmd's "/c" into a drive-relative path.
func (c *Config) resolveArg(a string) string {
	a = expandEnv(a)
	if a == "" || strings.HasPrefix(a, "-") || strings.HasPrefix(a, "/") || strings.ContainsAny(a, " 	") {
		return a
	}
	if filepath.IsAbs(a) || strings.HasPrefix(a, ".") || strings.ContainsAny(a, "/\\") {
		return c.resolve(a)
	}
	return a
}

var rePercentVar = regexp.MustCompile(`%([A-Za-z_][A-Za-z0-9_]*)%`)

func expandEnv(s string) string {
	if strings.Contains(s, "%") {
		s = rePercentVar.ReplaceAllStringFunc(s, func(m string) string {
			name := strings.Trim(m, "%")
			if v, ok := os.LookupEnv(name); ok {
				return v
			}
			for _, kv := range os.Environ() {
				if i := strings.IndexByte(kv, '='); i > 0 && strings.EqualFold(kv[:i], name) {
					return kv[i+1:]
				}
			}
			return ""
		})
	}
	return os.Expand(s, func(key string) string {
		if v, ok := os.LookupEnv(key); ok {
			return v
		}
		// Windows keeps these upper-cased; accept the case-insensitive spelling too.
		for _, kv := range os.Environ() {
			if i := strings.IndexByte(kv, '='); i > 0 && strings.EqualFold(kv[:i], key) {
				return kv[i+1:]
			}
		}
		return ""
	})
}
