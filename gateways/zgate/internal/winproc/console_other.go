//go:build !windows

package winproc

// AttachParentConsole is a no-op outside Windows.
func AttachParentConsole() bool { return true }
