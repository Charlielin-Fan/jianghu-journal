package main

import (
	"os"
	"syscall"
	"time"
	"unsafe"
)

var (
	kernel   = syscall.NewLazyDLL("kernel32.dll")
	moveFile = kernel.NewProc("MoveFileExW")
	shell    = syscall.NewLazyDLL("shell32.dll").NewProc("ShellExecuteW")
	dialog   = syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")
)

func replaceFile(source, destination string) error {
	from, err := syscall.UTF16PtrFromString(source)
	if err != nil {
		return err
	}
	to, err := syscall.UTF16PtrFromString(destination)
	if err != nil {
		return err
	}
	for attempt := 0; ; attempt++ {
		result, _, callErr := moveFile.Call(uintptr(unsafe.Pointer(from)), uintptr(unsafe.Pointer(to)), 1|8)
		if result != 0 {
			return nil
		}
		if attempt == 3 || (callErr != syscall.Errno(32) && callErr != syscall.Errno(5)) {
			return callErr
		}
		time.Sleep(40 * time.Millisecond)
	}
}

func openLock(path string) (*os.File, error) {
	name, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	handle, err := syscall.CreateFile(name, syscall.GENERIC_READ|syscall.GENERIC_WRITE, 0, nil,
		syscall.OPEN_ALWAYS, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(handle), path), nil
}

func notify(message string) {
	title, _ := syscall.UTF16PtrFromString("江湖行记")
	body, _ := syscall.UTF16PtrFromString(message)
	dialog.Call(0, uintptr(unsafe.Pointer(body)), uintptr(unsafe.Pointer(title)), 0x40)
}

func launchBrowser(url string) {
	action, _ := syscall.UTF16PtrFromString("open")
	target, _ := syscall.UTF16PtrFromString(url)
	result, _, _ := shell.Call(0, uintptr(unsafe.Pointer(action)), uintptr(unsafe.Pointer(target)), 0, 0, 1)
	if result <= 32 {
		notify("未能自动打开浏览器。可在 Edge 或 Chrome 中打开：\n\n" + url)
	}
}
