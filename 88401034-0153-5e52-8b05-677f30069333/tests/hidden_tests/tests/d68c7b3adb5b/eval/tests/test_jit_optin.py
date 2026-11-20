"""Opt-in and kill-switch JIT environment variables must change performance only, never results.

docs/closure-call-cache.md, docs/shared-closure-inlining.md, docs/closure-numeric-regions.md and
docs/optimizer.md document process-wide switches: the opt-ins `LUMEN_JIT_INLINE_CLOSURES=1`
(guarded inlining of fresh closures that share their caller's environment),
`LUMEN_JIT_REFRESH_CLOSURE_CACHE=1` (publishing validated fresh-closure retries into the native
call cache) and `LUMEN_JIT_FRESH_CLOSURE_RETRY=1` (the no-activation fresh-closure retry), plus
same-binary kill switches such as `LUMEN_JIT_NO_CFG_REGALLOC=1` that select a retained/fallback
code path. Every test runs one program with the switch off, with each switch
on, and on the bytecode VM, and compares all runs against ONE shared golden: a switch that alters
any observable result (values, `fn.caller` reflection, receivers, exceptions, GC lifetime) fails.
"""

import pytest

from conftest import out

INLINE = {"LUMEN_JIT_INLINE_CLOSURES": "1"}
REFRESH = {"LUMEN_JIT_REFRESH_CLOSURE_CACHE": "1"}
RETRY = {"LUMEN_JIT_FRESH_CLOSURE_RETRY": "1"}
ALL = {**INLINE, **REFRESH, **RETRY}

CLOSURE_MODES = [
    pytest.param({}, (), id="off"),
    pytest.param(INLINE, (), id="inline"),
    pytest.param(REFRESH, (), id="refresh"),
    pytest.param(RETRY, (), id="retry"),
    pytest.param(ALL, (), id="all"),
    pytest.param(ALL, ("--tier=bytecode",), id="all-bytecode"),
    pytest.param({}, ("--tier=bytecode",), id="off-bytecode"),
]


def kill_modes(*names):
    """Default JIT, each kill switch alone, all of them together, and the bytecode VM."""
    modes = [pytest.param({}, (), id="default")]
    modes += [pytest.param({n: "1"}, (), id=n.removeprefix("LUMEN_").lower()) for n in names]
    modes.append(pytest.param({n: "1" for n in names}, (), id="all-switches"))
    modes.append(pytest.param({}, ("--tier=bytecode",), id="bytecode"))
    return modes


def check(js, golden, name, code, switches, tier):
    r = js(code, *tier, env_overrides=switches)
    assert out(r) == golden(name)
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------ closure opt-ins
@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_fresh_closure_batches_from_the_call_cache_fixture(js, golden, switches, tier):
    """CATCHES: a refreshed or retried fresh-closure call cache that keeps calling an older closure instance (stale `seed` capture), so the per-batch self-checked sums of crates/lumen/benches/fixtures/closure_calls.js differ from the switch-off run."""
    code = r"""
function factory(seed) { return function(x) { return seed + x; }; }
function invoke(f, x) { return f(x); }
function run(n) {
  let total = 0;
  for (let i = 0; i < n; i++) {
    const f = factory(i);
    for (let j = 0; j < 32; j++) total += invoke(f, j);
  }
  const expected = 16 * n * (n - 1) + 496 * n;
  if (total !== expected) throw new Error('wrong sum: ' + total + ' expected ' + expected);
  return total;
}
console.log('warm', run(500));
for (let k = 1; k <= 5; k++) console.log('ClosureBatch', k, run(80 * k));
"""
    check(js, golden, "closure_batches", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_shared_sibling_closure_batches_fixture(js, golden, switches, tier):
    """CATCHES: a shared-closure inline guard that accepts a sibling `leaf` from a different factory activation, so batch() reads the wrong `seed` and the shared_closure_calls.js self-checked totals change."""
    code = r"""
// A fresh sibling closure shares its caller's lexical environment on every batch.
function factory(seed) {
  function leaf(x) { return seed + x; }
  function batch() {
    let total = 0;
    for (let j = 0; j < 32; j++) total += leaf(j);
    return total;
  }
  return batch;
}
function run(n) {
  let total = 0;
  for (let i = 0; i < n; i++) total += factory(i)();
  const expected = 32 * n * (n - 1) / 2 + 496 * n;
  if (total !== expected) throw new Error('wrong sum: ' + total);
  return total;
}
function warm() {
  const batch = factory(0);
  for (let i = 0; i < 150; i++) if (batch() !== 496) throw new Error('warm sum');
  return batch();
}
console.log('warm', warm());
for (let k = 1; k <= 5; k++) console.log('SharedClosureBatch', k, run(100 * k));
"""
    check(js, golden, "shared_batches", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_fresh_closures_reflect_live_callee_receiver_and_survive_gc(js, golden, switches, tier):
    """CATCHES: a fresh-closure retry that records the originally cached closure in the frame (so `inspect.caller` is not the live closure), loses the `box.f(x)` receiver, or reuses a published cache entry after GC collected its closure."""
    code = r"""
function inspect(){eval('');return inspect.caller;}
var expected=null, mismatches=0;
function factory(seed){return function(x){
  if(inspect()!==expected) mismatches++;
  return seed+x+this.bias;
};}
function invoke(box,x){return box.f(x);}
var box={bias:5};
function warm(){ expected=factory(1); box.f=expected; var s=0; for(var i=0;i<500;i++) s+=invoke(box,2); return s; }
console.log('warm', warm(), mismatches);
function fresh(){
  expected=null;box.f=null;$262.gc();
  var out=[];
  for(var i=0;i<20;i++){ expected=factory(i);box.f=expected; out.push(invoke(box,2)); }
  return out.join(',');
}
console.log('fresh', fresh(), mismatches);
function repeated(){
  expected=factory(100);box.f=expected;
  var rep=[];
  for(var j=0;j<100;j++) rep.push(invoke(box,j%3));
  return rep.slice(0,6).join(',')+' sum='+rep.reduce(function(a,b){return a+b;},0);
}
console.log('repeated', repeated(), mismatches);
function replacement(){
  expected=null;box.f=null;$262.gc();
  var tot=0;
  for(var i=0;i<50;i++){ expected=factory(i);box.f=expected; for(var j=0;j<10;j++) tot+=invoke(box,j); }
  return tot;
}
console.log('replacement', replacement(), mismatches);
box.bias='b';
console.log('string bias', invoke(box,1), mismatches);
"""
    check(js, golden, "reflect_receiver_gc", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_fresh_closure_throws_unwind_and_evaluate_arguments_once(js, golden, switches, tier):
    """CATCHES: a retried or refreshed native call that replays argument evaluation (argument() counted twice) or leaks the frame when a fresh closure throws, so the caught-exception and call counts differ from the plain call path."""
    code = r"""
function factory(seed){return function(x){if(seed<0)throw x;return seed+x;};}
function invoke(f,x){return f(x);}
function warm(){ var first=factory(1), s=0; for(var i=0;i<500;i++) s+=invoke(first,2); return s; }
console.log('warm', warm());
var calls=0;
function argument(){calls++;return 19;}
function freshThrows(){ var caught=0; for(var i=0;i<20;i++){ try{invoke(factory(-1),argument());}catch(e){ if(e===19) caught++; } } return caught; }
console.log('fresh throws', freshThrows(), calls);
function sameThrows(){ var fresh=factory(-1), caught=0; for(var i=0;i<100;i++){ try{invoke(fresh,argument());}catch(e){ if(e===19) caught++; } } return caught; }
console.log('same throws', sameThrows(), calls);
function tiered(){ var last=0, sum=0; for(var i=0;i<600;i++){ last=invoke(factory(i),3); sum+=last; } return last+' '+sum; }
console.log('tiered', tiered());
function errorObjects(){
  var msgs=[];
  for(var i=0;i<4;i++){ try{ invoke(factory(-1), new RangeError('r'+i)); }catch(e){ msgs.push(e.name+':'+e.message); } }
  return msgs.join(' ');
}
console.log(errorObjects());
"""
    check(js, golden, "throws_once", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_shared_inline_reports_the_live_leaf_as_caller(js, golden, switches, tier):
    """CATCHES: a shared-closure splice whose reflection metadata still names the closure it was compiled against, so `inspect.caller` inside a fresh `leaf` is not that leaf (wrong-caller count becomes non-zero), the fresh captures are not read, or one caller activation that calls three same-body closures reports a stale one."""
    code = r"""
function inspect() { eval(''); return inspect.caller; }
var wrong=[];
function make(seed) {
  function leaf(x) {
    if(inspect()!==leaf) wrong.push(seed);
    return seed+x;
  }
  function invoke(x) { return leaf(x); }
  function twice(x) { return invoke(x) + leaf(x * 2); }
  return {leaf:leaf,invoke:invoke,twice:twice};
}
var first=make(3);
function warm(){ var s=0; for(var n=0;n<500;n++) s+=first.invoke(4)+first.twice(1); return s; }
console.log('warm', warm());
function fresh(){ var out=[]; for(var n=0;n<40;n++){ var next=make(n); out.push(next.invoke(4)+'/'+next.twice(n)); } return out.join(','); }
console.log(fresh());
console.log('wrong callers', wrong.length, wrong.slice(0,5).join(','));
// Three closures of one function body share one environment; one caller activation calls all three.
function makeTrio(seed) {
  var fns = [];
  for (var i = 0; i < 3; i++) fns.push(function (x) { var c = inspect(); return (c === fns[0] ? 'a' : c === fns[1] ? 'b' : c === fns[2] ? 'c' : '?') + (seed + x); });
  function callAll(x) { var s = ''; for (var k = 0; k < fns.length; k++) s += fns[k](x); return s; }
  return callAll;
}
var trio = makeTrio(1);
function warmTrio() { var s = ''; for (var n = 0; n < 300; n++) s = trio(n); return s; }
console.log(warmTrio());
function freshTrio() { var out = []; for (var n = 0; n < 5; n++) out.push(makeTrio(n * 10)(n)); return out.join(' '); }
console.log(freshTrio());
"""
    check(js, golden, "inline_live_caller", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_inline_guards_fall_back_for_foreign_and_exotic_callees(js, golden, switches, tier):
    """CATCHES: a shared-function inline guard that accepts a callee from another environment, another function body, a Proxy, a bound function, a class, an arrow, a native or undefined, instead of running the original call with its own result or TypeError."""
    code = r"""
function make(seed) {
  function leaf(x) {return seed+x;}
  function invoke(f,x) {return f(x);}
  return {leaf:leaf,invoke:invoke};
}
var first=make(3), second=make(20);
function warm(){ var s=0; for(var n=0;n<500;n++) s+=first.invoke(first.leaf,4); return s; }
console.log('warm', warm());
function probe(){
  var out=[];
  out.push('foreign env '+first.invoke(second.leaf,4));
  out.push('foreign AST '+first.invoke(function(x){return 50+x;},4));
  var count=0;
  var proxy=new Proxy(first.leaf,{apply:function(f,t,args){count++;return 90+args[0];}});
  out.push('proxy '+first.invoke(proxy,4)+' '+count);
  out.push('bound '+first.invoke(second.leaf.bind(null),4));
  try {first.invoke(class C {},4); out.push('no throw');} catch(e) {out.push('class '+(e instanceof TypeError));}
  out.push('arrow '+first.invoke((x)=>x*2,4));
  out.push('native '+first.invoke(Math.abs,-4));
  try { first.invoke(undefined, 1); out.push('no throw'); } catch(e) { out.push('undefined '+e.constructor.name); }
  out.push('generator '+first.invoke(function*(x){ yield x; }, 7).next().value);
  out.push('back '+first.invoke(first.leaf,5)+' '+first.invoke(second.leaf,5));
  return out.join('\n');
}
console.log(probe());
"""
    check(js, golden, "guard_fallbacks", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_nested_fresh_inlines_with_getters_exceptions_and_gc(js, golden, switches, tier):
    """CATCHES: nested fresh inlines that report the wrong `caller` chain to a getter, keep `leaf.caller` non-null after an exception unwinds, drop `leaf`/`middle` from the stack trace, or let GC free the active callee once its only reference is cleared."""
    code = r"""
function make(seed) {
  function leaf(holder) {
    if(holder.drop) {holder.fn=null; $262.gc();}
    if(holder.fail) throw new Error('expected');
    return holder.value+seed;
  }
  function middle(holder) {return holder.fn(holder);}
  function invoke(holder) {return middle(holder);}
  return {leaf:leaf,middle:middle,invoke:invoke};
}
var first=make(3);
function warm(){ var h0={fn:first.leaf,value:4,drop:false,fail:false}, s=0; for(var n=0;n<500;n++) s+=first.invoke(h0); return s; }
console.log('warm', warm());
var next=make(20);
var holder={fn:next.leaf,drop:false,fail:false};
var log=[];
Object.defineProperty(holder,'value',{get:function inspectValue(){
  log.push((inspectValue.caller===holder.expected)+'/'+(holder.expected.caller===next.middle));
  return 4;
}});
holder.expected=next.leaf;
function fresh(){ var r=[]; for(var n=0;n<10;n++) r.push(next.invoke(holder)); return r.join(','); }
console.log(fresh(), log.slice(0,3).join(' '), log.length);
function failing(){
  holder.fail=true;
  try {next.invoke(holder); return 'no throw';} catch(e) {
    return e.message+' '+(e.stack.indexOf('leaf')>=0)+' '+(e.stack.indexOf('middle')>=0);
  } finally { holder.fail=false; }
}
console.log(failing());
console.log('callers', next.leaf.caller, next.middle.caller);
console.log('after catch', fresh());
function collected(){
  var gcHolder={fn:holder.fn,drop:true,fail:false}; holder.fn=null; next.leaf=null;
  Object.defineProperty(gcHolder,'value',{get:function inspectLive(){
    console.log('live', inspectLive.caller!==null, inspectLive.caller && inspectLive.caller.caller===next.middle);
    return 4;
  }});
  return next.invoke(gcHolder);
}
console.log('gc result', collected());
"""
    check(js, golden, "nested_getters_gc", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_fresh_inline_receivers_and_missing_arguments(js, golden, switches, tier):
    """CATCHES: a fresh method inline that binds `this` to a primitive instead of its boxed wrapper (Number/String/Boolean receivers), binds the wrong receiver for arrays/functions, or treats a missing second argument as anything but undefined."""
    code = r"""
function make(seed) {
  function leaf(x,missing) {return seed+this.bias+x+(missing===undefined?0:100);}
  function invoke(holder,x) {return holder.fn(x);}
  function invoke2(holder,x) {return holder.fn(x,1);}
  return {leaf:leaf,invoke:invoke,invoke2:invoke2};
}
var first=make(3), holder={fn:first.leaf,bias:10};
function warm(){ var s=0; for(var n=0;n<500;n++) s+=first.invoke(holder,4)+first.invoke2(holder,1); return s; }
console.log('warm', warm());
function probe(){
  var out=[];
  var next=make(20), h2={fn:next.leaf,bias:30};
  out.push('fresh receiver '+next.invoke(h2,4)+' '+next.invoke2(h2,4));
  Number.prototype.fn=next.leaf; Number.prototype.bias=40;
  out.push('boxed receiver '+next.invoke(7,4));
  String.prototype.fn=next.leaf; String.prototype.bias='s';
  out.push('string receiver '+next.invoke('q',4));
  Boolean.prototype.fn=next.leaf; Boolean.prototype.bias=1;
  out.push('boolean receiver '+next.invoke(true,4));
  var arr=[1]; arr.fn=next.leaf; arr.bias=2;
  out.push('array receiver '+next.invoke(arr,4));
  var fn=function(){}; fn.fn=next.leaf; fn.bias=3;
  out.push('function receiver '+next.invoke(fn,4));
  out.push('inherited bias '+next.invoke(Object.create(h2),5));
  return out.join('\n');
}
console.log(probe());
"""
    check(js, golden, "receivers_missing_args", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_activation_bearing_fresh_closures(js, golden, switches, tier):
    """CATCHES: the needs-environment fresh-closure retry running a new closure instance with the cached instance's activation (wrong `seed`, `doubled` or `arguments`), or mis-dispatching arrows, plain functions and natives that share its call site."""
    code = r"""
function inspect(){eval('');return inspect.caller;}
var live=null, wrong=0;
function factory(seed){
  return function(x){
    var doubled=x*2;
    var read=function(){ return seed+doubled; };
    if(live!==null && inspect()!==live) wrong++;
    return read()+arguments.length;
  };
}
function argsFactory(seed){ return function(){ var s=seed; for(var i=0;i<arguments.length;i++) s+=arguments[i]; return s; }; }
function invoke(f,x){return f(x);}
function invoke3(f){return f(1,2,3);}
function warm(){ var f=factory(1), s=0; for(var i=0;i<300;i++) s+=invoke(f,i); var g=argsFactory(0); for(var i=0;i<300;i++) s+=invoke3(g); return s; }
console.log('warm', warm());
function fresh(){
  var out=[];
  for(var i=0;i<30;i++){ live=factory(i*10); out.push(invoke(live,i)); }
  live=null;
  var sums=[];
  for(var i=0;i<30;i++) sums.push(invoke3(argsFactory(i)));
  return out.join(',')+' | '+sums.join(',');
}
console.log(fresh(), 'wrong', wrong);
function mixed(){
  var out=[];
  out.push(invoke((x)=>x+1000, 5));
  out.push(invoke(factory(7), 5));
  out.push(invoke(function(x){return -x;}, 5));
  out.push(invoke(x=>x*x, 9));
  out.push(invoke3((a,b,c)=>a+b+c));
  out.push(invoke3(argsFactory(100)));
  out.push(invoke(String, 42) + '!');
  return out.join(',');
}
console.log('mixed', mixed());
"""
    check(js, golden, "activation_closures", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_fresh_closures_after_a_second_realm_exists(js, golden, switches, tier):
    """CATCHES: a multi-realm fresh-closure retry that skips the same-realm root check (deeply nested environments or closures created by another realm's code), so calls run with the wrong global or wrong captured values once $262.createRealm() was used."""
    code = r"""
var other=$262.createRealm();
var foreignAdd=other.evalScript('(function(seed){ return function(x){ return seed + x; }; })');
function factory(seed){ return function(x){ return seed + x * 2; }; }
function deep(seed){
  return (function(){ return (function(){ return (function(){ return (function(){
    return (function(){ return (function(){ return (function(){ return (function(){
      return (function(){ return function(x){ return seed - x; }; })();
    })(); })(); })(); })();
  })(); })(); })(); })();
}
function invoke(f,x){return f(x);}
function warm(){ var f=factory(1), d=deep(1), s=0; for(var i=0;i<300;i++){ s+=invoke(f,i); s+=invoke(d,i); } return s; }
console.log('warm', warm());
function fresh(){
  var a=[], b=[], c=[];
  for(var i=0;i<25;i++){ a.push(invoke(factory(i),3)); b.push(invoke(deep(i),3)); c.push(invoke(foreignAdd(i),3)); }
  return a.join(',')+'\n'+b.join(',')+'\n'+c.join(',');
}
console.log(fresh());
function crossRealmCallee(){
  var f=other.evalScript('(function(x){ return [x, typeof Array, this === globalThis]; })');
  var r=invoke(f, 4);
  return r.length+' '+r[0]+' '+r[1]+' '+r[2]+' '+(r instanceof Array)+' '+Array.isArray(r);
}
console.log('foreign', crossRealmCallee());
"""
    check(js, golden, "second_realm", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_numeric_loops_inside_fresh_shared_inlines(js, golden, switches, tier):
    """CATCHES: a numeric loop region inside a fresh shared-closure inline that loses its continuation after 2048 iterations, mishandles int32 overflow, or on an out-of-bounds side exit to a prototype getter reports the wrong live inline owner or fails to unwind after a throw."""
    code = r"""
function make(seed) {
  function linear(a,n) { var sum=seed; for(var i=0;i<n;i++) { sum+=a[i]; } return sum; }
  function branchy(a,n) { var sum=seed; for(var i=0;i<n;i++) { if(i<2) sum+=a[i]; else sum-=a[i]; } return sum; }
  function invokeLinear(a,n) { return linear(a,n); }
  function invokeBranchy(a,n) { return branchy(a,n); }
  return {linear:linear,branchy:branchy,invokeLinear:invokeLinear,invokeBranchy:invokeBranchy};
}
var first=make(20);
function warm(){ var s=0; for(var j=0;j<500;j++){ s+=first.invokeLinear([1,2,3,4],4); s+=first.invokeBranchy([1,2,3,4],4); } return s; }
console.log('warm', warm());
var next=make(20);
function fresh(){
  return [next.invokeLinear([1,2,3,4],4), next.invokeBranchy([1,2,3,4],4),
    next.invokeLinear(Array(2048).fill(1),2048), next.invokeBranchy(Array(2048).fill(1),2048),
    make(-5).invokeLinear([0.5,1.5,-2,8],4), make(1e9).invokeBranchy([2147483647,2147483647,1,1],4)].join(' ');
}
console.log(fresh());
var reads=0, fail=false, owners=[];
function sideExit(which){
  var a=[1,2];
  var proto=Object.create(Array.prototype); proto[3]=4;
  Object.defineProperty(proto,'2',{get:function inspect(){
    reads++; $262.gc();
    owners.push(inspect.caller===next[which]);
    if(fail) throw new Error('expected '+which);
    return 3;
  }});
  Object.setPrototypeOf(a,proto);
  var call=function(arr){ return which==='linear' ? next.invokeLinear(arr,4) : next.invokeBranchy(arr,4); };
  var out=[which, call(a), reads];
  fail=true;
  try { call(a); out.push('no throw'); }
  catch(e){ out.push(e.message, String(next[which].caller)); }
  fail=false;
  out.push(call([1,2,3,4]));
  return out.join(' ');
}
console.log(sideExit('linear'));
console.log(sideExit('branchy'));
console.log('owners', owners.join(','));
console.log(next.invokeLinear(['a','b',3,4],4), next.invokeBranchy([1,'x',3,4],4), next.invokeLinear([1,2,,4],4), next.invokeLinear([1,2],4));
"""
    check(js, golden, "numeric_loops_inline", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_numeric_field_expressions_inside_fresh_shared_inlines(js, golden, switches, tier):
    """CATCHES: a numeric field-expression region inside a fresh shared inline that keeps using the warmed field values after a getter is installed, reports the wrong `caller` to that getter, or mishandles string, NaN, -0, inherited, proxied or null inputs."""
    code = r"""
function make(seed) {
  function leaf(o) { var amount=o.src.value*o.scale.value; return seed+amount; }
  function invoke(o) { return leaf(o); }
  return {leaf:leaf,invoke:invoke};
}
var first=make(20), input={src:{value:2},scale:{value:3}};
function warm(){ var s=0; for(var i=0;i<500;i++) s+=first.invoke(input); return s; }
console.log('warm', warm());
var next=make(30);
function fresh(){ var out=[]; for(var i=0;i<5;i++) out.push(make(i).invoke(input)); out.push(next.invoke(input)); return out.join(','); }
console.log(fresh());
var reads=0, fail=false, owner=[];
Object.defineProperty(input.src,'value',{configurable:true,get:function inspect(){
  reads++;
  owner.push(inspect.caller===next.leaf);
  if(fail) throw new Error('expected getter');
  return 4;
}});
function getterFallback(){
  var out=[next.invoke(input), reads];
  fail=true;
  try { next.invoke(input); out.push('no throw'); } catch(e){ out.push(e.message, String(next.leaf.caller)); }
  fail=false;
  out.push(next.invoke(input), reads, owner.join('/'));
  return out.join(' ');
}
console.log(getterFallback());
function shapes(){
  var out=[];
  out.push(next.invoke({src:{value:'7'},scale:{value:2}}));
  out.push(next.invoke({scale:{value:2},src:{value:1.5}}));
  out.push(next.invoke({src:{value:NaN},scale:{value:0}}));
  out.push(Object.is(make(-0).invoke({src:{value:-0},scale:{value:1}}), -0));
  var p=Object.create({value:9}); out.push(next.invoke({src:p,scale:{value:2}}));
  out.push(next.invoke({src:new Proxy({value:3},{get:function(t,k){return k==='value'?11:undefined;}}),scale:{value:1}}));
  try { next.invoke({src:null,scale:{value:1}}); out.push('no throw'); } catch(e){ out.push(e.constructor.name); }
  return out.join(' ');
}
console.log(shapes());
"""
    check(js, golden, "field_expr_inline", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_polymorphic_call_site_with_many_refreshed_closures(js, golden, switches, tier):
    """CATCHES: a refreshed call-cache entry that survives eviction from a site seeing five closure kinds, or whose replaceable pin is released while another entry still names it, so a later call dispatches to the wrong closure body or a collected closure."""
    code = r"""
function makeAdd(seed) { return function (x) { return seed + x; }; }
function makeMul(seed) { return function (x) { return seed * x; }; }
function makeSub(seed) { return function (x) { return seed - x; }; }
function makeStr(seed) { return function (x) { return 's' + seed + ':' + x; }; }
function makeNeg(seed) { return function (x) { return -seed - x; }; }
var makers = [makeAdd, makeMul, makeSub, makeStr, makeNeg];
function invoke(f, x) { return f(x); }
function warm() { var s = 0; for (var i = 0; i < 300; i++) { var r = invoke(makers[i % 5](i), 2); s += typeof r === 'number' ? r : r.length; } return s; }
console.log('warm', warm());
function rotate() {
  var out = [];
  for (var i = 0; i < 15; i++) { var f = makers[i % 5](i); out.push(invoke(f, 3), invoke(f, 4)); }
  return out.join(',');
}
console.log(rotate());
function refreshMany() {
  var total = 0, strs = 0;
  for (var i = 0; i < 1000; i++) {
    var f = makeAdd(i), g = makeStr(i % 10);
    total += invoke(f, 1) + invoke(f, 2) + invoke(f, 3);
    strs += invoke(g, i).length;
    if (i % 250 === 0) $262.gc();
  }
  return total + ' ' + strs;
}
console.log('refreshes', refreshMany());
function interleave() {
  var a = makeAdd(10), m = makeMul(10), out = [];
  for (var i = 0; i < 6; i++) {
    out.push(invoke(a, i), invoke(Math.max, i), invoke(m, i), invoke(makeAdd(100 + i), i), invoke(a, -i));
  }
  return out.join(' ');
}
console.log(interleave());
var kept = [];
function retain() { for (var i = 0; i < 40; i++) kept.push(makeSub(i)); $262.gc(); var s = 0; for (var j = 0; j < kept.length; j++) s += invoke(kept[j], 1) * (j + 1); return s; }
console.log('retained', retain());
"""
    check(js, golden, "polymorphic_refresh", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_strict_and_sloppy_fresh_closures_bind_this(js, golden, switches, tier):
    """CATCHES: a retried or refreshed fresh-closure call that reuses a cache entry across strictness, so a strict closure sees the global object as `this` or a sloppy one sees undefined (also as a method of a fresh object), or that breaks strict-mode tail calls between fresh sibling closures and their exception unwinding."""
    code = r"""
function strictFactory(seed){ 'use strict'; return function(x){ return [seed+x, this===undefined ? 'undef' : typeof this]; }; }
function sloppyFactory(seed){ return function(x){ return [seed+x, this===globalThis ? 'global' : typeof this]; }; }
function invoke(f,x){ return f(x); }
function invokeOn(o,x){ return o.m(x); }
function strictInvoke(f,x){ 'use strict'; return f(x); }
function warm(){ var s=strictFactory(1), l=sloppyFactory(1), t=0; for(var i=0;i<300;i++){ t+=invoke(s,i)[0]+invoke(l,i)[0]+strictInvoke(s,i)[0]+strictInvoke(l,i)[0]+invokeOn({m:s},i)[0]; } return t; }
console.log('warm', warm());
function fresh(){
  var out=[];
  for(var i=0;i<6;i++){
    out.push(invoke(strictFactory(i),1).join(':'), invoke(sloppyFactory(i),1).join(':'),
      strictInvoke(strictFactory(i),2).join(':'), strictInvoke(sloppyFactory(i),2).join(':'),
      invokeOn({m:strictFactory(i)},3).join(':'), invokeOn({m:sloppyFactory(i)},3).join(':'));
  }
  return out.join(' ');
}
console.log(fresh());
function tailFactory(seed) { 'use strict'; return function step(n, acc) { if (n === 0) return acc + seed; return step(n - 1, acc + 1); }; }
function bounce(seed) {
  'use strict';
  function even(n) { return n === 0 ? 'even' + seed : odd(n - 1); }
  function odd(n) { return n === 0 ? 'odd' + seed : even(n - 1); }
  return even;
}
function thrower(seed) { 'use strict'; return function t(n) { if (n === 0) throw new Error('bottom' + seed); return t(n - 1); }; }
function invokeTail(f, n) { 'use strict'; return f(n, 0); }
function warmTail() { var s = 0; for (var i = 0; i < 300; i++) s += invokeTail(tailFactory(i), 20) + bounce(i)(9).length; return s; }
console.log('tail warm', warmTail());
function tails() {
  var out = [];
  for (var i = 0; i < 5; i++) {
    out.push(invokeTail(tailFactory(i), 150), bounce(i)(101 + i));
    try { thrower(i)(60); } catch (e) { out.push(e.message); }
  }
  return out.join(' ');
}
console.log(tails());
"""
    check(js, golden, "strictness_this", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_sibling_closures_mutating_shared_captures(js, golden, switches, tier):
    """CATCHES: an inlined sibling closure that writes a captured binding into a stale environment or a register copy, so `inc`/`get` siblings from fresh counter() activations or per-iteration `let` closures disagree about the shared counter value."""
    code = r"""
function counter(start){
  var n=start;
  function inc(by){ n+=by; return n; }
  function get(){ return n; }
  function bump(){ return inc(1)+inc(2)+get(); }
  return {inc:inc,get:get,bump:bump};
}
function drive(c,k){ var s=0; for(var i=0;i<k;i++) s+=c.bump(); return s; }
function warm(){ var c=counter(0); return drive(c,300)+' '+c.get(); }
console.log('warm', warm());
function fresh(){
  var out=[];
  for(var i=0;i<20;i++){ var c=counter(i*100); var s=drive(c,5); c.inc(-1); out.push(s+'/'+c.get()); }
  return out.join(',');
}
console.log(fresh());
function perIteration(){
  var fns=[];
  for(let i=0;i<10;i++){ let j=i*i; fns.push(function(){ j++; return i+j; }); }
  var r=[];
  for(var k=0;k<3;k++) for(var m=0;m<fns.length;m++) r.push(fns[m]());
  return r.join(',');
}
console.log(perIteration());
"""
    check(js, golden, "shared_captures", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_fresh_closures_as_constructors_and_kinds(js, golden, switches, tier):
    """CATCHES: fresh-closure caching that also captures `new` calls (wrong prototype, lost `new.target`, ignored object return override) or that wrongly treats generator, async, arrow and method closures as plain inlinable functions."""
    code = r"""
function factory(seed){
  return function Point(x){
    if(!new.target) return 'called:'+(seed+x);
    this.v=seed+x;
    if(x<0) return {override:x};
  };
}
function build(C,x){ return new C(x); }
function call(C,x){ return C(x); }
function warm(){ var P=factory(1), s=0; for(var i=0;i<300;i++){ s+=build(P,i).v; } return s+' '+call(P,2); }
console.log('warm', warm());
function fresh(){
  var out=[];
  for(var i=0;i<12;i++){ var P=factory(i); var o=build(P,i); out.push(o.v+':'+(o instanceof P)+':'+(Object.getPrototypeOf(o)===P.prototype)); }
  var neg=build(factory(5),-3);
  out.push(JSON.stringify(neg), call(factory(9),1));
  return out.join(' ');
}
console.log(fresh());
function kinds(seed){
  return {
    gen: function*(x){ yield seed+x; yield seed-x; },
    asy: async function(x){ return seed*x; },
    arrow: (x)=>seed+x+0.5,
    method(x){ return this.k+seed+x; },
    k: 1000,
    get g(){ return seed*2; }
  };
}
function spread(f,x){ return [...f(x)]; }
function invoke(f,x){ return f(x); }
function viaMethod(o,x){ return o.method(x); }
function warmKinds(){ var o=kinds(1), s=0; for(var i=0;i<300;i++){ s+=spread(o.gen,i)[0]+invoke(o.arrow,i)+viaMethod(o,i)+o.g; } return s; }
console.log('kinds warm', warmKinds());
var results=[];
function freshKinds(){
  var out=[];
  for(var i=0;i<6;i++){ var o=kinds(i); out.push(spread(o.gen,2).join('/'), invoke(o.arrow,2), viaMethod(o,2), o.g); invoke(o.asy,3).then(function(v){results.push(v);}); }
  return out.join(' ');
}
console.log(freshKinds());
Promise.resolve().then(function(){}).then(function(){ console.log('async', results.join(',')); });
"""
    check(js, golden, "constructors_kinds", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_fresh_closure_recursion_arguments_and_stack_traces(js, golden, switches, tier):
    """CATCHES: fresh closures whose named self-reference resolves to an older instance (wrong recursive base), whose surplus/missing/default/rest arguments are bound wrongly when cached or inlined, or whose error stack omits the inlined leaf/invoke frames."""
    code = r"""
function factory(base){
  return function fact(n){ return n<=1 ? base : n*fact(n-1); };
}
function argsy(seed){ return function(a,b){ return seed+':'+arguments.length+':'+(b===undefined?'u':b)+':'+Array.prototype.slice.call(arguments,2).join('+'); }; }
function defaults(seed){ return function(a, b=seed){ return a+b; }; }
function rest(seed){ return function(a, ...more){ return seed+a+more.length; }; }
function invoke(f,x){ return f(x); }
function invoke4(f){ return f(1,2,3,4); }
function invoke1(f){ return f(1); }
function warm(){ var s=0; for(var i=0;i<300;i++){ s+=invoke(factory(1),5); s+=invoke1(defaults(2)); s+=invoke1(rest(3)); invoke4(argsy(0)); } return s; }
console.log('warm', warm());
function fresh(){
  var out=[];
  for(var i=1;i<8;i++){ out.push(invoke(factory(i),i)); }
  out.push(invoke4(argsy('x')), invoke1(argsy('y')), invoke1(defaults(10)), invoke4(defaults(10)), invoke4(rest(5)), invoke1(rest(6)));
  return out.join(' ');
}
console.log(fresh());
function make(seed){
  function leaf(x){ if(x<0) throw new Error('neg '+seed); return seed+x; }
  function invoke(x){ return leaf(x); }
  return invoke;
}
function warmStack(){ var f=make(1), s=0; for(var i=0;i<500;i++) s+=f(i); return s; }
console.log('warm stack', warmStack());
function stacks(){
  var lines=[];
  for(var i=0;i<3;i++){
    var f=make(i);
    try{ f(-1); }catch(e){ lines.push(e.message+' => '+e.stack.split('\n').slice(0,4).map(function(s){return s.trim();}).join(' | ')); }
  }
  return lines.join('\n');
}
console.log(stacks());
"""
    check(js, golden, "recursion_args_stacks", code, switches, tier)


@pytest.mark.parametrize("switches,tier", CLOSURE_MODES)
def test_inline_admission_of_global_functions_and_hoisted_vars(js, golden, switches, tier):
    """CATCHES: an inliner that splices a global (new Function) callee whose free name `g` is shadowed by the caller's local, splices a this-using callee at a plain call site, mis-resets a re-declared `for (var i ...)` or parameter `var`, or mishandles nine-argument and GC-churned call sites."""
    code = r"""
globalThis.g = 10;
var globalReader = new Function('x', 'return x + g;');
var globalThisUser = new Function('x', 'return this === globalThis ? x * 1000 : -x;');
function shadow(x) { var g = 5; return globalReader(x) + g; }
function noShadow(x) { return globalReader(x) * 2; }
function thisAtPlainSite(x) { return globalThisUser(x) + 1; }
function twoLoops(a) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i]; for (var i = 0; i < 2; i++) s *= 2; return s + i; }
function loopsCaller(x) { return twoLoops([x, 1, 2]) - 1; }
function redeclares(a, b) { var a; var c = a + b; return c; }
function redeclCaller(x) { return redeclares(x, 2) * 2; }
function many(a, b, c, d, e, f, g2, h, k) { return a + b + c + d + e + f + g2 + h + k; }
function manyCaller(x) { return many(x, 1, 2, 3, 4, 5, 6, 7, 8); }
function churn(f, x) { return f(x); }
function driveDead() { var s = 0; for (var i = 0; i < 160; i++) { if (i % 40 === 39) $262.gc(); s += churn(function (y) { return y + i; }, 1); } return s; }
function drive() { var s = 0; for (var i = 0; i < 300; i++) s += shadow(i) + noShadow(i) + thisAtPlainSite(i) + loopsCaller(i) + redeclCaller(i) + manyCaller(i); return s; }
console.log('drive', drive(), 'dead', driveDead());
console.log(shadow(1), noShadow(2), thisAtPlainSite(3), loopsCaller(4), redeclCaller(5), manyCaller(6));
globalThis.g = -1;
console.log('global changed', shadow(1), noShadow(2));
globalReader = function (x) { return 'r' + x; }; globalThisUser = function () { return this === undefined; };
console.log('replaced', shadow(1), noShadow(2), thisAtPlainSite(3));
"""
    check(js, golden, "inline_admission", code, switches, tier)


# ------------------------------------------------------------------------------- kill switches
@pytest.mark.parametrize("switches,tier", kill_modes(
    "LUMEN_JIT_NO_NUMERIC_CFG", "LUMEN_JIT_NO_MIXED_LOOP", "LUMEN_JIT_NO_LAST_USES",
    "LUMEN_NO_ARRAY_DESTRUCTURE"))
def test_loop_shapes_through_region_builders_under_kill_switches(js, golden, switches, tier):
    """CATCHES: loop-region analysis (or its disabled controls) that mishandles a loop body over 1024 operations, object/array destructuring per iteration, labeled continue/break, fallthrough switch cases, for-in, dead code after a return inside a loop, or a loop spliced into a pending `s += f()` expression."""
    code = r"""
var body = ''; for (var k = 0; k < 260; k++) body += 's = s + i * ' + k + ';\n';
var huge = new Function('n', 'var s = 0; for (var i = 0; i < n; i++) {\n' + body + '}\nreturn s;');
function linear(a, n) { var t = 0; for (var i = 0; i < n; i++) t += a[i]; return t; }
function pending(a, n) { var s = 1; s += linear(a, n); return s * 2 + linear(a, 2); }
function destructLoop(pairs) { var s = 0; for (var i = 0; i < pairs.length; i++) { var [a, b] = pairs[i]; s += a * b; } return s; }
function objDestructLoop(list) { var s = 0; for (var i = 0; i < list.length; i++) { var { x, y } = list[i]; if (x > y) s += x - y; else s += y; } return s; }
function whileContinue(n) { var i = 0, s = 0; while (i < n) { i++; if (i % 3 === 0) continue; s += i; } return s; }
function doWhile(n) { var i = 0, s = 0; do { s += i * 2; i++; } while (i < n); return s; }
function deadAfterReturn(n) { var s = 0; for (var i = 0; i < n; i++) { if (i > 5) { return s; s += 100; } s += i; } return -s; }
function forUpdate(n) { var s = 0; for (var i = 0, j = n; i < j; i++, j--) { if (i === 2) continue; s += j - i; } return s; }
function labeled(n) { var s = 0; outer: for (var i = 0; i < n; i++) { for (var j = 0; j < n; j++) { if (j > i) continue outer; if (i + j > 12) break outer; s += i * j; } } return s; }
function infinite(n) { var s = 0, i = 0; for (;;) { if (i >= n) break; s += i++; } return s; }
function switchLoop(n) { var s = 0; for (var i = 0; i < n; i++) { switch (i % 4) { case 0: s += 1; break; case 1: s -= 2; case 2: s *= 2; break; default: s = -s; } } return s; }
function forInLoop(o) { var s = ''; for (var k in o) { if (k === 'skip') continue; s += k + o[k]; } return s; }
function ternaryLoop(n) { var s = 0; for (var i = 0; i < n; i++) s = s + (i > 3 ? i : -i) * (i & 1 ? 2 : 3); return s; }
function logicalLoop(a, n) { var s = 0; for (var i = 0; i < n; i++) s += (a[i] || 7) + (a[i] && 1); return s; }
var pairs = []; for (var i = 0; i < 20; i++) pairs.push([i, i + 1]);
var pts = []; for (var i = 0; i < 12; i++) pts.push({ x: i % 5, y: 3 });
function warm() {
  var r = 0;
  for (var k = 0; k < 150; k++) {
    r += pending([1, 2, 3, 4], 4) + destructLoop(pairs) + objDestructLoop(pts) + whileContinue(20) + doWhile(10) + deadAfterReturn(10);
    r += forUpdate(10) + labeled(8) + infinite(10) + switchLoop(9) + ternaryLoop(10) + logicalLoop([0, 1, 2, 0], 4);
    forInLoop({ a: 1, skip: 2, b: 3 });
  }
  return r;
}
console.log('warm', warm(), huge(3), huge(10));
console.log(pending([1, 2, 3, 4], 4), destructLoop(pairs), whileContinue(30), doWhile(1), deadAfterReturn(3), deadAfterReturn(9), forUpdate(11), labeled(9), infinite(15), switchLoop(13), forInLoop({ x: 1, skip: 0, y: 'z' }), ternaryLoop(11), logicalLoop([0, '', null, 5, -0], 5));
console.log(destructLoop([[1, 2], 'ab', [3], new Set([4, 5])]), pending([1, 'x', 3], 3), objDestructLoop([{ x: 'a', y: 1 }, { y: 2 }, Object.create({ x: 9, y: 1 })]));
try { objDestructLoop([null]); console.log('no throw'); } catch (e) { console.log(e.constructor.name); }
"""
    check(js, golden, "loop_shapes", code, switches, tier)
@pytest.mark.parametrize("switches,tier", kill_modes(
    "LUMEN_JIT_NO_NUMERIC_CFG", "LUMEN_JIT_NO_NUMERIC_ARRAYS", "LUMEN_JIT_NO_CFG_FALLTHROUGH",
    "LUMEN_JIT_NO_CFG_REGALLOC", "LUMEN_JIT_NO_CFG_INPUTS", "LUMEN_JIT_NO_LAST_USES"))
def test_numeric_cfg_loops_under_their_kill_switches(js, golden, switches, tier):
    """CATCHES: a numeric CFG control (fixed-register emitter, old edge layout, disabled array reads or invariant inputs) that mis-evaluates negation, chained assignment, discarded expressions, pre/post increments, continue/break or do-while loops, or their guard fallbacks on holes, strings, getters, typed arrays and proxies."""
    code = r"""
var cfg = { lo: 3, hi: 11, step: 0.5 };
var LIMIT = 7;
function branched(n) {
  var s = 0, t = 1;
  for (var i = 0; i < n; i++) {
    if (i % 3 === 0) s += i * cfg.step; else if (i > LIMIT) s -= t; else s = -s + i;
    t = t * 0.5 - i;
  }
  return s + t;
}
function nested(n) {
  var acc = 0;
  for (var i = 0; i < n; i++) {
    for (var j = 0; j < i; j++) {
      if (j === 2) continue;
      if (i * j > 40) break;
      acc += i - j;
    }
  }
  return acc;
}
function bottomTested(n) {
  var x = n, steps = 0;
  do { if (x % 2) x = 3 * x + 1; else x = x / 2; steps++; } while (x !== 1 && steps < 500);
  return steps;
}
function neg(n) { var d = 1, s = 0; for (var i = 0; i < n; i++) { if (i > 5) d = -d; else s += d; } return s + d; }
function dup(n) { var a = 0, b = 0, s = 0; for (var i = 0; i < n; i++) { if (i < 4) a = b = i; else s += a - b; } return s + a + b; }
function pop(n) { var s = 0; for (var i = 0; i < n; i++) { if (s < 5) { s + 1; s += 2; } else s -= 1; } return s; }
function postDec(n) { var a = 0, c = 0; for (var i = 0; i < n; i++) { if (i > 3) c += a--; else c -= --a; } return a + c; }
function postInc(n) { var a = 0, c = 0; for (var i = 0; i < n; i++) { if (i > 3) c += a++; else c -= ++a; } return a + c; }
function arrays(xs, ys, n) {
  var s = 0;
  for (var i = 0; i < n; i++) {
    if (xs[i] > ys[i]) s += xs[i] - ys[i]; else s -= ys[i] * 0.25;
  }
  return s;
}
function nestedArrays(m, n) {
  var s = 0;
  for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) { if (m[i] < m[j]) s += m[j] - m[i]; else s += 1; }
  return s;
}
function fields(o, n) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (i < o.lo) s += o.lo; else if (i > o.hi) s -= o.step; else s += i * o.step; }
  return s;
}
function enclosing(n) {
  var k = 2.5, m = -1;
  function inner() { var s = 0; for (var i = 0; i < n; i++) { if (i > 4) s += k; else s += m; } return s; }
  return inner();
}
var xs = [], ys = [];
for (var i = 0; i < 64; i++) { xs.push((i * 7) % 13); ys.push((i * 5) % 11); }
function warm() {
  var r = 0;
  for (var k = 0; k < 60; k++) {
    r += branched(40) + nested(12) + bottomTested(27) + arrays(xs, ys, 64) + nestedArrays(xs, 16) + fields(cfg, 20) + enclosing(30);
    r += neg(20) + dup(10) + pop(9) + postDec(10) + postInc(10);
  }
  return r;
}
console.log('warm', warm());
console.log('branched', branched(50), branched(0), branched(7));
console.log('nested', nested(20), 'collatz', bottomTested(27), bottomTested(97), bottomTested(1));
console.log('updates', neg(31), dup(9), pop(7), postDec(9), postInc(12));
console.log('arrays', arrays(xs, ys, 64), nestedArrays(xs, 20));
console.log('fields', fields(cfg, 30), fields({ lo: 1, hi: 2, step: 4 }, 6), 'enclosing', enclosing(31));
var holes = xs.slice(); delete holes[5]; holes[70] = 1;
console.log('holes', arrays(holes, ys, 64), arrays(xs, ys, 70));
var mixed = xs.slice(); mixed[3] = '9'; mixed[4] = 2.5; mixed[6] = -0;
console.log('mixed', arrays(mixed, ys, 64), nestedArrays(mixed, 10));
var getterArr = xs.slice(); var reads = 0;
Object.defineProperty(getterArr, 10, { get: function () { reads++; return 100; } });
console.log('getter', arrays(getterArr, ys, 64), reads);
console.log('typed', arrays(new Float64Array(xs), new Int8Array(ys), 64), arrays(new Uint8Array([1, 2, 300]), [0, 0, 0], 3));
var px = new Proxy(xs, { get: function (t, k) { return k === '0' ? 1000 : t[k]; } });
console.log('proxy', arrays(px, ys, 64));
console.log('weird fields', fields({ lo: '2', hi: NaN, step: Infinity }, 5), fields({ lo: 1, hi: 3, step: -0 }, 5));
cfg.step = 2; LIMIT = 1;
console.log('changed', branched(20), fields(cfg, 30));
cfg = { step: 'x' };
console.log('replaced', branched(8));
"""
    check(js, golden, "numeric_cfg_switches", code, switches, tier)


@pytest.mark.parametrize("switches,tier", kill_modes(
    "LUMEN_JIT_NO_MIXED_LOOP", "LUMEN_JIT_NO_MIXED_LOOP_COMPARE", "LUMEN_JIT_NO_MIXED_READ_PROOFS",
    "LUMEN_JIT_NO_COMPACT_PROPERTY_HINT", "LUMEN_JIT_NO_INLINE_PACKED_READS",
    "LUMEN_NO_COMPACT_BUILTIN_ARRAYS"))
def test_object_loops_under_their_kill_switches(js, golden, switches, tier):
    """CATCHES: a mixed object/number loop control (separate compare/branch emission, no read proofs, old property-hint sequence, no packed reads or compact arrays) that mis-orders NaN/-0/Infinity comparisons, misses getters, replaced methods or frozen objects, or exits wrongly after a 1024-backedge budget."""
    code = r"""
function Node(v, next) { this.v = v; this.next = next; }
Node.prototype.weight = function () { return this.v * 2; };
function makeList(n) { var h = null; for (var i = n; i > 0; i--) h = new Node(i, h); return h; }
function sumList(h) { var s = 0, p = h; while (p !== null) { if (p.v > 3) s += p.v; else s -= 1; p = p.next; } return s; }
function weighList(h) { var s = 0; for (var p = h; p; p = p.next) s += p.weight(); return s; }
function objArray(arr) { var best = null, total = 0; for (var i = 0; i < arr.length; i++) { var o = arr[i]; if (best === null || o.score > best.score) best = o; total += o.score; } return best.id + ':' + total; }
function compareAll(arr, pivot) { var lt = 0, le = 0, gt = 0, ge = 0, eq = 0, ne = 0, seq = 0, sne = 0;
  for (var i = 0; i < arr.length; i++) { var x = arr[i].score;
    if (x < pivot) lt++; if (x <= pivot) le++; if (x > pivot) gt++; if (x >= pivot) ge++;
    if (x == pivot) eq++; if (x != pivot) ne++; if (x === pivot) seq++; if (x !== pivot) sne++; }
  return [lt, le, gt, ge, eq, ne, seq, sne].join(''); }
function ternary(arr) { var s = 0; for (var i = 0; i < arr.length; i++) { var o = arr[i]; s += o.score > 2 ? o.score : -o.score; } return s; }
function Acc() { this.total = 0; this.count = 0; }
Acc.prototype.run = function (arr) { for (var i = 0; i < arr.length; i++) { if (arr[i].score > 0) { this.total += arr[i].score; this.count++; } } return this.total + '/' + this.count; };
function nestedObj(rows) { var s = 0; for (var i = 0; i < rows.length; i++) { var r = rows[i]; for (var j = 0; j < r.cells.length; j++) { if (r.cells[j].v < 0) continue; if (r.cells[j].v > 50) break; s += r.cells[j].v; } } return s; }
function mk(n) { var a = []; for (var i = 0; i < n; i++) a.push({ id: 'o' + i, score: (i * 37) % 11 - 3 }); return a; }
var arr = mk(40), list = makeList(30);
var rows = []; for (var i = 0; i < 6; i++) { var row = []; for (var j = 0; j < 8; j++) row.push({ v: (i * 13 + j * 7) % 60 - 5 }); rows.push({ cells: row }); }
function warm() { var r = 0; for (var k = 0; k < 60; k++) { r += sumList(list) + weighList(list) + ternary(arr) + nestedObj(rows); objArray(arr); compareAll(arr, 2); new Acc().run(arr); } return r; }
console.log('warm', warm());
console.log(sumList(list), weighList(list), objArray(arr), compareAll(arr, 2), ternary(arr), new Acc().run(arr), nestedObj(rows));
var specials = mk(8); specials[1].score = NaN; specials[2].score = -0; specials[3].score = Infinity; specials[4].score = -Infinity; specials[5].score = '4';
console.log('specials', compareAll(specials, 0), compareAll(specials, NaN), compareAll(specials, -0), ternary(specials), objArray(specials));
var long = mk(1500);
console.log('long', objArray(long), ternary(long), new Acc().run(long));
var holey = mk(10); delete holey[4];
try { console.log(objArray(holey)); } catch (e) { console.log('holey', e.constructor.name); }
var inherited = mk(10); Object.setPrototypeOf(inherited, Object.create(Array.prototype));
console.log('inherited', objArray(inherited));
var getterObjs = mk(10); var reads = 0; Object.defineProperty(getterObjs[6], 'score', { get: function () { reads++; return 99; } });
console.log('getter', objArray(getterObjs), reads, ternary(getterObjs), reads);
Node.prototype.weight = function () { return -this.v; };
console.log('replaced method', weighList(list));
var odd = makeList(5); odd.next.next.weight = function () { return 1000; };
console.log('own method', weighList(odd));
Object.defineProperty(list.next, 'v', { get: function () { return 500; } });
console.log('accessor node', sumList(list));
var frozen = mk(5); Object.freeze(frozen[0]);
console.log('frozen', new Acc().run(frozen));
var swapped = mk(12); swapped[3] = { id: 'shape', extra: 1, score: 50 };
console.log('shape', objArray(swapped), ternary(swapped));
class Cell { constructor(v) { this.v = v; this.w = 2; } get() { return this.v * 3; } }
function sumCells(cells, n) { 'use strict'; let s = 0; for (let i = 0; i < n; i++) { s += cells[i].get(); } return s; }
function bumpCells(cells, n) { 'use strict'; for (let i = 0; i < n; i++) { const c = cells[i]; c.v = c.v + 1; } return cells[0].v; }
const cellList = []; for (let i = 0; i < 20; i++) cellList.push(new Cell(i));
function driveCells() { 'use strict'; let t = 0; for (let k = 0; k < 150; k++) { t += sumCells(cellList, 20); bumpCells(cellList, 20); } return t; }
console.log('cells', driveCells(), sumCells(cellList, 20));
const oddCells = cellList.slice(0, 6); oddCells[2] = { v: 1, w: 2, get() { return -100; } }; oddCells[4] = Object.create(oddCells[0]);
console.log('cells odd', sumCells(oddCells, 6), bumpCells(oddCells, 6), oddCells[4].v, oddCells[0].v);
Object.defineProperty(cellList[3], 'v', { get() { return 1000; }, set(x) {} });
console.log('cells accessor', sumCells(cellList, 20), bumpCells(cellList, 20));
Cell.prototype.get = function () { return 1; };
console.log('cells method', sumCells(cellList, 20));
"""
    check(js, golden, "object_loop_switches", code, switches, tier)


@pytest.mark.parametrize("switches,tier", kill_modes(
    "LUMEN_JIT_NO_GUARDED_WRITE_REGION", "LUMEN_JIT_NO_WRITE_SEQUENCE", "LUMEN_JIT_NO_NUMERIC_EXPR",
    "LUMEN_JIT_NO_NUMERIC_EXPR_PREFIX", "LUMEN_JIT_NO_COMPACT_PROPERTY_HINT",
    "LUMEN_JIT_NO_STORE_LOAD_FORWARD", "LUMEN_JIT_NO_CACHE_SEED", "LUMEN_JIT_NO_INLINE_METHOD"))
def test_property_writes_and_expressions_under_their_kill_switches(js, golden, switches, tier):
    """CATCHES: guarded write-region, write-sequence, numeric-expression, property-hint, store/load-forwarding, cache-seed or inline-method controls that skip a setter, write a read-only or strict-mode property, keep a stale global object, or reuse a field value after a getter/shape/method change."""
    code = r"""
var Direction = { FORWARD: 1, BACKWARD: -1, NONE: 0 };
function Point(x, y) { this.x = x; this.y = y; this.mag = 0; }
Point.prototype.len2 = function () { return this.x * this.x + this.y * this.y; };
Point.prototype.getX = function () { return this.x; };
function diamond(p, flag) { if (flag > 0) { p.mag = p.x + 1; } else { p.mag = p.y - 1; } return p.mag; }
function nestedDiamond(p, a, b) { if (a > b) { if (p.x > 0) p.mag = p.x * a; else p.mag = -p.x; } else { p.mag = p.y + b; } return p.mag * 2; }
function sequence(state) { state.indent = state.pos - state.start; state.pos = state.pos + 1; return state.indent; }
function chained(c) { c.a.b.v = c.a.b.v + c.k; c.a.w = c.a.b.v * 2; return c.a.w; }
function direction(c) { if (c.dir === Direction.FORWARD) c.out = c.in + 1; else c.out = c.in - 1; return c.out; }
function expr(o) { var amount = o.src.value * o.scale.value; return amount + o.src.value; }
function nestedReturn(d) { return d.left.value * 100 + d.right.inner.value; }
function nestedWrite(d) { d.sum.value = d.left.value + d.right.inner.value; return d.sum.value; }
function method(p) { return p.len2() + p.getX(); }
function forward(o) { var t = o; var u = t; return u.x + t.y; }
function plan(list) { var s = 0; for (var i = 0; i < list.length; i++) { var c = list[i]; s = s + c.x; } return s; }
var pts = []; for (var i = 0; i < 8; i++) pts.push(new Point(i - 3, 2 * i));
var st = { indent: 0, pos: 5, start: 2 };
var ch = { a: { b: { v: 1 }, w: 0 }, k: 3 };
var dc = { dir: 1, in: 10, out: 0 };
var ex = { src: { value: 2 }, scale: { value: 3 } };
var nd = { left: { value: 2 }, right: { inner: { value: 7 } }, sum: { value: 0 } };
function warm() { var r = 0; for (var k = 0; k < 150; k++) { var p = pts[k & 7]; r += diamond(p, k & 1 ? 1 : -1) + nestedDiamond(p, k & 3, 1) + method(p) + forward(p) + expr(ex) + nestedReturn(nd) + nestedWrite(nd) + plan(pts) + direction(dc); st.pos = 5; sequence(st); ch.a.b.v = 1; chained(ch); } return r; }
console.log('warm', warm());
console.log(diamond(pts[1], 1), diamond(pts[2], -1), nestedDiamond(pts[0], 5, 1), nestedDiamond(pts[6], 0, 9), sequence(st), st.pos, chained(ch), direction(dc), expr(ex), nestedReturn(nd), nestedWrite(nd), method(pts[3]), forward(pts[4]), plan(pts));
var nanP = new Point(NaN, -0); console.log('nan', diamond(nanP, 1), diamond(nanP, -1), Object.is(nanP.mag, -1), nestedDiamond(nanP, NaN, 0));
var strP = new Point('5', 2); console.log('string', diamond(strP, 1), nestedDiamond(strP, 3, 1));
var setterLog = []; var sp = new Point(1, 2); Object.defineProperty(sp, 'mag', { get: function () { return 77; }, set: function (v) { setterLog.push(v); } });
console.log('setter', diamond(sp, 1), diamond(sp, -1), setterLog.join(','));
var ro = new Point(1, 2); Object.defineProperty(ro, 'mag', { value: 5, writable: false });
console.log('readonly', diamond(ro, 1), ro.mag);
function strictDiamond(p) { 'use strict'; p.mag = p.x + 1; return p.mag; }
for (var k = 0; k < 120; k++) strictDiamond(pts[k & 7]);
try { strictDiamond(ro); console.log('no throw'); } catch (e) { console.log('strict', e.constructor.name); }
Direction = { FORWARD: 7, BACKWARD: 8 }; console.log('global replaced', direction(dc), direction({ dir: 7, in: 1, out: 0 }));
var st2 = { start: 1, pos: 4, indent: 0 }; console.log('seq shape', sequence(st2), st2.pos, sequence({ pos: '3', start: 1, indent: 0 }));
var gs = { indent: 0, start: 0, get pos() { return 40; }, set pos(v) { setterLog.push('pos' + v); } }; console.log('seq accessor', sequence(gs), setterLog.join(','));
Object.defineProperty(ex.src, 'value', { get: function () { return 4; } }); console.log('expr getter', expr(ex));
nd.left.value = 'x'; console.log('nested string', nestedReturn(nd), nestedWrite(nd));
nd.right.inner = { value: 1, other: 2 }; nd.left.value = 3; console.log('nested shape', nestedReturn(nd), nestedWrite(nd));
Point.prototype.len2 = function () { return -1; }; console.log('method replaced', method(pts[3]));
pts[5].getX = function () { return 1000; }; console.log('own method', method(pts[5]));
Number.prototype.len2 = function () { return 2; }; Number.prototype.getX = function () { return 3; };
console.log('primitive receiver', method(5));
var px = new Proxy(new Point(1, 1), {}); console.log('proxy', method(px), forward(px), diamond(px, 1));
function read(o) { return o.child.value + 1; }
function middle(o) { return read(o); }
function site(o) { return middle(o); }
function arrayRead(o) { return o.child.length + o.child.value; }
function arrayMiddle(o) { return arrayRead(o); }
function arraySite(o) { return arrayMiddle(o); }
var ha = { child: { value: 7 } }, hb = { padding: 1, child: { padding: 2, value: 11 } };
var harr = [1, 2, 3]; harr.value = 10; var holder = { child: harr };
function warmHints() { var s = 0; for (var i = 0; i < 600; i++) { s += site(ha) + arraySite(holder); } for (var i = 0; i < 40; i++) s += site(hb) + site(ha); return s; }
console.log('hints', warmHints());
var hreads = 0;
Object.defineProperty(ha.child, 'value', { configurable: true, get: function () { hreads++; $262.gc(); return 13; } });
console.log('hint getter', site(ha), hreads);
Object.defineProperty(ha.child, 'value', { configurable: true, writable: true, value: 15 });
console.log('hint data again', site(ha), hreads);
harr.push(4, 5); console.log('array hint', arraySite(holder)); harr.length = 0; console.log('emptied', arraySite(holder));
delete harr.value; harr.padding = 2; harr.value = 12; console.log('re-added', arraySite(holder), site({ child: { value: 'v' } }), site({ child: Object.create({ value: 1 }) }));
"""
    check(js, golden, "write_region_switches", code, switches, tier)


@pytest.mark.parametrize("switches,tier", kill_modes(
    "LUMEN_JIT_NO_SCALAR_CONDITION", "LUMEN_JIT_NO_LAST_USES"))
def test_scalar_and_bool_condition_fixtures_under_their_kill_switches(js, golden, switches, tier):
    """CATCHES: scalar-condition lowering (or its disabled helper path) that treats -0 or NaN as truthy, ignores BigInt zero, or branches on a stale operand, so the scalar_condition_branch.js / bool_condition_branch.js checksums and truthiness tables differ."""
    code = r"""
"use strict";
function branchReturn(value) { if (value & 1) return value; return value + 1; }
function branchBool(value, number) { if (value) return number; return number + 1; }
function runScalar(count) { let sum = 0; for (let i = 0; i < count; i++) sum += branchReturn(i & 7); return sum; }
function runBool(count) { let sum = 0; for (let i = 0; i < count; i++) sum += branchBool((i & 1) === 1, i & 7); return sum; }
function truthy(x) { if (x * 1) return 1; return 0; }
function truthySub(a, b) { if (a - b) return 'ne'; return 'eq'; }
function truthyDiv(a, b) { while (a / b) { return 'div'; } return 'zero'; }
function bigTruthy(a, b) { if (a * b) return 'big'; return 'bigzero'; }
function neg(x) { if (-x) return 'neg'; return 'negzero'; }
function shift(x) { if (x >> 1) return 's'; return 'z'; }
function warm() { let s = 0; for (let k = 0; k < 200; k++) { s += truthy(k) + (truthySub(k, 3) === 'ne' ? 1 : 0) + (truthyDiv(k, 2) === 'div' ? 1 : 0); bigTruthy(BigInt(k), 2n); neg(k); shift(k); } return s; }
runScalar(10000);
console.log('branch-return: (' + runScalar(20000) + ') ' + runScalar(77));
runBool(10000);
console.log('bool-branch: (' + runBool(20000) + ') ' + runBool(33));
console.log('warm', warm());
console.log(truthy(0), truthy(-0), truthy(NaN), truthy(0.5), truthy('0'), truthy(''), truthy(null), truthy([]), truthy(Infinity));
console.log(truthySub(3, 3), truthySub(0, -0), truthySub(NaN, NaN), truthySub(1.5, 1), truthySub('2', 2), truthySub(1n, 1n), truthySub(5n, 2n));
console.log(truthyDiv(0, 5), truthyDiv(-0, 5), truthyDiv(1, 0), truthyDiv(0, 0), truthyDiv(1, Infinity), truthyDiv(-1, -Infinity));
console.log(bigTruthy(0n, 5n), bigTruthy(3n, 4n), bigTruthy(2 ** 60, 0), bigTruthy(1, 1), neg(0), neg(-0), neg(NaN), neg(2), neg(0n), neg(-3n));
console.log(shift(1), shift(2), shift(-1), shift(0.9), shift(2 ** 32), shift('4'));
"""
    check(js, golden, "condition_switches", code, switches, tier)


@pytest.mark.parametrize("switches,tier", kill_modes(
    "LUMEN_NO_ARRAY_DESTRUCTURE", "LUMEN_NO_ARRAY_ITERATOR_STATE", "LUMEN_NO_ARRAY_ITERATOR_STEP",
    "LUMEN_NO_ASCII_SUBSTRING", "LUMEN_NO_COMPACT_BUILTIN_ARRAYS"))
def test_array_iteration_and_substring_under_their_kill_switches(js, golden, switches, tier):
    """CATCHES: the array-destructuring, array-iterator-state, iterator-step, ASCII-substring or compact-array baselines diverging from the fast paths: ignoring a patched %ArrayIteratorPrototype%.next or an own @@iterator, missing elements pushed during iteration, or slicing non-ASCII strings at the wrong code units."""
    code = r"""
function destr(arr) { var [a, b, , c = 9, ...rest] = arr; return a + '|' + b + '|' + c + '|' + rest.length; }
function swap(p) { var x = p[0], y = p[1]; [x, y] = [y, x]; return x * 10 + y; }
function spreadCall(f, xs) { return f(...xs); }
function sum3(a, b, c) { return a + b + c; }
function forOf(xs) { var s = 0; for (var v of xs) s += v; return s; }
function entries(xs) { var out = ''; for (var [i, v] of xs.entries()) out += i + ':' + v + ','; return out; }
function keysVals(xs) { return [...xs.keys()].join('') + '/' + Array.from(xs.values()).join(''); }
function iterManual(xs) { var it = xs[Symbol.iterator](); var r = it.next(); var s = ''; while (!r.done) { s += r.value; r = it.next(); } return s + String(it.next().done); }
function sub(s, i) { return s.substring(i, i + 3) + s.substr(i, 2) + s.slice(-i - 1) + s.substring(i + 4, i); }
function warm() { var acc = 0, t = ''; for (var k = 0; k < 120; k++) { destr([k, 2, 3, undefined, 5, 6]); acc += swap([k, k + 1]) + spreadCall(sum3, [k, 1, 2]) + forOf([1, 2, 3, k]); entries(['a', 'b']); keysVals([4, 5]); iterManual([1, 2]); t = sub('abcdefghijklmnop', k % 8); } return acc + t; }
console.log('warm', warm());
console.log(destr([1, 2, 3]), destr([1]), destr('xyzw'), destr(new Set([7, 8, 9, 10, 11])), swap([3, 4]), spreadCall(sum3, [1, 2, 3]), spreadCall(sum3, 'abc'));
console.log(forOf([1, 2, , 4]), forOf(new Float32Array([0.5, 1.5])), entries(['x', , 'z']), keysVals([7, 8, 9]), iterManual('hey'), iterManual(new Map([[1, 2]])));
var arr = [1, 2, 3]; var ArrayIteratorProto = Object.getPrototypeOf([][Symbol.iterator]()); var origNext = ArrayIteratorProto.next;
ArrayIteratorProto.next = function () { var r = origNext.call(this); if (!r.done) r.value = r.value * 100; return r; };
console.log('patched next', forOf(arr), destr(arr), spreadCall(sum3, arr), iterManual(arr));
ArrayIteratorProto.next = origNext;
arr[Symbol.iterator] = function* () { yield 'own'; };
console.log('own iterator', forOf(arr), destr(arr), spreadCall(sum3, arr));
console.log('restored', forOf([5, 5]), destr([4, 3, 2, 1]));
var grow = [1, 2]; var seen = []; for (var v of grow) { seen.push(v); if (grow.length < 5) grow.push(v * 10); } console.log('grow', seen.join(','));
console.log(sub('abcdefghij', 2), sub('héllo wörld', 1), sub('ab', 5), 'x'.substring(-1, 10), 'abc'.substring(NaN, 2), 'abcdef'.substring(4, 1));
var big = []; for (var i = 0; i < 300; i++) big.push(i % 7); console.log('big', forOf(big), destr(big), big.indexOf(6), big.lastIndexOf(0), big.includes(7));
"""
    check(js, golden, "iteration_switches", code, switches, tier)
