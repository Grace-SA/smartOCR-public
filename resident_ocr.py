"""Owned, bounded model workers; no shared service and no external network."""
import atexit
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import threading

ROOT = Path(__file__).resolve().parent


class ResidentWorker:
    def __init__(self, kind, python, environment):
        self.kind, self.python, self.environment = kind, python, environment
        self.process = None
        self.log = None
        self.lock = threading.Lock()
        atexit.register(self.close)

    def close(self):
        if self.process is not None:
            process, self.process = self.process, None
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()
        if self.log:
            self.log.close()
            self.log = None

    def request(self, payload, timeout=180):
        with self.lock:
            cold = self.process is None or self.process.poll() is not None
            if cold:
                self.close()
                directory = ROOT/'data/ensemble/logs'
                directory.mkdir(parents=True, exist_ok=True)
                self.log = (directory/f'resident-{self.kind}-{os.getpid()}.log').open('a')
                self.process = subprocess.Popen([str(self.python), '-u', str(ROOT/'scripts/resident_ocr_worker.py'), self.kind],
                                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                                env=self.environment, text=True, bufsize=1, start_new_session=True)
            try:
                self.process.stdin.write(json.dumps(payload)+'\n')
                self.process.stdin.flush()
                if not select.select([self.process.stdout], [], [], timeout)[0]:
                    raise TimeoutError(f'{self.kind} worker exceeded {timeout}s')
                line = self.process.stdout.readline()
                if not line:
                    raise RuntimeError(f'{self.kind} worker exited; see local worker log')
                result = json.loads(line)
                if not result.get('ok'):
                    raise RuntimeError(result.get('error', 'Worker failed'))
                return {**result, 'worker_cold_start': cold}
            except Exception:
                self.close()
                raise


_workers = {}
_registry_lock = threading.Lock()


def request(stage, payload, timeout=180):
    from ocr_ensemble import PYTHONS, environment
    kind = 'unlimited' if stage == 'unlimited' else 'cpu'
    with _registry_lock:
        if kind not in _workers:
            _workers[kind] = ResidentWorker(kind, PYTHONS['unlimited' if kind == 'unlimited' else 'paddle'], environment())
        worker = _workers[kind]
    return worker.request({'stage': stage, **payload}, timeout=timeout)
