//go:build !windows

package winproc

import (
	"net"
	"os/exec"
	"time"
)

func (p *Process) start() error {
	p.cmd.SysProcAttr = nil
	return p.cmd.Start()
}

func (p *Process) kill() error {
	if p == nil || p.cmd.Process == nil {
		return nil
	}
	return p.cmd.Process.Kill()
}

func (p *Process) release() {}

// PortBusy reports whether something accepts connections on the loopback port.
func PortBusy(port int) bool {
	conn, err := net.DialTimeout("tcp", listenAddr(port), 300*time.Millisecond)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

var _ = exec.Command
