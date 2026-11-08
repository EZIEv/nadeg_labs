"""Boolean physical-element analysis and the guide's bounded serial reserve search.

Independent, nonrepairable, actively loaded elements; identical copies use k.
Task 1 composes the Boolean scheme, task 2 uses the serial approximation.
"""
from decimal import Decimal, localcontext
import heapq
import re
import time

from .models import Problem
from .boolean import DecisionDiagram, StructureLimit

D = Decimal
ZERO, ONE = D(0), D(1)


class ModelError(ValueError):
    def __init__(self, message, path=None):
        self.path = path if path is not None else ["expression"]
        super().__init__(message)


def parse(expression: str, ids: set[str]):
    text = expression.upper().replace("∧", "&").replace("∨", "|")
    text = re.sub(r"\b(?:AND|И)\b", "&", text)
    text = re.sub(r"\b(?:OR|ИЛИ)\b", "|", text)
    tokens = re.findall(r"[A-Z][A-Z0-9_]*|[&|()]|\S", text)
    if len(tokens) > 500:
        raise ModelError("Слишком длинное выражение: максимум 500 токенов")
    position = 0

    def atom(depth):
        nonlocal position
        if depth > 32:
            raise ModelError("Допускается не более 32 уровней вложенности")
        if position >= len(tokens):
            raise ModelError("Выражение не закончено: укажите элемент или группу")
        token = tokens[position]
        position += 1
        if token == "(":
            result = disjunction(depth + 1)
            if position >= len(tokens) or tokens[position] != ")":
                raise ModelError("Не хватает закрывающей скобки")
            position += 1
            return result
        if token not in ids:
            raise ModelError(f"Неизвестный элемент или символ: {token}")
        return token

    def conjunction(depth):
        nonlocal position
        result = atom(depth)
        while position < len(tokens) and tokens[position] == "&":
            position += 1
            result = ("and", result, atom(depth))
        return result

    def disjunction(depth):
        nonlocal position
        result = conjunction(depth)
        while position < len(tokens) and tokens[position] == "|":
            position += 1
            result = ("or", result, conjunction(depth))
        return result

    result = disjunction(0)
    if position != len(tokens):
        raise ModelError(f"Лишний символ или пропущенный оператор: {tokens[position]}")
    return result


def leaves(node):
    return [node] if isinstance(node, str) else leaves(node[1]) + leaves(node[2])


def expression_text(node):
    if isinstance(node, str):
        return node
    return f"({expression_text(node[1])} {'И' if node[0] == 'and' else 'ИЛИ'} {expression_text(node[2])})"


class Calculator:
    def __init__(self, problem: Problem):
        self.problem = problem
        self.elements = problem.elements
        self.tree = parse(problem.expression, {e.id for e in self.elements})
        self.used = set(leaves(self.tree))
        def serial(node):
            return isinstance(node, str) or (node[0] == "and" and serial(node[1]) and serial(node[2]))
        if problem.task == 2 and (not serial(self.tree) or len(leaves(self.tree)) != len(self.used)):
            raise ModelError("Формула методички применяется к последовательной структуре без повторов ID. Параллельные копии элементов задайте количеством резервов k")
        self.diagram = None
        if problem.task == 1:
            try:
                self.diagram = DecisionDiagram(self.tree, [e.id for e in self.elements])
            except StructureLimit as error:
                raise ModelError(str(error))
        self.base_q = []
        self.warnings = []
        for index, e in enumerate(self.elements):
            x = e.rate * D(problem.rate_scale) * problem.time
            if x > 1:
                raise ModelError(f"{e.id}: ωτ больше 1. Уменьшите время или проверьте параметр ω и его масштаб", ["elements", index, "rate"])
            self.base_q.append(x)
            if x > D("0.01"):
                self.warnings.append(f"{e.id}: ωτ = {x}; приближение методички может быть неточным")
        unused = [e.id for e in self.elements if e.id not in self.used]
        if unused:
            self.warnings.append("Не участвуют в условии работоспособности, но входят в массу: " + ", ".join(unused))
        self.formula = ("Задание 1: qᵢ ≈ ωᵢτ; Qᵢ = qᵢ^(kᵢ+1). Вероятность заданного условия И/ИЛИ вычисляется с учётом общих физических элементов."
                        if problem.task == 1 else "Задание 2: P ≈ 1 − Σ(ωᵢτ)^(kᵢ+1), последовательная система с независимыми нагруженными резервами.")
        self.warnings.append(self.formula)
        if problem.task == 1:
            self.warnings.append("Независимость предполагается между разными физическими элементами. Повтор ID означает ту же группу, а не новую независимую копию. Схема изображает логическое условие работоспособности.")

    def failure(self, reserves):
        failures = [q ** (k + 1) for q, k in zip(self.base_q, reserves)]
        if self.diagram is not None:
            return self.diagram.probabilities(failures)[1]
        result = sum((failures[i] for i, e in enumerate(self.elements) if e.id in self.used), ZERO)
        if result > 1:
            raise ModelError("По формуле методички получилось P < 0. Проверьте исходные данные: приближение неприменимо")
        return result

    def mass(self, reserves):
        return sum((e.mass * (k + 1) for e, k in zip(self.elements, reserves)), ZERO)

    def metrics(self, reserves):
        q = self.failure(reserves)
        p = self.diagram.probabilities([x ** (k + 1) for x, k in zip(self.base_q, reserves)])[0] if self.diagram is not None else ONE - q
        return {"probability": str(p), "failure_probability": str(q), "mass": str(self.mass(reserves))}

    def summarize(self, reserves):
        initial = tuple(e.reserves for e in self.elements)
        metrics = self.metrics(reserves)
        initial_metrics = self.metrics(initial)
        raw_mass = self.mass((0,) * len(self.elements))
        elements = []
        q = self.failure(reserves)
        for i, (e, k) in enumerate(zip(self.elements, reserves)):
            effective = [v ** (n + 1) for v, n in zip(self.base_q, reserves)]
            effective[i] = ZERO
            ideal_q = self.diagram.probabilities(effective)[1] if self.diagram is not None else sum((effective[j] for j, el in enumerate(self.elements) if el.id in self.used), ZERO)
            elements.append({"id": e.id, "name": e.name or e.id, "rate": str(e.rate), "mass": str(e.mass),
                             "reserves": k, "copies": k + 1, "used": e.id in self.used,
                             "element_probability": str(ONE - self.base_q[i]),
                             "group_failure_probability": str(self.base_q[i] ** (k + 1)),
                             "importance": str(max(ZERO, q - ideal_q)),
                             "group_mass": str(e.mass * (k + 1))})
        return {**metrics, "initial": initial_metrics, "unreserved_mass": str(raw_mass),
                "mass_increase": str(self.mass(reserves) - raw_mass),
                "mass_increase_percent": str((self.mass(reserves) / raw_mass - ONE) * 100),
                "target_met": q <= ONE - self.problem.target,
                "mass_limit_met": self.problem.max_mass is None or self.mass(reserves) <= self.problem.max_mass,
                "expression": expression_text(self.tree), "elements": elements,
                "warnings": self.warnings, "model": self.problem.model, "task": self.problem.task, "formula": self.formula, "time": str(self.problem.time)}


def calculate(problem: Problem):
    with localcontext() as context:
        context.prec = 60
        calculator = Calculator(problem)
        result = calculator.summarize(tuple(e.reserves for e in problem.elements))
        result["optimization"] = None
        return result


def optimize(problem: Problem):
    """Uniform-cost search proves the first feasible result minimal in the bounds.

    If resource bounds interrupt search, any incumbent is reported as feasible only.
    The current reserve allocation is a lower bound, never silently removed.
    """
    with localcontext() as context:
        context.prec = 60
        if problem.task != 2:
            raise ModelError("Подбор резервирования выполняется по заданию 2. Выберите последовательную систему без повторов ID")
        calc = Calculator(problem)
        start = tuple(e.reserves for e in problem.elements)
        target_q = ONE - problem.target
        maximum = tuple(e.max_reserves if e.reservable and e.id in calc.used else e.reserves for e in calc.elements)
        started = time.monotonic()
        candidate = None
        trace = []

        def feasible(state):
            return calc.failure(state) <= target_q and (problem.max_mass is None or calc.mass(state) <= problem.max_mass)

        if feasible(start):
            result = calc.summarize(start)
            result["optimization"] = {"status": "optimal", "visited": 1, "trace": [], "reason": "Исходная структура уже удовлетворяет ограничениям"}
            return result
        if problem.max_mass is not None and calc.mass(start) > problem.max_mass:
            result = calc.summarize(start)
            result["optimization"] = {"status": "infeasible", "visited": 1, "trace": [], "reason": "Исходная масса уже превышает предел; удаление текущих резервов не разрешено"}
            return result
        if calc.failure(maximum) > target_q:
            result = calc.summarize(start)
            result["optimization"] = {"status": "infeasible", "visited": 1, "trace": [], "reason": "Даже максимальный разрешённый резерв не достигает требуемой вероятности"}
            return result

        # A cheap feasible incumbent is useful if the exact search hits its limit.
        state = start
        for _ in range(sum(maximum) - sum(start)):
            if time.monotonic() - started >= 2:
                break
            options = []
            current_q = calc.failure(state)
            for i, e in enumerate(calc.elements):
                if time.monotonic() - started >= 2:
                    break
                if state[i] < maximum[i]:
                    next_state = state[:i] + (state[i] + 1,) + state[i + 1:]
                    if problem.max_mass is None or calc.mass(next_state) <= problem.max_mass:
                        gain = (current_q - calc.failure(next_state)) / e.mass
                        options.append((gain, -e.mass, -i, next_state))
            if not options:
                break
            _, _, negative_i, state = max(options)
            trace.append({"element": calc.elements[-negative_i].id, **calc.metrics(state)})
            if feasible(state):
                candidate = state
                break
        greedy_trace = trace if candidate is not None else []

        queue = [(calc.mass(start), start)]
        seen = {start}
        parents = {}
        visited = 0
        status, reason = "infeasible", "В заданных пределах решения нет"
        while queue:
            if visited >= problem.search_limit or len(seen) >= 150000 or time.monotonic() - started >= 5:
                status = "feasible" if candidate is not None else "limit"
                reason = "Достигнут лимит поиска; минимальность массы не подтверждена"
                break
            mass, state = heapq.heappop(queue)
            visited += 1
            if candidate is not None and mass >= calc.mass(candidate):
                status, reason = "optimal", "Все структуры с меньшей массой проверены"
                break
            if feasible(state):
                candidate, status, reason = state, "optimal", "Найдена структура минимальной массы в заданных пределах"
                break
            for i, e in enumerate(calc.elements):
                if state[i] >= maximum[i]:
                    continue
                next_state = state[:i] + (state[i] + 1,) + state[i + 1:]
                next_mass = mass + e.mass
                if next_state in seen or (problem.max_mass is not None and next_mass > problem.max_mass):
                    continue
                if candidate is not None and next_mass >= calc.mass(candidate):
                    continue
                seen.add(next_state)
                parents[next_state] = (state, i)
                heapq.heappush(queue, (next_mass, next_state))
        else:
            if candidate is not None:
                status, reason = "optimal", "Все структуры с меньшей массой проверены"
        final = candidate if candidate is not None else start
        trace = []
        if candidate is not None and candidate in parents:
            cursor = candidate
            while cursor != start:
                previous, i = parents[cursor]
                trace.append({"element": calc.elements[i].id, **calc.metrics(cursor)})
                cursor = previous
            trace.reverse()
        elif candidate is not None:
            trace = greedy_trace
        result = calc.summarize(final)
        result["optimization"] = {"status": status, "reason": reason, "visited": visited, "trace": trace,
                                  "bounds": "Текущие резервы — нижняя граница; максимум задан отдельно для каждого элемента"}
        return result
