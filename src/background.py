"""Bounded background workers; completion callbacks belong to the GUI thread."""
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, SimpleQueue


class BackgroundTasks:
    def __init__(self, workers=2):
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='Stintrix-task')
        self._completed = SimpleQueue()
        self._futures = set()
        self._closed = False

    def submit(self, work, done):
        """Called by the GUI. No worker may call Tk, including root.after()."""
        if self._closed:
            raise RuntimeError('Background tasks are closing')
        self._prune()

        def run():
            try:
                result, error = work(), None
            except Exception as exception:
                result, error = None, str(exception)
            self._completed.put((done, result, error))

        future = self._executor.submit(run)
        self._futures.add(future)
        return future

    def _prune(self):
        self._futures = {future for future in self._futures if not future.done()}

    @property
    def busy(self):
        self._prune()
        return bool(self._futures)

    def completions(self):
        """Drain on the owning thread; do not retain completed results/futures."""
        while True:
            try:
                yield self._completed.get_nowait()
            except Empty:
                break
        self._prune()

    def close(self):
        """Reject new work, but finish every queued write before process exit."""
        if not self._closed:
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=False)
