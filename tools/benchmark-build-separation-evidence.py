#
#  SPDX-License-Identifier: Apache-2.0
#
#  Copyright The original authors
#
#  Licensed under the Apache Software License version 2.0, available at http://www.apache.org/licenses/LICENSE-2.0
#

"""Fork-only evidence for serialized-build baseline versus isolated measurement."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

OUT = Path('benchmark-evidence')
OUT.mkdir(exist_ok=True)


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='microseconds')


def inventory(hashes):
    result = []
    root = Path('performance-testing/test-data-setup/target')
    for folder in ('tlc-trip-record-data', 'overture-maps-data'):
        for path in sorted((root / folder).glob('*.parquet')):
            item = {'path': str(path), 'bytes': path.stat().st_size}
            if hashes:
                with path.open('rb') as stream:
                    item['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
            result.append(item)
    return result


def observe(stop):
    """Sample JVM identity and named reader threads; no attach/JFR operations."""
    with (OUT / 'processes.jsonl').open('w') as stream:
        while not stop.is_set():
            observed = []
            for proc in Path('/proc').glob('[0-9]*'):
                try:
                    args = (proc / 'cmdline').read_bytes().split(b'\0')
                    if not args or Path(args[0].decode()).name != 'java':
                        continue
                    stat = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
                    names = [(task / 'comm').read_text().strip()
                             for task in (proc / 'task').iterdir()]
                    observed.append({
                        'pid': int(proc.name), 'start_ticks': int(stat[19]),
                        'command': [arg.decode(errors='replace') for arg in args if arg],
                        'hardwood_threads': sorted(name for name in names if name.startswith('hardwood-')),
                        'thread_count': len(names),
                    })
                except (OSError, ValueError, ProcessLookupError):
                    continue
            stream.write(json.dumps({'timestamp': timestamp(), 'jvms': observed}) + '\n')
            stream.flush()
            stop.wait(0.5)


def main():
    arm = os.environ['EXPERIMENT_ARM']
    assert arm in ('before', 'after')
    if os.environ.get('EXPERIMENT_DEBUG') == 'true':
        os.environ['MAVEN_ARGS'] = '-X'
    command = ['./mvnw', '-B', 'verify', '-Pperformance-test', '-pl', ':hardwood-performance-testing', '-amd',
                '-Dperf.start=' + os.environ['PERF_START'],
                '-Dperf.end=' + os.environ['PERF_END'], '-Dperf.runs=5',
                '-Dtest=FlatPerformanceTest,NestedPerformanceTest',
                '-Dsurefire.failIfNoSpecifiedTests=false', '-DforkCount=1', '-DreuseForks=false']
    commands = [command] if arm == 'before' else [
        ['bash', 'performance-testing/run-end-to-end.sh', 'prepare'],
        ['bash', 'performance-testing/run-end-to-end.sh', 'measure']]
    metadata = {
        'product_revision': '66c4a62d9f258d52f7e8c0a0a73c721b69f0fbe2',
        'product_core_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD:core'], text=True).strip(),
        'protocol': 'serialized-build-v1' if arm == 'before' else 'e2e-build-separated-v2',
        'arm': arm, 'pair': os.environ['EXPERIMENT_PAIR'],
        'ordinal': os.environ['EXPERIMENT_ORDINAL'],
        'commands': commands, 'start': timestamp(),
        'environment': {key: os.environ.get(key) for key in (
            'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'RUNNER_OS',
            'RUNNER_ARCH', 'ImageOS', 'ImageVersion', 'MAVEN_OPTS')},
        'java_version': subprocess.run(['java', '-version'], capture_output=True, text=True).stderr,
        'cpu': subprocess.check_output(['lscpu'], text=True),
        'memory': Path('/proc/meminfo').read_text(),
        'files_before': None,
    }
    (OUT / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    stop = threading.Event()
    observer = threading.Thread(target=observe, args=(stop,), daemon=True)
    observer.start()
    try:
        with (OUT / 'performance.log').open('w') as log:
            code = 0
            for command in commands:
                log.write(timestamp() + ' COMMAND ' + json.dumps(command) + '\n')
                proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1)
                for line in proc.stdout:
                    if metadata['files_before'] is None and '[INFO] Running dev.hardwood.perf.' in line:
                        metadata['files_before'] = inventory(False)
                    line = timestamp() + ' ' + line
                    log.write(line)
                    print(line, end='', flush=True)
                code = proc.wait()
                if code:
                    break
    finally:
        stop.set()
        observer.join()
    metadata.update(end=timestamp(), exit_code=code, files_after=inventory(True))
    (OUT / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
