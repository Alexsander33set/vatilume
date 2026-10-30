"""On-demand, evidence-validated API analysis. No collector writes or retries."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .ai_cost import CostLedger, MODEL, atomic_json
from .ai_models import MODELS, PRICE_DATE, model_info
from .ai_evidence import EvidenceSession, SYSTEM, snapshot, tools_schema
from .ai_store import AIStore
from .diagnostics import provider_error
from .storage_policy import ensure_capacity
from .projection import asks_monthly_projection, projection_scenario

VALIDATOR_VERSION = 'observed-domain-model-3'


class ResponsesTransport:
    def __init__(self, key_path: Path):
        self.key_path = key_path

    def __call__(self, body, timeout):
        info = self.key_path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('A chave da API precisa pertencer ao serviço e ter permissão privada.')
        key = self.key_path.read_text().strip()
        if not key: raise ValueError('Configure uma chave da API.')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request('https://api.openai.com/v1/responses', data=body,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        try:
            with opener.open(request, timeout=timeout) as response:
                content = response.read(1_000_001)
                if len(content) > 1_000_000: raise ValueError('Resposta excedeu o limite de tamanho.')
                return json.loads(content)
        except urllib.error.HTTPError as error:
            try:
                detail=json.loads(error.read(16384)).get('error',{}).get('code')
            except (ValueError,AttributeError):
                detail=None
            raise ValueError(provider_error(error.code,detail)+' Não houve repetição automática; a reserva foi preservada.') from None
        except (OSError, ValueError):
            raise ValueError('Não foi possível confirmar a resposta da API. A reserva de gasto foi preservada.') from None


class AIService:
    def __init__(self, directory: Path, *, transport=None, ledger_path=None, limits_path=None, key_path=None):
        self.directory = directory
        self.store = AIStore(directory / 'ai.sqlite3')
        with (directory / 'ai-active.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.store.recover()
            except BlockingIOError:
                pass
        self.ledger = CostLedger(ledger_path or directory / 'ai-budget.json', limits_path or directory / 'ai-limits.json')
        self.key_path = key_path or directory / 'ai-api-key'
        self.transport = transport or ResponsesTransport(self.key_path)

    def settings(self):
        return {**self.ledger.status(), 'model': self.selected_model(), 'models': list(MODELS.values()), 'price_date': PRICE_DATE,
                'prices_per_million_usd': {'input': model_info(self.selected_model())['input'], 'output': model_info(self.selected_model())['output']},
                'key_configured': self.key_path.is_file(),
                'privacy': 'Sua pergunta é enviada ao provedor junto de fatos e recortes numéricos. Não inclua dados pessoais ou credenciais na pergunta. Nomes/PIDs de processos, inventário e chaves não são incluídos automaticamente nos prompts; isso não é garantia de anonimato.',
                'retention_note': 'store=false; o provedor ainda pode reter registros de monitoramento de abuso.',
                'validator_version': VALIDATOR_VERSION}

    def selected_model(self):
        path = self.directory / 'ai-model.json'
        selected = json.loads(path.read_text())['model'] if path.exists() else MODEL
        model_info(selected)
        return selected

    def save_model(self, identity):
        model_info(identity)
        atomic_json(self.directory / 'ai-model.json', {'model': identity})
        return self.settings()

    def save_key(self, key):
        with (self.directory / 'ai-active.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Aguarde a análise em andamento antes de substituir a chave.') from None
            return self._save_key(key)

    def _save_key(self, key):
        key = key.strip()
        if not 10 <= len(key) <= 1024 or any(c.isspace() for c in key): raise ValueError('Chave inválida.')
        temporary = self.key_path.with_name('ai-api-key.' + uuid.uuid4().hex + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(key)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.key_path)
        return {'key_configured': True}

    def remove_key(self):
        with (self.directory / 'ai-active.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Aguarde a análise em andamento terminar antes de remover a chave.') from None
            limits = self.ledger.status()['limits']
            self.ledger.configure({**limits, 'enabled': False})
            self.key_path.unlink(missing_ok=True)
            fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
        return {'key_configured': False}

    def check_key(self):
        identity=self.selected_model()
        info=self.key_path.stat() if self.key_path.exists() else None
        if info is None: raise ValueError('Configure uma chave da API antes de verificar o acesso.')
        if info.st_uid!=os.getuid() or info.st_mode&0o077: raise ValueError('O arquivo da chave precisa ter acesso privado da conta do serviço.')
        key=self.key_path.read_text().strip()
        request=urllib.request.Request('https://api.openai.com/v1/models/'+identity,headers={'Authorization':'Bearer '+key})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=8) as response:
                response.read(65536)
        except urllib.error.HTTPError as error:
            raise ValueError(provider_error(error.code)) from None
        except OSError:
            raise ValueError('Não foi possível conectar à OpenAI. Confira internet, DNS e firewall; nenhuma análise foi iniciada.') from None
        return {'credential_accepted':True,'model_visible':True,'billing_verified':False,
                'message':'A credencial foi aceita e o modelo está visível. Este teste não gera uma análise e não confirma créditos ou autorização de faturamento.'}

    def quote(self, view, tariffs, question, hours_per_day=24, *, model=None, observed_usage=None):
        if not 1 <= len(question.strip()) <= 500: raise ValueError('Escreva uma pergunta com até 500 caracteres.')
        settings = self.settings()
        selected_model = model or settings['model']
        model_info(selected_model)
        if not settings['limits']['enabled']: raise ValueError('As chamadas de IA estão pausadas.')
        if not settings['key_configured']: raise ValueError('Configure a chave da API antes de preparar uma análise.')
        if settings['remaining_usd'] < .001: raise ValueError('Não há orçamento disponível dentro dos limites atuais.')
        if view['sample_count'] < 2: raise ValueError('Acumule pelo menos duas amostras antes de analisar.')
        experiments_path = self.directory / 'ai-experiment-windows.json'
        experiments = json.loads(experiments_path.read_text()) if experiments_path.exists() else []
        frozen = snapshot(view, tariffs, experiments, projection_scenario(question, hours_per_day, observed_usage))
        frozen['model'] = selected_model
        frozen['sha256'] = hashlib.sha256(json.dumps({k:v for k,v in frozen.items() if k!='sha256'},sort_keys=True,allow_nan=False).encode()).hexdigest()
        maximum = min(settings['remaining_usd'], settings['limits']['per_analysis_usd'])
        cached = self.store.cached(frozen['sha256'], question.strip(), selected_model, VALIDATOR_VERSION)
        identity = cached or str(uuid.uuid4())
        frozen['approval_max_usd'] = maximum
        if not cached: ensure_capacity(self.directory, getattr(self,'storage_limit',2*1024**3), additional_bytes=len(json.dumps(frozen).encode())*3+65536)
        if not cached: self.store.create(identity, frozen, question.strip())
        preview = None
        if asks_monthly_projection(question):
            calculated = EvidenceSession(frozen, question)
            preview = calculated.validate({'answer_id': 'monthly_projection', 'fact_ids': ['monthly_projection'],
                'recommendation_ids': [], 'answer_status': 'evidence_found'})['answer']
        return {'id': identity, 'model': selected_model, 'window': frozen['window'], 'snapshot_sha256': frozen['sha256'],
                'projection': frozen['projection'],
                'calculation_preview': preview,
                'sample_count': frozen['sample_count'], 'maximum_usd': 0 if cached else maximum, 'cached': bool(cached),
                'authorized_total_usd': settings['authorized_total_usd'], 'expires_in_seconds': 180,
                'data_sent': ['Valores calculados de CPU/GPU e cobertura', 'Médias, desvios e pontos das métricas consultadas',
                    'CPU de processos com apelidos, sem nomes, PIDs, argumentos ou caminhos', 'Sua pergunta'],
                'whole_pc_measured': False}

    def start(self, identity):
        if self.store.get(identity)['state'] == 'complete': return self.record(identity)
        # Cross-process lock prevents duplicate concurrent work, without a queue.
        lock = (self.directory / 'ai-active.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise ValueError('Há uma análise em execução. Aguarde antes de iniciar outra.') from None
        try:
            self.store.start(identity)
        except BaseException:
            lock.close()
            raise
        thread = threading.Thread(target=self._run, args=(identity, lock), daemon=True, name='ai-analysis')
        thread.start()
        return self.record(identity)

    def record(self, identity):
        item = self.store.get(identity)
        item['estimated_cost_usd'] = self.ledger.run_cost(identity)
        return item

    def _run(self, identity, lock):
        try:
            record = self.store.get(identity, snapshot=True)
            report = self.analyze(identity, record['snapshot'], record['question'])
            self.store.finish(identity, report=report)
        except Exception as error:
            # Only curated domain errors are public; raw HTTP/provider content is never exposed.
            message = str(error) if isinstance(error, ValueError) else 'A análise foi interrompida. Nenhuma afirmação não validada foi exibida.'
            self.store.finish(identity, error=message)
        finally:
            lock.close()

    def analyze(self, identity, frozen, question):
        evidence = EvidenceSession(frozen, question)
        selected_model = frozen.get('model', MODEL)
        model_info(selected_model)
        maximum = frozen.get('approval_max_usd', self.ledger.status()['limits']['per_analysis_usd'])
        inputs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps({
            'question': question, 'already_queried_by_backend': evidence.initial()}, ensure_ascii=False)}]
        started, usage, queries = time.monotonic(), [], 0
        for turn in range(6):
            remaining = 120 - (time.monotonic() - started)
            if remaining <= 0: raise ValueError('A análise excedeu o prazo. Não houve repetição automática.')
            body = {'model': selected_model, 'input': inputs, 'tools': tools_schema(), 'parallel_tool_calls': False,
                'store': False, 'reasoning': {'effort': 'none'}, 'max_output_tokens': 512,
                'text': {'format': {'type': 'json_schema', 'name': 'verified_fact_selection', 'schema': evidence.output_schema(), 'strict': True}}}
            if turn == 5: body['tool_choice'] = 'none'
            payload = json.dumps(body, ensure_ascii=False).encode()
            request_id = self.ledger.reserve(payload, 512, identity, maximum=maximum, model=selected_model)
            result = self.transport(payload, min(30, remaining))
            returned_usage = result.get('usage', {})
            self.ledger.finish(request_id, {k: returned_usage.get(k) for k in ('input_tokens', 'output_tokens')})
            usage.append({k: returned_usage[k] for k in ('input_tokens', 'output_tokens')})
            if result.get('status') != 'completed': raise ValueError('A API não concluiu a resposta. Nenhuma afirmação foi exibida.')
            outputs = result.get('output', [])
            if not isinstance(outputs, list): raise ValueError('Resposta de API inválida.')
            calls = [item for item in outputs if item.get('type') == 'function_call']
            if calls:
                if len(calls) != 1: raise ValueError('A resposta excedeu o limite de ferramentas por rodada.')
                call = calls[0]
                queries += 1
                if queries > 5: raise ValueError('A análise excedeu o limite de consultas.')
                try:
                    arguments = json.loads(call['arguments'])
                    output = evidence.execute(call['name'], arguments)
                except (ValueError, KeyError, TypeError):
                    raise ValueError('A IA solicitou uma consulta fora do contrato. Resposta bloqueada.') from None
                inputs.extend([{'type': 'function_call', 'call_id': call['call_id'], 'name': call['name'], 'arguments': call['arguments']},
                    {'type': 'function_call_output', 'call_id': call['call_id'], 'output': json.dumps(output, ensure_ascii=False)}])
                continue
            messages = [part for output in outputs if output.get('type') == 'message' for part in output.get('content', [])]
            if any(part.get('type') == 'refusal' for part in messages): raise ValueError('O modelo recusou a solicitação; nenhuma afirmação foi exibida.')
            text = ''.join(part.get('text', '') for part in messages if part.get('type') == 'output_text')
            try: selection = json.loads(text)
            except (ValueError, TypeError): raise ValueError('A API não devolveu uma seleção válida de evidências.') from None
            report = evidence.validate(selection)
            report.update(model=selected_model, validator_version=VALIDATOR_VERSION, created_ms=time.time_ns() // 1_000_000,
                elapsed_seconds=time.monotonic()-started, token_usage=usage, question=question,
                maximum_approved_usd=maximum,
                estimated_cost_usd=self.ledger.run_cost(identity))
            return report
        raise ValueError('A análise não chegou a uma conclusão dentro do limite de consultas.')
