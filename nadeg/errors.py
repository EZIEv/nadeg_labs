"""Stable, Russian input errors with paths for the browser's field navigation."""
import re
from decimal import Decimal, InvalidOperation

LABELS = {'title':'Название', 'time':'Время работы', 'rate_scale':'Масштаб параметров отказов',
 'target':'Требуемая вероятность', 'max_mass':'Предел массы', 'search_limit':'Лимит поиска',
 'expression':'Условие работоспособности', 'task':'Задание', 'model':'Способ расчёта',
 'id':'ID', 'name':'Название', 'rate':'Параметр ω', 'mass':'Масса', 'reserves':'Резервов k',
 'max_reserves':'Максимум резервов', 'reservable':'Разрешение резервирования',
 'resource':'Расчётный ресурс', 'flight_time':'Среднее время полёта', 'flights_per_day':'Полётов за день',
 'interval':'Период обслуживания', 'periods':'Периоды обслуживания', 'operations':'Регламент ТО',
 'elements':'Элементы', 'labor':'Трудоёмкость', 'purpose':'Назначение', 'construction':'Описание конструкции',
 'placement':'Размещение', 'conclusion':'Вывод', 'limitations':'Ограничения', 'text':'Текст материала',
 'image':'Изображение', 'materials':'Материалы', 'rows':'Анализ',
 'condition':'Условие воздействия', 'shortcoming':'Конструктивный недостаток', 'consequence':'Последствие',
 'measure':'Мероприятие', 'justification':'Обоснование', 'content':'Содержимое таблицы', 'allocation':'Распределение резервов'}
LABOR = {'preliminary':'Предварительная подготовка','preflight':'Предполётная подготовка',
 'turnaround':'Повторный вылет','postflight':'Послеполётная подготовка'}

def label_for(path, body):
    current = body
    parts = []
    for key in path:
        if isinstance(key, int):
            try: item = current[key]
            except (TypeError, KeyError, IndexError): item = {}
            ident = item.get('id') or item.get('name') or str(key + 1) if isinstance(item, dict) else str(key + 1)
            parts.append(str(ident)[:160])
        elif key != 'problem':
            parts.append(LABELS.get(key, LABOR.get(key, 'Форма ' + key if re.fullmatch(r'P\d+', str(key)) else 'Поле')))
        try: current = current[key]
        except (KeyError, TypeError, IndexError): current = {}
    return ' → '.join(parts) or 'Исходные данные'

def message_for(item):
    kind, ctx = item['type'], item.get('ctx', {})
    if kind == 'value_error':
        message = str(ctx.get('error', 'Проверьте значение'))
        return re.sub(r'^Value error,?\s*', '', message)
    messages = {'missing':'Заполните поле', 'greater_than_equal':f"Введите число не меньше {ctx.get('ge', 0)}",
      'greater_than':f"Введите число больше {ctx.get('gt', 0)}", 'less_than_equal':f"Введите число не больше {ctx.get('le', '')}",
      'less_than':f"Введите число меньше {ctx.get('lt', '')}", 'int_parsing':'Введите целое число',
      'int_type':'Введите целое число', 'int_from_float':'Введите целое число', 'bool_type':'Выберите значение',
      'bool_parsing':'Выберите значение', 'string_type':'Введите текст', 'list_type':'Ожидается список',
      'dict_type':'Ожидается объект с полями', 'model_type':'Проверьте состав данных',
      'json_invalid':'Запрос повреждён или не является JSON', 'extra_forbidden':'Это поле не поддерживается',
      'literal_error':'Выберите одно из доступных значений', 'string_pattern_mismatch':'Проверьте формат значения',
      'string_too_short':f"Введите не менее {ctx.get('min_length', 1)} символов",
      'string_too_long':f"Допускается не более {ctx.get('max_length', '')} символов",
      'too_short':f"Добавьте не менее {ctx.get('min_length', 1)} записей",
      'too_long':f"Допускается не более {ctx.get('max_length', '')} записей"}
    if kind == 'string_pattern_mismatch' and item['loc'][-1:] == ('id',):
        return 'Начните ID с латинской буквы; используйте латинские буквы, цифры и знак подчёркивания'
    return messages.get(kind, 'Проверьте значение поля')

def response_error(message, *, path=None, body=None, issues=None):
    if issues is None:
        path = list(path or [])
        issues = [{'path':path, 'label':label_for(path, body or {}), 'message':message}]
    return {'detail':message, 'errors':issues}

def validation_payload(error):
    body = error.body if isinstance(error.body, dict) else {}
    issues = []
    for item in error.errors():
        path = list(item['loc'][1:])
        base = body.get('problem', {}) if path[:1] == ['problem'] else body
        local = path[1:] if path[:1] == ['problem'] else path
        prefix = ['problem'] if path[:1] == ['problem'] else []
        if local == ['periods'] and isinstance(base.get('periods'), list):
            periods = base['periods']
            try:
                for i in range(1, len(periods)):
                    a = Decimal(str(periods[i-1]['interval']).replace(',', '.')); b = Decimal(str(periods[i]['interval']).replace(',', '.'))
                    if a > 0 and (b <= a or b % a):
                        path = prefix + ['periods', i, 'interval']; break
            except (KeyError, ValueError, InvalidOperation, TypeError): pass
        if local == [] and 'Идентификаторы элементов' in str(item.get('msg', '')):
            ids = [str(e.get('id', '')).upper() for e in base.get('elements', [])]
            duplicate = next((i for i, ident in enumerate(ids) if ident in ids[:i]), 0)
            path = prefix + ['elements', duplicate, 'id']
        if local[:1] == ['elements'] and len(local) == 2 and 'Текущий резерв' in str(item.get('msg', '')):
            path = [*path, 'max_reserves']
        issues.append({'path':path, 'label':label_for(path, body), 'message':message_for(item)})
    return response_error('Исправьте отмеченные поля и повторите действие', issues=issues)
