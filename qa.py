import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright


DAY = "2026-11-11"
FIXED_TIME = datetime(2026, 11, 11, 12, tzinfo=timezone(timedelta(hours=8)))
TITLE = "写方案 <清河> & 看灯🏮"
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")


class Running:
    def __init__(self, exe, graphical=False):
        self.exe = exe
        self.data = exe.parent / "数据"
        self.session = self.data / ".session"
        self.main = self.data / "行记.json"
        self.backup = self.data / "行记.json.bak"
        args = [exe] if graphical else [exe, "--no-browser"]
        self.process = subprocess.Popen(args, cwd=os.environ["TEMP"])
        until = time.monotonic() + 10
        while time.monotonic() < until:
            if self.process.poll() is not None:
                raise AssertionError(f"Launcher terminated early: {self.process.returncode}")
            if self.session.exists():
                self.url = self.session.read_text(encoding="utf-8")
                try:
                    if self.api("ready") == b"":
                        return
                except OSError:
                    pass
            time.sleep(0.07)
        self.process.kill()
        raise AssertionError("Launcher did not open a session")

    def api(self, path, method="GET", body=None):
        origin = "/".join(self.url.split("/")[:3])
        headers = {"Origin": origin, "Content-Type": "application/json"}
        with urlopen(Request(self.url + "api/" + path, data=body, headers=headers, method=method), timeout=5) as response:
            return response.read()

    def contents(self):
        return json.loads(self.main.read_text(encoding="utf-8"))

    def stop(self):
        if self.process.poll() is not None:
            return
        try:
            self.api("exit", "POST")
            self.process.wait(timeout=10)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)


def install(source, directory):
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "江湖行记.exe"
    shutil.copy2(source, destination)
    return destination


def new_page(context, run, errors):
    page = context.new_page()
    page.set_default_timeout(6500)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.clock.set_fixed_time(FIXED_TIME)
    page.goto(run.url)
    expect(page.locator("#workspace")).to_have_attribute("aria-busy", "false")
    expect(page.locator(".brand")).to_have_text("江湖行记")
    expect(page.locator(".brand")).to_be_visible()
    return page


def choose_view(page, view):
    names = {"day": "日视图", "week": "周视图", "month": "月视图"}
    page.get_by_role("button", name=names[view], exact=True).click()
    expect(page.locator(f"[data-view={view}]")).to_have_attribute("aria-pressed", "true")


def goto(page, date):
    page.locator("#period-label").click()
    page.get_by_label("日期", exact=True).fill(date)
    page.get_by_role("button", name="前往", exact=True).click()


def lane_point(page, date, minute, kind=None):
    lane = page.locator(f'.lane[data-date="{date}"]' + (f'[data-kind="{kind}"]' if kind else '')).first
    return lane.evaluate("""(lane, minute) => {
      const workspace = document.getElementById('workspace');
      const absolute = lane.getBoundingClientRect().top - workspace.getBoundingClientRect().top + workspace.scrollTop;
      workspace.scrollTop = Math.max(0, absolute + minute / 1440 * lane.offsetHeight - 185);
      const box = lane.getBoundingClientRect();
      return [box.x + box.width / 2, box.y + minute / 1440 * box.height + 1];
    }""", minute)


def open_slot(page, date, minute, kind=None, end=None):
    x, y = lane_point(page, date, minute, kind)
    if end is None:
        page.mouse.click(x, y)
    else:
        lane = page.locator(f'.lane[data-date="{date}"]').first
        distance = (end - minute) * lane.bounding_box()["height"] / 1440
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x, y + distance, steps=9)
        page.mouse.up()
    editor = page.locator(".inline-editor input")
    expect(editor).to_be_focused()
    return editor


def submit_inline(page, title):
    editor = page.locator(".inline-editor input")
    editor.fill(title)
    editor.press("Enter")
    expect(editor).to_have_count(0)
    expect(page.locator("#status")).to_have_text("已保存到硬盘")


def card(page, title):
    return page.locator(".event .title").and_(page.get_by_text(title, exact=True))


def check_disk(run, title, date, start, minutes, kind):
    matches = [item for item in run.contents()["entries"] if item["title"] == title and item["kind"] == kind]
    assert len(matches) == 1, matches
    entry = matches[0]
    assert (entry["date"], entry["start"], entry["minutes"]) == (date, start, minutes), entry
    return entry


def test_workflow(context, run, screenshots):
    errors = []
    page = new_page(context, run, errors)
    assert run.contents()["entries"] == []
    assert page.locator("html").get_attribute("lang") == "zh-CN"
    expect(page.locator("#period-label")).to_have_text("11月11日 周三")
    assert page.evaluate("document.fonts.load('16px Journal Kai', '江湖行记').then(f => f.length)") == 1
    assert page.request.get(run.url + "lantern-river.png").ok
    assert page.evaluate("document.fonts.load('24px Journal Brush', '11月11日').then(f => f.length)") == 1
    expect(page.locator("#reflection")).to_contain_text("。")
    assert not page.locator("#instruction").count()
    assert page.evaluate("""async () => {
      const { reflectionFor } = await import(new URL('reflections.js', location.href));
      const verses = Array.from({length: 60}, (_, i) =>
        reflectionFor(new Date(Date.UTC(2026, 10, 11 + i)).toISOString().slice(0, 10)));
      return new Set(verses).size === 60 && verses[0] === document.querySelector('#reflection').textContent;
    }""")
    midnight = context.new_page()
    midnight.clock.install(time=FIXED_TIME.replace(hour=23, minute=59, second=40))
    midnight.goto(run.url)
    expect(midnight.locator("#reflection")).to_have_text(page.locator("#reflection").text_content())
    midnight.clock.run_for(21000)
    tomorrow = page.evaluate("""async () => {
      const { reflectionFor } = await import(new URL('reflections.js', location.href));
      return reflectionFor('2026-11-12');
    }""")
    expect(midnight.locator("#reflection")).to_have_text(tomorrow)
    midnight.close()

    editor = open_slot(page, DAY, 540, "plan")
    editor.fill(TITLE)
    editor.dispatch_event("compositionstart")
    editor.press("Enter")
    expect(editor).to_be_visible()
    assert not run.contents()["entries"]
    editor.dispatch_event("compositionend")
    submit_inline(page, TITLE)
    check_disk(run, TITLE, DAY, 540, 30, "plan")
    open_slot(page, DAY, 600, "actual")
    submit_inline(page, "临时会议")
    check_disk(run, "临时会议", DAY, 600, 30, "actual")

    choose_view(page, "week")
    for title in [TITLE, "临时会议"]:
        expect(card(page, title)).to_have_count(1)
    assert page.locator(".lane").count() == 7
    page.locator("#workspace").evaluate("el => { el.scrollTop = 540; }")
    week_position = page.locator("#workspace").evaluate("el => el.scrollTop")
    choose_view(page, "day")
    page.locator("#workspace").evaluate("el => { el.scrollTop = 250; }")
    choose_view(page, "week")
    assert page.locator("#workspace").evaluate("el => el.scrollTop") == week_position
    choose_view(page, "day")
    assert page.locator("#workspace").evaluate("el => el.scrollTop") == 250
    choose_view(page, "week")
    open_slot(page, DAY, 780, end=840)
    submit_inline(page, "项目讨论")
    check_disk(run, "项目讨论", DAY, 780, 60, "plan")
    page.locator('[data-filter="actual"]').click()
    expect(card(page, "项目讨论")).to_have_count(0)
    open_slot(page, DAY, 870, "actual")
    submit_inline(page, "记下进展")
    page.locator('[data-filter="all"]').click()
    check_disk(run, "记下进展", DAY, 870, 30, "actual")

    choose_view(page, "month")
    expect(page.locator('.cell')).to_have_count(42)
    for title in [TITLE, "临时会议", "项目讨论"]:
        expect(card(page, title)).to_have_count(1)
    expect(page.locator(f'.cell[data-date="{DAY}"] .more-events')).to_have_text("+1 项")
    ruler = page.locator(f'.cell[data-date="{DAY}"] .ruler')
    ruler.scroll_into_view_if_needed()
    bounds = ruler.bounding_box()
    x = bounds["x"] + 4 + (bounds["width"] - 8) * (975 / 1440)
    y = bounds["y"] + bounds["height"] / 2
    page.mouse.move(x, y)
    expect(page.locator("#time-tip")).to_have_text("16:00–16:30")
    page.mouse.click(x, y)
    expect(page.locator(".inline-editor input")).to_be_focused()
    submit_inline(page, "练字")
    check_disk(run, "练字", DAY, 960, 30, "plan")
    for _ in range(5):
        ruler.focus()
        ruler.press("Enter")
        submit_inline(page, "密集日程 " + str(_))
    expect(page.locator(f'.cell[data-date="{DAY}"] .month-event')).to_have_count(3)
    expect(page.locator(f'.cell[data-date="{DAY}"] .more-events')).to_have_text("+7 项")
    page.get_by_role("button", name="11月11日日程详情", exact=True).click()
    expect(page.locator("#agenda .agenda-item")).to_have_count(10)
    expect(page.locator("#agenda").get_by_text("练字", exact=True)).to_be_visible()
    page.get_by_role("button", name="关闭当天日程", exact=True).click()
    expect(page.locator("#agenda")).not_to_be_visible()
    expect(page.locator('[data-view=month]')).to_have_attribute("aria-pressed", "true")
    choose_view(page, "day")
    expect(card(page, "练字")).to_have_count(1)

    page.get_by_role("button", name="补记时长", exact=True).click()
    expect(page.get_by_label("日期", exact=True)).to_have_value(DAY)
    page.get_by_label("事项名称", exact=True).fill("阅读四十分钟")
    page.get_by_label("时长（分钟）").fill("40")
    page.get_by_label("分类", exact=True).select_option("study")
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.locator("#panel")).not_to_be_visible()
    check_disk(run, "阅读四十分钟", DAY, None, 40, "actual")

    card(page, TITLE).click()
    page.get_by_label("设为重点").check()
    page.get_by_label("已完成").check()
    page.get_by_label("备注", exact=True).fill("核对中文、符号与跨视图同步。")
    page.get_by_label("分类", exact=True).select_option("work")
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.get_by_text("已成", exact=True)).to_have_count(1)
    item = check_disk(run, TITLE, DAY, 540, 30, "plan")
    assert item["focus"] and item["done"] and "跨视图同步" in item["notes"]
    card(page, TITLE).click()
    page.get_by_role("button", name="记为实际", exact=True).click()
    page.get_by_label("时长（分钟）").fill("25")
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.locator("#panel")).not_to_be_visible()
    check_disk(run, TITLE, DAY, 540, 25, "actual")

    choose_view(page, "week")
    expect(card(page, "阅读四十分钟")).to_have_count(1)
    page.get_by_role("button", name="统计", exact=True).click()
    expect(page.locator(".stats-totals strong")).to_have_text("合计 2小时5分钟")
    page.get_by_label("统计分类").select_option("study")
    expect(page.locator(".stats-totals strong")).to_have_text("合计 40分钟")
    page.get_by_label("统计类型").select_option("plan")
    expect(page.locator(".stats-totals strong")).to_have_text("合计 0分钟")
    page.get_by_role("button", name="关闭", exact=True).click()
    choose_view(page, "month")
    page.get_by_role("button", name="11月11日日程详情", exact=True).click()
    expect(page.locator("#agenda").get_by_text("阅读四十分钟", exact=True)).to_have_count(1)
    page.get_by_role("button", name="关闭当天日程", exact=True).click()
    page.get_by_role("button", name="统计", exact=True).click()
    expect(page.locator(".heatmap button")).to_have_count(30)
    page.get_by_role("button", name="11月11日 2小时5分钟", exact=True).click()
    expect(page.locator('[data-view=day]')).to_have_attribute("aria-pressed", "true")

    page.get_by_role("button", name="设置", exact=True).click()
    page.get_by_label("每周实际记录目标（小时，0 为关闭）").fill("2.5")
    page.get_by_role("button", name="＋ 新建分类", exact=True).click()
    page.get_by_label("分类名称", exact=True).last.fill("修习")
    page.get_by_label("分类颜色", exact=True).last.fill("#475744")
    page.get_by_role("button", name="保存设置", exact=True).click()
    expect(page.locator("#panel")).not_to_be_visible()
    data = run.contents()
    assert data["weeklyGoal"] == 150
    assert any(item["name"] == "修习" and item["color"] == "#475744" for item in data["categories"])
    choose_view(page, "week")
    page.get_by_role("button", name="统计", exact=True).click()
    expect(page.get_by_text("周目标 2小时30分钟 · 83%")).to_be_visible()
    page.get_by_role("button", name="关闭", exact=True).click()

    page.get_by_role("button", name="设置", exact=True).click()
    with page.expect_download() as download:
        page.get_by_role("button", name="导出备份", exact=True).click()
    backup = download.value.path().read_bytes()
    assert json.loads(backup)["entries"] == run.contents()["entries"]
    page.locator('input[type="file"]').set_input_files({"name": "坏备份.json", "mimeType": "application/json", "buffer": b"{bad"})
    expect(page.get_by_role("alert")).to_contain_text("无法识别")
    assert json.loads(backup)["entries"] == run.contents()["entries"]
    page.get_by_role("button", name="移除分类 学习", exact=True).click()
    page.get_by_role("button", name="保存设置", exact=True).click()
    expect(page.locator("#panel")).not_to_be_visible()
    assert check_disk(run, "阅读四十分钟", DAY, None, 40, "actual")["category"] == ""

    card(page, "练字").click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="删除", exact=True).click()
    expect(card(page, "练字")).to_have_count(0)
    page.get_by_role("button", name="设置", exact=True).click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('input[type="file"]').set_input_files({"name": "行记备份.json", "mimeType": "application/json", "buffer": backup})
    expect(page.locator("#panel")).not_to_be_visible()
    expect(card(page, "练字")).to_have_count(1)
    assert check_disk(run, "阅读四十分钟", DAY, None, 40, "actual")["category"] == "study"

    other = new_page(context, run, errors)
    choose_view(page, "month")
    page.get_by_role("button", name="11月11日日程详情", exact=True).click()
    open_slot(other, DAY, 690, "actual")
    submit_inline(other, "另一个窗口即时同步")
    expect(page.locator("#agenda").get_by_text("另一个窗口即时同步", exact=True)).to_have_count(1)
    page.get_by_role("button", name="关闭当天日程", exact=True).click()
    second = subprocess.run([run.exe, "--no-browser"], cwd=os.environ["TEMP"], timeout=5)
    assert second.returncode == 0 and run.process.poll() is None

    choose_view(page, "day")
    open_slot(page, DAY, 1020, "plan")
    page.locator(".inline-editor input").fill("不应丢失的草稿")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="周视图", exact=True).click()
    expect(page.locator(".inline-editor input")).to_have_value("不应丢失的草稿")
    page.locator(".inline-editor input").press("Escape")
    expect(page.locator(".inline-editor")).to_have_count(0)

    goto(page, "2026-11-30")
    open_slot(page, "2026-11-30", 1425, "actual")
    submit_inline(page, "月底跨夜")
    check_disk(run, "月底跨夜", "2026-11-30", 1425, 30, "actual")
    page.get_by_role("button", name="下一个周期", exact=True).click()
    expect(card(page, "月底跨夜")).to_have_count(1)
    expect(page.locator("#summary")).to_have_text("计划 0分钟　·　实际 15分钟")
    choose_view(page, "month")
    expect(page.locator("#period-label")).to_have_text("2026年12月")
    expect(page.locator('.cell[data-date="2026-12-01"] .event')).to_have_count(1)
    goto(page, "2028-02-29")
    expect(page.locator('.cell[data-date="2028-02-29"]')).to_have_count(1)
    page.get_by_role("button", name="下一个周期", exact=True).click()
    expect(page.locator("#period-label")).to_have_text("2028年3月")
    page.get_by_role("button", name="上一个周期", exact=True).click()
    expect(page.locator("#period-label")).to_have_text("2028年2月")
    page.get_by_role("button", name="今天", exact=True).click()
    expect(page.locator("#period-label")).to_have_text("2026年11月")

    samples = page.evaluate("""() => {
      const timings = [];
      for (let i = 0; i < 8; i++) {
        for (const name of ['day', 'week', 'month']) {
          const start = performance.now();
          document.querySelector('[data-view=' + name + ']').click();
          if (!document.querySelector('#workspace .' + name)) throw new Error('view did not switch');
          document.getElementById('workspace').getBoundingClientRect();
          timings.push(performance.now() - start);
        }
      }
      return timings;
    }""")
    assert max(samples) < 200, samples
    print(f"PASS: 24 consecutive view changes, worst DOM render and layout {max(samples):.1f} ms", flush=True)
    expect(page.locator(f'.cell[data-date="{DAY}"] .month-event')).to_have_count(3)
    expect(page.locator(f'.cell[data-date="{DAY}"] .more-events')).to_have_text("+10 项")
    if screenshots:
        for view in ["month", "week", "day"]:
            choose_view(page, view)
            page.screenshot(path=screenshots / f"{view}.png", animations="disabled")
        page.set_viewport_size({"width": 1024, "height": 768})
        choose_view(page, "month")
        assert page.locator("#workspace").evaluate("n => n.clientWidth === n.scrollWidth")
        page.screenshot(path=screenshots / "month-1024.png", animations="disabled")
        page.set_viewport_size({"width": 640, "height": 620})
        assert page.locator("#workspace").evaluate("n => n.scrollWidth > n.clientWidth")
        assert page.locator("body").evaluate("n => n.scrollWidth === n.clientWidth")
        expect(page.get_by_role("button", name="退出", exact=True)).to_be_visible()
    assert not errors, errors
    page.get_by_role("button", name="退出", exact=True).click()
    expect(page.get_by_text("行记已合卷", exact=True)).to_be_visible()
    expect(other.get_by_text("行记已合卷", exact=True)).to_be_visible()
    assert run.process.wait(timeout=10) == 0
    assert not run.session.exists()
    print("PASS: click / drag / ruler, IME, 3-view sync, edit / delete / focus / actual, settings, statistics, import / export, tabs, date edges, layout, and exit", flush=True)


def test_dense_month(context, run, screenshots):
    date = "2026-11-27"
    lengthy = "清河行程🏮" + "带上需要核对的材料" * 11 + "ABCDEFGHIJKLMNO" * 3
    notes = "长备注第一行\n" + "不间断记录" * 350 + "\n长备注末尾🏮"

    def entry(identifier, date, title, start, kind="plan", minutes=30, notes=""):
        return {"id": identifier, "date": date, "title": title, "kind": kind, "start": start,
                "minutes": minutes, "notes": notes, "category": "", "focus": False, "done": False}

    data = run.contents()
    data["entries"] = [
        entry(f"dense-{i:03}", date, lengthy if i == 0 else f"密集事项 {i:03}", 480 + i,
              "actual" if i % 3 == 0 else "plan")
        for i in range(240)
    ]
    data["entries"].extend([
        entry("overnight", "2026-11-26", "渡口跨夜", 1425, "actual"),
        entry("duration", date, "仅时长事项", None, "actual", 20, notes),
        *[entry(f"comparison-{i}", "2026-11-05", f"普通事项 {i}", 540 + i * 60) for i in range(3)],
    ])
    run.api("journal", "PUT", json.dumps(data, ensure_ascii=False).encode())
    errors = []
    page = new_page(context, run, errors)
    choose_view(page, "month")
    cell = page.locator(f'.cell[data-date="{date}"]')
    other_day = page.locator('.cell[data-date="2026-11-05"]')
    expect(cell.locator(".month-event")).to_have_count(3)
    expect(cell.locator(".more-events")).to_have_text("+239 项")
    expect(cell.get_by_text(lengthy, exact=True)).to_have_count(1)
    for width, height in ((1440, 900), (1024, 768), (640, 620)):
        page.set_viewport_size({"width": width, "height": height})
        assert abs(cell.bounding_box()["height"] - other_day.bounding_box()["height"]) <= 1
        assert cell.evaluate("""cell => cell.scrollWidth <= cell.clientWidth + 1 &&
            [...cell.querySelectorAll('.month-event')].every(card => card.offsetHeight <= 28)""")
        assert cell.get_by_text(lengthy, exact=True).evaluate("el => el.scrollWidth > el.clientWidth")

    page.set_viewport_size({"width": 1024, "height": 768})
    more = cell.locator(".more-events")
    workspace = page.locator("#workspace")
    workspace.evaluate("el => { el.scrollTop = Math.min(84, el.scrollHeight - el.clientHeight); }")
    more.scroll_into_view_if_needed()
    position = workspace.evaluate("el => [el.scrollLeft, el.scrollTop]")
    assert position[1] > 0
    if screenshots:
        page.screenshot(path=screenshots / "month-summary.png", animations="disabled")
    more.click()
    agenda = page.locator("#agenda")
    centered = """() => {
      const {x, y, width, height} = document.querySelector('#agenda').getBoundingClientRect();
      return Math.abs(x * 2 + width - innerWidth) <= 2 &&
        Math.abs(y * 2 + height - innerHeight) <= 2 && y >= 20 && x >= 14;
    }"""
    page.wait_for_function(centered)
    expect(agenda.locator(".agenda-count")).to_have_text("共 242 项")
    expect(agenda.locator(".agenda-item").first).to_contain_text("00:00–00:15")
    expect(agenda.locator(".agenda-item").first).to_contain_text("跨日延续")
    expect(agenda.get_by_text(lengthy, exact=True)).to_be_visible()
    assert agenda.locator(".agenda-scroll").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    if screenshots:
        page.screenshot(path=screenshots / "month-agenda.png", animations="disabled")
    page.set_viewport_size({"width": 640, "height": 620})
    page.wait_for_function(centered)
    expect(agenda.get_by_role("button", name="下一页")).to_be_in_viewport()
    page.set_viewport_size({"width": 1024, "height": 768})
    page.wait_for_function(centered)
    assert agenda.locator(".agenda-scroll").evaluate("el => el.scrollHeight > el.clientHeight")

    seen = []
    for page_number, size in enumerate((50, 50, 50, 50, 42)):
        expect(agenda.locator(".agenda-item")).to_have_count(size)
        seen.extend(agenda.locator("[data-agenda-entry]").evaluate_all("els => els.map(el => el.dataset.agendaEntry)"))
        if page_number < 4:
            agenda.get_by_role("button", name="下一页").click()
    assert len(seen) == len(set(seen)) == 242
    expect(agenda.get_by_role("button", name="下一页")).to_be_disabled()
    expect(agenda.locator(".agenda-item").last.locator(".agenda-item-notes")).to_have_text(notes)
    assert agenda.locator(".agenda-scroll").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    agenda.get_by_role("button", name="编辑 仅时长事项", exact=True).click()
    page.get_by_label("备注", exact=True).fill("月历内编辑成功🏮")
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.locator("#panel")).not_to_be_visible()
    expect(agenda.locator(".agenda-range")).to_have_text("201–242 / 242 项")
    expect(agenda.get_by_text("月历内编辑成功🏮", exact=True)).to_be_visible()
    agenda.get_by_role("button", name="上一页").click()
    expect(agenda.locator(".agenda-range")).to_have_text("151–200 / 242 项")
    page.keyboard.press("Escape")
    expect(agenda).not_to_be_visible()
    expect(more).to_be_focused()
    assert workspace.evaluate("el => [el.scrollLeft, el.scrollTop]") == position
    expect(page.locator('[data-view=month]')).to_have_attribute("aria-pressed", "true")

    page.locator('.cell[data-date="2026-11-28"] .date-number').click()
    expect(agenda.get_by_text("这一天还没有事项。", exact=True)).to_be_visible()
    page.wait_for_function(centered)
    assert agenda.bounding_box()["height"] < 260
    page.get_by_role("button", name="关闭当天日程").click()
    expect(agenda).not_to_be_visible()
    assert not errors, errors
    page.close()
    print("PASS: 242 items in one day, capped month cells, long Unicode titles and notes, all agenda pages, edit refresh, and return to month position", flush=True)


def test_drive(context, run):
    errors = []
    page = new_page(context, run, errors)
    assert any(item["title"] == TITLE for item in run.contents()["entries"])
    expect(card(page, TITLE)).to_have_count(2)
    old = run.backup.read_bytes()
    run.backup.unlink()
    run.backup.mkdir()
    try:
        open_slot(page, DAY, 1140, "actual")
        page.locator(".inline-editor input").fill("硬盘写入重试")
        page.locator(".inline-editor input").press("Enter")
        expect(page.locator("#status")).to_contain_text("未能保存到硬盘")
        expect(page.locator(".inline-editor input")).to_have_value("硬盘写入重试")
        assert not any(item["title"] == "硬盘写入重试" for item in run.contents()["entries"])
    finally:
        run.backup.rmdir()
        run.backup.write_bytes(old)
    submit_inline(page, "硬盘写入重试")
    check_disk(run, "硬盘写入重试", DAY, 1140, 30, "actual")
    assert not errors, errors
    run.stop()
    previous = json.loads(run.backup.read_text(encoding="utf-8"))
    run.main.write_bytes(b"broken test journal")
    restart = Running(run.exe)
    try:
        page = new_page(context, restart, errors)
        expect(page.locator("#recovery")).to_be_visible()
        data = json.loads(restart.api("journal"))["journal"]
        assert data == previous
        open_slot(page, DAY, 1200, "actual")
        submit_inline(page, "备份恢复后继续写")
        expect(page.locator("#recovery")).not_to_be_visible()
        check_disk(restart, "备份恢复后继续写", DAY, 1200, 30, "actual")
        assert not errors, errors
    finally:
        restart.stop()
    print("PASS: USB read/write after relocation, failed write keeps draft, retry, damaged primary recovery and re-save", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("--usb", default="E:/", type=Path)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(exist_ok=True, parents=True)
    workspace = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="journal-qa-", dir=workspace) as local, tempfile.TemporaryDirectory(prefix="journal-qa-", dir=args.usb) as usb:
        source = install(args.exe, Path(local) / "测试 路径")
        with sync_playwright() as p:
            chrome = p.chromium.launch(executable_path=CHROME, headless=True)
            context = chrome.new_context(locale="zh-CN", timezone_id="Asia/Shanghai", viewport={"width": 1440, "height": 900})
            external = []
            def deny_external(route):
                if route.request.url.startswith("http://127.0.0.1:"):
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()
            context.route("**/*", deny_external)
            dense = Running(install(args.exe, Path(local) / "密集月历"))
            try:
                test_dense_month(context, dense, args.screenshots)
            finally:
                dense.stop()
            run = Running(source)
            try:
                test_workflow(context, run, args.screenshots)
                assert not external, external
            finally:
                run.stop()
                chrome.close()
            destination = Path(usb) / "换盘符 与 中文路径" / "完整工具"
            for attempt in range(3):
                try:
                    shutil.copytree(source.parent, destination, dirs_exist_ok=True)
                    break
                except (OSError, shutil.Error):
                    if attempt == 2:
                        raise
                    time.sleep(1)
            edge = p.chromium.launch(executable_path=EDGE, headless=True)
            context = edge.new_context(locale="en-US", timezone_id="Asia/Shanghai", viewport={"width": 1280, "height": 800})
            run = Running(destination / source.name)
            try:
                test_drive(context, run)
            finally:
                run.stop()
                edge.close()
    print("ALL RELEASE CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
