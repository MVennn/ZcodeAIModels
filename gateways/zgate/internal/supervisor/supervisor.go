// Package supervisor keeps the local upstream processes alive.
//
// Policies:
//
//	always    keep it running
//	ondemand  start on first request, stop after idleSeconds without traffic
//
// On top of the policy a child may declare daily windows ("08:58-09:15"). Inside
// a window it is treated as always: sign-in slots need the upstream awake even
// when nobody is chatting. Outside every window it falls back to its policy.
//
// Every child runs in its own Job Object, so a zgate crash cannot leave an
// orphan holding 7863 or 8790.
package supervisor

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"zgate/internal/config"
	"zgate/internal/logx"
	"zgate/internal/winproc"
)

type window struct {
	start int // minutes since midnight
	end   int
}

type kid struct {
	name      string
	cfg       config.Child
	windows   []window
	proc      *winproc.Process
	ready     bool
	starting  bool
	stopping  bool
	external  bool
	waiters   []chan error
	lastUsed  time.Time
	lastErr   string
	nextTry   time.Time
	failCount int
	outFile   *os.File
	errFile   *os.File
}

// Supervisor owns all children.
type Supervisor struct {
	logDir string
	log    *logx.Logger
	client *http.Client
	mu     sync.Mutex
	kids   map[string]*kid
	stopCh chan struct{}
	doneCh chan struct{}
}

// New builds a supervisor; call Start to launch it.
func New(cfg map[string]config.Child, logDir string, log *logx.Logger) *Supervisor {
	kids := make(map[string]*kid, len(cfg))
	for name, child := range cfg {
		normalize(&child)
		kids[name] = &kid{
			name:     name,
			cfg:      child,
			windows:  parseWindows(child.Windows),
			lastUsed: time.Now(),
		}
	}
	return &Supervisor{
		logDir: logDir,
		log:    log,
		client: &http.Client{Timeout: 3 * time.Second},
		kids:   kids,
		stopCh: make(chan struct{}),
		doneCh: make(chan struct{}),
	}
}

func normalize(child *config.Child) {
	if child.Policy != "always" && child.Policy != "ondemand" {
		child.Policy = "ondemand"
	}
	if child.IdleSeconds <= 0 {
		child.IdleSeconds = 300
	}
	if child.StartTimeoutSeconds <= 0 {
		child.StartTimeoutSeconds = 25
	}
}

// Start brings up children that are always-on (or inside a window) and begins
// the monitor loop. Everything else waits for its first request.
func (s *Supervisor) Start() {
	now := time.Now()
	s.mu.Lock()
	var boot []string
	for name, k := range s.kids {
		if k.cfg.Policy == "always" || inAnyWindow(k.windows, now) {
			boot = append(boot, name)
		}
	}
	s.mu.Unlock()
	for _, name := range boot {
		if err := s.Ensure(name); err != nil {
			s.log.Warnf("子进程 %s 启动失败: %v", name, err)
		}
	}
	go s.loop()
}

// Stop terminates every child and stops the monitor.
func (s *Supervisor) Stop() {
	close(s.stopCh)
	<-s.doneCh
	s.mu.Lock()
	names := make([]string, 0, len(s.kids))
	for name := range s.kids {
		names = append(names, name)
	}
	s.mu.Unlock()
	for _, name := range names {
		s.stopChild(name, "退出")
	}
}

// Ensure makes sure one child is up and marks it used.
//
// An "external" instance (something already listening on the child port when
// zgate started) is verified against its health URL on every call, so killing it
// from outside is noticed instead of being trusted forever.
func (s *Supervisor) Ensure(name string) error {
	for {
		s.mu.Lock()
		k, ok := s.kids[name]
		if !ok {
			s.mu.Unlock()
			return nil
		}
		k.lastUsed = time.Now()
		if k.proc != nil && k.ready {
			s.mu.Unlock()
			return nil
		}
		if k.starting {
			ch := make(chan error, 1)
			k.waiters = append(k.waiters, ch)
			s.mu.Unlock()
			return <-ch
		}
		if k.external {
			health := k.cfg.Health
			s.mu.Unlock()
			if s.healthy(health) {
				return nil
			}
			s.mu.Lock()
			k = s.kids[name]
			k.external = false
			k.ready = false
			k.lastErr = "外部实例已消失"
			s.mu.Unlock()
			continue
		}
		k.starting = true
		s.mu.Unlock()

		err := s.startChild(k)

		s.mu.Lock()
		k.starting = false
		if err != nil {
			k.lastErr = err.Error()
			k.ready = false
		} else {
			k.ready = true
			k.lastErr = ""
			k.failCount = 0
			k.nextTry = time.Time{}
		}
		waiters := k.waiters
		k.waiters = nil
		for _, ch := range waiters {
			ch <- err
		}
		s.mu.Unlock()
		return err
	}
}

// Touch marks a channel as used without forcing a start.
func (s *Supervisor) Touch(name string) {
	s.mu.Lock()
	if k, ok := s.kids[name]; ok {
		k.lastUsed = time.Now()
	}
	s.mu.Unlock()
}

func (s *Supervisor) startChild(k *kid) error {
	if winproc.PortBusy(k.cfg.Port) {
		if s.healthy(k.cfg.Health) {
			s.mu.Lock()
			k.external = true
			k.ready = true
			k.lastErr = ""
			s.mu.Unlock()
			s.log.Infof("子进程 %s：端口 %d 已有健康实例，接管（不重复启动）", k.name, k.cfg.Port)
			return nil
		}
		return fmt.Errorf("端口 %d 被占用且健康检查不通", k.cfg.Port)
	}

	if k.cfg.Exe == "" {
		return fmt.Errorf("未配置可执行文件")
	}
	outPath := filepath.Join(s.logDir, k.name+".stdout.log")
	errPath := filepath.Join(s.logDir, k.name+".stderr.log")
	outFile, err := os.OpenFile(outPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	errFile, err := os.OpenFile(errPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		_ = outFile.Close()
		return err
	}

	s.log.Infof("启动子进程 %s: %s %v (cwd=%s)", k.name, k.cfg.Exe, k.cfg.Args, k.cfg.Cwd)
	proc, err := winproc.Start(k.cfg.Exe, k.cfg.Args, k.cfg.Cwd, outFile, errFile)
	if err != nil {
		_ = outFile.Close()
		_ = errFile.Close()
		return fmt.Errorf("启动失败: %w", err)
	}

	deadline := time.Now().Add(time.Duration(k.cfg.StartTimeoutSeconds) * time.Second)
	for time.Now().Before(deadline) {
		select {
		case <-proc.Done():
			proc.Release()
			_ = outFile.Close()
			_ = errFile.Close()
			return fmt.Errorf("启动后立即退出（日志 %s）", errPath)
		case <-time.After(200 * time.Millisecond):
			if s.healthy(k.cfg.Health) {
				s.mu.Lock()
				k.proc = proc
				k.outFile = outFile
				k.errFile = errFile
				k.external = false
				s.mu.Unlock()
				s.log.Infof("子进程 %s 就绪 pid=%d", k.name, proc.Pid())
				go s.watch(k.name, proc)
				return nil
			}
		}
	}

	_ = proc.Kill()
	select {
	case <-proc.Done():
	case <-time.After(3 * time.Second):
	}
	proc.Release()
	_ = outFile.Close()
	_ = errFile.Close()
	return fmt.Errorf("健康检查超时（%ds，%s）", k.cfg.StartTimeoutSeconds, k.cfg.Health)
}

// watch clears the state as soon as the child exits on its own.
func (s *Supervisor) watch(name string, proc *winproc.Process) {
	<-proc.Done()
	proc.Release()
	s.mu.Lock()
	defer s.mu.Unlock()
	k, ok := s.kids[name]
	if !ok || k.proc != proc {
		return
	}
	k.proc = nil
	k.ready = false
	if k.outFile != nil {
		_ = k.outFile.Close()
		k.outFile = nil
	}
	if k.errFile != nil {
		_ = k.errFile.Close()
		k.errFile = nil
	}
	if k.stopping {
		k.stopping = false
		k.lastErr = ""
		s.log.Infof("子进程 %s 已停止", name)
		return
	}
	k.lastErr = fmt.Sprintf("进程退出: %v", proc.Err())
	s.log.Warnf("子进程 %s 已退出: %v", name, proc.Err())
}

func (s *Supervisor) stopChild(name, reason string) {
	s.mu.Lock()
	k, ok := s.kids[name]
	if !ok {
		s.mu.Unlock()
		return
	}
	k.stopping = true
	proc := k.proc
	s.mu.Unlock()
	if proc == nil {
		s.mu.Lock()
		k.stopping = false
		s.mu.Unlock()
		return
	}
	s.log.Infof("停止子进程 %s（%s）", name, reason)
	_ = proc.Kill()
	select {
	case <-proc.Done():
	case <-time.After(5 * time.Second):
	}
	proc.Release()
	s.mu.Lock()
	if k := s.kids[name]; k != nil && k.proc == proc {
		k.proc = nil
		k.ready = false
	}
	s.mu.Unlock()
}

func (s *Supervisor) loop() {
	defer close(s.doneCh)
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-s.stopCh:
			return
		case <-ticker.C:
			s.tick()
		}
	}
}

type action struct {
	name   string
	start  bool
	stop   bool
	verify string // health URL for an adopted instance
}

func (s *Supervisor) tick() {
	now := time.Now()
	s.mu.Lock()
	var actions []action
	for name, k := range s.kids {
		if k.starting {
			continue
		}
		if k.external {
			// Adopted instances have no handle to watch; poll their health.
			actions = append(actions, action{name: name, verify: k.cfg.Health})
			continue
		}
		forced := k.cfg.Policy == "always" || inAnyWindow(k.windows, now)
		if forced {
			if k.proc == nil && !now.Before(k.nextTry) {
				actions = append(actions, action{name: name, start: true})
			}
			continue
		}
		if k.proc != nil && now.Sub(k.lastUsed) > time.Duration(k.cfg.IdleSeconds)*time.Second {
			actions = append(actions, action{name: name, stop: true})
		}
	}
	s.mu.Unlock()

	for _, a := range actions {
		switch {
		case a.verify != "":
			if s.healthy(a.verify) {
				continue
			}
			s.mu.Lock()
			if k := s.kids[a.name]; k != nil && k.external {
				k.external = false
				k.ready = false
				k.lastErr = "外部实例已消失"
				s.log.Warnf("接管的子进程 %s 健康检查失败，转为由 zgate 管理", a.name)
			}
			s.mu.Unlock()
		case a.stop:
			s.stopChild(a.name, "空闲回收")
			s.mu.Lock()
			if k := s.kids[a.name]; k != nil {
				k.lastUsed = time.Now()
			}
			s.mu.Unlock()
		case a.start:
			if err := s.Ensure(a.name); err != nil {
				s.mu.Lock()
				if k := s.kids[a.name]; k != nil {
					k.failCount++
					k.nextTry = time.Now().Add(backoff(k.failCount))
				}
				s.mu.Unlock()
				s.log.Warnf("子进程 %s 自动重启失败（第 %d 次）: %v", a.name, s.failCountOf(a.name), err)
			}
		}
	}
}

// backoff is 1s, 2s, 4s, ... capped at 60s.
func backoff(fails int) time.Duration {
	if fails <= 0 {
		return 0
	}
	if fails > 7 {
		fails = 7
	}
	d := time.Second << uint(fails-1)
	if d > time.Minute {
		d = time.Minute
	}
	return d
}

func (s *Supervisor) failCountOf(name string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	if k := s.kids[name]; k != nil {
		return k.failCount
	}
	return 0
}

func (s *Supervisor) healthy(url string) bool {
	if url == "" {
		return true
	}
	resp, err := s.client.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	return resp.StatusCode < 500
}

// ApplyConfig updates policies, idle thresholds and windows of existing children.
// New children need a restart (the executable and port layout is boot-time only).
func (s *Supervisor) ApplyConfig(cfg map[string]config.Child) (applied, unknownKeep, added []string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for name, child := range cfg {
		normalize(&child)
		k, ok := s.kids[name]
		if !ok {
			added = append(added, name)
			continue
		}
		windows := parseWindows(child.Windows)
		if len(windows) != len(child.Windows) {
			s.log.Warnf("子进程 %s 有无法解析的 windows 条目，已忽略", name)
		}
		k.cfg = child
		k.windows = windows
		applied = append(applied, name)
	}
	for name := range s.kids {
		if _, ok := cfg[name]; !ok {
			unknownKeep = append(unknownKeep, name)
		}
	}
	return applied, unknownKeep, added
}

// States is the /health view of every child.
func (s *Supervisor) States() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now()
	out := make(map[string]any, len(s.kids))
	for name, k := range s.kids {
		state := "stopped"
		switch {
		case k.starting:
			state = "starting"
		case k.proc != nil && k.ready:
			state = "running"
		case k.external && k.ready:
			state = "external"
		case k.lastErr != "":
			state = "error"
		}
		entry := map[string]any{
			"policy":     k.cfg.Policy,
			"state":      state,
			"port":       k.cfg.Port,
			"idle_s":     int(now.Sub(k.lastUsed).Seconds()),
			"in_window":  inAnyWindow(k.windows, now),
			"windows":    k.cfg.Windows,
			"last_error": k.lastErr,
		}
		if k.proc != nil {
			entry["pid"] = k.proc.Pid()
		}
		out[name] = entry
	}
	return out
}

// parseWindows accepts "HH:MM-HH:MM"; invalid entries are dropped.
func parseWindows(specs []string) []window {
	out := make([]window, 0, len(specs))
	for _, spec := range specs {
		parts := strings.SplitN(strings.TrimSpace(spec), "-", 2)
		if len(parts) != 2 {
			continue
		}
		start, ok1 := parseClock(parts[0])
		end, ok2 := parseClock(parts[1])
		if !ok1 || !ok2 || start == end {
			continue
		}
		out = append(out, window{start: start, end: end})
	}
	return out
}

func parseClock(s string) (int, bool) {
	parts := strings.SplitN(strings.TrimSpace(s), ":", 2)
	if len(parts) != 2 {
		return 0, false
	}
	h, err1 := strconv.Atoi(parts[0])
	m, err2 := strconv.Atoi(parts[1])
	if err1 != nil || err2 != nil || h < 0 || h > 23 || m < 0 || m > 59 {
		return 0, false
	}
	return h*60 + m, true
}

func inAnyWindow(windows []window, t time.Time) bool {
	if len(windows) == 0 {
		return false
	}
	minutes := t.Hour()*60 + t.Minute()
	for _, w := range windows {
		if w.start < w.end {
			if minutes >= w.start && minutes < w.end {
				return true
			}
			continue
		}
		// Wraps midnight, e.g. 23:00-08:00.
		if minutes >= w.start || minutes < w.end {
			return true
		}
	}
	return false
}
