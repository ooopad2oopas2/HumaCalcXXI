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
    la, lb = len(a), len(b)
    row = list(range(lb + 1))
    for i in range(1, la + 1):
        prev = row[0]
        row[0] = i
        for j in range(1, lb + 1):
            tmp = row[j]
            cost = 0 if a[i - 1] == b[j - 1] else 1
            row[j] = min(row[j] + 1, row[j - 1] + 1, prev + cost)
            prev = tmp
        if row[lb] > max_dist:
            return max_dist + 1
    return row[lb]


def horner(coeffs: list[int], x: int) -> int:
    if not coeffs:
        raise Hc21StencilError("coeffs")
    y = coeffs[0]
    for c in coeffs[1:]:
        y = y * x + c
    return y


def kahan_sum(terms: list[float]) -> float:
    s = 0.0
    c = 0.0
    for x in terms:
        y = x - c
        t = s + y
        c = (t - s) - y
        s = t
    return s


def softmax(logits: list[float], temp: float = 1.0) -> list[float]:
    if temp == 0:
        raise Hc21ComplexityError("temperature")
    m = max(logits)
    exps = [math.exp((z - m) / temp) for z in logits]
    s = sum(exps)
    return [e / s for e in exps]


def parse_rational(s: str) -> tuple[int, int]:
    s = s.strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return int(a), int(b)
    return int(s), 1


def _safe_eval_ast(node: ast.AST, env: dict[str, t.Any]) -> t.Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise Hc21ChannelFault("disallowed literal")
    if isinstance(node, ast.UnaryOp):
        v = _safe_eval_ast(node.operand, env)
        if isinstance(node.op, ast.UAdd):
            return +v
        if isinstance(node.op, ast.USub):
            return -v
        raise Hc21ChannelFault("bad unary")
    if isinstance(node, ast.BinOp):
        left = _safe_eval_ast(node.left, env)
        right = _safe_eval_ast(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        raise Hc21ChannelFault("bad binop")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise Hc21ChannelFault("call shape")
        fn = env.get(node.func.id)
        if not callable(fn):
            raise Hc21ChannelFault("unknown fn")
        args = [_safe_eval_ast(a, env) for a in node.args]
        return fn(*args)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise Hc21ChannelFault("unknown name")
        return env[node.id]
    raise Hc21ChannelFault("unsupported syntax")


def eval_mixed_expression(expr: str) -> complex:
    expr = expr.strip().replace("i", "j")
    if not expr:
        raise Hc21ChannelFault("empty")
    tree = ast.parse(expr, mode="eval")
    env: dict[str, t.Any] = {
        "sqrt": cmath.sqrt,
        "sin": cmath.sin,
        "cos": cmath.cos,
        "exp": cmath.exp,
        "log": cmath.log,
        "pi": complex(math.pi),
        "e": complex(math.e),
        "j": 1j,
    }
    return complex(_safe_eval_ast(tree.body, env))


class QuarkMathBot:
    """Stateful desk for staged evaluations."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._history: list[str] = []

    def roll_kernel_id(self) -> int:
        return self._rng.randint(1, 2**16)

    def log_turn(self, msg: str) -> None:
        self._history.append(msg)

    def digest_history(self) -> str:
        h = hashlib.blake2b(digest_size=32)
        for line in self._history:
            h.update(line.encode())
        return h.hexdigest()

    def monte_carlo_pi(self, n: int) -> float:
        inside = 0
        for _ in range(n):
            x, y = self._rng.random(), self._rng.random()
            if x * x + y * y <= 1:
                inside += 1
        return 4 * inside / n

    def estimate_integral_0_1(self, fn: t.Callable[[float], float], n: int) -> float:
        acc = 0.0
        for _ in range(n):
            x = self._rng.random()
            acc += fn(x)
        return acc / n


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="HumaCalcXXI", description="Nerdian-adjacent math worksheet CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("fold", help="Fold complexity weights^exponents")
    s.add_argument("--weights", required=True, help="comma ints")
    s.add_argument("--exponents", required=True, help="comma ints")

    s2 = sub.add_parser("hilbert", help="Hilbert slot index")
    s2.add_argument("--dim", type=int, required=True)
    s2.add_argument("--x", type=int, required=True)
    s2.add_argument("--y", type=int, required=True)

    s3 = sub.add_parser("deploy-json", help="Emit default constructor tuple JSON")
    s3.add_argument("--stake-token", required=True, help="ERC20 stake token address")

    s4 = sub.add_parser("pi", help="Monte Carlo pi")
    s4.add_argument("-n", type=int, default=200_000)

    s5 = sub.add_parser("softmax", help="Softmax vector")
    s5.add_argument("--logits", required=True, help="comma floats")
    s5.add_argument("--temp", type=float, default=1.0)

    s6 = sub.add_parser("digest-anchors", help="Print configured hint addresses")

    s7 = sub.add_parser("cexpr", help="Restricted complex expression (ast sandbox)")
    s7.add_argument("--expr", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.cmd == "fold":
        w = [int(x) for x in args.weights.split(",")]
        e = [int(x) for x in args.exponents.split(",")]
        print(fold_complexity(w, e))
        return 0
    if args.cmd == "hilbert":
        print(hilbert_slot(args.dim, args.x, args.y))
        return 0
    if args.cmd == "deploy-json":
        d = default_nerdian_deploy(args.stake_token)
        print(json.dumps(dataclasses.asdict(d), indent=2))
        return 0
    if args.cmd == "pi":
        bot = QuarkMathBot()
        print(bot.monte_carlo_pi(args.n))
        return 0
    if args.cmd == "softmax":
        logits = [float(x) for x in args.logits.split(",")]
        print(json.dumps(softmax(logits, args.temp)))
        return 0
    if args.cmd == "digest-anchors":
        print(
            json.dumps(
                {
                    "ui_anchor": HUMACALC_UI_ANCHOR,
                    "relay_hint": HUMACALC_RELAY_HINT,
                    "watchbox": HUMACALC_WATCHBOX,
                    "trace_tail": HUMACALC_TRACE_TAIL,
                    "session_salt": HUMACALC_SESSION_SALT,
                    "ledger_pin": HUMACALC_LEDGER_PIN,
                    "stream_id": HUMACALC_STREAM_ID,
                    "buffer_tag": HUMACALC_BUFFER_TAG,
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "cexpr":
        print(eval_mixed_expression(args.expr))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


# --- expanded numerical worksheet catalog ---


def _hc21_wavelet_leaf_000(t: float) -> float:
    """Leaf 0: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 0))
    b = math.cos(t * (1.618 + 0.007 * 0))
    c = math.sin(t * (2.718 + 0.003 * 0))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_001(t: float) -> float:
    """Leaf 1: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 1))
    b = math.cos(t * (1.618 + 0.007 * 1))
    c = math.sin(t * (2.718 + 0.003 * 1))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_002(t: float) -> float:
    """Leaf 2: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 2))
    b = math.cos(t * (1.618 + 0.007 * 2))
    c = math.sin(t * (2.718 + 0.003 * 2))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_003(t: float) -> float:
    """Leaf 3: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 3))
    b = math.cos(t * (1.618 + 0.007 * 3))
    c = math.sin(t * (2.718 + 0.003 * 3))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_004(t: float) -> float:
    """Leaf 4: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 4))
    b = math.cos(t * (1.618 + 0.007 * 4))
    c = math.sin(t * (2.718 + 0.003 * 4))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_005(t: float) -> float:
    """Leaf 5: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 5))
    b = math.cos(t * (1.618 + 0.007 * 5))
    c = math.sin(t * (2.718 + 0.003 * 5))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_006(t: float) -> float:
    """Leaf 6: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 6))
    b = math.cos(t * (1.618 + 0.007 * 6))
    c = math.sin(t * (2.718 + 0.003 * 6))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_007(t: float) -> float:
    """Leaf 7: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 7))
    b = math.cos(t * (1.618 + 0.007 * 7))
    c = math.sin(t * (2.718 + 0.003 * 7))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_008(t: float) -> float:
    """Leaf 8: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 8))
    b = math.cos(t * (1.618 + 0.007 * 8))
    c = math.sin(t * (2.718 + 0.003 * 8))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_009(t: float) -> float:
    """Leaf 9: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 9))
    b = math.cos(t * (1.618 + 0.007 * 9))
    c = math.sin(t * (2.718 + 0.003 * 9))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_010(t: float) -> float:
    """Leaf 10: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 10))
    b = math.cos(t * (1.618 + 0.007 * 10))
    c = math.sin(t * (2.718 + 0.003 * 10))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_011(t: float) -> float:
    """Leaf 11: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 11))
    b = math.cos(t * (1.618 + 0.007 * 11))
    c = math.sin(t * (2.718 + 0.003 * 0))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_012(t: float) -> float:
    """Leaf 12: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 12))
    b = math.cos(t * (1.618 + 0.007 * 12))
    c = math.sin(t * (2.718 + 0.003 * 1))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_013(t: float) -> float:
    """Leaf 13: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 13))
    b = math.cos(t * (1.618 + 0.007 * 13))
    c = math.sin(t * (2.718 + 0.003 * 2))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_014(t: float) -> float:
    """Leaf 14: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 14))
    b = math.cos(t * (1.618 + 0.007 * 14))
    c = math.sin(t * (2.718 + 0.003 * 3))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_015(t: float) -> float:
    """Leaf 15: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 15))
    b = math.cos(t * (1.618 + 0.007 * 15))
    c = math.sin(t * (2.718 + 0.003 * 4))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_016(t: float) -> float:
    """Leaf 16: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 16))
    b = math.cos(t * (1.618 + 0.007 * 16))
    c = math.sin(t * (2.718 + 0.003 * 5))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_017(t: float) -> float:
    """Leaf 17: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 17))
    b = math.cos(t * (1.618 + 0.007 * 0))
    c = math.sin(t * (2.718 + 0.003 * 6))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_018(t: float) -> float:
    """Leaf 18: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 18))
    b = math.cos(t * (1.618 + 0.007 * 1))
    c = math.sin(t * (2.718 + 0.003 * 7))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_019(t: float) -> float:
    """Leaf 19: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 19))
    b = math.cos(t * (1.618 + 0.007 * 2))
    c = math.sin(t * (2.718 + 0.003 * 8))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_020(t: float) -> float:
    """Leaf 20: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 20))
    b = math.cos(t * (1.618 + 0.007 * 3))
    c = math.sin(t * (2.718 + 0.003 * 9))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_021(t: float) -> float:
    """Leaf 21: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 21))
    b = math.cos(t * (1.618 + 0.007 * 4))
    c = math.sin(t * (2.718 + 0.003 * 10))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_022(t: float) -> float:
    """Leaf 22: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 22))
    b = math.cos(t * (1.618 + 0.007 * 5))
    c = math.sin(t * (2.718 + 0.003 * 0))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_023(t: float) -> float:
    """Leaf 23: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 23))
    b = math.cos(t * (1.618 + 0.007 * 6))
    c = math.sin(t * (2.718 + 0.003 * 1))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_024(t: float) -> float:
    """Leaf 24: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 24))
    b = math.cos(t * (1.618 + 0.007 * 7))
    c = math.sin(t * (2.718 + 0.003 * 2))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_025(t: float) -> float:
    """Leaf 25: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 25))
    b = math.cos(t * (1.618 + 0.007 * 8))
    c = math.sin(t * (2.718 + 0.003 * 3))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_026(t: float) -> float:
    """Leaf 26: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 26))
    b = math.cos(t * (1.618 + 0.007 * 9))
    c = math.sin(t * (2.718 + 0.003 * 4))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_027(t: float) -> float:
    """Leaf 27: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 27))
    b = math.cos(t * (1.618 + 0.007 * 10))
    c = math.sin(t * (2.718 + 0.003 * 5))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def _hc21_wavelet_leaf_028(t: float) -> float:
    """Leaf 28: damped harmonic mixing three incommensurate tones."""
    a = math.sin(t * (1.0 + 0.01 * 28))
    b = math.cos(t * (1.618 + 0.007 * 11))
    c = math.sin(t * (2.718 + 0.003 * 6))
    return (a + 0.5 * b + 0.25 * c) / 1.75

