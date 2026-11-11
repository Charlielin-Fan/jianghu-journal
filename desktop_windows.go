package main

import (
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"syscall"
	"unsafe"

	webview "github.com/jchv/go-webview2"
)

const (
	wmSize       = 0x0005
	wmClose      = 0x0010
	wmNCHitTest  = 0x0084
	wmDPIChanged = 0x02e0
	wmFinish     = 0x8000 + 137
)

type windowRect struct{ left, top, right, bottom int32 }
type windowPoint struct{ x, y int32 }

var (
	windowDLL        = syscall.NewLazyDLL("user32.dll")
	windowEnum       = windowDLL.NewProc("EnumWindows")
	windowGetProp    = windowDLL.NewProc("GetPropW")
	windowSetProp    = windowDLL.NewProc("SetPropW")
	windowPost       = windowDLL.NewProc("PostMessageW")
	windowShow       = windowDLL.NewProc("ShowWindow")
	windowIconic     = windowDLL.NewProc("IsIconic")
	windowFocus      = windowDLL.NewProc("SetForegroundWindow")
	windowMetrics    = windowDLL.NewProc("GetSystemMetrics")
	windowDPI        = windowDLL.NewProc("GetDpiForSystem")
	windowPosition   = windowDLL.NewProc("SetWindowPos")
	windowGetStyle   = windowDLL.NewProc("GetWindowLongW")
	windowSetStyle   = windowDLL.NewProc("SetWindowLongW")
	windowZoomed     = windowDLL.NewProc("IsZoomed")
	clientToScreen   = windowDLL.NewProc("ClientToScreen")
	getClientRect    = windowDLL.NewProc("GetClientRect")
	copyWindowRect   = kernel.NewProc("RtlMoveMemory")
	dwmDLL           = syscall.NewLazyDLL("dwmapi.dll")
	dwmSetAttribute  = dwmDLL.NewProc("DwmSetWindowAttribute")
	controlDLL       = syscall.NewLazyDLL("comctl32.dll")
	subclassWindow   = controlDLL.NewProc("SetWindowSubclass")
	removeSubclass   = controlDLL.NewProc("RemoveWindowSubclass")
	defaultSubclass  = controlDLL.NewProc("DefSubclassProc")
	desktopURLFormat = regexp.MustCompile(`^http://127\.0\.0\.1:[0-9]{1,5}/[a-f0-9]{48}/$`)
)

func openDesktop(url string) error {
	if !desktopURLFormat.MatchString(url) {
		return errors.New("invalid desktop address")
	}
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	cache, err := os.UserCacheDir()
	if err != nil {
		return err
	}
	profile := filepath.Join(cache, "JianghuJournal", "WebView2")
	if err := os.MkdirAll(profile, 0700); err != nil {
		return err
	}
	width, _, _ := windowMetrics.Call(0)
	height, _, _ := windowMetrics.Call(1)
	dpi, _, _ := windowDPI.Call()
	if dpi == 0 {
		dpi = 96
	}
	view := webview.NewWithOptions(webview.WebViewOptions{
		DataPath: profile, AutoFocus: true,
		WindowOptions: webview.WindowOptions{
			Title: "江湖行记", Width: uint(min(width*88/100, 1460*dpi/96)),
			Height: uint(min(height*84/100, 1000*dpi/96)), IconId: 2, Center: true,
		},
	})
	if view == nil {
		return errors.New("WebView2 is not available")
	}
	hwnd := uintptr(view.Window())
	captionHeight, captionActions := int32(31*dpi/96), int32(144*dpi/96)
	setFrameColor(hwnd)
	property, _ := syscall.UTF16PtrFromString(url)
	windowSetProp.Call(hwnd, uintptr(unsafe.Pointer(property)), 1)
	callback := syscall.NewCallback(func(hwnd, message, wparam, lparam, id, data uintptr) uintptr {
		switch message {
		case wmNCHitTest:
			return captionHitTest(hwnd, message, wparam, lparam, captionHeight, captionActions)
		case wmSize:
			result, _, _ := defaultSubclass.Call(hwnd, message, wparam, lparam)
			if wparam == 2 {
				view.Eval("window.updateJournalCaption?.(true)")
			} else if wparam == 0 {
				view.Eval("window.updateJournalCaption?.(false)")
			}
			return result
		case wmClose:
			view.Eval("if (window.journalClose) window.journalClose(); else window.closeNativeWindow();")
			return 0
		case wmFinish:
			view.Terminate()
			return 0
		case wmDPIChanged:
			var bounds windowRect
			if lparam != 0 {
				copyWindowRect.Call(uintptr(unsafe.Pointer(&bounds)), lparam, unsafe.Sizeof(bounds))
				windowPosition.Call(hwnd, 0, uintptr(bounds.left), uintptr(bounds.top),
					uintptr(bounds.right-bounds.left), uintptr(bounds.bottom-bounds.top), 0x0014)
			}
			return 0
		default:
			result, _, _ := defaultSubclass.Call(hwnd, message, wparam, lparam)
			return result
		}
	})
	if result, _, _ := subclassWindow.Call(hwnd, callback, 1, 0); result == 0 {
		return errors.New("cannot initialize desktop window")
	}
	defer removeSubclass.Call(hwnd, callback, 1)
	const windowStyle = ^uintptr(15) // GWL_STYLE (-16)
	style, _, _ := windowGetStyle.Call(hwnd, windowStyle)
	windowSetStyle.Call(hwnd, windowStyle, style&^0x00c00000) // remove WS_CAPTION and retain WS_THICKFRAME
	windowPosition.Call(hwnd, 0, 0, 0, 0, 0, 0x0037)
	if err := view.Bind("closeNativeWindow", func() {
		view.Dispatch(view.Terminate)
	}); err != nil {
		return err
	}
	if err := view.Bind("journalWindowCommand", func(command string) {
		switch command {
		case "minimize":
			windowShow.Call(hwnd, 6)
		case "maximize":
			mode := uintptr(3)
			if zoomed, _, _ := windowZoomed.Call(hwnd); zoomed != 0 {
				mode = 9
			}
			windowShow.Call(hwnd, mode)
		case "close":
			windowPost.Call(hwnd, wmClose, 0, 0)
		}
	}); err != nil {
		return err
	}
	if err := view.Bind("journalCaptionSize", func(height, actions int32) {
		if height > 0 && height < 260 && actions > 0 && actions < 950 {
			captionHeight, captionActions = height, actions
		}
	}); err != nil {
		return err
	}
	view.Navigate(url + "?desktop=1")
	view.Run()
	return nil
}

func captionHitTest(hwnd, message, wparam, lparam uintptr, captionHeight, captionActions int32) uintptr {
	hit, _, _ := defaultSubclass.Call(hwnd, message, wparam, lparam)
	if hit == 1 { // HTCLIENT
		var origin windowPoint
		var client windowRect
		clientToScreen.Call(hwnd, uintptr(unsafe.Pointer(&origin)))
		getClientRect.Call(hwnd, uintptr(unsafe.Pointer(&client)))
		x, y := int32(int16(lparam))-origin.x, int32(int16(lparam>>16))-origin.y
		if y >= 0 && y < captionHeight && x < client.right-captionActions {
			return 2 // HTCAPTION
		}
	}
	return hit
}

func setFrameColor(hwnd uintptr) {
	// Windows 11 can carry the scene color through the system caption.
	for _, attribute := range []struct{ id, color uint32 }{
		{34, 0x00393229}, // border, COLORREF (BGR)
		{35, 0x00282018}, // caption
		{36, 0x00CCDFF0}, // text
	} {
		color := attribute.color
		dwmSetAttribute.Call(hwnd, uintptr(attribute.id), uintptr(unsafe.Pointer(&color)), 4)
	}
}

func desktopWindow(url string) uintptr {
	if !desktopURLFormat.MatchString(url) {
		return 0
	}
	property, _ := syscall.UTF16PtrFromString(url)
	var found uintptr
	callback := syscall.NewCallback(func(hwnd, data uintptr) uintptr {
		exists, _, _ := windowGetProp.Call(hwnd, uintptr(unsafe.Pointer(property)))
		if exists != 0 {
			found = hwnd
			return 0
		}
		return 1
	})
	windowEnum.Call(callback, 0)
	return found
}

func focusDesktop(url string) bool {
	hwnd := desktopWindow(url)
	if hwnd == 0 {
		return false
	}
	if minimized, _, _ := windowIconic.Call(hwnd); minimized != 0 {
		windowShow.Call(hwnd, 9)
	}
	windowFocus.Call(hwnd)
	return true
}

func finishDesktop(url string) {
	if hwnd := desktopWindow(url); hwnd != 0 {
		windowPost.Call(hwnd, wmFinish, 0, 0)
	}
}
