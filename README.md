# Kirktron
Programs to build crypto bot and system to help performance

## Graphify

[Graphify](https://github.com/Graphify-Labs/graphify) turns the codebase into a queryable
knowledge graph, so a coding assistant looks up nodes and edges instead of re-reading files.
That cuts token usage on large codebases.

Install it on the machine you actually run your assistant from (not in a throwaway container):

```sh
uv tool install graphifyy   # or: pipx install graphifyy
graphify install            # registers the /graphify skill with detected assistants
```

Then, from the repo root:

```sh
/graphify .
```

This parses the code locally with tree-sitter (deterministic, no LLM, nothing leaves the
machine) and writes `graphify-out/`:

| File | Purpose |
| --- | --- |
| `graph.json` | the full graph — query it without re-reading files |
| `graph.html` | interactive browser view (skip above ~5000 nodes) |
| `GRAPH_REPORT.md` | highlights and notable connections |

`graphify-out/` is gitignored — regenerate it locally, and re-run `/graphify .` after
significant changes so the graph does not drift from the code.

To expose the graph over MCP instead of the skill:

```sh
python -m graphify.serve graphify-out/graph.json
```

**Worth knowing:** Graphify pays off once the repo is large enough that answering one
question takes several Glob/Grep calls. While Kirktron is small enough to fit in context,
the graph adds overhead rather than removing it — so set it up now, but expect the savings
only as the codebase grows.

The PyPI package is `graphifyy` (two y's), published from `Graphify-Labs/graphify`.
Several similarly named sites and mirrors exist; prefer that source.
