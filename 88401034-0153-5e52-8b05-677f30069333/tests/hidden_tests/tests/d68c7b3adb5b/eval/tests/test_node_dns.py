"""node:dns without a network: lookups of IP literals (resolved without any nameserver), family
filtering, the NUL-byte resolver failure, the ENOTIMP record types, Resolver server lists and the
error-code constants. Nothing here sends a DNS query or prints the host's /etc/resolv.conf.

Callback completions come back from a thread pool, so programs that issue several lookups await
them one at a time (or collect them with Promise.all) to keep the printed order deterministic.
"""

from conftest import out

# Promise wrapper around a callback-style call that records exactly what the callback received.
CB = r"""
const dns = require('dns');
const viaCallback = (fn, ...args) => new Promise((res) => fn(...args, (...cbArgs) => res(cbArgs)));
const fmt = (cbArgs) => {
  const [err, ...rest] = cbArgs;
  if (err) return `ERR ${err.name} code=${err.code} message=${JSON.stringify(err.message)}`;
  return 'ok ' + JSON.stringify(rest);
};
"""


def test_lookup_ipv4_literals_callback_overloads(js, golden):
    """CATCHES: dns.lookup() overloads (cb), (options, cb), (family, cb) and {all:true} that
    mis-shuffle their arguments, return the wrong family number, or hand back a bare address where
    an array of {address, family} objects is expected."""
    code = CB + r"""
(async () => {
  const calls = [
    ['plain', '127.0.0.1'],
    ['empty options', '127.0.0.1', {}],
    ['family number 4', '10.20.30.40', 4],
    ['family option 4', '192.0.2.55', { family: 4 }],
    ['all', '127.0.0.1', { all: true }],
    ['all + family 4', '0.0.0.0', { all: true, family: 4 }],
    ['family 0', '255.255.255.255', { family: 0 }],
    ['null options', '198.51.100.7', null],
  ];
  for (const [label, ...args] of calls) console.log(label.padEnd(16), fmt(await viaCallback(dns.lookup, ...args)));
})();
"""
    r = js(code)
    assert out(r) == golden("lookup_ipv4")
    assert (r.returncode, r.stderr) == (0, b"")


def test_lookup_ipv6_literals(js, golden):
    """CATCHES: IPv6 literal lookups that report family 4, mangle the address text, ignore the
    numeric/option family forms, or mishandle IPv4-mapped and unspecified addresses."""
    code = CB + r"""
(async () => {
  const calls = [
    ['::1'], ['::1', { family: 6 }], ['::1', 6], ['fe80::1', { all: true }],
    ['2001:db8::1'], ['2001:db8:85a3::8a2e:370:7334', { family: 6, all: true }], ['::ffff:10.1.2.3'], ['::'],
  ];
  for (const args of calls) console.log(JSON.stringify(args).padEnd(52), fmt(await viaCallback(dns.lookup, ...args)));
})();
"""
    r = js(code)
    assert out(r) == golden("lookup_ipv6")
    assert (r.returncode, r.stderr) == (0, b"")


def test_lookup_family_filter_without_match_is_enotfound(js, golden):
    """CATCHES: a family filter that is ignored (returning an IPv4 address for family 6 or vice
    versa) or that fails with a code other than ENOTFOUND / a message other than
    'queryA/AAAA <host>: no matching records', in callback and promise form."""
    code = CB + r"""
(async () => {
  console.log('v4 as 6     ', fmt(await viaCallback(dns.lookup, '127.0.0.1', { family: 6 })));
  console.log('v4 as 6 all ', fmt(await viaCallback(dns.lookup, '192.0.2.1', { family: 6, all: true })));
  console.log('v6 as 4     ', fmt(await viaCallback(dns.lookup, '::1', 4)));
  try {
    await dns.promises.lookup('2001:db8::5', { family: 4 });
    console.log('promise resolved (unexpected)');
  } catch (e) {
    console.log('promise rejected', e instanceof Error, e.code, JSON.stringify(e.message));
  }
  const err = (await viaCallback(dns.lookup, '10.0.0.1', 6))[0];
  console.log('error equals NOTFOUND constant:', err.code === dns.NOTFOUND);
})();
"""
    r = js(code)
    assert out(r) == golden("family_mismatch")
    assert (r.returncode, r.stderr) == (0, b"")


def test_lookup_of_name_with_nul_byte_fails(js, golden):
    """CATCHES: a lookup of a hostname containing a NUL byte that is truncated at the NUL and
    resolved, hangs, or throws synchronously instead of failing via the callback/promise with
    code EAI_FAIL and the getaddrinfo message."""
    code = CB + r"""
(async () => {
  let sync = 'no synchronous throw';
  let p;
  try { p = viaCallback(dns.lookup, '127.0.0.1\u0000evil'); } catch (e) { sync = 'threw ' + e.message; }
  console.log(sync);
  console.log('callback', fmt(await p));
  const e2 = await dns.promises.lookup('a\u0000b', { all: true }).then(() => null, (e) => e);
  console.log('promise', e2.code, JSON.stringify(e2.message));
})();
"""
    r = js(code)
    assert out(r) == golden("nul_hostname")
    assert (r.returncode, r.stderr) == (0, b"")


def test_promises_lookup_shapes_and_module_identity(js, golden):
    """CATCHES: dns.promises.lookup resolving to the wrong shape ({address, family} for one result,
    an array with {all:true}), or dns.promises not being the same object as require('dns/promises')."""
    code = r"""
const dns = require('dns');
const dp = require('dns/promises');
console.log('dns.promises === dns/promises:', dns.promises === dp);
console.log('node:dns is dns:', require('node:dns') === dns, 'node:dns/promises is dns/promises:', require('node:dns/promises') === dp);
(async () => {
  console.log('default ', JSON.stringify(await dp.lookup('127.0.0.1')));
  console.log('number 6', JSON.stringify(await dp.lookup('::1', 6)));
  console.log('family 4', JSON.stringify(await dp.lookup('203.0.113.9', { family: 4 })));
  console.log('all     ', JSON.stringify(await dp.lookup('::ffff:1.2.3.4', { all: true })));
  const both = await Promise.all(['10.0.0.1', '::2', '10.0.0.3', 'fe80::4'].map((h) => dp.lookup(h)));
  console.log('Promise.all keeps order', JSON.stringify(both));
})();
"""
    r = js(code)
    assert out(r) == golden("promises_lookup")
    assert (r.returncode, r.stderr) == (0, b"")


def test_many_concurrent_lookups_settle_independently(js, golden):
    """CATCHES: concurrent lookups whose completions are delivered to the wrong callback (results
    swapped between requests) or that are lost when many are in flight at once."""
    code = CB + r"""
const hosts = [];
for (let i = 0; i < 24; i++) hosts.push(i % 3 === 0 ? `2001:db8::${(i + 1).toString(16)}` : `10.${i}.${i * 2}.${i * 3}`);
const opts = (i) => (i % 4 === 0 ? { all: true } : i % 4 === 1 ? 4 : i % 4 === 2 ? { family: 6 } : {});
Promise.all(hosts.map((h, i) => viaCallback(dns.lookup, h, opts(i)))).then((results) => {
  results.forEach((r, i) => console.log(String(i).padStart(2), hosts[i].padEnd(14), JSON.stringify(opts(i)).padEnd(12), fmt(r)));
});
"""
    r = js(code)
    assert out(r) == golden("concurrent_lookups")
    assert (r.returncode, r.stderr) == (0, b"")


def test_unbacked_record_types_fail_with_enotimp_asynchronously(js, golden):
    """CATCHES: resolvers with no backing (SRV/SOA/NAPTR/CAA/TLSA/ANY, lookupService) that throw
    on call, invoke the callback synchronously, invent records, or produce errors without the
    ENOTIMP code, the c-ares style syscall name and the hostname field."""
    code = r"""
const dns = require('dns');
const results = [];
const record = (label) => (err, value) => results.push(`${label.padEnd(26)} ${err ? `${err.code} syscall=${err.syscall} hostname=${err.hostname} message=${JSON.stringify(err.message)}` : 'value ' + JSON.stringify(value)}`);
dns.resolveSrv('_sip._tcp.example.test', record('resolveSrv'));
dns.resolveSoa('example.test', record('resolveSoa'));
dns.resolveNaptr('example.test', record('resolveNaptr'));
dns.resolveCaa('example.test', record('resolveCaa'));
dns.resolveTlsa('_443._tcp.example.test', record('resolveTlsa'));
dns.resolveAny('example.test', record('resolveAny'));
dns.resolveSrv('with-options.test', { ttl: true }, record('resolveSrv with options'));
dns.resolve('example.test', 'SRV', record("resolve(host, 'SRV')"));
dns.resolve('lower.test', 'naptr', record("resolve(host, 'naptr')"));
dns.lookupService('127.0.0.1', 22, record('lookupService'));
const r = new dns.Resolver();
r.resolveSoa('via-resolver.test', record('Resolver#resolveSoa'));
r.resolve('via-resolver.test', 'CAA', record('Resolver#resolve CAA'));
console.log('callbacks run synchronously:', results.length);
setTimeout(() => console.log(results.join('\n')), 0);
"""
    r = js(code)
    assert out(r) == golden("enotimp_callbacks")
    assert (r.returncode, r.stderr) == (0, b"")


def test_promise_api_rejects_unbacked_queries_with_enotimp(js, golden):
    """CATCHES: the promise API (dns.promises.* and dns.promises.Resolver) resolving or throwing
    synchronously for unbacked record types / lookupService instead of rejecting with ENOTIMP."""
    code = r"""
const dp = require('dns').promises;
const show = (p) => p.then((v) => 'resolved ' + JSON.stringify(v), (e) => `rejected ${e instanceof Error} ${e.code} ${e.syscall} ${JSON.stringify(e.message)}`);
(async () => {
  console.log('resolveSrv      ', await show(dp.resolveSrv('_ldap._tcp.example.test')));
  console.log('resolveAny      ', await show(dp.resolveAny('example.test')));
  console.log("resolve 'TLSA'  ", await show(dp.resolve('example.test', 'TLSA')));
  console.log('lookupService   ', await show(dp.lookupService('::1', 443)));
  const pr = new dp.Resolver({ timeout: 100 });
  console.log('Resolver.naptr  ', await show(pr.resolveNaptr('example.test')));
  console.log('Resolver.resolve', await show(pr.resolve('example.test', 'soa')));
  console.log('methods are functions:', ['resolve4', 'resolve6', 'resolveMx', 'resolveTxt', 'resolvePtr', 'resolveCname', 'resolveNs', 'reverse'].every((m) => typeof dp[m] === 'function' && typeof pr[m] === 'function'));
})();
"""
    r = js(code)
    assert out(r) == golden("enotimp_promises")
    assert (r.returncode, r.stderr) == (0, b"")


def test_resolver_server_lists_are_independent_copies(js, golden):
    """CATCHES: Resolver instances sharing one server array, getServers() returning the internal
    array (so caller mutations leak in), setServers() accepting non-arrays, or the promise
    Resolver not keeping its own list."""
    code = r"""
const dns = require('dns');
const systemServers = dns.getServers();
console.log('system list is an array of strings:', Array.isArray(systemServers), systemServers.every((s) => typeof s === 'string'));
const a = new dns.Resolver();
const b = new dns.Resolver({ timeout: 500, tries: 2 });
console.log('new resolvers start from the system list:', JSON.stringify(a.getServers()) === JSON.stringify(systemServers));
a.setServers(['192.0.2.1', '[2001:db8::1]:5353', '198.51.100.2']);
console.log('a after setServers', JSON.stringify(a.getServers()));
console.log('b unaffected:', JSON.stringify(b.getServers()) === JSON.stringify(systemServers));
const copy = a.getServers();
copy.push('203.0.113.99');
console.log('mutating the returned array does not leak:', JSON.stringify(a.getServers()));
const input = ['192.0.2.10'];
b.setServers(input);
input.push('192.0.2.11');
console.log('b keeps a copy of its input:', JSON.stringify(b.getServers()));
b.setServers([]);
console.log('b emptied', JSON.stringify(b.getServers()));
for (const bad of ['192.0.2.1', null, { length: 1, 0: '192.0.2.1' }]) {
  try { a.setServers(bad); console.log('accepted', JSON.stringify(bad)); }
  catch (e) { console.log(e.name, e.message.startsWith('The "servers" argument must be an instance of Array')); }
}
console.log('setLocalAddress/cancel are no-ops:', a.setLocalAddress('0.0.0.0'), a.cancel());
const pr = new dns.promises.Resolver();
pr.setServers(['192.0.2.77']);
console.log('promise resolver', JSON.stringify(pr.getServers()), 'a still', JSON.stringify(a.getServers()));
try { pr.setServers('x'); } catch (e) { console.log('promise resolver rejects non-arrays:', e.name); }
dns.setServers(['192.0.2.200']);
console.log('default resolver', JSON.stringify(dns.getServers()), 'promises view', JSON.stringify(dns.promises.getServers()));
console.log('a unaffected by default change:', JSON.stringify(a.getServers()));
"""
    r = js(code)
    assert out(r) == golden("resolver_servers")
    assert (r.returncode, r.stderr) == (0, b"")


def test_error_code_constants_and_lookup_flags(js, golden):
    """CATCHES: missing or misspelled dns error-code constants (dns.NOTFOUND === 'ENOTFOUND' ...),
    constants that differ between dns and dns.promises, or getaddrinfo hint flags (ADDRCONFIG,
    ALL, V4MAPPED) that are missing, collide, or leak onto dns.promises."""
    code = r"""
const dns = require('dns');
const names = ['NODATA', 'FORMERR', 'SERVFAIL', 'NOTFOUND', 'NOTIMP', 'REFUSED', 'BADQUERY', 'BADNAME',
  'BADFAMILY', 'BADRESP', 'CONNREFUSED', 'TIMEOUT', 'EOF', 'FILE', 'NOMEM', 'DESTRUCTION', 'BADSTR',
  'BADFLAGS', 'NONAME', 'BADHINTS', 'NOTINITIALIZED', 'LOADIPHLPAPI', 'ADDRGETNETWORKPARAMS', 'CANCELLED'];
for (const n of names) console.log(n.padEnd(22), dns[n], dns.promises[n] === dns[n]);
const flags = [dns.ADDRCONFIG, dns.ALL, dns.V4MAPPED];
console.log('flags are distinct single bits:', flags.every((v) => Number.isInteger(v) && v > 0 && (v & (v - 1)) === 0), new Set(flags).size);
console.log('flags on promises', dns.promises.ADDRCONFIG, dns.promises.ALL, dns.promises.V4MAPPED);
console.log('Resolver classes', typeof dns.Resolver, typeof dns.promises.Resolver, dns.Resolver === dns.promises.Resolver);
"""
    r = js(code)
    assert out(r) == golden("constants")
    assert (r.returncode, r.stderr) == (0, b"")


def test_default_result_order_is_shared(js, golden):
    """CATCHES: get/setDefaultResultOrder that do not round-trip, start from a value other than
    'verbatim', or keep separate state for dns and dns.promises."""
    code = r"""
const dns = require('dns');
console.log('initial', dns.getDefaultResultOrder(), dns.promises.getDefaultResultOrder());
dns.setDefaultResultOrder('ipv4first');
console.log('after dns.set ipv4first', dns.getDefaultResultOrder(), dns.promises.getDefaultResultOrder());
dns.promises.setDefaultResultOrder('verbatim');
console.log('after promises.set verbatim', dns.getDefaultResultOrder(), dns.promises.getDefaultResultOrder());
dns.setDefaultResultOrder('ipv6first');
console.log('after dns.set ipv6first', dns.getDefaultResultOrder());
dns.promises.lookup('127.0.0.1').then((r) => console.log('lookup still works', JSON.stringify(r)));
"""
    r = js(code)
    assert out(r) == golden("result_order")
    assert (r.returncode, r.stderr) == (0, b"")


