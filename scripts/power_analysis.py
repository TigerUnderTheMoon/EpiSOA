#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compute minimum sample size for paired benchmark comparisons."""

from __future__ import annotations

import argparse
import json
import math


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = paired_ttest_power_analysis(
        effect_size=float(args.effect_size),
        alpha=float(args.alpha),
        power=float(args.power),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Power analysis for EpiSOA paper experiments.")
    parser.add_argument("--effect-size", type=float, default=0.35, help="Expected paired Cohen's d.")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--power", type=float, default=0.80)
    return parser


def paired_ttest_power_analysis(effect_size: float, alpha: float = 0.05, power: float = 0.80) -> dict:
    if effect_size <= 0:
        raise ValueError("effect_size must be positive")
    try:
        from statsmodels.stats.power import TTestPower

        nobs = TTestPower().solve_power(effect_size=effect_size, alpha=alpha, power=power, alternative="two-sided")
        method = "statsmodels.TTestPower"
    except Exception:
        # Normal approximation fallback for environments without statsmodels.
        z_alpha = 1.96 if alpha == 0.05 else inverse_normal_cdf(1 - alpha / 2)
        z_power = 0.841621 if power == 0.80 else inverse_normal_cdf(power)
        nobs = ((z_alpha + z_power) / effect_size) ** 2
        method = "normal_approximation"
    return {
        "test": "paired_ttest",
        "effect_size_cohens_d": effect_size,
        "alpha": alpha,
        "target_power": power,
        "minimum_paired_items": math.ceil(nobs),
        "method": method,
    }


def inverse_normal_cdf(p: float) -> float:
    # Peter J. Acklam's rational approximation, sufficient for planning reports.
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.3577518672690, -30.66479806614716, 2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572]
    c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if phigh < p:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


if __name__ == "__main__":
    raise SystemExit(main())
