package ingest

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"syscall"
	"time"
)

var (
	ErrBlockedIPRange    = errors.New("access to private, loopback, or cloud metadata IP ranges is forbidden")
	ErrUnsupportedScheme = errors.New("only http and https schemes are supported")
	ErrResponseTooLarge  = errors.New("response payload exceeds maximum allowed size")
)

const MaxResponseBodyBytes = 2 * 1024 * 1024 // 2 MB

var privateIPBlocks []*net.IPNet

func init() {
	for _, cidr := range []string{
		"127.0.0.0/8",    // IPv4 loopback
		"10.0.0.0/8",     // RFC1918 private
		"172.16.0.0/12",  // RFC1918 private
		"192.168.0.0/16", // RFC1918 private
		"169.254.0.0/16", // IPv4 link-local / cloud metadata (169.254.169.254)
		"0.0.0.0/8",      // Current network
		"::1/128",        // IPv6 loopback
		"fc00::/7",       // IPv6 unique local address
		"fe80::/10",      // IPv6 link-local
	} {
		_, block, err := net.ParseCIDR(cidr)
		if err == nil {
			privateIPBlocks = append(privateIPBlocks, block)
		}
	}
}

func IsPrivateOrLoopbackIP(ip net.IP) bool {
	if ip == nil {
		return true
	}
	for _, block := range privateIPBlocks {
		if block.Contains(ip) {
			return true
		}
	}
	return false
}

func SafeDialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, err
	}

	ips, err := net.DefaultResolver.LookupIP(ctx, "ip", host)
	if err != nil {
		return nil, fmt.Errorf("DNS resolution failed for %s: %w", host, err)
	}

	for _, ip := range ips {
		if IsPrivateOrLoopbackIP(ip) {
			return nil, fmt.Errorf("%w: %s resolves to %s", ErrBlockedIPRange, host, ip.String())
		}
	}

	dialer := &net.Dialer{
		Timeout: 5 * time.Second,
		Control: func(network, address string, c syscall.RawConn) error {
			return nil
		},
	}
	return dialer.DialContext(ctx, network, net.JoinHostPort(ips[0].String(), port))
}

func NewSafeHTTPClient() *http.Client {
	transport := &http.Transport{
		DialContext:           SafeDialContext,
		ResponseHeaderTimeout: 8 * time.Second,
		DisableKeepAlives:     true,
	}

	client := &http.Client{
		Transport: transport,
		Timeout:   10 * time.Second,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 3 {
				return errors.New("stopped after 3 redirects")
			}
			if req.URL.Scheme != "http" && req.URL.Scheme != "https" {
				return ErrUnsupportedScheme
			}
			// SafeDialContext will re-validate the target IP upon connecting
			return nil
		},
	}
	return client
}

func FetchSafeURL(ctx context.Context, targetURL string) ([]byte, string, error) {
	parsed, err := url.Parse(targetURL)
	if err != nil {
		return nil, "", fmt.Errorf("invalid URL: %w", err)
	}

	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, "", ErrUnsupportedScheme
	}

	// Host check
	hostname := parsed.Hostname()
	if strings.EqualFold(hostname, "localhost") {
		return nil, "", ErrBlockedIPRange
	}

	client := NewSafeHTTPClient()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, targetURL, nil)
	if err != nil {
		return nil, "", err
	}
	req.Header.Set("User-Agent", "Gusby/1.0 (+https://github.com/gusby-kg)")

	resp, err := client.Do(req)
	if err != nil {
		return nil, "", fmt.Errorf("HTTP fetch failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, "", fmt.Errorf("target URL returned status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, MaxResponseBodyBytes+1))
	if err != nil {
		return nil, "", fmt.Errorf("failed to read response: %w", err)
	}

	if len(body) > MaxResponseBodyBytes {
		return nil, "", ErrResponseTooLarge
	}

	contentType := resp.Header.Get("Content-Type")
	return body, contentType, nil
}
