"""Optimizer-targeted code shapes across execution tiers: the shapes the bytecode compiler and the
native JIT specialise (scheduler/linked-list regions, guarded write regions, mixed object loops,
numeric CFG loops, inlined methods/closures, iterator entries, destructuring, call spread,
collection helpers, for-in, switch, parameter defaults, write strictness), each warmed past
tier-up and then perturbed. Every program runs on the default JIT tier, --tier=bytecode and
--tier=interp and must match ONE shared golden, so a divergent tier is caught."""
import pytest

from conftest import check_script, resources_for

G = resources_for(__file__)
TIERS = [pytest.param([], id="jit"), pytest.param(["--tier=bytecode"], id="bytecode"),
         pytest.param(["--tier=interp"], id="interp")]
tiers = pytest.mark.parametrize("cli", TIERS)


@tiers
def test_richards_scheduler(run, workdir, cli):
    """CATCHES: a JIT/bytecode tier whose specialised Richards scheduler regions (task dispatch, packet
    queue linked-list scan, hold/suspend/release state bits) compute different queue/hold
    counts, or that keeps using stale inlined prototype methods or globals after a state getter,
    a replaced prototype method, a replaced addTo and changed global constants."""
    check_script(run, workdir, G, "richards_scheduler", r'''
var COUNT = 150;
var ID_IDLE = 0, ID_WORKER = 1, ID_HANDLER_A = 2, ID_HANDLER_B = 3, ID_DEVICE_A = 4, ID_DEVICE_B = 5, NUMBER_OF_IDS = 6;
var KIND_DEVICE = 0, KIND_WORK = 1;
var STATE_RUNNING = 0, STATE_RUNNABLE = 1, STATE_SUSPENDED = 2, STATE_HELD = 4;
var STATE_SUSPENDED_RUNNABLE = STATE_SUSPENDED | STATE_RUNNABLE;
var STATE_NOT_HELD = ~STATE_HELD;
var DATA_SIZE = 4;

function runRichards() {
  var scheduler = new Scheduler();
  scheduler.addIdleTask(ID_IDLE, 0, null, COUNT);
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
  scheduler.schedule();
  return scheduler;
}

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
  this.addTask(id, priority, queue, new DeviceTask(this));
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
IdleTask.prototype.toString = function () { return "IdleTask"; };

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
DeviceTask.prototype.toString = function () { return "DeviceTask"; };

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
WorkerTask.prototype.toString = function () { return "WorkerTask"; };

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
HandlerTask.prototype.toString = function () { return "HandlerTask"; };

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
Packet.prototype.toString = function () { return "Packet"; };


var log = [];
for (var r = 0; r < 112; r++) {
  COUNT = r === 0 ? 150 : 12 + (r % 3);
  var s = runRichards();
  if (r % 37 === 0 || r === 111) log.push(r + ':' + s.queueCount + '/' + s.holdCount);
}
console.log('warm', log.join(' '));
// After warm-up: a state getter on one block reached from the hot scheduler loop.
var reads = 0;
var block = new TaskControlBlock(null, ID_IDLE, 1, null, {});
Object.defineProperty(block, 'state', { get: function () { reads++; return STATE_HELD; } });
var sched = new Scheduler();
sched.list = block;
sched.schedule();
console.log('getter state reads', reads, 'current', sched.currentTcb);
// Replace a hot prototype method and add a field to Packet instances mid-run.
var held = 0;
var original = TaskControlBlock.prototype.isHeldOrSuspended;
TaskControlBlock.prototype.isHeldOrSuspended = function () { held++; return original.call(this); };
s = runRichards();
console.log('patched', s.queueCount, s.holdCount, held > 0, String(s.blocks[ID_WORKER]), String(s.blocks[ID_DEVICE_B]));
TaskControlBlock.prototype.isHeldOrSuspended = original;
Packet.prototype.addTo = function (queue) {
  this.link = null;
  if (queue == null) return this;
  var n = 1, next = queue;
  while (next.link != null) { next = next.link; n++; }
  next.link = this;
  this.depth = n;
  return queue;
};
s = runRichards();
console.log('addTo replaced', s.queueCount, s.holdCount);
COUNT = 77; DATA_SIZE = 3;
s = runRichards();
console.log('globals changed', s.queueCount, s.holdCount);
''', cli=cli)


@tiers
def test_deltablue_constraints(run, workdir, cli):
    """CATCHES: a compiled tier that miscomputes the DeltaBlue constraint planner (inheritsFrom
    prototype chains, polymorphic execute/recalculate/isSatisfied calls, Strength switch,
    ScaleConstraint guarded numeric writes v2.value = v1.value*scale+offset), or that keeps a
    stale specialised write after Direction, variable shapes or a value accessor change post
    warm-up (NaN/Infinity/-0 results)."""
    check_script(run, workdir, G, "deltablue_constraints", r'''
var failures = [];
function alert(msg) { failures.push(msg); }
Object.defineProperty(Object.prototype, "inheritsFrom", {
  value: function (shuper) {
    function Inheriter() { }
    Inheriter.prototype = shuper.prototype;
    this.prototype = new Inheriter();
    this.superConstructor = shuper;
  }
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
    if (this.strength == Strength.REQUIRED) alert("Could not satisfy a required constraint!");
    return null;
  }
  this.markInputs(mark);
  var out = this.output();
  var overridden = out.determinedBy;
  if (overridden != null) overridden.markUnsatisfied();
  out.determinedBy = this;
  if (!planner.addPropagate(this, mark)) alert("Cycle encountered");
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
Direction.NONE = 0;
Direction.FORWARD = 1;
Direction.BACKWARD = -1;
function BinaryConstraint(var1, var2, strength) {
  BinaryConstraint.superConstructor.call(this, strength);
  this.v1 = var1;
  this.v2 = var2;
  this.direction = Direction.NONE;
  this.addConstraint();
}
BinaryConstraint.inheritsFrom(Constraint);
BinaryConstraint.prototype.chooseMethod = function (mark) {
  if (this.v1.mark == mark) {
    this.direction = (this.v2.mark != mark && Strength.stronger(this.strength, this.v2.walkStrength))
      ? Direction.FORWARD : Direction.NONE;
  }
  if (this.v2.mark == mark) {
    this.direction = (this.v1.mark != mark && Strength.stronger(this.strength, this.v1.walkStrength))
      ? Direction.BACKWARD : Direction.NONE;
  }
  if (Strength.weaker(this.v1.walkStrength, this.v2.walkStrength)) {
    this.direction = Strength.stronger(this.strength, this.v1.walkStrength) ? Direction.BACKWARD : Direction.NONE;
  } else {
    this.direction = Strength.stronger(this.strength, this.v2.walkStrength) ? Direction.FORWARD : Direction.BACKWARD;
  }
};
BinaryConstraint.prototype.addToGraph = function () {
  this.v1.addConstraint(this);
  this.v2.addConstraint(this);
  this.direction = Direction.NONE;
};
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
function EqualityConstraint(var1, var2, strength) {
  EqualityConstraint.superConstructor.call(this, var1, var2, strength);
}
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
      if (next != determining && next.isSatisfied()) { next.recalculate(); todo.add(next.output()); }
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
  for (var i = 0; i < this.size(); i++) { var c = this.constraintAt(i); c.execute(); }
};
function chainTest(n) {
  planner = new Planner();
  var prev = null, first = null, last = null;
  for (var i = 0; i <= n; i++) {
    var v = new Variable("v" + i);
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
  for (var i = 0; i < 100; i++) {
    first.value = i;
    plan.execute();
    if (last.value != i) alert("Chain test failed.");
  }
  return last.value + ':' + plan.size() + ':' + planner.currentMark;
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
  change(src, 17);
  if (dst.value != 1170) alert("Projection 1 failed");
  change(dst, 1050);
  if (src.value != 5) alert("Projection 2 failed");
  change(scale, 5);
  for (var i = 0; i < n - 1; i++) if (dests.at(i).value != i * 5 + 1000) alert("Projection 3 failed");
  change(offset, 2000);
  for (var i = 0; i < n - 1; i++) if (dests.at(i).value != i * 5 + 2000) alert("Projection 4 failed");
  return { src: src, dst: dst, scale: scale, offset: offset, dests: dests };
}
function change(v, newValue) {
  var edit = new EditConstraint(v, Strength.PREFERRED);
  var edits = new OrderedCollection();
  edits.add(edit);
  var plan = planner.extractPlanFromConstraints(edits);
  for (var i = 0; i < 10; i++) { v.value = newValue; plan.execute(); }
  edit.destroyConstraint();
}
var planner = null;
var results = [];
for (var round = 0; round < 8; round++) {
  var chain = chainTest(40);
  var p = projectionTest(40);
  if (round % 4 === 0) results.push(chain + '|' + p.src.value + ',' + p.dst.value + ',' + p.dests.at(7).value + ',' + planner.currentMark);
}
console.log(results.join('\n'));
console.log('failures', failures.length);
var p = projectionTest(10);
change(p.scale, 0);
console.log('scale 0 ->', p.dests.at(3).value, p.dst.value);
change(p.dst, 2500);
console.log('backward /0 ->', p.src.value);
change(p.offset, -0);
change(p.scale, -1);
change(p.src, 0);
console.log('signed zero ->', Object.is(p.dst.value, -0), Object.is(p.dst.value, 0));
change(p.src, NaN);
console.log('NaN ->', p.dst.value, p.dests.at(0).value);
var gets = 0;
var probe = projectionTest(6);
Object.defineProperty(probe.offset, 'value', { get: function () { gets++; return 7; }, set: function (v) { }, configurable: true });
change(probe.src, 3);
console.log('offset getter ->', probe.dst.value, gets > 0);
Direction.FORWARD = 2;
var flipped = projectionTest(4);
console.log('Direction.FORWARD changed ->', flipped.dst.value, flipped.src.value, failures.length > 0);
console.log(failures.slice(0, 3).join(';'));
''', cli=cli)


@tiers
def test_mixed_object_loop(run, workdir, cli):
    """CATCHES: a native mixed object loop (c=a[i]; c.value=c.value+1; sum+=...) that caches element or
    field reads across iterations: missed aliasing writes, a getter installed on an array index
    after warm-up not being called exactly once, frozen/non-writable values being overwritten,
    stale root.child / length / method proofs after the object graph changes, and wrong
    continue/break exits."""
    check_script(run, workdir, G, "mixed_object_loop", r'''
function scan(a, n) { var sum = 0, c; for (var i = 0; i < n; i++) { c = a[i]; c.value = c.value + 1; sum += c.value; } return sum; }
function fresh(n, v) { var a = []; for (var k = 0; k < n; k++) a.push({ value: v === undefined ? k : v }); return a; }
var a = fresh(3000);
console.log('plain', scan(a, 3000), scan(a, 3000), a[0].value, a[2999].value);
var b = fresh(20, 1), calls = 0, snap = '';
Object.defineProperty(b, '10', { get: function () { calls++; snap = b[0].value + '/' + b[9].value; return { value: 3 }; } });
console.log('element getter', scan(b, 20), calls, snap, b[0].value, b[19].value);
// aliasing: every element is the same object that root.child also points to
function scanRoot(a, root) { var total = 0, c; for (var i = 0; i < a.length; i++) { c = a[i]; c.value = c.value + 1; total += root.child.value; } return total; }
function aliases(o, n) { var a = []; for (var i = 0; i < n; i++) a.push(o); return a; }
var root = { child: { value: 1 } }, al = aliases(root.child, 40);
console.log('alias', scanRoot(al, root), root.child.value);
var other = { child: { value: 1 } };
console.log('other root', scanRoot(aliases(other.child, 40), other), other.child.value);
var constant = { child: { value: 9 } };
Object.defineProperty(constant.child, 'value', { writable: false });
console.log('readonly root', scanRoot(aliases(constant.child, 40), constant), constant.child.value);
// the getter swaps root.child to an accessor half way through
var reads = 0, el = fresh(40, 1), r2 = { child: { value: 3 } };
console.log('warm', scanRoot(el, r2));
Object.defineProperty(el, '10', { get: function () {
  Object.defineProperty(r2, 'child', { get: function () { reads++; return { value: 7 }; }, configurable: true });
  return { value: 1 };
}, configurable: true });
console.log('graph change', scanRoot(el, r2), reads);
// length proofs
function scanLen(a, root) { var total = 0, c; for (var i = 0; i < a.length; i++) { c = a[i]; c.value = c.value + 1; total += root.child.length; } return total; }
var big = fresh(1100, 1), lr = { child: [1, 2, 3] };
console.log('len', scanLen(big, lr));
lr.child.push(4, 5);
console.log('len grown', scanLen(big, lr));
var lcalls = 0;
Object.defineProperty(big, '10', { get: function () { lcalls++; lr.child.length = 1; return { value: 1 }; } });
console.log('len shrunk mid-loop', scanLen(big, lr), lcalls);
// method proofs
var proto = { read: function () { return this.value; } };
var mroot = Object.create(proto); mroot.value = 3;
function scanM(a, root) { var total = 0, c; for (var i = 0; i < a.length; i++) { c = a[i]; c.value = c.value + 1; total += root.read(); } return total; }
function invoke(a, root) { return scanM(a, root); }
var ma = fresh(40, 1), acc = 0;
for (var i = 0; i < 300; i++) acc += invoke(ma, mroot);
console.log('method warm', acc, ma[0].value);
proto.read = function () { return this.value + 1; };
console.log('proto method replaced', invoke(ma, mroot));
Object.setPrototypeOf(mroot, { read: function () { return this.value + 2; } });
console.log('prototype swapped', invoke(ma, mroot));
var mg = 0;
Object.defineProperty(mroot, 'read', { get: function () { mg++; return function () { return 9; }; } });
console.log('getter method', invoke(ma, mroot), mg);
// nested loops with continue / break
function nested(a) {
  var sum = 0, c;
  for (var outer = 0; outer < 3; outer++) {
    for (var inner = 0; inner < 1400; inner++) {
      c = a[inner];
      if (inner === 5) continue;
      c.value = c.value + 1;
      sum += c.value;
      if (inner === 1300) break;
    }
  }
  return sum;
}
var na = fresh(1400, 0);
console.log('nested', nested(na), nested(na), na[0].value, na[5].value, na[1300].value, na[1301].value);
// cold call from inside the hot loop
var coldCalls = 0;
function cold(o) { coldCalls++; return 7 + o.value; }
function withCold(a) { var c; for (var i = 0; i < a.length; i++) { c = a[i]; c.value = c.value + 1; if (i === 1300) c.out.value = 100 + cold(c); } }
var ca = []; for (var k = 0; k < 1400; k++) ca.push({ value: 0, out: { value: 0 } });
withCold(ca);
console.log('cold', coldCalls, ca[1300].out.value, ca[1299].out.value, ca[1399].value);
// polymorphic constructors with prototype methods, then a prototype getter
function A() { this.value = 0; } function B() { this.value = 0; }
A.prototype.run = function () { this.value = this.value + 1; };
B.prototype.run = function () { this.value = this.value + 2; };
function execute(a) { for (var i = 0; i < a.length; i++) { var c = a[i]; c.run(); } }
var pa = []; for (var i = 0; i < 12; i++) pa.push(i % 2 ? new A() : new B());
for (var j = 0; j < 300; j++) execute(pa);
console.log('poly', pa[0].value, pa[1].value);
var pg = 0;
Object.defineProperty(A.prototype, 'run', { configurable: true, get: function () { pg++; return function () { this.value += 10; }; } });
execute(pa);
Object.setPrototypeOf(pa[0], { run: function () { this.value += 20; } });
execute(pa);
console.log('poly after', pg, pa[0].value, pa[1].value, pa[2].value);
// strict variant writing to a frozen element throws mid-loop
function strictScan(a, n) { 'use strict'; var c; for (var i = 0; i < n; i++) { c = a[i]; c.value = c.value + 1; } }
var sa = fresh(40, 1);
for (var j = 0; j < 8; j++) strictScan(sa, 40);
Object.freeze(sa[20]);
try { strictScan(sa, 40); } catch (e) { console.log(e.name + ': ' + e.message); }
console.log('strict', sa[0].value, sa[19].value, sa[20].value, sa[21].value);
function sloppyScan(a, n) { var c; for (var i = 0; i < n; i++) { c = a[i]; c.value = c.value + 1; } }
sloppyScan(sa, 40);
console.log('sloppy', sa[0].value, sa[20].value, sa[39].value);
function condScan(a, condition) { for (var i = 0; i < a.length; i++) { var c = a[i]; if (condition) c.value = c.value + 1; else c.value = c.value + 2; } return a[0].value + a[a.length - 1].value; }
var condArr = fresh(128, 0), conds = [true, false, 0, -0, NaN, 1, null, undefined, '', 'x', {}, [], 0n, 5n, Symbol.iterator];
var condOut = [];
for (var i = 0; i < conds.length; i++) condOut.push(condScan(condArr, conds[i]));
console.log('conditions', condOut.join(','));
''', cli=cli)


@tiers
def test_numeric_cfg_loops(run, workdir, cli):
    """CATCHES: a register-allocated numeric loop (forward branches, continue/break, nested loops, do-
    while, multiple backedges) that loses the loop variable or accumulator at an exit,
    mishandles NaN/Infinity/-0 in branch conditions, skips valueOf/string coercion of non-number
    inputs, mixes BigInt with numbers, or reorders side-effecting calls and exceptions thrown
    inside the loop."""
    check_script(run, workdir, G, "numeric_cfg_loops", r'''
function calc(n) {
  var total = 0;
  for (var i = 0; i < n; i++) {
    if (i < 8) { total += 2; continue; }
    if (i > 3000) break;
    if (i < 1000) total -= 1; else total += 3;
  }
  return total * 10000 + i;
}
console.log('calc', calc(5000), calc(4), calc(0), calc(1000.5));
function nested(n) {
  var sum = 0;
  for (var i = 0; i < n; i++) {
    for (var j = 0; j < n; j++) {
      if (j < 20) { sum += i; continue; }
      if (i < 20) { sum -= j; continue; }
      sum += 2;
    }
  }
  return sum;
}
console.log('nested', nested(40), nested(3), nested(-1));
function bottom(n) { var i = 0, sum = 0; do { if (i < 1200) sum += 2; else sum--; i++; } while (i < n); return sum; }
console.log('do-while', bottom(2000), bottom(0), bottom(1));
function cond(n, x) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (x < 0) s += 1; else s += 2; if (x >= 0) s += 4; if (x !== x) s += 8; }
  return s;
}
console.log('cond', [NaN, 1, -1, Infinity, -Infinity, -0, '3', null, undefined].map(function (x) { return cond(3, x); }).join(','));
function zero(n, x) { for (var i = 0; i < n; i++) { if (i < 2) x = -x; else x = x / 1; } return x; }
console.log('signed zero', Object.is(zero(2000, -0), -0), Object.is(zero(2001, 0), 0), 1 / zero(3, 0));
function acc(n, sum) { for (var i = 0; i < n; i++) { if (i < 4) sum++; else sum--; } return sum; }
var vcalls = 0;
console.log('acc', acc('8', 0), acc(8, '0'), acc({ valueOf: function () { vcalls++; return 8; } }, 0), vcalls, typeof acc(8, 0n), acc(8, 0n) === 0n);
console.log('bigint bound', acc(8n, 0), acc(5n, 0));
function mix(n) { var s = 0n; for (var i = 0; i < n; i++) { if (i < 3) s += 1n; else s += i; } return s; }
try { mix(10); } catch (e) { console.log(e.name + ': ' + e.message); }
var effects = 0;
function effect() { effects++; return 2; }
function withCall(n) { var sum = 0; for (var i = 0; i < n; i++) { if (i < 4) sum += effect(); else sum--; } return sum; }
console.log('effect', withCall(8), effects);
function handled(n) {
  var sum = 0;
  try { for (var i = 0; i < n; i++) { if (i > 3) throw 7; else sum++; } }
  catch (e) { sum += e; } finally { sum *= 2; }
  return sum;
}
console.log('handled', handled(8), handled(2));
function overflow(n) {
  var x = 1, y = 2147483600, z = -2147483600, m = 1;
  for (var i = 0; i < n; i++) { if (i & 1) y += 7; else z -= 7; if (i < 31) x *= 2; m = (m * 31 + i) | 0; }
  return [x, y, z, m, y | 0, z | 0, x | 0].join(',');
}
console.log('overflow', overflow(40), overflow(1));
function divmod(n) {
  var s = 0, r = 0;
  for (var i = -n; i <= n; i++) { if (i === 0) continue; s += (100 / i) | 0; r += (-7 % i); }
  return s + ':' + r + ':' + (-7 % 7) + ':' + Object.is(-7 % 7, -0) + ':' + Object.is(0 * -1, -0);
}
console.log('divmod', divmod(9));
function triangle(limit) {
  var count = 0;
  outer: for (var a = 1; a < limit; a++) {
    var b = a;
    while (b < limit) {
      var c2 = a * a + b * b, c = Math.sqrt(c2);
      if (c > limit) continue outer;
      if (c === Math.floor(c)) count++;
      b++;
    }
  }
  return count;
}
console.log('triangles', triangle(60));
function floats(n) { var x = 0.1, s = 0; for (var i = 0; i < n; i++) { s += x; if (s > 1e3) s -= 1e3; } return s; }
console.log('floats', floats(25000), floats(10), 0.1 + 0.2);
function globalsLoop() { var sum = 0; for (var i = 0; i < regionLimit; i++) { if (i < 2) sum += regionWeight; else sum--; } return sum; }
globalThis.regionLimit = 4; globalThis.regionWeight = 2;
var g1 = globalsLoop();
regionLimit = 3; regionWeight = 5;
var g2 = globalsLoop();
var lgets = 0;
Object.defineProperty(globalThis, 'regionLimit', { get: function () { lgets++; return 6; }, configurable: true });
console.log('globals', g1, g2, globalsLoop(), lgets);
delete globalThis.regionLimit;
try { globalsLoop(); } catch (e) { console.log(e.name + ': ' + e.message); }
var SCALE = 3, MASK = 255, OFFSET = 0.5;
function linearGlobals(n) { var s = 0; for (var i = 0; i < n; i++) s = s + (i & MASK) * SCALE + OFFSET; return s; }
var lg = [linearGlobals(1000)];
SCALE = 2.5; lg.push(linearGlobals(1000));
MASK = 'x'; lg.push(linearGlobals(10));
OFFSET = '!'; lg.push(linearGlobals(2));
console.log('linear globals', lg.join(' '));
''', cli=cli)


@tiers
def test_numeric_array_branches(run, workdir, cli):
    """CATCHES: guarded numeric array reads inside branchy loops that ignore holes resolved through
    prototype getters, accessor elements, proxies, typed arrays, non-index keys (1.5, -1, NaN,
    Infinity, -0), array reassignment mid-loop, config objects/receivers/closures feeding the
    loop bound, or that re-run a getter, or evaluate x+(x=...) / x+(x++) aliasing in the wrong
    order."""
    check_script(run, workdir, G, "numeric_array_branches", r'''
function scan(a, n) { var sum = 0; for (var i = 0; i < n; i++) { if (i < 5000) sum += a[i] * 2; else sum -= a[i]; } return sum; }
console.log('fill', scan(new Array(10000).fill(2), 10000), scan([1, 2, 3], 5), scan([1, 2, 3], 3));
function pair(a, b, n) { var sum = 0; for (var i = 0; i < n; i++) { if (i < 2) sum += a[i] * b[i]; else sum -= a[i] * b[i]; } return sum; }
console.log('pair', pair([1, 2, 3], [4, 5, 6], 3), pair([1.5, 2.5], [2, 2], 2), pair([1, 'x'], [1, 1], 2));
function counted(a, n) { var sum = 0, count = 0; for (var i = 0; i < n; i++) { if (i < 10) sum += (++count) * a[i]; else sum--; } return sum * 100 + count; }
var calls = 0, arr = [1, 2, 3], proto = Object.create(Array.prototype);
Object.defineProperty(proto, '3', { get: function () { calls++; arr[0] = 10; return 4; } });
Object.setPrototypeOf(arr, proto);
console.log('proto getter', counted(arr, 4), calls, arr[0]);
function keyed(a, n, key) { var sum = 0; for (var i = 0; i < n; i++) { if (i < 2) sum += a[i]; else sum += a[key]; } return sum; }
var b = [1, 2, 3];
b['1.5'] = 9; b['-1'] = 7; b['NaN'] = 8; b['Infinity'] = 6;
console.log('keys', [1.5, -1, NaN, Infinity, -0, '2', '02', 2.0, 3].map(function (k) { return keyed(b, 3, k); }).join(','));
function plain(a, n) { var sum = 0; for (var i = 0; i < n; i++) { if (i < 2) sum += a[i]; else sum -= a[i]; } return sum; }
var acalls = 0, accessor = [1, 2, 3];
Object.defineProperty(accessor, '1', { get: function () { acalls++; return 2; } });
var proxy = new Proxy([1, 2, 3], { get: function (o, k) { acalls++; return o[k]; } });
var hole = [1, , 3], hproto = Object.create(Array.prototype);
Object.defineProperty(hproto, '1', { get: function () { acalls++; return 20; } });
Object.setPrototypeOf(hole, hproto);
console.log('variants', plain(accessor, 3), acalls, plain(proxy, 3), acalls, plain(new Float64Array([1, 2, 3]), 3),
  plain(new Int8Array([127, -128, 1]), 3), plain(hole, 3), acalls, plain([1, , 3], 3), plain('123', 3));
function reassigned(a, b, n) { var sum = 0; for (var i = 0; i < n; i++) { if (i > 1) a = b; sum += a[i]; } return sum; }
console.log('reassigned', reassigned([1, 2, 3], [4, 5, 6], 3), reassigned([1], [4, 5, 6, 7], 4));
function cfgScan(a, cfg) { var sum = 0; for (var i = 0; i < a.length; i++) { if (i < cfg.pivot) sum += a[i] * cfg.scale; else sum -= a[i]; } return sum; }
var xs = [1, 2, 3, 4];
console.log('cfg', cfgScan(xs, { pivot: 2, scale: 2 }), cfgScan(xs, { unused: 0, pivot: 3, scale: 3 }), cfgScan(xs, Object.freeze({ pivot: 2, scale: 2 })),
  cfgScan(xs, { pivot: '3', scale: '2' }), cfgScan(xs, {}));
function weighted(a) { var sum = 0; for (var i = 0; i < a.length; i++) { if (i < 2) sum += a[i] * a.scale; else sum -= a[i]; } return sum; }
var x = [1, 2], y = [5, 6, 7]; x.scale = 4; y.scale = 9;
var w = [weighted(x), weighted(y), weighted(x)];
y.push(8); w.push(weighted(y)); x.length = 1; w.push(weighted(x));
console.log('array props', w.join(','));
function receiver() { var sum = 0; for (var i = 0; i < this.limit; i++) { if (i < 2) sum += this.scale; else sum--; } return sum; }
console.log('receiver', receiver.call({ limit: 4, scale: 2 }), receiver.call({ scale: 5, limit: 3 }), receiver.call({ limit: 2, scale: 'a' }));
function factory(n) {
  return { run: function (a) { var sum = 0; for (var i = 0; i < n; i++) { if (i < 2) sum += a[i]; else sum -= a[i]; } return sum; }, set: function (v) { n = v; } };
}
var f = factory(4), g = factory(3);
var fr = [f.run(xs), g.run(xs)]; f.set(2); g.set(4); fr.push(f.run(xs), g.run(xs));
console.log('captured bound', fr.join(','));
function midChange(a, cfg) { var sum = 0; for (var i = 0; i < cfg.limit; i++) { if (i < 2) sum += a[i] * cfg.scale; else sum += a[i] + cfg.scale; } return sum; }
var ma = [1, 2], mcfg = { limit: 4, scale: 2 }, mcalls = 0, mproto = Object.create(Array.prototype);
Object.defineProperty(mproto, '2', { get: function () { mcalls++; mcfg.scale = 10; mcfg.limit = 3; return 3; } });
Object.setPrototypeOf(ma, mproto);
console.log('mid-loop cfg change', midChange(ma, mcfg), mcalls);
function limitScan(cfg) { var sum = 0; for (var i = 0; i < cfg.limit; i++) { if (i < 2) sum += cfg.scale; else sum--; } return sum; }
var lc = 0;
console.log('limit accessors', limitScan({ get limit() { lc++; return 4; }, scale: 2 }), lc,
  limitScan(new Proxy({ limit: 4, scale: 2 }, { get: function (o, k) { lc++; return o[k]; } })), lc,
  limitScan(Object.create({ limit: 4, scale: 2 })), limitScan({ limit: { valueOf: function () { lc++; return 4; } }, scale: 2 }), lc);
function aliases(n) { var sum = 0, x = 1; for (var i = 0; i < n; i++) { if (i < 2) sum += x + (x = 3); else sum += x + (x++); } return sum * 100 + x; }
function duplicates(n) { var x = 1, y = 0, sum = 0; for (var i = 0; i < n; i++) { if (i < 2) sum += x + (y = x + x) + (x = y); else sum += x + (--x) + (x--); } return sum * 100 + x * 10 + y; }
console.log('aliasing', aliases(4), duplicates(4), aliases(1000), duplicates(50));
function assignRead(a, n) { var sum = 0, x = 1; for (var i = 0; i < n; i++) { if (i < 10) sum += x + (x = a[i]); else sum--; } return sum * 100 + x; }
function indexInc(a, n) { var sum = 0, x = 0; for (var i = 0; i < n; i++) { if (i < 10) sum += (++x) * a[i] + x++; else sum--; } return sum * 100 + x; }
var ar = [2, 3], arc = 0, arp = Object.create(Array.prototype);
Object.defineProperty(arp, '2', { get: function () { arc++; return 4; } });
Object.setPrototypeOf(ar, arp);
console.log('assign reads', assignRead(ar, 3), arc, indexInc(ar, 3), arc, assignRead([5, 6, 7, 8], 12));
''', cli=cli)


@tiers
def test_guarded_property_writes(run, workdir, cli):
    """CATCHES: specialised o.dst.value = o.src.value * o.scale.value + o.offset.value regions (and
    branchy update(o) write regions) that keep using cached field slots after aliasing
    (dst===src), accessors, setters, proxies whose set trap returns false, frozen/non-extensible
    targets, valueOf coercion, string concatenation, inherited values, global/captured bounds
    and deep chains; strict variants must throw TypeError exactly where the tree-walker does and
    leave state identical."""
    check_script(run, workdir, G, "guarded_property_writes", r'''
function calculate(o) { o.dst.value = o.src.value * o.scale.value + o.offset.value; }
function reverse(o) { o.dst.value = (o.src.value - o.offset.value) / o.scale.value; }
function negate(o) { o.dst.value = -o.src.value + 2; }
var o = { dst: { value: 0 }, src: { value: 5 }, scale: { value: 2 }, offset: { value: 3 } };
var log = [];
for (var i = 0; i < 300; i++) { calculate(o); if (i === 0) log.push(o.dst.value); reverse(o); }
log.push(o.dst.value); negate(o); log.push(o.dst.value);
o.dst = o.src; calculate(o); log.push(o.src.value);
o.scale.value = 0; o.offset.value = 13; reverse(o); log.push(o.dst.value);
o.src.value = 1; o.offset.value = 0; reverse(o); log.push(o.dst.value);
o.src.value = -0; o.scale.value = 1; reverse(o); log.push(Object.is(o.dst.value, -0));
var arr = []; arr.value = 7; o.src = arr; o.dst = {}; o.scale.value = 2;
for (var i = 0; i < 50; i++) calculate(o);
log.push(o.dst.value); arr.push(1, 2, 3); calculate(o); log.push(o.dst.value);
console.log('calculate', log.join(','));
function add(o) { o.dst.value = o.left.value + o.right.value; }
var p = { dst: { value: 0 }, left: { value: 10 }, right: { value: 3 } };
for (var i = 0; i < 300; i++) add(p);
var reads = 0, out = [p.dst.value];
Object.defineProperty(p.right, 'value', { configurable: true, get: function () { reads++; p.left.value = 100; return 3; } });
add(p); out.push(p.dst.value); add(p); out.push(p.dst.value, reads);
p.right = new Proxy({ value: 4 }, { get: function (t, k) { reads++; return t[k]; } });
add(p); out.push(p.dst.value, reads);
var coercions = 0; p.left.value = { valueOf: function () { coercions++; return 6; } };
add(p); out.push(p.dst.value, coercions);
p.left.value = 'x'; p.right = { value: 2 }; add(p); out.push(p.dst.value);
p.left = Object.create({ value: 9 }); add(p); out.push(p.dst.value);
console.log('add', out.join(','));
function update(o) { if (o.direction === 1) o.dst.value = o.left.value + o.right.value; else o.dst.value = o.left.value - o.right.value; }
function strictUpdate(o) { 'use strict'; if (o.direction === 1) o.dst.value = o.left.value + o.right.value; else o.dst.value = o.left.value - o.right.value; }
var q = { direction: 1, dst: { value: 0 }, left: { value: 10 }, right: { value: 3 } };
for (var i = 0; i < 300; i++) { q.direction = i & 1; update(q); strictUpdate(q); }
var writes = 0, written = 0, res = [q.dst.value];
q.dst = { set value(v) { writes++; written = v; } };
update(q); res.push(written, writes);
q.dst = new Proxy({}, { set: function (t, k, v) { writes++; written = v; return false; } });
update(q); res.push(written, writes);
try { strictUpdate(q); } catch (e) { res.push(e.name + ': ' + e.message); }
q.dst = Object.freeze({ value: 0 });
try { strictUpdate(q); } catch (e) { res.push(e.name + ': ' + e.message); }
update(q); res.push(q.dst.value);
q.dst = Object.preventExtensions({}); update(q); res.push(JSON.stringify(q.dst));
q.dst = Object.create({ set value(v) { writes++; written = v * 2; } }); update(q); res.push(written, writes, Object.keys(q.dst).length);
console.log('update', res.join(' | '));
function cmpAll(o) {
  var r = '';
  if (o.x < o.y) r += 'a'; else r += 'b';
  if (o.x <= o.y) r += 'a'; else r += 'b';
  if (o.x > o.y) r += 'a'; else r += 'b';
  if (o.x >= o.y) r += 'a'; else r += 'b';
  if (o.x != o.y) r += 'a'; else r += 'b';
  if (o.x < o.y) { if (o.x < 0) r += 'n'; else r += 'p'; } else r += 'z';
  return r;
}
var cmpObj = { x: 1, y: 2 }, warm = '';
for (var i = 0; i < 300; i++) warm = cmpAll(cmpObj);
var cr = [warm];
[[NaN, 1], [-1, 2], [2, 2], [-0, 0], ['10', '9'], ['10', 9], [null, 0], [undefined, 0], [1n, 2], [-Infinity, Infinity]].forEach(function (pr) {
  cr.push(cmpAll({ x: pr[0], y: pr[1] }));
});
console.log('compare', cr.join(','));
globalThis.RegionDirection = { limit: 5 };
function viaGlobal(o) { if (o.x < RegionDirection.limit) o.dst.value = o.x + 1; else o.dst.value = o.x - 1; }
var gobj = { x: 3, dst: { value: 0 } }, gres = [];
for (var i = 0; i < 300; i++) viaGlobal(gobj);
gres.push(gobj.dst.value);
RegionDirection = { limit: 2 }; viaGlobal(gobj); gres.push(gobj.dst.value);
RegionDirection.extra = 1; RegionDirection.limit = 7; viaGlobal(gobj); gres.push(gobj.dst.value);
var gg = 0;
Object.defineProperty(globalThis, 'RegionDirection', { configurable: true, get: function () { gg++; return { limit: 1 }; } });
viaGlobal(gobj); gres.push(gobj.dst.value, gg);
delete globalThis.RegionDirection;
try { viaGlobal(gobj); } catch (e) { gres.push(e.name + ': ' + e.message); }
console.log('global bound', gres.join(','));
function factory(limit) { return function (o) { if (o.x < limit) o.dst.value = o.x + 1; else o.dst.value = o.x - 1; }; }
function invoke(fn, o) { fn(o); return o.dst.value; }
var fa = factory(5), fb = factory(2), fo = { x: 3, dst: { value: 0 } }, fres = [];
for (var i = 0; i < 300; i++) invoke(fa, fo);
for (var i = 0; i < 50; i++) { fres[0] = invoke(fa, fo); fres[1] = invoke(fb, fo); }
console.log('closures', fres.join(','));
function activation() {
  function inner(o) { if (o.x < limit) o.dst.value = o.x + 1; else o.dst.value = o.x - 1; }
  var t = { x: 3, dst: { value: 99 } }, msg = '';
  try { inner(t); } catch (e) { msg = e.name + ': ' + e.message; }
  let limit = 5;
  for (var i = 0; i < 150; i++) inner(t);
  return msg + ' / ' + t.dst.value;
}
console.log('tdz', activation(), activation());
globalThis.RegionScalar = 6;
function deep(o) { if (o.direction === 1) o.a.b.c.d.e.f.g.value = RegionScalar + 1; else o.a.b.c.d.e.f.g.value = RegionScalar - 1; }
var leaf = { value: 0 }, dobj = { direction: 1, a: { b: { c: { d: { e: { f: { g: leaf } } } } } } }, dres = [];
for (var i = 0; i < 300; i++) deep(dobj);
dres.push(leaf.value); dobj.direction = 0; deep(dobj); dres.push(leaf.value);
RegionScalar = 10; deep(dobj); dres.push(leaf.value);
Object.defineProperty(globalThis, 'RegionScalar', { configurable: true, value: { valueOf: function () { return 30; } } });
deep(dobj); dres.push(leaf.value);
dobj.a.b.c.d = null;
try { deep(dobj); } catch (e) { dres.push(e.name + ': ' + e.message); }
console.log('deep chain', dres.join(','));
''', cli=cli)


@tiers
def test_write_sequences_and_strictness(run, workdir, cli):
    """CATCHES: consecutive property-write sequences compiled as one region (o.a=o.a+1; o.b=o.a+...;
    chained o.left.mark=o.right.mark=n) that resume at the wrong point when a getter/setter
    fires mid-sequence or lose -0/NaN/Infinity, and JIT fast calls that leak the caller's
    strictness into the callee: sloppy callees called from strict code must silently ignore
    writes to frozen objects, read-only elements/length, false-returning proxy traps and
    undeclared globals, while strict callees called from sloppy code must throw
    TypeError/ReferenceError, including in nested call chains."""
    check_script(run, workdir, G, "write_sequences_and_strictness", r'''
function update(o, n) { o.a = o.a + 1; o.b = o.a + o.child.value + n; return 0; }
var o = { a: 0, b: 0, child: { value: 2 } };
for (var i = 0; i < 300; i++) update(o, 3);
var out = [o.a, o.b], calls = 0;
Object.defineProperty(o.child, 'value', { get: function () { calls++; out.push('get@' + o.a); o.a = 900; return 4; } });
update(o, 3); out.push(calls, o.a, o.b);
o.child = { value: 2 };
Object.defineProperty(o, 'b', { set: function (v) { calls++; out.push('set@' + o.a + '=' + v); }, configurable: true });
update(o, 3); out.push(calls, o.a, o.b);
console.log('sequence', out.join(','));
function chain(o, n) { o.left.mark = o.right.mark = n; return n; }
var c = { left: { mark: 0 }, right: { mark: 0 } }, cs = 0;
for (var i = 0; i < 300; i++) cs += chain(c, i);
var cout = [cs, c.left.mark, c.right.mark];
Object.defineProperty(c.left, 'mark', { set: function (v) { cout.push('setter ' + v + ' right=' + c.right.mark); delete c.left; delete c.right; this.survived = 1; } });
var left = c.left;
cout.push(chain(c, 700), left.survived, 'left' in c, 'right' in c);
try { chain(c, 1); } catch (e) { cout.push(e.name + ': ' + e.message); }
console.log('chain', cout.join(','));
function pair(a, b, n) { a.value = a.value + 1; b.value = a.value + n; }
var pa = { value: 0 };
for (var i = 0; i < 300; i++) pair(pa, pa, 1);
var pb = { value: 0 }, pc = { value: 5 };
for (var i = 0; i < 10; i++) pair(pb, pc, i);
console.log('pair', pa.value, pb.value, pc.value);
globalThis.sequenceValue = 1; globalThis.sequenceResult = 0;
function named(g) { g.sequenceValue = sequenceValue + 1; g.sequenceResult = sequenceValue + 1; }
for (var i = 0; i < 300; i++) named(globalThis);
console.log('global receiver', sequenceValue, sequenceResult);
function edge(o, n) { o.a = n; o.b = o.a; return o.b; }
var e = { a: 0, b: 0 }, eo = [];
for (var i = 0; i < 300; i++) edge(e, i);
[-0, Infinity, NaN, -Infinity, 2147483648, -2147483649, 0.5, '7', null].forEach(function (v) { var r = edge(e, v); eo.push(Object.is(r, -0) ? '-0' : String(r)); });
console.log('edge values', eo.join(','));
function change(o, n) { 'use strict'; o.a = o.a + 1; o.b = n; return 2; }
var coercions = 0;
function prefix() { return { valueOf: function () { coercions++; return 5; } }; }
function wrap(o) { return prefix() + change(o, 4); }
function invokeWrap(o) { return wrap(o); }
var w = { a: 0, b: 0 }, wsum = 0;
for (var i = 0; i < 300; i++) wsum += invokeWrap(w);
var wout = [wsum, w.a, coercions];
Object.defineProperty(w, 'b', { writable: false });
try { invokeWrap(w); } catch (err) { wout.push(err.name + ': ' + err.message); }
wout.push(w.a, w.b, coercions);
console.log('strict tail', wout.join(','));
function sloppyChange(o, n) { o.a = o.a + 1; o.b = n; return o.b; }
var sw = { a: 0, b: 1 };
for (var i = 0; i < 300; i++) sloppyChange(sw, i);
Object.defineProperty(sw, 'b', { writable: false });
console.log('sloppy tail', sloppyChange(sw, 5), sw.a);
function counters(o, n) { for (var i = 0; i < n; i++) { o.hits++; o.total += i; o.last = i; if (i % 7 === 0) o.sevens = (o.sevens || 0) + 1; } return o; }
var k = counters({ hits: 0, total: 0, last: -1 }, 5000);
var kk = counters(Object.create({ hits: 10, total: 0.5 }), 10);
console.log('counters', JSON.stringify(k), JSON.stringify(kk), Object.keys(kk).join());
function take(value) { var local = value; return local; }
function overwrite(old, value) { old = value; return old; }
var values = [undefined, null, false, true, -0, NaN, Infinity, 1.5, 1n << 100n, 'text', Symbol.iterator, { x: 1 }];
var same = 0;
for (var i = 0; i < 600; i++) {
  var v = values[i % values.length];
  if (Object.is(take(v), v) && Object.is(overwrite({ nested: { x: i } }, v), v) && Object.is(overwrite(1n << 150n, v), v)) same++;
}
function loopObj(n) { var result; for (let i = 0; i < n; i++) { var item = { x: i }; result = item; } return result.x; }
function tdz() { var x = y; let y = 3; return x; }
var td = '';
try { tdz(); } catch (err) { td = err.name + ': ' + err.message; }
console.log('locals', same, loopObj(1000), td);
function check(label, f) { try { return label + ':' + f(); } catch (e) { return label + ':' + e.name; } }
function sloppyWrite(o) { o.x = 2; return o.x; }
function strictWrite(o) { 'use strict'; o.x = 2; return o.x; }
function strictCaller(o) { 'use strict'; return sloppyWrite(o); }
function sloppyCaller(o) { return strictWrite(o); }
function warm() { for (var i = 0; i < 300; i++) { strictCaller({ x: 1 }); sloppyCaller({ x: 1 }); } }
warm();
var frozen = Object.freeze({ x: 1 });
var proxy = new Proxy({ x: 1 }, { set: function () { return false; } });
var getterOnly = { get x() { return 9; } };
var nonExt = Object.preventExtensions({});
var r = [];
[['frozen', frozen], ['proxy', proxy], ['getter', getterOnly], ['nonext', nonExt], ['plain', { x: 1 }]].forEach(function (p) {
  r.push(check('s>' + p[0], function () { return strictCaller(p[1]); }), check('l>' + p[0], function () { return sloppyCaller(p[1]); }));
});
console.log(r.join(' '));
function sloppyElem(o) { o[0] = 2; return o[0]; }
function strictElem(o) { 'use strict'; o[0] = 2; return o[0]; }
function strictElemCaller(o) { 'use strict'; return sloppyElem(o); }
function sloppyElemCaller(o) { return strictElem(o); }
for (var i = 0; i < 300; i++) { strictElemCaller([1]); sloppyElemCaller([1]); }
var fa = Object.freeze([1]), noLen = []; Object.defineProperty(noLen, 'length', { writable: false });
r = [check('s>frozen[]', function () { return strictElemCaller(fa); }), check('l>frozen[]', function () { return sloppyElemCaller(fa); }),
  check('s>fixedlen', function () { return strictElemCaller(noLen); }), check('l>fixedlen', function () { return sloppyElemCaller(noLen); }),
  check('s>string', function () { return strictElemCaller('abc'); }), check('l>string', function () { return sloppyElemCaller('abc'); })];
console.log(r.join(' '));
globalThis.targetName = 0;
function sloppyGlobal() { targetName = 1; return typeof targetName; }
function strictGlobal() { 'use strict'; targetName = 2; return typeof targetName; }
function sgCaller() { 'use strict'; return sloppyGlobal(); }
function lgCaller() { return strictGlobal(); }
for (var i = 0; i < 300; i++) { sgCaller(); lgCaller(); }
delete globalThis.targetName;
r = [check('s>undeclared', sgCaller), String(globalThis.targetName)];
delete globalThis.targetName;
r.push(check('l>undeclared', lgCaller), String(globalThis.targetName));
afterError = 3; r.push(globalThis.afterError);
function strictParent() { 'use strict'; var a = check('inner', sgCaller); var failed = 'no'; try { stillMissing = 1; } catch (e) { failed = e.name; } return a + '/' + failed; }
r.push(strictParent());
console.log(r.join(' '));
function sloppyUpdate(o) { o.n++; o.m += 1; return o.n + o.m; }
function strictUpdate(o) { 'use strict'; o.n++; o.m += 1; return o.n + o.m; }
function viaStrict(o) { 'use strict'; return sloppyUpdate(o); }
function viaSloppy(o) { return strictUpdate(o); }
for (var i = 0; i < 300; i++) { viaStrict({ n: 1, m: 1 }); viaSloppy({ n: 1, m: 1 }); }
var fz = Object.freeze({ n: 1, m: 1 });
console.log(check('s>update', function () { return viaStrict(fz); }), check('l>update', function () { return viaSloppy(fz); }), fz.n, fz.m);
function thisWrite() { this.v = 5; return this.v; }
function strictThisWrite() { 'use strict'; this.v = 5; return this.v; }
function callsThis(o) { 'use strict'; return thisWrite.call(o); }
function callsStrictThis(o) { return strictThisWrite.call(o); }
for (var i = 0; i < 300; i++) { callsThis({}); callsStrictThis({}); }
var fv = Object.freeze({ v: 1 });
console.log(check('s>this', function () { return callsThis(fv); }), check('l>this', function () { return callsStrictThis(fv); }),
  check('l>prim', function () { return callsStrictThis(7); }), check('s>prim', function () { return callsThis(7); }));
''', cli=cli)


@tiers
def test_inlined_methods(run, workdir, cli):
    """CATCHES: guarded method inlining (o.method() inside a hot call chain) that keeps calling a stale
    target after the prototype method is replaced, an own property shadows it, it becomes a
    getter, the prototype is swapped, or the receiver is a proxy; also wrong this for primitive
    receivers (strict functions see the primitive, sloppy ones a wrapper object) and lost
    closure identity."""
    check_script(run, workdir, G, "inlined_methods", r'''
function first() { return this.value; }
function second() { return this.value + 1; }
function methodSite(o) { return o.method(); }
function invoke(o) { return methodSite(o); }
var proto = { method: first }, o = Object.create(proto); o.value = 7;
var sum = 0;
for (var i = 0; i < 300; i++) sum += invoke(o);
var out = [sum];
proto.method = second; out.push(invoke(o));
o.method = first; out.push(invoke(o));
var reads = 0;
Object.defineProperty(o, 'method', { configurable: true, get: function () { reads++; return second; } });
out.push(invoke(o), reads);
delete o.method;
Object.setPrototypeOf(o, { method: first }); out.push(invoke(o));
var proxy = new Proxy(o, { get: function (t, k, r) { reads++; return Reflect.get(t, k, r); } });
out.push(invoke(proxy), reads);
o.method = 42;
try { invoke(o); } catch (e) { out.push(e.constructor.name); }
delete o.method; Object.setPrototypeOf(o, null);
try { invoke(o); } catch (e) { out.push(e instanceof TypeError); }
console.log('method', out.join(','));
function factory(n) { return function () { return n; }; }
var a = { method: first, value: 3 }, b = { method: factory(9) }, fo = [];
for (var i = 0; i < 300; i++) invoke(a);
a.method = factory(3); fo.push(invoke(a), invoke(b));
a.method = b.method; fo.push(invoke(a));
function strictValue() { 'use strict'; return this; }
function boxedValue() { return typeof this; }
String.prototype.method = strictValue; fo.push(typeof invoke('text'), invoke('text'));
String.prototype.method = boxedValue; fo.push(invoke('text'));
Number.prototype.method = strictValue; fo.push(invoke(5) + 1);
Boolean.prototype.method = boxedValue; fo.push(invoke(true));
delete String.prototype.method; delete Number.prototype.method; delete Boolean.prototype.method;
try { invoke(undefined); } catch (e) { fo.push(e.name + ': ' + e.message); }
console.log('receivers', fo.join(','));
function selfDelete() { if (this.drop) { delete this.method; } return this.value; }
var sd = { method: selfDelete, value: 17, drop: false };
for (var i = 0; i < 300; i++) invoke(sd);
sd.drop = true;
console.log('self delete', invoke(sd), Object.prototype.hasOwnProperty.call(sd, 'method'));
class Shape { area() { return 0; } describe() { return this.constructor.name + ':' + this.area(); } }
class Sq extends Shape { constructor(s) { super(); this.s = s; } area() { return this.s * this.s; } }
class Circle extends Shape { constructor(r) { super(); this.r = r; } area() { return Math.round(Math.PI * this.r * this.r); } }
class Tri extends Shape { constructor(b, h) { super(); this.b = b; this.h = h; } area() { return this.b * this.h / 2; } describe() { return 'T' + super.describe(); } }
function total(shapes) { var t = 0, names = ''; for (var i = 0; i < shapes.length; i++) { t += shapes[i].area(); if (i < 4) names += shapes[i].describe() + ' '; } return t + ' ' + names; }
var shapes = [];
for (var i = 0; i < 400; i++) shapes.push(i % 4 === 0 ? new Sq(i % 7) : i % 4 === 1 ? new Circle(i % 5) : i % 4 === 2 ? new Tri(i % 3, 4) : new Shape());
console.log('classes', total(shapes));
Sq.prototype.area = function () { return -1; };
console.log('class patched', total(shapes));
function leaf(x) { if (leaf.caller !== middle) return 'bad caller'; return x * 2; }
function middle(x) { return leaf(x); }
function top(x) { return middle(x); }
var lsum = 0;
for (var i = 0; i < 300; i++) lsum += top(i);
function thrower(t) { if (t) throw new Error('boom ' + t); return 1; }
function mid2(t) { return thrower(t); }
function top2(t) { try { return mid2(t); } catch (e) { return e.message + '|' + (thrower.caller === null) + '|' + (mid2.caller === null); } }
var tres = '';
for (var i = 0; i < 300; i++) tres = top2(i === 299 ? 'late' : 0);
function target() { return target.caller; }
function sloppyCaller() { return target(); }
function viaApply() { return target.apply(null, []); }
var sc = 0;
for (var i = 0; i < 300; i++) { if (sloppyCaller() === sloppyCaller) sc++; if (viaApply() === viaApply) sc++; }
console.log('callers', lsum, tres, sc);
''', cli=cli)


@tiers
def test_closure_call_caches(run, workdir, cli):
    """CATCHES: closure call caches and shared-closure inlining that reuse the first closure's captured
    environment for fresh closures from the same factory, miss captured-variable updates, call a
    stale target when a foreign closure/proxy/bound function/class reaches the same call site,
    or lose per-iteration let bindings of closures created inside hot loops."""
    check_script(run, workdir, G, "closure_call_caches", r'''
function factory(seed) { return function (x) { return seed + x; }; }
function invokeF(f, x) { return f(x); }
function run() {
  var total = 0;
  for (var i = 0; i < 300; i++) { var f = factory(i); for (var j = 0; j < 32; j++) total += invokeF(f, j); }
  return total;
}
console.log('fresh closures', run(), run());
function shared(seed) {
  function leaf(x) { return seed + x; }
  function batch() { var total = 0; for (var j = 0; j < 32; j++) total += leaf(j); return total; }
  return batch;
}
function runShared() { var total = 0; for (var i = 0; i < 300; i++) total += shared(i)(); return total; }
var w = shared(0), ws = 0;
for (var i = 0; i < 150; i++) ws += w();
console.log('shared closures', ws, runShared());
function make(seed) {
  function leaf(x) { return seed + x; }
  function invoke(f, x) { return f(x); }
  function bump() { seed++; }
  return { leaf: leaf, invoke: invoke, bump: bump };
}
var first = make(3), second = make(20), out = [];
for (var n = 0; n < 300; n++) if (first.invoke(first.leaf, 4) !== 7) out.push('warm fail');
out.push(first.invoke(second.leaf, 4), first.invoke(function (x) { return 50 + x; }, 4));
var count = 0;
var proxy = new Proxy(first.leaf, { apply: function (f, t, args) { count++; return 90 + args[0]; } });
out.push(first.invoke(proxy, 4), count, first.invoke(second.leaf.bind(null), 4), first.invoke(Math.abs, -4));
try { first.invoke(class C { }, 4); } catch (e) { out.push(e.name + ': ' + e.message); }
first.bump(); out.push(first.invoke(first.leaf, 4));
for (var n = 0; n < 40; n++) { var next = make(n); if (next.invoke(next.leaf, 4) !== n + 4) out.push('fresh capture ' + n); }
console.log('foreign targets', out.join(','));
function holderCall() {
  function leafH(x, missing) { return this.bias + x + (missing === undefined ? 0 : 100); }
  var holder = { fn: leafH, bias: 10 }, s = 0;
  function inv(h, x) { return h.fn(x); }
  for (var n = 0; n < 300; n++) s += inv(holder, 4);
  holder.fn = function (x) { return arguments.length * 1000 + x; };
  return s + ',' + inv(holder, 4);
}
console.log('holder', holderCall());
function counters() {
  var fns = [];
  for (let i = 0; i < 5; i++) fns.push(function () { return i; });
  var vfns = [];
  for (var j = 0; j < 5; j++) vfns.push(function () { return j; });
  var cfns = [];
  for (let k = 0; k < 5; k++) { cfns.push(function () { return k++; }); }
  var res = fns.map(function (f) { return f(); }).join('') + '|' + vfns.map(function (f) { return f(); }).join('') + '|';
  res += cfns.map(function (f) { return f() + f(); }).join(',');
  var acc = [];
  for (let m = 0; m < 3; m++) { setTimeoutLike(function () { acc.push(m); }); m += 0; }
  flush();
  return res + '|' + acc.join('');
}
var queue = [];
function setTimeoutLike(f) { queue.push(f); }
function flush() { while (queue.length) queue.shift()(); }
var cres;
for (var i = 0; i < 20; i++) cres = counters();
console.log('loop captures', cres);
function memo() {
  var cache = {};
  return function fib(n) { if (n < 2) return n; if (cache[n] !== undefined) return cache[n]; return cache[n] = fib(n - 1) + fib(n - 2); };
}
var mf = memo();
console.log('memo', mf(30), mf(60), mf(90), memo()(25));
function compose() { var fs = arguments; return function (x) { for (var i = fs.length - 1; i >= 0; i--) x = fs[i](x); return x; }; }
var pipeline = compose(function (x) { return x + 1; }, function (x) { return x * 2; }, Math.sqrt);
var ps = 0;
for (var i = 0; i < 2000; i++) ps += pipeline(i);
console.log('compose', ps.toFixed(6));
function adder() { var total = 0; return { add: function (v) { total += v; return this; }, get: function () { return total; } }; }
var ad = adder();
for (var i = 0; i < 3000; i++) ad.add(i % 3 === 0 ? 0.5 : -0.25);
console.log('accumulator', ad.get(), adder().add(1).add(2).get());
''', cli=cli)


@tiers
def test_iterator_protocol_loops(run, workdir, cli):
    """CATCHES: compiled for-of iterator entry/step paths that cache next() across iterations (missing
    a next method replaced mid-loop), skip IteratorClose (return()) on break/throw, call
    return() on normal completion, ignore a patched %ArrayIteratorPrototype%.next, mis-step
    arrays that grow or shrink during iteration, or bypass element getters, prototype-resolved
    holes and proxies."""
    check_script(run, workdir, G, "iterator_protocol_loops", r'''
function make() {
  var state = { cursor: 0, items: [{ x: 7 }, { x: 8 }, { x: 9 }] };
  return { state: state, [Symbol.iterator]() { return this; }, next() {
    if (state.cursor < state.items.length) { state.cursor = state.cursor + 1; return { value: state.items[state.cursor - 1], done: false }; }
    return { done: true };
  } };
}
function drain(it) { var values = []; for (var value of it) values.push(value.x); return values.join(''); }
var d = '';
for (var i = 0; i < 300; i++) d = drain(make());
var m = make(); m.state.items.push({ x: 1 });
console.log('stateful', d, drain(m), drain(m));
var steps = 0, iterator = {};
var original = function () { iterator.next = function () { throw new Error('replacement used'); }; return { value: ++steps, done: steps > 2 }; };
iterator[Symbol.iterator] = function () { return this; };
function sumOf(o) { var sum = 0; for (var v of o) sum += v; return sum; }
iterator.next = original;
try { console.log('captured next', sumOf(iterator), steps); } catch (e) { console.log('captured next threw', e.message); }
function counter(n, log) {
  var i = 0;
  return { [Symbol.iterator]: function () { return this; },
    next: function () { return i < n ? { value: i++, done: false } : { value: 'ret', done: true }; },
    return: function (v) { log.push('return(' + i + ')'); return {}; } };
}
function early(n, stopAt, log) { var s = 0; for (var v of counter(n, log)) { if (v === stopAt) break; s += v; } return s; }
function thrown(n, log) { var s = 0; try { for (var v of counter(n, log)) { if (v === 3) throw new Error('at ' + v); s += v; } } catch (e) { log.push(e.message); } return s; }
var log = [], es = 0;
for (var i = 0; i < 200; i++) es += early(10, i % 12, log);
console.log('break closes', es, log.length, log.slice(0, 3).join(' '), log[log.length - 1]);
log = [];
console.log('throw closes', thrown(10, log), log.join(' '));
function labeled(log) { var s = 0; outer: for (var a of counter(3, log)) { for (var b of counter(3, log)) { if (b === 1) continue outer; s += a * 10 + b; } } return s; }
log = [];
console.log('labeled continue closes inner', labeled(log), log.join(' '));
var proto = Object.getPrototypeOf([][Symbol.iterator]()), savedNext = proto.next, custom = 0;
function patchWhile(a) { var sum = 0; for (var x of a) { sum += x; proto.next = function () { custom++; return { done: true }; }; } return sum; }
var pw = 0;
for (var i = 0; i < 50; i++) { pw += patchWhile([1, 2, 3]); proto.next = savedNext; }
console.log('patched array next', pw, custom);
function changing(a) { var sum = 0, seen = []; for (var x of a) { sum += x; seen.push(x); if (x === 1) a.push(4); if (x === 2) a.length = 2; } return sum + ':' + seen.join(''); }
function grow(a) { var n = 0; for (var x of a) { if (n < 5) a.push(x * 2); n++; } return n + ':' + a.join(','); }
var cg = [];
for (var i = 0; i < 100; i++) cg[0] = changing([1, 2, 3]);
cg.push(grow([1, 2]));
var reads = 0, holes = [, 2], parent = Object.create(Array.prototype);
Object.defineProperty(parent, '0', { get: function () { reads++; return 5; } });
Object.setPrototypeOf(holes, parent);
cg.push(sumOf(holes), reads);
var traps = [], px = new Proxy([3, 4], { get: function (t, k) { traps.push(String(k)); return t[k]; } });
cg.push(sumOf(px), traps.join('/'));
cg.push(sumOf([1, , 3].concat([4])), sumOf(new Set([1, 1, 2])), sumOf(new Map([[1, 2]]).keys()), sumOf('123'));
var lens = 0, arrayLike = { 0: 7, 1: 8, get length() { lens++; return 2; } };
cg.push(sumOf(Array.prototype.values.call(arrayLike)), lens);
console.log('array steps', cg.join(' '));
var closed = 0, seen = null;
var src = { [Symbol.iterator]: function () { var it = [1, 2].values(); it.return = function () { closed++; seen = this === it; return {}; }; return it; } };
function firstOnly(s, fail) { for (var x of s) { if (fail) throw 'original'; return x; } }
var fr = 0;
for (var i = 0; i < 100; i++) fr += firstOnly(src, false);
var er = '';
try { firstOnly(src, true); } catch (e) { er = e; }
console.log('return in loop body', fr, closed, seen, er);
var badReturn = { [Symbol.iterator]: function () { return { next: function () { return { value: 1, done: false }; }, return: function () { return 5; } }; } };
function breakBad(s) { for (var x of s) break; }
try { breakBad(badReturn); } catch (e) { console.log('non-object return:', e.name); }
var nonObj = { [Symbol.iterator]: function () { return { next: function () { return 3; } }; } };
try { sumOf(nonObj); } catch (e) { console.log('non-object result:', e.name); }
var doneGetter = 0, valueGetter = 0;
var lazy = { [Symbol.iterator]: function () { var k = 0; return { next: function () { k++; return { get done() { doneGetter++; return k > 3; }, get value() { valueGetter++; return k; } }; } }; } };
console.log('result getters', sumOf(lazy), doneGetter, valueGetter);
''', cli=cli)


@tiers
def test_destructure_and_spread(run, workdir, cli):
    """CATCHES: bounded array destructuring and call-spread fast paths that read array storage directly
    instead of running the (possibly patched) iterator protocol: wrong results or call counts
    when %ArrayIteratorPrototype%.next/return or Array.prototype[Symbol.iterator] are replaced,
    element getters/proxy traps skipped or repeated, holes not resolved via the prototype, wrong
    evaluation order of spread arguments, or IteratorClose not invoked for a short pattern."""
    check_script(run, workdir, G, "destructure_and_spread", r'''
function empty(a) { var [] = a; return 1; }
function one(a) { var [x] = a; return x; }
function pair(a) { var [x, y] = a; return x + y; }
function three(a) { var [x, y, z] = a; return z; }
function skip(a) { var [x, , z] = a; return x + z; }
function rest(a) { var [x, ...r] = a; return x + ':' + r.length; }
function defaults(a) { var [x = 10, y = x * 2] = a; return x + y; }
var w = 0;
for (var i = 0; i < 300; i++) w += pair([i, 1]) + one([i]) + (three([1, 2]) === undefined ? 1 : 0) + skip([1, 99, 2]) + empty([]);
console.log('warm', w, rest([1, 2, 3]), rest([]), defaults([]), defaults([1]), defaults([undefined, 0]), defaults([null]));
var proto = Object.getPrototypeOf([].values()), originalNext = proto.next, steps = 0, closed = 0;
proto.next = function () { steps++; return { done: false, value: 7 }; };
proto.return = function () { closed++; return {}; };
var r1 = [pair([2, 3]), steps, closed, three([2, 3]), steps, closed, empty([5]), closed];
proto.next = originalNext;
r1.push(pair([2, 3]), closed, three([2, 3]), closed, one([4, 5, 6]), closed);
delete proto.return;
console.log('patched next/return', r1.join(','));
var originalIter = Array.prototype[Symbol.iterator], originalValues = Array.prototype.values;
function customIter() { return { next: function () { return { done: false, value: 4 }; }, return: function () { closed++; return {}; } }; }
Array.prototype[Symbol.iterator] = customIter;
var r2 = [pair([2, 3]), closed];
Array.prototype[Symbol.iterator] = originalIter;
r2.push(pair([2, 3]));
var getters = 0, ga = [2, 3];
Object.defineProperty(ga, '0', { get: function () { getters++; return 5; } });
r2.push(pair(ga), getters);
var holed = [, 3], parent = Object.create(Array.prototype);
Object.defineProperty(parent, '0', { get: function () { getters++; return 6; } });
Object.setPrototypeOf(holed, parent);
r2.push(pair(holed), getters);
var traps = 0, px = new Proxy([2, 3], { get: function (t, k) { traps++; return t[k]; } });
r2.push(pair(px), traps > 0);
r2.push(pair('ab'), pair(new Set([1, 2, 3])), pair(new Map([[1, 2], [3, 4]]).values()));
try { pair(null); } catch (e) { r2.push(e.name); }
try { pair({}); } catch (e) { r2.push(e.name); }
console.log('iterator variants', r2.join(','));
function swap(n) { var a = 1, b = 2; for (var i = 0; i < n; i++) { [a, b] = [b, a + b]; if (a > 1e6) { a = a % 1000; b = b % 1000; } } return a + ',' + b; }
console.log('swap loop', swap(5000), swap(1));
var order = [];
function firstArg() { order.push('plain'); return 1; }
function spreadArg() { order.push('spread'); return [2, 3]; }
function target(a, b, c) { order.push('target'); return this.marker + a + b + c; }
var receiver = { marker: 9, target: target };
function invokeSpread(r) { return r.target(firstArg(), ...spreadArg()); }
var st = 0;
for (var i = 0; i < 300; i++) st += invokeSpread(receiver);
console.log('spread order', st, order.slice(0, 3).join(','), order.length);
function sum3(a, b, c) { return a + b + c + arguments.length; }
function viaSpread(a) { return sum3(...a); }
function viaApply(a) { return sum3.apply(null, a); }
var sp = 0;
for (var i = 0; i < 300; i++) sp += viaSpread([i, 1, 2]) + viaApply([1, 2, i]);
var r3 = [sp, viaSpread([1]), viaSpread([1, 2, 3, 4, 5]), viaSpread([]), viaApply({ length: 2, 0: 5, 1: 6 }), viaSpread('abc')];
var ra = 0, sa = [2, 3];
Object.defineProperty(sa, '0', { get: function () { ra++; return 4; } });
r3.push(viaSpread(sa), ra);
console.log('spread variants', r3.join(','));
var trapped = 0;
var pt = new Proxy(sum3, { apply: function (fn, self, args) { trapped++; return args.length * 100; } });
function invokeProxy(a) { return pt(...a); }
function throws() { throw new Error('spread-target'); }
function invokeThrows(a) { return throws(...a); }
function recursive(n) { return n === 0 ? 'done' : recursive(...[n - 1]); }
function base(a, b) { return this.marker + a + b; }
var bound = base.bind({ marker: 4 }, 5);
function invokeBound(a) { return bound(...a); }
function Point(x, y) { this.x = x; this.y = y; }
function construct(a) { var p = new Point(...a); return p.x * p.y; }
var r4 = [];
for (var i = 0; i < 200; i++) { r4[0] = invokeProxy([1, 2, i]); r4[1] = invokeBound([i]); r4[2] = construct([i, 2]); }
r4.push(trapped, recursive(12));
try { invokeThrows([1]); } catch (e) { r4.push(e.message); }
r4.push(Math.max(...[1, 5, 3], ...new Set([9, 2])), String.fromCharCode(...[72, 105]), [...'héllo'].length, [..."a\u{1F600}b"].length);
console.log('spread targets', r4.join(','));
var big = [];
for (var i = 0; i < 40; i++) big.push(i * 3 - 50);
function spreadMax(a) { return Math.max(...a) + ':' + Math.min(...a, 0) + ':' + sum3(...a); }
var smx;
for (var i = 0; i < 100; i++) smx = spreadMax(big);
console.log('spread shapes', smx, spreadMax([1, , 3]), spreadMax([]), sum3(...[1, , 3]), viaSpread(Object.assign([4, 5], { 2: 6 })), viaSpread(new Set([7, 8])));
''', cli=cli)


@tiers
def test_collection_helpers(run, workdir, cli):
    """CATCHES: native Map.set/Set.add/Map.get/Map.has/Set.has call-site helpers that skip
    SameValueZero (-0 vs 0, NaN), lose Map's value sign while Set canonicalises -0, break
    insertion order on delete/re-insert with a live iterator, keep calling the builtin after an
    own override, accept a Proxy/plain object/WeakMap as receiver instead of throwing TypeError,
    or mishandle the dense integer index (sparse, fractional, negative, >= 65536 keys and string
    '1' vs number 1)."""
    check_script(run, workdir, G, "collection_helpers", r'''
var m = new Map(), s = new Set();
var keys = [undefined, null, true, 0, -0, NaN, Infinity, 1.5, 1n, 'key', Symbol.iterator, {}];
function put(k, v) { return m.set(k, v) === m && s.add(k) === s; }
var ok = 0;
for (var i = 0; i < 1000; i++) {
  var k = keys[i % keys.length];
  if (put(k, m) && m.get(k) === m && s.has(k)) ok++;
  put(k, k); if (Object.is(m.get(k), k)) ok++;
  m.delete(k); s.delete(k);
}
m.clear(); s.clear(); put(-0, -0);
console.log('categories', ok, m.size, s.size, 1 / m.keys().next().value, 1 / m.get(0), 1 / s.values().next().value, m.has(-0), s.has(0));
m.clear(); s.clear(); put('a', 1); put('b', 2);
var mi = m.keys(), si = s.values(), order = [mi.next().value, si.next().value];
m.delete('b'); s.delete('b'); put('c', 3); put('b', 4);
order.push(mi.next().value, mi.next().value, mi.next().done, si.next().value, si.next().value);
console.log('live iterator order', order.join(','), [...m.keys()].join(''), [...m.values()].join(''));
function putC(c, k, v) { return c.set(k, v); }
function addC(c, k) { return c.add(k); }
function throwsName(f) { try { f(); return 'no throw'; } catch (e) { return e.name; } }
var mm = new Map(), ss = new Set(), r = [];
for (var i = 0; i < 1000; i++) { putC(mm, i, i * 2); addC(ss, i); }
mm.set = function (k, v) { return 'own ' + v; }; r.push(putC(mm, 1, 7)); delete mm.set;
ss.add = function (k) { return 'own ' + k; }; r.push(addC(ss, 7)); delete ss.add;
r.push(throwsName(function () { putC(new Proxy(mm, {}), {}, {}); }), throwsName(function () { addC(new Proxy(ss, {}), {}); }));
r.push(throwsName(function () { putC({ set: Map.prototype.set }, {}, {}); }), throwsName(function () { addC({ add: Set.prototype.add }, {}); }));
r.push(throwsName(function () { addC(mm, 1); }), throwsName(function () { Map.prototype.get.call(ss, 1); }));
var weak = new WeakMap(); weak.set = Map.prototype.set; r.push(throwsName(function () { putC(weak, {}, {}); }));
var ws = new WeakSet(); ws.add = Set.prototype.add; r.push(throwsName(function () { addC(ws, {}); }));
mm.__ck = 'Set'; r.push(putC(mm, 1, 2) === mm, mm.get(1));
mm.set(); r.push(mm.has(undefined), mm.get(undefined)); mm.set('missing'); r.push(mm.has('missing'));
r.push(mm.size, ss.size, mm.get(999), mm.get(1000), ss.has(999), ss.has('999'));
console.log('receivers', r.join(','));
function build(keysList) { var map = new Map(); for (var i = 0; i < keysList.length; i++) map.set(keysList[i], (map.get(keysList[i]) || 0) + 1); return map; }
function lookups(map, probes) { var hits = 0, total = 0; for (var i = 0; i < probes.length; i++) { if (map.has(probes[i])) { hits++; total += map.get(probes[i]); } } return hits + '/' + total; }
var dense = [], probes = [];
for (var i = 0; i < 3000; i++) { dense.push(i % 700); probes.push(i - 100); }
var dm = build(dense);
console.log('dense', dm.size, lookups(dm, probes), lookups(dm, ['1', 1.5, -1, 699.0, 700, 1n, -0]));
var odd = [65535, 65536, 70000, 1e9, -5, 0.5, 2 ** 53, 3, 3.0, '3', 1e-7, 100000];
var om = build(odd.concat(odd));
console.log('sparse', om.size, JSON.stringify([...om.entries()]), lookups(om, [65536, 3, '3', 0.5 + 0, -5]));
var growing = new Map();
for (var i = 0; i < 5000; i += 3) growing.set(i, i);
for (var i = 0; i < 5000; i += 6) growing.delete(i);
for (var i = 0; i < 300; i += 1) growing.set(i, -i);
var gs = 0; growing.forEach(function (v, k) { gs += v * 3 + k; });
console.log('grow/delete', growing.size, gs, [...growing.keys()].slice(0, 8).join(','));
function words(text) {
  var counts = new Map(), seen = new Set(), firsts = [];
  var parts = text.split(/\W+/);
  for (var i = 0; i < parts.length; i++) {
    var wd = parts[i].toLowerCase(); if (!wd) continue;
    counts.set(wd, (counts.get(wd) || 0) + 1);
    if (!seen.has(wd)) { seen.add(wd); firsts.push(wd); }
  }
  return [...counts].sort(function (a, b) { return b[1] - a[1] || (a[0] < b[0] ? -1 : 1); }).slice(0, 5).map(function (e) { return e.join('='); }).join(' ') + ' | ' + firsts.slice(0, 6).join(',');
}
var text = '';
for (var i = 0; i < 200; i++) text += 'The quick brown fox jumps over the lazy dog. A dog, a fox; THE end ' + (i % 7) + '! ';
console.log('words', words(text));
''', cli=cli)


@tiers
def test_for_in_enumeration(run, workdir, cli):
    """CATCHES: compiled for-in enumeration that snapshots keys incorrectly: visiting keys deleted
    during the loop, visiting keys added during the loop, wrong order (integer keys ascending
    first, then strings in insertion order, then prototype keys), shadowed or non-enumerable
    prototype keys leaking, symbols enumerated, or per-iteration let bindings captured by
    closures being shared."""
    check_script(run, workdir, G, "for_in_enumeration", r'''
function keysOf(o) { var out = []; for (let k in o) out.push(k); return out.join(','); }
function sumValues(o) { var s = 0; for (const k in o) s += o[k]; return s; }
var base = { z: 1, 10: 2, a: 3, 2: 4, '-1': 5, '01': 6, 1.5: 7 };
var w = '';
for (var i = 0; i < 300; i++) w = keysOf(base);
console.log('order', w, sumValues(base));
var proto = { inherited: 1, shadow: 2 };
Object.defineProperty(proto, 'hidden', { value: 3, enumerable: false });
var child = Object.create(proto); child.own = 4; child.shadow = 5; child[Symbol('s')] = 6;
Object.defineProperty(child, 'nonEnum', { value: 7, enumerable: false });
var grand = Object.create(child); grand.g = 8;
Object.defineProperty(grand, 'inherited', { value: 0, enumerable: false });
console.log('chain', keysOf(child), '|', keysOf(grand), '|', sumValues(child));
function deleting(o) { var seen = []; for (let k in o) { seen.push(k); if (k === 'b') { delete o.c; delete o.a; } } return seen.join(''); }
function adding(o) { var seen = []; for (let k in o) { seen.push(k); if (seen.length < 10) o['n' + seen.length] = 1; } return seen.join(',') + ' ' + Object.keys(o).length; }
var dl = [];
for (var i = 0; i < 50; i++) dl[0] = deleting({ a: 1, b: 2, c: 3, d: 4 });
dl.push(adding({ x: 1, y: 2 }));
var protoDel = { p1: 1, p2: 2 }, pd = Object.create(protoDel); pd.o1 = 0;
var pseen = [];
for (let k in pd) { pseen.push(k); if (k === 'o1') delete protoDel.p2; }
dl.push(pseen.join(''));
console.log('mutation', dl.join(' | '));
function arrays(a) { var out = []; for (var k in a) out.push(k + '=' + a[k]); return out.join(' '); }
var arr = [5, , 7]; arr.extra = 'x'; arr[10] = 9;
Array.prototype.polluted = 'p';
var ar = arrays(arr);
delete Array.prototype.polluted;
console.log('arrays', ar, '|', arrays('hey'), '|', arrays(new Uint8Array([3, 4])), '|', keysOf(null), keysOf(undefined), keysOf(42), keysOf(true));
function capture(o) { var fns = []; for (let k in o) fns.push(function () { return k; }); return fns.map(function (f) { return f(); }).join(''); }
function captureVar(o) { var fns = []; for (var k in o) fns.push(function () { return k; }); return fns.map(function (f) { return f(); }).join(''); }
var cc = '';
for (var i = 0; i < 100; i++) cc = capture({ p: 1, q: 2, r: 3 }) + '/' + captureVar({ p: 1, q: 2, r: 3 });
console.log('captures', cc);
function count(o) { var n = 0; for (var k in o) { if (k.length > 2) continue; n++; if (n > 50) break; } return n; }
var big = {};
for (var i = 0; i < 2000; i++) big['k' + (i % 300)] = i;
console.log('big', count(big), Object.keys(big).length, sumValues(big));
var px = new Proxy({ a: 1, b: 2 }, { ownKeys: function (t) { return ['b', 'a', 'ghost']; }, getOwnPropertyDescriptor: function (t, k) { return k === 'ghost' ? undefined : Reflect.getOwnPropertyDescriptor(t, k); } });
console.log('proxy', keysOf(px));
function shapes(list) { var out = []; for (var i = 0; i < list.length; i++) { var o = list[i], ks = ''; for (var k in o) ks += k; out.push(ks); } return out.join(' '); }
var list = [];
for (var i = 0; i < 400; i++) { var o = {}; if (i & 1) o.a = 1; if (i & 2) o.b = 1; if (i & 4) o.c = 1; if (i % 5 === 0) delete o.a; list.push(o); }
console.log('polymorphic', shapes(list.slice(0, 12)), shapes(list).length);
''', cli=cli)


@tiers
def test_switch_and_parameters(run, workdir, cli):
    """CATCHES: compiled switch lowering that coerces case comparisons (must be strict ===), evaluates
    case expressions eagerly or out of order, mishandles default placed in the middle with
    fallthrough, forgets the shared case-block TDZ for let/const, or mis-wires break/continue to
    the enclosing loop; and parameter lowering that evaluates defaults for null, shares empty-
    object defaults between calls, maps arguments for functions with defaults, or skips
    parameter TDZ."""
    check_script(run, workdir, G, "switch_and_parameters", r'''
function classify(v) {
  switch (v) {
    case 0: return 'zero';
    case 1: case 2: return 'small';
    case '1': return 'string-one';
    case null: return 'null';
    case undefined: return 'undef';
    case NaN: return 'nan?';
    default: return 'other';
    case true: return 'true';
  }
}
var cv = [0, -0, 1, 2, '1', '0', null, undefined, NaN, true, 1n, [1], 3];
var cr = '';
for (var i = 0; i < 300; i++) cr = cv.map(classify).join(',');
console.log('classify', cr);
function fall(n) {
  var log = '';
  switch (n % 5) {
    case 1: log += 'a';
    case 2: log += 'b'; break;
    default: log += 'd';
    case 3: log += 'c';
    case 4: log += 'e'; break;
  }
  return log;
}
var fl = [];
for (var i = 0; i < 300; i++) fl[i % 5] = fall(i);
console.log('fallthrough', fl.join(' '));
var evals = [];
function key(k) { evals.push(k); return k; }
function lazyCases(v) { switch (v) { case key(1): return 'one'; case key(2): return 'two'; case key(3): return 'three'; } return 'none'; }
var lc = [];
for (var i = 0; i < 4; i++) { evals = []; lc.push(lazyCases(i) + ':' + evals.join('')); }
console.log('lazy cases', lc.join(' '));
function loopSwitch(n) {
  var out = 0;
  outer: for (var i = 0; i < n; i++) {
    switch (i % 6) {
      case 0: continue;
      case 1: out += 1; break;
      case 2: { let t = i * 2; out += t; break; }
      case 3: if (i > 30) break outer; out -= 1; break;
      case 4: for (var j = 0; j < 3; j++) { if (j === 1) continue outer; out += 100; }
      default: out += 1000;
    }
    out += 10000;
  }
  return out + ':' + i;
}
console.log('loop switch', loopSwitch(20), loopSwitch(100));
function tdzCase(v) {
  switch (v) {
    case 0: let x = 'zero'; return x;
    case 1: x = 'one'; return x;
    case 2: return typeof x;
    case 3: const y = 3; return y;
  }
  return 'none';
}
var tr = [];
for (var i = 0; i < 4; i++) { try { tr.push(tdzCase(i)); } catch (e) { tr.push(e.name + ': ' + e.message); } }
console.log('case tdz', tr.join(' | '));
function strSwitch(s) { switch (s.charCodeAt(0)) { case 97: return 1; case 98: return 2; case 0x1F600: return 3; case 55357: return 4; default: return 0; } }
var ss = 0, chars = 'abcab\u{1F600}x';
for (var i = 0; i < 2000; i++) ss += strSwitch(chars.slice(i % chars.length));
console.log('char switch', ss);
function defaults(a, b = a + 1, c = [], d = {}) { c.push(a); d.n = (d.n || 0) + 1; return [a, b, c.length, d.n, arguments.length].join('/'); }
var shared = [];
var dr = [];
for (var i = 0; i < 300; i++) dr[0] = defaults(i);
dr.push(defaults(1, undefined), defaults(1, null), defaults(1, 0, shared), defaults(1, 0, shared), defaults());
console.log('defaults', dr.join(' '));
function captured(a = 1, b = 'x', c = {}, d = []) { return function () { c.k = (c.k || 0) + a; d.push(b); return c.k + ':' + d.length; }; }
var cs = [];
for (var i = 0; i < 300; i++) { var f = captured(); f(); cs[0] = f(); }
var keep = captured(5, 'y'); keep(); cs.push(keep(), captured(undefined, undefined, { k: 10 })());
console.log('captured defaults', cs.join(' '));
function mapped(a, b) { arguments[0] = 'changed'; b = 'b2'; return a + ',' + arguments[1] + ',' + arguments.length; }
function unmapped(a, b = 0) { arguments[0] = 'changed'; b = 'b2'; return a + ',' + arguments[1] + ',' + arguments.length; }
function strictArgs(a, b) { 'use strict'; arguments[0] = 'changed'; b = 'b2'; return a + ',' + arguments[1] + ',' + arguments.length; }
function restP(a, ...r) { return a + ':' + r.join('+') + ':' + r.length + ':' + arguments.length; }
function destr({ x, y = 2 } = {}, [p, q] = [7, 8]) { return x + '/' + y + '/' + p + '/' + q; }
var pr = [];
for (var i = 0; i < 300; i++) { pr[0] = mapped(1, 2); pr[1] = unmapped(1, 2); pr[2] = strictArgs(1, 2); pr[3] = restP(1, 2, 3); pr[4] = destr({ x: i }); }
pr.push(mapped(1), restP(), destr(), destr({ x: 1, y: null }, 'ab'));
try { destr(null); } catch (e) { pr.push(e.name); }
function laterParam(a = b, b = 1) { return a; }
try { laterParam(); } catch (e) { pr.push(e.name + ': ' + e.message); }
pr.push(laterParam(5));
console.log('params', pr.join(' | '));
var limits = { max: 9, list: [4, 5] };
function richDefaults(a, b = -a, c = a ? 'yes' : 'no', d = a + (b || 1) * 2, e = Math.max(a, 3), f = [a, ...[1, 2]], g = { x: a, y: 'k' }, h = limits.max, k = limits.list[1], m = typeof a, n = a++, o = a, p = new Array(2).length, q = /x/g.flags, r = a && b, s = `t${a}`, t = String(a)) {
  return [a, b, c, d, e, f.join('+'), g.x + g.y, h, k, m, n, o, p, q, r, s, t].join(' ');
}
var rd = [];
for (var i = 0; i < 300; i++) rd[0] = richDefaults(i);
rd.push(richDefaults(0), richDefaults(undefined, null, 0, ''), richDefaults('s'));
limits.max = -1; limits.list = [0, 'swapped'];
rd.push(richDefaults(2));
console.log('rich defaults', rd.join(' | '));
function capturedDefault(a, cb = function () { return a * 2; }, arr = [a]) { a = a + 1; return cb() + ':' + arr[0] + ':' + a; }
function arrowDefault(x, f = () => x + y, y = 10) { return f(); }
var cdr = [];
for (var i = 0; i < 300; i++) { cdr[0] = capturedDefault(i); cdr[1] = arrowDefault(i); }
cdr.push(capturedDefault(5, function () { return 'own'; }), arrowDefault(1, undefined, 1));
console.log('closure defaults', cdr.join(' '));
''', cli=cli)


@tiers
def test_constructors_and_this(run, workdir, cli):
    """CATCHES: compiled constructor bodies and this-binding paths that run class field initialisers in
    the wrong order, share instances, ignore object return overrides, lose new.target or the
    Reflect.construct prototype, allow calling a hot class without new, give arrows the caller's
    this instead of the lexical one, or box/unbox this incorrectly for strict vs sloppy
    functions."""
    check_script(run, workdir, G, "constructors_and_this", r'''
var order = [];
class Base {
  a = (order.push('field a'), 1);
  #secret = 41;
  static count = 0;
  constructor(x, y = x * 2) { order.push('ctor'); this.x = x; this.y = y; Base.count++; }
  get secret() { return this.#secret + 1; }
  bump() { this.#secret++; return this; }
  static isBase(o) { return #secret in o; }
}
var bs = 0, inst;
for (var i = 0; i < 300; i++) { inst = new Base(i); bs += inst.x + inst.y + inst.a; }
console.log('base', bs, Base.count, order.slice(0, 3).join(','), order.length, inst.secret, inst.bump().bump().secret, Base.isBase(inst), Base.isBase({}));
function Plain(v) { this.v = v; if (v === 'obj') return { replaced: true }; if (v === 'prim') return 5; }
Plain.prototype.get = function () { return this.v; };
var pr = [];
for (var i = 0; i < 300; i++) pr[0] = new Plain(i).get();
pr.push(JSON.stringify(new Plain('obj')), new Plain('prim').get(), new Plain('prim') instanceof Plain);
function Target() { this.nt = new.target === Target ? 'Target' : String(new.target && new.target.name); }
function Other() { }
var nt;
for (var i = 0; i < 300; i++) nt = new Target().nt;
pr.push(nt);
var rc = Reflect.construct(Target, [], Other);
pr.push(rc.nt, Object.getPrototypeOf(rc) === Other.prototype, Target.call({}) === undefined);
console.log('plain', pr.join(' '));
class Counter { constructor() { this.n = 0; } inc() { return ++this.n; } }
function makeMany(n) { var out = []; for (var i = 0; i < n; i++) { var c = new Counter(); c.inc(); if (i & 1) c.inc(); out.push(c); } return out; }
var many = makeMany(500);
console.log('independent', many[0].n, many[1].n, many[0] !== many[2], many.reduce(function (s, c) { return s + c.n; }, 0));
var callErr = [];
for (var i = 0; i < 20; i++) { try { Counter(); } catch (e) { callErr[0] = e.name + ': ' + e.message; } }
class Throwing { f = (() => { if (Throwing.fail) throw new Error('field failed'); return 1; })(); }
for (var i = 0; i < 50; i++) new Throwing();
Throwing.fail = true;
try { new Throwing(); } catch (e) { callErr.push(e.message); }
console.log('errors', callErr.join(' | '));
class Animal { constructor(name) { this.name = name; } speak() { return this.name + ' makes a sound'; } get kind() { return 'animal'; } }
class Dog extends Animal { constructor(name) { super(name + '!'); this.tricks = 0; } speak() { return super.speak() + ' (woof)'; } get kind() { return 'dog/' + super.kind; } }
class Puppy extends Dog { constructor() { super('pup'); return this; } }
class Weird extends Animal { constructor() { super('w'); return { forged: true }; } }
var dr = [];
for (var i = 0; i < 300; i++) { var d = i % 2 ? new Dog('rex') : new Puppy(); dr[i % 2] = d.speak() + ' ' + d.kind + ' ' + (d instanceof Animal); }
dr.push(JSON.stringify(new Weird()));
class Bad extends Animal { constructor() { } }
try { new Bad(); } catch (e) { dr.push(e.name); }
console.log('derived', dr.join(' | '));
var holder = {
  base: 10,
  sumWithArrow: function (list) { var t = 0; list.forEach((v) => { t += v + this.base; }); return t; },
  nested: function () { return (() => (() => this.base)())(); },
  regular: function (list) { var t = 0; list.forEach(function (v) { t += (this === undefined ? -1 : this === globalThis ? 1000 : 0); }); return t; },
};
var hr = [];
for (var i = 0; i < 300; i++) { hr[0] = holder.sumWithArrow([1, 2, 3]); hr[1] = holder.nested(); hr[2] = holder.regular([1, 2]); }
var detached = holder.nested.bind({ base: 99 });
hr.push(detached(), holder.sumWithArrow.call({ base: -1 }, [1]));
console.log('lexical this', hr.join(','));
function strictThis() { 'use strict'; return this; }
function sloppyThis() { return this; }
var tr = [];
for (var i = 0; i < 300; i++) { tr[0] = typeof strictThis.call(5); tr[1] = typeof sloppyThis.call(5); tr[2] = strictThis.call(undefined); tr[3] = sloppyThis.call(undefined) === globalThis; tr[4] = sloppyThis.call('s') instanceof String; tr[5] = strictThis.apply(null); }
console.log('this boxing', tr.join(','));
''', cli=cli)


@tiers
def test_branch_conditions(run, workdir, cli):
    """CATCHES: compiled scalar/boolean branch conditions that get ToBoolean wrong for -0, NaN, '', 0n,
    empty-but-truthy objects or wrapper objects, fuse comparisons with branches incorrectly for
    NaN/-0/Infinity/mixed types (== vs ===, < with strings), or mis-evaluate short-circuit &&,
    ||, ?? and ?: chains (including side effects that must not run) inside hot predicates."""
    check_script(run, workdir, G, "branch_conditions", r'''
function flag(value) { if (value) return 'T'; return 'F'; }
function notFlag(value) { return !value ? 'n' : 'y'; }
function divFlag(left, right) { if (left / right) return 'T'; return 'F'; }
function bitFlag(value) { if (value & 1n) return 'T'; return 'F'; }
var values = [undefined, null, false, true, 0, -0, NaN, 1, -2, Infinity, 0n, 1n, '', 'x', '0', ' ', Symbol(), {}, [], new Boolean(false), new Number(0), function () { }];
for (var warm = 0; warm < 300; warm++) { for (var i = 0; i < values.length; i++) { flag(values[i]); notFlag(values[i]); } divFlag(warm & 1, 1); bitFlag(BigInt(warm & 3)); }
console.log(values.map(flag).join(''), values.map(notFlag).join(''), [[0, 1], [-0, 1], [0, 0], [1, 1], [-2, 1], [1, 0], [-1, Infinity]].map(function (x) { return divFlag(x[0], x[1]); }).join(''), [0n, 1n, 2n, 3n, -1n].map(bitFlag).join(''));
function cmp(x, y) {
  var s = 0;
  if (x < y) s += 1; if (x <= y) s += 2; if (x > y) s += 4; if (x >= y) s += 8;
  if (x == y) s += 16; if (x != y) s += 32; if (x === y) s += 64; if (x !== y) s += 128;
  return s;
}
var pairs = [[NaN, 1], [1, NaN], [NaN, NaN], [-0, 0], [-Infinity, Infinity], [Infinity, -Infinity], [1, '1'], ['a', 'b'], ['b', 'a'], ['10', '9'], ['10', 9],
  [null, undefined], [null, 0], [undefined, 0], [true, 1], [1n, 1], [2n, 1.5], ['', 0], [[2], 2], [{}, '[object Object]'], [2147483647, 2147483648], [-2147483648, -2147483649]];
var cr = [];
for (var k = 0; k < 100; k++) for (var p = 0; p < pairs.length; p++) cr[p] = cmp(pairs[p][0], pairs[p][1]);
console.log(cr.join(','));
var effects = 0;
function eff(v) { effects++; return v; }
function logic(a, b) { return [a && eff(b), a || eff(b), a ?? eff(b), a ? eff(1) : eff(2), !a && !b, (a, b)].map(String).join('/'); }
var lr = [];
for (var k = 0; k < 200; k++) { lr[0] = logic(0, 'x'); lr[1] = logic(null, 0); lr[2] = logic('s', NaN); lr[3] = logic(undefined, undefined); }
console.log(lr.join(' '), effects);
function chain(o) { return o?.a?.b ?? 'none'; }
function opt(f) { return f?.() ?? 'nf'; }
var oc = [];
for (var k = 0; k < 200; k++) { oc[0] = chain({ a: { b: 0 } }); oc[1] = chain({ a: null }); oc[2] = chain(null); oc[3] = opt(null); oc[4] = opt(function () { return null; }); oc[5] = opt(function () { return false; }); }
console.log(oc.join(','));
function pred(n) { return (n & 1) === 1; }
function branchBool(value, number) { if (value) return number; return number + 1; }
function runBool(count) { var sum = 0; for (var i = 0; i < count; i++) sum += branchBool(pred(i), i & 7); return sum; }
function branchReturn(value) { if (value & 1) return value; return value + 1; }
function runScalar(count) { var sum = 0; for (var i = 0; i < count; i++) sum += branchReturn(i & 7); return sum; }
console.log(runBool(10000), runScalar(10000), runBool(7), runScalar(1));
function ternaryChain(x) { return x < 0 ? 'neg' : x === 0 ? (1 / x < 0 ? '-zero' : 'zero') : x !== x ? 'nan' : x > 1e308 ? 'inf' : 'pos'; }
var tc = [];
for (var k = 0; k < 200; k++) tc = [-1, -0, 0, NaN, Infinity, 5, '-3', '', null].map(ternaryChain);
console.log(tc.join(','));
''', cli=cli)


@tiers
def test_regexp_and_packed_reads(run, workdir, cli):
    """CATCHES: specialised regexp statement loops (re.exec(list[i]) / /lit/.exec(s) / s.replace(/re/,
    x) / s.match(/re/) with discarded results) that skip the call and so lose lastIndex
    advancement and RegExp legacy statics ($1, lastMatch), and packed-element read fast paths
    that return wrong values for out-of-range, negative, fractional, NaN or Infinity indices,
    non-writable elements, prototype-resolved holes, regexp match index arrays, Object.entries
    pairs or proxies."""
    check_script(run, workdir, G, "regexp_and_packed_reads", r'''
var re = /(\w)(\d+)/g;
var list = [];
for (var i = 0; i < 100; i++) list.push('k' + i + ' z' + (i * 7));
function execLoop() { for (var i = 0; i < 100; i++) re.exec(list[i]); return re.lastIndex + ':' + RegExp.$1 + RegExp.$2 + ':' + RegExp.lastMatch; }
var el = [];
for (var r = 0; r < 4; r++) el.push(execLoop());
console.log('exec loop', el.join(' '));
function literalExec(k) { for (var i = 0; i < k; i++) { /q(\d)/.exec(list[i]); /(z)(\d)/.exec(list[i]); } return RegExp.$1 + RegExp.$2 + '|' + RegExp.leftContext + '|' + RegExp.rightContext; }
function constExec(k) { for (var i = 0; i < k; i++) { /c(o)nst/.exec('a const b'); } return RegExp.$1 + RegExp.lastMatch + RegExp.input; }
console.log('literal exec', literalExec(100), literalExec(7), constExec(50));
var out = [];
function replaceLoop(k) { for (var i = 0; i < k; i++) { list[i].replace(/(\d)(\d)/, '$2$1'); } return RegExp.lastMatch + RegExp.$2; }
function matchLoop(k) { for (var i = 0; i < k; i++) { list[i].match(/z(\d+)$/); } return RegExp.$1 + '/' + RegExp.input; }
console.log('replace/match', replaceLoop(100), replaceLoop(12), matchLoop(100), matchLoop(3));
function collect(text, rx) { var m, found = []; while ((m = rx.exec(text)) !== null) { found.push(m.index + '=' + m[0]); if (m[0] === '') rx.lastIndex++; } return found.join(','); }
var sentence = 'a1 b22 c333 d4444', results = [];
for (var r = 0; r < 50; r++) results[0] = collect(sentence, /[a-z](\d+)/g);
results.push(collect('aaa', /a*?/g), collect('x', /y/g), collect('ab\u{1F600}cd', /./gu));
console.log('exec while', results.join(' | '));
function read(a, k) { return a[k]; }
var lengths = [1, 10, 11, 32], pr = [];
for (var q = 0; q < lengths.length; q++) {
  var n = lengths[q], s = 'x';
  for (var j = 1; j < n; j++) s += ',x' + j;
  var a = s.split(',');
  for (var k = 0; k < 100; k++) read(a, k % n);
  pr.push(read(a, 0) + read(a, n - 1) + ':' + read(a, n) + ':' + read(a, -1) + ':' + read(a, 1.5) + ':' + read(a, NaN) + ':' + read(a, Infinity) + ':' + read(a, '0') + ':' + read(a, -0));
  Object.defineProperty(a, '0', { value: NaN, writable: false });
  a[0] = 17;
  pr.push(String(read(a, 0)));
}
var bigs = [123n, -1n];
for (var k = 0; k < 100; k++) read(bigs, k & 1);
pr.push(read(bigs, 0), read(bigs, 1), typeof read(bigs, 2));
console.log('packed', pr.join(' '));
function invoke(a, k) { return read(a, k); }
function pairSum(m) { return m.indices[0][0] + m.indices[0][1]; }
var m = /(a)(b)?/d.exec('za'), ir = [];
for (var k = 0; k < 200; k++) { ir[0] = pairSum(m); ir[1] = invoke(m, 1); ir[2] = invoke(m, 2); }
var p = m.indices[0];
ir.push(invoke(p, -1), invoke(p, 1.5), JSON.stringify(m.indices), m.index, m.input);
var gets = 0, proto = Object.create(Array.prototype);
Object.defineProperty(proto, '0', { get: function () { gets++; return 7; } });
Object.setPrototypeOf(p, proto); delete p[0];
ir.push(invoke(p, 0), gets);
Object.defineProperty(p, '0', { get: function () { gets++; return 9; }, configurable: true });
ir.push(invoke(p, 0), gets);
Object.defineProperty(p, '0', { value: 11, writable: true, configurable: true });
ir.push(invoke(p, 0)); p.length = 0; ir.push(invoke(p, 1));
Object.setPrototypeOf(p, Array.prototype); p.push(21, 22); ir.push(invoke(p, 1));
var child = { n: 33 }, entries = Object.entries({ a: child, b: child });
ir.push(invoke(invoke(entries, 0), 0), invoke(invoke(entries, 1), 1) === child);
var px = new Proxy([4], { get: function (t, k) { return k === '0' ? 8 : t[k]; } });
ir.push(invoke(px, 0), invoke(px, 'length'), invoke('str', 1), invoke('str', 5), invoke({ 1: 'one' }, 1));
console.log('indices', ir.join(' '));
function discards(words, re) {
  var n = 0;
  for (var i = 0; i < words.length; i++) {
    var w = words[i];
    w.split(re);
    w.split('-');
    w.replace(re, '#');
    w.replace(/[aeiou]/g, '');
    n += RegExp.lastMatch.length;
    re.exec(w);
    n += RegExp.$1.length * 100;
  }
  return n + ':' + re.lastIndex + ':' + RegExp.lastMatch + ':' + RegExp.$1;
}
var words = [];
for (var i = 0; i < 300; i++) words.push('w' + i + '-x' + (i % 13) + '-end');
console.log('discarded calls', discards(words, /(\d+)-/), discards(words, /x(\d+)/g), discards(['plain'], /q/));
''', cli=cli)


@tiers
def test_property_shapes_and_literals(run, workdir, cli):
    """CATCHES: compact own-property hints and shape caches that return a value from the wrong slot
    when objects with different layouts (padding fields, deleted/re-added keys, arrays with
    named props) reach the same hot read site, ignore an accessor installed after warm-up, or
    object-literal lowering that breaks constant computed keys, duplicate-key order, __proto__
    handling, inferred function names, getters/setters and spread order in hot object factories."""
    check_script(run, workdir, G, "property_shapes_and_literals", r'''
function readSite(o) { return o.child.value + 1; }
function middle(o) { return readSite(o); }
function site(o) { return middle(o); }
var a = { child: { value: 7 } }, b = { padding: 1, child: { padding: 2, value: 11 } }, r = [];
for (var i = 0; i < 300; i++) r[0] = site(a);
for (var i = 0; i < 40; i++) { r[1] = site(b); r[2] = site(a); }
var reads = 0;
Object.defineProperty(a.child, 'value', { configurable: true, get: function () { reads++; return 13; } });
r.push(site(a), reads);
Object.defineProperty(a.child, 'value', { configurable: true, writable: true, value: 15 });
r.push(site(a), reads);
delete a.child.value; r.push(site(a)); a.child.value = 1; r.push(site(a));
Object.setPrototypeOf(a.child, { value: 100 }); delete a.child.value; r.push(site(a));
function arrayRead(o) { return o.child.length + o.child.value; }
function arraySite(o) { return arrayRead(o); }
var arr = [1, 2, 3]; arr.value = 10; var holder = { child: arr };
var aw = 0;
for (var i = 0; i < 300; i++) aw += arraySite(holder);
r.push(aw);
arr.push(4, 5); r.push(arraySite(holder)); arr.length = 0; r.push(arraySite(holder));
delete arr.value; arr.padding = 2; arr.value = 12; r.push(arraySite(holder));
r.push(arraySite({ child: 'abcd' }), arraySite({ child: { length: 1, value: '!' } }));
console.log('hints', r.join(','));
function megamorphic(list) { var s = 0; for (var i = 0; i < list.length; i++) s += list[i].x; return s; }
var objs = [];
for (var i = 0; i < 600; i++) {
  var o = {};
  if (i % 3 === 0) o.a = i; if (i % 5 === 0) o.b = i; if (i % 7 === 0) o['c' + (i % 4)] = i;
  o.x = i % 10;
  if (i % 11 === 0) { delete o.x; o.x = -1; }
  if (i % 13 === 0) Object.defineProperty(o, 'x', { get: function () { return 100; } });
  objs.push(o);
}
console.log('megamorphic', megamorphic(objs), megamorphic(objs.slice(0, 50)));
function point(x, y) { return { x: x, y: y, ['len']: Math.abs(x) + Math.abs(y), ['to' + 'String']: function () { return '(' + this.x + ',' + this.y + ')'; } }; }
function dup(v) { return { a: 1, b: 2, a: v, ['b']: v * 2 }; }
function protoLit(p) { return { __proto__: p, own: 1 }; }
function protoComputed(p) { return { ['__proto__']: p, own: 1 }; }
function named() { return { f: function () { }, g: () => 1, ['h']: function () { }, k: class { }, get acc() { return 'g'; }, set acc(v) { this._v = v; } }; }
var lit = [];
for (var i = 0; i < 300; i++) { lit[0] = String(point(i, -i)); lit[1] = JSON.stringify(dup(i)); }
var pl = protoLit({ inherited: 'yes' }), pc = protoComputed({ inherited: 'yes' });
lit.push(pl.inherited, Object.keys(pl).join(), pc.inherited, Object.keys(pc).join(), typeof pc.__proto__, protoLit(null).toString);
var nm = named();
lit.push(nm.f.name, nm.g.name, nm.h.name, nm.k.name, Object.getOwnPropertyDescriptor(nm, 'acc').get.name, nm.acc);
nm.acc = 5; lit.push(nm._v, Object.keys(nm).join());
console.log('literals', lit.join(' | '));
function spreadMerge(a, b) { return { ...a, mid: 0, ...b }; }
var sm;
for (var i = 0; i < 300; i++) sm = spreadMerge({ x: i, mid: 9 }, { y: 2, x: -1 });
var getterSrc = { get g() { return 'computed'; } };
console.log('spread', JSON.stringify(sm), JSON.stringify(spreadMerge(getterSrc, null)), JSON.stringify(spreadMerge('ab', [7])), JSON.stringify({ ...{ 2: 'b', 1: 'a', z: 0 } }));
''', cli=cli)


@tiers
def test_name_resolution_paths(run, workdir, cli):
    """CATCHES: cached free-name resolution paths (globals, deep closure scopes, sloppy direct-eval
    scopes) that keep returning a stale binding after a global becomes an accessor, is deleted
    (must throw ReferenceError), is shadowed by an eval-introduced var, or when fresh
    activations of the same closure are created; also wrong this (must be undefined) for strict
    functions called by bare name."""
    check_script(run, workdir, G, "name_resolution_paths", r'''
let shared;
function make(local) { return () => [shared, target(local)]; }
globalThis.target = function (n) { 'use strict'; return this === undefined ? n : 'receiver'; };
var values = [undefined, null, true, 7, 1n, 'hello', Symbol.iterator, { x: 1 }], bad = 0;
for (var i = 0; i < 300; i++) { shared = values[i % values.length]; var res = make(i)(); if (res[0] !== shared || res[1] !== i) bad++; }
var reader = make(19), original = target, getters = 0, out = [bad];
Object.defineProperty(globalThis, 'target', { configurable: true, get: function () { getters++; return original; } });
for (var i = 0; i < 30; i++) out[1] = reader()[1];
out.push(getters);
delete globalThis.target;
try { reader(); } catch (e) { out.push(e.name + ': ' + e.message); }
globalThis.target = function () { return 'reinstalled'; };
out.push(reader()[1]);
console.log('globals', out.join(','));
var deepMaker = Function('return function(seed){eval("var deep=seed");return function(){eval("var middle=1");return function(){eval("var inner=2");return function(n){return [deep,middle,inner,n]}}()}()}')();
var obj = { value: 7 }, read = deepMaker(obj), dbad = 0;
for (var i = 0; i < 300; i++) { var rr = read(i); if (rr[0] !== obj || rr[3] !== i || rr[1] !== 1 || rr[2] !== 2) dbad++; }
console.log('eval scopes', dbad, JSON.stringify(deepMaker('s')(1)));
var g = 'global';
function shadowByEval(code) { var before = g; eval(code); return before + '>' + g; }
var se = [];
for (var i = 0; i < 50; i++) { se[0] = shadowByEval(''); se[1] = shadowByEval('var g = "local"'); }
se.push(g, shadowByEval('g = "assigned"'), g);
console.log('eval shadow', se.join(' '));
function counterFactory() { var count = 0; return function () { function inner() { return ++count; } return inner(); }; }
var cf = counterFactory(), cf2 = counterFactory(), cfr = 0;
for (var i = 0; i < 500; i++) cfr += cf();
console.log('deep closure', cfr, cf2(), cf());
function levels(a) { return function (b) { return function (c) { return function (d) { return function (e) { return function (f) { return function (h) { return a + b + c + d + e + f + h + depthBias; }; }; }; }; }; }; }
var depthBias = 1000, lv = 0, fnl = levels(1)(2)(3)(4)(5)(6);
for (var i = 0; i < 300; i++) lv += fnl(i);
depthBias = 0;
console.log('nine levels', lv, fnl(0), levels('a')('b')('c')('d')('e')('f')('g'));
var withObj = { wv: 'with' };
function sloppyWith() { var wv = 'local'; with (withObj) { return wv; } }
var ws = [];
for (var i = 0; i < 30; i++) ws[0] = sloppyWith();
delete withObj.wv; ws.push(sloppyWith());
withObj.wv = 'back'; ws.push(sloppyWith());
console.log('with', ws.join(','));
function typeofMissing() { return typeof notDeclaredAnywhere + ':' + typeof Math + ':' + (typeof undefinedVar === 'undefined'); }
var tm;
for (var i = 0; i < 300; i++) tm = typeofMissing();
globalThis.notDeclaredAnywhere = 1;
console.log('typeof', tm, typeofMissing());
''', cli=cli)


@tiers
def test_raytrace_prototype_classes(run, workdir, cli):
    """CATCHES: Prototype.js-style class shapes from the RayTrace benchmark: constructors that forward
    with this.initialize.apply(this, arguments), initialize bodies of the form `if (!r) r = 0;
    this.red = r` and `this.x = (x ? x : 0)`, Object.extend mixins via for-in, polymorphic shape
    intersection and deep float arithmetic; a tier that mis-forwards arguments, applies defaults
    to truthy values, ignores a replaced initialize/apply after warm-up or rounds differently
    fails."""
    check_script(run, workdir, G, "raytrace_prototype_classes", r'''
var Class = { create: function () { return function () { this.initialize.apply(this, arguments); }; } };
Object.extend = function (destination, source) { for (var property in source) destination[property] = source[property]; return destination; };
var RT = { Shape: {}, Material: {} };
RT.Color = Class.create();
RT.Color.prototype = {
  red: 0.0, green: 0.0, blue: 0.0,
  initialize: function (r, g, b) { if (!r) r = 0.0; if (!g) g = 0.0; if (!b) b = 0.0; this.red = r; this.green = g; this.blue = b; },
  limit: function () { this.red = (this.red > 0.0) ? ((this.red > 1.0) ? 1.0 : this.red) : 0.0; this.green = (this.green > 0.0) ? ((this.green > 1.0) ? 1.0 : this.green) : 0.0; this.blue = (this.blue > 0.0) ? ((this.blue > 1.0) ? 1.0 : this.blue) : 0.0; },
  brightness: function () { var r = Math.floor(this.red * 255), g = Math.floor(this.green * 255), b = Math.floor(this.blue * 255); return (r * 77 + g * 150 + b * 29) >> 8; },
  toString: function () { return 'rgb(' + Math.floor(this.red * 255) + ',' + Math.floor(this.green * 255) + ',' + Math.floor(this.blue * 255) + ')'; }
};
RT.Color.add = function (c1, c2) { var r = new RT.Color(0, 0, 0); r.red = c1.red + c2.red; r.green = c1.green + c2.green; r.blue = c1.blue + c2.blue; return r; };
RT.Color.multiply = function (c1, c2) { var r = new RT.Color(0, 0, 0); r.red = c1.red * c2.red; r.green = c1.green * c2.green; r.blue = c1.blue * c2.blue; return r; };
RT.Color.multiplyScalar = function (c1, f) { var r = new RT.Color(0, 0, 0); r.red = c1.red * f; r.green = c1.green * f; r.blue = c1.blue * f; return r; };
RT.Color.blend = function (c1, c2, w) { return RT.Color.add(RT.Color.multiplyScalar(c1, 1 - w), RT.Color.multiplyScalar(c2, w)); };
RT.Vector = Class.create();
RT.Vector.prototype = {
  x: 0.0, y: 0.0, z: 0.0,
  initialize: function (x, y, z) { this.x = (x ? x : 0); this.y = (y ? y : 0); this.z = (z ? z : 0); },
  normalize: function () { var m = this.magnitude(); return new RT.Vector(this.x / m, this.y / m, this.z / m); },
  magnitude: function () { return Math.sqrt((this.x * this.x) + (this.y * this.y) + (this.z * this.z)); },
  cross: function (w) { return new RT.Vector(-this.z * w.y + this.y * w.z, this.z * w.x - this.x * w.z, -this.y * w.x + this.x * w.y); },
  dot: function (w) { return this.x * w.x + this.y * w.y + this.z * w.z; }
};
RT.Vector.add = function (v, w) { return new RT.Vector(w.x + v.x, w.y + v.y, w.z + v.z); };
RT.Vector.subtract = function (v, w) { return new RT.Vector(v.x - w.x, v.y - w.y, v.z - w.z); };
RT.Vector.multiplyScalar = function (v, w) { return new RT.Vector(v.x * w, v.y * w, v.z * w); };
RT.Ray = Class.create();
RT.Ray.prototype = { position: null, direction: null, initialize: function (pos, dir) { this.position = pos; this.direction = dir; } };
RT.Light = Class.create();
RT.Light.prototype = { position: null, color: null, intensity: 10.0, initialize: function (pos, color, intensity) { this.position = pos; this.color = color; this.intensity = (intensity ? intensity : 10.0); } };
RT.Material.BaseMaterial = Class.create();
RT.Material.BaseMaterial.prototype = { gloss: 2.0, transparency: 0.0, reflection: 0.0, initialize: function () { }, wrapUp: function (t) { t = t % 2.0; if (t < -1) t += 2.0; if (t >= 1) t -= 2.0; return t; } };
RT.Material.Solid = Class.create();
RT.Material.Solid.prototype = Object.extend(new RT.Material.BaseMaterial(), {
  initialize: function (color, reflection, refraction, transparency, gloss) { this.color = color; this.reflection = reflection; this.transparency = transparency; this.gloss = gloss; this.hasTexture = false; },
  getColor: function (u, v) { return this.color; }
});
RT.Material.Chessboard = Class.create();
RT.Material.Chessboard.prototype = Object.extend(new RT.Material.BaseMaterial(), {
  colorEven: null, colorOdd: null, density: 0.5,
  initialize: function (colorEven, colorOdd, reflection, transparency, gloss, density) { this.colorEven = colorEven; this.colorOdd = colorOdd; this.reflection = reflection; this.transparency = transparency; this.gloss = gloss; this.density = density; this.hasTexture = true; },
  getColor: function (u, v) { var t = this.wrapUp(u * this.density) * this.wrapUp(v * this.density); return t < 0.0 ? this.colorEven : this.colorOdd; }
});
RT.IntersectionInfo = Class.create();
RT.IntersectionInfo.prototype = { isHit: false, hitCount: 0, shape: null, position: null, normal: null, color: null, distance: null, initialize: function () { this.color = new RT.Color(0, 0, 0); } };
RT.Shape.Sphere = Class.create();
RT.Shape.Sphere.prototype = {
  initialize: function (pos, radius, material) { this.radius = radius; this.position = pos; this.material = material; },
  intersect: function (ray) {
    var info = new RT.IntersectionInfo(); info.shape = this;
    var dst = RT.Vector.subtract(ray.position, this.position);
    var B = dst.dot(ray.direction), C = dst.dot(dst) - (this.radius * this.radius), D = (B * B) - C;
    if (D > 0) {
      info.isHit = true; info.distance = (-B) - Math.sqrt(D);
      info.position = RT.Vector.add(ray.position, RT.Vector.multiplyScalar(ray.direction, info.distance));
      info.normal = RT.Vector.subtract(info.position, this.position).normalize();
      info.color = this.material.getColor(0, 0);
    } else info.isHit = false;
    return info;
  }
};
RT.Shape.Plane = Class.create();
RT.Shape.Plane.prototype = {
  d: 0.0,
  initialize: function (pos, d, material) { this.position = pos; this.d = d; this.material = material; },
  intersect: function (ray) {
    var info = new RT.IntersectionInfo();
    var Vd = this.position.dot(ray.direction);
    if (Vd == 0) return info;
    var t = -(this.position.dot(ray.position) + this.d) / Vd;
    if (t <= 0) return info;
    info.shape = this; info.isHit = true;
    info.position = RT.Vector.add(ray.position, RT.Vector.multiplyScalar(ray.direction, t));
    info.normal = this.position; info.distance = t;
    if (this.material.hasTexture) { var vU = new RT.Vector(this.position.y, this.position.z, -this.position.x), vV = vU.cross(this.position); info.color = this.material.getColor(info.position.dot(vU), info.position.dot(vV)); }
    else info.color = this.material.getColor(0, 0);
    return info;
  }
};
function testIntersection(ray, shapes, exclude) {
  var hits = 0, best = new RT.IntersectionInfo(); best.distance = 2000;
  for (var i = 0; i < shapes.length; i++) {
    var shape = shapes[i];
    if (shape != exclude) { var info = shape.intersect(ray); if (info.isHit && info.distance >= 0 && info.distance < best.distance) { best = info; hits++; } }
  }
  best.hitCount = hits;
  return best;
}
function rayTrace(info, ray, scene, depth) {
  var color = RT.Color.multiplyScalar(info.color, 0.2);
  for (var i = 0; i < scene.lights.length; i++) {
    var light = scene.lights[i], v = RT.Vector.subtract(light.position, info.position).normalize();
    var L = v.dot(info.normal);
    if (L > 0.0) color = RT.Color.add(color, RT.Color.multiply(info.color, RT.Color.multiplyScalar(light.color, L)));
    if (depth <= 2 && info.shape.material.reflection > 0) {
      var N = info.normal, V = ray.direction, R = RT.Vector.subtract(V, RT.Vector.multiplyScalar(N, 2 * N.dot(V)));
      var refl = testIntersection(new RT.Ray(RT.Vector.add(info.position, RT.Vector.multiplyScalar(R, 0.001)), R), scene.shapes, info.shape);
      if (refl.isHit && refl.distance > 0) color = RT.Color.blend(color, rayTrace(refl, new RT.Ray(info.position, R), scene, depth + 1), info.shape.material.reflection);
    }
    var shadow = testIntersection(new RT.Ray(info.position, v), scene.shapes, info.shape);
    if (shadow.isHit && shadow.shape != info.shape) color = RT.Color.multiplyScalar(color, 0.5 + 0.5 * Math.pow(shadow.shape.material.transparency, 0.5));
  }
  color.limit();
  return color;
}
function render(w, h) {
  var scene = { shapes: [], lights: [] };
  scene.shapes.push(new RT.Shape.Plane(new RT.Vector(0.1, 0.9, -0.5).normalize(), 1.2, new RT.Material.Chessboard(new RT.Color(1, 1, 1), new RT.Color(0, 0, 0), 0.2, 0.0, 1.0, 0.7)));
  scene.shapes.push(new RT.Shape.Sphere(new RT.Vector(-1.5, 1.5, 2), 1.5, new RT.Material.Solid(new RT.Color(0, 0.5, 0.5), 0.3, 0.0, 0.0, 2.0)));
  scene.shapes.push(new RT.Shape.Sphere(new RT.Vector(1, 0.25, 1), 0.5, new RT.Material.Solid(new RT.Color(0.9, 0.9, 0.9), 0.1, 0.0, 0.0, 1.5)));
  scene.lights.push(new RT.Light(new RT.Vector(5, 10, -1), new RT.Color(0.8, 0.8, 0.8)));
  scene.lights.push(new RT.Light(new RT.Vector(-3, 5, -15), new RT.Color(0.8, 0.8, 0.8), 100));
  var eye = new RT.Vector(0, 0, -15), rows = [], sum = 0, hits = 0;
  for (var y = 0; y < h; y++) {
    var row = '';
    for (var x = 0; x < w; x++) {
      var dir = new RT.Vector((x / w) * 2 - 1, -((y / h) * 2 - 1) * 0.75, 3).normalize();
      var ray = new RT.Ray(eye, dir), info = testIntersection(ray, scene.shapes, null), c;
      if (info.isHit) { hits++; c = rayTrace(info, ray, scene, 0); } else c = new RT.Color(0, 0, 0);
      var b = c.brightness(); sum += b; row += ' .:-=+*#%@'[Math.min(9, Math.floor(b / 26))];
    }
    rows.push(row);
  }
  return { sum: sum, hits: hits, rows: rows };
}
var img;
img = render(30, 12);
console.log('render', img.sum, img.hits);
console.log(img.rows.join('\n'));
var c = new RT.Color(0, '', NaN), v = new RT.Vector(0, -0, 'z'), l = new RT.Light(v, c, 0);
console.log('falsy defaults', c.red, c.green, c.blue, v.x, Object.is(v.y, -0), v.z, l.intensity, String(new RT.Color(0.5, 2, -1)), new RT.Color(1, 1, 1, 'extra').red);
var calls = 0, saved = RT.Vector.prototype.initialize;
RT.Vector.prototype.initialize = function (x, y, z) { calls++; saved.call(this, x * 2, y, z); };
var doubled = new RT.Vector(1, 2, 3);
RT.Vector.prototype.initialize = saved;
var Point = Class.create();
Point.prototype = { initialize: function () { this.n = arguments.length; this.args = Array.prototype.join.call(arguments, '/'); } };
var p0 = new Point(), p3 = new Point(1, 'b', null);
Point.prototype.initialize = function (a) { this.n = -1; this.first = a; };
var pr = new Point(9, 8);
Object.defineProperty(Point.prototype, 'initialize', { get: function () { calls++; return function (q) { this.viaGetter = q; }; } });
var pg = new Point('g');
console.log('forwarders', doubled.x, calls, p0.n + ':' + p0.args, p3.n + ':' + p3.args, pr.n + ':' + pr.first, pg.viaGetter);
var Broken = Class.create();
Broken.prototype = {};
try { new Broken(1); } catch (e) { console.log('missing initialize', e.name); }
''', cli=cli)


@tiers
def test_crypto_bignum_digits(run, workdir, cli):
    """CATCHES: the Crypto benchmark's jsbn-style big-integer kernels: am3 multiply-accumulate on
    28-bit digits stored as integer-keyed properties of plain objects (this[i], w[j++]) with
    &0x3fff, >>14, >>28 and &0xfffffff, carry propagation, squaring and Montgomery-free modular
    exponentiation; results are cross-checked against BigInt, so any int32/double confusion in
    the hot digit loops or a stale element cache on the digit objects changes the printed
    values."""
    check_script(run, workdir, G, "crypto_bignum_digits", r'''
var DB = 28, DM = (1 << DB) - 1, DV = 1 << DB;
function BigInt28() { this.t = 0; this.s = 0; }
BigInt28.prototype.am = function (i, x, w, j, c, n) {
  var xl = x & 0x3fff, xh = x >> 14;
  while (--n >= 0) {
    var l = this[i] & 0x3fff;
    var h = this[i++] >> 14;
    var m = xh * l + h * xl;
    l = xl * l + ((m & 0x3fff) << 14) + w[j] + c;
    c = (l >> 28) + (m >> 14) + xh * h;
    w[j++] = l & 0xfffffff;
  }
  return c;
};
BigInt28.prototype.clamp = function () { var c = this.s & DM; while (this.t > 0 && this[this.t - 1] == c) --this.t; };
BigInt28.prototype.fromInt = function (x) { this.t = 1; this.s = 0; this[0] = x; if (x >= DV) { this[0] = x & DM; this[1] = Math.floor(x / DV); this.t = 2; } return this; };
BigInt28.prototype.multiplyTo = function (a, r) {
  var i = a.t; r.t = i + this.t;
  while (--i >= 0) r[i] = 0;
  for (i = 0; i < this.t; ++i) r[i + a.t] = a.am(0, this[i], r, i, 0, a.t);
  r.s = 0; r.clamp(); return r;
};
BigInt28.prototype.squareTo = function (r) { return this.multiplyTo(this, r); };
BigInt28.prototype.addTo = function (a, r) {
  var i = 0, c = 0, m = Math.min(a.t, this.t);
  while (i < m) { c += this[i] + a[i]; r[i++] = c & DM; c >>= DB; }
  if (a.t < this.t) { while (i < this.t) { c += this[i]; r[i++] = c & DM; c >>= DB; } }
  else { while (i < a.t) { c += a[i]; r[i++] = c & DM; c >>= DB; } }
  if (c > 0) r[i++] = c;
  r.t = i; r.clamp(); return r;
};
BigInt28.prototype.divSmall = function (d) { var rem = 0; for (var i = this.t - 1; i >= 0; i--) { var cur = rem * DV + this[i]; this[i] = Math.floor(cur / d); rem = cur % d; } this.clamp(); return rem; };
BigInt28.prototype.copy = function () { var r = new BigInt28(); for (var i = 0; i < this.t; i++) r[i] = this[i]; r.t = this.t; r.s = this.s; return r; };
BigInt28.prototype.toBig = function () { var v = 0n; for (var i = this.t - 1; i >= 0; i--) v = (v << 28n) + BigInt(this[i]); return v; };
BigInt28.prototype.toString = function () { var digits = [], x = this.copy(); if (x.t === 0) return '0'; while (x.t > 0) { var r = x.divSmall(10000); digits.push(x.t > 0 ? String(r + 10000).slice(1) : String(r)); } return digits.reverse().join(''); };
function factorial(n) { var acc = new BigInt28().fromInt(1); for (var k = 2; k <= n; k++) { var r = new BigInt28(); acc.multiplyTo(new BigInt28().fromInt(k), r); acc = r; } return acc; }
function power(base, e) { var result = new BigInt28().fromInt(1), b = new BigInt28().fromInt(base); while (e > 0) { if (e & 1) { var t = new BigInt28(); result.multiplyTo(b, t); result = t; } e >>= 1; if (e) { var s = new BigInt28(); b.squareTo(s); b = s; } } return result; }
function fibBig(n) { var a = new BigInt28().fromInt(0), b = new BigInt28().fromInt(1); for (var i = 0; i < n; i++) { var c = new BigInt28(); a.addTo(b, c); a = b; b = c; } return a; }
var f = factorial(120), fs = f.toString();
var exact = 1n; for (var k = 2n; k <= 120n; k++) exact *= k;
console.log('120!', fs.length, fs.slice(0, 20), fs.slice(-30), f.toBig() === exact, f.t);
var p = power(3, 500), pe = 3n ** 500n;
console.log('3^500', p.toBig() === pe, p.toString().slice(0, 24), p.t, (pe % 1000000007n).toString());
var fb = fibBig(700);
var fa = 0n, fbb = 1n; for (var i = 0; i < 700; i++) { var tmp = fa + fbb; fa = fbb; fbb = tmp; }
console.log('fib700', fb.toBig() === fa, fb.toString().length, fb.toString().slice(-12));
var probe = new BigInt28().fromInt(DV * 5 + 7);
console.log('fromInt', probe.t, probe[0], probe[1], probe.toString(), new BigInt28().fromInt(DM).am(0, DM, { 0: 0 }, 0, 0, 1), String(new BigInt28().fromInt(0)));
var digitsArr = [DM, DM, DM], w = [0, 0, 0, 0];
var carry = BigInt28.prototype.am.call(digitsArr, 0, DM, w, 0, 0, 3);
console.log('array receiver', carry, w.join(','), BigInt28.prototype.am.call({ 0: '5' }, 0, 3, [1], 0, 0, 1));
''', cli=cli)


@tiers
def test_navier_stokes_arrays(run, workdir, cli):
    """CATCHES: NavierStokes-style solver loops over plain numeric arrays (x[i] += dt*s[i], Gauss-
    Seidel lin_solve with computed row offsets, bilinear advection with Math.floor/clamping,
    boundary mirroring with sign flips): a tier whose numeric array mirrors or element stores
    drop a write, read a stale element after an in-place update, or round differently changes
    the checksums; the arrays are also mutated into holey/non-number states after warm-up to
    force guard exits."""
    check_script(run, workdir, G, "navier_stokes_arrays", r'''
function FluidField(width, height) {
  var rowSize = width + 2, size = (width + 2) * (height + 2);
  var iterations = 6, dt = 0.1;
  function addFields(x, s, dt) { for (var i = 0; i < size; i++) x[i] += dt * s[i]; }
  function set_bnd(b, x) {
    if (b === 1) { for (var i = 1; i <= width; i++) { x[i] = x[i + rowSize]; x[i + (height + 1) * rowSize] = x[i + height * rowSize]; } for (var j = 1; j <= height; j++) { x[j * rowSize] = -x[1 + j * rowSize]; x[(width + 1) + j * rowSize] = -x[width + j * rowSize]; } }
    else if (b === 2) { for (var i = 1; i <= width; i++) { x[i] = -x[i + rowSize]; x[i + (height + 1) * rowSize] = -x[i + height * rowSize]; } for (var j = 1; j <= height; j++) { x[j * rowSize] = x[1 + j * rowSize]; x[(width + 1) + j * rowSize] = x[width + j * rowSize]; } }
    else { for (var i = 1; i <= width; i++) { x[i] = x[i + rowSize]; x[i + (height + 1) * rowSize] = x[i + height * rowSize]; } for (var j = 1; j <= height; j++) { x[j * rowSize] = x[1 + j * rowSize]; x[(width + 1) + j * rowSize] = x[width + j * rowSize]; } }
    var maxEdge = (height + 1) * rowSize;
    x[0] = 0.5 * (x[1] + x[rowSize]);
    x[maxEdge] = 0.5 * (x[1 + maxEdge] + x[height * rowSize]);
    x[(width + 1)] = 0.5 * (x[width] + x[(width + 1) + rowSize]);
    x[(width + 1) + maxEdge] = 0.5 * (x[width + maxEdge] + x[(width + 1) + height * rowSize]);
  }
  function lin_solve(b, x, x0, a, c) {
    if (a === 0 && c === 1) {
      for (var j = 1; j <= height; j++) { var currentRow = j * rowSize; ++currentRow; for (var i = 0; i < width; i++) { x[currentRow] = x0[currentRow]; ++currentRow; } }
      set_bnd(b, x);
    } else {
      var invC = 1 / c;
      for (var k = 0; k < iterations; k++) {
        for (var j = 1; j <= height; j++) {
          var lastRow = (j - 1) * rowSize, currentRow = j * rowSize, nextRow = (j + 1) * rowSize;
          var lastX = x[currentRow];
          ++currentRow;
          for (var i = 1; i <= width; i++) lastX = x[currentRow] = (x0[currentRow] + a * (lastX + x[++currentRow] + x[++lastRow] + x[++nextRow])) * invC;
        }
        set_bnd(b, x);
      }
    }
  }
  function diffuse(b, x, x0, dt) { var a = 0; lin_solve(b, x, x0, a, 1 + 4 * a); }
  function advect(b, d, d0, u, v, dt) {
    var Wdt0 = dt * width, Hdt0 = dt * height, Wp5 = width + 0.5, Hp5 = height + 0.5;
    for (var j = 1; j <= height; j++) {
      var pos = j * rowSize;
      for (var i = 1; i <= width; i++) {
        var x = i - Wdt0 * u[++pos], y = j - Hdt0 * v[pos];
        if (x < 0.5) x = 0.5; else if (x > Wp5) x = Wp5;
        var i0 = x | 0, i1 = i0 + 1;
        if (y < 0.5) y = 0.5; else if (y > Hp5) y = Hp5;
        var j0 = y | 0, j1 = j0 + 1;
        var s1 = x - i0, s0 = 1 - s1, t1 = y - j0, t0 = 1 - t1;
        var row1 = j0 * rowSize, row2 = j1 * rowSize;
        d[pos] = s0 * (t0 * d0[i0 + row1] + t1 * d0[i0 + row2]) + s1 * (t0 * d0[i1 + row1] + t1 * d0[i1 + row2]);
      }
    }
    set_bnd(b, d);
  }
  function project(u, v, p, div) {
    var h = -0.5 / Math.sqrt(width * height);
    for (var j = 1; j <= height; j++) { var row = j * rowSize, previousRow = (j - 1) * rowSize, prevValue = row - 1, currentRow = row, nextValue = row + 1, nextRow = (j + 1) * rowSize;
      for (var i = 1; i <= width; i++) { div[++currentRow] = h * (u[++nextValue] - u[++prevValue] + v[++nextRow] - v[++previousRow]); p[currentRow] = 0; } }
    set_bnd(0, div); set_bnd(0, p);
    lin_solve(0, p, div, 1, 4);
    var wScale = 0.5 * width, hScale = 0.5 * height;
    for (var j = 1; j <= height; j++) { var prevPos = j * rowSize - 1, currentPos = j * rowSize, nextPos = j * rowSize + 1, prevRow = (j - 1) * rowSize, currentRow = j * rowSize, nextRow = (j + 1) * rowSize;
      for (var i = 1; i <= width; i++) { u[++currentPos] -= wScale * (p[++nextPos] - p[++prevPos]); v[currentPos] -= hScale * (p[++nextRow] - p[++prevRow]); } }
    set_bnd(1, u); set_bnd(2, v);
  }
  function dens_step(x, x0, u, v, dt) { addFields(x, x0, dt); diffuse(0, x0, x, dt); advect(0, x, x0, u, v, dt); }
  function vel_step(u, v, u0, v0, dt) { addFields(u, u0, dt); addFields(v, v0, dt); var temp = u0; u0 = u; u = temp; temp = v0; v0 = v; v = temp; diffuse(1, u, u0, dt); diffuse(2, v, v0, dt); project(u, v, u0, v0); temp = u0; u0 = u; u = temp; temp = v0; v0 = v; v = temp; advect(1, u, u0, u0, v0, dt); advect(2, v, v0, u0, v0, dt); project(u, v, u0, v0); }
  function fresh() { var a = new Array(size); for (var i = 0; i < size; i++) a[i] = 0; return a; }
  var dens = fresh(), dens_prev = fresh(), u = fresh(), u_prev = fresh(), v = fresh(), v_prev = fresh();
  this.arrays = { dens: dens, u: u, v: v, dens_prev: dens_prev };
  this.update = function (frame) {
    for (var i = 0; i < size; i++) u_prev[i] = v_prev[i] = dens_prev[i] = 0.0;
    var cx = (width >> 1) + 1, cy = (height >> 1) + 1;
    dens_prev[cx + cy * rowSize] = 50 + frame;
    u_prev[cx + cy * rowSize] = 3 * Math.cos(frame * 0.5) > 0 ? 2 : -2;
    v_prev[cx + 2 + cy * rowSize] = frame % 3 - 1;
    vel_step(u, v, u_prev, v_prev, dt);
    dens_step(dens, dens_prev, u, v, dt);
  };
}
function checksum(a) { var s = 0, w = 0; for (var i = 0; i < a.length; i++) { s += a[i]; w += a[i] * ((i % 7) + 1); } return s.toPrecision(12) + '/' + w.toPrecision(12); }
var field = new FluidField(20, 20);
for (var f = 0; f < 12; f++) field.update(f);
console.log('dens', checksum(field.arrays.dens));
console.log('u', checksum(field.arrays.u));
console.log('v', checksum(field.arrays.v));
var getterReads = 0;
field.arrays.dens[30] = { valueOf: function () { return 2; } };
field.arrays.u[45] = true;
Object.defineProperty(field.arrays.v, 50, { get: function () { getterReads++; return 0.5; }, set: function (x) { }, configurable: true });
for (var f = 12; f < 15; f++) field.update(f);
console.log('after shape changes', checksum(field.arrays.dens), checksum(field.arrays.u), checksum(field.arrays.v), getterReads, typeof field.arrays.dens[30]);
var small = new FluidField(4, 3);
small.update(1);
console.log('small', small.arrays.dens.map(function (x) { return x.toFixed(6); }).slice(6, 14).join(' '));
''', cli=cli)
