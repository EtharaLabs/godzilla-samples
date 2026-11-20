"""Codecs and node:crypto: node:zlib (deflate/zlib/gzip, Brotli, Zstandard; sync, callback and stream
forms), crc32, the web CompressionStream, and node:crypto hashing, HMAC, KDFs, AES ciphers and Argon2.

Every decoder is fed reference streams produced by independent encoders (Python's zlib, Node's
Brotli and the system libzstd, captured once and embedded below as base64) or hand-assembled per
RFC 1951 / RFC 7932 / RFC 8878 (and checked against those reference decoders), and the decoded bytes
are compared with the input regenerated in JS from a fixed LCG. Crypto outputs are standard test
vectors (FIPS 180, RFC 2202/4231/6070/5869/7914/9106, SP 800-38A, the GCM spec) cross-checked
against Node. Encoder outputs are deterministic for a fixed implementation, so a few small inputs
pin the exact compressed bytes.
"""

import json

import pytest

from conftest import err, out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

# Deterministic input generators shared by the codec programs (a Python port produced the
# reference streams below from exactly these bytes).
JS_GEN = r"""
const zlib = require("zlib");
function lcg(seed) { let s = seed >>> 0; return () => (s = (Math.imul(s, 1103515245) + 12345) >>> 0); }
const WORDS = ("the of and to in is that for it with as was on be at by this had not are but from or have an " +
  "they which one you were her all she there would their we him been has when who will more no if out so " +
  "said what up its about into than them can only other new some could time these two may then do first any " +
  "my now such like our over man me even most made after also did many before must through back years where " +
  "much your way well down should because each just those people how too little state good very make world " +
  "still own see men work long get here between both life being under never day same another know while last " +
  "might us great old year off come since against go came right used take three").split(" ");
function words(n, seed) {
  const r = lcg(seed); const o = [];
  for (let i = 0; i < n; i++) {
    const w = WORDS[r() % WORDS.length]; const t = r() & 15;
    o.push(t === 0 ? w.toUpperCase() : t === 1 ? w[0].toUpperCase() + w.slice(1) : t === 2 ? w + "," : t === 3 ? w + ".\n" : w);
  }
  return Buffer.from(o.join(" "));
}
function noise(n, seed, mask, base) {
  const r = lcg(seed); const b = Buffer.alloc(n);
  for (let i = 0; i < n; i++) b[i] = base + ((r() >>> 24) & mask);
  return b;
}
function sections(n, seed) {
  const r = lcg(seed); const parts = [];
  for (let i = 0; i < n; i++) {
    const k = r() % 4;
    if (k === 0) parts.push(words(60 + r() % 60, r()));
    else if (k === 1) parts.push(noise(200 + r() % 200, r(), 15, 0x30));
    else if (k === 2) parts.push(noise(150, r(), 0xC3, 0));
    else parts.push(Buffer.from(words(30, r()).toString().toUpperCase()));
  }
  return Buffer.concat(parts);
}
const crcHex = (b) => zlib.crc32(b).toString(16).padStart(8, "0");
const hex = (s) => Buffer.from(s, "hex");
"""


def program(body, **consts):
    """JS_GEN + body, with each `__NAME__` placeholder replaced by the JSON of consts[name]."""
    for name, value in consts.items():
        body = body.replace(f"__{name}__", json.dumps(value))
    return JS_GEN + body


# ---------------------------------------------------------------------------- reference streams
# Every reference stream below decodes to an input whose length and CRC-32 appear in the goldens
# (verified against the Python generator that produced the input).
# Raw DEFLATE from Python zlib (hex): level 9, Z_SYNC_FLUSH every 400 bytes, level 6 over mixed binary.
DEFLATE_REF = {
    "text_l9": (
        "4d544b72db300cddf7143841ef9074a6eda2e9a2f14ca64bca8224d612e111297374fbbe073269378925c3c0fb01d5f6"
        "9bd425aefaf993d834c91246d9e3bc141974b25de5d536153b76c9fc50aaa170b534cba961cf321c45f262c73aca6551"
        "d4afb19455e5c862052f501dd6152342919046198d7571972d24c1bbb2ec76cc0ba727a9214b8d28ef6fe5abed12a6a2"
        "f83b87983251c534a33a9756a7a917549f7e5962961ce2281aae8b4cbb6d283eb28e52552ad926939770cad531e36123"
        "5b14819aac0123f8a1757b3ec14da1c9439d3eaa062d553194ef933e3078004ff94271aab7dc8c30c3f5469426c71d9c"
        "6b62c7242ffcae9809df84d4c5214ae7ee987f5a9589bcd3895e3b877a83bbda1dc206e0f267a70a0132ecd9e943efe6"
        "4d5c6fc0435904327789aa5cdbd0e4de7467c8f4b4435e0ffc30a66232429f7fc6d068c0039a306a6bf3dd05c7880daf"
        "9be328f44e0cd0764a180c337f7992bcc16c322b31566f8edf0204d5f1802dc1b96cd495ba114a6939f11625dc547eb4"
        "68b171b3df1e2d60d9059bcd46e6ee89a9726df0a736d3200466a69e045a71e1630b81cb8988370acee996e0424f1415"
        "f60834a91c16972002122839e386f59951285e050966ae0aed6a607dcbf8ad7cb377bee8dc834d9447e7790db4ac07ed"
        "0d95d0aed5c7f77d7217c075c4bf57b46c2b8b227a441ec40b71db6e5027a877fb98d655bdb64cd3080edf183957e842"
        "85fcd1f3b0f715d9888e5b3ca8fc39d0e682280f6743c3912e8b9be40232e96ef573bb258cb3f00b9bd8ede4ce53c1d2"
        "0ca11c8571ad113a667522716b97c73f9450709138cd379507cb3cf8be42b07bd3de8c48734c576d2187011ebda6583f"
        "5831799041d007527bde81c5b2f66bb7e8e97178a230770a1ea7ff8e40cf2621fbaefdc616a1dbbc2b38631849522677"
        "030ba5dab6b3cb41642ee3d626b7a5046f8fb847e1cdc364931f948f8b6a493f4e649c78c4da4ded279bbf5eac322add"
        "6e9afa17"
    ),
    "text_sync": (
        "2c90516ec4200c44ff7b8a39410fd14afddbafee059ce004b4c4aec02cdadbd7cee607c1f0e499f1d4f6c0cca5f2e707"
        "74db9029a1953d1b16deb4317ef560e868e871b1a90e56951d2fa6d6b10c43cf3a6ac23db3f3b59855c6e85073c169aa"
        "d52dc840929034b8d27090c035cb4dc79ec35d30a96316c72f153fda409bb19f3b15e991aac8ee74b737c77201f374bf"
        "e7d2d1a92430ad195bd3c3e1d139613266b415c58d5e58cfccfe38a2ad435e0d95dc222eef695f2fefc6be93279ff59d"
        "5ad826bb69e8c24f375ebc27be6339f31c7968c4a4f5112915e3cf3b4f8989825bfc992a4221b9961329cfee4cff0000"
        "00ffff44924b0ec2301043af92abb06381580017083494aa4aa6ea8728b7c7f64462532955e2f13c1b9eaf56c39b7b97"
        "06ad954325b0245b0036c297ce5a150036c4b33287ae2611f1863d5c9be04c2991cacb871665d393e1a6cd8e703ff070"
        "2abb85017cfec13068d8839b382497390b384664fcf6c471514a2c506e213e0d336f6a9204460b63a2c72a71bc8509d2"
        "51c13e51bb647225375ad9bd2792d8e39cc2c5ab45618fdfbe5eb04dc046b381bd3bb15562834ff5d00002334b6f02a3"
        "78f0e825104e54dc57d04e73410a38fc000000ffff3c944d0e82301085afd2b3b0f10092b81644534d43a22586dbfbbe"
        "37832b209d4cdf2f240a851d8190cab0284115245132e3c03a1085ee2949f0a02ad81560dd324ecb693df86a73061b94"
        "5bf29caf589641bb6852dac57c3dfa6417c4f5a6c7592ba3b21ac223788057e24637d049eabdfeb7a5aa73641a23b8bc"
        "11392b34a2903f9d877756a4818e164f4b796e5a332acad31e68b8d2b2d8240b48d26df510ff12e25c3858ef6cdbe93c"
        "0af63004393a71fd56e9f8594ca4b6f8f3f8a5ff000000ffff4c944b0a80300c44cfe629c4a5486abbb01115c4db3b33"
        "09e201da24f379f30522719a9a4a60b982af0ac1eecdf2336e7ab6be58841c06287aa15802ab750519076a20b52707aa"
        "9f96b4abf6280e0385d929782b3f086436b9b2ba36a145f86d3d0c3763188fa44c720385328b76a61cdc4c326e31394a"
        "89bb157145615498bc08281f51bddb87c85608b1606a229bafabdf8c4ada4d535f000000ffff0300"
    ),
    "sec_l6": (
        "ed5a5b73a24814d6f847ce0ff081e64e433783ca442b2a5542d6ca238924ba5199525c2b6f31fe312f7f6c4f4366761f"
        "f652355b197612aa04e9f65cbf733e9aa66c1c8ebbe3f3be71516fecbdc3e9743a1ff79f6a35af85a3f3f9d43a9eeabb"
        "9db76b78b546ebf47cc6f9da61dfde9d6afb9ae7a1e41e15cf17bb5abd76f26afbd67e5f7f79393e9f1bade3a17e6e9f"
        "f7ad73ad513f1d2eeaa87238e3a9f1a9753abeec6b1717e8eae2e5f8526bec3f9d5af553fb79777e3ed45ece687de043"
        "163f26f0b84cb7b09da6709b6653d8a6ab47c8668b041e56499c35a1d3eb40bac9e0168f8714b269b24e60b684758c32"
        "4fe9a609deb023a617b04cc5046cf379582709acb3384b9a30eefa432102eb69ba994f60912cc570b6c2739c099f3879"
        "972e50b4e547631fa5c508b26d0ab30ce2254696ac209eaf5310d1de26b3e54313065e0773485398a7cb8762121341db"
        "e9fd3da0683a9fa0c11b74079b354c52d8cee6735888a493f86efa35c3b1dfef437c2b924c7e436d0c7e85ea8b6fe10a"
        "178b78f9d4846004ebd9f22e81c5669dc1349e887022efca87ab6130c63c0368055117c6c1e80aa21e427c39f2bda840"
        "31b88ea085c7650051d70f7de80d21f450e626b82e50c4e9010c03318151e55fa1ef43187991ff8a228a40d80daefb1d"
        "1814c3de08cf5e247cf63b94282e536559562c45321d4d56986ab85c279430cbd26c26d994ab0aa18a29b9b6464dc3d4"
        "2c17af39535c9d499a2a5b8e22bb36d375a22a8ace4c66db8aa11ba8c4254a34dd316d8b4b86c465261b12e55c619c6a"
        "d4515c9373a6bb12531cc79115dba28ead734a5453570dcdd40cd3e44c932495714976d0b2a372ddd05ceac88ea62926"
        "61a6a9339b108c43422baecc98e1e8b6ace92a2168042f34d556552a3357d6144b553008497399cc1ceee82e275ce3d4"
        "b0b8aa6a9aa3308353664b86aecb8450894a9a23338b2a96a672453315ce54c71550c84c37508468447225ce857b9d33"
        "d7962b467c1f2320dd2ebf8a0af89a100598d80af3dfc64f98c03a3fc44d67bd41b7b798e62008238c08151742a2c0ef"
        "4e408ab9e20f4de40a029fa5703f5ba1ab028ee92add3c4c118f2798cf308bf83e4b569880170a1bf811fe26b34971ab"
        "4b9745b5b0429f237f541a4ba11d0cfc3f2a2b46108d83f749da8a2e3f8a2e25b62ef42274804b9f3f02af1f06e864fc"
        "bedaf847af3d1a61322518175198a56a54976d4b326589d854a5924b5c827e3147d9c515df716d8ede29315554a5d446"
        "6784193ac66bda5804cb712adefd04cb54b98445a1def0f2b53c5110403f185e56ecfd337b2bcabc1565caeff462b270"
        "157cfe0c61f03e7bbeead9b26ff37fb91b0101e1e60b2c660fd3ec9bad7cf799a3314db7b843f16e10bdd78a88a8733f"
        "8b7892c0af79cab34513fa1e068f966e9f60b39ca055e159642782144988324251b31c4c14dc26abe47fc13908fa9dbc"
        "2bd0d275f8be98f7d6cf8a158fbf7bed29b3c9a113c0b887e00cc49b44df6b77ab76ff9ead51d5ea1f6ec92a002f9e67"
        "72a97e2f8afa3e7c49d22f73f17c23ca93678a052c93d15f5f31e69de1b5c4ab1aff177f58115c10bc62e8bf32b4bc16"
        "155bb111aa0fbead91e8e263f7eb5bbfab337585ba127128258eeaeab4e2c29bad56257208b5863739a4616fd8f66170"
        "1d46159ffe0b9f2a3efc0d1fca6b68e87a9d9c5fc178f82a5af5f65bae1555bf97b25b298d4df97f8d72c4a3eec8f711"
        "8b9b8a58ff44ac8a0f3fe7eebd544ae1b62bcc0ff117bff0baddfd18dcfa1d"
    ),
}
# Brotli from Node's encoder: quality 1 and 11, NPOSTFIX=1/NDIRECT=4, and the mixed-binary input at q11.
BROTLI_REF = {
    "text_q1": (
        "0bf5020080aaaaaaeaff6e97131f4e76b84724c07288c843ba0104e451cc94cd44d355551c544443c1e0bfefc4bf33db"
        "0f2c6fd29e87838b8bc1c5380683c5127ec8a573d8ad3d4c9ec07f9cd69f989a0bd705769e5049e8f9d2c0ced33af1b0"
        "4ad8e870ab444c5b17146b176e4a77ec23e06aa3246cca4e941c5188e1b050f675819482a912909690ec2ecfb9a34a83"
        "0442bb8d4b1570d330c53173295f5ecff8691d72063be492dc5c1997dcae7581c7dd6cb64bc35341fcb86976b8e404ca"
        "a138bbd575c170264cc2715c9ae1536e1cba633543754caf8b3d4e14f17889a3e2edfb0d5742e59b40c0cdba60674cb2"
        "7d8bdbc66f76ec168a1fa4f02c1b5d4d2a538ea7521e0de38564b3612a1b3ebfb3c20ca7b43440434acb7fe93effd8c4"
        "e99daddda8d69b4315b979d15e8590cea259766f43e98475ec232a8e2af4305502fc66c3962b6f7090f1f1e35ccd42c1"
        "d2a568e3ab4edc36f0188722b73024b9dbf09aeb826673c5941b55124b65ff2674360954b9bb3ee6baa05a3ca824d41b"
        "b2db08fce5cb51e4bc0c1775a26a0e89cc6641083ff0d12a7ec2952d6227398eac6495d9429ec447bc52c5ed1188b6ef"
        "90a51d5a5c2fb384e1784b16c56765c76488f7aeb142a5a561a81dde8ef0d1b528c4d346b791e56b3d9b4d4fe98d7258"
        "6380a7c928691a84999fb485e19afad0788f03a26b62a02feb0add2978d4a4c9d8c22f83e7d1ce70bf7a5d1a15e5751d"
        "5219b6bff925ce8f8351fd5c335531bf198e94131ecab11d2ddea7901769eef19a8f21568d0fcd7c46a9823f7158ae43"
        "cde87d34946e37a5f4f6504795895a0a6b5d503b8126f96127fe0f0f6c66d86f45a9df161ac70ea0202aedd56ebfef93"
        "745d2a886edb5911df734f5f6c196653509c1d91659f3914ce924ccd75fcc278892d2488c78853d3aaa5d536d45163b4"
        "6547250aa6d49e9edb4164a1c5e2357e1cd4de4b6be6863033c3f0d3107fed82a9e6239f2aa7e4cf1b6f70f00b3aceea"
        "f92c828364c9ae797bfc670361b83a2530c58d2254c2b321b493639e6f24534a419962ab2db842d9bd236347ecfd15a8"
        "683b974a18974297dd4a8696e705f944336cf9a0b1a34e55f8426dae0be492dc3c309c69"
    ),
    "text_q11": (
        "1bea05001c87b1dba419ce7fa17f1009fe9b0ee75987b64bbb5470fe6a30192e0fcc1d4720b6d9b4de30b94e2904a592"
        "f58fa10005ada98e8d71114666763744f717c01238b635b242d6f8aa88d38d8fe058320ed203394100fe1130a36a3408"
        "d69f19cb7bde695d769ef1c54856577177c48541cd934eaa3d4481e2ada0b5b8a262b99828fed9e4e882110d6e9cd4e5"
        "9ff9cc2b2f1ed25dba44f159a435c22cf9a2716ee42558902e083656d2211db280f87b87af269376da58f771ef198d17"
        "ef58e2cb3a1975b14b50d07d8afdf5399500d86756b8aa24d51282d1f406223b2d4a8182e9c6093e5ae504b101bff53e"
        "fcc80c70236f0cd88810377c471dfd98e0aaeaad38b688440499738a028ec7579899f139709c926f09dafde44d4ea7c4"
        "febed4c6a172ec53dd694ad4f1539e618ea6b63aaa224d4e546cf69f8a380b79b9e12e7ab2e55f66d8443a596a5e6733"
        "aa522895516c223adf140084db051abeedb848a358be44b178d3ac37c669386e08b278c3a872c387ec08508a9b1b8670"
        "518de35555cb0dfa397934bf9c600216a8fd09e6e12b5f40c3e38d9cfef95116ea1bcc488f73a3e934b092eafaceb6df"
        "35f8f3f74c674c6109e1fd78b5c1bfeabf8a1d3b81059d6b647cc01573ff3362989d9c7e7de85c05c84666a9b5e943f6"
        "89e913265ceb78742c48ecc3061c53239eab7884493c3a616e17034e8ef0c925b679b509be27944336bf955019054c69"
        "3bfcf48e5219cb67205a95b4c6383f7ff640b522106d95bfa14c8945ee67d6fc2b5fe0ccc51914feb9575af7910a2997"
        "d82fbd19fd1b45b344602651dbf1c695578b73aa7097aa5dbf8555da57848612b43395131b5d8109f635b8c368bf8217"
        "49a59f552fb8a6c98766f4c7a46d24ec2aff2626976101"
    ),
    "text_post": (
        "1bea05201c87b1dba419ce7fa17f1009fe9b0ee75987b64bbb5470fe31c1389c0fcc1de1e07f9b4deb1ba6bf4e291c94"
        "491687a1c0f3c1a172346201c1bc7f9774cda1052cd6bc3aa4d9b6573da1102065d27b31691efdff11b8d335ea8352df"
        "80e53ddea95cee7c6ed51591fa40890b801926dd4cbb1f85116f85e6e4728aeb9571e29f4d812e2652e02c983afbb30b"
        "9ffd174fb1d34562e05c5765c42bbd4cf8344182c0b12030d65420edcf86c1df6ff82a19b333c4d6649dbacbd725f06e"
        "4d46dfea1204c6afedfecc4a0f007c83c293246a65f852f40c220b2d3d4172e9ccd94cdc54e0e3c0fc527bffc7248033"
        "45e3bf0dc9a87aef40c726b13635ef1ac7152d909c825c9f20ee2c50c0cc1fed764c5aa38ddd4bded8743decdfaaf60d"
        "5f9f31d58566241d7cdad3ca81a99d4e53c21243eb96e56712ae64dc9d7036355df98f196e44c6587779a3c5e8a69f0c"
        "a1948714becdff645704886957f38599bef22e8ac56be67c9e9f7e732fc73a18e63a34a6541c4054949715cc528b7750"
        "6d5a45c19492e7bea5e512ab185dd30dc39ff70547969c4cf9ef67e7b3f9c664c23bb629ba18a662ba69aceded1af06d"
        "aada2e3f73047367eb5707ff6eff29766e620a953723d3035486fe77830decc211d67ca17d6454200db64ca990587cb2"
        "c4858ee7ca76c43e6c404985bc41267e2a0c0f9cededea0b1c1b316f0d17f89810f4648b81b55f4a687d345bd6af957d"
        "f93a4c66f30c92359c354fecfbab0736adc9a36cca3788e195445f8156bff185585e77da04bfa7b07add299045c4dc82"
        "cd5c62fefb721e2820695de9e6b2abfb0ebd82f68e45051bd64f823622942b24e7adf1e24ca66f4134cced97efc22953"
        "523d268c25af2ee77e69d62660b7f31fdae3f12b"
    ),
    "sec_q11": (
        "1bb92a11959b2080ce04639b54eb2bf1cca5847412f29f686ece868b1d239787693068b7b531728103ca4da7f5d9b34e"
        "125b03d52b18099d0bff6d33d55ff2da8dd3294c1fcc93c3d2a787e2f9da5504a8fa7d4ed8c80827939e7db939977303"
        "b7a2fc6923840387905884506cf6bb0845211442699c45180794d9acdadfe6cb903558b289cdbd5caba34fea124d2b92"
        "d3f900e61f6f9fa13725c2420dea3c63fea372079130ab7a9a357fc85901010de999726f9f51ef92d9933e50612d09a2"
        "26087d9c7d136b717addbed07ce8c27d624ee1ce0e7edfae0ed3c4a8818343f7e3b468b9cbe7af8f8b936a5f97375a03"
        "04c6ac25790655f5ecc774d017d2f6ea1f6dcfdeb558247b686c0428b7b45bfada94ad8613fb7cd1d00fe301decb4291"
        "b93b4caee9622def09959148f0c1f4077cc1b64beeafd988c74dfed7ec3a5b8edfc758c57db3be04fbaa5c39c6b0691b"
        "236a9dacd6b010a94fe17357c71bcd9b7927418c04b224910d4cac406005fdaae0b5da90bc6387eeaffe80d173bf4f22"
        "a0cbc3be0093737ff24b57feed56ab9473cb37def76483697ca0f1dcef1f1b57c1667da78bf56022a25f29c74561ef36"
        "b818ff7b83bad6944b93aebdf2a5ffbbfe4fe50bbd00b9c91f956b44b0a90612ddfae299f252b1c764ffa5472b9047b5"
        "abd8f21abddc451c416746b47f4dc7165b863d4f7f990b27322cc904726ce3f9d5c8b86b323203cd1c2022e809f0265a"
        "3c8c39c3c4c3adcd4a70e2fa4d6985fc20989db8e5f5adf7d7cc7d146f0b4d2f42988b8a7c04bff4bbad7aeac2e6944b"
        "05f184999de9683740148b6b51c544b7ed55390b447b1090b55dd08fc8fd95090fc15ab46ef86b099766b32a1b86f068"
        "0cc79091fa4f48a541d282b7311204a5d05a6c3bd256738637da79eee165885a825dbb779d53a9f0ad1d8f5dfd66a2eb"
        "0682703b12c96435df73f5f83f8b05aaea1798a4299724fdf9735fce906246b2e29b57487f4a21eeb2a2e3e3d9e95839"
        "3dccf56ebde2b46ba96ac167bc30ab6c7bf76792aac4a2d569946c7ccf67b00d2ea4823b0aef2eb9b5db1fac757d6add"
        "40b0fb2e2a229929a8f3f3168c59f32c02b5f8ec7450cf9e9dad2b46446db48bd229b29d6f464c23db4cd3bc7de55ab4"
        "1d55921e213e84a2e22fc23b2a26d32bbfee6ec5eb71ea4f1e457ba96f9dfa8b25cf59c86ce821074935bca9214b5d5f"
        "935f1d1ed5d6dc574727eb3dd9b2816e39acaab2f1cbb7821b2ddba1be6524a655b565339a75881b3734b90b28f2eaaa"
        "34a9990aab3850b52c9da43535b1d9fcf975bf4232b48e78aa78eca2f4903fc5caaa23b8a4335885401d44ea85d7544d"
        "3591d4a86fd5cc35764ececa6b62dff9d38b62d97cfe8825a7a238e1c41e102fffc6a61d7175209af864117c5e59ddaa"
        "c7fa1ad900cc5f207d01"
    ),
}
# Brotli of one short string with lgwin 10/16/17/24 and with the large-window extension.
BROTLI_WBITS = {
    "hello_w10": "a1400100206e63ebeaf72e9f2008510ea2083ff5784e9ff0ed1b4104",
    "hello_w16": "02050080b88dadabdfbb7c822044398822fcd4e3397dc2b76f0411",
    "hello_w17": "81400100206e63ebeaf72e9f2008510ea2083ff5784e9ff0ed1b4104",
    "hello_w24": "1f280000c46d6c5dfddee5130421ca4114e1a71ecfe913be7d2388",
    "hello_large": "1159a0000010b7b175f57b974f1084280751849f7af070fa846fdf0822",
}
# Zstandard frames from the system libzstd: level 19 with checksum, level 3 over tiny alphabets / raw literals.
ZSTD_REF = {
    "text_l19": (
        "28b52ffd64eb04b516005620531b606d73906ed98d5cfcb8643bbbf51ed4fde76597ca0d2e095e021e4a004c004a0065"
        "c981de5236b10c579b3a53866113d3ebf3600181e694af83ea27533d75736a9479a027d78494ba868eeab03f0504fed2"
        "b541afd719757b63a5991cd5ca606ad3bc80801f955e23ed2fafec9da904ea230b7ead139af24a9b2766cc7e69c5134c"
        "75728d06e9f02920b0964698e859fdcad8410504d65bd3b4a0cb2874752a351e73ba02020e538e2974b0cdd960db0b7d"
        "1ef5eaf00511e5dc7716498cf96553c0fc8e9b1c5147307361cab3b4d33b8b2674051bad0857f3c10cae46f81a21d327"
        "534d0bc428f4882d5eaa51e689db6be786f523b925edab116bfaae60d8ff898c1df49e581be5e68e77d9896e0ef48792"
        "0822f7944fa6bc30e5bcead41975622e65d7944a257ba3e66b1029fd1b4d07416a65b5c65a1075e8c428a318e5d0e185"
        "0b7443ddeeb8e5070e80c6a8d1295443922425851ac3182044400861d0f51060aca803f2031778106b5b765f951626a5"
        "5d4a4b18a8304119bb037ebf98137a5749ec2812e4d042f5f758958c2e872f47f12db06193ae4fbcc7a6fb70f0120cc7"
        "567e50db9f26fd6366941651cdfac162112e23b4f440cbe89e1f85966a1de45829ed7e9d33cb9952d842f92b458308cb"
        "c5c28127d25d6d071115d4a1c1ec3a229ebc11a231f94e204a215c42b4638086f1ba56cd32c52733ba323e32983e93ba"
        "ee34e4b69fb726724eb536a9fd6c089b646b90eae4061d6a731d7cda7930bf8f6a10a22bbf4cdd637d11069ae872db40"
        "f42ae65a356a73404a212092bc11bbc1e57ec0f502870f03f7003479647e023807c95ea8817d0538c68e68ebf33c6492"
        "840cff5cf33c71087dbf2411da0095f77a8acc5e2a1bfb0cce49b46924f7731287329ea456730332898c1605c1762ff3"
        "440233fccf9e6fcddf52c620f5abe8081a973c25aa9a5658e2946e3aa94c601acd87622f855720c16d7be378201311ce"
        "66513f2330953d0d2cd4b0f815599c1a820feaf8"
    ),
    "low4_l3": (
        "28b52ffd605801a50600c2c90a830111724a3d38578147803f39faf03a162dec54d838e572f32b0f036e95b3438e545e"
        "f2e9343d9a76d60166a8612aa449b27520428220b50710c0ed373d0455f853757afa9086733fb1f1b61791fc9e8a0e8f"
        "1482a78a7850fb4e30b6d7428d6a1167c20610d9baa999ed73653ada6c69ecc840c289c2f21b39534ccc6cb4996c07c1"
        "15d42a7de5dc1db4adf135ee320abe9af2c947bb0ff4e963f8f7339e8efc239d26a7c4b38efa8e711c2e366bfa084fa8"
        "e1647ba1be3ef184e1911d5777d71d76d0972f8af69f5a0df993ab29a802"
    ),
    "rawlit_l3": (
        "28b52ffd6058018d0600840c48a1297ca7e546dcffcc765258d32b4270837d5f4e61275ae8a26816091ecc1c957de7d7"
        "f198a2c61b8c81a5c0fc174e5a7e95c6212713b963c50e597f244267a088c3d6fe1b105026108688acb3522e3c9deae9"
        "e0dd9d9b11acb3fac419511aa0b3f58611235411ca42e95605107ab993a16c5075e29ef8a0d2329224856d29d80fa66f"
        "3c3ddedd3ba97d66fc8b5b81e667f80395749e004c4bd2b73a4b374695c7e6955ad6c8c43b677e0b11f4ead6cbea5484"
        "c2adcd21dcc646f9e9ab7cdc3222b4781233db110100c8c6a56aa4"
    ),
    "abc_l3": "28b52ffd60a10e850000486162636465666768210100959f5fb8",
    "small_l3": "28b52ffd24168500005068656c6c6f207a7374640100e14a119c98df48",
}
# libzstd: level 19 without content size, RLE-heavy level 19, and a 4-block frame made with ZSTD_e_flush.
ZSTD_REF_LARGE = {
    "sec_l19": (
        "28b52ffd0420ad2700363ec52940b30e10afa2288aa2ef1b0b4ab8fb83a82e08086a6c6e2977676c4bd6b2ada5a585af"
        "46c630308f3bc500b800ae00a9f92bfaaa68fd3052862047a5aca6074d4fce57362015d30813911f9cabb97efe3c3f2f"
        "7a357d8ea1f1fd00a48ecccfa7e89f9f13b3be7a99fc0a52dfa030fc60354fcfe54f0ebabec6a38a1eb3aa935731a217"
        "a9a9e64f8db97ec84899aa13295522155a00d8125841654299028140c59a502d4810a44e80c0a90508aa14c8a60a29c0"
        "09050a522494c904605990adbeb60254a5408afdbe8aadda52813d5529520b0aaa4f50fa4a25408b02db540afcaa8ac0"
        "a2526ddb9e3e560008085812aa843a09023dc3b2cc715ce358ce17c630ce7956ee36ebd297635ee6dddbb496695b73de"
        "d5f2c6f9ea9bbb9cd3dbc6f1c658f7b28b674b77dacd5bb62cebe25ec6db20969f43c17883f8181361f995e487213936"
        "9ef118251ff90dc5876498287f44805f3ec6f20b1d0845f90bc718f94439823f46c6c6e2c3c557564cccaf1f10e74f4a"
        "8a7ede31fe60947ede939ea17362be2886110cc53c39bfd9a0a2572bff01bda4b251df62512fa9ba7955357c8c1f5c52"
        "f49cbcfad998ef5103aa07b5bc41f1913fa0702a5f92238602fa7c46a6e8cfd333963f4845ea5b9cc73bd6fbf52ed638"
        "c3b8e57517ef59d3b95f7acb7be356a7efbe1b630bc3b2cbf1dd339e3badafab6fd9eebae3ee615defb8c53d7df3b565"
        "6d79dcdad7c55d1ae30bd316877519e7d6bd18731cd3348eb5ac756775dbd319d6afaeb36ee7d7bd9a774dcbb4a6b30b"
        "d32ebc3bc6757be3b2d5755de6d7c378ef9a97bbad77e7b9f77d338b5bfd66b76f9cd6611aef1b89c283242561e84894"
        "df888c862ff125f9607c586828248d8d795787f7eef0f576c634f21d8d101282dfbae9a867e743b12c1562a2f0851f2e"
        "445111f9d1f0e4c3208e7f7a4ed17bce4a0afad1a4243ff1071c34f367c5e4483ec30f442a66c55c50ce77403f927f38"
        "8c88c628fe886828ba6ee3342ce398dbfbd2f0ee9cd7712f7b56efb087bdbbafcde16b6977e32c6ceb6be319e36d71ac"
        "7f24c5ef1d63a9f831527ec8180bef08cb43aaa215f2f39cabc54437ff980b2880c7a88111430ecdcc884892a450180e"
        "101042904267950e72d3ce1342244ee2ff474209d03ce3af68989f94f545afbbdaeabf6af03722d2992237b8da7c60aa"
        "1b89379266a3b6f862b94b60deffad17c9b8f88d457aa9955b4c2cc7ced49699acf2fc858fb6d88c9583313c44bdf53a"
        "124d2327730e603976d435f509044ba30c90ffd73544a7830d3392cbd54d6270db52349a219c821d6e47171bbcad44db"
        "a3ab3c22ef5e46cae83e84f32739575eb46eacc8003804776b4c0d75e6b69332202dea10c6851dd814a1fdc9cae484ca"
        "8a41dc220e6d28fc74308af73592dba35b6ff3f4de0fd7856bbf9df5aebab39785e0874324a20412bf69379ea8aa2844"
        "f1ec5d98e72f027eff7c7403cbce9fa490983ec62609615f8e3399d634c56d3e0a59b7646cea571a6d2c7376aedd337d"
        "af1c7222c649ad637fd525c25db73d8deb1ba815f1d0ac12370fbe9d95557890e2eb443b772934605c38d454c42cc832"
        "20f30ea12204e8035265b28405a49aceaae0e08fb77a778a478577aa893aa91a25191f54d7190be009fa1f4fe2d16c7d"
        "bd7b492a634d4306c6810df8021dac96678307d7b8520cdcf96ae63d709fa38ab1f501896df1b193c8e4db483c15f6b4"
        "8309cccea14ee894e7e9e1531d5aead2014b6ae5e78234e52ff30b75a102825c6a84"
    ),
    "rle_l19": (
        "28b52ffd60171b750400f2050a0ab0eba0e77976c39a51e5cf397b63cca5948490fd3fc6d87f21c4fe4308fb0300f657"
        "d53e11ed0353a8e16b6ced77104604be1c12f8e2f175acffff19dcb7c3ef4fcfef75397eff3ef5fc5e27c7efdfa79eb7"
        "eb72fcfe7deaf9765d8edfbf4f3d7ed7e5f8fdfba4cfefba1cbf7f1ff5fcaecbf1dbefa79edf75397eff7cb2e7777aae"
        "e3571df03b520655"
    ),
    "sec_4blocks": (
        "28b52ffd04586c1e00ea46b40d324065a88b01b45114455114071b7c13ac2c1e21de894c09b2d08a5f3f136331432d03"
        "b5dc9279be6fbf3b28016314c517402dda00cf00c400e137d7ed5bbcdced7fb9f209e5a23bf0b9db87640ec91779731b"
        "7ccee0c35f74c3f5f74aeef61b10ec8b8b6e78ae70e03fef19ccddbe5ef8be247c5ff41b058d2f36972d0bcf156f9fc1"
        "a2c3775b275c77e143fd313c3370fbd963c4106c1e9c8cc306e340302218e380a8701e340f09cd664c241cf141333206"
        "14ce88d9649c118348644684c2d930c40dc10691d130141b07cdc303421419a2838d0ec2c124360a44427406440c7344"
        "67c41088194764601b8791a170300506c36010a386316e36194c64608e33206a36e33866305181482844070d46935104"
        "cfbdeab40d83034df20d736c3f28c81cdb21d9e30d0304cd1179e6d8b20ddb22cfb2c82547d0065c83fc913936046dc0"
        "b3071639a4e05924736cd7027c43607c43d0362c3b08f0ec51b05dc08126b963d318d71c924b3488806702b02dd4df27"
        "5cf70d5e2acf0a9f07fe40fba2e1e32ad77a573478cb4537fccb05f2f74527703730c8249d02979f19b8ca29142fbc9e"
        "1cbc3c573e80f1c584a2afc11320a0ffe52efcc2a729d77a3f6b608f2f163e2f273cd4df3548e16ec9ddd61ff7ed5d87"
        "fb902c936c19e38b5cd10a9f502c3ad4a51624adb473d2289264752d966eb520e8793025590ce189afc8c2d6a5f78224"
        "c5b23e5485e875a97d9eea8122883ed134e71341b48a2ce95e7ad52ba5bcd19cd58da6e9cea94290452d7b4152841f6b"
        "ba914525be8f94d0c5d3244113243dd1f44c8ba3cab25455a96559f5ca2bba184f57b52c64f1ad185b29d14bb19424a6"
        "aac98aa069259ef59122a956d59d6e54eb33a3e85617ad16451f48dee8aa175f72ba286892260b55979caa9df5c1b692"
        "b78228ea4e3b237c49cfad14b22659a94a290d96455dd2534df67922e94eead2ca5a5a5dcf34ad6431ae2eeb5ef5a238"
        "aa2c6ccd6b5ed23eb69a924e92aa6864a187ba754e774e4bef84241ae45ac400fb41e6d83408f6ade09a647bf6d008b2"
        "8746f0836c03807d91413df126dbfbf61ec1245f58f226c03d337894377cdcbb858bb6741bb47804aef71b0558e40b3d"
        "f9d6df738553d8de1b2aff423df916d11e5fe484770a17f0ba0bc1edbd810b9fb3a5dbd7b62f182c3afc427d5a5d1747"
        "52de086379c909cd39a9145d5aedac97f55c5c27a8e207a2aa0d1b007b050e10046fa06aecfc99d5f325ea0d64e6d44a"
        "a640e383c8ac82296e41f93b79d336b548a74716d79d9c8119df2709390faac893edae002a88acada6a2a899b41cb253"
        "7c607890b4c320b38259364417e7688f791bbeed4403640700e2c71a1d50ab330643dce1e787473d21bd19a57599e7a6"
        "75554f35c46acccc98104e1edf3a29082c361b2ce6d696c28aec10660cd2f48ddbb88a8e13564307e8e24a8b79154dcd"
        "1f67b58fe9295e099a18f221e086857c34a0932ef1a6a9795cb73a27892a8db6551fa559186019262020c287a43d1e15"
        "81bc04b0a139aad1e8980c6b6ae2963fc1766d507811041859054ae78602fd5d508039e8e455c4572d1cf81a0cb6508e"
        "598256f2091e35213d166c311904d0cd8ad7488ac6dd32417bf451601ad3b460cd00811ca0ed4af07f22c1d97c82fe3b"
        "5160a14715df9add827613a0426c825315a3a004571407007285141b706975905a74e1ad99b1526511229a02d84624b6"
        "908b5ee97f78010bf990f7056578bbd7ae845dee58d59e270590c944c648093802e66eec7e787c7c15a1efc70395244a"
        "8c8985e2485c1464b9b2eec5022a20105e64ea0d572017e0056549cd342c862740d7043c262a05040a10059dea04037b"
        "4da12bbfa0f0a814b0f617c8ea03ca2727b487528043d0a8edebfc044a83606145adc6c96a674a35e0190fba2219a229"
        "0f76ef03b641e1c478a1959e020a3fa7c0500830b07714c261010c68025e7509a85c38ba5031b84db369c0717c188069"
        "6b149cbb13fcac8c62408d0300b0375448524545205741592049545357484f2053554348190063865389ef5aba5571c2"
        "72090526ecb460f0a109e8ec3c103051a8f014a64e90ab28c11c76543ab2501bbc912a80a8a284340b4440630783229b"
        "83c280f903f93f1f3ce6090a20c1a829bc9811d8ce0342bf8913c214b802825c6a84"
    ),
}
# zlib (levels 1/9/0) and gzip (plain with MTIME, FNAME, FEXTRA+FNAME+FCOMMENT+FHCRC) from Python.
ZLIB_FRAMING = {
    "zlib_l1": (
        "780125ce310e83300c05d09d53fc13708776af3a7636609140624bb169d4dbd7c0f207ebe97f6703c902a3bcc013573c"
        "7fd02ee8d9132cf138a02745e75222a087e3a3ad2cd0d00d4c7302ad94c53c68ca35788e5b65c1ca8ef7c57a58863939"
        "63a67ab6d27476dd595456b82a1e8eed30bfd7f9cb12f09a8816634c34efa847d4bf68e7f8971c85c24bd8360e7f90de"
        "46e7"
    ),
    "zlib_l9": (
        "78da258d410e83300c04efbc625fc01fda7bd563cf062c12486c29368dfafb1ab8ace4d578361b481618e5059eb8e2f9"
        "837641cf9e6089c7013d293a9712013d1c1f6d658106ddc03427d04a59cc034db9069ea3ab2c58d9f1beb01ec1302767"
        "cc544f2b4da7ebcea2b2c255f1706c87f9bdce5f9600af89b01863a279473de27ed1ce5152fc52f0126c1b873f90de46"
        "e7"
    ),
    "zlib_l0": (
        "780101cd0032ff697320616e642073616964207468656d204279206f776e2077697468207368652e0a2077686f207765"
        "6c6c207765206f757420576f726c64206f74686572206561636820616761696e73742e0a2068696d207768696368206d"
        "656e20676574204f746865722077686572652073746174652063616d652e0a2061626f75742061626f7574206c6f6e67"
        "20746f6f204174206a7573742077697468206576656e2e0a2065616368207468657365206261636b206d756368204d61"
        "6b652074686174206c617374206e657665722e0a90de46e7"
    ),
    "gz_plain": (
        "1f8b0800d20296490003258d410e83300c04efbc625fc01fda7bd563cf062c12486c29368dfafb1ab8ace4d578361b48"
        "1618e5059eb8e2f9837641cf9e6089c7013d293a9712013d1c1f6d658106ddc03427d04a59cc034db9069ea3ab2c58d9"
        "f1beb01ec1302767cc544f2b4da7ebcea2b2c255f1706c87f9bdce5f9600af89b01863a279473de27ed1ce5152fc52f0"
        "126c1b873fe9582e78cd000000"
    ),
    "gz_name": (
        "1f8b0808000000000003776f7264732e74787400258d410e83300c04efbc625fc01fda7bd563cf062c12486c29368dfa"
        "fb1ab8ace4d578361b481618e5059eb8e2f9837641cf9e6089c7013d293a9712013d1c1f6d658106ddc03427d04a59cc"
        "034db9069ea3ab2c58d9f1beb01ec1302767cc544f2b4da7ebcea2b2c255f1706c87f9bdce5f9600af89b01863a27947"
        "3de27ed1ce5152fc52f0126c1b873fe9582e78cd000000"
    ),
    "gz_all": (
        "1f8b081e00000000000306004142020068696e006120636f6d6d656e74006edd258d410e83300c04efbc625fc01fda7b"
        "d563cf062c12486c29368dfafb1ab8ace4d578361b481618e5059eb8e2f9837641cf9e6089c7013d293a9712013d1c1f"
        "6d658106ddc03427d04a59cc034db9069ea3ab2c58d9f1beb01ec1302767cc544f2b4da7ebcea2b2c255f1706c87f9bd"
        "ce5f9600af89b01863a279473de27ed1ce5152fc52f0126c1b873fe9582e78cd000000"
    ),
}

# Hand-assembled streams (hex), each checked against the reference decoder (Node brotli, libzstd, zlib).
BROTLI_HANDMADE = {
    "unc": "60001048656c6c6f2c20980008756e636f6d707265737365642062726f746c692103",
    "meta": "ac03736b69702d6d6521066800086166746572206d6574616461746103",
    "s4t1": "e2000000f4581899d8102180e6",
    "s4t0": "e2000000f41d5e9e9e10218013",
    "s3": "e2000000a45b98588810c019",
    "s2": "e2000000144c4c88108001",
    "sw": "220140440100408f8591890d110282009af303",
    "dict_transforms": "0202000004400932489aea98e0fd7076872c0900",
    "ctxmap_two_trees": "02010000a1f4ffffffffffffff27a60a2f2f7008a029",
    "metadata_last": "40001066697273742d0178797a",
    "switch_wraps": "e201404401004087898d910911028200b039b001",
    "switch_prev": "2201400401004087898d910911028200b039",
    "switch_explicit": "2201c0080600001d26364626440808028200b039",
}
BROTLI_CORRUPT = {
    "truncated": "a0011048656c6c6f2c20756e",
    "truncated_header": "a001",
    "padding": "a0013048656c6c6f2c20756e636f6d707265737365642062726f746c692103",
    "reserved": "1c03",
    "exuberant_meta": "cc0200",
    "meta_overrun": "2c6473686f7274",
    "exuberant_nibble": "c4ab0001",
    "unc_overrun": "3006106f6e6c79206120666577206279746573",
    "large_window": "9101",
    "simple_range": "620000004458a00f00000000",
    "simple_dup": "6200000054581800000000",
    "cl_corrupt": "62000000000000000000000000",
    "undersubscribed": "62000000000000080000000000",
    "cl_run_overflow": "6200000000000200000000000000000000",
    "ctxmap_overflow": "62000000b1c20200000000",
    "dict_len": "620000005498584010800000",
    "mlen_mismatch": "a2000000549858881080010000",
    "short_distance": "82000000445801824811d0000000",
    "bad_transform": "62000000445808122d011900",
}
ZSTD_HANDMADE = {
    "raw": "28b52ffd200e710000726177207a73746420626c6f636b",
    "rle_ck": "28b52ffd64e802431f007abeb69289",
    "multi": "28b52ffd041010000061622a000063110000646528b971a5",
    "fcs8": "28b52ffde40e000000000000007100006569676874206279746520666373b3e451a7",
    "concat_skip": (
        "502a4d180f00000069676e6f726564207061796c6f616428b52ffd200631000066697273742c5f2a4d180000000028b5"
        "2ffd24060a00007329000065636f6e6437005e4d"
    ),
    "lit_raw1": "28b52ffd200d7d00006874696e79206c69746572616c7300",
    "lit_rle": "28b52ffd6400131c0000a17100240000450672002d00008d3801730052666d76",
    "did0": "28b52ffd2200000c61000064696374206964207a65726f",
    "seq_rle_repeat": "28b52ffd20105c00002061626364015404020107450000207778797801fc07",
    "rep_minus_one": "28b52ffd00005c000020616263640154040201073d000000015400010003",
}
ZSTD_CORRUPT = {
    "empty": "",
    "short": "28b52f",
    "magic": "28b52ffe240529000068656c6c6fa36d9f88",
    "skip_hdr": "552a4d180100",
    "skip_payload": "5f2a4d183200000073686f7274",
    "reserved": "28b52ffd280529000068656c6c6f",
    "dict": "28b52ffd21070529000068656c6c6f",
    "hdr_trunc": "28b52ffde00500",
    "blk_trunc": "28b52ffd20052900",
    "blk_max": "28b52ffd0058090010",
    "raw_trunc": "28b52ffd200529000068656c",
    "rle_trunc": "28b52ffd20094b0000",
    "reserved_block": "28b52ffd20052f000068656c6c6f",
    "comp_trunc": "28b52ffd20054501002868656c6c6f",
    "size_mismatch": "28b52ffd200629000068656c6c6f",
    "cks_trunc": "28b52ffd240529000068656c6c6fa36d",
    "cks_bad": "28b52ffd240529000068656c6c6fa36d9fd2",
    "lit_missing": "28b52ffd2000050000",
    "lit_trunc": "28b52ffd20052500002868656c",
    "lit_huge": "28b52ffd00582d0000fdffff7800",
    "seq_missing": "28b52ffd20053500002868656c6c6f",
    "seq_trailing": "28b52ffd20054500002868656c6c6f0000",
    "treeless": "28b52ffd20053d000053400061626300",
    "modes_missing": "28b52ffd20093d00002868656c6c6f01",
    "modes_reserved": "28b52ffd20094d00002868656c6c6f010100",
    "repeat_first": "28b52ffd20094d00002868656c6c6f01fc00",
    "rle_seq_range": "28b52ffd20095500002868656c6c6f01402400",
    "bits_missing": "28b52ffd20094500002868656c6c6f0100",
    "no_sentinel": "28b52ffd00005d00002061626364015404020100",
    "bits_truncated": "28b52ffd00005d00002061626364015404050107",
    "bad_repeat": "28b52ffd00003d000000015400010003",
    "lit_overrun": "28b52ffd00004d0000106162015404020107",
    "too_far": "28b52ffd00004d0000106162015402020107",
    "not_consumed": "28b52ffd00005d0000206162636401540402010f",
}
DEFLATE_CORRUPT = {
    "eof": "4b4c",
    "too_far": "03020000",
    "lit_sym": "4b1c030000",
    "stored_trunc": "0105",
    "stored_overrun": "0164009bff6f6e6c792074686973",
    "reserved": "070000",
    "repeat_first": "050002240000",
    "bad_code": "05008000e0ff1f",
    "overrun": "050080e4ff1f0000",
}


# ---------------------------------------------------------------------------------- deflate family
@pytest.mark.parametrize("tier", TIERS)
def test_zlib_sync_roundtrip_matrix(js, golden, tier):
    """CATCHES: a codec pair that is not an exact inverse (lost tail bytes, broken back-references
    on long runs, mishandled empty input or non-ASCII bytes) or a sync wrapper that returns a
    non-Buffer, across every node:zlib family and all three execution tiers."""
    code = program(r"""
const inputs = {
  empty: Buffer.alloc(0),
  one: Buffer.from("x"),
  zeros: Buffer.alloc(3000),
  text: words(200, 11),
  noise: noise(1000, 99, 255, 0),
  utf8: Buffer.from("héllo wörld 你好 🌍 ".repeat(12)),
};
const pairs = [["deflateSync", "inflateSync"], ["deflateRawSync", "inflateRawSync"], ["gzipSync", "gunzipSync"],
  ["gzipSync", "unzipSync"], ["brotliCompressSync", "brotliDecompressSync"], ["zstdCompressSync", "zstdDecompressSync"]];
for (const [name, buf] of Object.entries(inputs)) {
  const row = [name, buf.length, crcHex(buf)];
  for (const [c, d] of pairs) {
    const comp = zlib[c](buf);
    const back = zlib[d](comp);
    row.push(`${c.replace("Sync", "")}=${comp.length}:${Buffer.isBuffer(comp) && Buffer.isBuffer(back) && back.equals(buf)}`);
  }
  console.log(row.join(" "));
}
console.log(zlib.inflateSync(zlib.deflateSync("string input")).toString(),
  zlib.gunzipSync(zlib.gzipSync(new Uint8Array([104, 105]))).toString(),
  zlib.inflateRawSync(zlib.deflateRawSync(new Uint8Array([111, 107, 33, 33]).subarray(0, 2))).toString());
""")
    r = js(code, *tier)
    assert out(r) == golden("zlib_sync_roundtrip_matrix")
    assert (r.returncode, r.stderr) == (0, b"")


def test_encoder_exact_output_bytes(js, golden):
    """CATCHES: any change to the deterministic encoders (fixed-Huffman greedy LZ77 deflate, zlib
    78 9c header + Adler-32 trailer, gzip header/CRC/ISIZE trailer, the Brotli WBITS/meta-block
    layout, the Zstandard single-segment raw/RLE frame with XXH64 checksum) on small inputs."""
    code = program(r"""
const samples = ["", "a", "hello hello hello world", "abc".repeat(30), Buffer.from(Array.from({ length: 64 }, (_, i) => i * 4)),
  "aaaaaaaaaaaaaaaaaaaaaaab"];
for (const s of samples) {
  const b = Buffer.from(s);
  console.log(b.length, "raw", zlib.deflateRawSync(b).toString("hex"));
  console.log("  zlib", zlib.deflateSync(b).toString("hex"));
  console.log("  gzip", zlib.gzipSync(b).toString("hex"));
  console.log("  br", zlib.brotliCompressSync(b).toString("hex"));
  console.log("  zstd", zlib.zstdCompressSync(b).toString("hex"));
}
""")
    r = js(code)
    assert out(r) == golden("encoder_exact_output_bytes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_inflate_reference_streams_from_zlib(js, golden):
    """CATCHES: an inflater that only understands its own fixed-Huffman output and fails on real
    zlib streams: dynamic Huffman tables, level-9 lazy matches, sync-flush empty stored blocks and
    multi-block streams over binary data produced by Python's zlib (decoded length and CRC-32)."""
    code = r"""
const zlib = require("zlib");
const REF = __REF__;
for (const [name, h] of Object.entries(REF)) {
  const comp = Buffer.from(h, "hex");
  const got = zlib.inflateRawSync(comp);
  console.log(name, comp.length, got.length, zlib.crc32(got).toString(16).padStart(8, "0"), JSON.stringify(got.subarray(0, 40).toString("latin1")));
}
""".replace("__REF__", json.dumps(DEFLATE_REF))
    r = js(code)
    assert out(r) == golden("inflate_reference_streams_from_zlib")
    assert (r.returncode, r.stderr) == (0, b"")


def test_zlib_and_gzip_framing_references(js, golden):
    """CATCHES: a zlib/gzip unwrapper that assumes its own header bytes: other CMF/FLG levels
    (78 01 / 78 da), level-0 stored blocks, gzip FNAME/FEXTRA/FCOMMENT/FHCRC optional fields and a
    non-zero MTIME must all be skipped correctly before inflating, in sync and stream form."""
    code = program(r"""
const REF = __REF__;
const SMALL = words(40, 3);
for (const [name, h] of Object.entries(REF)) {
  const comp = hex(h);
  const fn = name.startsWith("gz") ? zlib.gunzipSync : zlib.inflateSync;
  const got = fn(comp);
  console.log(name, comp.subarray(0, 4).toString("hex"), got.length, got.equals(SMALL));
}
const g = zlib.createGunzip(); const parts = [];
g.on("data", (c) => parts.push(c));
g.on("end", () => console.log("stream", Buffer.concat(parts).toString() === SMALL.toString()));
const all = hex(REF.gz_all);
g.write(all.subarray(0, 25)); g.end(all.subarray(25));
""", REF=ZLIB_FRAMING)
    r = js(code)
    assert out(r) == golden("zlib_and_gzip_framing_references")
    assert (r.returncode, r.stderr) == (0, b"")


def test_deflate_family_corrupt_input_errors(js, golden):
    """CATCHES: a decoder that returns garbage or crashes instead of throwing on malformed input:
    truncated streams, invalid literal codes, distances beyond the output, reserved block types,
    bad code-length repeats, and broken zlib/gzip headers, each with its exact message."""
    code = program(r"""
const CASES = __CASES__;
const show = (label, f) => {
  try { console.log(label, "->", JSON.stringify(f().toString())); }
  catch (e) { console.log(label, "->", e.constructor.name, JSON.stringify(e.message), e.code); }
};
for (const [name, h] of Object.entries(CASES)) show("raw " + name, () => zlib.inflateRawSync(hex(h)));
show("zlib short", () => zlib.inflateSync(hex("789c01")));
show("zlib method", () => zlib.inflateSync(hex("7f9c4b0400000000")));
show("zlib body", () => zlib.inflateSync(hex("789c070000000000")));
show("gzip magic", () => zlib.gunzipSync(Buffer.alloc(20, 0x1f)));
show("gzip short", () => zlib.gunzipSync(hex("1f8b08")));
show("gzip method", () => zlib.gunzipSync(hex("1f8b0700000000000003030000000000000000")));
show("gzip name", () => zlib.gunzipSync(hex("1f8b080800000000000361626364656667686970")));
show("unzip", () => zlib.unzipSync(Buffer.from("plain text, not gzip")));
show("type", () => zlib.deflateSync(12345));
""", CASES=DEFLATE_CORRUPT)
    r = js(code)
    assert out(r) == golden("deflate_family_corrupt_input_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_uncaught_inflate_error_exits_1(run):
    """CATCHES: a codec failure that is swallowed or printed in the wrong format; an uncaught
    inflate error must print `Uncaught Error: <codec message>` on stderr and exit with status 1
    after the output produced before it."""
    code = 'console.log("before"); require("zlib").inflateSync(Buffer.from([0x78, 0x9c, 0x07, 0, 0, 0])); console.log("after");'
    r = run(["-e", code])
    assert out(r) == "before\n"
    assert (r.returncode, err(r)) == (1, "Uncaught Error: inflate: reserved block type\n")


def test_zlib_callback_and_promisified_forms(js, golden):
    """CATCHES: async zlib entry points that call back synchronously, drop the options argument,
    pass the error in the wrong slot, or break util.promisify, checked through one sequential
    chain of deflate/inflate/gunzip/brotli/zstd callbacks ending in a process.nextTick with arguments."""
    code = r"""
const zlib = require("zlib"); const util = require("util");
const input = Buffer.from("callback form ".repeat(40));
zlib.deflate(input, (err, c) => {
  console.log("deflate cb", err, Buffer.isBuffer(c), c.length);
  zlib.inflate(c, {}, (err2, d) => {
    console.log("inflate cb", err2, d.equals(input));
    zlib.gunzip(Buffer.from("definitely not gzip data"), (err3, d3) => {
      console.log("gunzip cb", err3 instanceof Error, err3.message, d3);
      util.promisify(zlib.brotliCompress)(input, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 5 } })
        .then((b) => util.promisify(zlib.brotliDecompress)(b))
        .then((d4) => { console.log("brotli promise", d4.equals(input)); return util.promisify(zlib.zstdCompress)(input); })
        .then((zc) => { console.log("zstd promise", zlib.zstdDecompressSync(zc).toString().slice(0, 13)); return util.promisify(zlib.inflateRaw)(Buffer.from([0xff])); })
        .catch((e) => {
          console.log("rejected", e.message);
          process.nextTick((label, n) => zlib.gzip(input, (e5, g) => console.log(label, n, e5, zlib.gunzipSync(g).length)), "nextTick gzip", 42);
        });
    });
  });
});
console.log("sync code runs first");
"""
    r = js(code)
    assert out(r) == golden("zlib_callback_and_promisified_forms")
    assert (r.returncode, r.stderr) == (0, b"")


def test_zlib_transform_stream_classes(js, golden):
    """CATCHES: zlib stream classes that are not real Transform streams, lose chunk boundaries or
    the final chunk, fail to pair with their inverse in a pipeline, or never emit `error` for
    corrupt input, for every create*/class pair including Unzip."""
    code = r"""
const zlib = require("zlib"); const stream = require("stream");
const input = Buffer.from("transform stream data ".repeat(100));
const pairs = [["createGzip", "createGunzip"], ["createDeflate", "createInflate"], ["createDeflateRaw", "createInflateRaw"],
  ["createBrotliCompress", "createBrotliDecompress"], ["createZstdCompress", "createZstdDecompress"], ["createGzip", "createUnzip"]];
console.log(zlib.createGzip() instanceof zlib.Gzip, zlib.createGzip() instanceof stream.Transform, typeof zlib.BrotliCompress);
let i = 0;
function next() {
  if (i === pairs.length) return errors();
  const [c, d] = pairs[i++];
  const parts = [];
  const sink = new stream.Writable({ write(chunk, enc, cb) { parts.push(chunk); cb(); } });
  stream.pipeline(stream.Readable.from([input.subarray(0, 700), input.subarray(700), "tail"]), zlib[c](), zlib[d](), sink, (e) => {
    const all = Buffer.concat(parts);
    console.log(c, d, e, all.length, all.toString().endsWith("data tail"));
    next();
  });
}
function errors() {
  const inf = zlib.createInflate();
  inf.on("error", (e) => {
    console.log("inflate stream error:", e.message);
    const g = new zlib.Gunzip();
    g.on("error", (e2) => console.log("Gunzip class error:", e2.message));
    g.end("not gzip at all, sorry!!");
  });
  inf.end(Buffer.from([0x78, 0x9c, 0x07, 0, 0, 0]));
}
next();
"""
    r = js(code)
    assert out(r) == golden("zlib_transform_stream_classes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_crc32_and_zlib_tables(js, golden):
    """CATCHES: a wrong CRC-32 polynomial/reflection, a seed that is not continued (chained crc32 must
    equal the crc32 of the concatenation), string inputs not hashed as UTF-8, and wrong values in
    the zlib constants/codes tables."""
    code = r"""
const zlib = require("zlib");
console.log(zlib.crc32("123456789").toString(16), zlib.crc32(""), zlib.crc32("hello world"), zlib.crc32(Buffer.from("hello world")));
console.log(zlib.crc32("world", zlib.crc32("hello ")) === zlib.crc32("hello world"), zlib.crc32(new Uint8Array(1000)), zlib.crc32("héllo"));
console.log(zlib.crc32("abc", 0xffffffff), zlib.crc32("abc", -1), zlib.crc32(new Uint8Array([48, 49, 50, 51]).subarray(1)));
console.log(Bun.hash.crc32("123456789").toString(16), Bun.hash.adler32("Wikipedia").toString(16), Bun.hash.crc32("x", 99) === Bun.hash.crc32("x"));
const C = zlib.constants;
console.log(C.Z_BEST_COMPRESSION, C.Z_DEFAULT_COMPRESSION, C.BROTLI_PARAM_QUALITY, C.BROTLI_MAX_WINDOW_BITS, C.ZSTD_c_compressionLevel, C.ZSTD_e_end);
console.log(zlib.codes.Z_DATA_ERROR, zlib.codes["-3"], zlib.codes[2], Object.keys(zlib.codes).length);
"""
    r = js(code)
    assert out(r) == golden("crc32_and_zlib_tables")
    assert (r.returncode, r.stderr) == (0, b"")


def test_compression_stream_formats(js, golden):
    """CATCHES: CompressionStream/DecompressionStream that ignore the format name, cannot
    reassemble input split across writes, accept unsupported formats, or resolve instead of
    erroring on corrupt gzip data."""
    code = r"""
async function collect(readable) {
  const reader = readable.getReader(); const parts = [];
  for (;;) { const { done, value } = await reader.read(); if (done) break; parts.push(Buffer.from(value)); }
  return Buffer.concat(parts);
}
(async () => {
  const text = "CompressionStream round trip, ".repeat(20);
  for (const fmt of ["gzip", "deflate", "deflate-raw"]) {
    const c = await collect(new Blob([text]).stream().pipeThrough(new CompressionStream(fmt)));
    const d = await collect(new Blob([c]).stream().pipeThrough(new DecompressionStream(fmt)));
    console.log(fmt, c.length, c.subarray(0, 3).toString("hex"), d.toString() === text);
  }
  try { new CompressionStream("brotli"); } catch (e) { console.log(e.name, e.message); }
  try { await collect(new Blob([new Uint8Array([1, 2, 3])]).stream().pipeThrough(new DecompressionStream("gzip"))); }
  catch (e) { console.log(e.name, e.message); }
  const ds = new DecompressionStream("deflate");
  const w = ds.writable.getWriter(); const comp = require("zlib").deflateSync(Buffer.from("chunked input"));
  w.write(comp.subarray(0, 5)); w.write(comp.subarray(5)); w.close();
  console.log((await collect(ds.readable)).toString());
})();
"""
    r = js(code)
    assert out(r) == golden("compression_stream_formats")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------------- brotli
def test_brotli_reference_streams(js, golden):
    """CATCHES: a Brotli decoder missing pieces of RFC 7932 that real encoders use: complex prefix
    codes, literal/distance context modeling, block switching, NPOSTFIX/NDIRECT distance codes, and
    static-dictionary references with word transforms (Node output at qualities 1 and 11)."""
    code = r"""
const zlib = require("zlib");
const REF = __REF__;
for (const [name, h] of Object.entries(REF)) {
  const comp = Buffer.from(h, "hex");
  const got = zlib.brotliDecompressSync(comp);
  console.log(name, comp.length, got.length, zlib.crc32(got).toString(16).padStart(8, "0"), JSON.stringify(got.subarray(0, 40).toString("latin1")));
}
""".replace("__REF__", json.dumps(BROTLI_REF))
    r = js(code)
    assert out(r) == golden("brotli_reference_streams")
    assert (r.returncode, r.stderr) == (0, b"")


def test_brotli_window_bits_variants(js, golden):
    """CATCHES: mis-parsing the variable-length WBITS stream header (16, 17, 18-24 and 10-15 bit
    windows encode differently) or silently accepting a large-window stream instead of rejecting it
    with the documented error."""
    code = r"""
const zlib = require("zlib");
const REF = __REF__;
for (const [name, h] of Object.entries(REF)) {
  const comp = Buffer.from(h, "hex");
  try { console.log(name, h.slice(0, 4), JSON.stringify(zlib.brotliDecompressSync(comp).toString())); }
  catch (e) { console.log(name, h.slice(0, 4), e.message); }
}
""".replace("__REF__", json.dumps(BROTLI_WBITS))
    r = js(code)
    assert out(r) == golden("brotli_window_bits_variants")
    assert (r.returncode, r.stderr) == (0, b"")


def test_brotli_handmade_streams(js, golden):
    """CATCHES: a Brotli decoder that mishandles meta-block kinds encoders rarely emit: uncompressed
    and metadata meta-blocks, simple prefix codes with 2/3/4 symbols (both tree-select shapes),
    command block-type switching, and static-dictionary words with omit-first and UTF-8 uppercase
    transforms; streams were hand-assembled and checked with the reference decoder."""
    code = program(r"""
const CASES = __CASES__;
for (const [name, h] of Object.entries(CASES)) console.log(name, JSON.stringify(zlib.brotliDecompressSync(hex(h)).toString()));
console.log("minimal", JSON.stringify(zlib.brotliDecompressSync(hex("06")).toString()), JSON.stringify(zlib.brotliDecompressSync(hex("3f")).toString()));
""", CASES=BROTLI_HANDMADE)
    r = js(code)
    assert out(r) == golden("brotli_handmade_streams")
    assert (r.returncode, r.stderr) == (0, b"")


def test_brotli_corrupt_streams(js, golden):
    """CATCHES: a Brotli decoder that accepts invalid streams (non-zero padding, reserved bits,
    exuberant size nibbles, out-of-range or duplicate simple-code symbols, over/under-subscribed
    prefix codes, context-map overruns, bad dictionary lengths) instead of failing with a precise error."""
    code = program(r"""
const CASES = __CASES__;
for (const [name, h] of Object.entries(CASES)) {
  try { console.log(name, "decoded", zlib.brotliDecompressSync(hex(h)).length); }
  catch (e) { console.log(name, e.constructor.name, e.message); }
}
""", CASES=BROTLI_CORRUPT)
    r = js(code)
    assert out(r) == golden("brotli_corrupt_streams")
    assert (r.returncode, r.stderr) == (0, b"")


def test_brotli_encoder_shapes_roundtrip(js, golden):
    """CATCHES: a Brotli encoder that expands incompressible data instead of falling back to
    uncompressed meta-blocks, mis-codes inputs with at most four distinct bytes, a uniform 8-symbol
    alphabet or a Fibonacci distribution that needs length-limited (15-bit) codes, or produces
    streams its own decoder cannot read back."""
    code = program(r"""
// 19 symbols with Fibonacci frequencies: an unconstrained Huffman code would need 18-bit codes.
const counts = [1, 1]; while (counts.length < 19) counts.push(counts[counts.length - 1] + counts[counts.length - 2]);
const fib = Buffer.alloc(counts.reduce((x, y) => x + y));
for (let i = 0, off = 0; i < counts.length; off += counts[i], i++) fib.fill(0x41 + i, off, off + counts[i]);
const inputs = [["empty", Buffer.alloc(0)], ["two-symbols", Buffer.from("abba".repeat(500))], ["four", noise(3000, 5, 3, 0x61)],
  ["text", words(1200, 3)], ["noise", noise(3000, 8, 255, 0)], ["mixed", Buffer.concat([words(300, 4), noise(1000, 6, 255, 0)])],
  ["byte", Buffer.from([7])], ["uniform8", Buffer.from(Array.from({ length: 800 }, (_, i) => (i * 5) % 8))], ["fibonacci", fib]];
for (const [name, buf] of inputs) {
  const c = zlib.brotliCompressSync(buf);
  console.log(name, buf.length, c.length, c.subarray(0, 4).toString("hex"), zlib.brotliDecompressSync(c).equals(buf));
}
""")
    r = js(code)
    assert out(r) == golden("brotli_encoder_shapes_roundtrip")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------------ zstd
def test_zstd_reference_frames(js, golden):
    """CATCHES: a Zstandard decoder that cannot read real libzstd frames: FSE-coded sequence tables,
    Huffman literals with direct (tiny alphabet) or FSE-compressed weights in 1 or 4 streams, raw
    literal sections with 2-byte headers, long matches and XXH64 content checksums."""
    code = r"""
const zlib = require("zlib");
const REF = __REF__;
for (const [name, h] of Object.entries(REF)) {
  const comp = Buffer.from(h, "hex");
  const got = zlib.zstdDecompressSync(comp);
  console.log(name, comp.length, got.length, zlib.crc32(got).toString(16).padStart(8, "0"), JSON.stringify(got.subarray(0, 24).toString("latin1")));
}
""".replace("__REF__", json.dumps(ZSTD_REF))
    r = js(code)
    assert out(r) == golden("zstd_reference_frames")
    assert (r.returncode, r.stderr) == (0, b"")


def test_zstd_multi_block_and_rle_reference_frames(js, golden):
    """CATCHES: Zstandard state not carried across blocks of one frame (the later blocks of the
    4-block frame reuse the previous Huffman table, repeat-mode sequence tables and repeat offsets),
    long runs of short matches (RLE-heavy input), two-byte sequence counts, and frames without a
    content size."""
    code = r"""
const zlib = require("zlib");
const REF = __REF__;
for (const [name, h] of Object.entries(REF)) {
  const comp = Buffer.from(h, "hex");
  const got = zlib.zstdDecompressSync(comp);
  console.log(name, comp.length, got.length, zlib.crc32(got).toString(16).padStart(8, "0"), JSON.stringify(got.subarray(0, 24).toString("latin1")));
}
""".replace("__REF__", json.dumps(ZSTD_REF_LARGE))
    r = js(code)
    assert out(r) == golden("zstd_multi_block_and_rle_reference_frames")
    assert (r.returncode, r.stderr) == (0, b"")


def test_zstd_handmade_frames(js, golden):
    """CATCHES: frame-header and block parsing bugs: 1/2/4/8-byte content sizes (the 2-byte form is
    offset by 256), window descriptors, zero dictionary ids, raw/RLE/compressed blocks, skippable and
    concatenated frames, raw literal headers of 1-3 bytes, RLE literal sections, RLE-mode
    sequence tables reused through repeat mode in the next block, and the "offset 3 with no
    literals" repeat code (previous offset minus one) using history from an earlier block."""
    code = program(r"""
const CASES = __CASES__;
const pat = (n) => Buffer.from(Array.from({ length: n }, (_, i) => (i * 7 + 3) & 255));
const T = pat(300);
const built = {
  fcs2: Buffer.concat([hex("28b52ffd602c00610900"), T]),
  fcs4: Buffer.concat([hex("28b52ffd80082c010000200300"), T.subarray(0, 100), hex("410600"), T.subarray(100)]),
  lit_raw2: Buffer.concat([hex("28b52ffd00005d0600840c"), T.subarray(0, 200), hex("00")]),
  lit_raw3: Buffer.concat([hex("28b52ffd609410c58c004c1901"), Buffer.concat(Array(15).fill(T)), hex("00")]),
};
for (const [name, h] of Object.entries(CASES)) console.log(name, JSON.stringify(zlib.zstdDecompressSync(hex(h)).toString()).slice(0, 70));
for (const [name, frame] of Object.entries(built)) {
  const got = zlib.zstdDecompressSync(frame);
  console.log(name, frame.length, got.length, crcHex(got), got.equals(pat(got.length)) || got.equals(Buffer.concat(Array(15).fill(T))));
}
""", CASES=ZSTD_HANDMADE)
    r = js(code)
    assert out(r) == golden("zstd_handmade_frames")
    assert (r.returncode, r.stderr) == (0, b"")


def test_zstd_corrupt_frames(js, golden):
    """CATCHES: a Zstandard decoder that accepts malformed frames (bad magic, reserved bits,
    dictionary ids, oversized or truncated blocks, content-size and checksum mismatches, broken
    literal/sequence section headers, repeat modes without history, sequence bitstreams without a
    sentinel, truncated or not fully consumed, bad repeat offsets, literal overruns, offsets beyond
    the output) instead of failing precisely."""
    code = program(r"""
const CASES = __CASES__;
for (const [name, h] of Object.entries(CASES)) {
  try { console.log(name, "decoded", zlib.zstdDecompressSync(hex(h)).length); }
  catch (e) { console.log(name, e.constructor.name, e.message); }
}
""", CASES=ZSTD_CORRUPT)
    r = js(code)
    assert out(r) == golden("zstd_corrupt_frames")
    assert (r.returncode, r.stderr) == (0, b"")


def test_zstd_encoder_frames_and_bun_api(js, golden):
    """CATCHES: a Zstandard encoder choosing the wrong frame-content-size width at the 255/256 and
    65791/65792 boundaries, not splitting at 128 KB blocks, not using RLE blocks for uniform chunks,
    plus Bun.zstd*/Bun.gzipSync helpers returning the wrong type or failing to round-trip."""
    code = program(r"""
for (const n of [0, 3, 5, 255, 256, 2000]) {
  const buf = n === 5 ? Buffer.alloc(5, 0x41) : noise(n, n, 255, 0);
  const c = zlib.zstdCompressSync(buf);
  console.log(n, c.length, c.subarray(0, 14).toString("hex"), zlib.zstdDecompressSync(c).equals(buf));
}
for (const n of [65791, 65792, 131072, 131075]) {
  const buf = Buffer.alloc(n, 0x5a);
  if (n === 131075) buf[131073] = 0x21;
  console.log(n, zlib.zstdCompressSync(buf).toString("hex"));
}
const u = Bun.zstdCompressSync("bun zstd helper");
console.log(u.constructor.name, Buffer.from(Bun.zstdDecompressSync(u)).toString());
const g = Bun.gzipSync("bun gzip helper"), d = Bun.deflateSync(new TextEncoder().encode("bun deflate helper"));
console.log(g.constructor.name, Buffer.from(Bun.gunzipSync(g)).toString(), Buffer.from(Bun.inflateSync(d)).toString());
Bun.zstdCompress("async zstd").then((c) => Bun.zstdDecompress(c)).then((d) => console.log("async", Buffer.from(d).toString()));
""")
    r = js(code)
    assert out(r) == golden("zstd_encoder_frames_and_bun_api")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------------ crypto
@pytest.mark.parametrize("tier", TIERS)
def test_hash_known_vectors_all_algorithms(js, golden, tier):
    """CATCHES: a wrong digest for any supported algorithm (md5, sha1, sha256, and the native
    SHA-512 family incl. sha384/sha512-224/sha512-256) at padding boundaries (55/56, 111/112,
    127/128 bytes), on multi-block input, on UTF-8 strings, or via the alias names."""
    code = r"""
const crypto = require("crypto");
const algs = ["md5", "sha1", "sha256", "sha384", "sha512", "sha512-224", "sha512-256", "SHA-256"];
const inputs = ["", "abc", "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", "a".repeat(55), "a".repeat(56),
  "a".repeat(111), "a".repeat(112), "a".repeat(128), "é😀"];
for (const a of algs) {
  console.log(a);
  for (const s of inputs) console.log(" ", s.length, crypto.createHash(a).update(s).digest("hex"));
}
"""
    r = js(code, *tier)
    assert out(r) == golden("hash_known_vectors_all_algorithms")
    assert (r.returncode, r.stderr) == (0, b"")


def test_hash_encodings_copy_and_errors(js, golden):
    """CATCHES: digest output encodings (base64, base64url, latin1, buffer) or input encodings
    (hex/base64/latin1, TypedArray/DataView/ArrayBuffer) handled wrongly, copy() sharing state with
    its source, and missing exact errors for double digest and unsupported algorithms."""
    code = r"""
const crypto = require("crypto");
const h = crypto.createHash("sha256").update("ab");
const c = h.copy();
h.update("c"); c.update("x");
console.log(h.digest("hex"));
console.log(c.digest("base64"));
const d = crypto.createHash("md5").update("616263", "hex").update("ZGVm", "base64").update("ghé", "latin1");
console.log(d.digest("base64url"));
console.log(JSON.stringify(crypto.createHash("sha1").update("abc").digest("latin1")));
const buf = crypto.createHash("sha512-256").update(new Uint16Array([0x6261, 0x63])).digest();
console.log(Buffer.isBuffer(buf), buf.length, buf.toString("hex"));
const u8 = new Uint8Array([0, 97, 98, 99, 0]);
console.log(crypto.createHash("sha1").update(new DataView(u8.buffer, 1, 3)).digest("hex") === crypto.createHash("sha1").update(u8.subarray(1, 4)).digest("hex"));
console.log(crypto.hash("sha1", "abc"), crypto.hash("md5", "abc", "base64"), crypto.hash("sha256", "", "buffer").length);
console.log(crypto.getHashes().join(","));
for (const f of [() => crypto.createHash("whirlpool"), () => { const x = crypto.createHash("md5"); x.digest(); x.digest(); },
  () => crypto.createHmac("sha3-256", "k"), () => crypto.createHash("sha1").update(42)]) {
  try { f(); console.log("no error"); } catch (e) { console.log(e.name, e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("hash_encodings_copy_and_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_hmac_rfc_vectors(js, golden):
    """CATCHES: HMAC with the wrong block size for the SHA-512 family (128 vs 64 bytes), keys longer
    than a block not hashed first, or chunked update() not equal to a single update, checked with the
    RFC 2202 / RFC 4231 test cases for every digest and a KeyObject key."""
    code = r"""
const crypto = require("crypto");
const k1 = Buffer.alloc(20, 0x0b), k6 = Buffer.alloc(131, 0xaa);
for (const a of ["md5", "sha1", "sha256", "sha384", "sha512", "sha512-224", "sha512-256"]) {
  console.log(a);
  console.log(" ", crypto.createHmac(a, k1).update("Hi There").digest("hex"));
  console.log(" ", crypto.createHmac(a, "Jefe").update("what do ya want ").update("for nothing?").digest("base64"));
  console.log(" ", crypto.createHmac(a, k6).update("Test Using Larger Than Block-Size Key - Hash Key First").digest("hex"));
}
const key = crypto.createSecretKey(Buffer.from("secret-key-bytes"));
console.log(key.type, key.symmetricKeySize, JSON.stringify(key.export({ format: "jwk" })), key.equals(crypto.createSecretKey("secret-key-bytes")));
console.log(crypto.createHmac("sha256", key).update("data").digest("hex"));
console.log(crypto.createHmac("sha1", "").update("").digest("hex"));
"""
    r = js(code)
    assert out(r) == golden("hmac_rfc_vectors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_pbkdf2_and_hkdf_vectors(js, golden):
    """CATCHES: PBKDF2 block indexing/XOR-accumulation bugs (multi-block keys, odd lengths, NUL bytes
    in password/salt), HKDF extract/expand mistakes or empty-salt handling (RFC 6070 / RFC 5869
    vectors), and the callback forms reporting results or argument errors in the wrong order."""
    code = r"""
const crypto = require("crypto");
const hx = (b) => Buffer.from(b).toString("hex");
console.log(hx(crypto.pbkdf2Sync("password", "salt", 1, 20, "sha1")));
console.log(hx(crypto.pbkdf2Sync("password", "salt", 2, 20, "sha1")));
console.log(hx(crypto.pbkdf2Sync("passwordPASSWORDpassword", "saltSALTsaltSALTsaltSALTsaltSALTsalt", 4, 25, "sha1")));
console.log(hx(crypto.pbkdf2Sync("passwd", "salt", 1, 64, "sha256")));
console.log(hx(crypto.pbkdf2Sync(Buffer.from("pass\0word"), Buffer.from("sa\0lt"), 3, 70, "sha512")));
console.log(hx(crypto.pbkdf2Sync("p", "s", 2, 50, "sha384")));
const ikm = Buffer.alloc(22, 0x0b), salt = Buffer.from("000102030405060708090a0b0c", "hex"), info = Buffer.from("f0f1f2f3f4f5f6f7f8f9", "hex");
const okm = crypto.hkdfSync("sha256", ikm, salt, info, 42);
console.log(okm instanceof ArrayBuffer, hx(okm));
console.log(hx(crypto.hkdfSync("sha1", ikm, "", "", 42)));
console.log(hx(crypto.hkdfSync("sha512", "key", "salt", "info", 10)));
try { crypto.hkdfSync("sha256", "k", "s", "i", 255 * 32 + 1); } catch (e) { console.log(e.name, e.message); }
try { crypto.pbkdf2Sync("a", "b", 1, 10); } catch (e) { console.log(e.name, e.message); }
crypto.pbkdf2("password", "salt", 2, 16, "sha256", (err, key) => {
  console.log("pbkdf2 cb", err, hx(key));
  crypto.hkdf("md5", "ikm", "salt", "info", 20, (err2, k2) => {
    console.log("hkdf cb", err2, hx(k2));
  });
});
"""
    r = js(code)
    assert out(r) == golden("pbkdf2_and_hkdf_vectors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_scrypt_vectors_and_param_validation(js, golden):
    """CATCHES: a wrong scrypt ROMix/BlockMix (the RFC 7914 N=16 vector plus Node-checked r=2/p=2 and
    r=1/p=3 outputs), ignored
    alias options (cost/blockSize/parallelization), and missing exact validation errors for a
    non-power-of-two N, conflicting aliases, the memory limit and bad keylen types."""
    code = r"""
const crypto = require("crypto");
console.log(crypto.scryptSync("", "", 64, { N: 16, r: 1, p: 1 }).toString("hex"));
console.log(crypto.scryptSync("password", "NaCl", 32, { N: 64, r: 2, p: 2 }).toString("hex"));
console.log(crypto.scryptSync("pw", "salt", 16, { cost: 32, blockSize: 1, parallelization: 3 }).toString("hex"));
console.log(crypto.scryptSync(Buffer.from("pw"), Buffer.from("salt"), 24, { N: 16, r: 2, maxmem: 1 << 20 }).toString("base64"));
const bad = [{ N: 3 }, { N: 16, cost: 16 }, { N: 1 << 20, r: 8 }, { N: 1.5 }, { r: -1 }, { p: "2" }];
for (const o of bad) {
  try { crypto.scryptSync("a", "b", 16, o); console.log("accepted", JSON.stringify(o)); }
  catch (e) { console.log(JSON.stringify(o), e.name, e.code, e.message); }
}
for (const k of ["x", 1.5, -1]) {
  try { crypto.scryptSync("a", "b", k, { N: 16 }); } catch (e) { console.log(JSON.stringify(k), e.name, e.code, e.message); }
}
crypto.scrypt("pw", "salt", 8, { N: 32, r: 1 }, (e, key) => console.log("scrypt cb", e, key.toString("hex")));
"""
    r = js(code)
    assert out(r) == golden("scrypt_vectors_and_param_validation")
    assert (r.returncode, r.stderr) == (0, b"")


def test_aes_block_modes_sp800_38a_vectors(js, golden):
    """CATCHES: wrong AES-128/192/256 key schedules or ECB/CBC/CTR mode chaining, and streaming
    update() calls that mishandle partial blocks or the CBC IV carried between chunks, using the
    NIST SP 800-38A vectors encrypted 7 bytes at a time and decrypted 13 bytes at a time."""
    code = r"""
const crypto = require("crypto");
const hx = (s) => Buffer.from(s, "hex");
function run(alg, key, iv, input, step, decipher) {
  const c = decipher ? crypto.createDecipheriv(alg, key, iv) : crypto.createCipheriv(alg, key, iv);
  if (alg.endsWith("ecb") || alg.endsWith("cbc")) c.setAutoPadding(false);
  const parts = [];
  for (let i = 0; i < input.length; i += step) parts.push(c.update(input.subarray(i, i + step)));
  parts.push(c.final());
  return Buffer.concat(parts);
}
const pt = hx("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e5130c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710");
const keys = { 128: hx("2b7e151628aed2a6abf7158809cf4f3c"), 192: hx("8e73b0f7da0e6452c810f32b809079e562f8ead2522c6b7b"),
  256: hx("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4") };
const iv = hx("000102030405060708090a0b0c0d0e0f"), ctrIv = hx("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff");
for (const bits of [128, 192, 256]) {
  for (const mode of ["ecb", "cbc", "ctr"]) {
    const alg = `aes-${bits}-${mode}`;
    const v = mode === "ecb" ? null : mode === "ctr" ? ctrIv : iv;
    const ct = run(alg, keys[bits], v, pt, 7, false);
    console.log(alg, ct.toString("hex"), run(alg, keys[bits], v, ct, 13, true).equals(pt));
  }
}
"""
    r = js(code)
    assert out(r) == golden("aes_block_modes_sp800_38a_vectors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_aes_padding_counters_and_encodings(js, golden):
    """CATCHES: PKCS#7 padding bugs at 0/15/16/17/31/33-byte inputs, a CTR counter that does not
    carry across all 128 bits (IV ff..ff), autoPadding(false) on aligned data, string/encoding
    handling in update()/final(), and the aes128/aes256 aliases."""
    code = r"""
const crypto = require("crypto");
const key = Buffer.from("000102030405060708090a0b0c0d0e0f", "hex"), iv = Buffer.alloc(16, 0x24);
const pt = Buffer.from("The quick brown fox jumps over the lazy dog!");
for (const n of [0, 1, 15, 16, 17, 31, 33]) {
  const c = crypto.createCipheriv("aes-128-cbc", key, iv);
  const ct = Buffer.concat([c.update(pt.subarray(0, n)), c.final()]);
  const d = crypto.createDecipheriv("aes-128-cbc", key, iv);
  console.log(n, ct.length, ct.toString("base64"), Buffer.concat([d.update(ct), d.final()]).equals(pt.subarray(0, n)));
}
const top = Buffer.alloc(16, 0xff);
const ctr = crypto.createCipheriv("aes-256-ctr", Buffer.alloc(32, 7), top);
console.log("ctr wrap", ctr.update(Buffer.alloc(40)).toString("hex"), ctr.final().length);
const ecb = crypto.createCipheriv("aes-192-ecb", Buffer.alloc(24, 9), null).setAutoPadding(false);
console.log("ecb nopad", ecb.update(Buffer.alloc(32, 3), undefined, "hex") + ecb.final("hex"));
const s = crypto.createCipheriv("aes-192-ctr", Buffer.alloc(24, 5), iv);
const b64 = s.update("héllo wörld", "utf8", "base64") + s.final("base64");
const u = crypto.createDecipheriv("aes-192-ctr", Buffer.alloc(24, 5), iv);
console.log("ctr text", b64, u.update(b64, "base64", "utf8") + u.final("utf8"));
for (const alias of ["aes128", "AES256"]) {
  const k = Buffer.alloc(alias.endsWith("128") ? 16 : 32, 1);
  const c = crypto.createCipheriv(alias, k, iv);
  const d = crypto.createCipheriv(alias.endsWith("128") ? "aes-128-cbc" : "aes-256-cbc", k, iv);
  console.log(alias, Buffer.concat([c.update("alias"), c.final()]).equals(Buffer.concat([d.update("alias"), d.final()])));
}
"""
    r = js(code)
    assert out(r) == golden("aes_padding_counters_and_encodings")
    assert (r.returncode, r.stderr) == (0, b"")


def test_aes_gcm_vectors_aad_and_tags(js, golden):
    """CATCHES: GCM bugs: wrong GHASH/tag with AAD (McGrew-Viega test case 4 for all key sizes),
    96-bit vs non-96-bit IVs (J0 derivation), truncated authTagLength, empty plaintext tags, and
    decryption that does not authenticate before final()."""
    code = r"""
const crypto = require("crypto");
const hx = (s) => Buffer.from(s, "hex");
const gk = hx("feffe9928665731c6d6a8f9467308308"), giv = hx("cafebabefacedbaddecaf888");
const gpt = hx("d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a721c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39");
const aad = hx("feedfacedeadbeeffeedfacedeadbeefabaddad2");
for (const [bits, key] of [[128, gk], [192, Buffer.concat([gk, gk.subarray(0, 8)])], [256, Buffer.concat([gk, gk])]]) {
  const c = crypto.createCipheriv(`aes-${bits}-gcm`, key, giv);
  c.setAAD(aad);
  const ct = Buffer.concat([c.update(gpt.subarray(0, 20)), c.update(gpt.subarray(20, 23)), c.update(gpt.subarray(23)), c.final()]);
  const tag = c.getAuthTag();
  const d = crypto.createDecipheriv(`aes-${bits}-gcm`, key, giv);
  d.setAAD(aad); d.setAuthTag(tag);
  const back = Buffer.concat([d.update(ct.subarray(0, 9)), d.update(ct.subarray(9)), d.final()]);
  console.log(bits, ct.toString("hex"), tag.toString("hex"), back.equals(gpt));
}
for (const ivh of ["cafebabefacedbad", "9313225df88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a721c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39"]) {
  const c = crypto.createCipheriv("aes-128-gcm", gk, hx(ivh), { authTagLength: 12 });
  c.setAAD(aad);
  const ct = Buffer.concat([c.update(gpt), c.final()]);
  console.log("iv" + ivh.length / 2, ct.subarray(0, 16).toString("hex"), c.getAuthTag().toString("hex"));
}
const e0 = crypto.createCipheriv("aes-256-gcm", Buffer.alloc(32), Buffer.alloc(12));
console.log("empty", e0.final().length, e0.getAuthTag().toString("hex"));
const z = crypto.createCipheriv("aes-128-gcm", Buffer.alloc(16), Buffer.alloc(12));
console.log("nist tc2", Buffer.concat([z.update(Buffer.alloc(16)), z.final()]).toString("hex"), z.getAuthTag().toString("hex"));
"""
    r = js(code)
    assert out(r) == golden("aes_gcm_vectors_aad_and_tags")
    assert (r.returncode, r.stderr) == (0, b"")


def test_cipher_misuse_errors(js, golden):
    """CATCHES: missing or wrong errors (class, code and message) for unsupported ciphers, bad key or
    IV lengths, invalid GCM tag lengths, bad PKCS#7 padding, misaligned final blocks, a forged GCM
    tag, and state misuse such as update after final or getAuthTag before final."""
    code = r"""
const crypto = require("crypto");
const t = (label, f) => { try { const r = f(); console.log(label, "OK", r === undefined ? "" : String(r)); } catch (e) { console.log(label, e.name, e.code, e.message); } };
const k16 = Buffer.alloc(16, 1), iv = Buffer.alloc(16, 2), n12 = Buffer.alloc(12);
t("badalg", () => crypto.createCipheriv("aes-128-xts", k16, iv));
t("keylen", () => crypto.createCipheriv("aes-256-cbc", k16, iv));
t("ivlen", () => crypto.createCipheriv("aes-128-cbc", k16, Buffer.alloc(8)));
t("ctr noiv", () => crypto.createCipheriv("aes-128-ctr", k16, null));
t("ecbiv", () => crypto.createCipheriv("aes-128-ecb", k16, iv));
t("gcmempty", () => crypto.createCipheriv("aes-128-gcm", k16, Buffer.alloc(0)));
t("taglen", () => crypto.createCipheriv("aes-128-gcm", k16, n12, { authTagLength: 7 }));
t("badpad", () => { const d = crypto.createDecipheriv("aes-128-cbc", k16, iv); d.update(Buffer.alloc(16, 9)); return d.final(); });
t("wronglen", () => { const d = crypto.createDecipheriv("aes-128-cbc", k16, iv); d.update(Buffer.alloc(20, 9)); return d.final(); });
t("nopad", () => { const c = crypto.createCipheriv("aes-128-cbc", k16, iv); c.setAutoPadding(false); c.update(Buffer.alloc(10)); return c.final(); });
t("nopaddec", () => { const d = crypto.createDecipheriv("aes-128-ecb", k16, null); d.setAutoPadding(false); d.update(Buffer.alloc(20)); return d.final(); });
t("twofinal", () => { const c = crypto.createCipheriv("aes-128-ctr", k16, iv); c.final(); c.final(); });
t("updafter", () => { const c = crypto.createCipheriv("aes-128-ctr", k16, iv); c.final(); c.update("x"); });
t("tagbefore", () => crypto.createCipheriv("aes-128-gcm", k16, n12).getAuthTag());
t("tagcbc", () => { const c = crypto.createCipheriv("aes-128-cbc", k16, iv); c.final(); return c.getAuthTag(); });
t("wrongtag", () => {
  const c = crypto.createCipheriv("aes-128-gcm", k16, n12); const ct = Buffer.concat([c.update("secret"), c.final()]);
  const tag = c.getAuthTag(); tag[0] ^= 1;
  const d = crypto.createDecipheriv("aes-128-gcm", k16, n12); d.setAuthTag(tag); d.update(ct); return d.final();
});
t("wrongaad", () => {
  const c = crypto.createCipheriv("aes-128-gcm", k16, n12); c.setAAD(Buffer.from("A")); const ct = Buffer.concat([c.update("secret"), c.final()]);
  const d = crypto.createDecipheriv("aes-128-gcm", k16, n12); d.setAAD(Buffer.from("B")); d.setAuthTag(c.getAuthTag()); d.update(ct); return d.final();
});
t("notag", () => { const d = crypto.createDecipheriv("aes-128-gcm", k16, n12); d.update("abc"); return d.final(); });
t("badtaglen", () => crypto.createDecipheriv("aes-128-gcm", k16, n12).setAuthTag(Buffer.alloc(3)));
t("fixedtaglen", () => crypto.createDecipheriv("aes-128-gcm", k16, n12, { authTagLength: 8 }).setAuthTag(Buffer.alloc(16)));
t("tagafter", () => { const d = crypto.createDecipheriv("aes-128-gcm", k16, n12); d.setAuthTag(Buffer.alloc(16)); try { d.final(); } catch (e) {} d.setAuthTag(Buffer.alloc(16)); });
t("aadlate", () => { const c = crypto.createCipheriv("aes-128-gcm", k16, n12); c.update("x"); c.setAAD(Buffer.from("a")); });
t("cbcaad", () => crypto.createCipheriv("aes-128-cbc", k16, iv).setAAD(Buffer.from("a")));
"""
    r = js(code)
    assert out(r) == golden("cipher_misuse_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_cipher_info_lists_and_timing_safe_equal(js, golden):
    """CATCHES: wrong introspection data (getCiphers ordering, getCipherInfo by name or NID with the
    OpenSSL id-aes*-gcm names and key/IV-length probes, getCurves) and a timingSafeEqual that
    compares only a prefix or does not throw its RangeError for unequal lengths."""
    code = r"""
const crypto = require("crypto");
console.log(crypto.getCiphers().join(","));
console.log(crypto.getCurves().join(","), crypto.getFips());
for (const q of [["aes-256-gcm"], ["aes-128-ecb"], [419], [906], ["AES-192-CBC"], ["aes-128-cbc", { ivLength: 8 }], ["aes-128-gcm", { ivLength: 20 }],
  ["aes-128-ctr", { keyLength: 16 }], ["aes-128-ctr", { keyLength: 32 }], ["aes-128-ecb", { ivLength: 16 }], ["chacha20"], [1]]) {
  console.log(JSON.stringify(q), JSON.stringify(crypto.getCipherInfo(...q)));
}
console.log(crypto.timingSafeEqual(Buffer.from("abc"), Buffer.from("abc")), crypto.timingSafeEqual(new Uint8Array([1, 2]), new Uint8Array([1, 3])),
  crypto.timingSafeEqual(new Uint32Array([7]), Buffer.from([7, 0, 0, 0])), crypto.timingSafeEqual(Buffer.alloc(0), Buffer.alloc(0)));
try { crypto.timingSafeEqual(Buffer.from("abc"), Buffer.from("ab")); } catch (e) { console.log(e.name, e.message); }
try { crypto.setFips(1); } catch (e) { console.log(e.message); }
console.log(crypto.constants.RSA_PKCS1_PSS_PADDING, crypto.constants.POINT_CONVERSION_UNCOMPRESSED, JSON.stringify(crypto.secureHeapUsed()));
"""
    r = js(code)
    assert out(r) == golden("cipher_info_lists_and_timing_safe_equal")
    assert (r.returncode, r.stderr) == (0, b"")


def test_argon2_rfc9106_vectors(js, golden):
    """CATCHES: an Argon2 implementation that is off from RFC 9106 (the official argon2d/argon2i/
    argon2id test vectors with secret and associated data, 4 lanes), mishandles string inputs or
    short tags, delivers async results wrongly, or misses the exact parameter-validation errors."""
    code = r"""
const crypto = require("crypto");
const p = { message: Buffer.alloc(32, 1), nonce: Buffer.alloc(16, 2), secret: Buffer.alloc(8, 3), associatedData: Buffer.alloc(12, 4),
  parallelism: 4, tagLength: 32, memory: 32, passes: 3 };
for (const a of ["argon2d", "argon2i", "argon2id"]) console.log(a, crypto.argon2Sync(a, p).toString("hex"));
console.log(crypto.argon2Sync("argon2id", { message: "password", nonce: "somesalt", parallelism: 1, tagLength: 16, memory: 64, passes: 2 }).toString("hex"));
console.log(crypto.argon2Sync("argon2i", { ...p, tagLength: 4, parallelism: 1, passes: 1 }).toString("hex"));
const t = (label, f) => { try { console.log(label, "OK", String(f())); } catch (e) { console.log(label, e.name, e.message); } };
t("alg", () => crypto.argon2Sync("argon3", p));
t("params", () => crypto.argon2Sync("argon2d", null));
t("missing", () => crypto.argon2Sync("argon2d", { message: "x" }));
t("nonce", () => crypto.argon2Sync("argon2d", { ...p, nonce: "short" }));
t("mem", () => crypto.argon2Sync("argon2d", { ...p, memory: 31 }));
t("tag", () => crypto.argon2Sync("argon2d", { ...p, tagLength: 3 }));
t("lanes", () => crypto.argon2Sync("argon2d", { ...p, parallelism: 0 }));
t("cb", () => crypto.argon2("argon2d", p));
crypto.argon2("argon2id", { ...p, tagLength: 8 }, (e, k) => console.log("async", e, k.toString("hex")));
"""
    r = js(code)
    assert out(r) == golden("argon2_rfc9106_vectors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_random_api_shapes(js, golden):
    """CATCHES: randomness helpers returning the wrong length/type/format (randomBytes sync and
    callback, randomFillSync offsets, randomUUID v4 layout, randomInt bounds and its range error)
    without ever printing the random values themselves."""
    code = r"""
const crypto = require("crypto");
const b = crypto.randomBytes(37);
console.log(Buffer.isBuffer(b), b.length, crypto.randomBytes(0).length, crypto.randomBytes(70000).length);
const ids = Array.from({ length: 20 }, () => crypto.randomUUID());
console.log(ids.every((u) => /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(u)), new Set(ids).size);
const buf = Buffer.alloc(10, 0xee);
crypto.randomFillSync(buf, 2, 3);
console.log(buf.subarray(0, 2).toString("hex"), buf.subarray(5).toString("hex"));
const ints = Array.from({ length: 200 }, () => crypto.randomInt(3, 7));
console.log(ints.every((n) => Number.isInteger(n) && n >= 3 && n < 7), crypto.randomInt(1) === 0);
try { crypto.randomInt(5, 5); } catch (e) { console.log(e.name, e.message); }
const arr = crypto.getRandomValues(new Uint32Array(4));
console.log(arr.constructor.name, arr.length);
crypto.randomBytes(5, (e, r) => {
  console.log("cb", e, r.length);
  crypto.randomFill(new Uint8Array(6), (e2, r2) => console.log("fill cb", e2, r2.constructor.name, r2.length));
});
"""
    r = js(code)
    assert out(r) == golden("random_api_shapes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_webcrypto_subtle_digest_bridge(js, golden):
    """CATCHES: a node:crypto.webcrypto/subtle bridge that is not the global WebCrypto object or
    computes the wrong SHA-256 digest (string and object algorithm forms, empty input), and digest
    algorithms lumen lacks resolving instead of rejecting with NotSupportedError."""
    code = r"""
const crypto = require("crypto");
(async () => {
  console.log(crypto.webcrypto === globalThis.crypto, crypto.subtle === globalThis.crypto.subtle, typeof crypto.getRandomValues);
  console.log(Buffer.from(await crypto.subtle.digest("SHA-256", new TextEncoder().encode("abc"))).toString("hex"));
  console.log(Buffer.from(await crypto.subtle.digest({ name: "SHA-256" }, new Uint8Array(0))).toString("hex"));
  console.log(Buffer.from(await crypto.subtle.digest("sha-256", Buffer.from("The quick brown fox jumps over the lazy dog"))).toString("base64"));
  for (const alg of ["MD5", "SHA-512"]) {
    try { await crypto.subtle.digest(alg, new Uint8Array(1)); console.log(alg, "resolved"); } catch (e) { console.log(e.name, e.message); }
  }
})();
"""
    r = js(code)
    assert out(r) == golden("webcrypto_subtle_digest_bridge")
    assert (r.returncode, r.stderr) == (0, b"")
