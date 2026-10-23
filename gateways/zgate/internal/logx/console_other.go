//go:build !windows

package logx

import "io"

// ConsoleWriter returns nil on non-Windows builds: stdout is already visible.
func ConsoleWriter() io.Writer { return nil }
