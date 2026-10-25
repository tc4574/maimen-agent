"""Run locally: python -m uvicorn maimen.api:app --host 127.0.0.1."""
from contextlib import asynccontextmanager
import asyncio
import os
import json
import uuid
from pathlib import Path
from pydantic import ValidationError

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .contracts import Command, CommandResult, CreateSession, Snapshot, Versions
from .harness import Rejected
from .service import Service
from .store import ConflictError, Store, encode
from .recommendation_contracts import RecommendationRequest, RecommendationFeedback
from .assistant import AssistantRequest, converse
from .deepseek import ModelError
from .live_queries import live_query
from .settings import model_config


def create_app(database="data/web.sqlite3", *, live_enabled=None, recommendation_runner=None, query_runner=None, model=None):
    @asynccontextmanager
    async def lifespan(app):
        store = Store(database)
        app.state.service = Service(store)
        app.state.recommendation_lock = asyncio.Lock()
        app.state.assistant_jobs = {}
        app.state.cancelled_requests = set()
        try:
            yield
        finally:
            jobs = [entry[1] for entry in app.state.assistant_jobs.values()]
            for task in jobs:
                task.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            store.close()

    app = FastAPI(title="McBot · 本机问答与真实推荐", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    enabled = live_enabled if live_enabled is not None else os.environ.get("MAIMEN_ENABLE_LIVE_RECOMMENDATIONS") == "1"

    @app.middleware("http")
    async def origin_guard(request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": {"code": "origin_not_allowed"}}, status_code=403)
        return await call_next(request)

    @app.exception_handler(Rejected)
    @app.exception_handler(ConflictError)
    async def rejected(request, error):
        return JSONResponse({"error": {"code": str(error)}}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({"error": {"code": "invalid_request"}}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"error": {"code": error.detail}}, status_code=error.status_code)

    async def authorized(session_id: str, request: Request, authorization: str = Header(default="")):
        service = request.app.state.service
        if not authorization.startswith("Bearer ") or not service.authorize(session_id, authorization[7:]):
            raise HTTPException(401, "invalid_session_credentials")
        return service

    @app.post("/api/sessions", status_code=201)
    async def create(body: CreateSession, request: Request):
        return request.app.state.service.create()

    @app.get("/api/sessions/{session_id}", response_model=Snapshot)
    async def snapshot(session_id: str, service=Depends(authorized)):
        return service.snapshot(session_id)

    @app.post("/api/sessions/{session_id}/turns")
    async def begin(session_id: str, body: Versions, service=Depends(authorized)):
        return service.begin(session_id, body)

    @app.post("/api/sessions/{session_id}/commands", response_model=CommandResult)
    async def command(session_id: str, body: Command, service=Depends(authorized)):
        return await service.command(session_id, body)

    @app.post("/api/sessions/{session_id}/quotes")
    async def quote(session_id: str, body: Versions, service=Depends(authorized)):
        return await service.quote(session_id, body)

    @app.post("/api/sessions/{session_id}/interrupt", response_model=Snapshot)
    async def interrupt(session_id: str, service=Depends(authorized)):
        service.harness.interrupt(session_id)
        return service.snapshot(session_id)

    @app.get("/api/sessions/{session_id}/events")
    async def events(session_id: str, after: int = -1, service=Depends(authorized)):
        return [{"event_id": f"{session_id}:{event['revision']}", "sequence": event["revision"],
                 "session_id": session_id, "source": "demo", **event}
                for event in service.store.events(session_id) if event["revision"] > after]

    async def execute_recommendation(session_id, body, request, service):
        # Website browses offers only; never reads or applies the operator's personal coupons.
        body = body.model_copy(update={'use_coupons': False})
        # Session token grants local API access only. Live results never mutate demo state.
        if not enabled:
            raise HTTPException(503, "live_recommendations_disabled")
        lock = request.app.state.recommendation_lock
        if lock.locked():
            raise HTTPException(409, "recommendation_in_progress")
        async with lock:
            try:
                if recommendation_runner is None:
                    from .recommend import run_live
                    result = await run_live(body)
                else:
                    result = await recommendation_runner(body)
            except TimeoutError:
                raise HTTPException(504, "recommendation_timeout") from None
            except Exception:
                raise HTTPException(502, "recommendation_provider_failed") from None
            run_id = uuid.uuid4().hex
            result["run_id"] = run_id
            with service.store.transaction():
                service.store.connection.execute("INSERT INTO recommendation_runs(run_id, session_id, request_json, result_json) VALUES (?, ?, ?, ?)",
                    (run_id, session_id, encode(body.model_dump()), encode(result)))
            return result

    @app.post("/api/sessions/{session_id}/recommendations")
    async def recommendations(session_id: str, body: RecommendationRequest, request: Request, service=Depends(authorized)):
        return await execute_recommendation(session_id, body, request, service)

    @app.post("/api/sessions/{session_id}/recommendations/feedback")
    async def feedback(session_id: str, body: RecommendationFeedback, request: Request, service=Depends(authorized)):
        row = service.store.connection.execute("SELECT request_json, result_json FROM recommendation_runs WHERE run_id=? AND session_id=?",
                                               (body.run_id, session_id)).fetchone()
        if row is None:
            raise HTTPException(404, "unknown_recommendation_run")
        previous, outcome = json.loads(row[0]), json.loads(row[1])
        known = {card["id"] for card in outcome.get("cards", [])}
        if not set(body.reject_card_ids) <= known:
            raise HTTPException(422, "unknown_feedback_card")
        updated = {**previous, **body.changes}
        updated["avoid_card_ids"] = list(dict.fromkeys(previous["avoid_card_ids"] + body.reject_card_ids))
        if "seed" not in body.changes:
            updated["seed"] = (previous["seed"] + 1) % 2147483648
        try:
            parsed = RecommendationRequest.model_validate(updated)
        except ValidationError:
            raise HTTPException(422, "invalid_feedback_constraints") from None
        return await execute_recommendation(session_id, parsed, request, service)

    @app.post('/api/sessions/{session_id}/assistant')
    async def assistant(session_id: str, body: AssistantRequest, request: Request, service=Depends(authorized)):
        connection = service.store.connection
        receipt = connection.execute('SELECT request_json,response_json FROM assistant_receipts WHERE session_id=? AND request_id=?',
                                     (session_id, body.request_id)).fetchone()
        if receipt:
            if receipt[0] != encode(body.model_dump()):
                raise HTTPException(409, 'request_id_reused')
            return json.loads(receipt[1])
        jobs = request.app.state.assistant_jobs
        if session_id in jobs:
            raise HTTPException(409, 'assistant_in_progress')
        if (session_id, body.request_id) in request.app.state.cancelled_requests:
            raise HTTPException(409, 'assistant_cancelled')
        context = {'preferences':body.preferences.model_dump(), 'cards':[]}
        if body.run_id:
            row = connection.execute('SELECT result_json FROM recommendation_runs WHERE session_id=? AND run_id=?',
                                     (session_id, body.run_id)).fetchone()
            if row is None:
                raise HTTPException(404, 'unknown_recommendation_run')
            prior = json.loads(row[0])
            context['cards'] = [{k:c.get(k) for k in ('id','offer_name','components','amount_cents','valid_until')}
                                for c in prior.get('cards', [])]
        if body.selected_id and body.selected_id not in {c['id'] for c in context['cards']}:
            raise HTTPException(422, 'unknown_selected_card')
        context['selected_id'] = body.selected_id
        history = [{'role':row[0], 'content':row[1]} for row in reversed(connection.execute(
            'SELECT role,content FROM assistant_messages WHERE session_id=? ORDER BY id DESC LIMIT 12', (session_id,)).fetchall())]

        async def query(q):
            if not enabled:
                raise HTTPException(503, 'live_recommendations_disabled')
            return await (query_runner or live_query)(q)

        async def recommend(req):
            if body.reroll:
                req = req.model_copy(update={'avoid_card_ids':list(dict.fromkeys(req.avoid_card_ids + [c['id'] for c in context['cards']]))[-30:]})
            return await execute_recommendation(session_id, req, request, service)

        async def work():
            if body.mode == 'query':
                if body.query is None:
                    raise HTTPException(422, 'query_required')
                facts = await query(body.query)
                count = len(facts['items'])
                result = {'reply':f'本次查询返回 {count} 条结果。请查看下方信息。' if count else '本次没有查到符合条件的结果。',
                          'facts':[facts], 'recommendation':None, 'action':None}
            elif body.mode == 'recommend':
                recommendation = await recommend(body.preferences)
                count = len(recommendation.get('cards', []))
                reply = f'找到 {count} 套符合条件的搭配。' if count else '本次未找到符合条件的搭配。'
                notes = recommendation.get('clarifications', []) + recommendation.get('warnings', [])
                result = {'reply':'\n'.join([reply, *notes]), 'facts':[], 'recommendation':recommendation, 'action':None}
            else:
                if not body.text.strip():
                    raise HTTPException(422, 'text_required')
                result = await converse(body, history, context, query, recommend, model)
            # No await between acceptance and commit; cancelled work cannot write a late receipt.
            if (session_id, body.request_id) in request.app.state.cancelled_requests:
                raise HTTPException(409, 'assistant_cancelled')
            with service.store.transaction():
                for role, content in [('user', body.text or body.mode), ('assistant', result['reply'])]:
                    connection.execute('INSERT INTO assistant_messages(session_id,role,content) VALUES (?,?,?)',
                                       (session_id, role, content))
                if result['facts']:
                    connection.execute('INSERT INTO assistant_messages(session_id,role,content) VALUES (?,?,?)',
                        (session_id, 'assistant', '历史查询记录（不代表当前有效，追问时重新核验）：' + encode(result['facts'])[:18000]))
                connection.execute('INSERT INTO assistant_receipts VALUES (?,?,?,?)',
                                   (session_id, body.request_id, encode(body.model_dump()), encode(result)))
                connection.execute('DELETE FROM assistant_messages WHERE session_id=? AND id NOT IN (SELECT id FROM assistant_messages WHERE session_id=? ORDER BY id DESC LIMIT 40)', (session_id, session_id))
            return result

        task = asyncio.create_task(work())
        jobs[session_id] = (body.request_id, task)
        try:
            return await asyncio.wait_for(task, 240)
        except asyncio.CancelledError:
            raise HTTPException(409, 'assistant_cancelled') from None
        except ModelError as error:
            raise HTTPException(503, str(error)) from None
        except TimeoutError:
            raise HTTPException(504, 'assistant_timeout') from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, 'assistant_query_failed') from None
        finally:
            if jobs.get(session_id, (None,))[0] == body.request_id:
                jobs.pop(session_id, None)

    @app.post('/api/sessions/{session_id}/assistant/cancel')
    async def cancel_assistant(session_id: str, body: AssistantRequest, request: Request, service=Depends(authorized)):
        cancelled = request.app.state.cancelled_requests
        if len(cancelled) >= 1000:
            cancelled.clear()
        cancelled.add((session_id, body.request_id))
        entry = request.app.state.assistant_jobs.get(session_id)
        if entry and entry[0] == body.request_id:
            entry[1].cancel()
        return {'cancelled':True, 'request_id':body.request_id}

    @app.post('/api/sessions/{session_id}/assistant/clear')
    async def clear_assistant(session_id: str, request: Request, service=Depends(authorized)):
        if session_id in request.app.state.assistant_jobs:
            raise HTTPException(409, 'assistant_in_progress')
        with service.store.transaction():
            service.store.connection.execute('DELETE FROM assistant_messages WHERE session_id=?', (session_id,))
            service.store.connection.execute('DELETE FROM assistant_receipts WHERE session_id=?', (session_id,))
        return {'cleared':True}

    @app.get("/api/capabilities")
    async def capabilities():
        configured = bool(model_config()['key'])
        return {"recommendations": enabled, "conversation": configured, "campaigns": enabled,
                "queries": enabled, "model":model_config()['model'], "model_key_configured":configured,
                "account_scope": "local", "checkout": False}

    web = Path(__file__).resolve().parent.parent / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app


app = create_app()
