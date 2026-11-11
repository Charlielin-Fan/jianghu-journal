import {
  weekdays, uncategorized, clock, durationText, dateRange, dateKey, offset, period, periodLabel, weekStart,
  shortDate, weekday, summarize,
} from './model.js';

export function makePanels({ node, button, panel, agenda, state, commit, addTo, navigate, render, inferCategory, timeSpan }) {
  let dirty = false;
  let changing = false;
  let agendaView = null;
  const agendaPageSize = 50;

  function close(force = false) {
    if (changing || state.busy) return;
    if (!force && dirty && !confirm('还有未保存的改动。要放弃吗？')) return;
    dirty = false;
    panel.close();
  }

  panel.addEventListener('cancel', event => {
    event.preventDefault();
    close();
  });

  function show(title, wide = false) {
    dirty = false;
    const head = node('div', 'dialog-head');
    const heading = node('h2', '', title);
    heading.id = 'panel-heading';
    head.append(heading, button('×', () => close(), 'dialog-close', '关闭'));
    panel.setAttribute('aria-labelledby', heading.id);
    panel.classList.toggle('wide', wide);
    panel.replaceChildren(head);
    if (!panel.open) panel.showModal();
  }

  function dayAgenda(date, fromMore) {
    agendaView = { date, fromMore, page: 0, revision: -1 };
    drawAgenda();
    agenda.showModal();
  }

  function refreshAgenda() {
    if (agenda.open && agendaView.revision !== state.data.revision) drawAgenda(true);
  }

  agenda.addEventListener('close', () => {
    if (agenda.open) return;
    const previous = agendaView;
    agendaView = null;
    if (!previous || state.closed || state.view !== 'month') return;
    const cell = document.querySelector('.cell[data-date="' + previous.date + '"]');
    const trigger = previous.fromMore ? cell?.querySelector('.more-events') : null;
    (trigger ?? cell?.querySelector('.date-number'))?.focus({ preventScroll: true });
  });

  function drawAgenda(preserveScroll = false) {
    const { date } = agendaView;
    const items = state.index.get(date) ?? [];
    const pages = Math.max(1, Math.ceil(items.length / agendaPageSize));
    agendaView.page = Math.min(agendaView.page, pages - 1);
    agendaView.revision = state.data.revision;
    const start = agendaView.page * agendaPageSize;
    const end = Math.min(items.length, start + agendaPageSize);
    const previousScroll = preserveScroll ? agenda.querySelector('.agenda-scroll')?.scrollTop ?? 0 : 0;
    const previousEntry = preserveScroll && agenda.contains(document.activeElement)
      ? document.activeElement.dataset.agendaEntry : null;

    const heading = node('div');
    const title = node('h2', '', shortDate(date) + ' ' + weekday(date));
    title.id = 'agenda-heading';
    heading.append(title, node('p', 'agenda-count', '共 ' + items.length + ' 项'));
    const head = node('header', 'dialog-head agenda-head');
    const closeAgenda = button('×', () => agenda.close(), 'dialog-close', '关闭当天日程');
    closeAgenda.autofocus = true;
    head.append(heading, closeAgenda);

    const scroller = node('div', 'agenda-scroll');
    scroller.tabIndex = 0;
    scroller.setAttribute('role', 'region');
    scroller.setAttribute('aria-label', '当天事项列表');
    const list = node('ul', 'agenda-list');
    const categoryNames = new Map(state.data.categories.map(item => [item.id, item.name]));
    for (const piece of items.slice(start, end)) {
      const item = piece.entry;
      const row = node('li', 'agenda-item');
      const layout = node('div', 'agenda-item-head');
      const description = node('div', 'agenda-item-description');
      const details = [
        piece.start === null ? '仅记时长 · ' + durationText(piece.minutes) : timeSpan(piece.start, piece.minutes),
        item.kind === 'plan' ? '计划' : '实际',
        categoryNames.get(item.category) ?? uncategorized.name,
      ];
      if (piece.continues) details.push('跨日延续');
      if (item.done) details.push('已完成');
      else if (item.focus) details.push('重点');
      description.append(node('p', 'agenda-item-meta', details.join(' · ')),
        node('h3', 'agenda-item-title', item.title));
      const edit = button('编辑', () => entry(item), 'agenda-edit', '编辑 ' + item.title);
      edit.dataset.agendaEntry = item.id;
      layout.append(description, edit);
      row.append(layout);
      if (item.notes) row.append(node('p', 'agenda-item-notes', item.notes));
      list.append(row);
    }
    if (items.length) scroller.append(list);
    else scroller.append(node('p', 'hint agenda-empty', '这一天还没有事项。'));
    agenda.replaceChildren(head, scroller);
    if (pages > 1) {
      const pager = node('nav', 'agenda-pager');
      pager.setAttribute('aria-label', '当天事项翻页');
      const changePage = direction => {
        agendaView.page += direction;
        drawAgenda();
        agenda.querySelector('.agenda-scroll').focus({ preventScroll: true });
      };
      const previous = button('上一页', () => changePage(-1));
      const next = button('下一页', () => changePage(1));
      previous.disabled = agendaView.page === 0;
      next.disabled = agendaView.page === pages - 1;
      const range = node('span', 'agenda-range', (start + 1) + '–' + end + ' / ' + items.length + ' 项');
      range.setAttribute('aria-live', 'polite');
      pager.append(previous, range, next);
      agenda.append(pager);
    }
    scroller.scrollTop = previousScroll;
    if (previousEntry) {
      const edit = agenda.querySelector('[data-agenda-entry="' + CSS.escape(previousEntry) + '"]');
      (edit ?? scroller).focus({ preventScroll: true });
    }
  }

  function field(label, control, className = '') {
    const wrapper = node('label', className);
    if (!control.hasAttribute('aria-label')) control.setAttribute('aria-label', label);
    wrapper.append(node('span', '', label), control);
    return wrapper;
  }

  function input(type, value = '', attributes = {}) {
    const control = node('input');
    control.type = type;
    for (const [key, val] of Object.entries(attributes)) control[key] = val;
    control.value = value;
    return control;
  }

  function option(value, name) {
    const result = node('option', '', name);
    result.value = value;
    return result;
  }

  function formNode() {
    const form = node('form', 'form');
    form.addEventListener('input', () => { dirty = true; });
    form.addEventListener('keydown', event => {
      if (event.key === 'Enter' && (event.isComposing || event.keyCode === 229)) event.preventDefault();
    });
    return form;
  }

  function saveButton(label = '保存') {
    const save = node('button', 'primary', label);
    save.type = 'submit';
    return save;
  }

  function formError() {
    const error = node('p', 'form-error');
    error.setAttribute('role', 'alert');
    return error;
  }

  async function perform(action, error) {
    if (changing) return;
    changing = true;
    error.textContent = '';
    const controls = Array.from(panel.querySelectorAll('button,input,select,textarea')).filter(control => !control.disabled);
    for (const control of controls) control.disabled = true;
    try {
      await action();
      dirty = false;
      changing = false;
      close(true);
      render();
    } catch (problem) {
      error.textContent = problem.message;
    } finally {
      changing = false;
      for (const control of controls) control.disabled = false;
    }
  }

  function entry(original) {
    const exists = Boolean(original.id);
    const entryId = original.id ?? crypto.randomUUID();
    const timed = original.start !== null;
    const isPlan = original.kind === 'plan';
    show(exists ? '事项详情' : timed ? '记为实际' : '补记时长');
    const form = formNode();
    const title = input('text', original.title, { required: true, maxLength: 160 });
    title.autocomplete = 'off';
    const date = input('date', original.date, { required: true, min: '1000-01-01', max: '9999-12-31' });
    const category = node('select');
    category.append(option('', '未分类'));
    for (const item of state.data.categories) category.append(option(item.id, item.name));
    category.value = original.category;
    const notes = node('textarea');
    notes.value = original.notes;
    notes.rows = 2;
    notes.maxLength = 2000;
    const start = input('time', timed ? clock(original.start) : '', { required: timed });
    const minutes = input('number', original.minutes, { required: true, min: 1, max: 1440, step: 1 });
    const timing = node('div', 'form-row');
    if (timed) timing.append(field('开始时间', start));
    timing.append(field('时长（分钟）', minutes));
    const details = node('div', 'form-row');
    details.append(field('日期', date), field('分类', category));
    const focus = input('checkbox');
    focus.checked = original.focus ?? false;
    const done = input('checkbox');
    done.checked = original.done ?? false;
    const checks = node('div', 'form-row');
    if (isPlan) checks.append(field('设为重点', focus, 'check'), field('已完成', done, 'check'));
    const error = formError();
    const actions = node('div', 'dialog-actions');
    function assertOriginal(data) {
      const current = data.entries.find(item => item.id === original.id);
      if (!current || JSON.stringify(current) !== JSON.stringify(original)) {
        throw new Error('这条事项已在另一窗口修改。请关闭详情后重新打开');
      }
    }
    if (exists) {
      actions.append(button('删除', () => {
        if (!confirm('删除这条事项？')) return;
        perform(() => commit(data => {
          assertOriginal(data);
          data.entries = data.entries.filter(item => item.id !== original.id);
        }), error);
      }, 'danger'));
    }
    if (exists && isPlan) {
      actions.append(button('记为实际', () => {
        if (dirty && !confirm('计划的改动还未保存。以当前填写的内容新建实际记录吗？')) return;
        const values = form.checkValidity() ? readEntry() : original;
        const { id, ...copy } = values;
        entry({ ...copy, kind: 'actual', focus: false, done: false });
      }));
    }
    actions.append(saveButton());
    form.append(field('事项名称', title), details, timing, checks, field('备注', notes), error, actions);
    panel.append(form);
    title.focus();
    function readEntry() {
      const [hours, mins] = start.value.split(':').map(Number);
      return {
        id: entryId,
        date: date.value, title: title.value.trim(), kind: original.kind,
        start: timed ? hours * 60 + mins : null, minutes: Number(minutes.value),
        category: category.value, notes: notes.value.trim(),
        focus: isPlan && focus.checked, done: isPlan && done.checked,
      };
    }
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!title.value.trim()) {
        error.textContent = '请填写事项名称';
        title.focus();
        return;
      }
      const updated = readEntry();
      if (!exists && !category.value && !category.dataset.chosen) updated.category = inferCategory(updated.title);
      perform(() => commit(data => {
        if (exists) {
          assertOriginal(data);
          data.entries[data.entries.findIndex(item => item.id === updated.id)] = updated;
        } else addTo(data, updated);
      }), error);
    });
    category.addEventListener('change', () => { category.dataset.chosen = 'true'; });
  }

  function jump() {
    show('跳转到日期');
    const form = node('form', 'form');
    const date = input('date', state.date, { required: true, min: '1000-01-01', max: '9999-12-31' });
    const actions = node('div', 'dialog-actions');
    actions.append(saveButton('前往'));
    form.append(field('日期', date), actions);
    panel.append(form);
    form.addEventListener('submit', event => {
      event.preventDefault();
      close(true);
      navigate(state.view, date.value);
    });
    date.focus();
  }

  function settings() {
    show('设置');
    const form = formNode();
    const base = state.data;
    const goal = input('number', base.weeklyGoal / 60, { required: true, min: 0, max: 168, step: 0.5 });
    const list = node('div');
    const error = formError();
    function addCategory(item) {
      const row = node('div', 'category-row');
      row.dataset.id = item.id;
      const name = input('text', item.name, { maxLength: 24, required: true, placeholder: '分类名称' });
      const color = input('color', item.color);
      name.setAttribute('aria-label', '分类名称');
      color.setAttribute('aria-label', '分类颜色');
      row.append(name, color, button('移除', () => {
        dirty = true;
        row.remove();
      }, 'danger', '移除分类 ' + item.name));
      list.append(row);
      return name;
    }
    for (const category of base.categories) addCategory(category);
    const add = button('＋ 新建分类', () => {
      if (list.children.length >= 100) {
        error.textContent = '最多可添加 100 个分类';
        return;
      }
      dirty = true;
      addCategory({ id: crypto.randomUUID(), name: '', color: '#696D53' }).focus();
    });
    const actions = node('div', 'dialog-actions');
    actions.append(saveButton('保存设置'));
    form.append(field('每周实际记录目标（小时，0 为关闭）', goal),
      node('h3', '', '分类'), list, node('p', 'hint', '移除分类会保留事项，改为未分类。'), add, error, actions);
    form.addEventListener('submit', event => {
      event.preventDefault();
      const categories = Array.from(list.children, row => ({
        id: row.dataset.id, name: row.querySelector('input[type="text"]').value.trim(),
        color: row.querySelector('input[type="color"]').value,
      }));
      if (categories.some(item => !item.name) || new Set(categories.map(item => item.name)).size !== categories.length) {
        error.textContent = '分类名称不能为空或重复';
        return;
      }
      const ids = new Set(categories.map(item => item.id));
      const weeklyGoal = Math.round(Number(goal.value) * 60);
      perform(() => commit(data => {
        if (JSON.stringify(data.categories) !== JSON.stringify(base.categories) || data.weeklyGoal !== base.weeklyGoal) {
          throw new Error('另一窗口修改了设置。请关闭后重新打开');
        }
        data.categories = categories;
        data.weeklyGoal = weeklyGoal;
        for (const item of data.entries) if (!ids.has(item.category)) item.category = '';
      }), error);
    });
    const backup = node('section', 'settings-section');
    const controls = node('div');
    const file = input('file', '', { accept: '.json,application/json' });
    file.hidden = true;
    file.addEventListener('change', async () => {
      const selected = file.files[0];
      file.value = '';
      if (!selected) return;
      if (selected.size > 16 * 1024 * 1024) {
        error.textContent = '备份文件过大';
        return;
      }
      let imported;
      try {
        imported = JSON.parse(await selected.text());
        if (imported?.version !== 1 || !Array.isArray(imported.entries) ||
            !Array.isArray(imported.categories) || !Number.isInteger(imported.weeklyGoal)) throw new Error();
      } catch {
        error.textContent = '无法识别此备份文件，当前行记没有改动';
        return;
      }
      if (!confirm('恢复会用这个备份替换当前行记（' + imported.entries.length + ' 条事项）。确定恢复？')) return;
      const revision = state.data.revision;
      perform(() => commit(data => {
        if (data.revision !== revision) throw new Error('另一窗口刚刚保存了内容，请重新确认恢复');
        data.version = imported.version;
        data.entries = imported.entries;
        data.categories = imported.categories;
        data.weeklyGoal = imported.weeklyGoal;
      }), error);
    });
    controls.append(button('导出备份', () => {
      const contents = JSON.stringify(state.data, null, 2) + '\n';
      const url = URL.createObjectURL(new Blob([contents], { type: 'application/json;charset=utf-8' }));
      const link = node('a');
      link.href = url;
      link.download = '江湖行记备份-' + dateKey(new Date()) + '.json';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }), button('恢复备份', () => file.click()), file);
    backup.append(node('h3', '', '移动硬盘上的数据'), controls,
      node('p', 'hint', '事项自动保存到程序旁的「数据」文件夹。导出的备份可以另存到其他硬盘。'));
    form.append(backup);
    panel.append(form);
  }

  function stats() {
    show(periodLabel(state.view, state.date) + ' · 统计', true);
    const days = dateRange(...period(state.view, state.date));
    const isWeek = state.view === 'week';
    const kind = node('select');
    kind.setAttribute('aria-label', '统计类型');
    kind.append(option('actual', '实际记录'), option('plan', '计划安排'));
    const category = node('select');
    category.setAttribute('aria-label', '统计分类');
    category.append(option('all', '全部分类'));
    for (const item of [uncategorized, ...state.data.categories]) category.append(option(item.id, item.name));
    const controls = node('div', 'form-row form');
    controls.append(field('类型', kind), field('分类', category));
    const body = node('div', 'stats-body');
    panel.append(controls, body);
    const categoryInfo = id => state.data.categories.find(item => item.id === id) ?? uncategorized;
    function drill(date) {
      close(true);
      navigate('day', date);
    }
    function update() {
      const report = summarize(state.index, days, kind.value);
      const selection = category.value;
      const shown = report.daily.map(day => {
        if (selection === 'all') return day;
        const total = day.categories.get(selection) ?? 0;
        return { ...day, total, categories: new Map([[selection, total]]) };
      });
      const total = shown.reduce((sum, day) => sum + day.total, 0);
      const peak = Math.max(1, ...shown.map(day => day.total));
      const totals = node('div', 'stats-totals');
      totals.append(node('strong', '', '合计 ' + durationText(total)),
        node('span', '', shown.filter(day => day.total > 0).length + ' 天有记录'));
      if (isWeek && kind.value === 'actual' && selection === 'all' && state.data.weeklyGoal) {
        totals.append(node('span', '', '周目标 ' + durationText(state.data.weeklyGoal) +
          ' · ' + Math.round(total / state.data.weeklyGoal * 100) + '%'));
      }
      const chart = node('section');
      chart.append(node('h3', '', isWeek ? '每日时间分布' : '每日时长'));
      if (isWeek) {
        const graph = node('div', 'week-chart');
        for (const day of shown) {
          const item = button('', () => drill(day.date), '', shortDate(day.date) + ' ' + durationText(day.total));
          const stack = node('span', 'stack');
          for (const [id, minutes] of day.categories) {
            const part = node('span');
            part.style.height = minutes / peak * 100 + '%';
            part.style.background = categoryInfo(id).color;
            stack.append(part);
          }
          item.title = shortDate(day.date) + ' · ' + durationText(day.total);
          item.append(stack, node('span', '', weekday(day.date).slice(1)));
          graph.append(item);
        }
        chart.append(graph);
      } else {
        const map = node('div', 'heatmap');
        for (const day of weekdays) map.append(node('span', 'hint', day));
        const first = weekStart(days[0]);
        for (let padding = first; padding < days[0]; padding = offset(padding, 1)) map.append(node('span'));
        for (const day of shown) {
          const item = button(String(Number(day.date.slice(-2))), () => drill(day.date), '',
            shortDate(day.date) + ' ' + durationText(day.total));
          item.title = shortDate(day.date) + ' · ' + durationText(day.total);
          if (day.total) item.style.background = 'color-mix(in srgb, #a94f37 ' + (12 + day.total / peak * 42) + '%, #fff5e1)';
          map.append(item);
        }
        chart.append(map);
      }
      const breakdown = node('section', 'breakdown');
      breakdown.append(node('h3', '', '分类时长'));
      for (const [id, minutes] of [...report.categories].sort((a, b) => b[1] - a[1])) {
        if (selection !== 'all' && id !== selection) continue;
        const item = categoryInfo(id);
        const row = node('div', 'breakdown-row');
        const bar = node('span', 'bar');
        const fill = node('span');
        fill.style.width = minutes / Math.max(1, total) * 100 + '%';
        fill.style.background = item.color;
        bar.append(fill);
        row.append(button(item.name, () => {
          category.value = id;
          update();
        }), bar, node('span', '', durationText(minutes)));
        breakdown.append(row);
      }
      if (!total) breakdown.append(node('p', 'hint', '这个范围还没有记录。'));
      body.replaceChildren(totals, chart, breakdown);
    }
    kind.addEventListener('change', update);
    category.addEventListener('change', update);
    update();
  }

  return { entry, dayAgenda, refreshAgenda, jump, settings, stats, hasChanges: () => dirty };
}
