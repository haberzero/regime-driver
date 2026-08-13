import pytest

from digraph import DiGraph


def test_empty_graph():
    g = DiGraph()
    assert g.vertex_count() == 0
    assert g.edge_count() == 0
    assert g.vertices() == []
    assert g.edges() == []
    assert g.topo_sort() == []
    assert not g.has_cycle()
    assert not g.reachable(1, 2)


def test_single_vertex():
    g = DiGraph()
    g.add_edge(1, 1)
    assert g.vertex_count() == 1
    assert g.edge_count() == 1
    assert g.has_vertex(1)
    assert g.vertices() == [1]
    assert g.edges() == [(1, 1)]
    assert g.has_cycle()
    with pytest.raises(ValueError):
        g.topo_sort()


def test_self_loop_cycle():
    g = DiGraph()
    g.add_edge("a", "a")
    assert g.has_cycle()
    with pytest.raises(ValueError, match="cycle"):
        g.topo_sort()


def test_duplicate_edges_deduped():
    g = DiGraph()
    g.add_edge(1, 2)
    g.add_edge(1, 2)
    g.add_edge(1, 2)
    assert g.edge_count() == 1
    assert g.edges() == [(1, 2)]
    assert not g.has_cycle()
    assert g.topo_sort() == [1, 2]


def test_simple_dag():
    g = DiGraph()
    g.add_edge(1, 2)
    g.add_edge(2, 3)
    assert g.topo_sort() == [1, 2, 3]
    assert not g.has_cycle()


def test_disconnected_graph():
    g = DiGraph()
    g.add_edge(1, 2)
    g.add_edge(3, 4)
    order = g.topo_sort()
    assert sorted(order) == [1, 2, 3, 4]
    assert not g.has_cycle()
    assert not g.reachable(1, 3)


def test_multiple_zero_indegree_vertices():
    g = DiGraph()
    g.add_edge(2, 3)
    g.add_edge(1, 3)
    order = g.topo_sort()
    assert set(order) == {1, 2, 3}
    assert order.index(1) < order.index(3)
    assert order.index(2) < order.index(3)


def test_topo_sort_valid_edges():
    g = DiGraph()
    edges = [(1, 2), (1, 3), (2, 4), (3, 4), (4, 5)]
    for u, v in edges:
        g.add_edge(u, v)
    order = g.topo_sort()
    assert set(order) == set(range(1, 6))
    pos = {v: i for i, v in enumerate(order)}
    for u, v in edges:
        assert pos[u] < pos[v], f"edge ({u}, {v}) violated topo order"


def test_cycle_detection():
    g = DiGraph()
    g.add_edge(1, 2)
    g.add_edge(2, 3)
    g.add_edge(3, 1)
    assert g.has_cycle()
    with pytest.raises(ValueError) as excinfo:
        g.topo_sort()
    assert "cycle" in str(excinfo.value)


def test_cycle_in_part_of_graph():
    g = DiGraph()
    g.add_edge(1, 2)
    g.add_edge(2, 1)
    g.add_edge(1, 3)
    assert g.has_cycle()
    with pytest.raises(ValueError):
        g.topo_sort()


def test_reachable():
    g = DiGraph()
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    assert g.reachable("a", "c")
    assert g.reachable("a", "a")
    assert not g.reachable("c", "a")
    assert not g.reachable("x", "a")
    assert not g.reachable("a", "x")


def test_reachable_with_cycle():
    g = DiGraph()
    g.add_edge(1, 2)
    g.add_edge(2, 1)
    g.add_edge(2, 3)
    assert g.reachable(1, 3)
    assert g.reachable(3, 1) is False


def test_neighbors():
    g = DiGraph()
    g.add_edge("a", "b")
    g.add_edge("a", "c")
    assert sorted(g.neighbors("a")) == ["b", "c"]
    assert g.neighbors("zzz") == []
