from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import signal
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .analysis import overview
from .cli import status
from .config import load_config
from .controls import Controls
from .storage import readonly
from .storage_policy import storage_status
from .observed_usage import observed_usage
from .projection import projection_scenario
from .ui_store import UIStore
from .ai_service import AIService
from .ai_raw_export import raw_csv, validate_history
from .process_analysis import coincidences
from .web_security import LimitedBodyMiddleware

LOG = logging.getLogger(__name__)
COOKIE = "device_observability_session"


class TariffBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: str = Field(max_length=20)
    effective_date: str = Field(max_length=10)
    description: str = Field(default="", max_length=180)


class CollectorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=64, max_length=64)
    interval_seconds: float = Field(ge=1, le=3600)
    thermal_interval_seconds: float = Field(ge=1, le=3600)
    process_interval_seconds: float | None = Field(default=None, ge=5, le=3600)
    process_top_n: int | None = Field(default=None, ge=1, le=10)
    enabled_collectors: list[str] = Field(min_length=1, max_length=6)
    max_storage_bytes: int | None = Field(default=None, ge=64*1024**2, le=1024**4, strict=True)
    retention_days: int | None = Field(default=None, ge=0, le=3650, strict=True)


class AIQuoteBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start_ms: int
    end_ms: int
    question: str = Field(min_length=1, max_length=500)
    hours_per_day: float | None = Field(default=None, gt=0, le=24, allow_inf_nan=False)


class AIModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=80)


class AILimitsBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = Field(strict=True)
    per_analysis_usd: float = Field(ge=.001, le=5, strict=True)
    daily_usd: float = Field(ge=.001, le=1000, strict=True)
    monthly_usd: float = Field(ge=.001, le=1000, strict=True)
    authorized_total_usd: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False, strict=True)


class AIKeyBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(min_length=10, max_length=1024, repr=False)


def create_app(config_path: Path, *, token: str | None = None, static_dir: Path | None = None,
               port: int = 8765, idle_seconds: int = 0, ai_transport=None) -> FastAPI:
    config = load_config(config_path)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    token_path = config.data_dir / "interface-token"
    if token is None:
        if not token_path.exists():
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_urlsafe(32))
        token = token_path.read_text().strip()
    secret = token.encode()
    ui = UIStore(config.data_dir / "interface.sqlite3")
    ai = AIService(config.data_dir, transport=ai_transport)
    controls = Controls(config_path)
    static_dir = (static_dir or Path(__file__).resolve().parent.parent / "backend/static").resolve()
    origin_hosts = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    last_request = time.monotonic()
    cache = OrderedDict()
    cache_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        async def idle_watch():
            while True:
                await asyncio.sleep(30)
                if idle_seconds and time.monotonic() - last_request > idle_seconds:
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
        task = asyncio.create_task(idle_watch()) if idle_seconds else None
        try:
            yield
        finally:
            if task:
                task.cancel()

    app = FastAPI(title="Vatilume", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(LimitedBodyMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def authenticated(value):
        try:
            stamp, nonce, signature = value.split(".")
            age = time.time() - int(stamp)
            expected = hmac.new(secret, f"{stamp}.{nonce}".encode(), hashlib.sha256).hexdigest()
            return 0 <= age <= 86400 and hmac.compare_digest(signature, expected)
        except (ValueError, AttributeError):
            return False

    @app.middleware("http")
    async def security(request: Request, call_next):
        nonlocal last_request
        last_request = time.monotonic()
        if request.url.path.startswith("/api/"):
            if request.method not in ("GET", "HEAD") and request.headers.get("origin") not in origin_hosts:
                return JSONResponse({"detail": "Origem da solicitação não permitida."}, status_code=403)
            if request.url.path != "/api/session" and not authenticated(request.cookies.get(COOKIE)):
                return JSONResponse({"detail": "Abra a interface pelo acesso local da aplicação."}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/api/", "/legal/")) or request.url.path == "/" else "public, max-age=31536000, immutable"
        return response

    @app.get('/legal/{document}')
    def legal(document: str):
        documents = {'license': 'LICENSE', 'privacy': 'PRIVACY.md',
                     'third-party': 'THIRD_PARTY_NOTICES.md', 'security': 'SECURITY.md'}
        filename = documents.get(document)
        if filename is None:
            raise HTTPException(404, 'Documento não encontrado.')
        path = Path(__file__).resolve().parent.parent / filename
        if not path.is_file():
            raise HTTPException(404, 'Documento indisponível nesta instalação.')
        return FileResponse(path, media_type='text/plain; charset=utf-8')

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's default HTTP errors include the submitted value, which may
        # be an API key. Never reflect input/ctx or log the request body.
        return JSONResponse({'detail': 'Revise os campos: tipo, tamanho ou valor fora do limite permitido.'}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def unavailable(request, exc):
        LOG.error("database query failed: %s", type(exc).__name__)
        return JSONResponse({"detail": "O histórico está temporariamente indisponível. Tente atualizar os dados."}, status_code=503)

    @app.exception_handler(OSError)
    async def disk_unavailable(request, exc):
        return JSONResponse({"detail": "Não foi possível acessar o armazenamento. Confira espaço livre e permissões em Configurações → Diagnóstico."}, status_code=503)

    @app.post("/api/session")
    def session(request: Request, response: Response):
        if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
            raise HTTPException(401, "Acesso local inválido.")
        stamp, nonce = str(int(time.time())), secrets.token_hex(16)
        signature = hmac.new(secret, f"{stamp}.{nonce}".encode(), hashlib.sha256).hexdigest()
        response.set_cookie(COOKIE, f"{stamp}.{nonce}.{signature}", httponly=True, samesite="strict", max_age=86400)
        return {"authenticated": True}

    @app.delete("/api/session")
    def logout(response: Response):
        response.delete_cookie(COOKIE)
        return {"authenticated": False}

    @app.get("/api/status")
    def state():
        current = load_config(config_path)
        result = status(current.data_dir)
        result["configuration"] = controls.settings()
        result["storage"] = storage_status(current.data_dir, current.max_storage_bytes, current.minimum_free_bytes)
        result["server_time_ms"] = time.time_ns() // 1_000_000
        result["timezone"] = "America/Sao_Paulo"
        return result

    def data(hours, start_ms, end_ms, points):
        if hours not in (1, 6, 24, 168, 720):
            raise ValueError("Período não permitido.")
        end = end_ms if end_ms is not None else time.time_ns() // 10_000_000_000 * 10000
        start = start_ms if start_ms is not None else end - hours * 3_600_000
        tariffs = ui.tariffs()
        with closing(readonly(config.data_dir / "telemetry.sqlite3")) as con:
            last_id = con.execute("SELECT COALESCE(MAX(id),0) FROM samples").fetchone()[0]
        key = start, end, points, last_id, json.dumps(tariffs, sort_keys=True)
        with cache_lock:
            if key in cache:
                return cache[key]
            result = overview(config.data_dir / "telemetry.sqlite3", start, end, tariffs, points)
            result['tariffs_applied'] = tariffs
            cache[key] = result
            while len(cache) > 4:
                cache.popitem(last=False)
            return result

    @app.get('/api/diagnostics')
    def diagnostics():
        current = load_config(config_path)
        health = status(current.data_dir)
        disk = storage_status(current.data_dir, current.max_storage_bytes, current.minimum_free_bytes)
        checks = [
            {'name':'Coletor', 'ok':health.get('state')=='running',
             'message':'Recebendo dados recentes.' if health.get('state')=='running' else 'Abra Eventos. Se a coleta não voltar, consulte o guia de suporte para verificar o serviço.'},
            {'name':'Armazenamento', 'ok':not disk['warning'],
             'message':'Há espaço para continuar.' if not disk['warning'] else 'A cota ou o espaço livre exige atenção. Revise Armazenamento; o histórico confirmado não é apagado sem retenção habilitada.'},
            {'name':'Configuração', 'ok':controls.settings()['applied'],
             'message':'A configuração solicitada já foi aplicada.' if controls.settings()['applied'] else 'Aguardando confirmação do coletor. Atualize em alguns segundos.'},
            {'name':'Credencial da IA', 'ok':ai.key_path.is_file(),
             'message':'Chave salva. Use Verificar acesso para testar a conexão; isso não confirma saldo.' if ai.key_path.is_file() else 'Opcional: configure uma chave para solicitar análises. A coleta funciona sem IA.'},
        ]
        return {'checks':checks, 'storage':disk, 'version':__version__, 'uploads':False}

    @app.get("/api/overview")
    def view(hours: int = 24, start_ms: int | None = None, end_ms: int | None = None, points: int = 240):
        return data(hours, start_ms, end_ms, points)

    @app.get('/api/processes/coincidences')
    def process_peaks(hours: int = 24, start_ms: int | None = None, end_ms: int | None = None, metric: str = 'cpu_w'):
        result = data(hours, start_ms, end_ms, 240)
        return coincidences(result['series'], result['processes'], result['window'], metric)

    @app.get("/api/export.csv")
    def export(hours: int = 24, start_ms: int | None = None, end_ms: int | None = None):
        result = data(hours, start_ms, end_ms, 240)
        output = io.StringIO()
        columns = ["time_ms", "cpu_w", "gpu_w", "cpu_percent", "gpu_percent", "cpu_temp", "gpu_temp", "memory_used_bytes"]
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["series"])
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="historico-agregado.csv"'})

    @app.get("/api/settings")
    def settings():
        return {"collector": controls.settings(), "tariffs": ui.tariffs(), "version": __version__,
                "tariff_context": {"source": "manual"}}

    @app.put("/api/settings/collector")
    def configure(body: CollectorBody):
        patch = body.model_dump(exclude={"revision"}, exclude_none=True)
        result = controls.save(patch, body.revision)
        ui.audit("collector_configuration_requested", {"revision": result["revision"], "values": result["values"]})
        return result

    @app.post("/api/settings/tariffs")
    def tariff(body: TariffBody):
        result = ui.save_tariff(body.price, body.effective_date, body.description)
        with cache_lock:
            cache.clear()
        return result

    @app.get('/api/ai/settings')
    def ai_settings():
        return ai.settings()

    @app.put('/api/ai/settings')
    def ai_limits(body: AILimitsBody):
        result = ai.ledger.configure(body.model_dump(exclude={'authorized_total_usd'}), cap_usd=body.authorized_total_usd)
        ui.audit('ai_spending_limits_changed', body.model_dump())
        return {**result, 'key_configured': ai.key_path.is_file()}

    @app.put('/api/ai/key')
    def ai_key(body: AIKeyBody):
        result = ai.save_key(body.key)
        ui.audit('ai_api_key_updated', {'key_configured': True})
        return result

    @app.delete('/api/ai/key')
    def remove_ai_key():
        result = ai.remove_key()
        ui.audit('ai_api_key_removed', {'key_configured': False})
        return result

    @app.put('/api/ai/model')
    def ai_model(body: AIModelBody):
        result = ai.save_model(body.model)
        ui.audit('ai_model_changed', {'model':body.model})
        return result

    @app.post('/api/ai/key/check')
    def check_ai_key():
        return ai.check_key()

    @app.post('/api/ai/quotes')
    def ai_quote(body: AIQuoteBody):
        view = data(24, body.start_ms, body.end_ms, 240)
        current = load_config(config_path)
        ai.storage_limit = current.max_storage_bytes
        usage = None
        if body.hours_per_day is None:
            try:
                projection_scenario(body.question, None)
            except ValueError as error:
                if 'intervalos suficientes' not in str(error): raise
                usage = observed_usage(config.data_dir / 'telemetry.sqlite3', body.end_ms)
        return ai.quote(view, view['tariffs_applied'], body.question, body.hours_per_day, observed_usage=usage)

    @app.post('/api/ai/analyses/{identity}')
    def ai_start(identity: str):
        result = ai.start(identity)
        ui.audit('ai_analysis_started', {'id': identity})
        return result

    @app.get('/api/ai/analyses')
    def ai_recent():
        return {'analyses': ai.store.recent()}

    @app.get('/api/ai/analyses/{identity}')
    def ai_record(identity: str):
        return ai.record(identity)

    @app.get('/api/ai/analyses/{identity}/evidence/{evidence_id}')
    def ai_evidence(identity: str, evidence_id: str):
        item = ai.record(identity)
        if not item['report'] or evidence_id not in item['report']['evidence']:
            raise HTTPException(404, 'Evidência não encontrada nesta análise validada.')
        return item['report']['evidence'][evidence_id]

    @app.get('/api/ai/analyses/{identity}/evidence/{evidence_id}/raw.csv')
    def ai_raw(identity: str, evidence_id: str):
        item = ai.store.get(identity, snapshot=True)
        evidence = (item['report'] or {}).get('evidence', {}).get(evidence_id)
        if not evidence or evidence['tool'] != 'calculate_energy_cost': raise HTTPException(404, 'Consulta de energia não encontrada.')
        frozen = item['snapshot']
        database = config.data_dir / 'telemetry.sqlite3'
        validate_history(database, frozen.get('provenance'), frozen['window']['start_ms'])
        return StreamingResponse(raw_csv(database, frozen),media_type='text/csv; charset=utf-8',
            headers={'Content-Disposition':'attachment; filename="leituras-energia.csv"'})

    @app.get('/api/ai/analyses/{identity}/evidence/{evidence_id}/processes.csv')
    def process_csv(identity: str, evidence_id: str):
        record = ai.record(identity)
        evidence = (record['report'] or {}).get('evidence', {}).get(evidence_id)
        if not evidence or evidence['tool'] != 'inspect_process_activity':
            raise HTTPException(404, 'Evidência de processos não encontrada.')
        output = io.StringIO()
        fields = ['peak_start_ms','peak_end_ms','metric','value','unit','sample_id','session_id',
            'pid','start_ticks','name','interval_start_ms','interval_end_ms','elapsed_ns',
            'cpu_ticks','previous_cpu_ticks','clock_ticks_per_second','machine_cpu_count','cpu_percent','rss_bytes','scan_quality',
            'ppid','application_id','application_name','application_method','application_alias','application_members_only','ancestors_json']
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for peak in evidence['data']['peaks']:
            for group in peak['matches']:
                for entry in group['entries']:
                    name = entry['name']
                    if name.startswith(('=','+','-','@','\t','\r')):
                        name = "'" + name  # Spreadsheet formula protection for untrusted process names.
                    label = group['name']
                    if label.startswith(('=','+','-','@','\t','\r')):
                        label = "'" + label
                    writer.writerow({**{k:entry[k] for k in fields if k in entry}, 'name':name,
                        'application_id':group.get('id',''), 'application_name':label,
                        'application_method':entry.get('application',{}).get('method',''),
                        'application_alias':group['alias'],'application_members_only':group.get('members_only',True),
                        'ancestors_json':json.dumps(entry.get('ancestors',[]),ensure_ascii=False),
                        'peak_start_ms':peak['start_ms'],'peak_end_ms':peak['end_ms'],
                        'metric':evidence['data']['metric'],'value':peak['value'],'unit':evidence['data']['unit'],
                        'sample_id':peak['sample_id'],'session_id':peak['session_id'], 'scan_quality':peak['scan_quality'],
                        'clock_ticks_per_second':peak['scan']['clock_ticks_per_second'], 'machine_cpu_count':peak['scan']['machine_cpu_count']})
        return Response(content='\ufeff'+output.getvalue(), media_type='text/csv; charset=utf-8',
            headers={'Content-Disposition':'attachment; filename="evidencias-processos.csv"'})

    @app.get("/")
    def index():
        if not (static_dir / "index.html").exists():
            raise HTTPException(503, "Interface ainda não compilada.")
        return FileResponse(static_dir / "index.html")

    @app.get("/assets/{name:path}")
    def asset(name: str):
        target = (static_dir / "assets" / name).resolve()
        if not target.is_relative_to(static_dir / "assets") or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target)

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/collector.toml"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fd", type=int)
    parser.add_argument("--idle-seconds", type=int, default=0)
    args = parser.parse_args()
    os.umask(0o077)
    uvicorn.run(create_app(args.config, port=args.port, idle_seconds=args.idle_seconds), host="127.0.0.1",
                port=args.port, fd=args.fd, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
