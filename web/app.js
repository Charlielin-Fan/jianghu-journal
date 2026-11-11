import {
  weekdays, uncategorized, clock, durationText, dateKey, fromKey, offset, moveMonth, period,
  shortDate, weekday, periodLabel, dateRange, calendarDays, indexedEntries, summarize, arrange,
} from './model.js';
import { makePanels } from './panels.js';
import { reflectionFor } from './reflections.js';

const get = selector => document.querySelector(selector);
const workspace = get('#workspace');
const status = get('#status');
const tooltip = get('#time-tip');
const panel = get('#panel');
const agenda = get('#agenda');
const tab = new BroadcastChannel('jianghu-journal');
const state = { data: null, index: new Map(), date: dateKey(new Date()), view: 'day', filter: 'all', draft: null, busy: false, closed: false };
const desktop = new URLSearchParams(location.search).get('desktop') === '1';
document.documentElement.classList.toggle('desktop', desktop);
const scrollPositions = new Map();
let remoteRevision = 0;
let statusTimer;
let reflectionTimer;
let selection;
let hovering = null;

function node(tag, className = '', text = '') {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== '') result.textContent = text;
  return result;
}

function button(text, handler, className = '', label = '') {
  const result = node('button', className, text);
  result.type = 'button';
  if (label) result.setAttribute('aria-label', label);
  result.addEventListener('click', handler);
  return result;
}

function setStatus(text, error = false) {
  clearTimeout(statusTimer);
  status.textContent = text;
  status.classList.toggle('error', error);
  if (!error) statusTimer = setTimeout(() => { status.textContent = ''; }, 3600);
}

function installData(data) {
  if (state.data && data.revision < state.data.revision) return;
  state.data = data;
  state.index = indexedEntries(data.entries);
}

async function reload() {
  const response = await fetch('api/journal', { cache: 'no-store' });
  if (!response.ok) throw new Error('无法读取行记');
  const result = await response.json();
  installData(result.journal);
  get('#recovery').hidden = !result.recovered;
}

async function commit(change) {
  if (state.busy || state.closed) throw new Error('正在保存或退出，请稍候');
  state.busy = true;
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      const next = structuredClone(state.data);
      change(next);
      const response = await fetch('api/journal', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(next),
      });
      const result = await response.json();
      if (response.status === 409) {
        installData(result.journal);
        continue;
      }
      if (!response.ok) throw new Error(result.message ?? '保存失败，请重试');
      installData(result.journal);
      get('#recovery').hidden = true;
      tab.postMessage({ revision: state.data.revision });
      setStatus('已保存到硬盘');
      return;
    }
    throw new Error('另一窗口正在保存，请稍后重试');
  } finally {
    state.busy = false;
  }
}

function addTo(data, entry) {
  if (entry.category && !data.categories.some(category => category.id === entry.category)) {
    throw new Error('该分类已被移除，请重新选择');
  }
  const existing = data.entries.find(item => item.id === entry.id);
  if (existing) {
    if (Object.keys(entry).every(key => existing[key] === entry[key])) return;
    throw new Error('上一次提交已保存。请关闭输入框后点击该事项修改');
  }
  data.entries.push(entry);
}

function category(id) {
  return state.data.categories.find(item => item.id === id) ?? uncategorized;
}

function inferCategory(title) {
  return [...state.data.entries].reverse().find(entry =>
    entry.title === title && entry.category && category(entry.category).id === entry.category)?.category ?? '';
}

function pieces(date, kind = state.filter) {
  return (state.index.get(date) ?? []).filter(piece => kind === 'all' || piece.entry.kind === kind);
}

function newKind() {
  return state.filter === 'actual' ? 'actual' : 'plan';
}

function timeSpan(start, minutes) {
  if (start === null) return durationText(minutes);
  const end = start + minutes;
  return clock(start) + '–' + (end <= 1440 ? clock(end) : '次日' + clock(end - 1440));
}

function eventNode(piece, type) {
  const { entry, start, minutes } = piece;
  const isMonth = type === 'month-event';
  const time = timeSpan(start, minutes);
  const mark = entry.done ? '已成' : entry.focus ? '重点' : '';
  const card = button('', () => openPanel(() => panels.entry(entry)), 'event ' + type + ' ' + entry.kind,
    entry.title + '，' + (entry.kind === 'plan' ? '计划' : '实际') + '，' + time + (mark ? '，' + mark : ''));
  card.dataset.entry = entry.id;
  card.dataset.kind = entry.kind;
  const color = entry.category ? category(entry.category).color : entry.kind === 'plan' ? '#A76632' : '#3D7F69';
  card.style.setProperty('--event', color);
  card.title = (piece.continues ? '跨日 · ' : '') + time + ' · ' + entry.title;
  const title = node('span', 'title', entry.title);
  const when = node('span', 'time', start === null ? time : isMonth ? clock(start) : time);
  if (isMonth) card.append(when, title);
  else card.append(title, when);
  if (type === 'time-event') {
    when.classList.add('full-time');
    card.append(node('span', 'time short-time', clock(start)));
  }
  if (mark) card.append(node('span', 'seal', mark));
  if (isMonth && entry.kind === 'actual' && start !== null) card.append(node('span', 'kind-label', '实'));
  return card;
}

function setToolTip(text, x, y) {
  tooltip.textContent = text;
  tooltip.hidden = false;
  tooltip.style.left = Math.max(4, Math.min(x + 13, innerWidth - tooltip.offsetWidth - 6)) + 'px';
  tooltip.style.top = Math.max(4, y - 32) + 'px';
}

function hideTip() {
  tooltip.hidden = true;
  hovering?.remove();
  hovering = null;
}

function clearDraft() {
  if (!state.draft) return;
  state.draft.form.remove();
  state.draft.host.classList.remove('active');
  state.draft = null;
}

function canLeave() {
  if (state.busy) return false;
  return !state.draft?.input.value.trim() || confirm('这条事项还没保存。要放弃这次输入吗？');
}

function openPanel(action) {
  if (!state.data || !canLeave()) return;
  clearDraft();
  action();
}

function beginEntry(host, date, kind, start, minutes, isMonth) {
  if (state.busy || !canLeave()) return;
  clearDraft();
  hideTip();
  const form = node('form', 'inline-editor' + (isMonth ? ' month-editor' : ''));
  const id = crypto.randomUUID();
  const input = node('input');
  input.placeholder = '写下事项';
  input.setAttribute('aria-label', '事项名称');
  input.autocomplete = 'off';
  input.maxLength = 160;
  input.required = true;
  const time = node('span', 'time', isMonth ? clock(start) : timeSpan(start, minutes));
  const save = node('button', '', '↵');
  save.type = 'submit';
  save.title = '回车保存';
  save.setAttribute('aria-label', '保存事项');
  if (isMonth) form.append(time, input, save);
  else {
    form.append(input, time, save);
    form.style.top = Math.min(97.4, start / 14.4) + '%';
  }
  host.classList.add('active');
  host.append(form);
  state.draft = { form, input, host };
  input.focus({ preventScroll: true });
  form.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  input.addEventListener('keydown', event => {
    if (event.isComposing || event.keyCode === 229) {
      if (event.key === 'Enter') event.preventDefault();
      return;
    }
    if (event.key === 'Escape' && !state.busy) {
      clearDraft();
      host.querySelector('.ruler')?.focus({ preventScroll: true });
    }
  });
  let composing = false;
  input.addEventListener('compositionstart', () => { composing = true; });
  input.addEventListener('compositionend', () => { composing = false; });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (composing || state.busy) return;
    const title = input.value.trim();
    if (!title) {
      input.focus();
      return;
    }
    save.disabled = true;
    input.readOnly = true;
    const entry = {
      id, date, kind, start, minutes, title,
      category: inferCategory(title), notes: '', focus: false, done: false,
    };
    try {
      await commit(data => addTo(data, entry));
      clearDraft();
      if (state.view === 'week' || state.view === 'month' && date.slice(0, 7) === state.date.slice(0, 7)) {
        state.date = date;
      }
      render();
      const saved = host.dataset.date === date
        ? workspace.querySelector('[data-date="' + date + '"] [data-entry="' + id + '"]')
        : null;
      if (saved && matchMedia('(prefers-reduced-motion: no-preference)').matches) {
        saved.classList.add('just-saved');
        saved.addEventListener('animationend', () => saved.classList.remove('just-saved'), { once: true });
      }
    } catch (error) {
      setStatus(error.message, true);
      save.disabled = false;
      input.readOnly = false;
      input.focus();
    }
  });
}

function attachLane(lane, date, kind) {
  const pointerMinute = y => {
    const bounds = lane.getBoundingClientRect();
    return Math.min(1440, Math.max(0, (y - bounds.top) / bounds.height * 1440));
  };
  const getMinute = y => Math.min(1425, Math.floor(pointerMinute(y) / 15) * 15);
  lane.addEventListener('pointerdown', event => {
    if (event.target !== lane || event.button !== 0 || state.busy) return;
    event.preventDefault();
    lane.setPointerCapture(event.pointerId);
    const ghost = node('div', 'ghost');
    lane.append(ghost);
    selection = { lane, id: event.pointerId, start: getMinute(event.clientY), y: event.clientY, ghost };
    showSelection(event);
  });
  function showSelection(event) {
    const start = getMinute(event.clientY);
    const selected = selection?.lane === lane ? selection : null;
    const origin = selected?.start ?? start;
    const dragging = selected && Math.abs(event.clientY - selected.y) > 8;
    const end = Math.round(pointerMinute(event.clientY) / 15) * 15;
    const from = dragging ? Math.min(origin, end) : start;
    const to = dragging ? Math.max(origin, end, from + 15) : start + 30;
    if (selected) {
      selected.ghost.style.top = from / 14.4 + '%';
      selected.ghost.style.height = (to - from) / 14.4 + '%';
    } else if (!state.draft) {
      if (hovering?.parentElement !== lane) {
        hovering?.remove();
        hovering = node('div', 'hover-slot');
        lane.append(hovering);
      }
      hovering.style.top = from / 14.4 + '%';
      hovering.style.height = (to - from) / 14.4 + '%';
    }
    setToolTip(timeSpan(from, to - from), event.clientX, event.clientY);
    return { from, to };
  }
  lane.addEventListener('pointermove', event => {
    if (event.target === lane && event.pointerType !== 'touch' || selection?.lane === lane) showSelection(event);
    else hideTip();
  });
  lane.addEventListener('pointerleave', hideTip);
  lane.addEventListener('pointerup', event => {
    if (selection?.lane !== lane || selection.id !== event.pointerId) return;
    const { from, to } = showSelection(event);
    selection.ghost.remove();
    selection = null;
    beginEntry(lane, date, kind, from, to - from, false);
  });
  lane.addEventListener('pointercancel', () => {
    if (selection?.lane !== lane) return;
    selection.ghost.remove();
    selection = null;
    hideTip();
  });
  lane.tabIndex = 0;
  lane.setAttribute('aria-label', shortDate(date) + (kind === 'plan' ? '计划' : '实际') + '时间轴，按回车在九点录入');
  lane.addEventListener('keydown', event => {
    if (event.target !== lane || event.key !== 'Enter') return;
    event.preventDefault();
    beginEntry(lane, date, kind, 540, 30, false);
  });
}

function monthRuler(cell, date) {
  const ruler = button('', event => {
    const start = event.detail === 0 ? 540 : point(event.clientX);
    beginEntry(cell, date, newKind(), start, Math.min(30, 1440 - start), true);
  }, 'ruler', shortDate(date) + '选择时段');
  const marks = node('span', 'ruler-marks');
  for (const number of ['00', '06', '12', '18', '24']) marks.append(node('span', '', number));
  const marker = node('span', 'ruler-marker');
  marker.hidden = true;
  ruler.append(marks, node('span', 'ruler-track'), marker);
  function point(x) {
    const bounds = ruler.getBoundingClientRect();
    return Math.max(0, Math.min(1410, Math.floor((x - bounds.left - 4) / (bounds.width - 8) * 48) * 30));
  }
  ruler.addEventListener('pointermove', event => {
    const minute = point(event.clientX);
    marker.hidden = false;
    marker.style.left = 'calc(4px + (100% - 8px) * ' + minute / 1440 + ')';
    setToolTip(timeSpan(minute, 30), event.clientX, event.clientY);
  });
  ruler.addEventListener('pointerleave', () => {
    marker.hidden = true;
    hideTip();
  });
  return ruler;
}

function renderMonth(today) {
  const grid = node('section', 'month');
  grid.setAttribute('aria-label', '整月日程');
  for (const name of weekdays) grid.append(node('div', 'month-heading', name));
  const days = calendarDays(state.date);
  grid.style.setProperty('--weeks', days.length / 7);
  for (const date of days) {
    const cell = node('div', 'cell');
    cell.dataset.date = date;
    const day = fromKey(date);
    cell.classList.toggle('outside', date.slice(0, 7) !== state.date.slice(0, 7));
    cell.classList.toggle('weekend', day.getDay() === 0 || day.getDay() === 6);
    cell.classList.toggle('selected', date === state.date);
    const heading = node('div', 'cell-heading');
    const openAgenda = (fromMore = false) => openPanel(() => panels.dayAgenda(date, fromMore));
    heading.append(button(String(day.getDate()), () => openAgenda(),
      'date-number' + (date === today ? ' today' : ''), shortDate(date) + '日程详情'));
    const items = pieces(date);
    const previewCount = 3;
    const remaining = items.length - previewCount;
    if (remaining > 0) {
      const more = button('+' + remaining + ' 项', () => openAgenda(true), 'more-events',
        shortDate(date) + '还有 ' + remaining + ' 项，查看当天日程');
      more.title = '查看当天完整日程';
      heading.append(more);
    }
    const list = node('div', 'month-events');
    for (const piece of items.slice(0, previewCount)) list.append(eventNode(piece, 'month-event'));
    cell.append(heading, list, monthRuler(cell, date));
    cell.addEventListener('click', event => {
      if (!event.target.closest('button, form')) openAgenda();
    });
    grid.append(cell);
  }
  return grid;
}

function renderTimeline(today) {
  const isWeek = state.view === 'week';
  const grid = node('section', 'timeline ' + (isWeek ? 'week' : 'day'));
  const columns = isWeek ? dateRange(...period('week', state.date)).map(date => ({
    date, title: weekday(date) + ' ' + fromKey(date).getDate(), add: newKind(), show: state.filter,
  })) : [
    { date: state.date, title: '计划', add: 'plan', show: 'plan' },
    { date: state.date, title: '实际', add: 'actual', show: 'actual' },
  ];
  grid.style.setProperty('--columns', columns.length);
  grid.append(node('div', 'time-head', '时间'));
  for (const column of columns) {
    const head = node('div', 'time-head' + (isWeek && column.date === today ? ' today' : ''));
    if (isWeek) head.append(button(column.title, () => navigate('day', column.date), 'date-link'));
    else head.textContent = column.title;
    const durations = node('div', 'header-duration');
    for (const piece of pieces(column.date, column.show)) {
      if (piece.start === null) durations.append(eventNode(piece, 'duration-event'));
    }
    head.append(durations);
    grid.append(head);
  }
  const axis = node('div', 'time-axis');
  for (let hour = 0; hour < 24; hour++) {
    const label = node('span', '', clock(hour * 60));
    label.style.top = hour / 24 * 100 + '%';
    axis.append(label);
  }
  grid.append(axis);
  for (const column of columns) {
    const lane = node('div', 'lane' + (isWeek && column.date === today ? ' today' : ''));
    lane.dataset.date = column.date;
    lane.dataset.kind = column.add;
    for (const piece of arrange(pieces(column.date, column.show))) {
      const event = eventNode(piece, 'time-event');
      if (piece.minutes < 40) event.classList.add('short-slot');
      event.style.top = piece.start / 14.4 + '%';
      event.style.height = 'max(21px, calc(' + piece.minutes / 14.4 + '% - 2px))';
      event.style.left = 'calc(' + piece.column / piece.columns * 100 + '% + 2px)';
      event.style.width = 'calc(' + 100 / piece.columns + '% - 4px)';
      lane.append(event);
    }
    attachLane(lane, column.date, column.add);
    grid.append(lane);
  }
  return grid;
}

function render({ position, transition = false } = {}) {
  if (!state.data || state.closed) return;
  hideTip();
  const top = workspace.scrollTop;
  const left = workspace.scrollLeft;
  const today = dateKey(new Date());
  const label = get('#period-label');
  const dateLabel = periodLabel(state.view, state.date);
  label.dataset.periodView = state.view;
  if (state.view === 'day') {
    label.replaceChildren(shortDate(state.date), ' ', node('span', 'weekday-label', weekday(state.date)));
  } else if (state.view === 'week') {
    const [first, last] = dateLabel.split('—');
    label.replaceChildren(node('span', 'date-part', first), '—', node('wbr'), node('span', 'date-part', last));
  } else {
    label.textContent = dateLabel;
  }
  get('#reflection').textContent = reflectionFor(today);
  get('#stats').hidden = state.view === 'day';
  get('#filter').hidden = state.view === 'day';
  get('.views').style.setProperty('--tab-index', ['day', 'week', 'month'].indexOf(state.view));
  for (const control of document.querySelectorAll('[data-view]')) {
    control.setAttribute('aria-pressed', String(control.dataset.view === state.view));
  }
  for (const control of document.querySelectorAll('[data-filter]')) {
    control.setAttribute('aria-pressed', String(control.dataset.filter === state.filter));
  }
  const calendar = state.view === 'month' ? renderMonth(today) : renderTimeline(today);
  if (transition) calendar.classList.add('view-change');
  workspace.replaceChildren(calendar);
  workspace.scrollTop = position?.top ?? top;
  workspace.scrollLeft = position?.left ?? left;
  const dates = dateRange(...period(state.view, state.date));
  const actual = summarize(state.index, dates);
  const planned = summarize(state.index, dates, 'plan');
  get('#summary').textContent = '计划 ' + durationText(planned.total) + '　·　实际 ' + durationText(actual.total);
  workspace.setAttribute('aria-busy', 'false');
  panels.refreshAgenda();
}

function navigate(view, date) {
  if (!state.data || !canLeave()) return;
  clearDraft();
  const previous = { top: workspace.scrollTop, left: workspace.scrollLeft };
  const changedView = view !== state.view;
  const newMonth = state.date.slice(0, 7) !== date.slice(0, 7);
  scrollPositions.set(state.view, { ...previous, date: state.date });
  let position = changedView ? scrollPositions.get(view) : previous;
  if (view === 'month' && (newMonth || position?.date && position.date.slice(0, 7) !== date.slice(0, 7))) {
    position = null;
  }
  if (!position) position = defaultPosition(view);
  state.view = view;
  state.date = date;
  render({ position, transition: changedView || date !== scrollPositions.get(view)?.date });
}

function defaultPosition(view) {
  const hour = Number.parseFloat(getComputedStyle(workspace).getPropertyValue('--hour')) || 53;
  return { top: view === 'month' ? 0 : hour * 8, left: 0 };
}

function advance(direction) {
  const date = state.view === 'month' ? moveMonth(state.date, direction) :
    offset(state.date, direction * (state.view === 'week' ? 7 : 1));
  navigate(state.view, date);
}

async function refreshFromOtherWindow() {
  if (state.busy || state.draft || panel.open || state.closed || remoteRevision <= (state.data?.revision ?? 0)) return;
  try {
    await reload();
    render();
  } catch (error) {
    setStatus(error.message, true);
  }
}

const panels = makePanels({ node, button, panel, agenda, state, commit, addTo, navigate, render, inferCategory, timeSpan });
panel.addEventListener('close', refreshFromOtherWindow);
tab.onmessage = event => {
  if (event.data.closed) {
    showClosed();
    return;
  }
  remoteRevision = Math.max(remoteRevision, event.data.revision ?? 0);
  refreshFromOtherWindow();
};

function showClosed() {
  state.closed = true;
  clearTimeout(reflectionTimer);
  document.body.classList.add('is-closed');
  if (panel.open) panel.close();
  if (agenda.open) agenda.close();
  clearDraft();
  hideTip();
  for (const control of document.querySelectorAll('.masthead button')) control.disabled = true;
  const content = node('section', 'closing');
  content.append(node('h1', '', '行记已合卷'), node('p', '', '程序已退出。可以关闭此页，并在 Windows 中安全弹出硬盘。'));
  workspace.replaceChildren(content);
  get('#summary').textContent = '';
  setStatus('');
}

for (const control of document.querySelectorAll('[data-view]')) {
  control.addEventListener('click', () => navigate(control.dataset.view, state.date));
}
for (const control of document.querySelectorAll('[data-filter]')) {
  control.addEventListener('click', () => {
    if (!canLeave()) return;
    clearDraft();
    state.filter = control.dataset.filter;
    render();
  });
}
get('#previous').addEventListener('click', () => advance(-1));
get('#next').addEventListener('click', () => advance(1));
get('#today').addEventListener('click', () => navigate(state.view, dateKey(new Date())));
get('#period-label').addEventListener('click', () => openPanel(panels.jump));
get('#duration').addEventListener('click', () => openPanel(() =>
  panels.entry({ date: state.date, kind: 'actual', start: null, minutes: 30, title: '', notes: '', category: '' })));
get('#stats').addEventListener('click', () => openPanel(panels.stats));
get('#settings').addEventListener('click', () => openPanel(panels.settings));
async function requestExit() {
  if (state.closed) {
    window.closeNativeWindow?.();
    return;
  }
  if (!state.data) {
    window.closeNativeWindow?.();
    return;
  }
  if (state.busy) {
    setStatus('正在写入硬盘，请稍候');
    return;
  }
  if (!canLeave() || panels.hasChanges() && !confirm('还有未保存的改动。要放弃并退出吗？')) return;
  const exit = get('#exit');
  if (exit.disabled) return;
  exit.disabled = true;
  try {
    const response = await fetch('api/exit', { method: 'POST' });
    if (!response.ok) throw new Error('未能退出行记，请重试');
    tab.postMessage({ closed: true });
    showClosed();
    window.closeNativeWindow?.();
  } catch (error) {
    setStatus(error.message, true);
    exit.disabled = false;
  }
}
get('#exit').addEventListener('click', requestExit);
if (desktop) {
  window.journalClose = requestExit;
  const caption = get('.desktop-caption');
  const actions = get('.window-actions');
  const maximize = actions.querySelector('[data-window="maximize"]');
  window.updateJournalCaption = maximized => {
    document.documentElement.classList.toggle('window-maximized', maximized);
    const label = maximized ? '还原窗口' : '最大化';
    maximize.setAttribute('aria-label', label);
    maximize.title = label;
  };
  for (const control of actions.querySelectorAll('[data-window]')) {
    control.addEventListener('click', () => window.journalWindowCommand?.(control.dataset.window));
  }
  const reportCaptionSize = () => window.journalCaptionSize?.(
    Math.ceil(caption.offsetHeight * devicePixelRatio), Math.ceil(actions.offsetWidth * devicePixelRatio),
  );
  const resizeCaption = new ResizeObserver(reportCaptionSize);
  resizeCaption.observe(caption);
  resizeCaption.observe(actions);
  window.addEventListener('resize', reportCaptionSize);
}
workspace.addEventListener('scroll', hideTip, { passive: true });
window.addEventListener('beforeunload', event => {
  if (!state.closed && (state.busy || state.draft?.input.value.trim() || panels.hasChanges())) event.preventDefault();
});

function scheduleReflection() {
  clearTimeout(reflectionTimer);
  if (state.closed) return;
  const now = new Date();
  get('#reflection').textContent = reflectionFor(dateKey(now));
  const midnight = new Date(now);
  midnight.setHours(24, 0, 0, 50);
  reflectionTimer = setTimeout(scheduleReflection, midnight - now);
}

window.addEventListener('focus', scheduleReflection);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) scheduleReflection();
});

try {
  await reload();
  render({ position: defaultPosition(state.view) });
  scheduleReflection();
} catch (error) {
  workspace.replaceChildren(node('p', 'loading error', '打开行记失败。请关闭此页，再双击程序重新打开。'));
  workspace.setAttribute('aria-busy', 'false');
  setStatus(error.message, true);
}
