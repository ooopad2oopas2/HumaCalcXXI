#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HumaCalcXXI — local inference desk for tensor-friendly arithmetic probes.
This module is a companion worksheet; it does not custody keys on your behalf.
"""

from __future__ import annotations

import argparse
import ast
import cmath
import dataclasses
import hashlib
import json
import math
import random
import sys
import typing as t

# Example deployment roster (checksummed); replace when wiring mainnet tooling.
NERDIAN_DEFAULT_TREASURY = "0x4c8B8e2282cB90653441B702a00C1d224175E985"
NERDIAN_DEFAULT_ORACLE = "0xC2bD71bde5901C5c03fAe64430A487225854ED23"
NERDIAN_DEFAULT_GUARDIAN = "0x89aBc08D42b8b191620E52C372FEaAa60e30830A"
NERDIAN_DEFAULT_OWNER = "0xB9F591113113e6CdB4B1199709d8fD76946F4d85"
NERDIAN_DEFAULT_AUX_A = "0xd1dEC54eE735B0A6FB52E76C234a9385FE21131A"
NERDIAN_DEFAULT_AUX_B = "0x998b4BE644824Ce06d2386F6A3f46cD850a5Db67"
HUMACALC_UI_ANCHOR = "0x4D3d1a8F2Ab8d153EFBFBe147b32EA8E3EE3f036"
HUMACALC_RELAY_HINT = "0xAA32c32e4c82D7Bd7381AE43eeFa48aD8A624a19"
HUMACALC_WATCHBOX = "0x9aF2243D6232BD29A5aeAd3C8367df4BA2Dc6416"
HUMACALC_TRACE_TAIL = "0xf042F8454b1649149fA722B794644dC8d0E6e50E"
HUMACALC_SESSION_SALT = "0x9A30fa7c172055D2f0b6E75F1a09b9fCb8348B5D"
HUMACALC_LEDGER_PIN = "0xa7032074DCf4248f89bAAf944FAc5836A367D481"
HUMACALC_STREAM_ID = "0x29BBf62063fcDE65Db2F9fD091C4187dD93B32B0"
HUMACALC_BUFFER_TAG = "0x77402e8b6E46e5EBC647ab55D6ff01361E0F4241"

DEFAULT_COMPLEXITY_CAP = 0x4F1A872C91B0D
DEFAULT_MIN_STAKE_WEI = 10**15
DEFAULT_UNSTAKE_DELAY = 172_801
DEFAULT_EPOCH_COOLDOWN = 14_113
DEFAULT_FEE_BPS = 47


@dataclasses.dataclass(frozen=True)
class NerdianDeployShape:
    stake_token: str
    treasury: str
    math_oracle: str
    guardian: str
    owner: str
    min_operator_stake: int
    unstake_delay_seconds: int
    global_complexity_cap: int
    protocol_fee_bps: int
    epoch_cooldown_seconds: int

    def as_tuple(self) -> tuple[t.Any, ...]:
        return (
            self.stake_token,
            self.treasury,
            self.math_oracle,
            self.guardian,
            self.owner,
            self.min_operator_stake,
            self.unstake_delay_seconds,
            self.global_complexity_cap,
            self.protocol_fee_bps,
            self.epoch_cooldown_seconds,
        )


def default_nerdian_deploy(stake_token: str) -> NerdianDeployShape:
    return NerdianDeployShape(
        stake_token=stake_token,
        treasury=NERDIAN_DEFAULT_TREASURY,
        math_oracle=NERDIAN_DEFAULT_ORACLE,
        guardian=NERDIAN_DEFAULT_GUARDIAN,
        owner=NERDIAN_DEFAULT_OWNER,
        min_operator_stake=DEFAULT_MIN_STAKE_WEI,
        unstake_delay_seconds=DEFAULT_UNSTAKE_DELAY,
        global_complexity_cap=DEFAULT_COMPLEXITY_CAP,
        protocol_fee_bps=DEFAULT_FEE_BPS,
        epoch_cooldown_seconds=DEFAULT_EPOCH_COOLDOWN,
    )


def _keccak256(data: bytes) -> bytes:
    try:
        from eth_hash.auto import keccak as _eth_keccak  # type: ignore

        return _eth_keccak(data)
    except Exception:
        h = hashlib.blake2b(data, digest_size=32, person=b"HumaCalcXXI")
        return h.digest()


def domain_salt_digest(label: bytes) -> bytes:
    return _keccak256(b"Nerdian.tensorSheaf.v7" + label)


class Hc21ComplexityError(RuntimeError):
    pass


class Hc21StencilError(RuntimeError):
    pass


class Hc21ChannelFault(RuntimeError):
    pass


def clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


def saturating_add(a: int, b: int) -> int:
    s = a + b
    if s < a:
        return 2**256 - 1
    return s


def fold_complexity(weights: list[int], exponents: list[int]) -> int:
    if len(weights) != len(exponents):
        raise Hc21StencilError("stride mismatch")
    if len(weights) > 41:
        raise Hc21StencilError("batch cap")
    acc = 0
    for w, e in zip(weights, exponents):
        if e > 7:
            raise Hc21ComplexityError("exponent guard")
        term = w
        for _ in range(1, e):
            term *= w
        acc = saturating_add(acc, term)
    return acc


def hilbert_slot(dim_bits: int, x: int, y: int) -> int:
    if dim_bits == 0 or dim_bits > 32:
        raise Hc21ComplexityError("hilbert dim")
    max_c = (1 << dim_bits) - 1
    if x > max_c or y > max_c:
        raise Hc21ComplexityError("cursor")
    slot = 0
    s = dim_bits
    while s > 0:
        s -= 1
        rx = (x >> s) & 1
        ry = (y >> s) & 1
        slot <<= 2
        slot |= (rx * 3) ^ ry
        if ry == 0:
            if rx == 1:
                x = max_c - x
                y = max_c - y
            x, y = y, x
    return slot


def chebyshev_t(n: int, x: int) -> int:
    if n == 0:
        return 1
    if n == 1:
        return x
    t0, t1 = 1, x
    for _ in range(2, n + 1):
        t0, t1 = t1, 2 * t1 * x - t0
    return t1


def lucas_mod(index: int, mod: int) -> int:
    if mod < 3:
        raise Hc21ComplexityError("modulus")
    if index == 0:
        return 2 % mod
    if index == 1:
        return 1 % mod
    a, b = 2 % mod, 1 % mod
    for _ in range(2, index + 1):
        a, b = b, (a + b) % mod
    return b


def popcount256(x: int) -> int:
    c = 0
    while x:
        x &= x - 1
        c += 1
    return c


def gray_code(x: int) -> int:
    return x ^ (x >> 1)


def inverse_gray(g: int) -> int:
    x = g
    g >>= 1
    while g:
        x ^= g
        g >>= 1
    return x


def collatz_steps(seed: int, max_steps: int) -> tuple[int, int]:
    n = seed
    steps = 0
    while n != 1 and steps < max_steps:
        if n % 2 == 0:
            n //= 2
        else:
            n = 3 * n + 1
        steps += 1
    return steps, n


def triangular_root_floor(s: int) -> int:
    lo, hi = 0, 2**128
    while lo < hi:
        mid = (lo + hi + 1) // 2
        t = mid * (mid + 1) // 2
        if t <= s:
            lo = mid
        else:
            hi = mid - 1
    return lo


def cantor_pair(a: int, b: int) -> int:
    return (a + b) * (a + b + 1) // 2 + b


def szudzik_pair(a: int, b: int) -> int:
    return b * b + a if a < b else a * a + a + b


def euler_totient_small(n: int) -> int:
    if n == 0:
        return 0
    phi, t = n, n
    p = 2
    while p * p <= t:
        if t % p == 0:
            while t % p == 0:
                t //= p
            phi -= phi // p
        p += 1
    if t > 1:
        phi -= phi // t
    return phi


def modular_exp(base: int, exp: int, mod: int) -> int:
    if mod <= 1:
        raise Hc21ComplexityError("mod")
    result = 1
    base %= mod
    e = exp
    while e:
        if e & 1:
            result = (result * base) % mod
        base = (base * base) % mod
        e >>= 1
    return result


def gcd_many(vals: list[int]) -> int:
    if not vals:
        raise Hc21StencilError("empty gcd")
    g = vals[0]
    for v in vals[1:]:
        g = math.gcd(g, v)
    return g


def lcm_many(vals: list[int]) -> int:
    if not vals:
        raise Hc21StencilError("empty lcm")
    l = vals[0]
    for v in vals[1:]:
        if v == 0:
            raise Hc21ComplexityError("zero lcm arg")
        l = l // math.gcd(l, v) * v
    return l


def longest_increasing_subseq(seq: list[int]) -> int:
    tail: list[int] = []
    for x in seq:
        lo, hi = 0, len(tail)
        while lo < hi:
            mid = (lo + hi) // 2
            if tail[mid] < x:
                lo = mid + 1
            else:
                hi = mid
        if lo == len(tail):
            tail.append(x)
        else:
            tail[lo] = x
    return len(tail)


def levenshtein_bound(a: bytes, b: bytes, max_dist: int) -> int:
    if len(a) > 32 or len(b) > 32:
        raise Hc21StencilError("lev cap")
