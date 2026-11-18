//! Deflate (RFC 1951) and zlib (RFC 1950) compression, byte for byte as flate2's default
//! backend (miniz_oxide) writes it when the data goes in with one `write_all` and out with
//! `finish`, its 32 KiB buffer and all.
//!
//! Level 1 (`Compression::fast()`, zlib header `78 01`, what a project file's point clouds are
//! packed with) is a greedy LZRW1-style parse over 4 KiB of lookahead with one hash probe; the
//! other levels parse over hash chains (lazily from level 4; 128 probes at 6, the default, `78 9c`,
//! what a PDF's content streams are written with), level 0 stores. Blocks are cut when the LZ code
//! buffer fills (or, past 31 KiB, when they stop paying); each is static under 48 bytes and
//! dynamic otherwise (length-limited canonical Huffman codes), and stored when it doesn't shrink.

const LZ_DICT_SIZE: usize = 32768;
const LZ_DICT_SIZE_MASK: usize = LZ_DICT_SIZE - 1;
const MIN_MATCH_LEN: u32 = 3;
const MAX_MATCH_LEN: usize = 258;
const LZ_CODE_BUF_SIZE: usize = 64 * 1024;
const LZ_HASH_BITS: u32 = 15;
const LEVEL1_HASH_SIZE_MASK: u32 = 4095;
const COMP_FAST_LOOKAHEAD_SIZE: usize = 4096;
const LZ_HASH_SHIFT: u32 = (LZ_HASH_BITS + 2) / 3;
const LZ_HASH_SIZE: usize = 1 << LZ_HASH_BITS;
/// How many hash-chain probes each level makes.
const NUM_PROBES: [u32; 11] = [0, 1, 6, 32, 16, 32, 128, 256, 512, 768, 1500];
/// The dictionary, the first bytes again past its end (so matches read on), and room to read a word past that.
const DICT_FULL_SIZE: usize = LZ_DICT_SIZE + MAX_MATCH_LEN - 1 + 1 + 8;

const MAX_HUFF_SYMBOLS_0: usize = 288;
const MAX_HUFF_SYMBOLS_1: usize = 32;
const MAX_HUFF_SYMBOLS_2: usize = 19;
const MAX_SUPPORTED_HUFF_CODESIZE: usize = 32;

/// The order the code length code's lengths are sent in.
const HUFFMAN_LENGTH_ORDER: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

struct Tables {
    len_sym: [u16; 256],
    len_extra: [u8; 256],
    small_dist_sym: [u8; 512],
    small_dist_extra: [u8; 512],
    large_dist_sym: [u8; 128],
    large_dist_extra: [u8; 128],
}

fn tables() -> &'static Tables {
    static T: std::sync::OnceLock<Tables> = std::sync::OnceLock::new();
    T.get_or_init(|| {
        // lengths 3..258 (index len-3) to codes 257..285
        const LEN_BASE: [u16; 29] =
            [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
        const LEN_EXTRA: [u8; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
        const DIST_BASE: [u32; 30] = [
            1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097,
            6145, 8193, 12289, 16385, 24577,
        ];
        const DIST_EXTRA: [u8; 30] =
            [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
        let mut t = Tables {
            len_sym: [0; 256],
            len_extra: [0; 256],
            small_dist_sym: [0; 512],
            small_dist_extra: [0; 512],
            large_dist_sym: [0; 128],
            large_dist_extra: [0; 128],
        };
        for l in 0..256usize {
            let len = l as u16 + 3;
            let mut c = 0;
            for (i, b) in LEN_BASE.iter().enumerate() {
                if *b <= len {
                    c = i;
                }
            }
            t.len_sym[l] = 257 + c as u16;
            t.len_extra[l] = LEN_EXTRA[c];
        }
        let dist_code = |d: u32| -> usize {
            // d is the distance less one
            let mut c = 0;
            for (i, b) in DIST_BASE.iter().enumerate() {
                if *b <= d + 1 {
                    c = i;
                }
            }
            c
        };
        for d in 0..512u32 {
            let c = dist_code(d);
            t.small_dist_sym[d as usize] = c as u8;
            t.small_dist_extra[d as usize] = DIST_EXTRA[c];
        }
        for h in 0..128u32 {
            // what the high byte of distances of 512 and more selects (only those of 2 and more occur)
            let c = dist_code(h << 8);
            t.large_dist_sym[h as usize] = c as u8;
            t.large_dist_extra[h as usize] = DIST_EXTRA[c];
        }
        t
    })
}

/// Bits out, least significant first, as deflate packs them.
struct BitOut {
    out: Vec<u8>,
    bit_buffer: u64,
    bits_in: u32,
}

impl BitOut {
    fn put_bits(&mut self, bits: u32, len: u32) {
        debug_assert!(len == 0 || bits as u64 <= (1u64 << len) - 1);
        self.bit_buffer |= (bits as u64) << self.bits_in;
        self.bits_in += len;
        while self.bits_in >= 8 {
            self.out.push(self.bit_buffer as u8);
            self.bit_buffer >>= 8;
            self.bits_in -= 8;
        }
    }
    fn pad_to_bytes(&mut self) {
        if self.bits_in != 0 {
            let n = 8 - self.bits_in;
            self.put_bits(0, n);
        }
    }
    fn save(&self) -> (usize, u64, u32) {
        (self.out.len(), self.bit_buffer, self.bits_in)
    }
    fn load(&mut self, s: (usize, u64, u32)) {
        self.out.truncate(s.0);
        self.bit_buffer = s.1;
        self.bits_in = s.2;
    }
}

#[derive(Clone, Copy, Default)]
struct SymFreq {
    key: u16,
    sym_index: u16,
}

struct Huffman {
    count: [[u16; MAX_HUFF_SYMBOLS_0]; 3],
    codes: [[u16; MAX_HUFF_SYMBOLS_0]; 3],
    code_sizes: [[u8; MAX_HUFF_SYMBOLS_0]; 3],
}

impl Huffman {
    fn new() -> Huffman {
        Huffman {
            count: [[0; MAX_HUFF_SYMBOLS_0]; 3],
            codes: [[0; MAX_HUFF_SYMBOLS_0]; 3],
            code_sizes: [[0; MAX_HUFF_SYMBOLS_0]; 3],
        }
    }

    /// A stable sort of the symbols by their counts, least first (two radix passes, one if the counts are small).
    fn radix_sort_symbols<'a>(syms0: &'a mut [SymFreq], syms1: &'a mut [SymFreq]) -> &'a mut [SymFreq] {
        let mut hist = [[0u32; 256]; 2];
        for f in syms0.iter() {
            hist[0][(f.key & 0xFF) as usize] += 1;
            hist[1][((f.key >> 8) & 0xFF) as usize] += 1;
        }
        let mut n_passes = 2;
        if syms0.len() == hist[1][0] as usize {
            n_passes -= 1;
        }
        let mut current = syms0;
        let mut new = syms1;
        for (pass, h) in hist.iter().enumerate().take(n_passes) {
            let mut offsets = [0u32; 256];
            let mut off = 0;
            for i in 0..256 {
                offsets[i] = off;
                off += h[i];
            }
            for sym in current.iter() {
                let j = ((sym.key >> (pass * 8)) & 0xFF) as usize;
                new[offsets[j] as usize] = *sym;
                offsets[j] += 1;
            }
            std::mem::swap(&mut current, &mut new);
        }
        current
    }

    /// Code lengths in place of the counts (Moffat and Katajainen's in-place minimum redundancy codes).
    fn calculate_minimum_redundancy(a: &mut [SymFreq]) {
        let n = a.len();
        if n == 0 {
            return;
        }
        if n == 1 {
            a[0].key = 1;
            return;
        }
        a[0].key = a[0].key.wrapping_add(a[1].key);
        let mut root = 0usize;
        let mut leaf = 2usize;
        for next in 1..n - 1 {
            if leaf >= n || a[root].key < a[leaf].key {
                a[next].key = a[root].key;
                a[root].key = next as u16;
                root += 1;
            } else {
                a[next].key = a[leaf].key;
                leaf += 1;
            }
            if leaf >= n || (root < next && a[root].key < a[leaf].key) {
                a[next].key = a[next].key.wrapping_add(a[root].key);
                a[root].key = next as u16;
                root += 1;
            } else {
                a[next].key = a[next].key.wrapping_add(a[leaf].key);
                leaf += 1;
            }
        }
        a[n - 2].key = 0;
        for next in (0..n - 2).rev() {
            a[next].key = a[a[next].key as usize].key + 1;
        }
        let mut avbl: i32 = 1;
        let mut used: i32 = 0;
        let mut dpth: u16 = 0;
        let mut root = n as i32 - 2;
        let mut next = n as i32 - 1;
        while avbl > 0 {
            while root >= 0 && a[root as usize].key == dpth {
                used += 1;
                root -= 1;
            }
            while avbl > used {
                a[next as usize].key = dpth;
                next -= 1;
                avbl -= 1;
            }
            avbl = 2 * used;
            dpth += 1;
            used = 0;
        }
    }

    /// Holds the code lengths to `max_code_size`, taking from the longest codes.
    fn enforce_max_code_size(num_codes: &mut [i32], code_list_len: usize, max_code_size: usize) {
        if code_list_len <= 1 {
            return;
        }
        let extra: i32 = num_codes[max_code_size + 1..].iter().sum();
        num_codes[max_code_size] += extra;
        let mut total: u32 = 0;
        for i in (1..=max_code_size).rev() {
            total += (num_codes[i] as u32) << (max_code_size - i);
        }
        while total != 1u32 << max_code_size {
            num_codes[max_code_size] -= 1;
            for i in (1..max_code_size).rev() {
                if num_codes[i] != 0 {
                    num_codes[i] -= 1;
                    num_codes[i + 1] += 2;
                    break;
                }
            }
            total -= 1;
        }
    }

    fn optimize_table(&mut self, table_num: usize, table_len: usize, code_size_limit: usize, static_table: bool) {
        let mut num_codes = [0i32; MAX_SUPPORTED_HUFF_CODESIZE + 1];
        let mut next_code = [0u32; MAX_SUPPORTED_HUFF_CODESIZE + 1];
        if static_table {
            for &cs in &self.code_sizes[table_num][..table_len] {
                num_codes[cs as usize] += 1;
            }
        } else {
            let mut syms0 = [SymFreq::default(); MAX_HUFF_SYMBOLS_0];
            let mut syms1 = [SymFreq::default(); MAX_HUFF_SYMBOLS_0];
            let mut used = 0;
            for i in 0..table_len {
                let c = self.count[table_num][i];
                if c != 0 {
                    syms0[used] = SymFreq { key: c, sym_index: i as u16 };
                    used += 1;
                }
            }
            let syms = Self::radix_sort_symbols(&mut syms0[..used], &mut syms1[..used]);
            Self::calculate_minimum_redundancy(syms);
            for s in syms.iter() {
                num_codes[s.key as usize] += 1;
            }
            Self::enforce_max_code_size(&mut num_codes, used, code_size_limit);
            self.code_sizes[table_num] = [0; MAX_HUFF_SYMBOLS_0];
            self.codes[table_num] = [0; MAX_HUFF_SYMBOLS_0];
            let mut last = used;
            for i in 1..=code_size_limit {
                let first = last - num_codes[i] as usize;
                for s in &syms[first..last] {
                    self.code_sizes[table_num][s.sym_index as usize] = i as u8;
                }
                last = first;
            }
        }
        let mut j: u32 = 0;
        next_code[1] = 0;
        for i in 2..=code_size_limit {
            j = (j + num_codes[i - 1] as u32) << 1;
            next_code[i] = j;
        }
        for i in 0..table_len {
            let cs = self.code_sizes[table_num][i] as usize;
            if cs == 0 {
                continue;
            }
            let mut code = next_code[cs];
            next_code[cs] += 1;
            let mut rev = 0u32;
            for _ in 0..cs {
                rev = (rev << 1) | (code & 1);
                code >>= 1;
            }
            self.codes[table_num][i] = rev as u16;
        }
    }

    fn start_static_block(&mut self, out: &mut BitOut) {
        let cs = &mut self.code_sizes[0];
        cs[0..144].fill(8);
        cs[144..256].fill(9);
        cs[256..280].fill(7);
        cs[280..288].fill(8);
        self.code_sizes[1][..32].fill(5);
        self.optimize_table(0, 288, 15, true);
        self.optimize_table(1, 32, 15, true);
        out.put_bits(1, 2);
    }

    fn start_dynamic_block(&mut self, out: &mut BitOut) {
        self.count[0][256] = 1;
        self.optimize_table(0, MAX_HUFF_SYMBOLS_0, 15, false);
        self.optimize_table(1, MAX_HUFF_SYMBOLS_1, 15, false);

        let mut num_lit_codes = 286;
        while num_lit_codes > 257 && self.code_sizes[0][num_lit_codes - 1] == 0 {
            num_lit_codes -= 1;
        }
        let mut num_dist_codes = 30;
        while num_dist_codes > 1 && self.code_sizes[1][num_dist_codes - 1] == 0 {
            num_dist_codes -= 1;
        }

        let mut to_pack = Vec::with_capacity(num_lit_codes + num_dist_codes);
        to_pack.extend_from_slice(&self.code_sizes[0][..num_lit_codes]);
        to_pack.extend_from_slice(&self.code_sizes[1][..num_dist_codes]);

        let mut packed: Vec<u8> = Vec::with_capacity(to_pack.len());
        self.count[2] = [0; MAX_HUFF_SYMBOLS_0];
        let mut rle_z_count: u32 = 0;
        let mut rle_repeat_count: u32 = 0;
        let mut prev_code_size: u8 = 0xFF;

        fn rle_prev(c: &mut [u16; MAX_HUFF_SYMBOLS_0], packed: &mut Vec<u8>, repeat: &mut u32, prev: u8) {
            if *repeat != 0 {
                if *repeat < 3 {
                    c[prev as usize] = c[prev as usize].wrapping_add(*repeat as u16);
                    for _ in 0..*repeat {
                        packed.push(prev);
                    }
                } else {
                    c[16] = c[16].wrapping_add(1);
                    packed.push(16);
                    packed.push((*repeat - 3) as u8);
                }
                *repeat = 0;
            }
        }
        fn rle_zero(c: &mut [u16; MAX_HUFF_SYMBOLS_0], packed: &mut Vec<u8>, z: &mut u32) {
            if *z != 0 {
                if *z < 3 {
                    c[0] = c[0].wrapping_add(*z as u16);
                    for _ in 0..*z {
                        packed.push(0);
                    }
                } else if *z <= 10 {
                    c[17] = c[17].wrapping_add(1);
                    packed.push(17);
                    packed.push((*z - 3) as u8);
                } else {
                    c[18] = c[18].wrapping_add(1);
                    packed.push(18);
                    packed.push((*z - 11) as u8);
                }
                *z = 0;
            }
        }

        for &code_size in &to_pack {
            if code_size == 0 {
                rle_prev(&mut self.count[2], &mut packed, &mut rle_repeat_count, prev_code_size);
                rle_z_count += 1;
                if rle_z_count == 138 {
                    rle_zero(&mut self.count[2], &mut packed, &mut rle_z_count);
                }
            } else {
                rle_zero(&mut self.count[2], &mut packed, &mut rle_z_count);
                if code_size != prev_code_size {
                    rle_prev(&mut self.count[2], &mut packed, &mut rle_repeat_count, prev_code_size);
                    self.count[2][code_size as usize] = self.count[2][code_size as usize].wrapping_add(1);
                    packed.push(code_size);
                } else {
                    rle_repeat_count += 1;
                    if rle_repeat_count == 6 {
                        rle_prev(&mut self.count[2], &mut packed, &mut rle_repeat_count, prev_code_size);
                    }
                }
            }
            prev_code_size = code_size;
        }
        if rle_repeat_count != 0 {
            rle_prev(&mut self.count[2], &mut packed, &mut rle_repeat_count, prev_code_size);
        } else {
            rle_zero(&mut self.count[2], &mut packed, &mut rle_z_count);
        }

        self.optimize_table(2, MAX_HUFF_SYMBOLS_2, 7, false);

        out.put_bits(2, 2);
        out.put_bits((num_lit_codes - 257) as u32, 5);
        out.put_bits((num_dist_codes - 1) as u32, 5);

        let mut num_bit_lengths: i32 = 18;
        while num_bit_lengths >= 0 && self.code_sizes[2][HUFFMAN_LENGTH_ORDER[num_bit_lengths as usize]] == 0 {
            num_bit_lengths -= 1;
        }
        let num_bit_lengths = std::cmp::max(4, num_bit_lengths + 1) as usize;
        out.put_bits(num_bit_lengths as u32 - 4, 4);
        for &sw in &HUFFMAN_LENGTH_ORDER[..num_bit_lengths] {
            out.put_bits(self.code_sizes[2][sw] as u32, 3);
        }

        let mut i = 0;
        while i < packed.len() {
            let code = packed[i] as usize;
            i += 1;
            out.put_bits(self.codes[2][code] as u32, self.code_sizes[2][code] as u32);
            if code >= 16 {
                out.put_bits(packed[i] as u32, [2, 3, 7][code - 16]);
                i += 1;
            }
        }
    }
}

struct Lz {
    codes: Vec<u8>,
    code_position: usize,
    flag_position: usize,
    num_flags_left: u32,
    total_bytes: u32,
}

impl Lz {
    fn new() -> Lz {
        Lz { codes: vec![0; LZ_CODE_BUF_SIZE], code_position: 1, flag_position: 0, num_flags_left: 8, total_bytes: 0 }
    }
    #[inline]
    fn write_code(&mut self, v: u8) {
        self.codes[self.code_position] = v;
        self.code_position += 1;
    }
    #[inline]
    fn flag(&mut self) -> &mut u8 {
        &mut self.codes[self.flag_position]
    }
    #[inline]
    fn consume_flag(&mut self) {
        self.num_flags_left -= 1;
        if self.num_flags_left == 0 {
            self.num_flags_left = 8;
            self.flag_position = self.code_position;
            self.code_position += 1;
        }
    }
    fn init_flag(&mut self) {
        if self.num_flags_left == 8 {
            *self.flag() = 0;
            self.code_position -= 1;
        } else {
            let n = self.num_flags_left;
            *self.flag() >>= n;
        }
    }
}

/// The compressor's state between calls, as a stream keeps it.
pub struct Compressor {
    dict: Vec<u8>,
    hash: Vec<u16>,
    lookahead_pos: usize,
    lookahead_size: usize,
    dict_size: usize,
    code_buf_dict_pos: usize,
    lz: Lz,
    huff: Huffman,
    block_index: u32,
    zlib: bool,
    adler: u32,
    out: BitOut,
    /// Output room left in the caller's buffer (flate2's writer hands 32 KiB at a time).
    space: usize,
    /// Output of a block that didn't fit, waiting for room.
    pending: usize,
    /// A block didn't fit: the parse stopped where it was, to go on when there is room.
    early: bool,
    /// The level's parse: probes into the hash chains (for short and for long matches so far),
    /// greedy or lazy, or stored blocks only (level 0).
    max_probes: [u32; 2],
    greedy: bool,
    raw: bool,
    fast: bool,
    zlib_level: u8,
    next: Vec<u16>,
    saved_lit: u8,
    saved_match_dist: u32,
    saved_match_len: u32,
}

/// The room flate2's writer gives each call (its buffer's capacity).
const WRITER_BUF: usize = 32 * 1024;

#[derive(Clone, Copy, PartialEq)]
enum Flush {
    None,
    Finish,
}

impl Compressor {
    fn new(zlib: bool, level: u32) -> Compressor {
        let level = level.min(10);
        let probes = NUM_PROBES[level as usize];
        let greedy = level <= 3;
        let raw = level == 0;
        let fast = probes == 1 && greedy && !raw;
        let zlib_level = if greedy {
            if probes <= 1 {
                0
            } else {
                1
            }
        } else if probes >= NUM_PROBES[9] {
            3
        } else {
            2
        };
        Compressor {
            max_probes: [1 + (probes + 2) / 3, 1 + ((probes >> 2) + 2) / 3],
            greedy,
            raw,
            fast,
            zlib_level,
            next: vec![0; LZ_DICT_SIZE],
            saved_lit: 0,
            saved_match_dist: 0,
            saved_match_len: 0,
            dict: vec![0; DICT_FULL_SIZE],
            hash: vec![0; 1 << LZ_HASH_BITS],
            lookahead_pos: 0,
            lookahead_size: 0,
            dict_size: 0,
            code_buf_dict_pos: 0,
            lz: Lz::new(),
            huff: Huffman::new(),
            block_index: 0,
            zlib,
            adler: 1,
            out: BitOut { out: Vec::new(), bit_buffer: 0, bits_in: 0 },
            space: WRITER_BUF,
            pending: 0,
            early: false,
        }
    }

    #[inline]
    fn read_u32(&self, pos: usize) -> u32 {
        u32::from_le_bytes([self.dict[pos], self.dict[pos + 1], self.dict[pos + 2], self.dict[pos + 3]])
    }
    #[inline]
    fn read_u64(&self, pos: usize) -> u64 {
        let mut b = [0u8; 8];
        b.copy_from_slice(&self.dict[pos..pos + 8]);
        u64::from_le_bytes(b)
    }

    /// The fast parse over what `input` adds; true when `flush` asked for the rest to be parsed too.
    fn compress_fast(&mut self, input: &[u8], src_pos: &mut usize, flush: Flush) {
        let mut cur_pos = self.lookahead_pos & LZ_DICT_SIZE_MASK;
        while *src_pos < input.len() || (flush != Flush::None && self.lookahead_size != 0) {
            let mut dst_pos = (self.lookahead_pos + self.lookahead_size) & LZ_DICT_SIZE_MASK;
            let mut num = std::cmp::min(input.len() - *src_pos, COMP_FAST_LOOKAHEAD_SIZE - self.lookahead_size);
            self.lookahead_size += num;
            while num != 0 {
                let n = std::cmp::min(LZ_DICT_SIZE - dst_pos, num);
                self.dict[dst_pos..dst_pos + n].copy_from_slice(&input[*src_pos..*src_pos + n]);
                if dst_pos < MAX_MATCH_LEN - 1 {
                    let m = std::cmp::min(n, MAX_MATCH_LEN - 1 - dst_pos);
                    self.dict[dst_pos + LZ_DICT_SIZE..dst_pos + LZ_DICT_SIZE + m]
                        .copy_from_slice(&input[*src_pos..*src_pos + m]);
                }
                *src_pos += n;
                dst_pos = (dst_pos + n) & LZ_DICT_SIZE_MASK;
                num -= n;
            }
            self.dict_size = std::cmp::min(LZ_DICT_SIZE - self.lookahead_size, self.dict_size);
            if flush == Flush::None && self.lookahead_size < COMP_FAST_LOOKAHEAD_SIZE {
                break;
            }

            while self.lookahead_size >= 4 {
                let mut cur_match_len: u32 = 1;
                let first_trigram = self.read_u32(cur_pos) & 0xFF_FFFF;
                let hash = ((first_trigram ^ (first_trigram >> (24 - (LZ_HASH_BITS - 8)))) & LEVEL1_HASH_SIZE_MASK) as usize;
                let mut probe_pos = self.hash[hash] as usize;
                self.hash[hash] = self.lookahead_pos as u16;
                let mut cur_match_dist = (self.lookahead_pos.wrapping_sub(probe_pos)) as u16;
                let mut matched = false;
                if (cur_match_dist as usize) <= self.dict_size {
                    probe_pos &= LZ_DICT_SIZE_MASK;
                    let trigram = self.read_u32(probe_pos) & 0xFF_FFFF;
                    if first_trigram == trigram {
                        let mut p = cur_pos + 3;
                        let mut q = probe_pos + 3;
                        let mut len = None;
                        for _ in 0..32 {
                            let x = self.read_u64(p) ^ self.read_u64(q);
                            if x == 0 {
                                p += 8;
                                q += 8;
                            } else {
                                len = Some((p - cur_pos) as u32 + (x.trailing_zeros() >> 3));
                                break;
                            }
                        }
                        cur_match_len = match len {
                            Some(l) => l,
                            None => {
                                if cur_match_dist == 0 {
                                    0
                                } else {
                                    MAX_MATCH_LEN as u32
                                }
                            }
                        };
                        if cur_match_len < MIN_MATCH_LEN || (cur_match_len == MIN_MATCH_LEN && cur_match_dist >= 8 * 1024) {
                            cur_match_len = 1;
                        } else {
                            matched = true;
                            cur_match_len = std::cmp::min(cur_match_len, self.lookahead_size as u32);
                            cur_match_dist -= 1;
                            self.lz.write_code((cur_match_len - MIN_MATCH_LEN) as u8);
                            self.lz.write_code(cur_match_dist as u8);
                            self.lz.write_code((cur_match_dist >> 8) as u8);
                            *self.lz.flag() >>= 1;
                            *self.lz.flag() |= 0x80;
                            let t = tables();
                            let ds = if cur_match_dist < 512 {
                                t.small_dist_sym[cur_match_dist as usize] as usize
                            } else {
                                t.large_dist_sym[(cur_match_dist >> 8) as usize] as usize
                            };
                            self.huff.count[1][ds] += 1;
                            let ls = t.len_sym[(cur_match_len - MIN_MATCH_LEN) as usize] as usize;
                            self.huff.count[0][ls] += 1;
                        }
                    }
                }
                if !matched {
                    let lit = first_trigram as u8;
                    self.lz.write_code(lit);
                    *self.lz.flag() >>= 1;
                    self.huff.count[0][lit as usize] += 1;
                }
                self.lz.consume_flag();
                self.lz.total_bytes += cur_match_len;
                self.lookahead_pos += cur_match_len as usize;
                self.dict_size = std::cmp::min(self.dict_size + cur_match_len as usize, LZ_DICT_SIZE);
                cur_pos = (cur_pos + cur_match_len as usize) & LZ_DICT_SIZE_MASK;
                self.lookahead_size -= cur_match_len as usize;
                if self.lz.code_position > LZ_CODE_BUF_SIZE - 8 {
                    self.flush_block(Flush::None);
                    if self.early {
                        return;
                    }
                }
            }

            while self.lookahead_size != 0 {
                let lit = self.dict[cur_pos];
                self.lz.total_bytes += 1;
                self.lz.write_code(lit);
                *self.lz.flag() >>= 1;
                self.lz.consume_flag();
                self.huff.count[0][lit as usize] += 1;
                self.lookahead_pos += 1;
                self.dict_size = std::cmp::min(self.dict_size + 1, LZ_DICT_SIZE);
                cur_pos = (cur_pos + 1) & LZ_DICT_SIZE_MASK;
                self.lookahead_size -= 1;
                if self.lz.code_position > LZ_CODE_BUF_SIZE - 8 {
                    self.flush_block(Flush::None);
                    if self.early {
                        return;
                    }
                }
            }
        }
    }

    fn record_literal(&mut self, lit: u8) {
        self.lz.total_bytes += 1;
        self.lz.write_code(lit);
        *self.lz.flag() >>= 1;
        self.lz.consume_flag();
        self.huff.count[0][lit as usize] += 1;
    }

    fn record_match(&mut self, match_len: u32, mut match_dist: u32) {
        self.lz.total_bytes += match_len;
        match_dist -= 1;
        self.lz.write_code((match_len - MIN_MATCH_LEN) as u8);
        self.lz.write_code(match_dist as u8);
        self.lz.write_code((match_dist >> 8) as u8);
        *self.lz.flag() >>= 1;
        *self.lz.flag() |= 0x80;
        self.lz.consume_flag();
        let t = tables();
        let ds = if match_dist < 512 {
            t.small_dist_sym[match_dist as usize] as usize
        } else {
            t.large_dist_sym[((match_dist >> 8) & 127) as usize] as usize
        };
        self.huff.count[1][ds] += 1;
        let ls = t.len_sym[(match_len - MIN_MATCH_LEN) as usize] as usize;
        self.huff.count[0][ls] += 1;
    }

    #[inline]
    fn read_u16(&self, pos: usize) -> u16 {
        u16::from_le_bytes([self.dict[pos], self.dict[pos + 1]])
    }

    /// The longest match for the lookahead in the hash chains, within the level's probes.
    fn find_match(
        &self,
        lookahead_pos: usize,
        max_dist: usize,
        max_match_len: u32,
        mut match_dist: u32,
        mut match_len: u32,
    ) -> (u32, u32) {
        let max_match_len = max_match_len.min(MAX_MATCH_LEN as u32);
        match_len = match_len.max(1);
        let pos = lookahead_pos & LZ_DICT_SIZE_MASK;
        let mut probe_pos = pos;
        let mut num_probes_left = self.max_probes[(match_len >= 32) as usize];
        if max_match_len <= match_len {
            return (match_dist, match_len);
        }
        let mut c01 = self.read_u16(pos + match_len as usize - 1);
        let s01 = self.read_u16(pos);
        'outer: loop {
            let mut dist;
            'found: loop {
                num_probes_left -= 1;
                if num_probes_left == 0 {
                    return (match_dist, match_len);
                }
                for _ in 0..3 {
                    let next_probe_pos = self.next[probe_pos] as usize;
                    dist = lookahead_pos.wrapping_sub(next_probe_pos) & 0xFFFF;
                    if next_probe_pos == 0 || dist > max_dist {
                        return (match_dist, match_len);
                    }
                    probe_pos = next_probe_pos & LZ_DICT_SIZE_MASK;
                    if self.read_u16(probe_pos + match_len as usize - 1) == c01 {
                        break 'found;
                    }
                }
            }
            if dist == 0 {
                return (match_dist, match_len);
            }
            if self.read_u16(probe_pos) != s01 {
                continue;
            }
            let mut p = pos + 2;
            let mut q = probe_pos + 2;
            for _ in 0..32 {
                let x = self.read_u64(p) ^ self.read_u64(q);
                if x == 0 {
                    p += 8;
                    q += 8;
                } else {
                    let probe_len = p - pos + (x.trailing_zeros() as usize >> 3);
                    if probe_len > match_len as usize {
                        match_dist = dist as u32;
                        match_len = max_match_len.min(probe_len as u32);
                        if match_len == max_match_len {
                            return (match_dist, match_len);
                        }
                        c01 = self.read_u16(pos + match_len as usize - 1);
                    }
                    continue 'outer;
                }
            }
            return (dist as u32, max_match_len.min(MAX_MATCH_LEN as u32));
        }
    }

    /// The parse of every level but the fastest: hash chains, lazy matching (greedy to level 3).
    fn compress_normal(&mut self, input: &[u8], src_pos: &mut usize, flush: Flush) {
        let mask_hash = (LZ_HASH_SIZE - 1) as u32;
        while *src_pos < input.len() || (flush != Flush::None && self.lookahead_size != 0) {
            let src_left = input.len() - *src_pos;
            let num = src_left.min(MAX_MATCH_LEN - self.lookahead_size);
            if self.lookahead_size + self.dict_size >= MIN_MATCH_LEN as usize - 1 && num > 0 {
                let mut dst_pos = (self.lookahead_pos + self.lookahead_size) & LZ_DICT_SIZE_MASK;
                let mut ins_pos = self.lookahead_pos + self.lookahead_size - 2;
                let mut hash = ((self.dict[ins_pos & LZ_DICT_SIZE_MASK] as u32) << LZ_HASH_SHIFT)
                    ^ self.dict[(ins_pos + 1) & LZ_DICT_SIZE_MASK] as u32;
                hash &= mask_hash;
                self.lookahead_size += num;
                for k in 0..num {
                    let c = input[*src_pos + k];
                    self.dict[dst_pos] = c;
                    if dst_pos < MAX_MATCH_LEN - 1 {
                        self.dict[LZ_DICT_SIZE + dst_pos] = c;
                    }
                    hash = ((hash << LZ_HASH_SHIFT) ^ c as u32) & mask_hash;
                    self.next[ins_pos & LZ_DICT_SIZE_MASK] = self.hash[hash as usize];
                    self.hash[hash as usize] = ins_pos as u16;
                    dst_pos = (dst_pos + 1) & LZ_DICT_SIZE_MASK;
                    ins_pos += 1;
                }
                *src_pos += num;
            } else {
                for k in 0..num {
                    let c = input[*src_pos + k];
                    let dst_pos = (self.lookahead_pos + self.lookahead_size) & LZ_DICT_SIZE_MASK;
                    self.dict[dst_pos] = c;
                    if dst_pos < MAX_MATCH_LEN - 1 {
                        self.dict[LZ_DICT_SIZE + dst_pos] = c;
                    }
                    self.lookahead_size += 1;
                    if self.lookahead_size + self.dict_size >= MIN_MATCH_LEN as usize {
                        let ins_pos = self.lookahead_pos + self.lookahead_size - 3;
                        let hash = (((self.dict[ins_pos & LZ_DICT_SIZE_MASK] as u32) << (LZ_HASH_SHIFT * 2))
                            ^ (((self.dict[(ins_pos + 1) & LZ_DICT_SIZE_MASK] as u32) << LZ_HASH_SHIFT) ^ c as u32))
                            & mask_hash;
                        self.next[ins_pos & LZ_DICT_SIZE_MASK] = self.hash[hash as usize];
                        self.hash[hash as usize] = ins_pos as u16;
                    }
                }
                *src_pos += num;
            }
            self.dict_size = (LZ_DICT_SIZE - self.lookahead_size).min(self.dict_size);
            if flush == Flush::None && self.lookahead_size < MAX_MATCH_LEN {
                break;
            }

            let mut len_to_move: usize = 1;
            let mut cur_match_dist: u32 = 0;
            let mut cur_match_len: u32 =
                if self.saved_match_len != 0 { self.saved_match_len } else { MIN_MATCH_LEN - 1 };
            let cur_pos = self.lookahead_pos & LZ_DICT_SIZE_MASK;
            if !self.raw {
                let (d, l) = self.find_match(
                    self.lookahead_pos,
                    self.dict_size,
                    self.lookahead_size as u32,
                    cur_match_dist,
                    cur_match_len,
                );
                cur_match_dist = d;
                cur_match_len = l;
            }
            let far_and_small = cur_match_len == MIN_MATCH_LEN && cur_match_dist >= 8 * 1024;
            if far_and_small || cur_pos == cur_match_dist as usize {
                cur_match_dist = 0;
                cur_match_len = 0;
            }
            let at = |c: &Compressor, i: usize| c.dict[i.min(c.dict.len() - 1)];
            if self.saved_match_len != 0 {
                if cur_match_len > self.saved_match_len {
                    let lit = self.saved_lit;
                    self.record_literal(lit);
                    if cur_match_len >= 128 {
                        self.record_match(cur_match_len, cur_match_dist);
                        self.saved_match_len = 0;
                        len_to_move = cur_match_len as usize;
                    } else {
                        self.saved_lit = self.dict[cur_pos];
                        self.saved_match_dist = cur_match_dist;
                        self.saved_match_len = cur_match_len;
                    }
                } else {
                    let (l, d) = (self.saved_match_len, self.saved_match_dist);
                    self.record_match(l, d);
                    len_to_move = (l - 1) as usize;
                    self.saved_match_len = 0;
                }
            } else if cur_match_dist == 0 {
                let lit = at(self, cur_pos);
                self.record_literal(lit);
            } else if self.greedy || cur_match_len >= 128 {
                self.record_match(cur_match_len, cur_match_dist);
                len_to_move = cur_match_len as usize;
            } else {
                self.saved_lit = at(self, cur_pos);
                self.saved_match_dist = cur_match_dist;
                self.saved_match_len = cur_match_len;
            }
            self.lookahead_pos += len_to_move;
            self.lookahead_size -= len_to_move;
            self.dict_size = (self.dict_size + len_to_move).min(LZ_DICT_SIZE);

            let tight = self.lz.code_position > LZ_CODE_BUF_SIZE - 8;
            let fat = ((self.lz.code_position * 115) >> 7) >= self.lz.total_bytes as usize;
            if tight || (self.lz.total_bytes > 31 * 1024 && (fat || self.raw)) {
                self.flush_block(Flush::None);
                if self.early {
                    return;
                }
            }
        }
    }

    fn parse(&mut self, input: &[u8], src_pos: &mut usize, flush: Flush) {
        if self.fast {
            self.compress_fast(input, src_pos, flush)
        } else {
            self.compress_normal(input, src_pos, flush)
        }
    }

    fn compress_lz_codes(&mut self) {
        let t = tables();
        let out = &mut self.out;
        let huff = &self.huff;
        let codes = &self.lz.codes[..self.lz.code_position];
        let mut flags: u32 = 1;
        let mut i = 0;
        while i < codes.len() {
            if flags == 1 {
                flags = codes[i] as u32 | 0x100;
                i += 1;
                if i >= codes.len() {
                    break;
                }
            }
            if flags & 1 == 1 {
                let match_len = codes[i] as usize;
                let match_dist = codes[i + 1] as usize | (codes[i + 2] as usize) << 8;
                i += 3;
                let ls = t.len_sym[match_len] as usize;
                out.put_bits(huff.codes[0][ls] as u32, huff.code_sizes[0][ls] as u32);
                let le = t.len_extra[match_len] as u32;
                out.put_bits(match_len as u32 & ((1u32 << le) - 1), le);
                let (sym, extra) = if match_dist < 512 {
                    (t.small_dist_sym[match_dist] as usize, t.small_dist_extra[match_dist] as u32)
                } else {
                    (t.large_dist_sym[match_dist >> 8] as usize, t.large_dist_extra[match_dist >> 8] as u32)
                };
                out.put_bits(huff.codes[1][sym] as u32, huff.code_sizes[1][sym] as u32);
                out.put_bits(match_dist as u32 & ((1u32 << extra) - 1), extra);
            } else {
                let lit = codes[i] as usize;
                i += 1;
                out.put_bits(huff.codes[0][lit] as u32, huff.code_sizes[0][lit] as u32);
            }
            flags >>= 1;
        }
        out.put_bits(huff.codes[0][256] as u32, huff.code_sizes[0][256] as u32);
    }

    fn flush_block(&mut self, flush: Flush) {
        let start = self.out.out.len();
        self.lz.init_flag();
        if self.zlib && self.block_index == 0 {
            let cmf: u16 = 0x78;
            let flg = (self.zlib_level as u16) << 6;
            let flg = flg + (31 - ((cmf << 8) | flg) % 31);
            self.out.put_bits(cmf as u32, 8);
            self.out.put_bits(flg as u32 & 0xFF, 8);
        }
        self.out.put_bits((flush == Flush::Finish) as u32, 1);
        let saved = self.out.save();
        let total = self.lz.total_bytes as usize;
        let in_window = self.lookahead_pos - self.code_buf_dict_pos <= self.dict_size;
        let use_raw_block = self.raw && in_window;
        if !use_raw_block {
            if self.lz.total_bytes < 48 {
                self.huff.start_static_block(&mut self.out);
            } else {
                self.huff.start_dynamic_block(&mut self.out);
            }
            self.compress_lz_codes();
        }
        let expanded = total > 32 && self.out.out.len() - saved.0 + 1 >= total && in_window;
        if use_raw_block || expanded {
            self.out.load(saved);
            self.out.put_bits(0, 2);
            self.out.pad_to_bytes();
            self.out.put_bits(total as u32 & 0xFFFF, 16);
            self.out.put_bits(!(total as u32) & 0xFFFF, 16);
            for k in 0..total {
                let b = self.dict[(self.code_buf_dict_pos + k) & LZ_DICT_SIZE_MASK];
                self.out.put_bits(b as u32, 8);
            }
        }
        if flush == Flush::Finish {
            self.out.pad_to_bytes();
            if self.zlib {
                let mut a = self.adler;
                for _ in 0..4 {
                    self.out.put_bits((a >> 24) & 0xFF, 8);
                    a <<= 8;
                }
            }
        }
        self.huff.count[0] = [0; MAX_HUFF_SYMBOLS_0];
        self.huff.count[1] = [0; MAX_HUFF_SYMBOLS_0];
        self.lz.code_position = 1;
        self.lz.flag_position = 0;
        self.lz.num_flags_left = 8;
        self.code_buf_dict_pos += self.lz.total_bytes as usize;
        self.lz.total_bytes = 0;
        self.block_index += 1;
        let n = self.out.out.len() - start;
        if n > self.space {
            self.pending = n - self.space;
            self.space = 0;
            self.early = true;
        } else {
            self.space -= n;
        }
    }

    /// The caller makes room for what didn't fit: each call of flate2's writer has a buffer's worth.
    fn drain(&mut self) {
        self.early = false;
        while self.pending > 0 {
            self.space = WRITER_BUF;
            let d = std::cmp::min(self.pending, self.space);
            self.pending -= d;
            self.space -= d;
        }
        if self.space == 0 {
            self.space = WRITER_BUF;
        }
    }
}

/// What flate2's `write_all` then `finish` do: the data in one write (resumed while a block waits for room), then the end.
fn compress(data: &[u8], zlib: bool, level: u32) -> Vec<u8> {
    let mut c = Compressor::new(zlib, level);
    let mut src = 0;
    // `finish` calls with a buffer of its own, unless what waited for room is still going out in it
    let mut fresh_finish = true;
    loop {
        c.parse(data, &mut src, Flush::None);
        if !c.early {
            break;
        }
        c.drain();
        if src == data.len() {
            fresh_finish = false;
            break;
        }
    }
    if fresh_finish {
        c.space = WRITER_BUF;
    }
    loop {
        c.parse(data, &mut src, Flush::Finish);
        if !c.early {
            break;
        }
        c.drain();
    }
    c.adler = crate::inflate::adler32(data);
    c.flush_block(Flush::Finish);
    c.out.out
}

/// A zlib stream of `data` (header `78 01`), as flate2 writes it at `Compression::fast()`.
pub fn zlib_compress(data: &[u8]) -> Vec<u8> {
    compress(data, true, 1)
}

/// Raw deflate of `data`, as flate2's `DeflateEncoder` writes it at `Compression::fast()`.
pub fn deflate_compress(data: &[u8]) -> Vec<u8> {
    compress(data, false, 1)
}

/// A zlib stream of `data` at a flate2 level (0 stored, 1 fast, 6 `Compression::default()`, 9 best;
/// written whole with `write_all`, then `finish`).
pub fn zlib_compress_level(data: &[u8], level: u32) -> Vec<u8> {
    compress(data, true, level)
}

/// Raw deflate of `data` at a flate2 level.
pub fn deflate_compress_level(data: &[u8], level: u32) -> Vec<u8> {
    compress(data, false, level)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(s: &str) -> Vec<u8> {
        (0..s.len() / 2).map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap()).collect()
    }

    #[test]
    fn as_the_original_packs_a_small_scan() {
        // le.ply's points, as BIMCraft 0.10 packed them into a project file
        let mut pts = Vec::new();
        for v in [-50000.0f32, 1000.0, -3500.0, -48500.0, -1000.0, -250.0, 50000.0, 1000.0, 3500.0] {
            pts.extend_from_slice(&v.to_le_bytes());
        }
        let want = hex("78016308703ecec050e5c27020ea2843892d887d04c83f0c147707d220715700ca600ae2");
        assert_eq!(zlib_compress(&pts), want);
        assert_eq!(zlib_compress(&[255, 0, 0, 10, 20, 30, 0, 0, 255]), hex("7801fbcfc0c02522c7c0f01f000b17023b"));
    }

    #[test]
    fn round_trips_at_every_level() {
        let mut data = Vec::new();
        let mut x: u32 = 12345;
        for i in 0..200_000u32 {
            x = x.wrapping_mul(1103515245).wrapping_add(12345);
            data.push(if i % 7 == 0 { (x >> 24) as u8 } else { (i % 251) as u8 });
        }
        for level in 0..=10 {
            let z = zlib_compress_level(&data, level);
            assert_eq!(crate::inflate::zlib_decode(&z, data.len()).unwrap(), data, "level {}", level);
        }
        assert_eq!(zlib_compress(&[]), vec![0x78, 0x01, 0x03, 0x00, 0x00, 0x00, 0x00, 0x01]);
    }
}
