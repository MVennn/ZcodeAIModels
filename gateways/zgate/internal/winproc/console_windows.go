//go:build windows

package winproc

import (
	"os"
	"syscall"
)

const attachParentProcess = ^uintptr(0) // (DWORD)-1

var (
	procAttachConsole = kernel32.NewProc("AttachConsole")
)

// AttachParentConsole rebinds stdout/stderr to the terminal that launched us.
//
// zgate is built as a GUI-subsystem binary so a scheduled task never flashes a
// console window. When the same binary is run from a shell, it re-attaches to
// that shell's console so `zgate status` still prints.
func AttachParentConsole() bool {
	ok, _, _ := procAttachConsole.Call(attachParentProcess)
	if ok == 0 {
		return false
	}
	if out, err := os.OpenFile("CONOUT$", os.O_WRONLY, 0); err == nil {
		os.Stdout = out
		os.Stderr = out
	}
	return true
}

var _ = syscall.Handle(0)
