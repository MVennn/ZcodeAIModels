// Package logx is a tiny size-rotating logger used for zgate's own output.
// Children get their own stdout/stderr files wired up by the supervisor.
package logx

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// Logger writes lines to a file (and to the console when one is attached).
type Logger struct {
	mu      sync.Mutex
	file    *os.File
	path    string
	maxSize int64
	written int64
	console io.Writer
}

// Open creates the log directory if needed and rotates an oversized file to .1.
func Open(dir, name string, maxMB int) (*Logger, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, name)
	max := int64(maxMB) * 1024 * 1024
	if stat, err := os.Stat(path); err == nil && max > 0 && stat.Size() > max {
		_ = os.Remove(path + ".1")
		_ = os.Rename(path, path+".1")
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, err
	}
	var written int64
	if stat, err := f.Stat(); err == nil {
		written = stat.Size()
	}
	return &Logger{file: f, path: path, maxSize: max, written: written, console: ConsoleWriter()}, nil
}

// Path is the file being written.
func (l *Logger) Path() string { return l.path }

// Dir returns the directory the log lives in.
func (l *Logger) Dir() string { return filepath.Dir(l.path) }

func (l *Logger) write(level, msg string) {
	line := fmt.Sprintf("%s %-5s %s\n", time.Now().Format("2006-01-02 15:04:05"), level, msg)
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file != nil {
		n, _ := l.file.WriteString(line)
		l.written += int64(n)
		if l.maxSize > 0 && l.written >= l.maxSize {
			l.rotateLocked()
		}
	}
	if l.console != nil {
		_, _ = io.WriteString(l.console, line)
	}
}

// Infof logs an informational line.
func (l *Logger) Infof(format string, args ...any) { l.write("INFO", fmt.Sprintf(format, args...)) }

// Warnf logs a warning.
func (l *Logger) Warnf(format string, args ...any) { l.write("WARN", fmt.Sprintf(format, args...)) }

// Errorf logs an error.
func (l *Logger) Errorf(format string, args ...any) { l.write("ERROR", fmt.Sprintf(format, args...)) }

// rotateLocked moves the current file to .1 and reopens a fresh one. A zgate
// process runs for days, so rotation has to happen while writing, not only at
// open time.
func (l *Logger) rotateLocked() {
	_ = l.file.Close()
	_ = os.Remove(l.path + ".1")
	if err := os.Rename(l.path, l.path+".1"); err != nil {
		// Another process may hold the file; keep appending instead of losing logs.
		if f, reopenErr := os.OpenFile(l.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644); reopenErr == nil {
			l.file = f
		}
		return
	}
	f, err := os.OpenFile(l.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		l.file = nil
		return
	}
	l.file = f
	l.written = 0
}

// Close flushes and closes the file.
func (l *Logger) Close() {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file != nil {
		_ = l.file.Close()
		l.file = nil
	}
}
