import argparse
import ctypes
from ctypes import wintypes
from io import BytesIO
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import winreg
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from qa import DAY, FIXED_TIME, Running, card, check_disk, choose_view, goto, install, open_slot, submit_inline


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.GetPropW.restype = wintypes.HANDLE
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]


def desktop_window(url):
    matches = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _):
        if user32.GetPropW(hwnd, url):
            matches.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return matches[0] if len(matches) == 1 else None


def local_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def windows_text_scale():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
            return winreg.QueryValueEx(key, "TextScaleFactor")[0] / 100
    except FileNotFoundError:
        return 1


def wait_cdp(port, run):
    endpoint = f"http://127.0.0.1:{port}"
    end = time.monotonic() + 14
    while time.monotonic() < end:
        try:
            with urlopen(endpoint + "/json/version", timeout=0.5) as response:
                if response.status == 200:
                    return endpoint
        except OSError:
            if run.process.poll() is not None:
                break
            time.sleep(0.1)
    raise AssertionError("WebView2 did not expose the test connection")


def capture_window(hwnd, path):
    from PIL import Image
    bounds = wintypes.RECT()
    assert user32.GetWindowRect(hwnd, ctypes.byref(bounds))
    width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
    gdi = ctypes.WinDLL("gdi32")
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HANDLE
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                              ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]

    screen = user32.GetWindowDC(hwnd)
    buffer = gdi.CreateCompatibleDC(screen)
    bitmap = gdi.CreateCompatibleBitmap(screen, width, height)
    old = gdi.SelectObject(buffer, bitmap)
    try:
        assert user32.PrintWindow(hwnd, buffer, 2)
        gdi.SelectObject(buffer, old)
        info = (ctypes.c_int32 * 10)(40, width, -height, 32 << 16 | 1, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        assert gdi.GetDIBits(buffer, bitmap, 0, height, pixels, info, 0) == height
        image = Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX")
        image.save(path)
        return image, bounds
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(buffer)
        user32.ReleaseDC(hwnd, screen)


def verify_type_and_motion(page, client):
    client.send("DOM.enable")
    client.send("CSS.enable")
    root = client.send("DOM.getDocument")["root"]["nodeId"]
    for selector, expected in ((".desktop-caption > span", "MaShanZheng"),
                               ("#period-label", "MaShanZheng"), ("#reflection", "LXGWWenKai")):
        node = client.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
        fonts = client.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
        assert any(font["isCustomFont"] and expected.casefold() in font["postScriptName"].replace("-", "").casefold()
                   and font["glyphCount"] > 0 for font in fonts), (selector, fonts)
    animation = page.locator(".lantern-light")
    assert animation.evaluate("el => el.getAnimations().length") == 1
    values = animation.evaluate("""el => {
      const motion = el.getAnimations()[0];
      motion.pause();
      motion.currentTime = 0;
      const dark = +getComputedStyle(el).opacity;
      motion.currentTime = 1260;
      const light = +getComputedStyle(el).opacity;
      motion.play();
      return [dark, light];
    }""")
    assert values[1] - values[0] > 0.25, values
    page.emulate_media(reduced_motion="reduce")
    assert animation.evaluate("el => el.getAnimations().length") == 0
    assert page.locator(".river-mist").evaluate("el => el.getAnimations().length") == 0
    page.emulate_media(reduced_motion="no-preference")
    assert animation.evaluate("el => el.getAnimations().length") == 1


def verify_caption_transition(page, hwnd, image, bounds):
    origin = wintypes.POINT()
    assert user32.ClientToScreen(hwnd, ctypes.byref(origin))
    seam = origin.y - bounds.top + round(page.locator(".masthead").bounding_box()["y"] * page.evaluate("devicePixelRatio"))
    assert 4 < seam < image.height - 4
    differences = []
    for fraction in (0.42, 0.56, 0.70, 0.82, 0.89):
        x = int(image.width * fraction)
        above, below = (image.getpixel((x, y)) for y in (seam - 3, seam + 3))
        differences.append(max(abs(a - b) for a, b in zip(above, below)))
    assert max(differences) <= 10, (seam, differences)
    print(f"PASS: native caption and animated scene join within {max(differences)} RGB levels", flush=True)


def verify_caption_hit_zones(page, hwnd):
    origin = wintypes.POINT()
    assert user32.ClientToScreen(hwnd, ctypes.byref(origin))
    dpi = page.evaluate("devicePixelRatio")
    x = int(page.locator(".window-actions").bounding_box()["x"] * dpi)
    def hit(px, py):
        point = ((origin.x + px) & 0xffff) | (((origin.y + py) & 0xffff) << 16)
        return user32.SendMessageW(hwnd, 0x0084, 0, point)
    assert hit(100, 14) == 2
    assert hit(x + 10, 14) == 1


def verify_header_layout(page):
    dimensions = page.evaluate("""() => {
      const controls = document.querySelector('.header-controls').getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(document.querySelector('#period-label'));
      const title = [...range.getClientRects()];
      return [Math.max(...title.map(rect => rect.right)), controls.left, document.body.scrollWidth, innerWidth];
    }""")
    assert dimensions[0] <= dimensions[1] and dimensions[2] == dimensions[3], dimensions


def capture_scene_motion(page, path):
    from PIL import Image

    page.evaluate("""() => {
      for (const node of document.querySelectorAll('.landscape *')) {
        for (const animation of node.getAnimations()) animation.pause();
      }
    }""")
    images = []
    for tick in range(0, 6000, 300):
        page.evaluate("""tick => {
          for (const node of document.querySelectorAll('.landscape *')) {
            for (const animation of node.getAnimations()) animation.currentTime = tick;
          }
        }""", tick)
        contents = page.locator(".masthead").screenshot(scale="css")
        images.append(Image.open(BytesIO(contents)).convert("RGB"))
    images[0].save(path, save_all=True, append_images=images[1:], duration=300, loop=0, quality=83)
    page.evaluate("""() => {
      for (const node of document.querySelectorAll('.landscape *')) {
        for (const animation of node.getAnimations()) animation.play();
      }
    }""")


def desktop_test(exe, screenshots, smoke=False):
    port = local_port()
    with tempfile.TemporaryDirectory(prefix="journal-webview-qa-", ignore_cleanup_errors=True) as profile:
        previous = {
            key: os.environ.get(key)
            for key in ("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "WEBVIEW2_USER_DATA_FOLDER")
        }
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port}"
        os.environ["WEBVIEW2_USER_DATA_FOLDER"] = profile
        try:
            run = Running(exe, graphical=True)
        finally:
            for key, value in previous.items():
                if value is None:
                    del os.environ[key]
                else:
                    os.environ[key] = value
        try:
            endpoint = wait_cdp(port, run)
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(endpoint, timeout=15000)
                context = browser.contexts[0]
                limit = time.monotonic() + 10
                page = None
                while time.monotonic() < limit:
                    page = next((item for item in context.pages if "?desktop=1" in item.url), None)
                    if page:
                        break
                    if context.pages:
                        context.pages[0].wait_for_timeout(100)
                    else:
                        context.wait_for_event("page", timeout=2000)
                assert page is not None
                expect(page.locator("#workspace")).to_have_attribute("aria-busy", "false")
                expect(page.locator("html")).to_have_class("desktop")
                assert page.locator(".landscape").evaluate("el => getComputedStyle(el).maskImage.includes('46px')")
                expect(page.locator("#reflection")).to_contain_text("。")
                assert not page.locator("#instruction").count()
                hwnd = desktop_window(run.url)
                assert hwnd
                awareness = user32.GetWindowDpiAwarenessContext(hwnd)
                assert user32.AreDpiAwarenessContextsEqual(awareness, ctypes.c_void_p(-4))
                dpi = user32.GetDpiForWindow(hwnd)
                ratio = page.evaluate("devicePixelRatio")
                text_scale = windows_text_scale()
                assert dpi >= 96 and abs(ratio - dpi / 96 * text_scale) < 0.02, (dpi, ratio, text_scale)
                assert page.evaluate("document.fonts.load('24px Journal Brush', '江湖行记').then(f => f.length)") == 1
                print(f"PASS: Per-Monitor V2, {dpi} DPI, text scale {text_scale:g}, WebView2 DPR {ratio:g}", flush=True)
                if smoke:
                    choose_view(page, "month")
                    page.locator(".date-number").first.click()
                    expect(page.locator("#agenda")).to_be_visible()
                    page.get_by_role("button", name="关闭当天日程", exact=True).click()
                    expect(page.locator("#agenda")).not_to_be_visible()
                    choose_view(page, "day")
                    assert user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    assert run.process.wait(timeout=10) == 0
                    assert not run.session.exists()
                    print("PASS: final portable executable opened a real desktop window and closed cleanly")
                    return

                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.clock.set_fixed_time(FIXED_TIME)
                page.get_by_role("button", name="今天", exact=True).click()
                expect(page.locator("#period-label")).to_have_text("11月11日 周三")
                expect(page.locator(".desktop-caption > span")).to_have_text("江湖行记")
                verify_caption_hit_zones(page, hwnd)
                page.get_by_role("button", name="最小化", exact=True).click()
                until = time.monotonic() + 3
                while not user32.IsIconic(hwnd) and time.monotonic() < until:
                    time.sleep(0.04)
                assert user32.IsIconic(hwnd)
                user32.ShowWindow(hwnd, 9)
                page.get_by_role("button", name="最大化", exact=True).click()
                expect(page.get_by_role("button", name="还原窗口", exact=True)).to_be_visible()
                assert user32.IsZoomed(hwnd)
                choose_view(page, "week")
                goto(page, "2026-11-30")
                expect(page.locator("#period-label")).to_have_text("11月30日—12月6日")
                verify_header_layout(page)
                if screenshots:
                    screenshots.mkdir(parents=True, exist_ok=True)
                    capture_window(hwnd, screenshots / "desktop-maximized.png")
                page.get_by_role("button", name="还原窗口", exact=True).click()
                expect(page.get_by_role("button", name="最大化", exact=True)).to_be_visible()
                assert not user32.IsZoomed(hwnd)
                choose_view(page, "day")
                page.get_by_role("button", name="今天", exact=True).click()

                open_slot(page, DAY, 540, "plan")
                submit_inline(page, "晨间写作")
                open_slot(page, DAY, 600, "actual")
                submit_inline(page, "清河读书🏮")
                check_disk(run, "清河读书🏮", DAY, 600, 30, "actual")
                assert page.locator(".short-slot .title").evaluate_all("""spans => spans.every(span => {
                  const text = span.getBoundingClientRect();
                  const block = span.closest('.time-event').getBoundingClientRect();
                  return text.top >= block.top && text.bottom <= block.bottom;
                })""")
                open_slot(page, DAY, 810, "plan", end=885)
                submit_inline(page, "项目讨论")
                for view in ("week", "month", "day"):
                    choose_view(page, view)
                    expect(card(page, "晨间写作")).to_have_count(1)
                    expect(card(page, "清河读书🏮")).to_have_count(1)

                choose_view(page, "month")
                page.get_by_role("button", name="11月11日日程详情", exact=True).click()
                expect(page.locator("#agenda .agenda-item")).to_have_count(3)
                expect(page.locator("#agenda").get_by_text("清河读书🏮", exact=True)).to_be_visible()
                if screenshots:
                    screenshots.mkdir(parents=True, exist_ok=True)
                    page.wait_for_function("""() => {
                      const agenda = document.querySelector('#agenda');
                      const r = agenda.getBoundingClientRect();
                      return Math.abs(r.x * 2 + r.width - innerWidth) <= 2 &&
                        Math.abs(r.y * 2 + r.height - innerHeight) <= 2 &&
                        getComputedStyle(agenda).opacity === '1';
                    }""")
                    capture_window(hwnd, screenshots / "desktop-agenda.png")
                page.get_by_role("button", name="关闭当天日程", exact=True).click()
                expect(page.locator("#agenda")).not_to_be_visible()
                expect(page.locator('[data-view=month]')).to_have_attribute("aria-pressed", "true")
                choose_view(page, "day")

                client = context.new_cdp_session(page)
                verify_type_and_motion(page, client)
                for scale in (1, 1.25, 1.5, 2):
                    client.send("Emulation.setDeviceMetricsOverride", {
                        "width": 1100, "height": 810, "deviceScaleFactor": scale, "mobile": False,
                    })
                    assert abs(page.evaluate("devicePixelRatio") - scale) < 0.02
                    for view in ("day", "week", "month"):
                        choose_view(page, view)
                        assert page.locator("body").evaluate("el => el.scrollWidth === el.clientWidth")
                        expect(card(page, "清河读书🏮")).to_have_count(1)
                client.send("Emulation.clearDeviceMetricsOverride")
                choose_view(page, "day")

                # A second launch must use the same desktop session.
                second = subprocess.run([exe], cwd=os.environ["TEMP"], timeout=8)
                assert second.returncode == 0 and desktop_window(run.url) == hwnd
                assert len(context.pages) == 1

                page.get_by_role("button", name="设置", exact=True).click()
                with page.expect_download(timeout=12000) as downloaded:
                    page.get_by_role("button", name="导出备份", exact=True).click()
                assert "江湖行记备份" in downloaded.value.suggested_filename
                assert downloaded.value.path().stat().st_size > 100
                page.get_by_role("button", name="关闭", exact=True).click()

                editor = open_slot(page, DAY, 960, "plan")
                editor.fill("练字")
                if screenshots:
                    screenshots.mkdir(parents=True, exist_ok=True)
                    page.locator("#workspace").evaluate(
                        "el => { el.scrollTop = 8.8 * parseFloat(getComputedStyle(el).getPropertyValue('--hour')); }"
                    )
                    page.screenshot(path=screenshots / "desktop-day.png", animations="disabled")
                    image, bounds = capture_window(hwnd, screenshots / "desktop-window.png")
                    verify_caption_transition(page, hwnd, image, bounds)
                    capture_scene_motion(page, screenshots / "lantern-motion.webp")
                page.once("dialog", lambda dialog: dialog.dismiss())
                page.get_by_role("button", name="关闭窗口", exact=True).click()
                expect(editor).to_have_value("练字")
                assert run.process.poll() is None
                submit_inline(page, "练字")
                assert not errors, errors
                assert user32.PostMessageW(hwnd, 0x0010, 0, 0)
                assert run.process.wait(timeout=10) == 0
                assert not run.session.exists()
                assert not desktop_window(run.url)
                check_disk(run, "练字", DAY, 960, 30, "plan")
            print("PASS: desktop window, actual Kai and brush glyphs, animated lanterns, reduced motion, maximize/restore, single instance, Chinese input, three-view sync, export, draft-safe close")
        finally:
            run.stop()
            # WebView2 may release its temporary profile shortly after the app exits.
            for _ in range(12):
                try:
                    with os.scandir(profile):
                        pass
                    if not desktop_window(run.url):
                        break
                except FileNotFoundError:
                    break
                time.sleep(0.1)


if __name__ == "__main__":
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--smoke", action="store_true")
    arguments = parser.parse_args()
    if arguments.smoke:
        desktop_test(arguments.exe.resolve(), arguments.screenshots, smoke=True)
    else:
        with tempfile.TemporaryDirectory(prefix="journal-desktop-qa-", dir=Path(__file__).resolve().parent) as directory:
            desktop_test(install(arguments.exe, Path(directory)), arguments.screenshots)
