"""Standalone source embedded-API load/export stress check for issue #223.

Run from the workspace, with rebuilt native extensions (no mocks):
  .venv\\Scripts\\python.exe tests\\embed_transport_integration.py --iterations 100

Uses the real startup pipe and authenticated local socket. A harness timeout is
only a test watchdog, never a production workaround. Temporary files stay under
this workspace and are removed on success/failure.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['VEUSZ_RESOURCE_DIR'] = str(ROOT)
# The child executes veusz/veusz_main.py, so it needs the package's parent on
# sys.path as well; editing this process's sys.path alone is not inherited.
os.environ['PYTHONPATH'] = str(ROOT) + os.pathsep + os.environ.get('PYTHONPATH', '')

from veusz import embed, qtall  # load Qt DLLs before the native helpers
from veusz.helpers import qtloops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--disconnect-test', action='store_true')
    args = parser.parse_args()
    if args.iterations < 1 or args.workers < 1:
        parser.error('iterations and workers must be positive')
    print('Python:', sys.executable, flush=True)
    print('Source:', embed.__file__, flush=True)
    print('Native:', qtloops.__file__, flush=True)
    remote = None
    terminated_for_test = False
    try:
        with tempfile.TemporaryDirectory(prefix='embed-223-', dir=ROOT / 'tests') as tmp:
            tmp = Path(tmp)
            graph = embed.Embedded('transport regression', hidden=True, debug=True)
            remote = embed.Embedded.remote
            print('Remote:', remote.args, flush=True)
            graph.SetUpdateInterval(0)
            graph.Add('page', name='page1')
            graph.To('/page1')
            graph.Add('graph', name='graph1')
            graph.To('graph1')
            graph.SetData('x', list(range(200)))
            graph.SetData('y', [x*x for x in range(200)])
            graph.Add('xy', xData='x', yData='y')
            source = tmp / 'fixture.vsz'
            graph.Save(str(source))
            graphs = [graph]
            for worker in range(1, args.workers):
                other = embed.Embedded('transport worker %i' % worker, hidden=True)
                other.SetUpdateInterval(0)
                graphs.append(other)

            def exercise(item):
                worker, window = item
                for index in range(args.iterations):
                    window.Load(str(source))
                    # Each worker uses its own window and output files, but
                    # all windows share the same authenticated TCP stream.
                    for extension in ('png', 'svg'):
                        target = tmp / ('output-%i.%s' % (worker, extension))
                        window.Export(str(target))
                        assert target.stat().st_size > 0
                    assert len(window.GetData('x')[0]) == 200
                    if (index + 1) % 50 == 0:
                        print('Worker %i completed %i loads / %i exports' %
                              (worker, index + 1, 2*(index + 1)), flush=True)

            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                list(pool.map(exercise, enumerate(graphs)))
            if args.disconnect_test:
                # Fault injection: a dead peer must raise, never spin on EOF.
                terminated_for_test = True
                remote.terminate()
                remote.wait(timeout=15)
                try:
                    graph.IsClosed()
                except OSError as exc:
                    print('PASS: dead remote detected:', type(exc).__name__, flush=True)
                else:
                    raise AssertionError('Dead remote unexpectedly answered')
            else:
                for window in graphs:
                    window.Close()
        print('PASS: %i workers, %i loads, %i exports' %
              (args.workers, args.workers*args.iterations,
               args.workers*args.iterations*2), flush=True)
    finally:
        if remote is not None:
            embed.Embedded.exitQt()
            # A test cleanup watchdog, not a timeout in the embedded protocol.
            try:
                remote.wait(timeout=15)
            except Exception:
                remote.kill()
                remote.wait()
                raise
            if not terminated_for_test:
                assert remote.returncode == 0, remote.returncode


if __name__ == '__main__':
    main()
