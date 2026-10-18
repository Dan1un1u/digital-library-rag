import importlib.metadata as metadata
import json
import platform
from pathlib import Path
import sys
import torch
import transformers

ROOT = Path(__file__).resolve().parents[1]
names = ['torch', 'transformers', 'huggingface-hub', 'safetensors', 'numpy', 'tokenizers',
         'requests', 'fastapi', 'uvicorn', 'pydantic', 'pydantic-core']
packages = {}
for name in names:
    distribution = metadata.distribution(name)
    packages[name] = {'version': distribution.version, 'location': str(distribution.locate_file(''))}
if not torch.cuda.is_available():
    raise RuntimeError('CUDA runtime is unavailable')
with torch.inference_mode():
    left = torch.randn(128, 128, dtype=torch.float16, device='cuda:0')
    product = left @ left.T
    gpu_test = bool(torch.isfinite(product).all())
report = {'python': sys.version, 'python_prefix': sys.prefix, 'platform': platform.platform(),
          'packages': packages, 'gpu': torch.cuda.get_device_name(0),
          'compute_capability': list(torch.cuda.get_device_capability(0)),
          'cuda_runtime': torch.version.cuda, 'fp16_gpu_matmul_passed': gpu_test,
          'deployment_root': str(ROOT), 'new_packages_installed_in': str(ROOT / '.venv-wsl'),
          'reuse_method': 'Read existing GPU and shared ML site-packages through local .pth; do not install into them',
          'transformers_file': transformers.__file__}
(ROOT / 'reports/environment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if gpu_test else 1)
