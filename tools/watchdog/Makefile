PREFIX ?= /usr/local
LIBDIR = $(PREFIX)/lib/homelab-watchdog
.PHONY: install gate check
install:
	install -d "$(DESTDIR)$(LIBDIR)/runtime" "$(DESTDIR)$(PREFIX)/bin"
	install -m755 watchdog "$(DESTDIR)$(LIBDIR)/watchdog"
	install -m644 runtime/*.py "$(DESTDIR)$(LIBDIR)/runtime/"
	install -m755 runtime/external-probe "$(DESTDIR)$(LIBDIR)/runtime/"
	ln -sfn ../lib/homelab-watchdog/watchdog "$(DESTDIR)$(PREFIX)/bin/homelab-watchdog"
gate:
	CGO_ENABLED=0 go build -trimpath -o vpn-transit-gate gate/main.go
check:
	python3 -m unittest discover -s tests -p 'test_*.py'
