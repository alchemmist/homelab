package main

import (
	"crypto/sha256"
	"encoding/hex"
	"sync"
)

// Identical canonical byte stream, sequential SHA256 chain in its own goroutine.
// Four fixed256KiB buffers overlap hashing with source decoding/OTLP assembly;
// no per-sample allocation, changed digest scheme or unbounded queue.
type canonicalStream struct {
	free    chan []byte
	jobs    chan []byte
	current []byte
	wg      sync.WaitGroup
	once    sync.Once
	result  string
}

func newCanonicalStream() *canonicalStream {
	s := &canonicalStream{free: make(chan []byte, 4), jobs: make(chan []byte, 2)}
	for i := 0; i < 4; i++ {
		s.free <- make([]byte, 0, 256*1024)
	}
	s.current = <-s.free
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		h := sha256.New()
		for b := range s.jobs {
			h.Write(b)
			s.free <- b[:0]
		}
		s.result = hex.EncodeToString(h.Sum(nil))
	}()
	return s
}
func (s *canonicalStream) Write(data []byte) (int, error) {
	length := len(data)
	for len(data) > 0 {
		n := min(len(data), cap(s.current)-len(s.current))
		s.current = append(s.current, data[:n]...)
		data = data[n:]
		if len(s.current) == cap(s.current) {
			s.jobs <- s.current
			s.current = <-s.free
		}
	}
	return length, nil
}
func (s *canonicalStream) close() string {
	s.once.Do(func() {
		if len(s.current) > 0 {
			s.jobs <- s.current
		}
		close(s.jobs)
		s.wg.Wait()
	})
	return s.result
}
