'use strict';
(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const fresh = () => ({mode: 'analysis', title: 'Моя система', time: '4', rate_scale: '1e-4', target: '0,999', max_mass: '', search_limit: 15000,
    elements: [{id: 'A', name: '', rate: '', mass: '1', reserves: 0, max_reserves: 3, reservable: true}],
    tree: {op: 'and', children: [{ref: 'A'}]}, editor: 'builder', expression: ''});
  let state = fresh(), stage = 0, result = null, resultProblem = null, busy = false, db = null, saveTimer;
  let revision = 0, saveQueue = Promise.resolve(), loadToken = 0;

  function el(tag, text, className) {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node;}
  function button(text, handler, className = '') {const node = el('button', text, className); node.type = 'button'; node.addEventListener('click', handler); return node;}
  function showError(value) {NadegErrors.show(value);}
  function clearError() {NadegErrors.clear();}
  function dirty() {revision++; result = null; resultProblem = null; $('#results').hidden = true; $('#empty-result').hidden = false; clearError(); scheduleSave();}
  function scheduleSave() {clearTimeout(saveTimer); $('#save-state').textContent = 'Сохранение…'; saveTimer = setTimeout(() => persist(clone(state)), 350);}
  function persist(snapshot) {
    saveQueue = saveQueue.then(() => new Promise((resolve) => {
      if (!db) {$('#save-state').textContent = 'Автосохранение недоступно · скачайте JSON'; resolve(); return;}
      const tx = db.transaction('projects', 'readwrite'); tx.objectStore('projects').put({version: 1, state: snapshot}, 'draft');
      tx.oncomplete = () => {$('#save-state').textContent = 'Сохранено на устройстве'; resolve();};
      tx.onerror = tx.onabort = () => {$('#save-state').textContent = 'Не удалось сохранить · скачайте JSON'; resolve();};
    })); return saveQueue;
  }
  async function initStorage() {
    const initialRevision = revision;
    try {
      db = await new Promise((resolve, reject) => {const request = indexedDB.open('nadeg', 1); request.onupgradeneeded = () => request.result.createObjectStore('projects'); request.onsuccess = () => resolve(request.result); request.onerror = reject; request.onblocked = reject;});
      const saved = await new Promise((resolve, reject) => {const request = db.transaction('projects').objectStore('projects').get('draft'); request.onsuccess = () => resolve(request.result); request.onerror = reject;});
      if (saved && initialRevision === revision) {state = validateProject(saved); renderAll(); $('#save-state').textContent = 'Черновик восстановлен';}
      else if (revision !== initialRevision) scheduleSave();
      else $('#save-state').textContent = 'Автосохранение включено';
    } catch (_) {$('#save-state').textContent = 'Автосохранение недоступно · скачайте JSON';}
  }
  function treeExpression(node) {
    if (node.ref !== undefined) return node.ref;
    if (!node.children.length) throw new Error('В структуре есть пустая группа. Добавьте элемент или удалите группу.');
    return '(' + node.children.map(treeExpression).join(node.op === 'and' ? ' & ' : ' | ') + ')';
  }
  function currentExpression() {return state.editor === 'expression' ? state.expression.trim() : treeExpression(state.tree);}
  function preview() {try {$('#expression-preview').textContent = currentExpression().replaceAll('&', 'И').replaceAll('|', 'ИЛИ') || '—';} catch (_) {$('#expression-preview').textContent = 'Незаполненная группа';}}
  function num(value, label, positive = false) {const text = String(value).trim().replace(',', '.'); if (!text || !Number.isFinite(Number(text)) || (positive && Number(text) <= 0)) throw new Error(`Проверьте поле «${label}».`); return text;}
  function checkedNumber(value, label, path, positive = false) {
    const text = String(value).trim().replace(',', '.');
    if (!text || !Number.isFinite(Number(text)) || (positive ? Number(text) <= 0 : Number(text) < 0)) throw NadegErrors.field(positive ? 'Введите число больше 0' : 'Введите число не меньше 0', path, label);
    return text;
  }
  function integer(value, label, path) {const n = Number(value); if (String(value).trim() === '' || !Number.isInteger(n) || n < 0 || n > 12) throw NadegErrors.field('Введите целое число от 0 до 12', path, label); return n;}
  function problem(dataOnly = false) {
    const elements = state.elements.map((e, index) => ({id: e.id.trim().toUpperCase(), name: e.name.trim(), rate: checkedNumber(e.rate, `Параметр ω элемента ${e.id}`, ["elements", index, "rate"]), mass: checkedNumber(e.mass, `Масса элемента ${e.id}`, ["elements", index, "mass"], true),
      reserves: integer(e.reserves, `Резервов k элемента ${e.id}`, ['elements', index, 'reserves']), max_reserves: state.mode === 'reserve' ? integer(e.max_reserves, `Максимум резервов элемента ${e.id}`, ['elements', index, 'max_reserves']) : 12, reservable: e.reservable}));
    const expression = dataOnly ? (elements[0]?.id || "A") : currentExpression(); if (!expression) throw NadegErrors.field('Задайте условие работоспособности системы', ['expression'], 'Структура');
    return {task: state.mode === 'analysis' ? 1 : 2, title: state.title || 'Моя система', time: checkedNumber(state.time, 'Время работы', ['time'], true), rate_scale: state.rate_scale, target: state.mode === 'reserve' ? checkedNumber(state.target, 'Требуемая вероятность', ['target'], true) : '0.999',
      max_mass: state.mode === 'reserve' && state.max_mass.trim() ? checkedNumber(state.max_mass, 'Максимальная масса', ['max_mass'], true) : null, search_limit: Number(state.search_limit), expression, elements};
  }
  async function api(path, payload) {
    let response;
    try {response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});}
    catch (_) {throw new Error('Сервер недоступен. Черновик остаётся в браузере; проверьте подключение.');}
    if (!response.ok) {let data; try {data = await response.json();} catch (_) {} throw NadegErrors.fromResponse(data, response.status);}
    return response;
  }
  function setBusy(value) {busy = value; $$('button, input, select, textarea').forEach(b => b.disabled = value); if (!value) $$('#builder option[value=or]').forEach(n => n.disabled = state.mode === 'reserve'); $('#next').textContent = value ? (state.mode === 'reserve' ? 'Подбираем резервы…' : 'Считаем…') : nextLabel();}
  function nextLabel() {return stage === 0 ? 'К структуре →' : stage === 1 ? (state.mode === 'reserve' ? 'Подобрать резервы →' : 'Рассчитать →') : 'Пересчитать';}
  function showStage(value) {stage = value; $$('[data-panel]').forEach(p => p.hidden = Number(p.dataset.panel) !== stage); $$('[data-step]').forEach(b => {if (Number(b.dataset.step) === stage) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');}); $('#back').hidden = stage === 0; $('#step-caption').textContent = ['Введите собственные данные', 'Задайте условие работоспособности', 'Исследуйте результат и сохраните отчёт'][stage]; $('#next').textContent = nextLabel(); preview();}
  async function run() {
    if (busy) return;
    clearError(); let input; try {input = problem();} catch (error) {showError(error); return;}
    setBusy(true);
    try {const response = await api(state.mode === 'reserve' ? '/api/optimize' : '/api/analyze', input); result = await response.json(); resultProblem = clone(input); renderResults(); showStage(2);}
    catch (error) {showError(error);}
    finally {setBusy(false);}
  }
  function fieldCell(row, element, key, label, kind = 'text', extra = '') {
    const cell = el('td'); cell.dataset.field = key; cell.dataset.label = key === 'reservable' ? 'Можно' : label; if (extra) {cell.className = extra; cell.hidden = state.mode !== 'reserve';}
    const input = el('input'); input.dataset.field = key; input.setAttribute('aria-label', `${label}, элемент ${element.id}`);
    if (kind === 'checkbox') {input.type = 'checkbox'; input.checked = element[key];}
    else {input.type = 'text'; input.value = element[key]; input.autocomplete = 'off'; if (['rate', 'mass'].includes(key)) input.inputMode = 'decimal'; if (['reserves', 'max_reserves'].includes(key)) input.inputMode = 'numeric'; if (key === 'id') input.maxLength = 24; if (key === 'name') {input.maxLength = 100; input.placeholder = 'Необязательно';}}
    input.addEventListener('input', () => {const old = element[key]; element[key] = kind === 'checkbox' ? input.checked : input.value;
      if (key === 'id') {element.id = input.value.toUpperCase(); renameReferences(state.tree, old, element.id); if (state.editor === 'expression' && /^[A-Za-z][A-Za-z0-9_]*$/.test(old)) {state.expression = state.expression.replace(new RegExp(`\\b${old}\\b`, 'gi'), element.id); $('#expression').value = state.expression;}}
      dirty(); preview();
    });
    input.addEventListener('change', () => {if (key === 'id') {input.value = element.id; renderBuilder();} if (key === 'name') renderBuilder();}); cell.append(input); row.append(cell);
  }
  function renameReferences(node, before, after) {if (node.ref !== undefined) {if (node.ref === before) node.ref = after;} else node.children.forEach(c => renameReferences(c, before, after));}
  function pruneReferences(node, id) {if (node.children) {node.children = node.children.filter(c => c.ref !== id); node.children.forEach(c => pruneReferences(c, id));}}
  function renderElements() {
    const tbody = $('#element-rows'); tbody.replaceChildren();
    state.elements.forEach((element, index) => {
      const row = el('tr');
      fieldCell(row, element, 'id', 'ID'); fieldCell(row, element, 'name', 'Название'); fieldCell(row, element, 'rate', 'Параметр ω'); fieldCell(row, element, 'mass', 'Масса, кг');
      fieldCell(row, element, 'reserves', 'Резервов k'); fieldCell(row, element, 'max_reserves', 'Макс. k', 'text', 'reserve-only'); fieldCell(row, element, 'reservable', 'Разрешён', 'checkbox', 'reserve-only');
      const cell = el('td'); cell.dataset.field = 'delete'; const remove = button('×', () => {if (state.elements.length === 1) {showError('В системе должен оставаться хотя бы один элемент.'); return;} const [removed] = state.elements.splice(index, 1); pruneReferences(state.tree, removed.id); dirty(); renderElements(); renderBuilder();}); remove.className = 'delete-element'; remove.setAttribute('aria-label', `Удалить элемент ${element.id}`); cell.append(remove); row.append(cell); tbody.append(row);
    });
  }
  function nextId() {let i = 1; while (state.elements.some(e => e.id === `E${i}`)) i++; return `E${i}`;}
  function renderBuilder() {
    const container = $('#builder'); container.replaceChildren();
    function draw(node, parent, index, depth) {
      if (node.ref !== undefined) {const line = el('div', undefined, 'group-leaf'); const select = el('select'); select.setAttribute('aria-label', 'Элемент группы');
        state.elements.forEach(e => {const opt = el('option', `${e.id}${e.name ? ' · ' + e.name : ''}`); opt.value = e.id; select.append(opt);}); select.value = node.ref;
        select.addEventListener('change', () => {node.ref = select.value; dirty(); preview();}); line.append(select, button('Удалить', () => {parent.children.splice(index, 1); dirty(); renderBuilder();}, 'remove-node')); return line;}
      const group = el('div', undefined, 'group'); const header = el('div', undefined, 'group-header'); const op = el('select'); op.setAttribute('aria-label', 'Условие группы');
      for (const [value, label] of [['and', 'Работают все (И)'], ['or', 'Достаточно одного (ИЛИ)']]) {const option = el('option', label); option.value = value; option.disabled = value === 'or' && state.mode === 'reserve'; op.append(option);}
      op.value = node.op;
      op.addEventListener('change', () => {node.op = op.value; dirty(); preview();}); header.append(op);
      if (parent) header.append(button('Удалить группу', () => {parent.children.splice(index, 1); dirty(); renderBuilder();}, 'remove-node'));
      group.append(header); const children = el('div', undefined, 'group-children'); node.children.forEach((c, i) => children.append(draw(c, node, i, depth + 1))); group.append(children);
      const tools = el('div', undefined, 'group-tools'); tools.append(button('+ Элемент', () => {if (countNodes(state.tree) >= 200) {showError('Достигнут предел конструктора: 200 узлов.'); return;} node.children.push({ref: state.elements[0].id}); dirty(); renderBuilder();}));
      if (depth < 12) tools.append(button('+ Группа', () => {if (countNodes(state.tree) >= 199) {showError('Достигнут предел конструктора: 200 узлов.'); return;} node.children.push({op: 'and', children: []}); dirty(); renderBuilder();})); group.append(tools); return group;
    }
    container.append(draw(state.tree, null, 0, 0));
    const tokens = $('#element-tokens'); tokens.replaceChildren(); state.elements.forEach(e => tokens.append(button(e.id, () => {const input = $('#expression'); const start = input.selectionStart, end = input.selectionEnd; input.setRangeText(e.id, start, end, 'end'); state.expression = input.value; dirty(); preview(); input.focus();})));
    $('#expression-editor').hidden = state.editor !== 'expression'; container.hidden = state.editor !== 'builder'; $('#toggle-editor').textContent = state.editor === 'builder' ? 'Ввести выражением' : 'Открыть конструктор'; preview();
  }
  function countNodes(node) {return 1 + (node.children || []).reduce((sum, c) => sum + countNodes(c), 0);}
  const settings = {title: '#project-title', time: '#time', rate_scale: '#rate-scale', target: '#target', max_mass: '#max-mass', search_limit: '#search-limit'};
  function applyMode() {$$('.analysis-only').forEach(n => n.hidden = state.mode !== 'analysis'); $('#task-scope').textContent = state.mode === 'analysis' ? 'Задание 1: условия И/ИЛИ и общие физические элементы. Один ID в разных ветвях означает одну и ту же группу.' : 'Задание 2: последовательная система и одинаковые нагруженные резервы. Каждый ID используется один раз.'; document.body.dataset.mode = state.mode; $$('[data-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === state.mode))); $$('.reserve-only').forEach(n => n.hidden = state.mode !== 'reserve'); $('#next').textContent = nextLabel();}
  function renderAll() {Object.entries(settings).forEach(([key, selector]) => $(selector).value = state[key]); $('#expression').value = state.expression; renderElements(); renderBuilder(); applyMode(); $('#rate-unit').textContent = $('#rate-scale').selectedOptions[0].textContent; showStage(0);}
  function pretty(value, digits = 10) {const n = Number(value); if (!Number.isFinite(n)) return String(value); if (n !== 0 && Math.abs(n) < 1e-7) return n.toExponential(5).replace('.', ','); return n.toLocaleString('ru-RU', {maximumFractionDigits: digits, useGrouping: false});}
  function probability(value) {const n = Number(value); if (n === 1 && String(value) !== '1' && !/^1\.0+$/.test(String(value))) return '≈ 1'; return pretty(value, 12);}
  function fillTable(tbody, rows) {tbody.replaceChildren(); rows.forEach(values => {const row = el('tr'); values.forEach(value => row.append(el('td', value))); tbody.append(row);});}
  function renderResults() {
    $('#empty-result').hidden = true; $('#results').hidden = false;
    $('#metric-p').textContent = probability(result.probability); $('#metric-p').title = result.probability;
    $('#metric-q').textContent = `Q = ${pretty(result.failure_probability, 12)}`; $('#metric-q').title = result.failure_probability;
    $('#metric-mass').textContent = pretty(result.mass, 6) + ' кг'; $('#metric-increase').textContent = `Без резервов: ${pretty(result.unreserved_mass, 6)} кг · +${pretty(result.mass_increase, 6)} кг (${pretty(result.mass_increase_percent, 2)}%)`;
    $('#metric-target').textContent = result.target_met && result.mass_limit_met ? 'Выполнено' : 'Не выполнено'; $('#metric-before').textContent = `Pзад = ${resultProblem.target}; до подбора P = ${probability(result.initial.probability)}${result.mass_limit_met ? '' : '; превышен предел массы'}`;
    $('#result-expression').textContent = result.expression;
    $('#result-formula').textContent = result.formula + ' Масса = Σmᵢ(kᵢ+1).';
    $('#warnings').replaceChildren(...result.warnings.map(w => el('li', w)));
    const parsed = new DOMParser().parseFromString(result.svg, 'image/svg+xml'); const drawing = document.importNode(parsed.documentElement, true); $('#diagram').replaceChildren(drawing);
    fillTable($('#result-rows'), result.elements.map(e => [e.id, (e.name || e.id) + (e.used ? '' : ' (не используется)'), `${e.reserves} / ${e.copies}`, pretty(e.group_mass, 6), pretty(e.importance, 12)]));
    const opt = result.optimization; $('#optimization-status').hidden = !opt; $('#trace-details').hidden = !opt || !opt.trace.length;
    if (opt) {const titles = {optimal: 'Минимальная масса подтверждена', feasible: 'Найдено допустимое решение', infeasible: 'В заданных пределах решения нет', limit: 'Поиск остановлен по лимиту'};
      $('#optimization-status').className = 'message' + (opt.status === 'optimal' ? ' success' : ''); $('#optimization-status').textContent = `${titles[opt.status]}. ${opt.reason}. Проверено структур: ${opt.visited}.`;
      fillTable($('#trace-rows'), opt.trace.map((t, i) => [String(i + 1), t.element, probability(t.probability), pretty(t.mass, 6)]));}
    applyMode();
  }
  function download(content, filename, type) {const blob = content instanceof Blob ? content : new Blob([content], {type}); const url = URL.createObjectURL(blob); const link = el('a'); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);}
  async function exportResult(format) {if (!result || busy) return; setBusy(true); clearError(); try {const response = await api('/api/export/' + format, {problem: resultProblem, allocation: result.elements.map(e => e.reserves)}); download(await response.blob(), `nadeg-report.${format}`);} catch (error) {showError(error);} finally {setBusy(false);}}
  async function confirmAction(title, text) {const dialog = $('#confirm-dialog'); $('#confirm-title').textContent = title; $('#confirm-text').textContent = text; dialog.returnValue = 'cancel'; return new Promise(resolve => {dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), {once: true}); dialog.showModal();});}
  function validateProject(document) {
    if (document && document.lab !== undefined && document.lab !== 1) throw new Error('Этот проект относится к другой лабораторной работе. Откройте его в соответствующей вкладке.');
    if (!document || document.version !== 1 || !document.state) throw new Error('Неподдерживаемый формат проекта. Ожидается JSON NADEG версии 1.');
    const input = document.state, clean = fresh(); if (!['analysis', 'reserve'].includes(input.mode) || !Array.isArray(input.elements) || !input.elements.length || input.elements.length > 40) throw new Error('Некорректный список элементов проекта.');
    for (const key of Object.keys(settings)) {if (!['string', 'number'].includes(typeof input[key]) || String(input[key]).length > 160) throw new Error('Некорректные настройки проекта.'); clean[key] = String(input[key]);}
    if (!['1', '1e-4', '1e-6'].includes(clean.rate_scale)) throw new Error('Неизвестный масштаб.');
    clean.elements = input.elements.map(e => {if (!e || typeof e !== 'object') throw new Error('Некорректный элемент проекта.'); const item = {}; for (const key of ['id', 'name', 'rate', 'mass', 'reserves', 'max_reserves']) {if (!['string', 'number'].includes(typeof e[key]) || String(e[key]).length > (key === 'name' ? 100 : 80)) throw new Error('Некорректные параметры элемента.'); item[key] = String(e[key]);} item.reservable = e.reservable !== false; return item;});
    let nodes = 0; function cleanTree(n, depth = 0) {if (++nodes > 200 || depth > 13 || !n || typeof n !== 'object') throw new Error('Структура проекта слишком сложна.'); if (typeof n.ref === 'string' && n.ref.length <= 80) return {ref: n.ref}; if (!['and', 'or'].includes(n.op) || !Array.isArray(n.children)) throw new Error('Некорректная группа.'); return {op: n.op, children: n.children.map(c => cleanTree(c, depth + 1))};}
    clean.tree = cleanTree(input.tree); if (!clean.tree.children) throw new Error('Корень конструктора должен быть группой.'); clean.mode = input.mode; clean.editor = input.editor === 'expression' ? 'expression' : 'builder'; clean.expression = typeof input.expression === 'string' ? input.expression : ''; if (clean.expression.length > 2400) throw new Error('Выражение слишком длинное.'); return clean;
  }
  function parseCSV(text) {const firstLine = text.replace(/^\ufeff/, '').split(/\r?\n/).find(line => line.trim()) || ''; const delimiter = firstLine.includes(';') ? ';' : firstLine.includes('\t') ? '\t' : ',';
    const rows = []; let row = [], cell = '', quoted = false;
    text = text.replace(/^\ufeff/, ''); for (let i = 0; i < text.length; i++) {const c = text[i]; if (c === '"') {if (quoted && text[i + 1] === '"') {cell += '"'; i++;} else quoted = !quoted;} else if (!quoted && c === delimiter) {row.push(cell.trim()); cell = '';} else if (!quoted && (c === '\n' || c === '\r')) {if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell.trim()); if (row.some(Boolean)) rows.push(row); row = []; cell = '';} else cell += c;}
    if (quoted) throw new Error('CSV: незакрытая кавычка.'); row.push(cell.trim()); if (row.some(Boolean)) rows.push(row); if (!rows.length) throw new Error('CSV пуст.');
    const numeric = value => value !== undefined && String(value).trim() !== '' && Number.isFinite(Number(String(value).replace(',', '.')));
    let elements;
    if (rows.length === 2 && rows.every(r => r.every(numeric))) {if (rows[0].length !== rows[1].length) throw new Error('CSV NADEG: строки параметров и масс должны иметь одинаковую длину.'); elements = rows[0].map((rate, i) => ({id: `E${i + 1}`, name: '', rate, mass: rows[1][i], reserves: 0, max_reserves: 3, reservable: true}));}
    else {const header = rows.shift().map(x => x.toLowerCase()); const aliases = {id: ['id'], name: ['name', 'название'], rate: ['rate', 'omega', 'ω', 'параметр отказов (масштаб проекта)'], mass: ['mass', 'масса', 'масса элемента, кг'], reserves: ['reserves', 'k', 'резервов'], max_reserves: ['max_reserves', 'max_k'], reservable: ['reservable']}; const indices = {}; Object.entries(aliases).forEach(([key, values]) => indices[key] = header.findIndex(x => values.includes(x))); if (indices.rate < 0 || indices.mass < 0) throw new Error('CSV: нужны колонки rate и mass. Необязательные: id, name, reserves, max_reserves, reservable.');
      elements = rows.map((r, i) => {const get = (key, fallback) => indices[key] >= 0 && r[indices[key]] !== '' ? r[indices[key]] : fallback; const k = get('reserves', 0); return {id: get('id', `E${i + 1}`).toUpperCase(), name: get('name', ''), rate: get('rate', ''), mass: get('mass', ''), reserves: k, max_reserves: get('max_reserves', Math.max(3, Number(k))), reservable: !['false', '0', 'нет'].includes(String(get('reservable', true)).toLowerCase())};});}
    if (!elements.length || elements.length > 40) throw new Error('CSV должен содержать от 1 до 40 элементов.'); return elements;
  }
  Object.entries(settings).forEach(([key, selector]) => $(selector).addEventListener('input', () => {state[key] = $(selector).value; dirty(); if (key === 'rate_scale') $('#rate-unit').textContent = $('#rate-scale').selectedOptions[0].textContent;}));
  $('#expression').addEventListener('input', () => {state.expression = $('#expression').value; dirty(); preview();});
  $('#toggle-editor').addEventListener('click', async () => {if (state.editor === 'builder') {try {state.expression = treeExpression(state.tree);} catch (error) {showError(error); return;} state.editor = 'expression'; $('#expression').value = state.expression;} else {if (state.expression !== treeExpressionSafe(state.tree) && !await confirmAction('Открыть конструктор?', 'Изменённое вручную выражение будет заменено последней структурой конструктора. Скачайте проект, если хотите сохранить оба варианта.')) return; state.editor = 'builder';} dirty(); renderBuilder();});
  function treeExpressionSafe(tree) {try {return treeExpression(tree);} catch (_) {return '';}}
  $('#add-element').addEventListener('click', () => {if (state.elements.length >= 40) {showError('Максимум 40 элементов для интерактивного расчёта.'); return;} const id = nextId(); state.elements.push({id, name: '', rate: '', mass: '1', reserves: 0, max_reserves: 3, reservable: true}); state.tree.children.push({ref: id}); dirty(); renderElements(); renderBuilder(); $('#element-rows tr:last-child input[data-field=name]').focus();});
  $$('[data-mode]').forEach(b => b.addEventListener('click', () => {if (busy) return; state.mode = b.dataset.mode; dirty(); renderBuilder(); applyMode(); showStage(0);}));
  $$('[data-step]').forEach(b => b.addEventListener('click', () => {if (!busy) showStage(Number(b.dataset.step));}));
  $('#back').addEventListener('click', () => {if (!busy) showStage(Math.max(0, stage - 1));});
  $('#next').addEventListener('click', async () => {if (busy) return; if (stage !== 0) {run(); return;} try {const data = problem(true); setBusy(true); await api('/api/lab1/validate', data); showStage(1);} catch (e) {showError(e);} finally {setBusy(false);}});
  ['pdf', 'csv', 'svg'].forEach(format => $('#export-' + format).addEventListener('click', () => exportResult(format)));
  $('#save-project').addEventListener('click', () => {download(JSON.stringify({version: 1, lab: 1, state}, null, 2), `nadeg-lab1-task${state.mode === 'analysis' ? 1 : 2}-${(state.title || 'project').replace(/[^a-zA-Zа-яА-ЯёЁ0-9]+/g, '-').slice(0,70)}.json`, 'application/json'); $('.project-menu').open = false;});
  $('#load-project').addEventListener('click', () => {$('#project-file').click(); $('.project-menu').open = false;});
  $('#project-file').addEventListener('change', async event => {const file = event.target.files[0]; event.target.value = ''; if (!file) return; const token = ++loadToken; try {if (file.size > 131072) throw new Error('Проект слишком большой: максимум 128 КБ.'); const imported = validateProject(NadegErrors.parseProject(await file.text())); if (!await confirmAction('Открыть проект?', 'Текущий черновик будет заменён данными файла.')) return; if (token !== loadToken) return; state = imported; dirty(); renderAll();} catch (error) {showError(error);}});
  $('#new-project').addEventListener('click', async () => {if (await confirmAction('Новый проект?', 'Сначала скачайте текущий проект, если хотите сохранить его отдельно.')) {state = fresh(); dirty(); renderAll();} $('.project-menu').open = false;});
  $('#import-csv').addEventListener('click', () => $('#csv-file').click());
  $('#csv-file').addEventListener('change', async event => {const file = event.target.files[0]; event.target.value = ''; if (!file) return; try {if (file.size > 131072) throw new Error('CSV слишком большой: максимум 128 КБ.'); const elements = parseCSV(await file.text()); if (!await confirmAction('Импортировать элементы?', 'Текущая таблица и структура будут заменены. Масштаб параметров останется выбранным на экране. Поддерживается CSV NADEG из двух строк и таблица с заголовками.')) return; state.elements = elements; state.tree = {op: 'and', children: elements.map(e => ({ref: e.id}))}; state.editor = 'builder'; state.expression = ''; dirty(); renderAll();} catch (error) {showError(error);}});
  document.addEventListener('visibilitychange', () => {if (document.hidden) {clearTimeout(saveTimer); persist(clone(state));}});
  NadegErrors.configure(path => {
    if (path[0] === 'problem') path = path.slice(1);
    if (path[0] === 'elements') {
      const row = $$('#element-rows tr')[path[1] || 0];
      return {stage: 0, node: row && [...row.querySelectorAll('input')].find(n => n.dataset.field === (path[2] || 'id'))};
    }
    if (path[0] === 'expression') return {stage: 1, node: state.editor === 'expression' ? $('#expression') : $('#builder select')};
    return {stage: 0, node: settings[path[0]] ? $(settings[path[0]]) : null};
  }, showStage);
  renderAll(); initStorage();
})();
