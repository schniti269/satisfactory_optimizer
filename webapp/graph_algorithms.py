"""
graph_algorithms.py - Formal graph theory algorithms for factory analysis.

Contains:
- Tarjan's SCC algorithm (iterative, stack-safe)
- Condensation DAG + topological sort (Kahn's algorithm)
- Lengauer-Tarjan dominator tree construction

All algorithms are implemented iteratively to avoid Python's recursion limit
on graphs with 6,500+ nodes.
"""

from collections import defaultdict, deque

VIRTUAL_SOURCE = "__VIRTUAL_SOURCE__"


# ═══════════════════════════════════════════════════════════════════════════════
# Tarjan's Strongly Connected Components (Iterative)
# ═══════════════════════════════════════════════════════════════════════════════


def tarjan_scc(adj):
    """
    Iterative Tarjan's SCC algorithm.

    Args:
        adj: dict[node_id -> list[node_id]] — forward adjacency list

    Returns:
        List of frozenset[node_id], each a strongly connected component.
        Returned in reverse topological order (sinks first).
    """
    index_counter = 0
    stack = []
    on_stack = set()
    index = {}
    lowlink = {}
    result = []

    all_nodes = set(adj.keys())
    for targets in adj.values():
        all_nodes.update(targets)

    for start in all_nodes:
        if start in index:
            continue

        # Iterative DFS using explicit call stack
        # Each frame: (node, neighbor_iterator, is_root_call)
        call_stack = [(start, iter(adj.get(start, [])), True)]
        index[start] = lowlink[start] = index_counter
        index_counter += 1
        stack.append(start)
        on_stack.add(start)

        while call_stack:
            v, neighbors, _ = call_stack[-1]

            advanced = False
            for w in neighbors:
                if w not in index:
                    # Tree edge: recurse into w
                    index[w] = lowlink[w] = index_counter
                    index_counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    call_stack.append((w, iter(adj.get(w, [])), True))
                    advanced = True
                    break
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], index[w])

            if not advanced:
                # All neighbors processed — pop this frame
                call_stack.pop()

                # Update parent's lowlink
                if call_stack:
                    parent = call_stack[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[v])

                # Check if v is root of an SCC
                if lowlink[v] == index[v]:
                    scc = set()
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.add(w)
                        if w == v:
                            break
                    result.append(frozenset(scc))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Condensation DAG + Topological Sort
# ═══════════════════════════════════════════════════════════════════════════════


def condensation_topo_order(sccs, adj):
    """
    Build condensation DAG from SCCs and return topological order.

    Args:
        sccs: list of frozenset (from tarjan_scc)
        adj: dict[node_id -> list[node_id]] — original adjacency

    Returns:
        topo_order: list of SCC indices in topological order (sources first)
        scc_index: dict[node_id -> scc_idx] mapping each node to its SCC
    """
    # Map each node to its SCC index
    scc_index = {}
    for idx, scc in enumerate(sccs):
        for nid in scc:
            scc_index[nid] = idx

    # Build condensation DAG
    in_degree = [0] * len(sccs)
    scc_adj = defaultdict(set)

    for src, targets in adj.items():
        si = scc_index.get(src)
        if si is None:
            continue
        for dst in targets:
            sj = scc_index.get(dst)
            if sj is None or si == sj:
                continue
            if sj not in scc_adj[si]:
                scc_adj[si].add(sj)
                in_degree[sj] += 1

    # Kahn's algorithm for topological sort
    queue = deque()
    for idx in range(len(sccs)):
        if in_degree[idx] == 0:
            queue.append(idx)

    topo = []
    while queue:
        u = queue.popleft()
        topo.append(u)
        for v in scc_adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    return topo, scc_index


# ═══════════════════════════════════════════════════════════════════════════════
# Lengauer-Tarjan Dominator Tree (Iterative)
# ═══════════════════════════════════════════════════════════════════════════════


def lengauer_tarjan_dominators(adj, root):
    """
    Lengauer-Tarjan dominator tree algorithm (simple version).
    O(E * alpha(V)), almost linear.

    Uses iterative DFS and the "simple" semi-NCA variant which is
    sufficient and correct for graphs of this size (~15k edges).

    Args:
        adj: dict[node_id -> list[node_id]] — forward adjacency
        root: the start/source node

    Returns:
        idom: dict[node_id -> immediate_dominator_id]
    """
    # Step 1: Iterative DFS to compute DFS numbering
    order = []       # DFS visit order
    dfnum = {}       # node -> DFS number
    parent = {}      # DFS tree parent

    dfs_stack = [(root, iter(adj.get(root, [])))]
    dfnum[root] = 0
    order.append(root)

    while dfs_stack:
        v, children = dfs_stack[-1]
        advanced = False
        for w in children:
            if w not in dfnum:
                dfnum[w] = len(order)
                order.append(w)
                parent[w] = v
                dfs_stack.append((w, iter(adj.get(w, []))))
                advanced = True
                break
        if not advanced:
            dfs_stack.pop()

    n = len(order)
    if n <= 1:
        return {}

    # Build reverse adjacency (predecessors in original graph)
    pred = defaultdict(list)
    for u, succs in adj.items():
        if u not in dfnum:
            continue
        for v in succs:
            if v in dfnum:
                pred[v].append(u)

    # Step 2: Compute semi-dominators and immediate dominators
    # Using the "simple" Lengauer-Tarjan with path compression

    semi = {}       # node -> semi-dominator (by DFS number)
    idom = {}       # node -> immediate dominator
    ancestor = {}   # for LINK/EVAL (union-find with path compression)
    best = {}       # best semi-dominator along compressed path

    for v in order:
        semi[v] = dfnum[v]
        ancestor[v] = None
        best[v] = v

    def _eval(v):
        """Find the node with minimum semi-dominator on path to root of forest."""
        # Walk up to root of forest
        path = []
        u = v
        while ancestor[u] is not None:
            path.append(u)
            u = ancestor[u]
        # u is now the root of the tree

        # Walk path from root toward v, updating best + path compression
        for i in range(len(path) - 1, -1, -1):
            node = path[i]
            par_node = ancestor[node]
            if par_node is not None and ancestor[par_node] is not None:
                if semi[best[par_node]] < semi[best[node]]:
                    best[node] = best[par_node]
                ancestor[node] = u  # path compression

        return best[v]

    def _link(par, child):
        """Link child to parent in the forest."""
        ancestor[child] = par

    # Process vertices in reverse DFS order (skip root)
    bucket = defaultdict(list)

    for i in range(n - 1, 0, -1):
        w = order[i]
        p = parent[w]

        # Compute semi-dominator of w
        for v in pred[w]:
            if dfnum.get(v, n) <= dfnum[w]:
                # v is an ancestor (or equal) in DFS
                s_candidate = dfnum[v]
            else:
                u = _eval(v)
                s_candidate = semi[u]
            if s_candidate < semi[w]:
                semi[w] = s_candidate

        # Add w to bucket of its semi-dominator
        semi_node = order[semi[w]]
        bucket[semi_node].append(w)

        _link(p, w)

        # Process bucket for p
        for v in bucket.get(p, []):
            u = _eval(v)
            idom[v] = p if semi[u] == semi[v] else u
        bucket[p] = []

    # Step 3: Adjust idom for nodes where idom != semi-dominator
    for i in range(1, n):
        w = order[i]
        if w in idom and idom[w] != order[semi[w]]:
            idom[w] = idom.get(idom[w], root)

    return idom


def build_dominator_tree(nodes, edges, source_categories=("miner",)):
    """
    Build dominator tree with virtual source connected to all source nodes.

    Args:
        nodes: dict[node_id -> FlowNode]
        edges: dict[edge_id -> FlowEdge]
        source_categories: tuple of categories to treat as sources

    Returns:
        idom: dict[node_id -> immediate_dominator_id]
        Virtual source has id VIRTUAL_SOURCE.
    """
    # Build forward adjacency
    adj = defaultdict(list)
    for eid, edge in edges.items():
        if edge.src in nodes and edge.dst in nodes:
            adj[edge.src].append(edge.dst)

    # Connect virtual source to all miners/extractors
    adj[VIRTUAL_SOURCE] = [
        nid for nid, node in nodes.items()
        if node.category in source_categories
    ]

    # Also connect to nodes with no incoming edges (additional sources)
    has_incoming = set()
    for eid, edge in edges.items():
        if edge.dst in nodes:
            has_incoming.add(edge.dst)
    for nid in nodes:
        if nid not in has_incoming and nid not in adj[VIRTUAL_SOURCE]:
            adj[VIRTUAL_SOURCE].append(nid)

    idom = lengauer_tarjan_dominators(adj, VIRTUAL_SOURCE)
    return idom


def build_reverse_dominator_tree(nodes, edges, sink_categories=("storage",)):
    """
    Build dominator tree on the REVERSED graph for output backup analysis.
    The dominator in the reversed graph identifies the downstream chokepoint.

    Args:
        nodes: dict[node_id -> FlowNode]
        edges: dict[edge_id -> FlowEdge]
        sink_categories: tuple of categories to treat as sinks

    Returns:
        idom: dict[node_id -> immediate_dominator_id]
    """
    # Build REVERSE adjacency (swap src/dst)
    rev_adj = defaultdict(list)
    for eid, edge in edges.items():
        if edge.src in nodes and edge.dst in nodes:
            rev_adj[edge.dst].append(edge.src)

    # Virtual sink connected to all terminal nodes
    VIRTUAL_SINK = "__VIRTUAL_SINK__"
    has_outgoing = set()
    for eid, edge in edges.items():
        if edge.src in nodes:
            has_outgoing.add(edge.src)

    rev_adj[VIRTUAL_SINK] = []
    for nid, node in nodes.items():
        if nid not in has_outgoing or node.category in sink_categories:
            rev_adj[VIRTUAL_SINK].append(nid)

    idom = lengauer_tarjan_dominators(rev_adj, VIRTUAL_SINK)
    return idom
