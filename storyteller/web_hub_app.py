from __future__ import annotations

import contextlib
import os
import secrets
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response


WEB_HUB_SERVICE = "story-content-hub"
WEB_HUB_PROTOCOL_VERSION = 2


MANAGEMENT_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Story Teller Hub</title>
  <style>
    :root { color: #24352f; background: #f5faf7; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: radial-gradient(circle at 15% 0%, #e2f5ec 0, transparent 35%), #f7faf8; }
    main { width: min(1080px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 72px; }
    header { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 26px; }
    h1 { margin: 4px 0; font: 650 34px/1.1 Georgia, serif; color: #18392d; }
    header p, .empty { color: #687a73; }
    .eyebrow { color: #43826a; font-size: 12px; letter-spacing: .16em; text-transform: uppercase; }
    #refresh { border: 0; background: transparent; color: #39715b; cursor: pointer; padding: 10px; }
    .contents { display: grid; gap: 18px; }
    article { background: rgba(255,255,255,.9); border: 1px solid #dbe9e2; border-radius: 18px; box-shadow: 0 14px 38px rgba(45,83,67,.08); padding: 22px; }
    article > header { align-items: center; margin: 0 0 18px; }
    h2 { margin: 0 0 4px; font-size: 21px; }
    small { color: #809088; }
    .states, .actions, .projects { display: flex; flex-wrap: wrap; gap: 9px; align-items: center; }
    .state { border-radius: 999px; padding: 5px 10px; background: #eff5f2; color: #607169; font-size: 12px; }
    .state.on { background: #ddf4e8; color: #24704e; }
    button, a.open { border: 1px solid #c9ddd3; border-radius: 9px; background: #fff; color: #315e4d; padding: 8px 12px; cursor: pointer; text-decoration: none; font-size: 13px; }
    button:hover, a.open:hover { border-color: #72a88f; background: #f3faf6; }
    button.danger { color: #a64242; border-color: #edd0d0; }
    button:disabled, a.disabled { opacity: .45; pointer-events: none; }
    .actions { margin: 16px 0; }
    .projects { border-top: 1px solid #e8f0ec; padding-top: 14px; }
    .project { display: flex; align-items: center; gap: 7px; padding: 5px 0; }
    .project.off { opacity: .55; }
    .project.error { color: #9b3e3e; }
    .project small { max-width: 420px; color: #9b5a5a; }
    .diagnostics { margin-top: 14px; border-top: 1px solid #e8f0ec; padding-top: 12px; color: #64766e; font-size: 12px; }
    .diagnostics summary { cursor: pointer; color: #39715b; }
    .diagnostics dl { display: grid; grid-template-columns: max-content 1fr; gap: 5px 12px; }
    .diagnostics dt { font-weight: 650; }
    .diagnostics dd { margin: 0; overflow-wrap: anywhere; }
    dialog { width: min(860px, calc(100% - 32px)); border: 1px solid #d5e5dd; border-radius: 16px; padding: 0; box-shadow: 0 25px 80px #173d2d33; }
    dialog::backdrop { background: #18392d55; }
    dialog header { margin: 0; padding: 16px 20px; border-bottom: 1px solid #e3eee8; align-items: center; }
    dialog pre { margin: 0; padding: 18px 20px; max-height: 60vh; overflow: auto; background: #f8fbf9; white-space: pre-wrap; font: 12px/1.55 ui-monospace, monospace; }
    .dialog-actions { display: flex; justify-content: end; gap: 8px; padding: 14px 20px; }
    .notice { position: fixed; right: 24px; bottom: 24px; border-radius: 10px; padding: 11px 14px; background: #204d3c; color: white; box-shadow: 0 8px 24px #244a3b33; }
  </style>
</head>
<body>
<main>
  <header><div><span class="eyebrow">Local workspace manager</span><h1>Story Teller Hub</h1><p>统一管理多个 Content 及其 Projects</p></div><button id="refresh">刷新状态</button></header>
  <section id="contents" class="contents"><p class="empty">正在读取 Content…</p></section>
</main>
<dialog id="log-dialog"><header><div><strong>Content 运行日志</strong><small id="log-title"></small></div></header><pre id="log-content"></pre><div class="dialog-actions"><button onclick="document.querySelector('#log-dialog').close()">关闭</button></div></dialog>
<script>
const host = document.querySelector('#contents');
const busy = new Set();
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const notify = text => { const n=document.createElement('div'); n.className='notice'; n.textContent=text; document.body.append(n); setTimeout(()=>n.remove(),2600); };
const actionToken = '__ACTION_TOKEN__';
async function request(path, options={}) { const response=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Story-Teller-Hub-Action':actionToken,...(options.headers||{})}}); const body=await response.json(); if(!response.ok) throw new Error(body.detail||'操作失败'); return body; }
async function operation(id, callback) { if(busy.has(id)) return; busy.add(id); await load(); try { await callback(); notify('操作已完成'); } catch(e) { notify(e.message); } finally { busy.delete(id); await load(); } }
async function act(id, action, question='') { if(question && !window.confirm(question)) return; await operation(id,()=>request(`/api/v1/contents/${encodeURIComponent(id)}/actions/${action}`,{method:'POST'})); }
async function independent(id, enabled) { await operation(id,()=>request(`/api/v1/contents/${encodeURIComponent(id)}/mcp-independent`,{method:'PUT',body:JSON.stringify({enabled})})); }
async function projectState(id, project, enabled) { if(!enabled && !window.confirm(`停用 Project“${project}”？它的数据不会被删除。`)) return; await operation(id,()=>request(`/api/v1/contents/${encodeURIComponent(id)}/projects/${encodeURIComponent(project)}`,{method:'PUT',body:JSON.stringify({enabled})})); }
async function createProject(id) { const project=window.prompt('Project ID（字母、数字、下划线或短横线）'); if(!project) return; const title=window.prompt('Project 显示标题',project); if(title===null) return; await operation(id,()=>request(`/api/v1/contents/${encodeURIComponent(id)}/projects`,{method:'POST',body:JSON.stringify({project,title})})); }
async function removeContent(id,encodedName) { const name=decodeURIComponent(encodedName); if(!window.confirm(`从 Hub 移除“${name}”？小说文件不会被删除，之后仍可通过 run.sh 重新注册。`)) return; await operation(id,()=>request(`/api/v1/contents/${encodeURIComponent(id)}`,{method:'DELETE'})); }
async function showLogs(id,encodedName) { try { const data=await request(`/api/v1/contents/${encodeURIComponent(id)}/logs`); document.querySelector('#log-title').textContent=decodeURIComponent(encodedName); document.querySelector('#log-content').textContent=data.log||'还没有 Web Worker 日志'; document.querySelector('#log-dialog').showModal(); } catch(e) { notify(e.message); } }
async function load() {
  try {
    const data=await request('/api/v1/contents');
    if(!data.workspaces.length){host.innerHTML='<p class="empty">尚未注册 Content。请在小说仓库运行 ./run.sh 或 ./run-rag.sh。</p>';return;}
    host.innerHTML=data.workspaces.map(w=>{
      const enabled=new Set(w.projects); const configured=new Set(w.allProjects.filter(p=>!(w.disabledProjects||[]).includes(p))); const web=w.web.running; const mcp=w.mcp.running; const waiting=busy.has(w.workspaceId); const statuses=new Map((w.projectStatuses||[]).map(s=>[s.project,s]));
      const projects=w.allProjects.map(p=>{ const status=statuses.get(p)||{state:configured.has(p)?'unchecked':'disabled',error:''}; const ready=enabled.has(p); const stateLabel=status.state==='ready'?'可用':status.state==='error'?'检查失败':status.state==='disabled'?'已停用':'待检查'; return `<div class="project ${status.state==='error'?'error':ready?'':'off'}"><strong>${esc(p)}</strong><span class="state ${ready?'on':''}">${stateLabel}</span>${status.error?`<small title="${esc(status.error)}">${esc(status.error)}</small>`:''}<a class="open ${web&&ready?'':'disabled'}" href="/w/${encodeURIComponent(w.workspaceId)}/?project=${encodeURIComponent(p)}">打开</a><button ${waiting?'disabled':''} onclick="projectState('${esc(w.workspaceId)}','${esc(p)}',${!configured.has(p)})">${configured.has(p)?'停用':'启用'}</button>${configured.has(p)?`<button ${waiting?'disabled':''} onclick="act('${esc(w.workspaceId)}','reload-project:${encodeURIComponent(p)}')">检查并加载</button>`:''}</div>`}).join('');
      const mode=w.web.mode==='managed'?'Hub 托管':w.web.mode==='attached'?`终端连接 ${w.web.leaseCount}`:'未托管'; const lastError=w.web.lastError||w.mcp.status?.lastError||'';
      return `<article><header><div><h2>${esc(w.displayName)}</h2><small>${esc(w.contentRoot||w.repositoryRoot)}</small></div><div class="states"><span class="state ${web?'on':''}">Web ${web?'运行中':'已停止'}</span><span class="state ${mcp?'on':''}">MCP ${mcp?'运行中':'已停止'}</span><span class="state">${w.mcp.mode==='independent'?'独立运行':'跟随 Web'}</span><span class="state">${mode}</span></div></header><div class="actions"><button ${web||waiting?'disabled':''} onclick="act('${esc(w.workspaceId)}','start-content')">启动 Content</button><button ${!web||waiting?'disabled':''} onclick="act('${esc(w.workspaceId)}','restart-content')">重启 Content</button><button ${!web||waiting?'disabled':''} onclick="act('${esc(w.workspaceId)}','stop-content','停止 Content？跟随 Web 的 MCP 也会停止。')">停止 Content</button><button ${!mcp||waiting?'disabled':''} onclick="act('${esc(w.workspaceId)}','restart-mcp')">重启 MCP</button><button ${waiting?'disabled':''} onclick="independent('${esc(w.workspaceId)}',${w.mcp.mode!=='independent'})">${w.mcp.mode==='independent'?'改为跟随 Web':'开启 MCP 独立运行'}</button><button ${waiting?'disabled':''} onclick="act('${esc(w.workspaceId)}','scan-projects')">扫描 Project</button><button ${waiting?'disabled':''} onclick="createProject('${esc(w.workspaceId)}')">新建 Project</button><button class="danger" ${!web||waiting?'disabled':''} onclick="act('${esc(w.workspaceId)}','force-stop-content','强制终止 Content？未完成的请求会立即中断。')">强制终止</button><button class="danger" ${waiting?'disabled':''} onclick="removeContent('${esc(w.workspaceId)}','${encodeURIComponent(w.displayName)}')">从 Hub 移除</button>${waiting?'<span class="state on">操作中…</span>':''}</div><div class="projects">${projects}</div><details class="diagnostics"><summary>运行诊断</summary><dl><dt>Workspace</dt><dd>${esc(w.workspaceId)}</dd><dt>Web PID</dt><dd>${w.web.processId||'—'}</dd><dt>Web 启动时间</dt><dd>${w.web.startedAt?new Date(w.web.startedAt*1000).toLocaleString():'—'}</dd><dt>最近心跳</dt><dd>${w.web.lastHeartbeatAt?new Date(w.web.lastHeartbeatAt*1000).toLocaleString():'—'}</dd><dt>MCP Projects</dt><dd>${esc((w.mcp.status?.projects||[]).join(', ')||'—')}</dd><dt>最近错误</dt><dd>${esc(lastError||'无')}</dd></dl><button onclick="showLogs('${esc(w.workspaceId)}','${encodeURIComponent(w.displayName)}')">查看 Web 日志</button></details></article>`;
    }).join('');
  } catch(e) { host.innerHTML=`<p class="empty">${esc(e.message)}</p>`; }
}
document.querySelector('#refresh').addEventListener('click',load); load(); setInterval(load,5000);
</script>
</body></html>"""


def create_web_hub_app(hub_url: str, token: str) -> FastAPI:
    hub_url = hub_url.rstrip("/")
    action_token = secrets.token_urlsafe(32)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.http = httpx.AsyncClient(timeout=30, trust_env=False)
        try:
            yield
        finally:
            await app.state.http.aclose()

    app = FastAPI(title="Story Teller Hub", version="1.0.0", lifespan=lifespan)

    def require_action_token(request: Request) -> None:
        supplied = request.headers.get("X-Story-Teller-Hub-Action", "")
        if not secrets.compare_digest(supplied, action_token):
            raise HTTPException(status_code=403, detail="Hub 管理授权无效，请刷新管理页")

    async def hub_request(method: str, path: str, *, payload: Any = None, protected: bool = False) -> httpx.Response:
        headers = {"X-Story-World-Hub-Token": token} if protected else {}
        try:
            return await app.state.http.request(method, hub_url + path, headers=headers, json=payload)
        except httpx.HTTPError as error:
            raise HTTPException(status_code=503, detail=f"Story World Hub 暂时不可用：{error}") from error

    @app.get("/api/v1/health")
    async def health():
        upstream = await hub_request("GET", "/api/v1/hub/health")
        return {
            "ok": upstream.status_code == 200,
            "service": WEB_HUB_SERVICE,
            "protocolVersion": WEB_HUB_PROTOCOL_VERSION,
            "processId": os.getpid(),
            "hub": hub_url,
        }

    @app.get("/api/v1/contents")
    async def contents():
        response = await hub_request("GET", "/api/v1/hub/workspaces")
        return JSONResponse(response.json(), status_code=response.status_code)

    @app.post("/api/v1/contents/{workspace_id}/actions/{action}")
    async def content_action(workspace_id: str, action: str, request: Request):
        require_action_token(request)
        if action.startswith("reload-project:"):
            project = action.split(":", 1)[1]
            path = f"/api/v1/hub/workspaces/{quote(workspace_id)}/projects/{quote(project)}/reload"
        else:
            path = f"/api/v1/hub/workspaces/{quote(workspace_id)}/actions/{quote(action)}"
        response = await hub_request("POST", path, protected=True)
        return JSONResponse(response.json(), status_code=response.status_code)

    @app.put("/api/v1/contents/{workspace_id}/mcp-independent")
    async def independent_mcp(workspace_id: str, request: Request):
        require_action_token(request)
        response = await hub_request(
            "PUT", f"/api/v1/hub/workspaces/{quote(workspace_id)}/mcp-independent",
            payload=await request.json(), protected=True,
        )
        return JSONResponse(response.json(), status_code=response.status_code)

    @app.put("/api/v1/contents/{workspace_id}/projects/{project}")
    async def project_state(workspace_id: str, project: str, request: Request):
        require_action_token(request)
        response = await hub_request(
            "PUT", f"/api/v1/hub/workspaces/{quote(workspace_id)}/projects/{quote(project)}",
            payload=await request.json(), protected=True,
        )
        return JSONResponse(response.json(), status_code=response.status_code)

    @app.post("/api/v1/contents/{workspace_id}/projects")
    async def create_project(workspace_id: str, request: Request):
        require_action_token(request)
        response = await hub_request(
            "POST", f"/api/v1/hub/workspaces/{quote(workspace_id)}/projects",
            payload=await request.json(), protected=True,
        )
        return JSONResponse(response.json(), status_code=response.status_code)

    @app.delete("/api/v1/contents/{workspace_id}")
    async def remove_content(workspace_id: str, request: Request):
        require_action_token(request)
        response = await hub_request(
            "DELETE", f"/api/v1/hub/workspaces/{quote(workspace_id)}", protected=True,
        )
        return JSONResponse(response.json(), status_code=response.status_code)

    @app.get("/api/v1/contents/{workspace_id}/logs")
    async def content_logs(workspace_id: str, request: Request):
        require_action_token(request)
        response = await hub_request(
            "GET", f"/api/v1/hub/workspaces/{quote(workspace_id)}/logs", protected=True,
        )
        return JSONResponse(response.json(), status_code=response.status_code)

    async def target(workspace_id: str) -> dict[str, Any]:
        response = await hub_request(
            "GET", f"/api/v1/hub/workspaces/{quote(workspace_id)}/web-target", protected=True,
        )
        if response.status_code != 200:
            try:
                detail = response.json().get("detail", "Content Web 当前不可用")
            except ValueError:
                detail = "Content Web 当前不可用"
            raise HTTPException(status_code=response.status_code, detail=detail)
        return response.json()

    @app.api_route("/w/{workspace_id}", methods=["GET"], include_in_schema=False)
    async def workspace_redirect(workspace_id: str):
        return RedirectResponse(f"/w/{quote(workspace_id)}/", status_code=307)

    @app.api_route(
        "/w/{workspace_id}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def proxy_workspace(workspace_id: str, path: str, request: Request):
        try:
            info = await target(workspace_id)
        except HTTPException as error:
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": str(error.detail),
                    "detail": str(error.detail),
                    "code": "api_unavailable",
                },
                headers={"Cache-Control": "no-store", "Retry-After": "1"},
            )
        project = ""
        marker = "api/v1/projects/"
        if marker in path:
            project = path.split(marker, 1)[1].split("/", 1)[0]
        elif path == "api/v1/meta":
            project = request.query_params.get("project", "")
        if project and project not in info.get("projects", []):
            raise HTTPException(status_code=404, detail=f"Project 未启用：{project}")
        query = request.url.query
        upstream_url = info["target"] + "/" + path
        if query:
            upstream_url += "?" + query
        headers = {
            key: value for key, value in request.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        try:
            response = await app.state.http.request(
                request.method, upstream_url, headers=headers, content=await request.body(),
            )
        except httpx.HTTPError as error:
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": f"Content Worker 请求失败：{error}",
                    "detail": f"Content Worker 请求失败：{error}",
                    "code": "api_unavailable",
                },
                headers={"Cache-Control": "no-store", "Retry-After": "1"},
            )
        forwarded_headers = {
            key: value for key, value in response.headers.items()
            if key.lower() in {"content-type", "cache-control", "etag", "last-modified"}
        }
        return Response(response.content, status_code=response.status_code, headers=forwarded_headers)

    @app.get("/", response_class=HTMLResponse)
    async def management():
        return HTMLResponse(MANAGEMENT_HTML.replace("__ACTION_TOKEN__", action_token))

    return app
