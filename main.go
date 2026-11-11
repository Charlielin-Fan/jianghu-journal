package main

import (
	"context"
	"crypto/rand"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

//go:embed web/*.html web/*.css web/*.js web/*.svg web/lantern-river.png web/LXGWWenKai-Regular.ttf web/MaShanZheng-Regular.ttf
var assets embed.FS

type session struct {
	mutex     sync.Mutex
	data      Journal
	recovered bool
	path      string
	host      string
	cancel    context.CancelFunc
	isClosing bool
}

func main() {
	noBrowser := flag.Bool("no-browser", false, "start without opening a window")
	browserOnly := flag.Bool("browser", false, "open in the default browser")
	desktopURL := flag.String("desktop-window", "", "internal window process")
	flag.Parse()
	if *desktopURL != "" {
		if err := openDesktop(*desktopURL); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if err := run(*noBrowser, *browserOnly); err != nil {
		fmt.Fprintln(os.Stderr, err)
		if !*noBrowser {
			notify(err.Error())
		}
		os.Exit(1)
	}
}

func run(noBrowser, browserOnly bool) error {
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	dataDir := filepath.Join(filepath.Dir(executable), "数据")
	if err := os.MkdirAll(dataDir, 0700); err != nil {
		return fmt.Errorf("无法在程序旁创建数据目录。请确认所在文件夹可写。\n%s", err)
	}
	sessionPath := filepath.Join(dataDir, ".session")
	lock, err := openLock(filepath.Join(dataDir, ".lock"))
	if err != nil {
		if errors.Is(err, syscall.Errno(32)) {
			for i := 0; i < 10; i++ {
				if url := runningURL(sessionPath); url != "" {
					if !noBrowser && !browserOnly {
						for attempt := 0; attempt < 12; attempt++ {
							if focusDesktop(url) {
								return nil
							}
							time.Sleep(100 * time.Millisecond)
						}
					}
					if !noBrowser {
						launchBrowser(url)
					}
					return nil
				}
				time.Sleep(100 * time.Millisecond)
			}
			return errors.New("江湖行记已启动，请切回原窗口，或稍后重新打开")
		}
		return fmt.Errorf("无法打开数据目录。请确认移动硬盘已连接且可写。\n%s", err)
	}
	defer lock.Close()
	defer os.Remove(sessionPath)

	dataPath := filepath.Join(dataDir, "行记.json")
	journal, recovered, err := loadJournal(dataPath)
	if err != nil {
		return err
	}
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return fmt.Errorf("无法打开本机行记窗口：%w", err)
	}
	defer listener.Close()
	token := make([]byte, 24)
	if _, err := rand.Read(token); err != nil {
		return err
	}
	prefix := "/" + hex.EncodeToString(token) + "/"
	host := listener.Addr().String()
	url := "http://" + host + prefix
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	s := &session{data: journal, recovered: recovered, path: dataPath, host: host, cancel: stop}
	handler := http.NewServeMux()
	handler.HandleFunc("GET /api/ready", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusNoContent) })
	handler.HandleFunc("GET /api/journal", s.read)
	handler.HandleFunc("PUT /api/journal", s.write)
	handler.HandleFunc("POST /api/exit", s.exit)
	web, err := fs.Sub(assets, "web")
	if err != nil {
		return err
	}
	handler.Handle("GET /", http.FileServer(http.FS(web)))
	router := http.StripPrefix(strings.TrimSuffix(prefix, "/"), handler)
	server := &http.Server{
		ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second,
		WriteTimeout: 20 * time.Second, IdleTimeout: 20 * time.Second,
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Host != host || !strings.HasPrefix(r.URL.Path, prefix) {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("Cache-Control", "no-store")
			w.Header().Set("X-Content-Type-Options", "nosniff")
			w.Header().Set("Referrer-Policy", "no-referrer")
			w.Header().Set("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'")
			router.ServeHTTP(w, r)
		}),
	}
	if err := writeAtomic(sessionPath, []byte(url)); err != nil {
		return fmt.Errorf("无法在移动硬盘写入会话信息：%w", err)
	}
	served := make(chan error, 1)
	go func() { served <- server.Serve(listener) }()
	childCtx, stopChild := context.WithCancel(context.Background())
	defer stopChild()
	desktopDone := make(chan struct{})
	switch {
	case noBrowser:
		close(desktopDone)
	case browserOnly:
		close(desktopDone)
		go launchBrowser(url)
	default:
		go func() {
			defer close(desktopDone)
			command := exec.CommandContext(childCtx, executable, "--desktop-window", url)
			if err := command.Run(); err != nil && ctx.Err() == nil {
				launchBrowser(url)
			} else {
				stop()
			}
		}()
	}
	select {
	case err := <-served:
		return err
	case <-ctx.Done():
	}
	closeCtx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	err = server.Shutdown(closeCtx)
	select {
	case <-desktopDone:
	case <-time.After(450 * time.Millisecond):
		finishDesktop(url)
		select {
		case <-desktopDone:
		case <-time.After(3 * time.Second):
			stopChild()
			<-desktopDone
		}
	}
	return err
}

func runningURL(path string) string {
	raw, err := os.ReadFile(path)
	if err != nil || len(raw) > 100 {
		return ""
	}
	url := string(raw)
	if !strings.HasPrefix(url, "http://127.0.0.1:") || !strings.HasSuffix(url, "/") ||
		strings.ContainsAny(url, "\r\n?#\\@") {
		return ""
	}
	client := &http.Client{Timeout: 250 * time.Millisecond, CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}}
	response, err := client.Get(url + "api/ready")
	if err != nil {
		return ""
	}
	response.Body.Close()
	if response.StatusCode != http.StatusNoContent {
		return ""
	}
	return url
}

func reply(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func message(w http.ResponseWriter, status int, text string) {
	reply(w, status, map[string]string{"message": text})
}

func (s *session) read(w http.ResponseWriter, r *http.Request) {
	s.mutex.Lock()
	defer s.mutex.Unlock()
	reply(w, http.StatusOK, map[string]any{"journal": s.data, "recovered": s.recovered})
}

func (s *session) checkOrigin(w http.ResponseWriter, r *http.Request) bool {
	if r.Header.Get("Origin") != "http://"+s.host {
		message(w, http.StatusForbidden, "请从江湖行记窗口操作")
		return false
	}
	return true
}

func (s *session) write(w http.ResponseWriter, r *http.Request) {
	if !s.checkOrigin(w, r) {
		return
	}
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, maxDataSize))
	if err != nil {
		message(w, http.StatusBadRequest, "数据无法读取或文件过大")
		return
	}
	next, err := decodeJournal(raw)
	if err != nil {
		message(w, http.StatusBadRequest, err.Error())
		return
	}
	s.mutex.Lock()
	defer s.mutex.Unlock()
	if s.isClosing {
		message(w, http.StatusServiceUnavailable, "行记正在退出。请重新打开后保存")
		return
	}
	if next.Revision != s.data.Revision {
		reply(w, http.StatusConflict, map[string]any{"message": "另一窗口刚刚保存了内容，请重试", "journal": s.data})
		return
	}
	next.Revision++
	if err = saveJournal(s.path+".bak", s.data); err == nil {
		err = saveJournal(s.path, next)
	}
	if err != nil {
		message(w, http.StatusInsufficientStorage, "未能保存到硬盘。请确认硬盘已连接、可写且有剩余空间，再重试。")
		return
	}
	s.data = next
	s.recovered = false
	reply(w, http.StatusOK, map[string]any{"journal": s.data})
}

func (s *session) exit(w http.ResponseWriter, r *http.Request) {
	if !s.checkOrigin(w, r) {
		return
	}
	s.mutex.Lock()
	s.isClosing = true
	s.mutex.Unlock()
	reply(w, http.StatusOK, map[string]bool{"closed": true})
	s.cancel()
}
