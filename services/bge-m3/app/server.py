"""Single-GPU FP16 BGE-M3 dense embeddings, compatible with /v1/embeddings."""
from contextlib import asynccontextmanager
import json
from pathlib import Path
import threading
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr
import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))


class EmbeddingInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    input: StrictStr | list[StrictStr]
    model: str = CONFIG['model_name']
    encoding_format: Literal['float'] = 'float'
    dimensions: int | None = Field(default=None, strict=True)
    user: str | None = None


class Encoder:
    def __init__(self):
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA is required for this FP16 deployment; CPU fallback is disabled.')
        self.device = torch.device(CONFIG['device'])
        started = time.perf_counter()
        path = ROOT / CONFIG['model_dir']
        self.provenance = json.loads((path / 'provenance.json').read_text(encoding='utf-8'))
        self.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True,
                                                       trust_remote_code=False, use_fast=True,
                                                       fix_mistral_regex=False)
        self.model = AutoModel.from_pretrained(str(path), local_files_only=True, trust_remote_code=False,
                                               use_safetensors=True, dtype=torch.float16,
                                               attn_implementation='sdpa').to(self.device).eval()
        if any(parameter.dtype != torch.float16 or parameter.device != self.device
               for parameter in self.model.parameters()):
            raise RuntimeError('Model must reside on the configured GPU with FP16 parameters.')
        self.lock = threading.Lock()
        self.requests = 0
        self.texts = 0
        self.dimension = self.model.config.hidden_size
        self.parameter_count = sum(parameter.numel() for parameter in self.model.parameters())
        self.started_at = time.time()
        self.encode(['本地数字图书馆语义检索服务就绪。'])
        self.requests = 0
        self.texts = 0
        self.load_seconds = time.perf_counter() - started

    def encode(self, texts):
        if not texts or len(texts) > CONFIG['max_inputs']:
            raise HTTPException(422, f'input must contain 1 to {CONFIG["max_inputs"]} texts')
        if any(not isinstance(text, str) or not text.strip() or len(text) > 65536 for text in texts):
            raise HTTPException(422, 'Each input must be nonempty text with at most 65536 characters')
        with self.lock, torch.inference_mode():
            encoded = self.tokenizer(texts, padding=False, truncation=False, add_special_tokens=True)
            lengths = [len(ids) for ids in encoded['input_ids']]
            if max(lengths) > CONFIG['max_input_tokens']:
                raise HTTPException(422, f'Input exceeds {CONFIG["max_input_tokens"]} tokens; split the document first. No text was truncated.')
            vectors = []
            start = 0
            while start < len(texts):
                end = start + 1
                while end < len(texts) and end - start < CONFIG['batch_size']:
                    padded_tokens = max(lengths[start:end + 1]) * (end + 1 - start)
                    if padded_tokens > CONFIG['max_batch_tokens']:
                        break
                    end += 1
                batch = self.tokenizer.pad({key: values[start:end] for key, values in encoded.items()},
                                          padding=True, return_tensors='pt').to(self.device)
                output = self.model(**batch, return_dict=True).last_hidden_state[:, 0, :].float()
                output = torch.nn.functional.normalize(output, p=2, dim=1)
                if not bool(torch.isfinite(output).all()):
                    raise RuntimeError('Non-finite embedding output')
                vectors.extend(output.cpu().tolist())
                del batch, output
                start = end
            self.requests += 1
            self.texts += len(texts)
            return vectors, sum(lengths)

    def health(self):
        free, total = torch.cuda.mem_get_info(self.device)
        return {'status': 'ready', 'model': CONFIG['model_name'], 'dtype': 'float16',
                'device': str(self.device), 'gpu': torch.cuda.get_device_name(self.device),
                'compute_capability': list(torch.cuda.get_device_capability(self.device)),
                'torch_version': torch.__version__, 'cuda_runtime': torch.version.cuda,
                'dimension': self.dimension, 'parameter_count': self.parameter_count,
                'source_revision': self.provenance['source_revision'],
                'normalization': 'L2', 'pooling': 'CLS', 'output_encoding': 'float32 JSON numbers',
                'max_input_tokens': CONFIG['max_input_tokens'], 'max_inputs': CONFIG['max_inputs'],
                'batch_size': CONFIG['batch_size'], 'max_batch_tokens': CONFIG['max_batch_tokens'],
                'cuda_allocated_mib': round(torch.cuda.memory_allocated(self.device) / 1024**2, 2),
                'cuda_reserved_mib': round(torch.cuda.memory_reserved(self.device) / 1024**2, 2),
                'cuda_peak_allocated_mib': round(torch.cuda.max_memory_allocated(self.device) / 1024**2, 2),
                'gpu_free_mib': round(free / 1024**2, 2), 'gpu_total_mib': round(total / 1024**2, 2),
                'load_seconds': round(self.load_seconds, 3),
                'requests': self.requests, 'texts': self.texts,
                'scope': 'Dense embeddings only; no text generation, reranker, sparse or ColBERT outputs'}


@asynccontextmanager
async def lifespan(app):
    app.state.encoder = Encoder()
    yield


app = FastAPI(title='Local BGE-M3 FP16 Embeddings', version='1.0.0', lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse({'error': {'message': str(exc.detail), 'type': 'invalid_request_error',
                                   'code': 'INVALID_REQUEST' if exc.status_code == 422 else 'SERVICE_ERROR'}},
                        status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def invalid(request, exc):
    return JSONResponse({'error': {'message': 'Invalid embedding request schema',
                                   'type': 'invalid_request_error', 'code': 'INVALID_REQUEST'}}, status_code=422)


@app.get('/health')
def health(request: Request):
    return request.app.state.encoder.health()


@app.get('/v1/models')
def models():
    return {'object': 'list', 'data': [{'id': CONFIG['model_name'], 'object': 'model',
                                      'created': 0, 'owned_by': 'local-BAAI'}]}


@app.post('/v1/embeddings')
def embeddings(body: EmbeddingInput, request: Request):
    encoder = request.app.state.encoder
    if body.model not in (CONFIG['model_name'], 'bge-m3-fp16'):
        raise HTTPException(422, 'Unknown model; use BAAI/bge-m3 or bge-m3-fp16')
    if body.dimensions is not None and body.dimensions != encoder.dimension:
        raise HTTPException(422, 'BGE-M3 dense embeddings have a fixed dimension of 1024')
    texts = [body.input] if isinstance(body.input, str) else body.input
    try:
        vectors, tokens = encoder.encode(texts)
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        raise HTTPException(503, 'GPU memory unavailable; retry with shorter inputs or fewer concurrent applications') from None
    return {'object': 'list', 'data': [{'object': 'embedding', 'index': i, 'embedding': vector}
                                       for i, vector in enumerate(vectors)],
            'model': CONFIG['model_name'], 'usage': {'prompt_tokens': tokens, 'total_tokens': tokens}}
