const $ = (selector) => document.querySelector(selector);
let state = {events: [], sources: [], projects: []}, selected = 'all', projectId = null, editing = null, toastTimer, publishing = false;
const projectApi = (suffix = '') => `/api/projects/${projectId}${suffix}`;
const currentProject = () => state.projects.find(p => p.id === projectId);
const form = $('#event-form');
const field = name => form.elements.namedItem(name);
const el = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 4500); }
async function api(path, method = 'GET', body) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json'}, ...(body !== undefined ? {body: JSON.stringify(body)} : {})});
  const data = await response.json(); if (!response.ok) throw new Error(data.error || '请求失败'); return data;
}
async function reload() { state = await api('/api/state' + (projectId ? '?project=' + encodeURIComponent(projectId) : '')); projectId = state.current_project; render(); }
function render() {
  const project = currentProject();
  $('#projects').replaceChildren(...state.projects.map(p => { const b = el('button', p.name, 'nav' + (p.id === projectId ? ' active' : '')); b.disabled = publishing; b.onclick = async () => { projectId = p.id; selected = 'all'; $('#search').value = ''; try { await reload(); renderPlugin(); } catch(e) { toast(e.message); } }; return b; }));
  const labels = {unpublished: '未发布', changed: '有更新待发布', published: '已发布'};
  $('#publish-status').textContent = labels[project.status];
  $('#publish-summary').textContent = project.last_error ? '上次发布失败，可重试' : project.status === 'changed' ? '本地有更新，重新发布后同步' : project.status === 'published' ? '已发布 · 订阅地址保持不变' : '完成发布设置，生成 GitHub 订阅';
  $('#copy-url').disabled = !project.subscription_url;
  $('#copy-url').title = project.subscription_url || '成功发布到 GitHub 后可复制';
  $('#publish-project').textContent = publishing ? '发布中…' : project.status === 'unpublished' ? '发布到 GitHub' : '重新发布';
  $('#publish-project').disabled = publishing;
  $('#publish-settings').disabled = publishing;
  $('#new-project').disabled = publishing;
  $('#total').textContent = state.events.length; $('#stat-events').textContent = state.events.length; $('#stat-sources').textContent = state.sources.length;
  const source = state.sources.find(s => s.id === selected);
  $('#page-title').textContent = source ? `${project.name} · ${source.title}` : project.name;
  $('#page-description').textContent = source ? source.description : '独立管理这份订阅的日程，在本地编辑，发布到 GitHub。';
  $('#all-source').classList.toggle('active', selected === 'all');
  $('#sources').replaceChildren(...state.sources.map(s => { const b = el('button', '◷　' + s.title, 'nav' + (selected === s.id ? ' active' : '')); b.onclick = () => chooseSource(s.id); return b; }));
  $('#download').href = `/subscription/${projectId}.ics`;
  $('#updated').textContent = state.updated ? '最近更新 ' + new Date(state.updated).toLocaleString('zh-CN') : '等待第一次安排';
  renderEvents();
}
function chooseSource(id) { selected = id; render(); renderPlugin(); }
function renderPlugin() {
  const source = state.sources.find(s => s.id === selected);
  $('#plugin-panel').hidden = !source || source.editable;
  $('#plugin-fields').replaceChildren();
  if (!source || source.editable) return;
  $('#plugin-description').textContent = source.description;
  for (const spec of source.fields) {
    const label = el('label', spec.label || spec.name);
    const input = document.createElement(spec.type === 'textarea' ? 'textarea' : spec.type === 'select' ? 'select' : 'input');
    if (input.tagName === 'INPUT') input.type = spec.type;
    input.name = spec.name; input.required = !!spec.required;
    if (spec.type === 'select') for (const option of spec.options || []) { const o = el('option', option.label); o.value = option.value; input.append(o); }
    if (spec.type === 'checkbox') input.checked = !!spec.default; else input.value = spec.default ?? '';
    if (spec.placeholder) input.placeholder = spec.placeholder;
    label.append(input); if (spec.help) label.append(el('small', spec.help)); $('#plugin-fields').append(label);
  }
}
function renderEvents() {
  const query = $('#search').value.trim().toLowerCase();
  const events = state.events.filter(e => (selected === 'all' || e.source === selected) && [e.title, e.location, e.description, e.categories].some(v => v.toLowerCase().includes(query))).sort((a,b) => a.start.localeCompare(b.start));
  $('#list-count').textContent = events.length;
  $('#events').replaceChildren();
  if (!events.length) {
    const box = el('div', undefined, 'empty'); box.append(el('div', '▦', 'icon'), el('h3', query ? '没有找到匹配的日程' : '为重要的时刻，留一个位置'), el('p', query ? '试试其他关键词，或切换日历渠道。' : '创建第一条日程，或连接更多渠道。我们会为你自动生成订阅日历。'));
    if (!query) { const b = el('button', '＋ 创建第一条日程', 'primary'); b.onclick = () => openEvent(); box.append(b); }
    $('#events').append(box); return;
  }
  for (const event of events) {
    const row = el('article', undefined, 'event-row'), tile = el('div', undefined, 'date-tile'); tile.append(el('small', event.start.slice(0,7)), el('strong', event.start.slice(8,10)));
    const content = el('div', undefined, 'event-content'); content.append(el('h3', event.title));
    const time = event.all_day ? `${event.start} → ${event.end}（全天，结束日不含）` : `${event.start.replace('T',' ')} → ${event.end.replace('T',' ')} · ${event.timezone}`;
    const reminders = event.reminders?.length ? event.reminders.map(minutes => minutes ? `提前 ${minutes} 分钟` : '开始时').join('、') : '不提醒';
    content.append(el('p', time), el('p', `${event.location || '未设置地点'} · ${reminders}`));
    const tags = el('div'); tags.append(el('span', state.sources.find(s => s.id === event.source)?.title || event.source, 'badge'));
    if (event.frequency) tags.append(el('span', '重复日程', 'badge'));
    if (event.status !== 'CONFIRMED') tags.append(el('span', event.status === 'CANCELLED' ? '已取消' : '暂定', 'badge'));
    content.append(tags); row.append(tile, content);
    if (event.source === 'manual') {
      const actions = el('div', undefined, 'event-actions'), edit = el('button', '编辑'), remove = el('button', '删除', 'danger');
      edit.onclick = () => openEvent(event);
      remove.onclick = async () => { if (!confirm(`删除「${event.title}」？此操作仅修改本项目的本地文件，重新发布后生效。`)) return; remove.disabled = true; try { await api(projectApi(`/events/${event.id}`), 'DELETE', {}); await reload(); toast('日程已从本项目删除，重新发布后更新 GitHub 订阅'); } catch(e) { toast(e.message); remove.disabled = false; } };
      actions.append(edit, remove); row.append(actions);
    }
    $('#events').append(row);
  }
}
function localISO(date) { return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0,16); }
function updateRecurrence() { $('#recurrence').hidden = !field('frequency').value; $('#weekdays').hidden = field('frequency').value !== 'WEEKLY'; }
function updateAllDay() {
  for (const name of ['start','end']) { const input = field(name), value = input.value; input.type = field('all_day').checked ? 'date' : 'datetime-local'; input.value = field('all_day').checked ? value.slice(0,10) : value.length === 10 ? value + 'T09:00' : value; }
  if (field('all_day').checked && field('start').value && field('end').value <= field('start').value) {
    const next = new Date(field('start').value + 'T00:00:00Z'); next.setUTCDate(next.getUTCDate() + 1); field('end').value = next.toISOString().slice(0,10);
  }
}
function openEvent(event) {
  editing = event?.id || null; form.reset(); $('#form-error').textContent = ''; $('#dialog-title').textContent = event ? '编辑日程' : '新建日程';
  field('all_day').checked = !!event?.all_day; updateAllDay();
  if (event) {
    for (const [name,value] of Object.entries(event)) { const input = field(name); if (!input || name === 'all_day' || name === 'weekdays') continue; input.value = name === 'reminders' ? value.join(', ') : value ?? ''; }
  } else {
    const start = new Date(); start.setMinutes(0,0,0); start.setHours(start.getHours()+1);
    field('start').value = localISO(start); field('end').value = localISO(new Date(start.getTime()+3600000));
    field('timezone').value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';
  }
  document.querySelectorAll('[name=weekdays]').forEach(input => input.checked = (event?.weekdays || []).includes(input.value));
  updateRecurrence(); $('#event-dialog').showModal(); field('title').focus();
}
for (const [index,day] of ['MO','TU','WE','TH','FR','SA','SU'].entries()) { const label = el('label'), input = el('input'); input.type = 'checkbox'; input.name = 'weekdays'; input.value = day; label.append(input, el('span', ['一','二','三','四','五','六','日'][index])); $('#weekdays').append(label); }
field('all_day').onchange = updateAllDay; field('frequency').onchange = updateRecurrence;
$('#new-event').onclick = () => openEvent(); $('#close-dialog').onclick = $('#cancel-dialog').onclick = () => $('#event-dialog').close();
$('#all-source').onclick = () => chooseSource('all'); $('#search').oninput = renderEvents;
$('#copy-url').onclick = async () => { const url = currentProject()?.subscription_url; if (!url) return; try { await navigator.clipboard.writeText(url); toast('GitHub 订阅链接已复制'); } catch { prompt('复制以下 GitHub 订阅链接', url); } };
for (const button of document.querySelectorAll('[data-close]')) button.onclick = () => document.getElementById(button.dataset.close).close();
$('#new-project').onclick = () => { $('#project-form').reset(); $('#project-form .form-error').textContent = ''; $('#project-dialog').showModal(); };
$('#project-form').onsubmit = async event => {
  event.preventDefault(); const button = event.target.querySelector('[type=submit]'); button.disabled = true;
  try { const created = await api('/api/projects', 'POST', {name: event.target.elements.namedItem('name').value}); projectId = created.id; selected = 'all'; $('#search').value = ''; await reload(); renderPlugin(); $('#project-dialog').close(); toast('独立订阅项目已创建'); }
  catch(error) { $('#project-form .form-error').textContent = error.message; } finally { button.disabled = false; }
};
const publishForm = $('#publish-form');
function previewPublication() {
  const values = Object.fromEntries(new FormData(publishForm));
  $('#publish-url-preview').textContent = values.repository && values.branch && values.path ? `https://raw.githubusercontent.com/${values.repository}/refs/heads/${values.branch.split('/').map(encodeURIComponent).join('/')}/${values.path.split('/').map(encodeURIComponent).join('/')}` : '填写仓库、分支和文件路径后显示';
}
function openPublishSettings() {
  const project = currentProject(); publishForm.reset();
  publishForm.elements.namedItem('name').value = project.name;
  for (const [key, value] of Object.entries(project.publication)) publishForm.elements.namedItem(key).value = value;
  $('#publish-form .form-error').textContent = project.last_error || '';
  $('#publish-history').textContent = project.published ? '上次发布：' + new Date(project.published.at).toLocaleString('zh-CN') + ' · 提交 ' + project.published.commit.slice(0, 8) : '尚未发布。日程编辑会自动保存在本地，不会自动上传。';
  previewPublication(); $('#publish-dialog').showModal();
}
$('#publish-settings').onclick = openPublishSettings;
publishForm.oninput = previewPublication;
publishForm.onsubmit = async event => {
  event.preventDefault(); const button = event.target.querySelector('[type=submit]'); button.disabled = true;
  try { const {name, ...publication} = Object.fromEntries(new FormData(publishForm)); await api(projectApi(), 'PUT', {name, publication}); await reload(); $('#publish-dialog').close(); toast('发布设置已保存，尚未上传文件'); }
  catch(error) { $('#publish-form .form-error').textContent = error.message; } finally { button.disabled = false; }
};
$('#publish-project').onclick = async () => {
  const project = currentProject();
  if (!project.publication.repository) { openPublishSettings(); return; }
  if (!confirm(`将「${project.name}」的全部日程发布到公开 GitHub 仓库？\n\n${project.publication.repository} · ${project.publication.branch}\n${project.publication.path}\n\n仅提交此项目的 ICS；其他订阅项目不受影响。`)) return;
  publishing = true; render(); toast('正在生成 Git 提交并推送，请稍候…');
  let error;
  try { await api(projectApi('/publish'), 'POST', {}); toast('发布成功，可以复制 GitHub 订阅链接'); }
  catch(e) { error = e.message; }
  finally { publishing = false; await reload().catch(e => toast(e.message)); if (error) { openPublishSettings(); $('#publish-form .form-error').textContent = error; } }
};
form.onsubmit = async (event) => {
  event.preventDefault(); const button = form.querySelector('[type=submit]'); button.disabled = true; $('#form-error').textContent = '';
  try {
    const payload = Object.fromEntries(new FormData(form)); payload.all_day = field('all_day').checked;
    payload.interval = Number(payload.interval || 1); payload.count = payload.count ? Number(payload.count) : null;
    payload.weekdays = [...document.querySelectorAll('[name=weekdays]:checked')].map(i => i.value);
    payload.reminders = payload.reminders.trim() ? payload.reminders.split(/[,，]/).map(s => { if (!/^\d+$/.test(s.trim())) throw new Error('提醒请填写以逗号分隔的非负整数'); return Number(s.trim()); }) : [];
    if (!payload.frequency) { payload.count = null; payload.until = ''; payload.weekdays = []; }
    await api(editing ? projectApi(`/events/${editing}`) : projectApi('/events'), editing ? 'PUT' : 'POST', payload);
    $('#event-dialog').close(); await reload(); toast('日程已保存到本项目，发布后更新 GitHub 订阅');
  } catch (error) { $('#form-error').textContent = error.message; } finally { button.disabled = false; }
};
$('#plugin-form').onsubmit = async event => {
  event.preventDefault(); const button = event.target.querySelector('[type=submit]'); button.disabled = true;
  try { const source = state.sources.find(s => s.id === selected), config = {};
    for (const spec of source.fields) { const input = event.target.elements.namedItem(spec.name); config[spec.name] = spec.type === 'checkbox' ? input.checked : spec.type === 'number' ? Number(input.value) : input.value; }
    await api(projectApi(`/sources/${selected}/refresh`), 'POST', config); await reload(); toast('渠道已同步');
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
};
reload().catch(error => { toast('加载失败：' + error.message); $('#events').textContent = '无法加载日程，请确认服务运行后刷新页面。'; });
