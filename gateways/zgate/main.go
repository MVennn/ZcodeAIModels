// zgate is the single entry point for ZCode's four chat providers.
//
//	zgate serve       listen on 127.0.0.1:7871: alias routing, protocol bridge,
//	                  child process supervision
//	zgate status      one-shot report (works whether or not serve is running)
//	zgate install     register a logon scheduled task
//	zgate uninstall   remove it
//
// The port, paths and child commands live in zgate.json next to the binary.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	"zgate/internal/alias"
	"zgate/internal/config"
	"zgate/internal/keys"
	"zgate/internal/logx"
	"zgate/internal/router"
	"zgate/internal/supervisor"
	"zgate/internal/winproc"
)

const version = "0.3.0"

const taskName = "ZcodeAIModels-zgate"

func main() {
	winproc.AttachParentConsole()

	cmd := "serve"
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}
	switch cmd {
	case "serve":
		if err := serve(); err != nil {
			fmt.Fprintln(os.Stderr, "zgate serve:", err)
			os.Exit(1)
		}
	case "status":
		if err := status(); err != nil {
			fmt.Fprintln(os.Stderr, "zgate status:", err)
			os.Exit(1)
		}
	case "reload":
		if err := reload(); err != nil {
			fmt.Fprintln(os.Stderr, "zgate reload:", err)
			os.Exit(1)
		}
	case "install":
		if err := install(); err != nil {
			fmt.Fprintln(os.Stderr, "zgate install:", err)
			os.Exit(1)
		}
	case "uninstall":
		if err := uninstall(); err != nil {
			fmt.Fprintln(os.Stderr, "zgate uninstall:", err)
			os.Exit(1)
		}
	case "version", "-v", "--version":
		fmt.Println("zgate", version)
	case "help", "-h", "--help":
		usage()
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Printf(`zgate %s —— ZCode 统一入口（路由 + 协议桥 + 子进程守护）

用法:
  zgate serve        前台运行（计划任务用这个）
  zgate status       打印配置、健康与子进程状态（不碰日志文件）
  zgate reload       让运行中的实例热加载 zgate.json（策略/空闲/窗口）
  zgate install      注册登录自启（启动文件夹快捷方式）
  zgate uninstall    移除该快捷方式
  zgate version      版本

配置文件: zgate.json（默认与可执行文件同目录，可用 ZGATE_CONFIG 指定）
监听地址可用 ZGATE_LISTEN 覆盖，例如 ZGATE_LISTEN=127.0.0.1:7971。
`, version)
}

func loadConfig() (*config.Config, keys.Set, error) {
	cfgPath := ""
	fs := flag.NewFlagSet("zgate", flag.ContinueOnError)
	fs.StringVar(&cfgPath, "config", "", "zgate.json 路径")
	// os.Args[0] is the subcommand here; ignore parse errors so flags after it work.
	_ = fs.Parse(os.Args[2:])

	cfg, err := config.Load(cfgPath)
	if err != nil {
		return nil, keys.Set{}, err
	}
	ks := keys.Load(cfg.ProviderConfig, cfg.WBGatewayConfig, cfg.QoderEnvFile)
	return cfg, ks, nil
}

func serve() error {
	cfg, ks, err := loadConfig()
	if err != nil {
		return err
	}
	log, err := logx.Open(cfg.Log.Dir, cfg.Log.File, cfg.Log.MaxMB)
	if err != nil {
		return err
	}
	defer log.Close()

	am := alias.New(cfg.AliasMap)
	sup := supervisor.New(cfg.Children, log.Dir(), log)
	client := &http.Client{
		Transport: &http.Transport{
			Proxy:                 nil, // same as the old Node router: no env proxy
			DisableCompression:    true,
			ForceAttemptHTTP2:     true,
			MaxIdleConns:          100,
			MaxIdleConnsPerHost:   32,
			IdleConnTimeout:       90 * time.Second,
			// 8s: opencode.ai 经透明代理握手会抖（2026-10-27 实测坏节点下最长
			// 7.7s，再往上就是死路）。15s 会把一次失败拖成 15s 的 502 长尾，
			// 而链式回落只需要尽快拿到「这次不行」的结论。
			TLSHandshakeTimeout:   8 * time.Second,
			ExpectContinueTimeout: time.Second,
			DialContext:           (&net.Dialer{Timeout: 30 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		},
	}

	ln, err := net.Listen("tcp", cfg.Listen)
	if err != nil {
		log.Errorf("监听 %s 失败: %v（是否已有实例在跑？）", cfg.Listen, err)
		return fmt.Errorf("监听 %s 失败: %w", cfg.Listen, err)
	}

	// Boot children in the background: Start() runs the boot list serially and
	// each child can take StartTimeoutSeconds, while the HTTP server should be
	// accepting requests during that window.
	go sup.Start()
	srv := &http.Server{
		Handler:  router.New(cfg, ks, am, sup, client, log).Handler(),
		ErrorLog: nil,
	}

	log.Infof("zgate %s 已启动: http://%s/v1", version, cfg.Listen)
	log.Infof("配置文件 : %s", cfg.Path)
	for _, name := range []string{"OC", "WB", "QD"} {
		u := cfg.Upstreams[name]
		state := "missing"
		if ks.For(name) != "" {
			state = "ok"
		}
		log.Infof("%-11s: %s (key=%s%s)", name, u.Base, state, childSuffix(u.Child))
	}
	if n := am.Count(); n == 0 {
		log.Warnf("alias map 为空或读不到: %s（只有前缀兜底可用）", cfg.AliasMap)
	} else {
		log.Infof("alias map  : %s (%d models)", cfg.AliasMap, n)
	}

	errCh := make(chan error, 1)
	go func() { errCh <- srv.Serve(ln) }()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)

	select {
	case s := <-sig:
		log.Infof("收到 %v，正在退出", s)
	case err := <-errCh:
		if err != nil && err != http.ErrServerClosed {
			sup.Stop()
			return err
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
	sup.Stop()
	log.Infof("已退出")
	return nil
}

func childSuffix(child string) string {
	if child == "" {
		return ""
	}
	return ", child=" + child
}

func status() error {
	cfg, ks, err := loadConfig()
	if err != nil {
		return err
	}

	fmt.Printf("zgate %s\n", version)
	fmt.Printf("配置      : %s\n", cfg.Path)
	fmt.Printf("监听      : http://%s/v1\n", cfg.Listen)
	fmt.Printf("alias map : %s\n", cfg.AliasMap)
	fmt.Printf("日志      : %s\n\n", filepath.Join(cfg.Log.Dir, cfg.Log.File))

	fmt.Println("凭据（只报有无）:")
	for _, name := range []string{"OC", "WB", "QD"} {
		want := ks.For(name) != ""
		fmt.Printf("  %-3s %-8s %s\n", name, yesNo(want), cfg.Upstreams[name].Base)
	}
	fmt.Println()

	body, code := probeHealth(cfg.Listen)
	if body == nil {
		fmt.Printf("服务状态  : 未运行（健康检查不可达，HTTP %d）\n", code)
	} else {
		fmt.Printf("服务状态  : 运行中（HTTP %d）\n", code)
		var health struct {
			Alias struct {
				Models int `json:"models"`
			} `json:"alias"`
			UptimeS  int            `json:"uptime_s"`
			Children map[string]any `json:"children"`
		}
		if err := json.Unmarshal(body, &health); err == nil {
			fmt.Printf("alias     : %d models\n", health.Alias.Models)
			fmt.Printf("运行时长  : %s\n", (time.Duration(health.UptimeS) * time.Second).String())
			if len(health.Children) > 0 {
				fmt.Println("子进程:")
				names := make([]string, 0, len(health.Children))
				for name := range health.Children {
					names = append(names, name)
				}
				sort.Strings(names)
				for _, name := range names {
					entry, _ := health.Children[name].(map[string]any)
					fmt.Printf("  %-9s %-9v pid=%v port=%v 空闲=%vs %v\n",
						name, entry["state"], dash(entry["pid"]), entry["port"], entry["idle_s"], errText(entry["last_error"]))
				}
			}
		}
	}

	// Port-level truth, independent of the HTTP API.
	for name, child := range cfg.Children {
		if child.Port == 0 {
			continue
		}
		free := winproc.PortBusy(child.Port)
		fmt.Printf("端口 %-5d: %-18s %s\n", child.Port, name, map[bool]string{true: "被占用", false: "空闲"}[free])
	}
	return nil
}

func probeHealth(listen string) ([]byte, int) {
	host := listen
	if strings.HasPrefix(host, ":") {
		host = "127.0.0.1" + host
	}
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get("http://" + host + "/health")
	if err != nil {
		return nil, 0
	}
	defer resp.Body.Close()
	buf := make([]byte, 0, 4096)
	tmp := make([]byte, 4096)
	for {
		n, err := resp.Body.Read(tmp)
		buf = append(buf, tmp[:n]...)
		if err != nil || len(buf) > 1<<20 {
			break
		}
	}
	return buf, resp.StatusCode
}

// reload asks the running instance to re-read zgate.json.
func reload() error {
	cfg, _, err := loadConfig()
	if err != nil {
		return err
	}
	host := cfg.Listen
	if strings.HasPrefix(host, ":") {
		host = "127.0.0.1" + host
	}
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Post("http://"+host+"/admin/reload", "application/json", nil)
	if err != nil {
		return fmt.Errorf("连不上 %s（服务没在跑？）: %w", host, err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, raw)
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		fmt.Println(string(raw))
		return nil
	}
	fmt.Printf("已热加载：生效 %v\n", out["applied"])
	if stale, ok := out["stale"].([]any); ok && len(stale) > 0 {
		fmt.Printf("配置里已删除但仍由本进程管理：%v（重启后彻底移除）\n", stale)
	}
	if added, ok := out["added"].([]any); ok && len(added) > 0 {
		fmt.Printf("新增子进程：%v（需要重启 zgate 才会生效）\n", added)
	}
	return nil
}

func startupLinkPath() (string, error) {
	appData := os.Getenv("APPDATA")
	if appData == "" {
		return "", fmt.Errorf("APPDATA 未设置")
	}
	dir := filepath.Join(appData, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return filepath.Join(dir, "ZcodeAIModels zgate.lnk"), nil
}

func install() error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	exe, _ = filepath.Abs(exe)
	workDir := filepath.Dir(exe)
	if _, statErr := os.Stat(filepath.Join(workDir, "zgate.json")); statErr != nil {
		fmt.Fprintf(os.Stderr, "提示: %s 下没有 zgate.json，启动时会失败\n", workDir)
	}
	link, err := startupLinkPath()
	if err != nil {
		return err
	}
	// schtasks ONLOGON needs elevation; a Startup shortcut does not, and it is
	// the mechanism the old PowerShell watchdog already used.
	// PowerShell single-quoted strings escape a quote by doubling it.
	psq := func(p string) string { return strings.ReplaceAll(p, "'", "''") }
	script := fmt.Sprintf(
		"$ws = New-Object -ComObject WScript.Shell; "+
			"$s = $ws.CreateShortcut('%s'); "+
			"$s.TargetPath = '%s'; $s.Arguments = 'serve'; $s.WorkingDirectory = '%s'; "+
			"$s.WindowStyle = 7; $s.Description = 'ZCode 统一入口 (zgate)'; $s.Save()",
		psq(link), psq(exe), psq(workDir))
	out, err := exec.Command("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script).CombinedOutput()
	if err != nil {
		return fmt.Errorf("创建启动快捷方式失败: %v\n%s", err, out)
	}
	fmt.Printf("已注册登录自启: %s（目标: %s serve）\n", link, exe)
	return nil
}

func uninstall() error {
	link, err := startupLinkPath()
	if err != nil {
		return err
	}
	if err := os.Remove(link); err != nil && !os.IsNotExist(err) {
		return err
	}
	fmt.Printf("已移除登录自启: %s\n", link)
	fmt.Println("（正在运行的 zgate 需要手动停止；子进程会随它一起退出）")
	return nil
}

func dash(v any) any {
	if v == nil {
		return "-"
	}
	return v
}

func errText(v any) string {
	s, _ := v.(string)
	if s == "" {
		return ""
	}
	return "错误=" + s
}

func yesNo(v bool) string {
	if v {
		return "有"
	}
	return "缺"
}
