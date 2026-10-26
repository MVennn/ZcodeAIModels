//go:build windows

package winproc

import (
	"os"
	"syscall"
)

const (
	attachParentProcess = ^uintptr(0) // (DWORD)-1

	stdOutputHandle = ^uintptr(10) // (DWORD)-11, STD_OUTPUT_HANDLE

	fileTypeUnknown = 0 // invalid handle
	fileTypeDisk    = 1 // redirection to a file
	fileTypeChar    = 2 // console screen buffer
	fileTypePipe    = 3 // mintty / CI / child_process
)

var (
	procAttachConsole = kernel32.NewProc("AttachConsole")
	procGetStdHandle  = kernel32.NewProc("GetStdHandle")
	procGetFileType   = kernel32.NewProc("GetFileType")
)

// AttachParentConsole rebinds stdout/stderr to the terminal that launched us.
//
// zgate is built as a GUI-subsystem binary so autostart never flashes a console
// window. Inherited handles that already work — pipes (mintty, CI, scripts) and
// file redirections — must be left alone, or output would be swallowed by a
// hidden conhost and `zgate status > file` would be empty. Only when stdout is
// unusable or a raw console handle do we attach to the parent's console, so
// running from cmd / PowerShell still prints.
func AttachParentConsole() bool {
	if keepInheritedStdio() {
		return true
	}
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

func keepInheritedStdio() bool {
	out, _, _ := procGetStdHandle.Call(stdOutputHandle)
	if out == 0 {
		return false
	}
	ft, _, _ := procGetFileType.Call(out)
	switch uintptr(ft) {
	case fileTypeDisk, fileTypePipe:
		return true
	default: // unknown (invalid) or char (console): try attaching instead
		return false
	}
}

var _ = syscall.Handle(0)
