"""DEP-001: legacy cloud configuration, request contracts and portable startup."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from dotenv import dotenv_values
import pytest
from pydantic import ValidationError
import requests

from dlrag.api.qa_factory import create_client
from dlrag.api.services import assemble
from dlrag.ingestion.metadata_api import request_candidates
from dlrag.qa.errors import ProjectError as QAError
from dlrag.qa.llm_client import SiliconFlowLLM
from dlrag.qa.semantic_reranker import SiliconFlowReranker
from dlrag.retrieval.embeddings import SiliconFlowEmbedding
from dlrag.retrieval.errors import ProjectError as RetrievalError
from dlrag.shared.config import Settings

ROOT = Path(__file__).resolve().parents[3]
PROVIDERS = ['llm_provider', 'embedding_provider', 'metadata_api_provider', 'qa_rerank_provider']


@pytest.fixture
def legacy_settings(tmp_path, monkeypatch):
    # The original delivery did not contain provider selectors. Use only its keys.
    values = dict(dotenv_values(ROOT / 'app/.env.example'))
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    for name in PROVIDERS:
        values.pop(name.upper(), None)
    values.update(APP_MODE='real', DATA_DIR=str(tmp_path / 'cloud-library'),
                  SILICONFLOW_API_KEY='offline-contract-fixture', LLM_API_KEY='')
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_original_configuration_selects_cloud_for_every_service(legacy_settings, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Assembly must not call a model server')
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)
    services = assemble(legacy_settings)
    assert all(getattr(legacy_settings, name) == 'siliconflow' for name in PROVIDERS)
    assert type(services.retriever.backend) is SiliconFlowEmbedding
    assert type(services.qa.llm) is SiliconFlowLLM
    assert type(services.qa.reranker) is SiliconFlowReranker
    assert services.qa.llm._api_key == 'offline-contract-fixture'
    assert services.embedding_configured and services.llm_configured
    assert not [row for row in services.issues if row['component'] in {'A', 'B', 'C'}]


@pytest.mark.parametrize('service', ['qa', 'metadata', 'embedding', 'rerank'])
def test_cloud_http_contract(legacy_settings, monkeypatch, service):
    calls = []

    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            if service == 'embedding':
                return {'data': [{'index': 0, 'embedding': [1.] * 1024}]}
            if service == 'rerank':
                return {'results': [{'index': 0, 'relevance_score': .8}]}
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(requests.Session, 'post', lambda self, url, **kw: post(url, **kw))
    settings = legacy_settings
    if service == 'qa':
        assert create_client(settings).generate_json('Return JSON.', {'question': '元数据质量'}) == {'ok': True}
        endpoint, model = '/chat/completions', settings.llm_model
    elif service == 'metadata':
        pages = [{'pdf_page': 1, 'text': 'Metadata quality', 'image': 'data:image/jpeg;base64,Zml4dHVyZQ=='}]
        assert request_candidates(settings, pages, {}) == {'ok': True}
        endpoint, model = '/chat/completions', settings.metadata_api_model
    elif service == 'embedding':
        client = SiliconFlowEmbedding(api_key=settings.siliconflow_api_key.get_secret_value())
        assert client.encode(['Metadata quality']).shape == (1, 1024)
        endpoint, model = '/embeddings', settings.embedding_model
    else:
        client = SiliconFlowReranker(settings.siliconflow_api_key.get_secret_value(), model=settings.qa_rerank_model)
        hits = [{'rank': 1, 'chunk': {'text': 'Metadata quality'}, 'scores': {}}]
        assert client.rerank('metadata', hits)[0]['semantic_relevance'] == .8
        endpoint, model = '/rerank', settings.qa_rerank_model
    assert len(calls) == 1
    url, options = calls[0]
    assert url == 'https://api.siliconflow.cn/v1' + endpoint
    assert options['headers'] == {'Authorization': 'Bearer offline-contract-fixture'}
    assert options['allow_redirects'] is False
    body = options['json']
    assert body['model'] == model
    assert not {'max_completion_tokens', 'reasoning_effort'} & body.keys()
    if service in {'qa', 'metadata'}:
        assert body['response_format'] == {'type': 'json_object'}
        assert body['temperature'] == 0 and body['stream'] is False
        assert body['max_tokens'] == (settings.llm_max_output_tokens if service == 'qa' else 2200)
    if service == 'qa':
        assert body['enable_thinking'] is False
    if service == 'metadata':
        assert body['messages'][1]['content'][-1]['image_url']['url'] == pages[0]['image']
    if service == 'embedding':
        assert body['encoding_format'] == 'float' and body['input'] == ['Metadata quality']
    if service == 'rerank':
        assert body['top_n'] == 1 and body['return_documents'] is False and body['instruction']


@pytest.mark.parametrize('field', PROVIDERS)
def test_project_rejects_private_provider_selection(field):
    with pytest.raises(ValidationError):
        Settings(app_mode='real', _env_file=None, **{field: 'private-deployment'})


@pytest.mark.parametrize('adapter', [SiliconFlowLLM, SiliconFlowEmbedding, SiliconFlowReranker])
def test_cloud_adapters_keep_https_requirement(adapter):
    with pytest.raises((QAError, RetrievalError)):
        adapter(api_key='fixture', base_url='http://127.0.0.1:8000/v1')


@pytest.fixture
def controller(tmp_path, monkeypatch):
    if os.name != 'nt':
        pytest.skip('The supplied process controller is a Windows entry point')
    spec = importlib.util.spec_from_file_location('dep001_controller', ROOT / 'scripts/control.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ['DATA_DIR', 'DB_PATH', 'FILES_DIR', 'INDEX_DIR']:
        monkeypatch.delenv(name, raising=False)
    module.ROOT = tmp_path
    module.APP = tmp_path / 'app'
    module.APP.mkdir()
    module.STATE = tmp_path / 'runtime/processes.json'
    return module


def test_real_startup_honors_env_file_paths(controller):
    (controller.APP / '.env').write_text('DATA_DIR=../collection\nDB_PATH=../db/custom.sqlite\n', encoding='utf-8')
    environment = controller.environment('real')
    assert Path(environment['DATA_DIR']) == controller.ROOT / 'collection'
    assert Path(environment['DB_PATH']) == controller.ROOT / 'db/custom.sqlite'
    assert Path(environment['FILES_DIR']) == controller.ROOT / 'collection/raw'
    assert Path(environment['INDEX_DIR']) == controller.ROOT / 'collection/indexes'


def test_process_environment_takes_priority(controller, tmp_path, monkeypatch):
    (controller.APP / '.env').write_text('DATA_DIR=../ignored\n', encoding='utf-8')
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'selected'))
    assert Path(controller.environment('real')['DATA_DIR']) == tmp_path / 'selected'


def test_mock_storage_remains_isolated(controller, monkeypatch):
    (controller.APP / '.env').write_text('DATA_DIR=../private-real\n', encoding='utf-8')
    monkeypatch.setenv('DATA_DIR', 'another-real-library')
    environment = controller.environment('mock')
    assert Path(environment['DATA_DIR']) == controller.ROOT / 'runtime/mock'
    assert not environment['SILICONFLOW_API_KEY'] and not environment['LLM_API_KEY']


@pytest.mark.parametrize('mode', ['real', 'mock', 'both'])
def test_root_launcher_only_starts_project_controller(tmp_path, mode):
    if os.name != 'nt':
        pytest.skip('PowerShell launcher is a Windows entry point')
    # A clean teammate checkout has no private service scripts or runtime folders.
    project = tmp_path / 'teammate project'
    binaries = project / '.venv/Scripts'
    binaries.mkdir(parents=True)
    shutil.copy2(sys.executable, binaries / 'python.exe')
    shutil.copy2(Path(sys.prefix) / 'pyvenv.cfg', project / '.venv/pyvenv.cfg')
    shutil.copy2(ROOT / 'Start-Library.ps1', project / 'Start-Library.ps1')
    (project / 'scripts').mkdir()
    (project / 'scripts/control.py').write_text(
        'import json, sys\nfrom pathlib import Path\n'
        'Path(__file__).with_suffix(".json").write_text(json.dumps(sys.argv[1:]))\n', encoding='utf-8')
    script = str(project / 'Start-Library.ps1').replace("'", "''")
    command = "function powershell.exe { throw 'Unexpected external service startup' }; & '" + script + "' -Mode " + mode
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((project / 'scripts/control.json').read_text()) == ['start', '--mode', mode]
