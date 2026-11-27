// Standalone entrypoint for the scratch relay image. No shell or credentials.
package main

import (
	"os"
	"syscall"
	"time"
)

func main() {
	for {
		f, err := os.Lstat("/run/vpn-owner/cluster")
		if err == nil && f.Mode().IsRegular() {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	const xray = "/usr/local/bin/xray"
	if err := syscall.Exec(xray, append([]string{xray}, os.Args[1:]...), os.Environ()); err != nil {
		os.Exit(126)
	}
}
