"""Custom iterator protocols run with the experimental native iterator entry enabled.

docs/optimizer.md documents `LUMEN_ITERATOR_ENTRY_NATIVE`: an opt-in fast entry for admitted
`next()` bodies that must stay observably identical to an ordinary call. Every test drives a
user-defined iterator through `for...of`/spread/destructuring with the flag on, under the default
(JIT) tier and the bytecode VM, and compares the exact program output with the reference.
"""

import pytest

from conftest import out

NATIVE = {"LUMEN_ITERATOR_ENTRY_NATIVE": "1"}
TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode")]

# The canonical admitted shape: guard on captured state, bump a numeric field, yield a dense element.
QUEUE = r"""
function make(items){
  const state={cursor:0,items:items};
  return {state:state,[Symbol.iterator](){return this;},next(){
    if(state.cursor<state.items.length){
      state.cursor=state.cursor+1;
      return {value:state.items[state.cursor-1],done:false};
    }
    return {done:true};
  }};
}
function drain(it){var values=[];for(var value of it)values.push(value);return values;}
"""


@pytest.mark.parametrize("tier", TIERS)
def test_queue_iterator_yields_each_element_in_order(js, golden, tier):
    """CATCHES: a native iterator entry that skips, repeats or reorders yielded elements, or loses
    the cursor write when the entry is reused across 300 freshly created iterators."""
    code = QUEUE + r"""
var lines=[];var total=0;
for(var n=0;n<300;n++){
  var it=make([{x:n},{x:n+1},{x:n*2}]);
  var v=drain(it);
  total+=v[0].x+v[1].x+v[2].x;
  if(n%60===0)lines.push(n+':'+v.map(function(o){return o.x;}).join(',')+':cursor='+it.state.cursor);
}
console.log(lines.join('\n'));
console.log('total', total);
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("queue_in_order")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_yielded_objects_survive_after_iterator_is_dropped(js, golden, tier):
    """CATCHES: native entries that hand out borrowed (unowned) element references, so yielded
    objects are corrupted or freed once the iterator and its state are released and GC runs."""
    code = QUEUE + r"""
var kept=[];
for(var n=0;n<120;n++){
  var it=make([{x:n,tag:'a'+n},{x:-n,tag:'b'+n}]);
  var v=drain(it);
  kept.push(v[0],v[1]);
  it=null;v=null;
  var junk=[];for(var k=0;k<200;k++)junk.push({k:k,s:'s'+k});
}
var sum=0;for(var i=0;i<kept.length;i++)sum+=kept[i].x;
console.log(kept.length, sum, kept[0].tag, kept[1].tag, kept[238].tag, kept[239].tag);
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("yielded_survive")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_accessor_element_runs_getter_exactly_once(js, golden, tier):
    """CATCHES: a guard miss that replays the deferred cursor write or calls an accessor element's
    getter twice (or not at all) instead of resuming the original next() body."""
    code = QUEUE + r"""
for(var w=0;w<50;w++)drain(make([{x:1},{x:2},{x:3}]));
var it=make([{x:7},{x:8},{x:9}]),calls=0,seen=[];
Object.defineProperty(it.state.items,'1',{get(){calls++;seen.push(it.state.cursor);return {x:80};},configurable:true});
var values=drain(it);
console.log('calls',calls,'cursor at getter',seen.join(','),'final',it.state.cursor);
console.log(values.map(function(v){return v.x;}).join(','));
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("accessor_once")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_holes_proxies_and_readonly_cursor_fall_back(js, golden, tier):
    """CATCHES: native entries that read array holes as undefined elements without consulting the
    prototype, bypass a Proxy's traps, or write a frozen/readonly cursor instead of falling back."""
    code = QUEUE + r"""
for(var w=0;w<40;w++)drain(make([1,2,3]));
Array.prototype[1]='from-proto';
var holey=[10,,30];
console.log('holes', JSON.stringify(drain(make(holey))));
delete Array.prototype[1];
var log=[];
var proxied=new Proxy([4,5,6],{get(t,k,r){if(typeof k==='string')log.push(k);return Reflect.get(t,k,r);}});
console.log('proxy', drain(make(proxied)).join(','), log.join(' '));
var it=make([1,2,3]);
Object.defineProperty(it.state,'cursor',{value:0,writable:false});
var ro=[];for(var v of it){ro.push(v);if(ro.length>4)break;}
console.log('readonly', ro.join(','), it.state.cursor);
var it2=make([1,2,3]);Object.freeze(it2.state);
var got=[];var guard=0;for(var v of it2){got.push(v);if(++guard>4)break;}
console.log('frozen', got.join(','), it2.state.cursor);
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("holes_proxy_readonly")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_numeric_edge_values_keep_ieee_semantics(js, golden, tier):
    """CATCHES: a native numeric store that rounds differently from the interpreter near 2**53,
    canonicalises NaN incorrectly, or loses the sign of negative zero in the cursor field."""
    code = r"""
function counter(start, step){
  const s={pos:start,limit:start+step*3,step:step};
  return {[Symbol.iterator](){return this;},s:s,next(){
    if(s.pos<s.limit){s.pos=s.pos+s.step;return {value:s.pos,done:false};}
    return {done:true};
  }};
}
for(var w=0;w<60;w++)[...counter(w,1)];
console.log([...counter(2**53-2,1)].join(','));
console.log([...counter(0.1,0.2)].join(','));
console.log([...counter(-3,1)].map(function(v){return Object.is(v,-0)?'-0':String(v);}).join(','));
var c=counter(NaN,1);console.log([...c].length, String(c.s.pos));
var big=counter(1e308,1e308);console.log([...big].join(','));
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("numeric_edges")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_this_based_iterator_with_arithmetic_and_comparisons(js, golden, tier):
    """CATCHES: wrong evaluation of `this.field` reads, Mul/Div/Sub arithmetic or <=, >, >= guards
    inside an admitted next() body, or yielding the computed value from the wrong operand."""
    code = r"""
function Range(lo,hi,scale){this.i=lo;this.hi=hi;this.scale=scale;}
Range.prototype[Symbol.iterator]=function(){return this;};
Range.prototype.next=function(){
  if(this.i<=this.hi){this.i=this.i+1;return {value:(this.i-1)*this.scale/2,done:false};}
  return {value:undefined,done:true};
};
function Down(hi,lo){this.i=hi;this.lo=lo;}
Down.prototype[Symbol.iterator]=function(){return this;};
Down.prototype.next=function(){
  if(this.i>this.lo){this.i=this.i-1;return {done:false,value:this.i*3};}
  return {done:true,value:null};
};
function Gate(n){this.n=n;this.k=0;}
Gate.prototype[Symbol.iterator]=function(){return this;};
Gate.prototype.next=function(){
  if(this.n>=this.k){this.k=this.k+2;return {value:this.k>this.n,done:false};}
  return {done:true};
};
var acc=0;
for(var r=0;r<100;r++){for(var v of new Range(0,4,3))acc+=v;for(var d of new Down(5,1))acc+=d;}
console.log(acc);
console.log([...new Range(1,5,5)].join(' '));
console.log([...new Down(4,0)].join(' '));
console.log([...new Gate(5)].join(' '));
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("this_arith")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_constant_and_global_valued_iterators(js, golden, tier):
    """CATCHES: native entries that mishandle literal results (null, undefined, booleans, numbers)
    or read a global/captured name once and keep yielding a stale value after it changes."""
    code = r"""
var LIMIT=3;var hits=0;
var g={[Symbol.iterator](){return this;},next(){return {value:LIMIT,done:false};}};
var n={[Symbol.iterator](){return this;},next(){return {value:null,done:false};}};
var u={[Symbol.iterator](){return this;},next(){return {value:undefined,done:false};}};
var t={[Symbol.iterator](){return this;},next(){return {value:true,done:false};}};
function take(it,k){var out=[];for(var v of it){out.push(v);if(out.length>=k)break;}return out;}
var s=0;for(var r=0;r<80;r++){s+=take(g,3).length;LIMIT=r;}
console.log(s, take(g,2).join(','));
LIMIT='changed';console.log(take(g,2).join(','));
console.log(JSON.stringify(take(n,2)), JSON.stringify(take(u,2)), JSON.stringify(take(t,2)));
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("constants_globals")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_rejected_shapes_still_iterate_correctly(js, golden, tier):
    """CATCHES: an implementation whose iterator fast path changes the results of next() bodies
    that do more than one store, call functions, use string literals, return non-literal done
    flags or other result keys, or are arrow/generator/argument-using functions."""
    code = r"""
function mk(next){return {[Symbol.iterator](){return this;},next:next};}
function take(it,k){var out=[];for(var v of it){out.push(v);if(out.length>=k)break;}return out;}
var st={a:0,b:0};
var two=mk(function(){st.a=st.a+1;st.b=st.b+2;return {value:st.a+st.b,done:false};});
var call=mk(function(){return {value:Math.max(st.a,7),done:false};});
var str=mk(function(){return {value:'s',done:false};});
var dyn=mk(function(){st.a=st.a+1;return {value:st.a,done:st.a>200};});
var keys=mk(function(){return {value:1,done:false,extra:2};});
var args=mk(function(){return {value:arguments.length,done:false};});
var arrow={[Symbol.iterator](){return this;},next:()=>({value:'arrow',done:false})};
function* gen(){var i=0;while(true)yield i++;}
var loop=mk(function(){var x=0;for(var i=0;i<3;i++)x+=i;return {value:x,done:false};});
var lines=[];
for(var r=0;r<30;r++){
  lines=[take(two,2),take(call,2),take(str,2),take(dyn,2),take(keys,2),take(args,2),take(arrow,2),take(gen(),3),take(loop,2)];
}
console.log(lines.map(function(l){return l.join('|');}).join('\n'));
console.log(st.a, st.b);
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("rejected_shapes")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_thrown_and_non_object_results(js, golden, tier):
    """CATCHES: native iterator entries that swallow an exception thrown by next(), or accept a
    primitive iterator result instead of throwing TypeError as IteratorStep requires."""
    code = r"""
var st={i:0};
var it={[Symbol.iterator](){return this;},next(){
  if(st.i<3){st.i=st.i+1;return {value:st.i,done:false};}
  throw new RangeError('stop at '+st.i);
}};
for(var r=0;r<40;r++){st.i=0;try{for(var v of it){}}catch(e){if(r===39)console.log(e.name+': '+e.message);}}
var prim={[Symbol.iterator](){return this;},next(){return 42;}};
try{for(var v of prim){}}catch(e){console.log(e.name+': '+e.message);}
var nul={[Symbol.iterator](){return this;},next(){return null;}};
try{[...nul];}catch(e){console.log(e.name);}
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("throw_nonobject")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_switching_between_live_iterators(js, golden, tier):
    """CATCHES: a cached native entry rebound to one closure's captured state that keeps reading
    the wrong iterator's state when two live iterators from the same factory alternate."""
    code = QUEUE + r"""
function one(it){for(var value of it)return value;}
var a=make([{x:10},{x:11}]),b=make([{x:20},{x:21}]);
var out=[];
for(var n=0;n<40;n++){
  a.state.cursor=0;b.state.cursor=0;
  var row=[one(a).x,one(a).x,one(b).x,one(b).x];
  if(n%10===0)out.push(row.join(','));
  if(n===25){a.state.items=[{x:30},{x:31}];}
}
console.log(out.join('\n'));
console.log(a.state.cursor, b.state.cursor);
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("switching")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_shadowing_and_mutated_captures(js, golden, tier):
    """CATCHES: native name resolution that caches a captured binding's storage and misses later
    reassignment of the captured variable, eval-introduced shadowing, or a let still in its TDZ."""
    code = r"""
function factory(){
  let limit=2; let base=100;
  const it={[Symbol.iterator](){return this;},pos:0,next(){
    if(this.pos<limit){this.pos=this.pos+1;return {value:base+this.pos,done:false};}
    return {done:true};
  }};
  return {it:it,set(l,b){limit=l;base=b;}};
}
var f=factory();var seen=[];
for(var r=0;r<50;r++){f.it.pos=0;seen.push([...f.it].join('+'));if(r===30)f.set(4,500);}
console.log(seen[0], seen[30], seen[31], seen[49]);
function late(){
  const it={[Symbol.iterator](){return this;},next(){return {value:early,done:false};}};
  for(var w=0;w<20;w++){try{for(var v of it)break;}catch(e){if(w===0)console.log(e.name);}}
  let early=5;
  var got=[];for(var v of it){got.push(v);if(got.length>1)break;}
  return got.join(',');
}
console.log(late());
"""
    r = js(code, *tier, env_overrides=NATIVE)
    assert out(r) == golden("shadow_capture")
    assert (r.returncode, r.stderr) == (0, b"")
