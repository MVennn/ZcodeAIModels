//go:build windows

package logx

import (
	"io"
	"os"
)

// ConsoleWriter returns CONOUT$ when zgate is attached to a console.
func ConsoleWriter() io.Writer {
	f, err := os.OpenFile("CONOUT$", os.O_WRONLY, 0)
	if err != nil {
		return nil
	}
	return f
}
