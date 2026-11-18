import asyncio
import jobs
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
def _pf_task_scope(body):
    async def run():
        async def scoped():
            async with asyncio.TaskGroup() as tg:
                _pf_scope.set(tg)
                return await body
        return await asyncio.create_task(scoped())
    return _pf_Async(run)
runAsync = lambda _pf_p0: asyncio.run(_pf_run(_pf_p0))
async def _pf_fn0():
    _ = jobs.launch("x")
    _ = jobs.launch("y")
    return 7
session = _pf_task_scope(_pf_Async(_pf_fn0))
print(asyncio.run(_pf_run(session)))
