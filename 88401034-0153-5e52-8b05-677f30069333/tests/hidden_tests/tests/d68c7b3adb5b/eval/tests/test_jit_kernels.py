"""Classic V8 benchmark kernels and Richards scheduler perturbations on every tier.

docs/optimizer.md describes how the ARM64 template JIT specialises the hot shapes of the classic
V8 benchmarks: the Richards scheduler loop (`schedule()` with the inlined `isHeldOrSuspended`
predicate, `currentTcb = currentTcb.link`, the per-role `task.run(packet)` dispatch, Idle release,
Device hold/queue, Handler delivery and the linked `Packet.addTo` scan), numeric diamonds such as
the Worker fill loop, and register-resident numeric chains over dense arrays.  Each test runs a
scaled-down but faithful kernel long enough for the hot functions to be compiled and recompiled
with their callees inlined, then prints deterministic results.  The perturbation tests change a
running program under the JIT's guarded fast paths (replaced methods, prototype swaps, accessor
links, deleted packet fields, null/undefined alternation, global constants, thrown errors) and
must still match the tree-walking interpreter, which pins the reference semantics through one
golden shared by all three tiers.
"""

import pytest

from conftest import out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]


def check(js, golden, name, code, tier):
    r = js(code, *tier)
    assert out(r) == golden(name)
    assert (r.returncode, r.stderr) == (0, b"")


# The V8 benchmark suite's richards.js (minus the BenchmarkSuite harness and its final check).
RICHARDS = r"""
function runRichards() {
  var scheduler = new Scheduler();
  scheduler.addIdleTask(ID_IDLE, 0, null, COUNT);

  var queue = new Packet(null, ID_WORKER, KIND_WORK);
  queue = new Packet(queue,  ID_WORKER, KIND_WORK);
  scheduler.addWorkerTask(ID_WORKER, 1000, queue);

  queue = new Packet(null, ID_DEVICE_A, KIND_DEVICE);
  queue = new Packet(queue,  ID_DEVICE_A, KIND_DEVICE);
  queue = new Packet(queue,  ID_DEVICE_A, KIND_DEVICE);
  scheduler.addHandlerTask(ID_HANDLER_A, 2000, queue);

  queue = new Packet(null, ID_DEVICE_B, KIND_DEVICE);
  queue = new Packet(queue,  ID_DEVICE_B, KIND_DEVICE);
  queue = new Packet(queue,  ID_DEVICE_B, KIND_DEVICE);
  scheduler.addHandlerTask(ID_HANDLER_B, 3000, queue);

  scheduler.addDeviceTask(ID_DEVICE_A, 4000, null);

  scheduler.addDeviceTask(ID_DEVICE_B, 5000, null);

  scheduler.schedule();
  return scheduler;
}

var COUNT = 1000;
var EXPECTED_QUEUE_COUNT = 2322;
var EXPECTED_HOLD_COUNT = 928;

var ID_IDLE       = 0;
var ID_WORKER     = 1;
var ID_HANDLER_A  = 2;
var ID_HANDLER_B  = 3;
var ID_DEVICE_A   = 4;
var ID_DEVICE_B   = 5;
var NUMBER_OF_IDS = 6;

var KIND_DEVICE   = 0;
var KIND_WORK     = 1;

function Scheduler() {
  this.queueCount = 0;
  this.holdCount = 0;
  this.blocks = new Array(NUMBER_OF_IDS);
  this.list = null;
  this.currentTcb = null;
  this.currentId = null;
}

Scheduler.prototype.addIdleTask = function (id, priority, queue, count) {
  this.addRunningTask(id, priority, queue, new IdleTask(this, 1, count));
};

Scheduler.prototype.addWorkerTask = function (id, priority, queue) {
  this.addTask(id, priority, queue, new WorkerTask(this, ID_HANDLER_A, 0));
};

Scheduler.prototype.addHandlerTask = function (id, priority, queue) {
  this.addTask(id, priority, queue, new HandlerTask(this));
};

Scheduler.prototype.addDeviceTask = function (id, priority, queue) {
  this.addTask(id, priority, queue, new DeviceTask(this))
};

Scheduler.prototype.addRunningTask = function (id, priority, queue, task) {
  this.addTask(id, priority, queue, task);
  this.currentTcb.setRunning();
};

Scheduler.prototype.addTask = function (id, priority, queue, task) {
  this.currentTcb = new TaskControlBlock(this.list, id, priority, queue, task);
  this.list = this.currentTcb;
  this.blocks[id] = this.currentTcb;
};

Scheduler.prototype.schedule = function () {
  this.currentTcb = this.list;
  while (this.currentTcb != null) {
    if (this.currentTcb.isHeldOrSuspended()) {
      this.currentTcb = this.currentTcb.link;
    } else {
      this.currentId = this.currentTcb.id;
      this.currentTcb = this.currentTcb.run();
    }
  }
};

Scheduler.prototype.release = function (id) {
  var tcb = this.blocks[id];
  if (tcb == null) return tcb;
  tcb.markAsNotHeld();
  if (tcb.priority > this.currentTcb.priority) {
    return tcb;
  } else {
    return this.currentTcb;
  }
};

Scheduler.prototype.holdCurrent = function () {
  this.holdCount++;
  this.currentTcb.markAsHeld();
  return this.currentTcb.link;
};

Scheduler.prototype.suspendCurrent = function () {
  this.currentTcb.markAsSuspended();
  return this.currentTcb;
};

Scheduler.prototype.queue = function (packet) {
  var t = this.blocks[packet.id];
  if (t == null) return t;
  this.queueCount++;
  packet.link = null;
  packet.id = this.currentId;
  return t.checkPriorityAdd(this.currentTcb, packet);
};

function TaskControlBlock(link, id, priority, queue, task) {
  this.link = link;
  this.id = id;
  this.priority = priority;
  this.queue = queue;
  this.task = task;
  if (queue == null) {
    this.state = STATE_SUSPENDED;
  } else {
    this.state = STATE_SUSPENDED_RUNNABLE;
  }
}

var STATE_RUNNING = 0;
var STATE_RUNNABLE = 1;
var STATE_SUSPENDED = 2;
var STATE_HELD = 4;
var STATE_SUSPENDED_RUNNABLE = STATE_SUSPENDED | STATE_RUNNABLE;
var STATE_NOT_HELD = ~STATE_HELD;

TaskControlBlock.prototype.setRunning = function () {
  this.state = STATE_RUNNING;
};

TaskControlBlock.prototype.markAsNotHeld = function () {
  this.state = this.state & STATE_NOT_HELD;
};

TaskControlBlock.prototype.markAsHeld = function () {
  this.state = this.state | STATE_HELD;
};

TaskControlBlock.prototype.isHeldOrSuspended = function () {
  return (this.state & STATE_HELD) != 0 || (this.state == STATE_SUSPENDED);
};

TaskControlBlock.prototype.markAsSuspended = function () {
  this.state = this.state | STATE_SUSPENDED;
};

TaskControlBlock.prototype.markAsRunnable = function () {
  this.state = this.state | STATE_RUNNABLE;
};

TaskControlBlock.prototype.run = function () {
  var packet;
  if (this.state == STATE_SUSPENDED_RUNNABLE) {
    packet = this.queue;
    this.queue = packet.link;
    if (this.queue == null) {
      this.state = STATE_RUNNING;
    } else {
      this.state = STATE_RUNNABLE;
    }
  } else {
    packet = null;
  }
  return this.task.run(packet);
};

TaskControlBlock.prototype.checkPriorityAdd = function (task, packet) {
  if (this.queue == null) {
    this.queue = packet;
    this.markAsRunnable();
    if (this.priority > task.priority) return this;
  } else {
    this.queue = packet.addTo(this.queue);
  }
  return task;
};

TaskControlBlock.prototype.toString = function () {
  return "tcb { " + this.task + "@" + this.state + " }";
};

function IdleTask(scheduler, v1, count) {
  this.scheduler = scheduler;
  this.v1 = v1;
  this.count = count;
}

IdleTask.prototype.run = function (packet) {
  this.count--;
  if (this.count == 0) return this.scheduler.holdCurrent();
  if ((this.v1 & 1) == 0) {
    this.v1 = this.v1 >> 1;
    return this.scheduler.release(ID_DEVICE_A);
  } else {
    this.v1 = (this.v1 >> 1) ^ 0xD008;
    return this.scheduler.release(ID_DEVICE_B);
  }
};

IdleTask.prototype.toString = function () {
  return "IdleTask"
};

function DeviceTask(scheduler) {
  this.scheduler = scheduler;
  this.v1 = null;
}

DeviceTask.prototype.run = function (packet) {
  if (packet == null) {
    if (this.v1 == null) return this.scheduler.suspendCurrent();
    var v = this.v1;
    this.v1 = null;
    return this.scheduler.queue(v);
  } else {
    this.v1 = packet;
    return this.scheduler.holdCurrent();
  }
};

DeviceTask.prototype.toString = function () {
  return "DeviceTask";
};

function WorkerTask(scheduler, v1, v2) {
  this.scheduler = scheduler;
  this.v1 = v1;
  this.v2 = v2;
}

WorkerTask.prototype.run = function (packet) {
  if (packet == null) {
    return this.scheduler.suspendCurrent();
  } else {
    if (this.v1 == ID_HANDLER_A) {
      this.v1 = ID_HANDLER_B;
    } else {
      this.v1 = ID_HANDLER_A;
    }
    packet.id = this.v1;
    packet.a1 = 0;
    for (var i = 0; i < DATA_SIZE; i++) {
      this.v2++;
      if (this.v2 > 26) this.v2 = 1;
      packet.a2[i] = this.v2;
    }
    return this.scheduler.queue(packet);
  }
};

WorkerTask.prototype.toString = function () {
  return "WorkerTask";
};

function HandlerTask(scheduler) {
  this.scheduler = scheduler;
  this.v1 = null;
  this.v2 = null;
}

HandlerTask.prototype.run = function (packet) {
  if (packet != null) {
    if (packet.kind == KIND_WORK) {
      this.v1 = packet.addTo(this.v1);
    } else {
      this.v2 = packet.addTo(this.v2);
    }
  }
  if (this.v1 != null) {
    var count = this.v1.a1;
    var v;
    if (count < DATA_SIZE) {
      if (this.v2 != null) {
        v = this.v2;
        this.v2 = this.v2.link;
        v.a1 = this.v1.a2[count];
        this.v1.a1 = count + 1;
        return this.scheduler.queue(v);
      }
    } else {
      v = this.v1;
      this.v1 = this.v1.link;
      return this.scheduler.queue(v);
    }
  }
  return this.scheduler.suspendCurrent();
};

HandlerTask.prototype.toString = function () {
  return "HandlerTask";
};

var DATA_SIZE = 4;

function Packet(link, id, kind) {
  this.link = link;
  this.id = id;
  this.kind = kind;
  this.a1 = 0;
  this.a2 = new Array(DATA_SIZE);
}

Packet.prototype.addTo = function (queue) {
  this.link = null;
  if (queue == null) return this;
  var peek, next = queue;
  while ((peek = next.link) != null)
    next = peek;
  next.link = this;
  return queue;
};

Packet.prototype.toString = function () {
  return "Packet";
};
"""

WARMUP = r"""
// Get schedule() and the task methods compiled, then recompiled with their callees inlined: real
// runs warm every role, direct holdCurrent calls warm the hold helper, and cheap re-schedules of a
// finished (all held or suspended) scheduler reach schedule()'s recompilation threshold.
function warmup(first, small) {
  var s, acc = 0;
  COUNT = first;
  s = runRichards();
  acc = s.queueCount * 3 + s.holdCount;
  for (var i = 0; i < 9; i++) {
    COUNT = small;
    s = runRichards();
    acc = (acc * 31 + s.queueCount * 3 + s.holdCount) % 1000003;
  }
  for (var k = 0; k < 110; k++) {
    s.currentTcb = s.blocks[k % 2 ? ID_DEVICE_A : ID_DEVICE_B];
    s.holdCurrent();
  }
  s.currentTcb = null;
  for (var j = 0; j < 80; j++) s.schedule();
  for (var i = 0; i < 25; i++) {
    COUNT = small + (i % 3);
    s = runRichards();
    acc = (acc * 31 + s.queueCount * 3 + s.holdCount) % 1000003;
  }
  return acc + "/" + s.queueCount + "/" + s.holdCount;
}
"""

# Helpers for the perturbation drivers: an un-run scheduler, the shared warm-up, a state summary, and a one-shot trigger that
# fires from inside a running schedule() through an accessor on one handler packet's `kind`.
HARNESS = r"""
function buildScheduler(count) {
  var scheduler = new Scheduler();
  scheduler.addIdleTask(ID_IDLE, 0, null, count);
  var queue = new Packet(null, ID_WORKER, KIND_WORK);
  queue = new Packet(queue, ID_WORKER, KIND_WORK);
  scheduler.addWorkerTask(ID_WORKER, 1000, queue);
  queue = new Packet(null, ID_DEVICE_A, KIND_DEVICE);
  queue = new Packet(queue, ID_DEVICE_A, KIND_DEVICE);
  queue = new Packet(queue, ID_DEVICE_A, KIND_DEVICE);
  scheduler.addHandlerTask(ID_HANDLER_A, 2000, queue);
  queue = new Packet(null, ID_DEVICE_B, KIND_DEVICE);
  queue = new Packet(queue, ID_DEVICE_B, KIND_DEVICE);
  queue = new Packet(queue, ID_DEVICE_B, KIND_DEVICE);
  scheduler.addHandlerTask(ID_HANDLER_B, 3000, queue);
  scheduler.addDeviceTask(ID_DEVICE_A, 4000, null);
  scheduler.addDeviceTask(ID_DEVICE_B, 5000, null);
  return scheduler;
}
function warm() { return warmup(120, 4); }
function summary(s) {
  var parts = [];
  for (var id = 0; id < NUMBER_OF_IDS; id++) {
    var t = s.blocks[id];
    var q = 0; for (var p = t.queue; p != null; p = p.link) q++;
    parts.push(id + ":" + t.state + "/" + q);
  }
  return "q=" + s.queueCount + " h=" + s.holdCount + " cur=" + s.currentId + " [" + parts.join(" ") + "]";
}
// Run a schedule with a one-shot trigger: after `after` reads of a device packet's kind, call fn().
function scheduleWithTrigger(count, after, fn) {
  var s = buildScheduler(count), reads = 0, fired = false;
  var pk = s.blocks[ID_HANDLER_A].queue;
  var kind = pk.kind;
  Object.defineProperty(pk, "kind", { get: function () { if (++reads === after && !fired) { fired = true; fn(s); } return kind; }, set: function (v) { kind = v; }, configurable: true, enumerable: true });
  s.schedule();
  return summary(s) + " reads=" + reads;
}
"""

# Semantics-preserving rewrites of individual Richards methods (old text, new text). The scheduler
# planners match exact bytecode shapes, so each rewrite forces a different partial plan.
DIALECTS = {
    "hold": (
        r"""
Scheduler.prototype.holdCurrent = function () {
  this.holdCount++;
  this.currentTcb.markAsHeld();
  return this.currentTcb.link;
};
""",
        r"""
Scheduler.prototype.holdCurrent = function () {
  var tcb = this.currentTcb;
  this.holdCount = this.holdCount + 1;
  tcb.markAsHeld();
  return tcb.link;
};
""",
    ),
    "suspend": (
        r"""
Scheduler.prototype.suspendCurrent = function () {
  this.currentTcb.markAsSuspended();
  return this.currentTcb;
};
""",
        r"""
Scheduler.prototype.suspendCurrent = function () {
  var tcb = this.currentTcb;
  tcb.markAsSuspended();
  return tcb;
};
""",
    ),
    "addto": (
        r"""
Packet.prototype.addTo = function (queue) {
  this.link = null;
  if (queue == null) return this;
  var peek, next = queue;
  while ((peek = next.link) != null)
    next = peek;
  next.link = this;
  return queue;
};
""",
        r"""
Packet.prototype.addTo = function (queue) {
  this.link = null;
  if (queue == null) return this;
  var next = queue;
  while (next.link != null) next = next.link;
  next.link = this;
  return queue;
};
""",
    ),
    "check": (
        r"""
TaskControlBlock.prototype.checkPriorityAdd = function (task, packet) {
  if (this.queue == null) {
    this.queue = packet;
    this.markAsRunnable();
    if (this.priority > task.priority) return this;
  } else {
    this.queue = packet.addTo(this.queue);
  }
  return task;
};
""",
        r"""
TaskControlBlock.prototype.checkPriorityAdd = function (task, packet) {
  if (this.queue != null) {
    this.queue = packet.addTo(this.queue);
    return task;
  }
  this.queue = packet;
  this.markAsRunnable();
  return this.priority > task.priority ? this : task;
};
""",
    ),
    "worker": (
        r"""
    for (var i = 0; i < DATA_SIZE; i++) {
      this.v2++;
      if (this.v2 > 26) this.v2 = 1;
      packet.a2[i] = this.v2;
    }
""",
        r"""
    for (var i = 0; i < DATA_SIZE; i++) {
      this.v2 = this.v2 + 1;
      if (this.v2 > 26) { this.v2 = 1; }
      packet.a2[i] = this.v2;
    }
""",
    ),
}


def richards_dialect(*names):
    src = RICHARDS
    for name in names:
        old, new = DIALECTS[name]
        assert old in src
        src = src.replace(old, new)
    return src


DIALECT_DRIVER = r"""
console.log("warmup " + warmup(120, 4));
COUNT = 200;
var s = runRichards();
var states = [];
for (var id = 0; id < NUMBER_OF_IDS; id++) states.push(String(s.blocks[id]));
console.log("reference " + s.queueCount + "/" + s.holdCount + " " + states.join(" "));
"""

WARM_QUEUE = r"""
// Warm Scheduler.queue on its own so it is recompiled with checkPriorityAdd/markAsRunnable inlined.
function warmQueue(n) {
  var acc = 0;
  for (var i = 0; i < n; i++) {
    var s = new Scheduler();
    s.addHandlerTask(ID_HANDLER_A, 2000, null);
    s.addWorkerTask(ID_WORKER, 1000, null);
    s.currentId = ID_WORKER;
    var r = s.queue(new Packet(null, ID_HANDLER_A, KIND_WORK));
    if (i & 1) s.queue(new Packet(null, ID_HANDLER_A, KIND_WORK));
    acc += (r === s.blocks[ID_HANDLER_A] ? 1 : 0) + s.queueCount + s.blocks[ID_HANDLER_A].state;
  }
  return acc;
}
console.log("warm queue " + warmQueue(150));
"""

# Scaled-down navier-stokes.js FluidField; storage comes from a caller-supplied allocator.
NAVIER = r"""
// Scaled-down NavierStokes (V8 benchmark suite, after Oliver Hunt / Jos Stam's solver).
function FluidField(width, height, alloc) {
  function addFields(x, s, dt) {
    for (var i = 0; i < size; i++) x[i] += dt * s[i];
  }
  function set_bnd(b, x) {
    if (b === 1) {
      for (var i = 1; i <= width; i++) {
        x[i] = x[i + rowSize];
        x[i + (height + 1) * rowSize] = x[i + height * rowSize];
      }
      for (var j = 1; j <= height; j++) {
        x[j * rowSize] = -x[1 + j * rowSize];
        x[(width + 1) + j * rowSize] = -x[width + j * rowSize];
      }
    } else if (b === 2) {
      for (var i = 1; i <= width; i++) {
        x[i] = -x[i + rowSize];
        x[i + (height + 1) * rowSize] = -x[i + height * rowSize];
      }
      for (var j = 1; j <= height; j++) {
        x[j * rowSize] = x[1 + j * rowSize];
        x[(width + 1) + j * rowSize] = x[width + j * rowSize];
      }
    } else {
      for (var i = 1; i <= width; i++) {
        x[i] = x[i + rowSize];
        x[i + (height + 1) * rowSize] = x[i + height * rowSize];
      }
      for (var j = 1; j <= height; j++) {
        x[j * rowSize] = x[1 + j * rowSize];
        x[(width + 1) + j * rowSize] = x[width + j * rowSize];
      }
    }
    var maxEdge = (height + 1) * rowSize;
    x[0] = 0.5 * (x[1] + x[rowSize]);
    x[maxEdge] = 0.5 * (x[1 + maxEdge] + x[height * rowSize]);
    x[(width + 1)] = 0.5 * (x[width] + x[(width + 1) + rowSize]);
    x[(width + 1) + maxEdge] = 0.5 * (x[width + maxEdge] + x[(width + 1) + height * rowSize]);
  }
  function lin_solve(b, x, x0, a, c) {
    if (a === 0 && c === 1) {
      for (var j = 1; j <= height; j++) {
        var currentRow = j * rowSize;
        ++currentRow;
        for (var i = 0; i < width; i++) {
          x[currentRow] = x0[currentRow];
          ++currentRow;
        }
      }
      set_bnd(b, x);
    } else {
      var invC = 1 / c;
      for (var k = 0; k < iterations; k++) {
        for (var j = 1; j <= height; j++) {
          var lastRow = (j - 1) * rowSize;
          var currentRow = j * rowSize;
          var nextRow = (j + 1) * rowSize;
          var lastX = x[currentRow];
          ++currentRow;
          for (var i = 1; i <= width; i++)
            lastX = x[currentRow] = (x0[currentRow] + a * (lastX + x[++currentRow] + x[++lastRow] + x[++nextRow])) * invC;
        }
        set_bnd(b, x);
      }
    }
  }
  function diffuse(b, x, x0, dt) {
    var a = 0;
    lin_solve(b, x, x0, a, 1 + 4 * a);
  }
  function lin_solve2(x, x0, y, y0, a, c) {
    if (a === 0 && c === 1) {
      for (var j = 1; j <= height; j++) {
        var currentRow = j * rowSize;
        ++currentRow;
        for (var i = 0; i < width; i++) {
          x[currentRow] = x0[currentRow];
          y[currentRow] = y0[currentRow];
          ++currentRow;
        }
      }
      set_bnd(1, x);
      set_bnd(2, y);
    } else {
      var invC = 1 / c;
      for (var k = 0; k < iterations; k++) {
        for (var j = 1; j <= height; j++) {
          var lastRow = (j - 1) * rowSize;
          var currentRow = j * rowSize;
          var nextRow = (j + 1) * rowSize;
          var lastX = x[currentRow];
          var lastY = y[currentRow];
          ++currentRow;
          for (var i = 1; i <= width; i++) {
            lastX = x[currentRow] = (x0[currentRow] + a * (lastX + x[currentRow] + x[lastRow] + x[nextRow])) * invC;
            lastY = y[currentRow] = (y0[currentRow] + a * (lastY + y[++currentRow] + y[++lastRow] + y[++nextRow])) * invC;
          }
        }
        set_bnd(1, x);
        set_bnd(2, y);
      }
    }
  }
  function diffuse2(x, x0, y, y0, dt) {
    var a = 0;
    lin_solve2(x, x0, y, y0, a, 1 + 4 * a);
  }
  function advect(b, d, d0, u, v, dt) {
    var Wdt0 = dt * width;
    var Hdt0 = dt * height;
    var Wp5 = width + 0.5;
    var Hp5 = height + 0.5;
    for (var j = 1; j <= height; j++) {
      var pos = j * rowSize;
      for (var i = 1; i <= width; i++) {
        var x = i - Wdt0 * u[++pos];
        var y = j - Hdt0 * v[pos];
        if (x < 0.5) x = 0.5;
        else if (x > Wp5) x = Wp5;
        var i0 = x | 0;
        var i1 = i0 + 1;
        if (y < 0.5) y = 0.5;
        else if (y > Hp5) y = Hp5;
        var j0 = y | 0;
        var j1 = j0 + 1;
        var s1 = x - i0;
        var s0 = 1 - s1;
        var t1 = y - j0;
        var t0 = 1 - t1;
        var row1 = j0 * rowSize;
        var row2 = j1 * rowSize;
        d[pos] = s0 * (t0 * d0[i0 + row1] + t1 * d0[i0 + row2]) + s1 * (t0 * d0[i1 + row1] + t1 * d0[i1 + row2]);
      }
    }
    set_bnd(b, d);
  }
  function project(u, v, p, div) {
    var h = -0.5 / Math.sqrt(width * height);
    for (var j = 1; j <= height; j++) {
      var row = j * rowSize;
      var previousRow = (j - 1) * rowSize;
      var prevValue = row - 1;
      var currentRow = row;
      var nextValue = row + 1;
      var nextRow = (j + 1) * rowSize;
      for (var i = 1; i <= width; i++) {
        div[++currentRow] = h * (u[++nextValue] - u[++prevValue] + v[++nextRow] - v[++previousRow]);
        p[currentRow] = 0;
      }
    }
    set_bnd(0, div);
    set_bnd(0, p);
    lin_solve(0, p, div, 1, 4);
    var wScale = 0.5 * width;
    var hScale = 0.5 * height;
    for (var j = 1; j <= height; j++) {
      var prevPos = j * rowSize - 1;
      var currentPos = j * rowSize;
      var nextPos = j * rowSize + 1;
      var prevRow = (j - 1) * rowSize;
      var currentRow = j * rowSize;
      var nextRow = (j + 1) * rowSize;
      for (var i = 1; i <= width; i++) {
        u[++currentPos] -= wScale * (p[++nextPos] - p[++prevPos]);
        v[currentPos] -= hScale * (p[++nextRow] - p[++prevRow]);
      }
    }
    set_bnd(1, u);
    set_bnd(2, v);
  }
  function dens_step(x, x0, u, v, dt) {
    addFields(x, x0, dt);
    diffuse(0, x0, x, dt);
    advect(0, x, x0, u, v, dt);
  }
  function vel_step(u, v, u0, v0, dt) {
    addFields(u, u0, dt);
    addFields(v, v0, dt);
    var temp = u0; u0 = u; u = temp;
    var temp = v0; v0 = v; v = temp;
    diffuse2(u, u0, v, v0, dt);
    project(u, v, u0, v0);
    var temp = u0; u0 = u; u = temp;
    var temp = v0; v0 = v; v = temp;
    advect(1, u, u0, u0, v0, dt);
    advect(2, v, v0, u0, v0, dt);
    project(u, v, u0, v0);
  }
  var uiCallback = function (d, u, v) { };
  function Field(dens, u, v) {
    this.setDensity = function (x, y, d) { dens[(x + 1) + (y + 1) * rowSize] = d; };
    this.getDensity = function (x, y) { return dens[(x + 1) + (y + 1) * rowSize]; };
    this.setVelocity = function (x, y, xv, yv) {
      u[(x + 1) + (y + 1) * rowSize] = xv;
      v[(x + 1) + (y + 1) * rowSize] = yv;
    };
    this.getXVelocity = function (x, y) { return u[(x + 1) + (y + 1) * rowSize]; };
    this.getYVelocity = function (x, y) { return v[(x + 1) + (y + 1) * rowSize]; };
    this.width = function () { return width; };
    this.height = function () { return height; };
  }
  function queryUI(d, u, v) {
    for (var i = 0; i < size; i++) u[i] = v[i] = d[i] = 0.0;
    uiCallback(new Field(d, u, v));
  }
  this.update = function () {
    queryUI(dens_prev, u_prev, v_prev);
    vel_step(u, v, u_prev, v_prev, dt);
    dens_step(dens, dens_prev, u, v, dt);
  };
  this.setUICallback = function (callback) { uiCallback = callback; };
  this.setIterations = function (iters) { iterations = iters; };
  this.dens = function () { return dens; };
  var iterations = 10;
  var dt = 0.1;
  var dens, dens_prev, u, u_prev, v, v_prev;
  var width = width, height = height;
  var rowSize = width + 2;
  var size = (width + 2) * (height + 2);
  dens = alloc(size); dens_prev = alloc(size);
  u = alloc(size); u_prev = alloc(size);
  v = alloc(size); v_prev = alloc(size);
}
"""

# Scaled-down deltablue.js (OrderedCollection, Strength, the constraint hierarchy and Planner).
DELTABLUE = r"""
// Scaled-down DeltaBlue (V8 benchmark suite) - one-way constraint solver.
Object.defineProperty(Object.prototype, "inheritsFrom", {
  value: function (shuper) {
    function Inheriter() { }
    Inheriter.prototype = shuper.prototype;
    this.prototype = new Inheriter();
    this.superConstructor = shuper;
  }, writable: true, configurable: true
});
function OrderedCollection() { this.elms = new Array(); }
OrderedCollection.prototype.add = function (elm) { this.elms.push(elm); };
OrderedCollection.prototype.at = function (index) { return this.elms[index]; };
OrderedCollection.prototype.size = function () { return this.elms.length; };
OrderedCollection.prototype.removeFirst = function () { return this.elms.pop(); };
OrderedCollection.prototype.remove = function (elm) {
  var index = 0, skipped = 0;
  for (var i = 0; i < this.elms.length; i++) {
    var value = this.elms[i];
    if (value != elm) { this.elms[index] = value; index++; } else { skipped++; }
  }
  for (var i = 0; i < skipped; i++) this.elms.pop();
};
function Strength(strengthValue, name) { this.strengthValue = strengthValue; this.name = name; }
Strength.stronger = function (s1, s2) { return s1.strengthValue < s2.strengthValue; };
Strength.weaker = function (s1, s2) { return s1.strengthValue > s2.strengthValue; };
Strength.weakestOf = function (s1, s2) { return this.weaker(s1, s2) ? s1 : s2; };
Strength.strongest = function (s1, s2) { return this.stronger(s1, s2) ? s1 : s2; };
Strength.prototype.nextWeaker = function () {
  switch (this.strengthValue) {
    case 0: return Strength.WEAKEST;
    case 1: return Strength.WEAK_DEFAULT;
    case 2: return Strength.NORMAL;
    case 3: return Strength.STRONG_DEFAULT;
    case 4: return Strength.PREFERRED;
    case 5: return Strength.REQUIRED;
  }
};
Strength.REQUIRED = new Strength(0, "required");
Strength.STRONG_PREFERRED = new Strength(1, "strongPreferred");
Strength.PREFERRED = new Strength(2, "preferred");
Strength.STRONG_DEFAULT = new Strength(3, "strongDefault");
Strength.NORMAL = new Strength(4, "normal");
Strength.WEAK_DEFAULT = new Strength(5, "weakDefault");
Strength.WEAKEST = new Strength(6, "weakest");
function Constraint(strength) { this.strength = strength; }
Constraint.prototype.addConstraint = function () { this.addToGraph(); planner.incrementalAdd(this); };
Constraint.prototype.satisfy = function (mark) {
  this.chooseMethod(mark);
  if (!this.isSatisfied()) {
    if (this.strength == Strength.REQUIRED) throw new Error("Could not satisfy a required constraint!");
    return null;
  }
  this.markInputs(mark);
  var out = this.output();
  var overridden = out.determinedBy;
  if (overridden != null) overridden.markUnsatisfied();
  out.determinedBy = this;
  if (!planner.addPropagate(this, mark)) throw new Error("Cycle encountered");
  out.mark = mark;
  return overridden;
};
Constraint.prototype.destroyConstraint = function () {
  if (this.isSatisfied()) planner.incrementalRemove(this);
  else this.removeFromGraph();
};
Constraint.prototype.isInput = function () { return false; };
function UnaryConstraint(v, strength) {
  UnaryConstraint.superConstructor.call(this, strength);
  this.myOutput = v;
  this.satisfied = false;
  this.addConstraint();
}
UnaryConstraint.inheritsFrom(Constraint);
UnaryConstraint.prototype.addToGraph = function () { this.myOutput.addConstraint(this); this.satisfied = false; };
UnaryConstraint.prototype.chooseMethod = function (mark) {
  this.satisfied = (this.myOutput.mark != mark) && Strength.stronger(this.strength, this.myOutput.walkStrength);
};
UnaryConstraint.prototype.isSatisfied = function () { return this.satisfied; };
UnaryConstraint.prototype.markInputs = function (mark) { };
UnaryConstraint.prototype.output = function () { return this.myOutput; };
UnaryConstraint.prototype.recalculate = function () {
  this.myOutput.walkStrength = this.strength;
  this.myOutput.stay = !this.isInput();
  if (this.myOutput.stay) this.execute();
};
UnaryConstraint.prototype.markUnsatisfied = function () { this.satisfied = false; };
UnaryConstraint.prototype.inputsKnown = function () { return true; };
UnaryConstraint.prototype.removeFromGraph = function () {
  if (this.myOutput != null) this.myOutput.removeConstraint(this);
  this.satisfied = false;
};
function StayConstraint(v, str) { StayConstraint.superConstructor.call(this, v, str); }
StayConstraint.inheritsFrom(UnaryConstraint);
StayConstraint.prototype.execute = function () { };
function EditConstraint(v, str) { EditConstraint.superConstructor.call(this, v, str); }
EditConstraint.inheritsFrom(UnaryConstraint);
EditConstraint.prototype.isInput = function () { return true; };
EditConstraint.prototype.execute = function () { };
var Direction = new Object();
Direction.NONE = 0; Direction.FORWARD = 1; Direction.BACKWARD = -1;
function BinaryConstraint(var1, var2, strength) {
  BinaryConstraint.superConstructor.call(this, strength);
  this.v1 = var1; this.v2 = var2;
  this.direction = Direction.NONE;
  this.addConstraint();
}
BinaryConstraint.inheritsFrom(Constraint);
BinaryConstraint.prototype.chooseMethod = function (mark) {
  if (this.v1.mark == mark) {
    this.direction = (this.v2.mark != mark && Strength.stronger(this.strength, this.v2.walkStrength)) ? Direction.FORWARD : Direction.NONE;
  }
  if (this.v2.mark == mark) {
    this.direction = (this.v1.mark != mark && Strength.stronger(this.strength, this.v1.walkStrength)) ? Direction.BACKWARD : Direction.NONE;
  }
  if (Strength.weaker(this.v1.walkStrength, this.v2.walkStrength)) {
    this.direction = Strength.stronger(this.strength, this.v1.walkStrength) ? Direction.BACKWARD : Direction.NONE;
  } else {
    this.direction = Strength.stronger(this.strength, this.v2.walkStrength) ? Direction.FORWARD : Direction.BACKWARD;
  }
};
BinaryConstraint.prototype.addToGraph = function () { this.v1.addConstraint(this); this.v2.addConstraint(this); this.direction = Direction.NONE; };
BinaryConstraint.prototype.isSatisfied = function () { return this.direction != Direction.NONE; };
BinaryConstraint.prototype.markInputs = function (mark) { this.input().mark = mark; };
BinaryConstraint.prototype.input = function () { return (this.direction == Direction.FORWARD) ? this.v1 : this.v2; };
BinaryConstraint.prototype.output = function () { return (this.direction == Direction.FORWARD) ? this.v2 : this.v1; };
BinaryConstraint.prototype.recalculate = function () {
  var ihn = this.input(), out = this.output();
  out.walkStrength = Strength.weakestOf(this.strength, ihn.walkStrength);
  out.stay = ihn.stay;
  if (out.stay) this.execute();
};
BinaryConstraint.prototype.markUnsatisfied = function () { this.direction = Direction.NONE; };
BinaryConstraint.prototype.inputsKnown = function (mark) {
  var i = this.input();
  return i.mark == mark || i.stay || i.determinedBy == null;
};
BinaryConstraint.prototype.removeFromGraph = function () {
  if (this.v1 != null) this.v1.removeConstraint(this);
  if (this.v2 != null) this.v2.removeConstraint(this);
  this.direction = Direction.NONE;
};
function ScaleConstraint(src, scale, offset, dest, strength) {
  this.direction = Direction.NONE;
  this.scale = scale;
  this.offset = offset;
  ScaleConstraint.superConstructor.call(this, src, dest, strength);
}
ScaleConstraint.inheritsFrom(BinaryConstraint);
ScaleConstraint.prototype.addToGraph = function () {
  ScaleConstraint.superConstructor.prototype.addToGraph.call(this);
  this.scale.addConstraint(this);
  this.offset.addConstraint(this);
};
ScaleConstraint.prototype.removeFromGraph = function () {
  ScaleConstraint.superConstructor.prototype.removeFromGraph.call(this);
  if (this.scale != null) this.scale.removeConstraint(this);
  if (this.offset != null) this.offset.removeConstraint(this);
};
ScaleConstraint.prototype.markInputs = function (mark) {
  ScaleConstraint.superConstructor.prototype.markInputs.call(this, mark);
  this.scale.mark = this.offset.mark = mark;
};
ScaleConstraint.prototype.execute = function () {
  if (this.direction == Direction.FORWARD) {
    this.v2.value = this.v1.value * this.scale.value + this.offset.value;
  } else {
    this.v1.value = (this.v2.value - this.offset.value) / this.scale.value;
  }
};
ScaleConstraint.prototype.recalculate = function () {
  var ihn = this.input(), out = this.output();
  out.walkStrength = Strength.weakestOf(this.strength, ihn.walkStrength);
  out.stay = ihn.stay && this.scale.stay && this.offset.stay;
  if (out.stay) this.execute();
};
function EqualityConstraint(var1, var2, strength) { EqualityConstraint.superConstructor.call(this, var1, var2, strength); }
EqualityConstraint.inheritsFrom(BinaryConstraint);
EqualityConstraint.prototype.execute = function () { this.output().value = this.input().value; };
function Variable(name, initialValue) {
  this.value = initialValue || 0;
  this.constraints = new OrderedCollection();
  this.determinedBy = null;
  this.mark = 0;
  this.walkStrength = Strength.WEAKEST;
  this.stay = true;
  this.name = name;
}
Variable.prototype.addConstraint = function (c) { this.constraints.add(c); };
Variable.prototype.removeConstraint = function (c) {
  this.constraints.remove(c);
  if (this.determinedBy == c) this.determinedBy = null;
};
function Planner() { this.currentMark = 0; }
Planner.prototype.incrementalAdd = function (c) {
  var mark = this.newMark();
  var overridden = c.satisfy(mark);
  while (overridden != null) overridden = overridden.satisfy(mark);
};
Planner.prototype.incrementalRemove = function (c) {
  var out = c.output();
  c.markUnsatisfied();
  c.removeFromGraph();
  var unsatisfied = this.removePropagateFrom(out);
  var strength = Strength.REQUIRED;
  do {
    for (var i = 0; i < unsatisfied.size(); i++) {
      var u = unsatisfied.at(i);
      if (u.strength == strength) this.incrementalAdd(u);
    }
    strength = strength.nextWeaker();
  } while (strength != Strength.WEAKEST);
};
Planner.prototype.newMark = function () { return ++this.currentMark; };
Planner.prototype.makePlan = function (sources) {
  var mark = this.newMark();
  var plan = new Plan();
  var todo = sources;
  while (todo.size() > 0) {
    var c = todo.removeFirst();
    if (c.output().mark != mark && c.inputsKnown(mark)) {
      plan.addConstraint(c);
      c.output().mark = mark;
      this.addConstraintsConsumingTo(c.output(), todo);
    }
  }
  return plan;
};
Planner.prototype.extractPlanFromConstraints = function (constraints) {
  var sources = new OrderedCollection();
  for (var i = 0; i < constraints.size(); i++) {
    var c = constraints.at(i);
    if (c.isInput() && c.isSatisfied()) sources.add(c);
  }
  return this.makePlan(sources);
};
Planner.prototype.addPropagate = function (c, mark) {
  var todo = new OrderedCollection();
  todo.add(c);
  while (todo.size() > 0) {
    var d = todo.removeFirst();
    if (d.output().mark == mark) { this.incrementalRemove(c); return false; }
    d.recalculate();
    this.addConstraintsConsumingTo(d.output(), todo);
  }
  return true;
};
Planner.prototype.removePropagateFrom = function (out) {
  out.determinedBy = null;
  out.walkStrength = Strength.WEAKEST;
  out.stay = true;
  var unsatisfied = new OrderedCollection();
  var todo = new OrderedCollection();
  todo.add(out);
  while (todo.size() > 0) {
    var v = todo.removeFirst();
    for (var i = 0; i < v.constraints.size(); i++) {
      var c = v.constraints.at(i);
      if (!c.isSatisfied()) unsatisfied.add(c);
    }
    var determining = v.determinedBy;
    for (var i = 0; i < v.constraints.size(); i++) {
      var next = v.constraints.at(i);
      if (next != determining && next.isSatisfied()) {
        next.recalculate();
        todo.add(next.output());
      }
    }
  }
  return unsatisfied;
};
Planner.prototype.addConstraintsConsumingTo = function (v, coll) {
  var determining = v.determinedBy;
  var cc = v.constraints;
  for (var i = 0; i < cc.size(); i++) {
    var c = cc.at(i);
    if (c != determining && c.isSatisfied()) coll.add(c);
  }
};
function Plan() { this.v = new OrderedCollection(); }
Plan.prototype.addConstraint = function (c) { this.v.add(c); };
Plan.prototype.size = function () { return this.v.size(); };
Plan.prototype.constraintAt = function (index) { return this.v.at(index); };
Plan.prototype.execute = function () {
  for (var i = 0; i < this.size(); i++) {
    var c = this.constraintAt(i);
    c.execute();
  }
};
function chainTest(n) {
  planner = new Planner();
  var prev = null, first = null, last = null;
  for (var i = 0; i <= n; i++) {
    var name = "v" + i;
    var v = new Variable(name);
    if (prev != null) new EqualityConstraint(prev, v, Strength.REQUIRED);
    if (i == 0) first = v;
    if (i == n) last = v;
    prev = v;
  }
  new StayConstraint(last, Strength.STRONG_DEFAULT);
  var edit = new EditConstraint(first, Strength.PREFERRED);
  var edits = new OrderedCollection();
  edits.add(edit);
  var plan = planner.extractPlanFromConstraints(edits);
  var bad = 0;
  for (var i = 0; i < 100; i++) {
    first.value = i;
    plan.execute();
    if (last.value != i) bad++;
  }
  return "chain n=" + n + " plan=" + plan.size() + " last=" + last.value + " bad=" + bad;
}
function projectionTest(n) {
  planner = new Planner();
  var scale = new Variable("scale", 10);
  var offset = new Variable("offset", 1000);
  var src = null, dst = null;
  var dests = new OrderedCollection();
  for (var i = 0; i < n; i++) {
    src = new Variable("src" + i, i);
    dst = new Variable("dst" + i, i);
    dests.add(dst);
    new StayConstraint(src, Strength.NORMAL);
    new ScaleConstraint(src, scale, offset, dst, Strength.REQUIRED);
  }
  var log = [];
  change(src, 17);
  log.push(dst.value);
  change(dst, 1050);
  log.push(src.value);
  change(scale, 5);
  var sum = 0;
  for (var i = 0; i < n - 1; i++) sum += dests.at(i).value;
  log.push(sum);
  change(offset, 2000);
  sum = 0;
  for (var i = 0; i < n - 1; i++) sum += dests.at(i).value;
  log.push(sum);
  return "projection n=" + n + " " + log.join(",");
}
function change(v, newValue) {
  var edit = new EditConstraint(v, Strength.PREFERRED);
  var edits = new OrderedCollection();
  edits.add(edit);
  var plan = planner.extractPlanFromConstraints(edits);
  for (var i = 0; i < 10; i++) {
    v.value = newValue;
    plan.execute();
  }
  edit.destroyConstraint();
}
"""



def chain_vars(prefix, seed, n):
    """JS source declaring n locals, each derived from the previous one (a >256-slot frame)."""
    lines = [f"  var {prefix}0 = {seed};"]
    lines += [f"  var {prefix}{k} = ({prefix}{k - 1} * 3 + {k}) % 9973;" for k in range(1, n)]
    return "\n".join(lines)


@pytest.mark.parametrize("tier", TIERS)
def test_richards_benchmark_drives_every_scheduler_role(js, golden, tier):
    """CATCHES: A scheduler-shell, Idle-release, Device, Handler or Worker fast path that commits the wrong TCB state, drops or reorders a queued packet, miscounts queueCount/holdCount, or leaves currentTcb/currentId stale after the epoch-guarded role dispatch."""
    code = RICHARDS + WARMUP + r"""
console.log("warmup " + warmup(120, 4));
var s;
[1, 2, 3, 7, 20, 120].forEach(function (c) {
  COUNT = c;
  s = runRichards();
  console.log("count=" + c + " queue=" + s.queueCount + " hold=" + s.holdCount);
});
COUNT = 1000;
s = runRichards();
console.log("reference " + (s.queueCount === EXPECTED_QUEUE_COUNT) + " " + (s.holdCount === EXPECTED_HOLD_COUNT) + " " + s.queueCount + "/" + s.holdCount);
var lines = [];
for (var id = 0; id < NUMBER_OF_IDS; id++) {
  var t = s.blocks[id], q = [];
  for (var p = t.queue; p != null; p = p.link) q.push(p.id + ":" + p.kind + ":" + p.a1 + ":" + p.a2.join("."));
  lines.push(String(t) + " id=" + t.id + " pri=" + t.priority + " queue=[" + q.join(" ") + "]");
}
console.log(lines.join("\n"));
var w = s.blocks[ID_WORKER].task, h = s.blocks[ID_HANDLER_A].task, idle = s.blocks[ID_IDLE].task;
console.log("worker v1=" + w.v1 + " v2=" + w.v2 + " idle v1=" + idle.v1 + " count=" + idle.count + " handlerA v1=" + (h.v1 && h.v1.a1) + " v2=" + h.v2);
console.log("list order " + (function () { var o = [], t = s.list; while (t) { o.push(t.id); t = t.link; } return o.join(","); })() + " current=" + s.currentTcb + " id=" + s.currentId);
"""
    check(js, golden, "richards_full", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_richards_with_small_counts_uses_the_role_epoch_path(js, golden, tier):
    """CATCHES: A role-dispatch scheduler region compiled without the Idle release arm (small COUNT values) that mishandles the final hold, an Idle task whose count reaches zero immediately, or the v1 shift/xor sequence across releases."""
    code = RICHARDS + WARMUP + r"""
// Small counts: IdleTask.run already took its final hold before it is specialised, so the scheduler
// is planned without the Idle release arm (role-epoch dispatch without the six-task graph).
console.log("warmup " + warmup(20, 12));
var s;
for (var c = 1; c <= 6; c++) {
  COUNT = c;
  s = runRichards();
  console.log("count " + c + ": queue=" + s.queueCount + " hold=" + s.holdCount + " idle.v1=" + s.blocks[ID_IDLE].task.v1 + " worker.v2=" + s.blocks[ID_WORKER].task.v2);
}
COUNT = 200;
s = runRichards();
console.log("reference " + s.queueCount + "/" + s.holdCount);
"""
    check(js, golden, "richards_uniform", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_richards_after_device_task_warmed_without_queue_arm(js, golden, tier):
    """CATCHES: A Device dispatch planner that assumes DeviceTask.run was recompiled with Scheduler.queue inlined, so a device whose hot body only ever suspended or held mis-queues packets once the full scheduler runs."""
    code = RICHARDS + WARMUP + r"""
// Warm DeviceTask.run on its suspend and hold arms only, before any scheduler runs.
function warmDevice(n) {
  var s = new Scheduler();
  s.addDeviceTask(ID_DEVICE_A, 4000, null);
  var dev = s.currentTcb.task, pkt = new Packet(null, ID_DEVICE_A, KIND_DEVICE), r = 0;
  for (var i = 0; i < n; i++) {
    if (i & 1) { dev.v1 = null; r += dev.run(null) === s.currentTcb ? 1 : 0; }
    else { r += dev.run(pkt) === null ? 2 : 0; }
  }
  return r + ":" + s.holdCount + ":" + s.currentTcb.state;
}
console.log("warm device " + warmDevice(240));
console.log("warmup " + warmup(120, 4));
var s;
COUNT = 200;
s = runRichards();
console.log("reference " + s.queueCount + "/" + s.holdCount + " " + String(s.blocks[ID_DEVICE_A]) + " " + String(s.blocks[ID_DEVICE_B]));
"""
    check(js, golden, "richards_device_warm", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_richards_methods_replaced_during_schedule(js, golden, tier):
    """CATCHES: Inlined or identity-cached task methods (WorkerTask.run, TaskControlBlock.run/isHeldOrSuspended, Scheduler.queue, a Device prototype swap) or LoadName-cached globals (DATA_SIZE, STATE_NOT_HELD) that keep running their stale compiled versions after being replaced mid-schedule."""
    code = RICHARDS + WARMUP + HARNESS + r"""
console.log("warm", warm());
// 1. Worker run replaced on the prototype mid-schedule.
var origWorkerRun = WorkerTask.prototype.run, workerCalls = 0;
console.log("worker-proto", scheduleWithTrigger(60, 2, function () {
  WorkerTask.prototype.run = function (packet) { workerCalls++; return origWorkerRun.call(this, packet); };
}), "calls=" + workerCalls);
WorkerTask.prototype.run = origWorkerRun;
// 2. One TCB gets an own run method.
var ownCalls = 0;
console.log("tcb-own-run", scheduleWithTrigger(60, 3, function (s) {
  var tcb = s.blocks[ID_DEVICE_B];
  tcb.run = function () { ownCalls++; return TaskControlBlock.prototype.run.call(this); };
}), "calls=" + ownCalls);
// 3. The inlined predicate is replaced by an equivalent counting version.
var origHeld = TaskControlBlock.prototype.isHeldOrSuspended, heldCalls = 0;
console.log("held-proto", scheduleWithTrigger(60, 2, function () {
  TaskControlBlock.prototype.isHeldOrSuspended = function () { heldCalls++; return origHeld.call(this); };
}), "calls=" + heldCalls);
TaskControlBlock.prototype.isHeldOrSuspended = origHeld;
// 4. Scheduler.queue wrapped.
var origQueue = Scheduler.prototype.queue, queued = [];
console.log("queue-proto", scheduleWithTrigger(60, 4, function () {
  Scheduler.prototype.queue = function (packet) { if (queued.length < 6) queued.push(packet.id + ">" + this.currentId); return origQueue.call(this, packet); };
}), "first=" + queued.join(","));
Scheduler.prototype.queue = origQueue;
// 5. Device task switches prototype to a subclass that delegates.
function LoudDevice() {}
LoudDevice.prototype = Object.create(DeviceTask.prototype);
var loud = 0;
LoudDevice.prototype.run = function (packet) { loud++; return DeviceTask.prototype.run.call(this, packet); };
console.log("device-proto", scheduleWithTrigger(60, 2, function (s) {
  Object.setPrototypeOf(s.blocks[ID_DEVICE_A].task, LoudDevice.prototype);
}), "calls=" + loud);
// 6. Globals read by inlined code change mid-run.
console.log("data-size", scheduleWithTrigger(60, 3, function () { DATA_SIZE = 3; }));
DATA_SIZE = 4;
console.log("state-held", scheduleWithTrigger(60, 3, function () { STATE_NOT_HELD = ~STATE_HELD & 7; }));
STATE_NOT_HELD = ~STATE_HELD;
// Clean runs afterwards still produce the reference counts.
COUNT = 200; var clean = runRichards();
console.log("clean", clean.queueCount, clean.holdCount);
"""
    check(js, golden, "richards_methods", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_richards_object_shapes_change_during_schedule(js, golden, tier):
    """CATCHES: Scheduler fast paths that read a TCB link, packet a1, device v1 or a blocks element through a stale own-data slot after it became an accessor or was deleted, treat undefined differently from null in the == null tests, or bypass a Proxy installed as a task's scheduler."""
    code = RICHARDS + WARMUP + HARNESS + r"""
console.log("warm", warm());
console.log("baseline", scheduleWithTrigger(60, 2, function () {}));
// 1. A TCB's link turns into a counting getter mid-run.
var linkReads = 0;
console.log("link-getter", scheduleWithTrigger(60, 2, function (s) {
  var tcb = s.blocks[ID_HANDLER_B], link = tcb.link;
  Object.defineProperty(tcb, "link", { get: function () { linkReads++; return link; }, set: function (v) { link = v; }, configurable: true });
}), "reads=" + linkReads);
// 2. Work packets lose their a1 field mid-run.
console.log("delete-a1", scheduleWithTrigger(60, 3, function (s) {
  for (var p = s.blocks[ID_WORKER].queue; p != null; p = p.link) delete p.a1;
  var h = s.blocks[ID_HANDLER_A].task; if (h.v1 != null) delete h.v1.a1;
}));
// 3. Links and task fields use undefined where null was expected.
console.log("undefined-null", scheduleWithTrigger(60, 2, function (s) {
  var d = s.blocks[ID_DEVICE_A].task; if (d.v1 === null) d.v1 = undefined;
  var hb = s.blocks[ID_HANDLER_B].task; if (hb.v2 === null) hb.v2 = undefined;
  for (var id = 0; id < NUMBER_OF_IDS; id++) if (s.blocks[id].queue === null) s.blocks[id].queue = undefined;
}));
// 4. State and priority values change representation.
console.log("string-state", scheduleWithTrigger(60, 2, function (s) {
  var w = s.blocks[ID_WORKER]; w.state = String(w.state);
  s.blocks[ID_DEVICE_B].priority = "5000";
  s.blocks[ID_HANDLER_A].priority = 2000.5;
}));
// 5. An element of blocks becomes an accessor.
var blockReads = 0;
console.log("blocks-accessor", scheduleWithTrigger(60, 2, function (s) {
  var tcb = s.blocks[ID_DEVICE_A];
  Object.defineProperty(s.blocks, ID_DEVICE_A, { get: function () { blockReads++; return tcb; }, configurable: true });
}), "reads=" + blockReads);
// 6. Packets alternate between real objects and null in the device's v1.
var flips = 0;
console.log("null-object", scheduleWithTrigger(60, 2, function (s) {
  var dev = s.blocks[ID_DEVICE_B].task, v = dev.v1;
  Object.defineProperty(dev, "v1", { get: function () { flips++; return v; }, set: function (x) { v = x; }, configurable: true });
}), "flips=" + flips);
// 7. A task's scheduler field points at a proxy of the scheduler.
var trapped = {};
console.log("proxy-scheduler", scheduleWithTrigger(60, 3, function (s) {
  var w = s.blocks[ID_WORKER].task;
  w.scheduler = new Proxy(s, { get: function (t, k, r) { trapped[k] = (trapped[k] || 0) + 1; return Reflect.get(t, k, r); } });
}), Object.keys(trapped).sort().map(function (k) { return k + ":" + trapped[k]; }).join(","));
COUNT = 200; var clean = runRichards();
console.log("clean", clean.queueCount, clean.holdCount);
"""
    check(js, golden, "richards_shapes", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_richards_errors_thrown_inside_a_running_schedule(js, golden, tier):
    """CATCHES: A specialised scheduler region that, when an accessor throws mid-schedule, unwinds with a half-committed TCB/packet transaction, loses queueCount/holdCount updates, cannot be resumed afterwards, or reports an uncaught error from compiled code with the wrong message or exit status."""
    code = RICHARDS + WARMUP + HARNESS + r"""
console.log("warm", warm());
// A packet accessor throws from deep inside a running schedule; the scheduler state at the throw
// point must be exactly what the interpreter observes.
function throwingRun(count, after) {
  var s = buildScheduler(count), reads = 0;
  var pk = s.blocks[ID_HANDLER_B].queue, kind = pk.kind;
  Object.defineProperty(pk, "kind", { get: function () { if (++reads === after) throw new RangeError("kind read " + reads); return kind; }, configurable: true });
  try { s.schedule(); return "finished " + summary(s); }
  catch (e) { return e.name + ": " + e.message + " | " + summary(s) + " current=" + (s.currentTcb && s.currentTcb.id); }
}
for (var k = 1; k <= 13; k += 4) console.log(throwingRun(60, k));
// The same scheduler keeps working after resuming from the interrupted state.
var s = buildScheduler(60), reads = 0, pk = s.blocks[ID_HANDLER_A].queue, kind = pk.kind;
Object.defineProperty(pk, "kind", { get: function () { if (++reads === 5) throw new Error("once"); return kind; }, configurable: true });
try { s.schedule(); } catch (e) { console.log("caught " + e.message + " at q=" + s.queueCount); }
s.currentTcb = s.list; s.schedule();
console.log("resumed " + summary(s));
COUNT = 200; var clean = runRichards();
console.log("clean", clean.queueCount, clean.holdCount);
// Finally an uncaught error escapes the compiled scheduler.
var last = buildScheduler(100), n = 0;
last.blocks[ID_WORKER].task.run = function (packet) { if (++n === 3) throw new TypeError("worker gave up after " + this.scheduler.queueCount + " queues"); return WorkerTask.prototype.run.call(this, packet); };
last.schedule();
console.log("unreachable");
"""
    r = js(code, *tier)
    assert out(r) == golden("richards_errors")
    assert (r.returncode, r.stderr) == (1, b"Uncaught TypeError: worker gave up after 4 queues\n")


@pytest.mark.parametrize("tier", TIERS)
def test_richards_dialect_refactored_hold_with_hot_queue(js, golden, tier):
    """CATCHES: A Device queue planner that, when DeviceTask.run's recompiled body does not have the canonical inlined shape (holdCurrent written with a local), falls back to Scheduler.queue's own recompiled body and then commits the queue/priority transaction incorrectly."""
    code = richards_dialect("hold") + WARMUP + WARM_QUEUE + DIALECT_DRIVER
    check(js, golden, "richards_dialect_hold", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_richards_dialect_refactored_suspend_and_addto(js, golden, tier):
    """CATCHES: Scheduler Device/Handler regions that assume the canonical suspendCurrent and Packet.addTo bodies and mis-handle the plain-commit fallback used when those helpers are written differently but mean the same thing."""
    code = richards_dialect("suspend", "addto") + WARMUP + DIALECT_DRIVER
    check(js, golden, "richards_dialect_suspend", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_richards_dialect_refactored_priority_check_and_worker(js, golden, tier):
    """CATCHES: Scheduler regions that assume the canonical checkPriorityAdd and Worker fill loop shapes and, for equivalent rewrites (early-return priority check, braced v2 wrap), take a partially planned fast path that queues or wraps differently."""
    code = richards_dialect("check", "worker") + WARMUP + DIALECT_DRIVER
    check(js, golden, "richards_dialect_check", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_deltablue_constraint_solver(js, golden, tier):
    """CATCHES: A JIT that miscompiles DeltaBlue's polymorphic constraint dispatch (Unary/Binary/Scale/Equality via inheritsFrom prototypes), the planner's mark/strength comparisons, or OrderedCollection.remove's compacting loop, changing the plan size or the propagated values."""
    code = DELTABLUE + r"""
var planner = null;
var results = [];
for (var round = 0; round < 6; round++) {
  var a = chainTest(12 + round), b = projectionTest(12 + round);
  if (round % 3 == 2) results.push(a, b);
}
console.log(results.join("\n"));
console.log("final mark", planner.currentMark);
"""
    check(js, golden, "deltablue", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_deltablue_methods_and_values_change_under_plans(js, golden, tier):
    """CATCHES: Cached constraint methods or Strength helpers that survive replacement, a Variable.value accessor installed while a hot plan runs that the compiled execute() bypasses, or a constraint prototype swap that keeps calling the old execute()."""
    code = DELTABLUE + r"""
var planner = null;
for (var round = 0; round < 5; round++) { chainTest(12); projectionTest(12); }
console.log("warm " + chainTest(12) + " | " + projectionTest(12));
// 1. The scale constraint's execute is wrapped after its plan has been extracted.
var origExecute = ScaleConstraint.prototype.execute, executes = 0;
ScaleConstraint.prototype.execute = function () { executes++; origExecute.call(this); };
console.log("wrapped " + projectionTest(10) + " executes=" + executes);
ScaleConstraint.prototype.execute = origExecute;
// 2. Strength comparison is redefined (reversed twice is the identity).
var origStronger = Strength.stronger;
Strength.stronger = function (a, b) { return !origStronger(b, a) && a !== b; };
console.log("stronger " + chainTest(10) + " | " + projectionTest(10));
Strength.stronger = origStronger;
// 3. A variable's value becomes an accessor while the plan runs.
planner = new Planner();
var a = new Variable("a", 1), b = new Variable("b", 2), c = new Variable("c", 3);
new StayConstraint(c, Strength.WEAK_DEFAULT);
new EqualityConstraint(a, b, Strength.REQUIRED);
new EqualityConstraint(b, c, Strength.STRONG_DEFAULT);
var edit = new EditConstraint(a, Strength.PREFERRED), edits = new OrderedCollection();
edits.add(edit);
var plan = planner.extractPlanFromConstraints(edits), log = [];
for (var i = 0; i < 6; i++) {
  if (i === 3) { var stored = b.value, sets = 0; Object.defineProperty(b, "value", { get: function () { return stored; }, set: function (v) { sets++; stored = v * 2; }, configurable: true }); }
  a.value = i * 10;
  plan.execute();
  log.push(a.value + "/" + b.value + "/" + c.value);
}
console.log("accessor " + log.join(" ") + " sets=" + sets + " plan=" + plan.size());
// 4. A constraint's prototype is swapped for an equality that negates.
function NegEquality(v1, v2, s) { NegEquality.superConstructor.call(this, v1, v2, s); }
NegEquality.inheritsFrom(EqualityConstraint);
NegEquality.prototype.execute = function () { this.output().value = -this.input().value; };
planner = new Planner();
var x = new Variable("x", 0), y = new Variable("y", 0), z = new Variable("z", 0);
new StayConstraint(z, Strength.WEAK_DEFAULT);
var e1 = new EqualityConstraint(x, y, Strength.REQUIRED), e2 = new EqualityConstraint(y, z, Strength.REQUIRED);
var ex = new EditConstraint(x, Strength.PREFERRED), ec = new OrderedCollection(); ec.add(ex);
var p2 = planner.extractPlanFromConstraints(ec), out = [];
for (var i = 1; i <= 4; i++) { if (i === 3) Object.setPrototypeOf(e2, NegEquality.prototype); x.value = i; p2.execute(); out.push(y.value + "," + z.value); }
console.log("negated " + out.join(" "));
console.log("final " + chainTest(20) + " | " + projectionTest(20));
"""
    check(js, golden, "deltablue_mutations", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_navier_stokes_fluid_solver(js, golden, tier):
    """CATCHES: Numeric loop regions over Float64Array and dense Array fields that reorder the lin_solve chained assignment, mishandle pre-increment index arithmetic, bounds-clamp in advect wrongly, or diverge between typed and untyped storage of the same solver."""
    code = NAVIER + r"""
function runNavier(alloc, frames) {
  var solver = new FluidField(10, 10, alloc);
  solver.setIterations(4);
  var framesTillAddingPoints = 0, framesBetweenAddingPoints = 3;
  solver.setUICallback(function (field) {
    if (framesTillAddingPoints == 0) {
      field.setVelocity(5, 5, 0, 8);
      field.setDensity(5, 5, 5);
      field.setVelocity(2, 7, 6, -3);
      field.setDensity(2, 7, 20);
      framesTillAddingPoints = framesBetweenAddingPoints;
      framesBetweenAddingPoints++;
    } else {
      framesTillAddingPoints--;
    }
  });
  for (var f = 0; f < frames; f++) solver.update();
  var d = solver.dens(), sum = 0, wsum = 0;
  for (var i = 0; i < d.length; i++) { sum += d[i]; wsum += d[i] * (i % 7); }
  return [sum, wsum, d[6 + 6 * 12], d[3 + 8 * 12]];
}
function alloc64(n) { return new Float64Array(n); }
function allocArray(n) { var a = new Array(n); for (var i = 0; i < n; i++) a[i] = 0; return a; }
var a = runNavier(alloc64, 7), b = runNavier(allocArray, 7);
console.log("typed  " + a.join(" "));
console.log("array  " + b.join(" "));
console.log("same", a.join() === b.join());
"""
    check(js, golden, "navier", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_navier_stokes_storage_variants_and_nan(js, golden, tier):
    """CATCHES: Numeric loops that store doubles into a Float32Array without rounding to float32, treat null/false elements of a mixed Array as numbers without coercion, or mis-propagate a NaN injected mid-run, compared with the interpreter's results."""
    code = NAVIER + r"""
var allocs = {
  f32: function (n) { return new Float32Array(n); },
  mixed: function (n) { var a = []; for (var i = 0; i < n; i++) a.push(i % 5 === 0 ? null : (i % 7 === 0 ? false : 0)); return a; },
  grown: function (n) { var a = [0.5]; a.length = 0; while (a.length < n) a[a.length] = 0; return a; }
};
function runVariant(name, frames, poisonAt) {
  var solver = new FluidField(8, 8, allocs[name]);
  solver.setIterations(4);
  var frame = 0;
  solver.setUICallback(function (field) {
    if (frame % 3 === 0) { field.setVelocity(4, 4, 1, 6); field.setDensity(4, 4, 9); field.setVelocity(1, 6, 4, -2); field.setDensity(1, 6, 12); }
    if (frame === poisonAt) field.setDensity(6, 1, NaN);
  });
  for (frame = 0; frame < frames; frame++) solver.update();
  var d = solver.dens(), sum = 0, nans = 0;
  for (var i = 0; i < d.length; i++) { if (d[i] !== d[i]) nans++; else sum += d[i]; }
  return name + " sum=" + sum + " nans=" + nans + " probe=" + d[5 + 5 * 10] + " tag=" + Object.prototype.toString.call(d);
}
console.log(runVariant("f32", 5, -1));
console.log(runVariant("mixed", 5, -1));
console.log(runVariant("grown", 5, -1));
console.log(runVariant("grown", 5, 4));
console.log(runVariant("f32", 5, 3));
"""
    check(js, golden, "navier_storage", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_crypto_bignum_montgomery_modpow(js, golden, tier):
    """CATCHES: Int32 bit operations in the am3 inner loop, carry propagation in subTo/divRemTo, or the Montgomery reduction sliding window that the JIT computes differently from the interpreter, detected by comparing against native BigInt modular exponentiation."""
    code = r"""
// Scaled-down Crypto kernel: jsbn-style BigInteger (28-bit digits, am3) with Montgomery modPow.
var dbits = 28;
var BI_DB = dbits, BI_DM = ((1 << dbits) - 1), BI_DV = (1 << dbits);
var BI_FP = 52, BI_FV = Math.pow(2, BI_FP), BI_F1 = BI_FP - dbits, BI_F2 = 2 * dbits - BI_FP;
function BigInteger(a, b) {
  this.array = new Array();
  if (a != null) {
    if ("number" == typeof a) this.fromInt(a);
    else this.fromString(a, b);
  }
}
function nbi() { return new BigInteger(null); }
function am3(i, x, w, j, c, n) {
  var this_array = this.array, w_array = w.array;
  var xl = x & 0x3fff, xh = x >> 14;
  while (--n >= 0) {
    var l = this_array[i] & 0x3fff;
    var h = this_array[i++] >> 14;
    var m = xh * l + h * xl;
    l = xl * l + ((m & 0x3fff) << 14) + w_array[j] + c;
    c = (l >> 28) + (m >> 14) + xh * h;
    w_array[j++] = l & 0xfffffff;
  }
  return c;
}
BigInteger.prototype.am = am3;
var BI_RM = "0123456789abcdefghijklmnopqrstuvwxyz";
var BI_RC = new Array();
var rr, vv;
rr = "0".charCodeAt(0); for (vv = 0; vv <= 9; ++vv) BI_RC[rr++] = vv;
rr = "a".charCodeAt(0); for (vv = 10; vv < 36; ++vv) BI_RC[rr++] = vv;
rr = "A".charCodeAt(0); for (vv = 10; vv < 36; ++vv) BI_RC[rr++] = vv;
function int2char(n) { return BI_RM.charAt(n); }
function intAt(s, i) { var c = BI_RC[s.charCodeAt(i)]; return (c == null) ? -1 : c; }
function bnpCopyTo(r) {
  var this_array = this.array, r_array = r.array;
  for (var i = this.t - 1; i >= 0; --i) r_array[i] = this_array[i];
  r.t = this.t; r.s = this.s;
}
function bnpFromInt(x) {
  var this_array = this.array;
  this.t = 1;
  this.s = (x < 0) ? -1 : 0;
  if (x > 0) this_array[0] = x;
  else if (x < -1) this_array[0] = x + BI_DV;
  else this.t = 0;
}
function nbv(i) { var r = nbi(); r.fromInt(i); return r; }
function bnpFromString(s, b) {
  var this_array = this.array;
  var k = 4;
  this.t = 0; this.s = 0;
  var i = s.length, mi = false, sh = 0;
  while (--i >= 0) {
    var x = intAt(s, i);
    if (x < 0) { if (s.charAt(i) == "-") mi = true; continue; }
    mi = false;
    if (sh == 0) this_array[this.t++] = x;
    else if (sh + k > BI_DB) {
      this_array[this.t - 1] |= (x & ((1 << (BI_DB - sh)) - 1)) << sh;
      this_array[this.t++] = (x >> (BI_DB - sh));
    } else this_array[this.t - 1] |= x << sh;
    sh += k;
    if (sh >= BI_DB) sh -= BI_DB;
  }
  this.clamp();
  if (mi) BigInteger.ZERO.subTo(this, this);
}
function bnpClamp() {
  var this_array = this.array;
  var c = this.s & BI_DM;
  while (this.t > 0 && this_array[this.t - 1] == c) --this.t;
}
function bnToString(b) {
  var this_array = this.array;
  if (this.s < 0) return "-" + this.negate().toString(b);
  var k = 4;
  var km = (1 << k) - 1, d, m = false, r = "", i = this.t;
  var p = BI_DB - (i * BI_DB) % k;
  if (i-- > 0) {
    if (p < BI_DB && (d = this_array[i] >> p) > 0) { m = true; r = int2char(d); }
    while (i >= 0) {
      if (p < k) {
        d = (this_array[i] & ((1 << p) - 1)) << (k - p);
        d |= this_array[--i] >> (p += BI_DB - k);
      } else {
        d = (this_array[i] >> (p -= k)) & km;
        if (p <= 0) { p += BI_DB; --i; }
      }
      if (d > 0) m = true;
      if (m) r += int2char(d);
    }
  }
  return m ? r : "0";
}
function bnNegate() { var r = nbi(); BigInteger.ZERO.subTo(this, r); return r; }
function bnAbs() { return (this.s < 0) ? this.negate() : this; }
function bnCompareTo(a) {
  var this_array = this.array, a_array = a.array;
  var r = this.s - a.s;
  if (r != 0) return r;
  var i = this.t;
  r = i - a.t;
  if (r != 0) return r;
  while (--i >= 0) if ((r = this_array[i] - a_array[i]) != 0) return r;
  return 0;
}
function nbits(x) {
  var r = 1, t;
  if ((t = x >>> 16) != 0) { x = t; r += 16; }
  if ((t = x >> 8) != 0) { x = t; r += 8; }
  if ((t = x >> 4) != 0) { x = t; r += 4; }
  if ((t = x >> 2) != 0) { x = t; r += 2; }
  if ((t = x >> 1) != 0) { x = t; r += 1; }
  return r;
}
function bnBitLength() {
  var this_array = this.array;
  if (this.t <= 0) return 0;
  return BI_DB * (this.t - 1) + nbits(this_array[this.t - 1] ^ (this.s & BI_DM));
}
function bnpDLShiftTo(n, r) {
  var this_array = this.array, r_array = r.array;
  var i;
  for (i = this.t - 1; i >= 0; --i) r_array[i + n] = this_array[i];
  for (i = n - 1; i >= 0; --i) r_array[i] = 0;
  r.t = this.t + n; r.s = this.s;
}
function bnpDRShiftTo(n, r) {
  var this_array = this.array, r_array = r.array;
  for (var i = n; i < this.t; ++i) r_array[i - n] = this_array[i];
  r.t = Math.max(this.t - n, 0); r.s = this.s;
}
function bnpLShiftTo(n, r) {
  var this_array = this.array, r_array = r.array;
  var bs = n % BI_DB, cbs = BI_DB - bs, bm = (1 << cbs) - 1;
  var ds = Math.floor(n / BI_DB), c = (this.s << bs) & BI_DM, i;
  for (i = this.t - 1; i >= 0; --i) {
    r_array[i + ds + 1] = (this_array[i] >> cbs) | c;
    c = (this_array[i] & bm) << bs;
  }
  for (i = ds - 1; i >= 0; --i) r_array[i] = 0;
  r_array[ds] = c;
  r.t = this.t + ds + 1; r.s = this.s;
  r.clamp();
}
function bnpRShiftTo(n, r) {
  var this_array = this.array, r_array = r.array;
  r.s = this.s;
  var ds = Math.floor(n / BI_DB);
  if (ds >= this.t) { r.t = 0; return; }
  var bs = n % BI_DB, cbs = BI_DB - bs, bm = (1 << bs) - 1;
  r_array[0] = this_array[ds] >> bs;
  for (var i = ds + 1; i < this.t; ++i) {
    r_array[i - ds - 1] |= (this_array[i] & bm) << cbs;
    r_array[i - ds] = this_array[i] >> bs;
  }
  if (bs > 0) r_array[this.t - ds - 1] |= (this.s & bm) << cbs;
  r.t = this.t - ds; r.clamp();
}
function bnpSubTo(a, r) {
  var this_array = this.array, r_array = r.array, a_array = a.array;
  var i = 0, c = 0, m = Math.min(a.t, this.t);
  while (i < m) { c += this_array[i] - a_array[i]; r_array[i++] = c & BI_DM; c >>= BI_DB; }
  if (a.t < this.t) {
    c -= a.s;
    while (i < this.t) { c += this_array[i]; r_array[i++] = c & BI_DM; c >>= BI_DB; }
    c += this.s;
  } else {
    c += this.s;
    while (i < a.t) { c -= a_array[i]; r_array[i++] = c & BI_DM; c >>= BI_DB; }
    c -= a.s;
  }
  r.s = (c < 0) ? -1 : 0;
  if (c < -1) r_array[i++] = BI_DV + c;
  else if (c > 0) r_array[i++] = c;
  r.t = i; r.clamp();
}
function bnpMultiplyTo(a, r) {
  var this_array = this.array, r_array = r.array;
  var x = this.abs(), y = a.abs();
  var y_array = y.array;
  var i = x.t;
  r.t = i + y.t;
  while (--i >= 0) r_array[i] = 0;
  for (i = 0; i < y.t; ++i) r_array[i + x.t] = x.am(0, y_array[i], r, i, 0, x.t);
  r.s = 0; r.clamp();
  if (this.s != a.s) BigInteger.ZERO.subTo(r, r);
}
function bnpSquareTo(r) {
  var x = this.abs();
  var x_array = x.array, r_array = r.array;
  var i = r.t = 2 * x.t;
  while (--i >= 0) r_array[i] = 0;
  for (i = 0; i < x.t - 1; ++i) {
    var c = x.am(i, x_array[i], r, 2 * i, 0, 1);
    if ((r_array[i + x.t] += x.am(i + 1, 2 * x_array[i], r, 2 * i + 1, c, x.t - i - 1)) >= BI_DV) {
      r_array[i + x.t] -= BI_DV;
      r_array[i + x.t + 1] = 1;
    }
  }
  if (r.t > 0) r_array[r.t - 1] += x.am(i, x_array[i], r, 2 * i, 0, 1);
  r.s = 0; r.clamp();
}
function bnpDivRemTo(m, q, r) {
  var pm = m.abs();
  if (pm.t <= 0) return;
  var pt = this.abs();
  if (pt.t < pm.t) { if (q != null) q.fromInt(0); if (r != null) this.copyTo(r); return; }
  if (r == null) r = nbi();
  var y = nbi(), ts = this.s, ms = m.s;
  var pm_array = pm.array;
  var nsh = BI_DB - nbits(pm_array[pm.t - 1]);
  if (nsh > 0) { pm.lShiftTo(nsh, y); pt.lShiftTo(nsh, r); }
  else { pm.copyTo(y); pt.copyTo(r); }
  var ys = y.t;
  var y_array = y.array;
  var y0 = y_array[ys - 1];
  if (y0 == 0) return;
  var yt = y0 * (1 << BI_F1) + ((ys > 1) ? y_array[ys - 2] >> BI_F2 : 0);
  var d1 = BI_FV / yt, d2 = (1 << BI_F1) / yt, e = 1 << BI_F2;
  var i = r.t, j = i - ys, t = (q == null) ? nbi() : q;
  y.dlShiftTo(j, t);
  var r_array = r.array;
  if (r.compareTo(t) >= 0) { r_array[r.t++] = 1; r.subTo(t, r); }
  BigInteger.ONE.dlShiftTo(ys, t);
  t.subTo(y, y);
  while (y.t < ys) y_array[y.t++] = 0;
  while (--j >= 0) {
    var qd = (r_array[--i] == y0) ? BI_DM : Math.floor(r_array[i] * d1 + (r_array[i - 1] + e) * d2);
    if ((r_array[i] += y.am(0, qd, r, j, 0, ys)) < qd) {
      y.dlShiftTo(j, t);
      r.subTo(t, r);
      while (r_array[i] < --qd) r.subTo(t, r);
    }
  }
  if (q != null) { r.drShiftTo(ys, q); if (ts != ms) BigInteger.ZERO.subTo(q, q); }
  r.t = ys;
  r.clamp();
  if (nsh > 0) r.rShiftTo(nsh, r);
  if (ts < 0) BigInteger.ZERO.subTo(r, r);
}
function bnMod(a) {
  var r = nbi();
  this.abs().divRemTo(a, null, r);
  if (this.s < 0 && r.compareTo(BigInteger.ZERO) > 0) a.subTo(r, r);
  return r;
}
function bnpInvDigit() {
  var this_array = this.array;
  if (this.t < 1) return 0;
  var x = this_array[0];
  if ((x & 1) == 0) return 0;
  var y = x & 3;
  y = (y * (2 - (x & 0xf) * y)) & 0xf;
  y = (y * (2 - (x & 0xff) * y)) & 0xff;
  y = (y * (2 - (((x & 0xffff) * y) & 0xffff))) & 0xffff;
  y = (y * (2 - x * y % BI_DV)) % BI_DV;
  return (y > 0) ? BI_DV - y : -y;
}
function Montgomery(m) {
  this.m = m;
  this.mp = m.invDigit();
  this.mpl = this.mp & 0x7fff;
  this.mph = this.mp >> 15;
  this.um = (1 << (BI_DB - 15)) - 1;
  this.mt2 = 2 * m.t;
}
function montConvert(x) {
  var r = nbi();
  x.abs().dlShiftTo(this.m.t, r);
  r.divRemTo(this.m, null, r);
  if (x.s < 0 && r.compareTo(BigInteger.ZERO) > 0) this.m.subTo(r, r);
  return r;
}
function montRevert(x) { var r = nbi(); x.copyTo(r); this.reduce(r); return r; }
function montReduce(x) {
  var x_array = x.array;
  while (x.t <= this.mt2) x_array[x.t++] = 0;
  for (var i = 0; i < this.m.t; ++i) {
    var j = x_array[i] & 0x7fff;
    var u0 = (j * this.mpl + (((j * this.mph + (x_array[i] >> 15) * this.mpl) & this.um) << 15)) & BI_DM;
    j = i + this.m.t;
    x_array[j] += this.m.am(0, u0, x, i, 0, this.m.t);
    while (x_array[j] >= BI_DV) { x_array[j] -= BI_DV; x_array[++j]++; }
  }
  x.clamp();
  x.drShiftTo(this.m.t, x);
  if (x.compareTo(this.m) >= 0) x.subTo(this.m, x);
}
function montSqrTo(x, r) { x.squareTo(r); this.reduce(r); }
function montMulTo(x, y, r) { x.multiplyTo(y, r); this.reduce(r); }
Montgomery.prototype.convert = montConvert;
Montgomery.prototype.revert = montRevert;
Montgomery.prototype.reduce = montReduce;
Montgomery.prototype.mulTo = montMulTo;
Montgomery.prototype.sqrTo = montSqrTo;
function bnpIsEven() { var this_array = this.array; return ((this.t > 0) ? (this_array[0] & 1) : this.s) == 0; }
function bnpExp(e, z) {
  if (e > 0xffffffff || e < 1) return BigInteger.ONE;
  var r = nbi(), r2 = nbi(), g = z.convert(this), i = nbits(e) - 1;
  g.copyTo(r);
  while (--i >= 0) {
    z.sqrTo(r, r2);
    if ((e & (1 << i)) > 0) z.mulTo(r2, g, r);
    else { var t = r; r = r2; r2 = t; }
  }
  return z.revert(r);
}
function bnModPowInt(e, m) { return this.exp(e, new Montgomery(m)); }
function bnModPow(e, m) {
  var e_array = e.array;
  var i = e.bitLength(), k, r = nbv(1), z;
  if (i <= 0) return r;
  else if (i < 18) k = 1;
  else if (i < 48) k = 3;
  else if (i < 144) k = 4;
  else k = 5;
  z = new Montgomery(m);
  var g = new Array(), n = 3, k1 = k - 1, km = (1 << k) - 1;
  g[1] = z.convert(this);
  if (k > 1) {
    var g2 = nbi();
    z.sqrTo(g[1], g2);
    while (n <= km) { g[n] = nbi(); z.mulTo(g2, g[n - 2], g[n]); n += 2; }
  }
  var j = e.t - 1, w, is1 = true, r2 = nbi(), t;
  i = nbits(e_array[j]) - 1;
  while (j >= 0) {
    if (i >= k1) w = (e_array[j] >> (i - k1)) & km;
    else {
      w = (e_array[j] & ((1 << (i + 1)) - 1)) << (k1 - i);
      if (j > 0) w |= e_array[j - 1] >> (BI_DB + i - k1);
    }
    n = k;
    while ((w & 1) == 0) { w >>= 1; --n; }
    if ((i -= n) < 0) { i += BI_DB; --j; }
    if (is1) { g[w].copyTo(r); is1 = false; }
    else {
      while (n > 1) { z.sqrTo(r, r2); z.sqrTo(r2, r); n -= 2; }
      if (n > 0) z.sqrTo(r, r2); else { t = r; r = r2; r2 = t; }
      z.mulTo(r2, g[w], r);
    }
    while (j >= 0 && (e_array[j] & (1 << i)) == 0) {
      z.sqrTo(r, r2); t = r; r = r2; r2 = t;
      if (--i < 0) { i = BI_DB - 1; --j; }
    }
  }
  return z.revert(r);
}
BigInteger.prototype.copyTo = bnpCopyTo;
BigInteger.prototype.fromInt = bnpFromInt;
BigInteger.prototype.fromString = bnpFromString;
BigInteger.prototype.clamp = bnpClamp;
BigInteger.prototype.dlShiftTo = bnpDLShiftTo;
BigInteger.prototype.drShiftTo = bnpDRShiftTo;
BigInteger.prototype.lShiftTo = bnpLShiftTo;
BigInteger.prototype.rShiftTo = bnpRShiftTo;
BigInteger.prototype.subTo = bnpSubTo;
BigInteger.prototype.multiplyTo = bnpMultiplyTo;
BigInteger.prototype.squareTo = bnpSquareTo;
BigInteger.prototype.divRemTo = bnpDivRemTo;
BigInteger.prototype.invDigit = bnpInvDigit;
BigInteger.prototype.isEven = bnpIsEven;
BigInteger.prototype.exp = bnpExp;
BigInteger.prototype.toString = bnToString;
BigInteger.prototype.negate = bnNegate;
BigInteger.prototype.abs = bnAbs;
BigInteger.prototype.compareTo = bnCompareTo;
BigInteger.prototype.bitLength = bnBitLength;
BigInteger.prototype.mod = bnMod;
BigInteger.prototype.modPowInt = bnModPowInt;
BigInteger.prototype.modPow = bnModPow;
BigInteger.ZERO = nbv(0);
BigInteger.ONE = nbv(1);
// Native BigInt reference.
function refModPow(b, e, m) {
  var r = 1n; b %= m;
  while (e > 0n) { if (e & 1n) r = r * b % m; b = b * b % m; e >>= 1n; }
  return r;
}
var N = "c4e3f7a2b19d05e8f6a3c2d1b0e9f8a7c6d5e4f3a2b1c0d9e8f7b3";
var D = "5a17c3e9b2d4f6a8c0e2b4d6f8a1c3e5b7";
var n = new BigInteger(N, 16), d = new BigInteger(D, 16);
var lines = [], ok = 0, total = 0;
for (var round = 0; round < 2; round++) {
  var msgHex = "";
  for (var k = 0; k < 14; k++) msgHex += ((round * 7919 + k * 104729) % 4093).toString(16);
  var m = new BigInteger(msgHex, 16).mod(n);
  var c = m.modPowInt(65537, n);
  var p = m.modPow(d, n);
  var refC = refModPow(BigInt("0x" + m.toString(16)), 65537n, BigInt("0x" + N));
  var refP = refModPow(BigInt("0x" + m.toString(16)), BigInt("0x" + D), BigInt("0x" + N));
  total += 2;
  if (refC.toString(16) === c.toString(16)) ok++;
  if (refP.toString(16) === p.toString(16)) ok++;
  lines.push(round + ": " + c.toString(16).slice(0, 24) + " " + p.toString(16).slice(-24) + " bits=" + c.bitLength() + "/" + p.bitLength());
}
console.log(lines.join("\n"));
console.log("verified " + ok + "/" + total);
"""
    check(js, golden, "crypto", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_raytrace_scene_render(js, golden, tier):
    """CATCHES: Object-heavy float math (Class.create constructors, prototype methods called through Flog.RayTracer.Vector.prototype, Math.sqrt, reflection recursion, shadow tests) that the JIT rounds or dispatches differently, changing pixel brightness or the checksum."""
    code = r"""
// Scaled-down RayTrace (V8 benchmark suite, Flog.RayTracer) rendering a tiny scene.
var Class = { create: function () { return function () { this.initialize.apply(this, arguments); }; } };
Object.extend = function (destination, source) { for (var property in source) destination[property] = source[property]; return destination; };
function powi(x, n) { var r = 1; while (n > 0) { if (n & 1) r *= x; x *= x; n >>= 1; } return r; }
var Flog = { RayTracer: { Shape: {}, Material: {} } };
Flog.RayTracer.Color = Class.create();
Flog.RayTracer.Color.prototype = {
  red: 0.0, green: 0.0, blue: 0.0,
  initialize: function (r, g, b) { if (!r) r = 0.0; if (!g) g = 0.0; if (!b) b = 0.0; this.red = r; this.green = g; this.blue = b; },
  add: function (c1, c2) { var result = new Flog.RayTracer.Color(0, 0, 0); result.red = c1.red + c2.red; result.green = c1.green + c2.green; result.blue = c1.blue + c2.blue; return result; },
  addScalar: function (c1, s) { var result = new Flog.RayTracer.Color(0, 0, 0); result.red = c1.red + s; result.green = c1.green + s; result.blue = c1.blue + s; result.limit(); return result; },
  multiply: function (c1, c2) { var result = new Flog.RayTracer.Color(0, 0, 0); result.red = c1.red * c2.red; result.green = c1.green * c2.green; result.blue = c1.blue * c2.blue; return result; },
  multiplyScalar: function (c1, f) { var result = new Flog.RayTracer.Color(0, 0, 0); result.red = c1.red * f; result.green = c1.green * f; result.blue = c1.blue * f; return result; },
  limit: function () {
    this.red = (this.red > 0.0) ? ((this.red > 1.0) ? 1.0 : this.red) : 0.0;
    this.green = (this.green > 0.0) ? ((this.green > 1.0) ? 1.0 : this.green) : 0.0;
    this.blue = (this.blue > 0.0) ? ((this.blue > 1.0) ? 1.0 : this.blue) : 0.0;
  },
  blend: function (c1, c2, w) { var result = new Flog.RayTracer.Color(0, 0, 0); result = Flog.RayTracer.Color.prototype.add(Flog.RayTracer.Color.prototype.multiplyScalar(c1, 1 - w), Flog.RayTracer.Color.prototype.multiplyScalar(c2, w)); return result; },
  brightness: function () { var r = Math.floor(this.red * 255); var g = Math.floor(this.green * 255); var b = Math.floor(this.blue * 255); return (r * 77 + g * 150 + b * 29) >> 8; },
  toString: function () { var r = Math.floor(this.red * 255); var g = Math.floor(this.green * 255); var b = Math.floor(this.blue * 255); return "rgb(" + r + "," + g + "," + b + ")"; }
};
Flog.RayTracer.Light = Class.create();
Flog.RayTracer.Light.prototype = {
  position: null, color: null, intensity: 10.0,
  initialize: function (pos, color, intensity) { this.position = pos; this.color = color; this.intensity = (intensity ? intensity : 10.0); }
};
Flog.RayTracer.Vector = Class.create();
Flog.RayTracer.Vector.prototype = {
  x: 0.0, y: 0.0, z: 0.0,
  initialize: function (x, y, z) { this.x = (x ? x : 0); this.y = (y ? y : 0); this.z = (z ? z : 0); },
  normalize: function () { var m = this.magnitude(); return new Flog.RayTracer.Vector(this.x / m, this.y / m, this.z / m); },
  magnitude: function () { return Math.sqrt((this.x * this.x) + (this.y * this.y) + (this.z * this.z)); },
  cross: function (w) { return new Flog.RayTracer.Vector(-this.z * w.y + this.y * w.z, this.z * w.x - this.x * w.z, -this.y * w.x + this.x * w.y); },
  dot: function (w) { return this.x * w.x + this.y * w.y + this.z * w.z; },
  add: function (v, w) { return new Flog.RayTracer.Vector(w.x + v.x, w.y + v.y, w.z + v.z); },
  subtract: function (v, w) { return new Flog.RayTracer.Vector(v.x - w.x, v.y - w.y, v.z - w.z); },
  multiplyScalar: function (v, w) { return new Flog.RayTracer.Vector(v.x * w, v.y * w, v.z * w); }
};
Flog.RayTracer.Ray = Class.create();
Flog.RayTracer.Ray.prototype = { position: null, direction: null, initialize: function (pos, dir) { this.position = pos; this.direction = dir; } };
Flog.RayTracer.Scene = Class.create();
Flog.RayTracer.Scene.prototype = {
  camera: null, shapes: [], lights: [], background: null,
  initialize: function () {
    this.camera = new Flog.RayTracer.Camera(new Flog.RayTracer.Vector(0, 0, -5), new Flog.RayTracer.Vector(0, 0, 1), new Flog.RayTracer.Vector(0, 1, 0));
    this.shapes = new Array(); this.lights = new Array();
    this.background = new Flog.RayTracer.Background(new Flog.RayTracer.Color(0, 0, 0.5), 0.2);
  }
};
Flog.RayTracer.Material.BaseMaterial = Class.create();
Flog.RayTracer.Material.BaseMaterial.prototype = {
  gloss: 2.0, transparency: 0.0, reflection: 0.0, refraction: 0.50, hasTexture: false,
  initialize: function () { },
  getColor: function (u, v) { },
  wrapUp: function (t) { t = t % 2.0; if (t < -1) t += 2.0; if (t >= 1) t -= 2.0; return t; }
};
Flog.RayTracer.Material.Solid = Class.create();
Flog.RayTracer.Material.Solid.prototype = Object.extend(new Flog.RayTracer.Material.BaseMaterial(), {
  initialize: function (color, reflection, refraction, transparency, gloss) { this.color = color; this.reflection = reflection; this.transparency = transparency; this.gloss = gloss; this.hasTexture = false; },
  getColor: function (u, v) { return this.color; }
});
Flog.RayTracer.Material.Chessboard = Class.create();
Flog.RayTracer.Material.Chessboard.prototype = Object.extend(new Flog.RayTracer.Material.BaseMaterial(), {
  colorEven: null, colorOdd: null, density: 0.5,
  initialize: function (colorEven, colorOdd, reflection, transparency, gloss, density) { this.colorEven = colorEven; this.colorOdd = colorOdd; this.reflection = reflection; this.transparency = transparency; this.gloss = gloss; this.density = density; this.hasTexture = true; },
  getColor: function (u, v) { var t = this.wrapUp(u * this.density) * this.wrapUp(v * this.density); if (t < 0.0) return this.colorEven; else return this.colorOdd; }
});
Flog.RayTracer.Shape.Sphere = Class.create();
Flog.RayTracer.Shape.Sphere.prototype = {
  initialize: function (pos, radius, material) { this.radius = radius; this.position = pos; this.material = material; },
  intersect: function (ray) {
    var info = new Flog.RayTracer.IntersectionInfo();
    info.shape = this;
    var dst = Flog.RayTracer.Vector.prototype.subtract(ray.position, this.position);
    var B = dst.dot(ray.direction);
    var C = dst.dot(dst) - (this.radius * this.radius);
    var D = (B * B) - C;
    if (D > 0) {
      info.isHit = true;
      info.distance = (-B) - Math.sqrt(D);
      info.position = Flog.RayTracer.Vector.prototype.add(ray.position, Flog.RayTracer.Vector.prototype.multiplyScalar(ray.direction, info.distance));
      info.normal = Flog.RayTracer.Vector.prototype.subtract(info.position, this.position).normalize();
      info.color = this.material.getColor(0, 0);
    } else {
      info.isHit = false;
    }
    return info;
  }
};
Flog.RayTracer.Shape.Plane = Class.create();
Flog.RayTracer.Shape.Plane.prototype = {
  d: 0.0,
  initialize: function (pos, d, material) { this.position = pos; this.d = d; this.material = material; },
  intersect: function (ray) {
    var info = new Flog.RayTracer.IntersectionInfo();
    var Vd = this.position.dot(ray.direction);
    if (Vd == 0) return info;
    var t = -(this.position.dot(ray.position) + this.d) / Vd;
    if (t <= 0) return info;
    info.shape = this;
    info.isHit = true;
    info.position = Flog.RayTracer.Vector.prototype.add(ray.position, Flog.RayTracer.Vector.prototype.multiplyScalar(ray.direction, t));
    info.normal = this.position;
    info.distance = t;
    if (this.material.hasTexture) {
      var vU = new Flog.RayTracer.Vector(this.position.y, this.position.z, -this.position.x);
      var vV = vU.cross(this.position);
      var u = info.position.dot(vU);
      var v = info.position.dot(vV);
      info.color = this.material.getColor(u, v);
    } else {
      info.color = this.material.getColor(0, 0);
    }
    return info;
  }
};
Flog.RayTracer.IntersectionInfo = Class.create();
Flog.RayTracer.IntersectionInfo.prototype = {
  isHit: false, hitCount: 0, shape: null, position: null, normal: null, color: null, distance: null,
  initialize: function () { this.color = new Flog.RayTracer.Color(0, 0, 0); }
};
Flog.RayTracer.Camera = Class.create();
Flog.RayTracer.Camera.prototype = {
  position: null, lookAt: null, equator: null, up: null, screen: null,
  initialize: function (pos, lookAt, up) {
    this.position = pos; this.lookAt = lookAt; this.up = up;
    this.equator = lookAt.normalize().cross(this.up);
    this.screen = Flog.RayTracer.Vector.prototype.add(this.position, this.lookAt);
  },
  getRay: function (vx, vy) {
    var pos = Flog.RayTracer.Vector.prototype.subtract(this.screen, Flog.RayTracer.Vector.prototype.subtract(Flog.RayTracer.Vector.prototype.multiplyScalar(this.equator, vx), Flog.RayTracer.Vector.prototype.multiplyScalar(this.up, vy)));
    pos.y = pos.y * -1;
    var dir = Flog.RayTracer.Vector.prototype.subtract(pos, this.position);
    return new Flog.RayTracer.Ray(pos, dir.normalize());
  }
};
Flog.RayTracer.Background = Class.create();
Flog.RayTracer.Background.prototype = { color: null, ambience: 0.0, initialize: function (color, ambience) { this.color = color; this.ambience = ambience; } };
Flog.RayTracer.Engine = Class.create();
Flog.RayTracer.Engine.prototype = {
  canvas: null,
  initialize: function (options) {
    this.options = Object.extend({ canvasHeight: 100, canvasWidth: 100, pixelWidth: 2, pixelHeight: 2, renderDiffuse: false, renderShadows: false, renderHighlights: false, renderReflections: false, rayDepth: 2 }, options || {});
    this.options.canvasHeight /= this.options.pixelHeight;
    this.options.canvasWidth /= this.options.pixelWidth;
    this.rows = [];
  },
  setPixel: function (x, y, color) { this.rows.push(color.brightness()); this.checksum = (this.checksum * 31 + color.brightness() + x * 3 + y) | 0; },
  renderScene: function (scene) {
    this.checksum = 0;
    var canvasHeight = this.options.canvasHeight;
    var canvasWidth = this.options.canvasWidth;
    for (var y = 0; y < canvasHeight; y++) {
      for (var x = 0; x < canvasWidth; x++) {
        var yp = y * 1.0 / canvasHeight * 2 - 1;
        var xp = x * 1.0 / canvasWidth * 2 - 1;
        var ray = scene.camera.getRay(xp, yp);
        var color = this.getPixelColor(ray, scene);
        this.setPixel(x, y, color);
      }
    }
  },
  getPixelColor: function (ray, scene) {
    var info = this.testIntersection(ray, scene, null);
    if (info.isHit) { var color = this.rayTrace(info, ray, scene, 0); return color; }
    return scene.background.color;
  },
  testIntersection: function (ray, scene, exclude) {
    var hits = 0;
    var best = new Flog.RayTracer.IntersectionInfo();
    best.distance = 2000;
    for (var i = 0; i < scene.shapes.length; i++) {
      var shape = scene.shapes[i];
      if (shape != exclude) {
        var info = shape.intersect(ray);
        if (info.isHit && info.distance >= 0 && info.distance < best.distance) { best = info; hits++; }
      }
    }
    best.hitCount = hits;
    return best;
  },
  getReflectionRay: function (P, N, V) {
    var c1 = -N.dot(V);
    var R1 = Flog.RayTracer.Vector.prototype.add(Flog.RayTracer.Vector.prototype.multiplyScalar(N, 2 * c1), V);
    return new Flog.RayTracer.Ray(P, R1);
  },
  rayTrace: function (info, ray, scene, depth) {
    var color = Flog.RayTracer.Color.prototype.multiplyScalar(info.color, scene.background.ambience);
    var oldColor = color;
    var shininess = powi(10, info.shape.material.gloss + 1);
    for (var i = 0; i < scene.lights.length; i++) {
      var light = scene.lights[i];
      var v = Flog.RayTracer.Vector.prototype.subtract(light.position, info.position).normalize();
      if (this.options.renderDiffuse) {
        var L = v.dot(info.normal);
        if (L > 0.0) color = Flog.RayTracer.Color.prototype.add(color, Flog.RayTracer.Color.prototype.multiply(info.color, Flog.RayTracer.Color.prototype.multiplyScalar(light.color, L)));
      }
      if (depth <= this.options.rayDepth) {
        if (this.options.renderReflections && info.shape.material.reflection > 0) {
          var reflectionRay = this.getReflectionRay(info.position, info.normal, ray.direction);
          var refl = this.testIntersection(reflectionRay, scene, info.shape);
          if (refl.isHit && refl.distance > 0) refl.color = this.rayTrace(refl, reflectionRay, scene, depth + 1);
          else refl.color = scene.background.color;
          color = Flog.RayTracer.Color.prototype.blend(color, refl.color, info.shape.material.reflection);
        }
      }
      var shadowInfo = new Flog.RayTracer.IntersectionInfo();
      if (this.options.renderShadows) {
        var shadowRay = new Flog.RayTracer.Ray(info.position, v);
        shadowInfo = this.testIntersection(shadowRay, scene, info.shape);
        if (shadowInfo.isHit && shadowInfo.shape != info.shape) {
          var vA = Flog.RayTracer.Color.prototype.multiplyScalar(color, 0.5);
          var dB = (0.5 * powi(shadowInfo.shape.material.transparency, 1));
          color = Flog.RayTracer.Color.prototype.addScalar(vA, dB);
        }
      }
      if (this.options.renderHighlights && !shadowInfo.isHit && info.shape.material.gloss > 0) {
        var Lv = Flog.RayTracer.Vector.prototype.subtract(info.shape.position, light.position).normalize();
        var E = Flog.RayTracer.Vector.prototype.subtract(scene.camera.position, info.shape.position).normalize();
        var H = Flog.RayTracer.Vector.prototype.subtract(E, Lv).normalize();
        var glossWeight = powi(Math.max(info.normal.dot(H), 0), shininess);
        color = Flog.RayTracer.Color.prototype.add(Flog.RayTracer.Color.prototype.multiplyScalar(light.color, glossWeight), color);
      }
    }
    color.limit();
    return color;
  }
};
function renderScene(size) {
  var scene = new Flog.RayTracer.Scene();
  scene.camera = new Flog.RayTracer.Camera(new Flog.RayTracer.Vector(0, 0, -15), new Flog.RayTracer.Vector(-0.2, 0, 5), new Flog.RayTracer.Vector(0, 1, 0));
  scene.background = new Flog.RayTracer.Background(new Flog.RayTracer.Color(0.5, 0.5, 0.5), 0.4);
  var sphere = new Flog.RayTracer.Shape.Sphere(new Flog.RayTracer.Vector(-1.5, 1.5, 2), 1.5, new Flog.RayTracer.Material.Solid(new Flog.RayTracer.Color(0, 0.5, 0.5), 0.3, 0.0, 0.0, 2.0));
  var sphere1 = new Flog.RayTracer.Shape.Sphere(new Flog.RayTracer.Vector(1, 0.25, 1), 0.5, new Flog.RayTracer.Material.Solid(new Flog.RayTracer.Color(0.9, 0.9, 0.9), 0.1, 0.0, 0.0, 1.5));
  var plane = new Flog.RayTracer.Shape.Plane(new Flog.RayTracer.Vector(0.1, 0.9, -0.5).normalize(), 1.2, new Flog.RayTracer.Material.Chessboard(new Flog.RayTracer.Color(1, 1, 1), new Flog.RayTracer.Color(0, 0, 0), 0.2, 0.0, 1.0, 0.7));
  scene.shapes.push(plane); scene.shapes.push(sphere); scene.shapes.push(sphere1);
  var light = new Flog.RayTracer.Light(new Flog.RayTracer.Vector(5, 10, -1), new Flog.RayTracer.Color(0.8, 0.8, 0.8));
  var light1 = new Flog.RayTracer.Light(new Flog.RayTracer.Vector(-3, 5, -15), new Flog.RayTracer.Color(0.8, 0.8, 0.8), 100);
  scene.lights.push(light); scene.lights.push(light1);
  var raytracer = new Flog.RayTracer.Engine({ canvasWidth: size, canvasHeight: size, pixelWidth: 1, pixelHeight: 1, renderDiffuse: true, renderHighlights: true, renderShadows: true, renderReflections: true, rayDepth: 2 });
  raytracer.renderScene(scene);
  return raytracer;
}
var r = renderScene(10);
var chars = " .:-=+*#%@";
for (var y = 0; y < 10; y += 2) {
  var line = "";
  for (var x = 0; x < 10; x++) line += chars[Math.floor(r.rows[y * 10 + x] * 10 / 256)];
  console.log("|" + line + "|");
}
console.log("checksum", r.checksum, "pixels", r.rows.length);
"""
    check(js, golden, "raytrace", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_earley_boyer_lists_and_closures(js, golden, tier):
    """CATCHES: Cons-list traversal, instanceof checks, closures captured by sc_map callbacks and the Earley chart's memoised counting that the compiled tiers get wrong, visible as wrong tautology verdicts, rewrites, or Catalan parse counts."""
    code = r"""
// Scaled-down EarleyBoyer flavour: Scheme-style cons lists, closures, a Boyer rewriter and an Earley parser.
function sc_Pair(car, cdr) { this.car = car; this.cdr = cdr; }
sc_Pair.prototype.toString = function () {
  var parts = [], p = this;
  while (p instanceof sc_Pair) { parts.push(sc_toStr(p.car)); p = p.cdr; }
  return "(" + parts.join(" ") + (p === null ? "" : " . " + sc_toStr(p)) + ")";
};
function sc_toStr(x) { return x === null ? "()" : (typeof x === "string" ? x.slice(1) : String(x)); }
function sc_cons(a, b) { return new sc_Pair(a, b); }
function sc_list() { var r = null; for (var i = arguments.length - 1; i >= 0; i--) r = new sc_Pair(arguments[i], r); return r; }
function sc_isPair(x) { return x instanceof sc_Pair; }
function sc_length(l) { var n = 0; while (l !== null) { n++; l = l.cdr; } return n; }
function sc_reverse(l) { var r = null; while (l !== null) { r = new sc_Pair(l.car, r); l = l.cdr; } return r; }
function sc_append(a, b) { if (a === null) return b; return new sc_Pair(a.car, sc_append(a.cdr, b)); }
function sc_map(f, l) { var r = null; while (l !== null) { r = new sc_Pair(f(l.car), r); l = l.cdr; } return sc_reverse(r); }
function sc_assq(k, al) { while (al !== null) { if (al.car.car === k) return al.car; al = al.cdr; } return false; }
function sc_member(x, l) { while (l !== null) { if (sc_isEqual(x, l.car)) return l; l = l.cdr; } return false; }
function sc_isEqual(a, b) {
  if (a === b) return true;
  if (a instanceof sc_Pair && b instanceof sc_Pair) return sc_isEqual(a.car, b.car) && sc_isEqual(a.cdr, b.cdr);
  return false;
}
var symtab = Object.create(null);
function sym(name) { return symtab[name] || (symtab[name] = "ẜ" + name); }
// Parse a tiny s-expression reader.
function read(src) {
  var pos = 0;
  function skip() { while (pos < src.length && src.charCodeAt(pos) <= 32) pos++; }
  function item() {
    skip();
    if (src[pos] === "(") {
      pos++; var items = [];
      for (;;) { skip(); if (src[pos] === ")") { pos++; break; } items.push(item()); }
      var r = null; for (var i = items.length - 1; i >= 0; i--) r = sc_cons(items[i], r); return r;
    }
    var start = pos;
    while (pos < src.length && src[pos] !== "(" && src[pos] !== ")" && src.charCodeAt(pos) > 32) pos++;
    var tok = src.slice(start, pos);
    return /^-?\d+$/.test(tok) ? parseInt(tok, 10) : sym(tok);
  }
  return item();
}
// ---- Boyer ----
var lemmas = Object.create(null);
function addLemma(term) {
  var head = term.cdr.car.car;
  lemmas[head] = sc_cons(term, lemmas[head] || null);
}
[
  "(equal (if (if a b c) d e) (if a (if b d e) (if c d e)))",
  "(equal (and p q) (if p (if q (t) (f)) (f)))",
  "(equal (or p q) (if p (t) (if q (t) (f))))",
  "(equal (not p) (if p (f) (t)))",
  "(equal (implies p q) (if p (if q (t) (f)) (t)))",
  "(equal (iff x y) (and (implies x y) (implies y x)))",
  "(equal (plus (plus x y) z) (plus x (plus y z)))",
  "(equal (times x (plus y z)) (plus (times x y) (times x z)))",
  "(equal (times (times x y) z) (times x (times y z)))",
  "(equal (append (append x y) z) (append x (append y z)))",
  "(equal (reverse (append a b)) (append (reverse b) (reverse a)))",
  "(equal (lessp (remainder x y) y) (not (zerop y)))",
  "(equal (zerop x) (or (equal x (zero)) (not (numberp x))))",
  "(equal (eqp x y) (equal (fix x) (fix y)))"
].forEach(function (s) { addLemma(read(s)); });
var unifySubst = null;
function applySubst(alist, term) {
  if (!sc_isPair(term)) { var t = sc_assq(term, alist); return t ? t.cdr : term; }
  return sc_cons(term.car, sc_map(function (x) { return applySubst(alist, x); }, term.cdr));
}
function oneWayUnify(term1, term2) { unifySubst = null; return oneWayUnify1(term1, term2); }
function oneWayUnify1(term1, term2) {
  if (!sc_isPair(term2)) {
    var temp = sc_assq(term2, unifySubst);
    if (temp) return sc_isEqual(term1, temp.cdr);
    if (typeof term2 === "number") return term1 === term2;
    unifySubst = sc_cons(sc_cons(term2, term1), unifySubst);
    return true;
  }
  if (!sc_isPair(term1)) return false;
  if (term1.car !== term2.car) return false;
  var l1 = term1.cdr, l2 = term2.cdr;
  while (l1 !== null && l2 !== null) { if (!oneWayUnify1(l1.car, l2.car)) return false; l1 = l1.cdr; l2 = l2.cdr; }
  return l1 === null && l2 === null;
}
var rewriteCount = 0;
function rewrite(term) {
  rewriteCount++;
  if (!sc_isPair(term)) return term;
  return rewriteWithLemmas(sc_cons(term.car, sc_map(rewrite, term.cdr)), lemmas[term.car] || null);
}
function rewriteWithLemmas(term, lst) {
  while (lst !== null) {
    if (oneWayUnify(term, lst.car.cdr.car)) return rewrite(applySubst(unifySubst, lst.car.cdr.cdr.car));
    lst = lst.cdr;
  }
  return term;
}
var T = read("(t)"), F = read("(f)");
function truep(x, lst) { return sc_isEqual(x, T) || sc_member(x, lst) !== false; }
function falsep(x, lst) { return sc_isEqual(x, F) || sc_member(x, lst) !== false; }
function tautologyp(x, trueLst, falseLst) {
  if (truep(x, trueLst)) return true;
  if (falsep(x, falseLst)) return false;
  if (!sc_isPair(x)) return false;
  if (x.car === sym("if")) {
    var test = x.cdr.car, yes = x.cdr.cdr.car, no = x.cdr.cdr.cdr.car;
    if (truep(test, trueLst)) return tautologyp(yes, trueLst, falseLst);
    if (falsep(test, falseLst)) return tautologyp(no, trueLst, falseLst);
    return tautologyp(yes, sc_cons(test, trueLst), falseLst) && tautologyp(no, trueLst, sc_cons(test, falseLst));
  }
  return false;
}
function tautp(x) { return tautologyp(rewrite(x), null, null); }
var theorems = [
  "(implies (and (implies a b) (implies b c)) (implies a c))",
  "(implies (and a b) (or a c))",
  "(implies (and p q) (and q p))",
  "(implies (or a b) a)",
  "(implies (not (not p)) p)",
  "(implies (and p (implies p q)) q)"
];
var boyerOut = [];
for (var round = 0; round < 2; round++) {
  for (var i = 0; i < theorems.length; i++) {
    var res = tautp(read(theorems[i]));
    if (round === 1) boyerOut.push(res ? "T" : "F");
  }
}
console.log("boyer", boyerOut.join(""), "rewrites", rewriteCount);
console.log("rewritten", rewrite(read("(times a (plus b (plus c d)))")).toString());
console.log("rev", rewrite(read("(reverse (append (append x y) z))")).toString());
// ---- Earley ----
function makeParser(grammar) {
  var prods = [], start = grammar.car.car;
  for (var g = grammar; g !== null; g = g.cdr) {
    var lhs = g.car.car;
    for (var alts = g.car.cdr; alts !== null; alts = alts.cdr) prods.push({ lhs: lhs, rhs: alts.car });
  }
  function isNonterminal(x) { for (var p = 0; p < prods.length; p++) if (prods[p].lhs === x) return true; return false; }
  return function parse(input) {
    var n = input.length, sets = [];
    for (var i = 0; i <= n; i++) sets.push([]);
    function add(set, prod, rest, start) {
      for (var k = 0; k < set.length; k++) {
        var o = set[k];
        if (o.prod === prod && o.rest === rest && o.start === start) return;
      }
      set.push({ prod: prod, rest: rest, start: start });
    }
    for (var p = 0; p < prods.length; p++) if (prods[p].lhs === start) add(sets[0], prods[p], prods[p].rhs, 0);
    var done = Object.create(null);
    for (var i = 0; i <= n; i++) {
      var set = sets[i];
      for (var j = 0; j < set.length; j++) {
        var it = set[j];
        if (it.rest === null) {
          done[it.prod.lhs + "@" + it.start + ":" + i] = true;
          var from = sets[it.start];
          for (var k = 0; k < from.length; k++) {
            var w = from[k];
            if (w.rest !== null && w.rest.car === it.prod.lhs) add(set, w.prod, w.rest.cdr, w.start);
          }
        } else {
          var next = it.rest.car;
          if (isNonterminal(next)) {
            for (var p = 0; p < prods.length; p++) if (prods[p].lhs === next) add(set, prods[p], prods[p].rhs, i);
          } else if (i < n && input[i] === next) {
            add(sets[i + 1], it.prod, it.rest.cdr, it.start);
          }
        }
      }
    }
    var memo = Object.create(null);
    function count(x, i, j) {
      if (!isNonterminal(x)) return (j === i + 1 && input[i] === x) ? 1 : 0;
      var key = x + "@" + i + ":" + j;
      if (!done[key]) return 0;
      if (key in memo) return memo[key];
      var total = 0;
      for (var p = 0; p < prods.length; p++) if (prods[p].lhs === x) total += countSeq(prods[p].rhs, i, j);
      return memo[key] = total;
    }
    function countSeq(l, i, j) {
      if (l === null) return i === j ? 1 : 0;
      var total = 0, last = j - sc_length(l.cdr);
      for (var k = i + 1; k <= last; k++) { var c = count(l.car, i, k); if (c) total += c * countSeq(l.cdr, k, j); }
      return total;
    }
    var items = 0;
    for (var i = 0; i <= n; i++) items += sets[i].length;
    return [items, count(start, 0, n)];
  };
}
var parser = makeParser(read("((s (a) (s s)))"));
var counts = [];
for (var len = 1; len <= 9; len++) {
  var input = []; for (var i = 0; i < len; i++) input.push(sym("a"));
  counts.push(parser(input).join(":"));
}
console.log("earley", counts.join(" "));
var bad = parser([sym("a"), sym("b"), sym("a")]);
console.log("reject", bad.join(":"));
"""
    check(js, golden, "earley", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_splay_tree_insert_and_remove(js, golden, tier):
    """CATCHES: A JIT that mishandles prototype-defaulted left/right fields (SplayTree.Node.prototype.left = null) shadowed by own writes, the top-down splay rotations, or the shift/xor key generator, producing an unsorted or wrongly sized tree."""
    code = r"""
// Scaled-down Splay (V8 benchmark suite): top-down splay tree with payload trees.
var kSplayTreeSize = 300, kSplayTreeModifications = 40, kSplayTreePayloadDepth = 3;
var seed = 49734321;
function nextRandom() {
  // Deterministic replacement for Math.random (same LCG as the V8 suite's base.js).
  seed = ((seed + 0x7ed55d16) + (seed << 12)) & 0xffffffff;
  seed = ((seed ^ 0xc761c23c) ^ (seed >>> 19)) & 0xffffffff;
  seed = ((seed + 0x165667b1) + (seed << 5)) & 0xffffffff;
  seed = ((seed + 0xd3a2646c) ^ (seed << 9)) & 0xffffffff;
  seed = ((seed + 0xfd7046c5) + (seed << 3)) & 0xffffffff;
  seed = ((seed ^ 0xb55a4f09) ^ (seed >>> 16)) & 0xffffffff;
  return (seed & 0xfffffff) / 0x10000000;
}
function GeneratePayloadTree(depth, tag) {
  if (depth == 0) {
    return { array: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], string: 'String for key ' + tag + ' in leaf node' };
  } else {
    return { left: GeneratePayloadTree(depth - 1, tag), right: GeneratePayloadTree(depth - 1, tag) };
  }
}
function GenerateKey() { return nextRandom(); }
function InsertNewNode() {
  var key;
  do { key = GenerateKey(); } while (splayTree.find(key) != null);
  var payload = GeneratePayloadTree(kSplayTreePayloadDepth, String(key));
  splayTree.insert(key, payload);
  return key;
}
function SplaySetup() {
  splayTree = new SplayTree();
  for (var i = 0; i < kSplayTreeSize; i++) InsertNewNode();
}
function SplayRun() {
  for (var i = 0; i < kSplayTreeModifications; i++) {
    var key = InsertNewNode();
    var greatest = splayTree.findGreatestLessThan(key);
    if (greatest == null) splayTree.remove(key);
    else splayTree.remove(greatest.key);
  }
}
function SplayTree() { }
SplayTree.prototype.root_ = null;
SplayTree.prototype.isEmpty = function () { return !this.root_; };
SplayTree.prototype.insert = function (key, value) {
  if (this.isEmpty()) { this.root_ = new SplayTree.Node(key, value); return; }
  this.splay_(key);
  if (this.root_.key == key) return;
  var node = new SplayTree.Node(key, value);
  if (key > this.root_.key) {
    node.left = this.root_;
    node.right = this.root_.right;
    this.root_.right = null;
  } else {
    node.right = this.root_;
    node.left = this.root_.left;
    this.root_.left = null;
  }
  this.root_ = node;
};
SplayTree.prototype.remove = function (key) {
  if (this.isEmpty()) throw Error('Key not found: ' + key);
  this.splay_(key);
  if (this.root_.key != key) throw Error('Key not found: ' + key);
  var removed = this.root_;
  if (!this.root_.left) {
    this.root_ = this.root_.right;
  } else {
    var right = this.root_.right;
    this.root_ = this.root_.left;
    this.splay_(key);
    this.root_.right = right;
  }
  return removed;
};
SplayTree.prototype.find = function (key) {
  if (this.isEmpty()) return null;
  this.splay_(key);
  return this.root_.key == key ? this.root_ : null;
};
SplayTree.prototype.findMax = function (opt_startNode) {
  if (this.isEmpty()) return null;
  var current = opt_startNode || this.root_;
  while (current.right) current = current.right;
  return current;
};
SplayTree.prototype.findGreatestLessThan = function (key) {
  if (this.isEmpty()) return null;
  this.splay_(key);
  if (this.root_.key < key) return this.root_;
  else if (this.root_.left) return this.findMax(this.root_.left);
  else return null;
};
SplayTree.prototype.exportKeys = function () {
  var result = [];
  if (!this.isEmpty()) this.root_.traverse_(function (node) { result.push(node.key); });
  return result;
};
SplayTree.prototype.splay_ = function (key) {
  if (this.isEmpty()) return;
  var dummy, left, right;
  dummy = left = right = new SplayTree.Node(null, null);
  var current = this.root_;
  while (true) {
    if (key < current.key) {
      if (!current.left) break;
      if (key < current.left.key) {
        var tmp = current.left;
        current.left = tmp.right;
        tmp.right = current;
        current = tmp;
        if (!current.left) break;
      }
      right.left = current;
      right = current;
      current = current.left;
    } else if (key > current.key) {
      if (!current.right) break;
      if (key > current.right.key) {
        var tmp = current.right;
        current.right = tmp.left;
        tmp.left = current;
        current = tmp;
        if (!current.right) break;
      }
      left.right = current;
      left = current;
      current = current.right;
    } else {
      break;
    }
  }
  left.right = current.left;
  right.left = current.right;
  current.left = dummy.right;
  current.right = dummy.left;
  this.root_ = current;
};
SplayTree.Node = function (key, value) { this.key = key; this.value = value; };
SplayTree.Node.prototype.left = null;
SplayTree.Node.prototype.right = null;
SplayTree.Node.prototype.traverse_ = function (f) {
  var current = this;
  while (current) {
    var left = current.left;
    if (left) left.traverse_(f);
    f(current);
    current = current.right;
  }
};
var splayTree = null;
SplaySetup();
for (var r = 0; r < 6; r++) SplayRun();
var keys = splayTree.exportKeys();
var sorted = true;
for (var i = 1; i < keys.length; i++) if (!(keys[i - 1] < keys[i])) sorted = false;
var h = 0;
for (var i = 0; i < keys.length; i++) h = (h * 33 + Math.floor(keys[i] * 1e6)) | 0;
var depthMax = 0;
(function walk(n, d) { if (!n) return; if (d > depthMax) depthMax = d; walk(n.left, d + 1); walk(n.right, d + 1); })(splayTree.root_, 0);
console.log("size", keys.length, "sorted", sorted, "hash", h);
console.log("first", keys[0], "last", keys[keys.length - 1]);
console.log("payload", splayTree.findMax().value.left.right.left.string.length > 20, splayTree.root_.value.right.left.right.array.join(""));
console.log("depth<=", depthMax < 300);
"""
    check(js, golden, "splay", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_djot_like_markup_parser(js, golden, tier):
    """CATCHES: String scanning with charCodeAt, slice/indexOf, delimiter stacks, regex exec on suffixes and string concatenation in hot loops that the compiled tiers render differently, changing the HTML or its rolling hash."""
    code = r"""
// Djot-like markup parser: block splitter, inline tokenizer with a delimiter stack, HTML renderer.
var C_STAR = 42, C_UNDER = 95, C_TICK = 96, C_LBRACK = 91, C_RBRACK = 93, C_LPAREN = 40, C_RPAREN = 41, C_BSLASH = 92, C_LT = 60, C_GT = 62, C_AMP = 38, C_LBRACE = 123;
function escapeHtml(s) {
  var out = "", last = 0;
  for (var i = 0; i < s.length; i++) {
    var c = s.charCodeAt(i), rep = null;
    if (c === C_LT) rep = "&lt;"; else if (c === C_GT) rep = "&gt;"; else if (c === C_AMP) rep = "&amp;"; else if (c === 34) rep = "&quot;";
    if (rep !== null) { out += s.slice(last, i) + rep; last = i + 1; }
  }
  return last === 0 ? s : out + s.slice(last);
}
function Tokenizer(src) { this.src = src; this.pos = 0; this.tokens = []; this.stack = []; }
Tokenizer.prototype.text = function (s) {
  var t = this.tokens, n = t.length;
  if (n > 0 && t[n - 1].type === "text") t[n - 1].value += s; else t.push({ type: "text", value: s });
};
Tokenizer.prototype.openOrClose = function (c, kind) {
  for (var k = this.stack.length - 1; k >= 0; k--) {
    if (this.stack[k].c === c) {
      var opener = this.stack[k];
      this.tokens[opener.index] = { type: "open", kind: kind };
      this.tokens.push({ type: "close", kind: kind });
      this.stack.length = k;
      return;
    }
  }
  this.stack.push({ c: c, index: this.tokens.length });
  this.tokens.push({ type: "delim", value: String.fromCharCode(c) });
};
Tokenizer.prototype.run = function () {
  var src = this.src, n = src.length, start = 0;
  while (this.pos < n) {
    var c = src.charCodeAt(this.pos);
    if (c === C_BSLASH && this.pos + 1 < n) {
      if (this.pos > start) this.text(src.slice(start, this.pos));
      this.text(src[this.pos + 1]); this.pos += 2; start = this.pos; continue;
    }
    if (c === C_STAR || c === C_UNDER || c === C_TICK || c === C_LBRACK) {
      if (this.pos > start) this.text(src.slice(start, this.pos));
      if (c === C_TICK) {
        var end = src.indexOf("`", this.pos + 1);
        if (end < 0) { this.text("`"); this.pos++; }
        else { this.tokens.push({ type: "code", value: src.slice(this.pos + 1, end) }); this.pos = end + 1; }
      } else if (c === C_LBRACK) {
        var m = /^\[([^\]]*)\]\(([^)]*)\)/.exec(src.slice(this.pos));
        if (m) { this.tokens.push({ type: "link", text: m[1], href: m[2] }); this.pos += m[0].length; }
        else { this.text("["); this.pos++; }
      } else {
        this.openOrClose(c, c === C_STAR ? "strong" : "em"); this.pos++;
      }
      start = this.pos;
      continue;
    }
    this.pos++;
  }
  if (n > start) this.text(src.slice(start));
  return this.tokens;
};
function renderInline(src) {
  var toks = new Tokenizer(src).run(), out = [];
  for (var i = 0; i < toks.length; i++) {
    var t = toks[i];
    switch (t.type) {
      case "text": case "delim": out.push(escapeHtml(t.value)); break;
      case "open": out.push("<" + t.kind + ">"); break;
      case "close": out.push("</" + t.kind + ">"); break;
      case "code": out.push("<code>" + escapeHtml(t.value) + "</code>"); break;
      case "link": out.push('<a href="' + escapeHtml(t.href) + '">' + renderInline(t.text) + "</a>"); break;
    }
  }
  return out.join("");
}
function parseAttrs(line) {
  var m = /\{([^}]*)\}\s*$/.exec(line), attrs = "";
  if (!m) return [line, ""];
  var parts = m[1].trim().split(/\s+/), classes = [];
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i];
    if (p.charCodeAt(0) === 35) attrs += ' id="' + p.slice(1) + '"';
    else if (p.charCodeAt(0) === 46) classes.push(p.slice(1));
    else { var eq = p.indexOf("="); if (eq > 0) attrs += " " + p.slice(0, eq) + '="' + p.slice(eq + 1) + '"'; }
  }
  if (classes.length) attrs += ' class="' + classes.join(" ") + '"';
  return [line.slice(0, m.index).replace(/\s+$/, ""), attrs];
}
function renderDoc(doc) {
  var lines = doc.split("\n"), html = [], para = [], list = null, quote = [];
  function flushPara() { if (para.length) { html.push("<p>" + renderInline(para.join(" ")) + "</p>"); para = []; } }
  function flushList() { if (list) { html.push("<ul>" + list.map(function (it) { return "<li>" + renderInline(it) + "</li>"; }).join("") + "</ul>"); list = null; } }
  function flushQuote() { if (quote.length) { html.push("<blockquote>" + renderDoc(quote.join("\n")) + "</blockquote>"); quote = []; } }
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (line.charCodeAt(0) === C_GT) { flushPara(); flushList(); quote.push(line.replace(/^> ?/, "")); continue; }
    flushQuote();
    if (/^\s*$/.test(line)) { flushPara(); flushList(); continue; }
    var h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      flushPara(); flushList();
      var pa = parseAttrs(h[2]);
      html.push("<h" + h[1].length + pa[1] + ">" + renderInline(pa[0]) + "</h" + h[1].length + ">");
      continue;
    }
    if (line.startsWith("- ")) { flushPara(); (list || (list = [])).push(line.slice(2)); continue; }
    para.push(line.trim());
  }
  flushPara(); flushList(); flushQuote();
  return html.join("\n");
}
var doc = [
  "# Lumen *notes* {#top .title}",
  "",
  "Some _emphasis_, some *strong* and `code <b>` with a [link *here*](http://x.test/?a=1&b=2).",
  "Escaped \\*stars\\* and an unclosed _underscore and a [bracket.",
  "",
  "- first *item*",
  "- second `item`",
  "- third [l](u)",
  "",
  "> quoted *text*",
  "> # inner heading",
  "",
  "## Tail {.a .b data-x=1}",
  "final \"para\" & done"
].join("\n");
var html = "", total = 0, h = 0;
for (var round = 0; round < 40; round++) {
  html = renderDoc(doc + "\nround " + round + " _r_");
  total += html.length;
  for (var i = 0; i < html.length; i++) h = (h * 31 + html.charCodeAt(i)) | 0;
}
console.log(html);
console.log("total", total, "hash", h);
"""
    check(js, golden, "djot", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_numeric_chains_over_many_arrays(js, golden, tier):
    """CATCHES: Register-resident numeric chains that read three or more arrays in one expression (exhausting the pinned mirror registers), overwrite or increment a local that held an array receiver, or keep a stale mirror after holes, strings, accessors or out-of-range indices appear."""
    code = r"""
function four(a, b, c, d, i) { return a[i] * b[i] + c[i] - d[i] + c[i + 1] * d[i + 1]; }
function fourSet(a, b, c, d, e, i) { e[i] = a[i] + b[i] * c[i] - d[i]; e[i + 1] = c[i] + d[i + 1]; return e[i] + e[i + 1]; }
function rebind(a, i) { a = a[i] + a[i + 1] * 2; return a; }
function bump(a, i) { var s = a[i] * 3 + a[i + 1]; a++; return s + (a !== a ? 1 : 0); }
function keyed(a, b, c, k) { return a[k] + b[k] - c[k] * a[k + 1] + b[k + 2]; }
var A = [1, 2, 3, 4, 5, 6, 7, 8], B = [8, 7, 6, 5, 4, 3, 2, 1], C = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5], D = [3, 1, 4, 1, 5, 9, 2, 6], E = new Array(8).fill(0);
var s = 0;
for (var r = 0; r < 300; r++) {
  var i = r % 6;
  s += four(A, B, C, D, i) + fourSet(A, B, C, D, E, i) + rebind(A, i) + bump(B, i) + keyed(A, B, C, i % 5);
}
console.log("sum " + s + " E=" + E.join(","));
// Leave the fast path: holes, strings, getters and out-of-range indices.
var H = [1, , 3, 4, 5, 6, 7, 8]; var S = ["1", "2", "3", "4", "5", "6", "7", "8"];
var G = [1, 2, 3, 4, 5, 6, 7, 8]; Object.defineProperty(G, 2, { get: function () { return 100; } });
console.log(four(H, B, C, D, 0), four(A, S, C, D, 1), four(A, B, G, D, 2), four(A, B, C, D, 7), fourSet(A, B, C, D, H, 1), rebind(S, 0), bump(S, 2), keyed(A, B, C, 6));
var F = new Float64Array([1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5]);
console.log(four(F, F, F, F, 3), keyed(F, A, F, 2), H.join(","));
"""
    check(js, golden, "chains", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_loop_regions_with_near_miss_shapes(js, golden, tier):
    """CATCHES: Linear loop planning that accepts bodies it cannot lower (discarded expression values, boolean stores, nesting deeper than eight operands, five array receivers, a reassigned receiver, ten float or eleven int accumulators, non-index constant keys, two exits) and computes a different result from the interpreter."""
    code = r"""
function popBody(a, n) { var s = 0; for (var i = 0; i < n; i++) { s + a[i]; s += a[i]; } return s; }
function boolStore(a, b, n) { for (var i = 0; i < n; i++) b[i] = a[i] < 3; return b.join(""); }
function deep(a, b, c, d, n) { var s = 0; for (var i = 0; i < n; i++) s += a[i] * (b[i] * (c[i] * (d[i] * (a[i + 1] * (b[i + 1] * (c[i + 1] * (d[i + 1] * (a[i + 2] + 1)))))))); return s; }
function five(a, b, c, d, e, n) { var s = 0; for (var i = 0; i < n; i++) s += a[i] + b[i] + c[i] + d[i] + e[i]; return s; }
function storedRecv(a, b, n) { var s = 0; for (var i = 0; i < n; i++) { s += a[i]; a = b; } return s; }
function manyFloats(a, n) {
  var f0 = 0.5, f1 = 1.5, f2 = 2.5, f3 = 3.5, f4 = 4.5, f5 = 5.5, f6 = 6.5, f7 = 7.5, f8 = 8.5, f9 = 9.5;
  for (var i = 0; i < n; i++) { f0 += a[i] * 0.5; f1 += f0 * 0.25; f2 += f1 * 0.5; f3 += f2 * 0.5; f4 += f3 * 0.5; f5 += f4 * 0.5; f6 += f5 * 0.5; f7 += f6 * 0.5; f8 += f7 * 0.5; f9 += f8 * 0.5; }
  return f9;
}
function manyInts(a, n) {
  var k0 = 0, k1 = 1, k2 = 2, k3 = 3, k4 = 4, k5 = 5, k6 = 6, k7 = 7, k8 = 8, k9 = 9, k10 = 10;
  for (var i = 0; i < n; i++) { k0 = (k0 + a[i]) | 0; k1 = (k1 + k0) | 0; k2 = (k2 + k1) | 0; k3 = (k3 + k2) | 0; k4 = (k4 + k3) | 0; k5 = (k5 + k4) | 0; k6 = (k6 + k5) | 0; k7 = (k7 + k6) | 0; k8 = (k8 + k7) | 0; k9 = (k9 + k8) | 0; k10 = (k10 + k9) | 0; }
  return k10;
}
function wide(a, n) { var s = 0; for (var i = 0; i < n; i++) s += (a[i] + 1) * (a[i] + 2) * (a[i] + 3) - (a[i] + 4) * (a[i] + 5) * (a[i] + 6) + (a[i] + 7) * (a[i] + 8) * (a[i] + 9); return s; }
function constKeys(a, n) { var s = 0; for (var i = 0; i < n; i++) s += a[i] + a[1.5] + a[-1] + a[4294967296]; return s; }
function counterConst(a, n) { var s = 0, j = 0; for (var i = 0; i < n; i++) { s += a[j]; j = 2; } return s + j; }
function nonIntStore(a, n) { var s = 0, x = 0; for (var i = 0; i < n; i++) { x = a[i] / 3; s += x; } return s + x; }
function twoExits(a, n) { var i = 0; while (i < n) { if (a[i] === 7) break; i++; } return i; }
var A = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], B = A.map(function (x) { return x * 2; }), C = A.map(function (x) { return x - 0.5; }), D = A.slice().reverse(), E = A.map(function (x) { return x & 3; });
var out = [];
for (var r = 0; r < 40; r++) {
  out = [popBody(A, 10), boolStore(A, [], 10), deep(A, B, C, D, 9), five(A, B, C, D, E, 12), storedRecv(A, B, 10), manyFloats(C, 12), manyInts(A, 12), wide(C, 12), constKeys(A, 10), counterConst(A, 10), nonIntStore(A, 12), twoExits(A, 12)];
}
var names = ["pop", "boolStore", "deep", "five", "storedRecv", "manyFloats", "manyInts", "wide", "constKeys", "counterConst", "nonIntStore", "twoExits"];
console.log(names.map(function (n, k) { return n + "=" + out[k]; }).join("\n"));
var H = [1, 2, , 4, 5, 6, 7, 8, 9, 10, 11, 12], S = A.map(String);
console.log("holey " + [popBody(H, 10), five(A, B, H, D, E, 12), manyFloats(H, 12), manyInts(S, 12), twoExits(H, 12)].join(" "));
"""
    check(js, golden, "loop_shapes", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_worker_fill_diamonds_and_linked_scans(js, golden, tier):
    """CATCHES: The numeric-diamond and linked-scan regions (Worker-style counter wrap and Packet.addTo-style tail walks) applied to near-miss variants: a different stored field, non-integer threshold or reset, a string loop limit, a prototype-held array, an undefined sentinel or a strict null test."""
    code = r"""
var LIMIT = 6, LIMIT_S = "6";
function W(seed) { this.v2 = seed; this.other = 3; this.out = new Array(8).fill(0); }
W.prototype.fill = function (pk) { for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; pk.a2[i] = this.v2; } return this.fmt(pk); };
W.prototype.fillOther = function (pk) { for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; pk.a2[i] = this.other; } return this.fmt(pk); };
W.prototype.fillHalf = function (pk) { for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26.5) this.v2 = 1; pk.a2[i] = this.v2; } return this.fmt(pk); };
W.prototype.fillReset = function (pk) { for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 0.5; pk.a2[i] = this.v2; } return this.fmt(pk); };
W.prototype.fillStr = function (pk) { for (var i = 0; i < LIMIT_S; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; pk.a2[i] = this.v2; } return this.fmt(pk); };
function P(seed) { this.v2 = seed; }
function Pk() { this.a2 = new Array(8).fill(0); }
function ProtoPk() {}
ProtoPk.prototype.a2 = new Array(8).fill(0);
P.prototype.fill = W.prototype.fill;
W.prototype.fmt = P.prototype.fmt = function (pk) { return pk.a2.join(","); };
function Node(id, link) { this.id = id; this.link = link; }
function tailOf(head) { var peek, next = head; while ((peek = next.link) != undefined) next = peek; return next.id; }
function tailStrict(head) { var peek, next = head; while ((peek = next.link) !== null) next = peek; return next.id; }
var list = null; for (var k = 0; k < 12; k++) list = new Node(k, list);
function drive() {
var res = [];
for (var r = 0; r < 130; r++) {
  var w = new W(r % 30), p = new P(r % 29);
  res = [w.fill(new Pk()), w.fillOther(new Pk()), w.fillHalf(new Pk()), w.fillReset(new Pk()), w.fillStr(new Pk()), p.fill(new ProtoPk()), tailOf(list), tailStrict(list)];
}
return res;
}
console.log(drive().join("\n"));
var u = new Node(99, undefined), l2 = new Node(5, new Node(6, u));
console.log(tailOf(l2), tailStrict(new Node(1, new Node(2, null))));
"""
    check(js, golden, "diamonds", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_wide_frames_deep_recursion_and_pending_operands(js, golden, tier):
    """CATCHES: Compiled calls into functions, closures and constructors whose frames exceed the pooled 256-slot buffer, deep recursion that overflows the frame pool, or exceptions thrown with operands still pending on the stack, that corrupt locals, mis-count references held by a constructor's locals, or report the wrong error."""
    n = 270
    code = "\n".join([
        "function wide(a, b) {",
        chain_vars("v", "(a * 7 + b) % 9973", n),
        f"  if (a === -1) throw new RangeError('wide ' + v{n - 1});",
        f"  return v{n - 1} + v{n // 2};",
        "}",
        "function makeWide(k) {",
        "  var hits = 0;",
        "  return function (a) {",
        chain_vars("w", "(a + k) % 9973", n),
        "    hits++;",
        f"    if (a === -1) throw new TypeError('closure ' + w{n - 1} + ' ' + hits);",
        f"    return w{n - 1} * 2 + hits;",
        "  };",
        "}",
        "function Wide(a, o) {",
        "  var keep = o;",
        chain_vars("u", "(a * 5) % 9973", n),
        f"  if (a === -1) throw new Error('ctor ' + u{n - 1} + ' ' + keep.tag);",
        f"  this.v = u{n - 1};",
        "  this.o = keep;",
        "}",
    ]) + r"""
function drive(n) {
  var s = 0, f = makeWide(3), shared = { tag: "shared" }, objs = [];
  for (var i = 0; i < n; i++) {
    s = (s + wide(i, i & 7)) % 1000003;
    s = (s + f(i)) % 1000003;
    var w = new Wide(i, shared);
    s = (s + w.v) % 1000003;
    if (i % 25 === 0) objs.push(w);
  }
  return s + " objs=" + objs.length + " same=" + (objs[1].o === shared) + " last=" + objs[objs.length - 1].v;
}
console.log("drive " + drive(60));
console.log("drive " + drive(30));
var f2 = makeWide(11);
var errs = [];
for (var t = 0; t < 3; t++) {
  try { wide(-1, t); } catch (e) { errs.push(e.name + ":" + e.message); }
  try { f2(-1); } catch (e) { errs.push(e.name + ":" + e.message); }
  try { new Wide(-1, { tag: "t" + t }); } catch (e) { errs.push(e.name + ":" + e.message); }
}
console.log(errs.join("\n"));
function depth(n) { if (n === 0) return 0; var x = n * 2; return depth(n - 1) + (x & 3); }
function boom(x) { if (x > 3) throw new Error("boom " + x); return x; }
function pending(a, b) { return a + b * boom(a) + boom(b); }
function nested(k) { var o = { a: k }; return [o.a, pending(k, k + 1), o.a + 1]; }
var d = 0; for (var r = 0; r < 40; r++) d += depth(150);
console.log("depth " + d);
var caught = [];
for (var i = 0; i < 30; i++) { try { caught.push(nested(i % 6).join("/")); } catch (e) { caught.push(e.message); } }
console.log(caught.slice(0, 8).join(" | "));
"""
    check(js, golden, "wide_frames", code, tier)
