'use strict';
(() => {
  let resolveField = () => null, activate = () => {};
  class InputError extends Error {
    constructor(message, issues = []) {super(message); this.issues = issues;}
  }
  function clear() {
    document.querySelectorAll('[aria-invalid="true"]').forEach(n => {n.removeAttribute('aria-invalid'); n.removeAttribute('aria-describedby');});
    const box = document.querySelector('#error'); if (box) box.hidden = true;
  }
  function show(value) {
    clear();
    const error = typeof value === 'string' ? new InputError(value) : value;
    const box = document.querySelector('#error'); box.replaceChildren(); box.hidden = false; box.tabIndex = -1;
    const heading = document.createElement('p'); heading.textContent = error?.message || 'Не удалось выполнить действие. Проверьте данные и повторите.'; box.append(heading);
    let first;
    if (Array.isArray(error?.issues)) {
      const list = document.createElement('ul');
      for (const issue of error.issues) {
        const li = document.createElement('li'), target = resolveField(issue.path || []);
        const text = `${issue.label ? issue.label + ': ' : ''}${issue.message}`;
        if (target?.node) {
          const go = document.createElement('button'); go.type = 'button'; go.textContent = text; go.className = 'error-link';
          go.addEventListener('click', () => {activate(target.stage); target.node.focus(); target.node.scrollIntoView({block:'center'});}); li.append(go);
          target.node.setAttribute('aria-invalid', 'true'); target.node.setAttribute('aria-describedby', 'error');
          if (!first) first = target;
        } else li.textContent = text;
        list.append(li);
      }
      if (list.children.length) box.append(list);
    }
    if (first) {activate(first.stage); requestAnimationFrame(() => first.node.focus());} else box.focus();
  }
  function fromResponse(data, status) {
    const detail = Array.isArray(data?.detail) ? data.detail.join('\n') : data?.detail;
    return new InputError(detail || `Не удалось выполнить действие (${status}). Повторите позже.`, Array.isArray(data?.errors) ? data.errors : []);
  }
  function field(message, path, label) {return new InputError('Исправьте отмеченное поле', [{path, label, message}]);}
  function parseProject(text) {
    try {return JSON.parse(text);} catch (_) {throw new InputError('Файл повреждён или не является проектом NADEG. Выберите сохранённый файл проекта JSON.');}
  }
  window.NadegErrors = {InputError, clear, show, fromResponse, field, parseProject, configure(resolve, showStage) {resolveField = resolve; activate = showStage;}};
})();
