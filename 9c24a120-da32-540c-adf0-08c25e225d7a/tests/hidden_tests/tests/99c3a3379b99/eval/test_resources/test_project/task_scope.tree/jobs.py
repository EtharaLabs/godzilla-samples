import asyncio
from _pyfun_rt import _pf_scope
class _pf_Async:
    __slots__ = ("fn", "args")
    def __init__(self, fn, *args):
        self.fn = fn
        self.args = args
    def __await__(self):
        return self.fn(*self.args).__await__()
    async def __call__(self):
        return await self
    def __repr__(self):
        return "<Async>"
async def _pf_run(a):
    return await a
def _pf_task_start(c):
    _pf_scope.get().create_task(_pf_run(c))
    return None
def worker(name):
    async def _pf_fn0():
        await asyncio.sleep(0.0)
        _ = print(name)
    return _pf_Async(_pf_fn0)
def launch(name):
    return _pf_task_start(worker(name))
