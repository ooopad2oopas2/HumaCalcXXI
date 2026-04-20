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
