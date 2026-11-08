"""Bounded reduced ordered decision diagram over physical element groups."""
from decimal import Decimal


class StructureLimit(ValueError):
    pass


class DecisionDiagram:
    def __init__(self, tree, ids, max_nodes=12000, max_operations=60000):
        self.order = {name: i for i, name in enumerate(ids)}
        self.nodes = [None, None]  # false, true
        self.unique = {}
        self.applied = {}
        self.max_nodes, self.max_operations = max_nodes, max_operations

        def compile(node):
            if isinstance(node, str):
                return self.make(self.order[node], 0, 1)
            return self.apply(node[0], compile(node[1]), compile(node[2]))
        self.root = compile(tree)

    def make(self, variable, low, high):
        if low == high:
            return low
        key = variable, low, high
        if key not in self.unique:
            if len(self.nodes) >= self.max_nodes:
                raise StructureLimit('Схема слишком сложна для расчёта. Сократите число логических связей или разделите анализ на подсистемы')
            self.unique[key] = len(self.nodes)
            self.nodes.append(key)
        return self.unique[key]

    def apply(self, operation, left, right):
        if left > right:
            left, right = right, left
        if left == right:
            return left
        if operation == 'and':
            if left == 0: return 0
            if left == 1: return right
        else:
            if left == 0: return right
            if left == 1: return 1
        key = operation, left, right
        if key in self.applied:
            return self.applied[key]
        if len(self.applied) >= self.max_operations:
            raise StructureLimit('Достигнут предел сложности логической схемы. Упростите выражение или разделите систему на подсистемы')
        a, b = self.nodes[left], self.nodes[right]
        variable = min(a[0], b[0])
        al, ah = a[1:] if a[0] == variable else (left, left)
        bl, bh = b[1:] if b[0] == variable else (right, right)
        result = self.make(variable, self.apply(operation, al, bl), self.apply(operation, ah, bh))
        self.applied[key] = result
        return result

    def probabilities(self, failures):
        # Propagate both tails directly, preserving tiny Q without subtracting from 1.
        cache = {0: (Decimal(0), Decimal(1)), 1: (Decimal(1), Decimal(0))}
        def evaluate(node):
            if node not in cache:
                variable, low, high = self.nodes[node]
                pl, ql = evaluate(low); ph, qh = evaluate(high)
                q = failures[variable]; p = Decimal(1) - q
                cache[node] = (q * pl + p * ph, q * ql + p * qh)
            return cache[node]
        return evaluate(self.root)
