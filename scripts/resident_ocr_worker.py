"""Private stdin/stdout worker. Reuse verified model objects between OCR jobs.

No HTTP endpoint. The parent owns the process. Existing model adapters remain
the source of preprocessing and inference behaviour. stdout is JSONL only.
"""
import contextlib
import functools
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ocr_ensemble import EXISTING, environment
os.environ.update(environment())
sys.path.insert(0, str(EXISTING))


def main():
    kind = sys.argv[1]
    protocol = sys.stdout
    modules = {}
    with tempfile.TemporaryDirectory(prefix='smartocr-resident-') as dictionary:
        with contextlib.redirect_stdout(sys.stderr):
            if kind == 'cpu':
                import paddle_runner
                import orientation_runner
                # Keep dictionary paths alive for the worker's full lifetime.
                original_engine = paddle_runner.engine
                model = None
                def resident_engine(_directory):
                    nonlocal model
                    if model is None:
                        model = original_engine(dictionary)
                    return model
                paddle_runner.engine = resident_engine
                original_session = orientation_runner.ort.InferenceSession
                sessions = {}
                def resident_session(path, *args, **kwargs):
                    # Only cache the fixed orientation model, not OCR sessions.
                    if 'doc_ori' not in str(path):
                        return original_session(path, *args, **kwargs)
                    if str(path) not in sessions:
                        sessions[str(path)] = original_session(path, *args, **kwargs)
                    return sessions[str(path)]
                orientation_runner.ort.InferenceSession = resident_session
                modules = {'paddle': paddle_runner, 'orientation': orientation_runner}
            elif kind == 'unlimited':
                import mlx_vlm
                original_load = mlx_vlm.load
                models = {}
                def resident_load(path, *args, **kwargs):
                    key = str(Path(path).resolve())
                    if key not in models:
                        models[key] = original_load(path, *args, **kwargs)
                    return models[key]
                mlx_vlm.load = resident_load
                sys.path.insert(0, str(ROOT/'scripts'))
                import run_focused_unlimited
                modules = {'unlimited': run_focused_unlimited}
            else:
                raise ValueError('Unsupported worker kind')
        for line in sys.stdin:
            started = time.monotonic()
            try:
                request = json.loads(line)
                with contextlib.redirect_stdout(sys.stderr):
                    stage = request['stage']
                    if stage in ('paddle', 'orientation'):
                        paths = [Path(p).resolve() for p in request['images']]
                        out = Path(request['out']).resolve()
                        if not out.is_relative_to(ROOT/'data') or any(not p.is_relative_to(ROOT/'data') for p in paths):
                            raise ValueError('Worker input and output must stay inside local data/')
                        modules[stage].run(paths, out)
                    elif stage == 'unlimited':
                        manifest = Path(request['manifest']).resolve()
                        if not manifest.is_relative_to(ROOT/'data'):
                            raise ValueError('Manifest must stay inside local data/')
                        sys.argv = ['run_focused_unlimited.py', '--manifest', str(manifest)]
                        modules[stage].main()
                    else:
                        raise ValueError('Unsupported stage')
                result = {'ok': True, 'elapsed_s': time.monotonic()-started}
            except Exception as exc:
                result = {'ok': False, 'error': str(exc), 'elapsed_s': time.monotonic()-started}
            protocol.write(json.dumps(result)+'\n')
            protocol.flush()


if __name__ == '__main__':
    main()
