from collections import deque


class DiGraph:
    def __init__(self):
        self._adj = {}
        self._edge_set = set()

    def add_edge(self, u, v):
        if u not in self._adj:
            self._adj[u] = set()
        if v not in self._adj:
            self._adj[v] = set()
        if (u, v) not in self._edge_set:
            self._edge_set.add((u, v))
            self._adj[u].add(v)

    def vertices(self):
        return list(self._adj.keys())

    def edges(self):
        return list(self._edge_set)

    def neighbors(self, v):
        return list(self._adj.get(v, set()))

    def has_vertex(self, v):
        return v in self._adj

    def vertex_count(self):
        return len(self._adj)

    def edge_count(self):
        return len(self._edge_set)

    def topo_sort(self):
        in_degree = {v: 0 for v in self._adj}
        for u, v in self._edge_set:
            in_degree[v] += 1

        queue = deque(v for v in self._adj if in_degree[v] == 0)
        order = []

        while queue:
            u = queue.popleft()
            order.append(u)
            for v in self._adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        if len(order) != self.vertex_count():
            remaining = [v for v in self._adj if in_degree[v] > 0]
            raise ValueError(f"graph contains a cycle involving vertices: {remaining}")
        return order

    def has_cycle(self):
        in_degree = {v: 0 for v in self._adj}
        for u, v in self._edge_set:
            in_degree[v] += 1

        queue = deque(v for v in self._adj if in_degree[v] == 0)
        visited = 0

        while queue:
            u = queue.popleft()
            visited += 1
            for v in self._adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        return visited != self.vertex_count()

    def reachable(self, u, v):
        if u not in self._adj:
            return False
        if u == v:
            return True
        seen = {u}
        queue = deque([u])
        while queue:
            current = queue.popleft()
            for nxt in self._adj[current]:
                if nxt == v:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return False
