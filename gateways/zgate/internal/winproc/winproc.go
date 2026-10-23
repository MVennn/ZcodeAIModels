// Package winproc starts and stops child processes.
//
// On Windows every child is put into its own Job Object with
// JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, so closing zgate (or crashing it) takes the
// children down with it instead of leaving orphans holding 7863 / 8790.
package winproc

import (
	"io"
	"os/exec"
	"strconv"
	"sync"
)

func listenAddr(port int) string { return "127.0.0.1:" + strconv.Itoa(port) }

// Process is a supervised child.
type Process struct {
	cmd      *exec.Cmd
	job      uintptr
	releaseO sync.Once
	done     chan struct{}
	err      error
}

// Start launches exe in dir with args, wiring stdout/stderr to out/errOut.
func Start(exe string, args []string, dir string, out, errOut io.Writer) (*Process, error) {
	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	cmd.Stdout = out
	cmd.Stderr = errOut
	p := &Process{cmd: cmd, done: make(chan struct{})}
	if err := p.start(); err != nil {
		return nil, err
	}
	go func() {
		p.err = cmd.Wait()
		close(p.done)
	}()
	return p, nil
}

// Pid is the child's process id (0 before start).
func (p *Process) Pid() int {
	if p == nil || p.cmd.Process == nil {
		return 0
	}
	return p.cmd.Process.Pid
}

// Done is closed when the child exits.
func (p *Process) Done() <-chan struct{} { return p.done }

// Err is the exit error, valid after Done is closed.
func (p *Process) Err() error { return p.err }

// Kill terminates the child and everything it spawned.
func (p *Process) Kill() error { return p.kill() }

// Release drops OS handles; safe to call more than once and from several
// goroutines (the monitor and an explicit stop can both get here).
func (p *Process) Release() {
	p.releaseO.Do(func() {
		p.release()
	})
}
