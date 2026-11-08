'use strict';
(() => {
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const copy = value => JSON.parse(JSON.stringify(value));
  const operational = [
    ['preliminary', 'Предварительная'], ['preflight', 'Предполётная'],
    ['turnaround', 'Повторный вылет'], ['postflight', 'Послеполётная']
  ];
  const fresh = () => ({title: 'Моя система', resource: '', flight_time: '', flights_per_day: '',
    periods: [{id: 'P1', interval: '50'}, {id: 'P2', interval: '100'}, {id: 'P3', interval: '200'}],
    operations: [{name: '', labor: {}}]});
  let state = fresh(), stage = 0, busy = false, result = null, snapshot = null;
  let db = null, revision = 0, saveTimer, saveQueue = Promise.resolve();
  const settingFields = {title: '#project-title', resource: '#resource', flight_time: '#flight-time', flights_per_day: '#flights-per-day'};

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(text, action, className = '') {
    const node = el('button', text, className); node.type = 'button'; node.addEventListener('click', action); return node;
  }
  function error(value) {NadegErrors.show(value);}
  function clearError() {NadegErrors.clear();}
  function dirty() {
    revision++; result = null; snapshot = null; $('#results').hidden = true; $('#empty-result').hidden = false; clearError();
    clearTimeout(saveTimer); $('#save-state').textContent = 'Сохранение…'; saveTimer = setTimeout(() => persist(copy(state)), 350);
  }
  function persist(value) {
    saveQueue = saveQueue.then(() => new Promise(resolve => {
      if (!db) {$('#save-state').textContent = 'Автосохранение недоступно · скачайте JSON'; resolve(); return;}
      const tx = db.transaction('projects', 'readwrite'); tx.objectStore('projects').put({version: 1, lab: 2, state: value}, 'lab2-draft');
      tx.oncomplete = () => {$('#save-state').textContent = 'Сохранено на устройстве'; resolve();};
      tx.onerror = tx.onabort = () => {$('#save-state').textContent = 'Не удалось сохранить · скачайте JSON'; resolve();};
    })); return saveQueue;
  }
  async function initStorage() {
    const initial = revision;
    try {
      db = await new Promise((resolve, reject) => {
        const request = indexedDB.open('nadeg', 1);
        request.onupgradeneeded = () => request.result.createObjectStore('projects');
        request.onsuccess = () => resolve(request.result); request.onerror = reject; request.onblocked = reject;
      });
      const saved = await new Promise((resolve, reject) => {
        const request = db.transaction('projects').objectStore('projects').get('lab2-draft');
        request.onsuccess = () => resolve(request.result); request.onerror = reject;
      });
      if (saved && initial === revision) {
        try {state = validateProject(saved); renderAll(); $('#save-state').textContent = 'Черновик ЛР №2 восстановлен';}
        catch (_) {$('#save-state').textContent = 'Сохранение включено'; error('Не удалось прочитать черновик ЛР №2. Можно открыть сохранённый JSON.');}
      } else if (initial !== revision) persist(copy(state));
      else $('#save-state').textContent = 'Автосохранение ЛР №2 включено';
    } catch (_) {$('#save-state').textContent = 'Автосохранение недоступно · скачайте JSON';}
  }
  function definitions() {
    return [...operational.map(([id, label]) => ({id, label})),
      ...state.periods.map(p => ({id: p.id, label: `Регламент ${p.interval || p.id} ч`}))];
  }
  function number(value, label, positive = false, path = []) {
    const text = String(value).trim().replace(',', '.');
    if (!text || !Number.isFinite(Number(text)) || (positive ? Number(text) <= 0 : Number(text) < 0)) throw NadegErrors.field(positive ? 'Введите число больше 0' : 'Введите число не меньше 0', path, label);
    return text;
  }
  function settings() {
    return {title: state.title.trim() || 'Моя система', resource: number(state.resource, 'Ресурс', true, ['resource']),
      flight_time: number(state.flight_time, 'Время полёта', true, ['flight_time']), flights_per_day: number(state.flights_per_day, 'Полётов за день', true, ['flights_per_day']),
      periods: state.periods.map((p, i) => ({id: p.id, interval: number(p.interval, `Период ${p.id}`, true, ["periods", i, "interval"])}))};
  }
  function problem() {
    return {...settings(), operations: state.operations.map((op, index) => {
      if (!op.name.trim()) throw NadegErrors.field("Укажите название операции", ["operations", index, "name"], `Операция ${index + 1}`);
      return {name: op.name.trim(), labor: Object.fromEntries(definitions().map(f =>
        [f.id, String(op.labor[f.id] ?? '').trim() ? number(op.labor[f.id], `${op.name}: ${f.label}`, false, ["operations", index, "labor", f.id]) : '0']))};
    })};
  }
  async function api(path, payload) {
    let response;
    try {response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});}
    catch (_) {throw new Error('Сервер недоступен. Введённые данные остаются в браузере; проверьте подключение.');}
    if (!response.ok) {let data; try {data = await response.json();} catch (_) {} throw NadegErrors.fromResponse(data, response.status);}
    return response;
  }
  function setBusy(value) {busy = value; $$('button, input, select, textarea').forEach(n => n.disabled = value); $('#next').textContent = value ? 'Выполняется…' : nextLabel();}
  function nextLabel() {return stage === 0 ? 'К регламенту →' : stage === 1 ? 'Рассчитать →' : 'Пересчитать';}
  function showStage(next) {
    stage = next; $$('[data-panel]').forEach(n => n.hidden = Number(n.dataset.panel) !== stage);
    $$('[data-step]').forEach(n => {if (Number(n.dataset.step) === stage) n.setAttribute('aria-current', 'step'); else n.removeAttribute('aria-current');});
    $('#back').hidden = stage === 0; $('#next').textContent = nextLabel();
    $('#step-caption').textContent = ['Введите условия эксплуатации', 'Заполните трудоёмкости в чел·ч', 'Исследуйте составляющие трудоёмкости'][stage];
  }
  async function next() {
    if (busy) return; clearError(); let payload;
    try {payload = stage === 0 ? settings() : problem();} catch (e) {error(e); return;}
    setBusy(true);
    try {
      if (stage === 0) {await api('/api/lab2/validate', payload); renderOperations(); showStage(1);}
      else {result = await (await api('/api/lab2/calculate', payload)).json(); snapshot = copy(payload); renderResults(); showStage(2);}
    } catch (e) {error(e);} finally {setBusy(false);}
  }
  function renderPeriods() {
    $('#period-rows').replaceChildren();
    state.periods.forEach((period, index) => {
      const row = el('div', undefined, 'period-item'); const label = el('label', `Регламент ${period.id}, ч`);
      const input = el('input'); input.value = period.interval; input.inputMode = 'decimal'; input.autocomplete = 'off'; input.dataset.period = period.id;
      input.setAttribute('aria-label', `Период ${period.id}, ч`);
      input.addEventListener('input', () => {period.interval = input.value; dirty();});
      input.addEventListener('change', renderOperations); label.append(input);
      const remove = button('×', () => {
        if (state.periods.length === 1) {error('Оставьте хотя бы один периодический регламент.'); return;}
        state.periods.splice(index, 1); state.operations.forEach(op => delete op.labor[period.id]); dirty(); renderPeriods(); renderOperations();
      }); remove.setAttribute('aria-label', `Удалить период ${period.id}`); row.append(label, remove); $('#period-rows').append(row);
    });
  }
  function renderOperations() {
    const defs = definitions(), head = el('tr');
    head.append(el('th', 'Операция')); defs.forEach(f => head.append(el('th', f.label + ', чел·ч')));
    const removeHeader = el('th'); const hint = el('span', 'Удалить', 'sr-only'); removeHeader.append(hint); head.append(removeHeader);
    $('#regulation-header').replaceChildren(head); $('#operation-rows').replaceChildren();
    state.operations.forEach((operation, index) => {
      const row = el('tr'), cell = el('td'); cell.dataset.label = 'Операция';
      const name = el('input'); name.value = operation.name; name.maxLength = 160; name.placeholder = 'Название операции'; name.dataset.field = 'name';
      name.setAttribute('aria-label', `Название операции ${index + 1}`); name.addEventListener('input', () => {operation.name = name.value; dirty();}); cell.append(name); row.append(cell);
      defs.forEach(f => {
        const td = el('td'); td.dataset.label = f.label + ', чел·ч'; const input = el('input'); input.value = operation.labor[f.id] ?? '';
        input.dataset.form = f.id; input.inputMode = 'decimal'; input.autocomplete = 'off'; input.placeholder = '0';
        input.setAttribute('aria-label', `${f.label}, операция ${index + 1}, чел·ч`);
        input.addEventListener('input', () => {operation.labor[f.id] = input.value; dirty();}); td.append(input); row.append(td);
      });
      const td = el('td'); const remove = button('Удалить', () => {
        if (state.operations.length === 1) {error('В регламенте должна остаться хотя бы одна операция.'); return;}
        state.operations.splice(index, 1); dirty(); renderOperations();
      }, 'delete-operation'); remove.setAttribute('aria-label', `Удалить операцию ${index + 1}`); td.append(remove); row.append(td); $('#operation-rows').append(row);
    });
  }
  function renderAll() {Object.entries(settingFields).forEach(([key, selector]) => $(selector).value = state[key]); renderPeriods(); renderOperations(); showStage(0);}
  function pretty(value, digits = 8) {
    const n = Number(value); if (!Number.isFinite(n)) return String(value);
    if (n && Math.abs(n) < 1e-7) return n.toExponential(5).replace('.', ',');
    return n.toLocaleString('ru-RU', {maximumFractionDigits: digits, useGrouping: false});
  }
  function fillTable(selector, rows) {$(selector).replaceChildren(...rows.map(values => {const row = el('tr'); values.forEach(v => row.append(el('td', v))); return row;}));}
  function renderResults() {
    $('#empty-result').hidden = true; $('#results').hidden = false;
    for (const [selector, value] of [['#metric-total', result.total_labor], ['#metric-specific', result.specific_labor], ['#metric-days', result.flight_days]]) {$(selector).textContent = pretty(value); $(selector).title = value;}
    $('#metric-days').title = result.flight_days_exact; $('#metric-flights').textContent = `Расчётных полётов: ${pretty(result.flights)}`;
    fillTable('#form-results', result.forms.map(f => [f.label, pretty(f.count), pretty(f.per_service), pretty(f.total), pretty(f.share_percent, 2)]));
    fillTable('#operation-results', result.operations.map(op => [op.name, pretty(op.total), pretty(op.share_percent, 2)]));
    $('#days-formula').textContent = `Nлд = ${result.resource} / (${result.flights_per_day} × ${result.flight_time}) = ${result.flight_days_exact}.`;
    $('#count-formulas').replaceChildren(...result.forms.map(f => el('li', `${f.label}: ${f.formula}; количество = ${f.count_exact}.`)));
    $('#rules').replaceChildren(...result.rules.map(r => el('li', r))); $('#warnings').replaceChildren(...result.warnings.map(r => el('li', r)));
  }
  function download(content, name, type) {
    const blob = content instanceof Blob ? content : new Blob([content], {type}); const url = URL.createObjectURL(blob), link = el('a');
    link.href = url; link.download = name; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  async function exportResult(format) {
    if (busy || !snapshot) return; clearError(); setBusy(true);
    try {download(await (await api('/api/lab2/export/' + format, snapshot)).blob(), `nadeg-lab2.${format}`);}
    catch (e) {error(e);} finally {setBusy(false);}
  }
  async function confirmAction(title, message) {
    const dialog = $('#confirm-dialog'); $('#confirm-title').textContent = title; $('#confirm-text').textContent = message; dialog.returnValue = 'cancel';
    return new Promise(resolve => {dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), {once: true}); dialog.showModal();});
  }
  function validateProject(document) {
    if (!document || document.version !== 1 || document.lab !== 2 || !document.state) throw new Error('Ожидается JSON проекта ЛР №2 версии 1. Проект ЛР №1 открывается в своей вкладке.');
    const input = document.state, clean = fresh();
    for (const key of Object.keys(settingFields)) {
      if (!['string', 'number'].includes(typeof input[key]) || String(input[key]).length > 120) throw new Error('Некорректные условия эксплуатации.');
      clean[key] = String(input[key]);
    }
    if (!Array.isArray(input.periods) || !input.periods.length || input.periods.length > 8) throw new Error('В проекте должно быть от 1 до 8 периодических форм.');
    clean.periods = input.periods.map(p => {
      if (!p || !/^P[1-9][0-9]{0,3}$/.test(p.id) || !['string', 'number'].includes(typeof p.interval) || String(p.interval).length > 80) throw new Error('Некорректный период.');
      return {id: p.id, interval: String(p.interval)};
    });
    const keys = [...operational.map(([key]) => key), ...clean.periods.map(p => p.id)];
    if (new Set(clean.periods.map(p => p.id)).size !== clean.periods.length) throw new Error('Повторные ID периодических форм.');
    if (!Array.isArray(input.operations) || !input.operations.length || input.operations.length > 100) throw new Error('В проекте должно быть от 1 до 100 операций.');
    clean.operations = input.operations.map(op => {
      if (!op || typeof op.name !== 'string' || op.name.length > 160 || !op.labor || typeof op.labor !== 'object' || Array.isArray(op.labor)) throw new Error('Некорректная операция.');
      const labor = {};
      for (const key of keys) {
        const value = op.labor[key] ?? ''; if (!['string', 'number'].includes(typeof value) || String(value).length > 80) throw new Error('Некорректная трудоёмкость.');
        labor[key] = String(value);
      }
      return {name: op.name, labor};
    });
    return clean;
  }
  async function importText(text) {
    if (busy) return; clearError(); let periods;
    try {periods = state.periods.map((p, i) => ({id: p.id, interval: number(p.interval, `Период ${p.id}`, true, ["periods", i, "interval"])}));}
    catch (e) {error(e); return;}
    setBusy(true); let imported;
    try {imported = await (await api('/api/lab2/import', {text, periods})).json();}
    catch (e) {error(e); return;}
    finally {setBusy(false);}
    if (!await confirmAction('Заменить регламент?', 'Текущие операции ЛР №2 будут заменены импортированной таблицей. Условия эксплуатации и ЛР №1 останутся прежними.')) return;
    state.operations = imported.operations; dirty(); renderOperations(); showStage(1);
  }
  Object.entries(settingFields).forEach(([key, selector]) => $(selector).addEventListener('input', () => {state[key] = $(selector).value; dirty();}));
  $('#next').addEventListener('click', next); $('#back').addEventListener('click', () => {if (!busy) showStage(Math.max(0, stage - 1));});
  $$('[data-step]').forEach(n => n.addEventListener('click', () => {if (!busy) {clearError(); renderOperations(); showStage(Number(n.dataset.step));}}));
  $('#add-period').addEventListener('click', () => {
    if (state.periods.length >= 8) {error('Максимум 8 периодических форм.'); return;}
    let id = 1; while (state.periods.some(p => p.id === `P${id}`)) id++;
    state.periods.push({id: `P${id}`, interval: ''}); dirty(); renderPeriods(); renderOperations(); $('#period-rows .period-item:last-child input').focus();
  });
  $('#add-operation').addEventListener('click', () => {
    if (state.operations.length >= 100) {error('Максимум 100 операций.'); return;}
    state.operations.push({name: '', labor: {}}); dirty(); renderOperations(); $('#operation-rows tr:last-child input[data-field=name]').focus();
  });
  ['pdf', 'csv'].forEach(format => $('#export-' + format).addEventListener('click', () => exportResult(format)));
  $('#save-project').addEventListener('click', () => {download(JSON.stringify({version: 1, lab: 2, state}, null, 2), 'nadeg-lab2-project.json', 'application/json'); $('.project-menu').open = false;});
  $('#load-project').addEventListener('click', () => {$('#project-file').click(); $('.project-menu').open = false;});
  $('#project-file').addEventListener('change', async event => {
    const file = event.target.files[0]; event.target.value = ''; if (!file) return;
    try {if (file.size > 131072) throw new Error('Максимальный размер проекта — 128 КБ.'); const imported = validateProject(NadegErrors.parseProject(await file.text()));
      if (!await confirmAction('Открыть проект ЛР №2?', 'Текущий черновик ЛР №2 будет заменён. При необходимости сначала скачайте его JSON.')) return;
      state = imported; dirty(); renderAll();
    } catch (e) {error(e);}
  });
  $('#new-project').addEventListener('click', async () => {
    if (await confirmAction('Новый проект ЛР №2?', 'Сначала скачайте текущий JSON, если хотите сохранить его отдельно.')) {state = fresh(); dirty(); renderAll();}
    $('.project-menu').open = false;
  });
  $('#import-csv').addEventListener('click', () => $('#csv-file').click());
  $('#csv-file').addEventListener('change', async event => {
    const file = event.target.files[0]; event.target.value = ''; if (!file) return;
    try {if (file.size > 100000) throw new Error('Максимальный размер CSV — 100 КБ.'); await importText(await file.text());} catch (e) {error(e);}
  });
  $('#paste-table').addEventListener('click', () => {$('#paste-content').value = ''; $('#paste-dialog').showModal(); $('#paste-content').focus();});
  $('#paste-cancel').addEventListener('click', () => $('#paste-dialog').close());
  $('#paste-import').addEventListener('click', () => {const text = $('#paste-content').value; $('#paste-dialog').close(); importText(text);});
  document.addEventListener('visibilitychange', () => {if (document.hidden) {clearTimeout(saveTimer); persist(copy(state));}});
  NadegErrors.configure(path => {
    if (path[0] === 'periods') return {stage: 0, node: $$('#period-rows input')[path[1] || 0]};
    if (path[0] === 'operations') {const row = $$('#operation-rows tr')[path[1] || 0]; return {stage: 1, node: row && [...row.querySelectorAll('input')].find(n => path[2] === 'labor' ? n.dataset.form === path[3] : n.dataset.field === 'name')};}
    return {stage: 0, node: settingFields[path[0]] ? $(settingFields[path[0]]) : null};
  }, showStage);
  renderAll(); initStorage();
})();
