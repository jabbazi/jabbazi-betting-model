"""Dependency-free, versioned player probability calibration.

Legacy positive-side artifacts keep their original step function. New artifacts
declare their canonical positive side and use the same interpolation at fit/report
and inference. Calibrating the negative side separately is not coherent.
"""
from bisect import bisect_right
import math


def apply_calibration(raw, calibration):
    raw = float(raw)
    if not math.isfinite(raw) or not 0 <= raw <= 1:
        raise ValueError("Invalid calibration input")
    if not calibration:
        return raw
    method = calibration.get("method")
    if method == "platt":
        slope, intercept = float(calibration["slope"]), float(calibration["intercept"])
        if not math.isfinite(slope) or not math.isfinite(intercept) or slope < 0:
            raise ValueError("Invalid monotone logistic calibration")
        p = min(1 - 1e-8, max(1e-8, raw))
        z = slope * math.log(p / (1 - p)) + intercept
        return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))
    if method != "isotonic":
        raise ValueError("Unsupported player calibrator")
    x, y = calibration.get("x", []), calibration.get("y", [])
    if not x or len(x) != len(y):
        raise ValueError("Malformed isotonic calibration")
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in [*x, *y]):
        raise ValueError("Invalid isotonic knots")
    if any(a >= b for a, b in zip(x, x[1:])) or any(a > b for a, b in zip(y, y[1:])):
        raise ValueError("Non-monotone isotonic calibration")
    mode = calibration.get("interpolation", "legacy_step")
    if mode not in {"linear", "legacy_step"}:
        raise ValueError("Unsupported isotonic interpolation")
    if raw <= x[0]:
        return float(y[0])
    if raw >= x[-1]:
        return float(y[-1])
    i = bisect_right(x, raw) - 1
    if mode == "legacy_step":
        return float(y[i])
    return float(y[i] + (y[i + 1] - y[i]) * (raw - x[i]) / (x[i + 1] - x[i]))
