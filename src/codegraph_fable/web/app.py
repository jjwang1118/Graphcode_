"""HTTP API。規格：docs/spec/web.md"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..query import EDGE_TYPES, Index, cycles, detail, impact, locate, overview, view
from ..service import Service

ALLOWED_ENV = "CODEGRAPH_ALLOWED_ROOTS"
DIST_ENV = "CODEGRAPH_FRONTEND_DIST"
_DEFAULT_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class ProjectRequest(BaseModel):
    project: str


class AnalyzeRequest(ProjectRequest):
    python: str | None = None
    force: bool = False


class ViewRequest(ProjectRequest):
    expanded: list[str] = []
    edge_types: list[str] = list(EDGE_TYPES)
    externals: str = "grouped"
    level: int | None = 1  # 0＝只有專案根、n＝到第 n 層目錄、null＝不收合
    collapsed: list[str] = []


class ImpactRequest(ViewRequest):
    target: str
    depth: int | None = None


class TargetRequest(ProjectRequest):
    target: str


class FindRequest(ProjectRequest):
    name: str


def create_app(service: Service | None = None, allowed_roots: list[str] | None = None) -> FastAPI:
    service = service or Service()
    if allowed_roots is None:
        allowed_roots = [p for p in os.environ.get(ALLOWED_ENV, "").split(os.pathsep) if p]
    roots = [Path(p).expanduser().resolve() for p in allowed_roots]
    app = FastAPI(title="codegraph")

    def index_of(project: str, python: str | None = None, force: bool = False) -> tuple[Index, str]:
        path = Path(project).expanduser().resolve()
        # 硬性規定：只分析允許清單內的資料夾。沒設定清單＝全部拒絕
        if not any(path == root or root in path.parents for root in roots):
            hint = "尚未設定允許清單" if not roots else "不在允許清單內"
            raise HTTPException(403, f"路徑不被允許（{hint}）。請設定環境變數 {ALLOWED_ENV}。")
        try:
            return service.index(str(path), python, force)
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error

    def node_of(index: Index, target: str) -> str:
        if target not in index.nodes:
            raise HTTPException(404, f"找不到節點：{target}")
        return target

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {"allowed_roots": [str(r) for r in roots]}

    @app.post("/api/analyze")
    def analyze_endpoint(request: AnalyzeRequest) -> dict[str, Any]:
        index, source = index_of(request.project, request.python, request.force)
        meta = index.graph.meta
        keys = ("root", "search_roots", "python", "counts", "imports", "uses",
                "missing_dependencies", "parse_errors")  # fmt: skip
        return {
            "source": source,
            "unresolved_imports": len(meta.get("unresolved_imports", [])),
            "cycles": cycles(index)["count"],
            **{k: meta.get(k) for k in keys},
        }

    @app.post("/api/overview")
    def overview_endpoint(request: ProjectRequest) -> dict[str, Any]:
        return overview(index_of(request.project)[0])

    @app.post("/api/cycles")
    def cycles_endpoint(request: ProjectRequest) -> dict[str, Any]:
        index = index_of(request.project)[0]
        return {"module": cycles(index), "with_deferred": cycles(index, True)}

    @app.post("/api/view")
    def view_endpoint(request: ViewRequest) -> dict[str, Any]:
        index = index_of(request.project)[0]
        return view(
            index,
            request.expanded,
            request.edge_types,
            request.externals,
            request.level,
            request.collapsed,
        )

    @app.post("/api/find")
    def find_endpoint(request: FindRequest) -> list[dict[str, Any]]:
        index = index_of(request.project)[0]
        return [
            {
                "id": node.id,
                "type": node.type,
                "label": node.label,
                "line": node.properties.get("line"),
                "signature": node.properties.get("signature"),
                "ancestors": index.ancestors(node.id),  # 要讓它出現在畫面上，需要展開這些
            }
            for node in index.find(request.name)[:50]
        ]

    @app.post("/api/detail")
    def detail_endpoint(request: TargetRequest) -> dict[str, Any]:
        index = index_of(request.project)[0]
        return detail(index, node_of(index, request.target))

    @app.post("/api/impact")
    def impact_endpoint(request: ImpactRequest) -> dict[str, Any]:
        index = index_of(request.project)[0]
        result = impact(index, node_of(index, request.target), request.depth)
        ids = [*result["scope"], *(e["id"] for level in result["levels"] for e in level)]
        ids += [c["id"] for c in result["candidates"]]
        # 受影響的節點可能收在某個方塊裡：告訴前端該把哪個看得見的節點標起來
        result["visible"] = locate(
            index, request.expanded, ids, request.externals, request.level, request.collapsed
        )
        return result

    dist = Path(os.environ.get(DIST_ENV, _DEFAULT_DIST))
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
