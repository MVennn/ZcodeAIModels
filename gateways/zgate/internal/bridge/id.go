package bridge

import (
	"crypto/rand"
	"encoding/hex"
)

func randomHex(n int) string {
	buf := make([]byte, n)
	if _, err := rand.Read(buf); err != nil {
		for i := range buf {
			buf[i] = byte(i * 7)
		}
	}
	return hex.EncodeToString(buf)
}

// shortID mirrors randomUUID().slice(0, 8) from the JS bridge.
func shortID() string { return randomHex(4) }

// longID fills the chatcmpl- suffix.
func longID() string { return randomHex(16) }
