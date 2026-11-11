export const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
export const uncategorized = { id: '', name: '未分类', color: '#70695B' };
export const clock = minute => String(Math.floor(minute / 60)).padStart(2, '0') + ':' + String(minute % 60).padStart(2, '0');
export const durationText = minute => (minute >= 60 ? Math.floor(minute / 60) + '小时' : '') +
  (minute % 60 || minute === 0 ? minute % 60 + '分钟' : '');

export function dateKey(date) {
  return [date.getFullYear(), date.getMonth() + 1, date.getDate()].map((part, index) =>
    String(part).padStart(index === 0 ? 4 : 2, '0')).join('-');
}

export function fromKey(value) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day, 12);
}

export function offset(value, days) {
  const date = fromKey(value);
  date.setDate(date.getDate() + days);
  return dateKey(date);
}

export function weekStart(value) {
  return offset(value, -((fromKey(value).getDay() + 6) % 7));
}

export function monthStart(value) {
  return value.slice(0, 7) + '-01';
}

export function moveMonth(value, amount) {
  const date = fromKey(value);
  const day = date.getDate();
  date.setDate(1);
  date.setMonth(date.getMonth() + amount);
  const end = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
  date.setDate(Math.min(day, end));
  return dateKey(date);
}

export function dateRange(start, end) {
  const days = [];
  for (let date = start; date < end; date = offset(date, 1)) days.push(date);
  return days;
}

export function period(view, selected) {
  if (view === 'day') return [selected, offset(selected, 1)];
  if (view === 'week') {
    const first = weekStart(selected);
    return [first, offset(first, 7)];
  }
  const first = monthStart(selected);
  return [first, moveMonth(first, 1)];
}

export function shortDate(value) {
  const date = fromKey(value);
  return (date.getMonth() + 1) + '月' + date.getDate() + '日';
}

export function weekday(value) {
  return weekdays[(fromKey(value).getDay() + 6) % 7];
}

export function periodLabel(view, selected) {
  if (view === 'day') return shortDate(selected) + ' ' + weekday(selected);
  if (view === 'month') {
    const date = fromKey(selected);
    return date.getFullYear() + '年' + (date.getMonth() + 1) + '月';
  }
  const [start, end] = period(view, selected);
  const last = offset(end, -1);
  return shortDate(start) + '—' + shortDate(last);
}

export function calendarDays(selected) {
  const [first, end] = period('month', selected);
  const gridStart = weekStart(first);
  let gridEnd = offset(weekStart(offset(end, -1)), 7);
  const minimum = offset(gridStart, 35);
  if (gridEnd < minimum) gridEnd = minimum;
  return dateRange(gridStart, gridEnd);
}

export function indexedEntries(entries) {
  const byDate = new Map();
  function push(date, piece) {
    if (!byDate.has(date)) byDate.set(date, []);
    byDate.get(date).push(piece);
  }
  for (const entry of entries) {
    if (entry.start === null) {
      push(entry.date, { entry, start: null, minutes: entry.minutes });
      continue;
    }
    const beforeMidnight = Math.min(1440 - entry.start, entry.minutes);
    push(entry.date, { entry, start: entry.start, minutes: beforeMidnight });
    if (entry.minutes > beforeMidnight) {
      push(offset(entry.date, 1), { entry, start: 0, minutes: entry.minutes - beforeMidnight, continues: true });
    }
  }
  for (const pieces of byDate.values()) {
    pieces.sort((a, b) => (a.start ?? 1440) - (b.start ?? 1440) ||
      (a.entry.kind === b.entry.kind ? 0 : a.entry.kind === 'plan' ? -1 : 1) ||
      a.entry.title.localeCompare(b.entry.title, 'zh-CN'));
  }
  return byDate;
}

export function summarize(byDate, days, kind = 'actual') {
  const daily = days.map(date => {
    const categories = new Map();
    for (const piece of byDate.get(date) ?? []) {
      if (piece.entry.kind === kind) {
        const id = piece.entry.category;
        categories.set(id, (categories.get(id) ?? 0) + piece.minutes);
      }
    }
    return { date, categories, total: [...categories.values()].reduce((sum, value) => sum + value, 0) };
  });
  const categories = new Map();
  for (const day of daily) {
    for (const [id, minutes] of day.categories) categories.set(id, (categories.get(id) ?? 0) + minutes);
  }
  return { daily, categories, total: daily.reduce((sum, day) => sum + day.total, 0) };
}

export function arrange(pieces) {
  const result = [];
  let group = [];
  let columnEnds = [];
  const finish = () => {
    for (const item of group) result.push({ ...item, columns: columnEnds.length });
    group = [];
    columnEnds = [];
  };
  for (const piece of pieces) {
    if (piece.start === null) continue;
    if (columnEnds.length && Math.max(...columnEnds) <= piece.start) finish();
    let column = columnEnds.findIndex(end => end <= piece.start);
    if (column < 0) column = columnEnds.length;
    columnEnds[column] = piece.start + Math.max(24, piece.minutes);
    group.push({ ...piece, column });
  }
  finish();
  return result;
}
