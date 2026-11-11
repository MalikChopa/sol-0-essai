"""Sonde du dépôt d'essai Sol-0 : déterminisme numpy (F5), GIF servi par branche (F2), ponctualité du cron (F3).
Usage : python probe.py <dossier_sortie>   (écrit probe.json, probe.gif et ajoute une ligne à runs.csv)"""
import csv, datetime as dt, hashlib, json, os, platform, sys
import numpy as np
from PIL import Image, ImageDraw

def h(a) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]

def splitmix64(counter: np.ndarray, seed: int) -> np.ndarray:
    z = (counter.astype(np.uint64) + np.uint64(seed)) * np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))

def probes() -> dict:
    with np.errstate(over="ignore"):
        r = splitmix64(np.arange(1_000_000, dtype=np.uint64), 42)
    x = (r >> np.uint64(11)).astype(np.float64) * (2.0 ** -53)
    x32 = x.astype(np.float32)
    A = x[:4096].reshape(64, 64)
    out = {
        "prng_splitmix64": h(r),
        "ieee_add_mul_div_sqrt_f64": h(np.sqrt((x * 1.5 + 0.25) / (x + 1.0))),
        "ieee_add_mul_div_sqrt_f32": h(np.sqrt((x32 * np.float32(1.5) + np.float32(0.25)) / (x32 + np.float32(1.0)))),
        "sin_f64": h(np.sin(x * 100.0)), "exp_f64": h(np.exp(x * 5.0)), "tanh_f64": h(np.tanh(x * 4.0 - 2.0)),
        "log1p_f64": h(np.log1p(x)), "sin_f32": h(np.sin(x32 * np.float32(100))), "exp_f32": h(np.exp(x32 * np.float32(5))),
        "tanh_f32": h(np.tanh(x32 * np.float32(4) - np.float32(2))),
        "matmul_f64_64": h(A @ A), "matmul_f32_64": h(A.astype(np.float32) @ A.astype(np.float32)),
        "dot_f64_1e6": h(np.array([np.dot(x, x[::-1])])),
        "sum_f64_1e6": h(np.array([x.sum()])), "sum_axis0_f64": h(x.reshape(1000, 1000).sum(axis=0)),
        "cumsum_f64": h(np.cumsum(x[:100_000])), "mean_f32": h(np.array([x32.mean()])),
        "einsum_small_f64": h(np.einsum("ij,j->i", A[:16, :12], x[:12])),
        "rational_act_f64": h((lambda v: v / (1.0 + np.abs(v)))(x * 6.0 - 3.0)),
    }
    return out

def main(outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    event, sched = os.environ.get("EVENT", "local"), os.environ.get("SCHEDULE", "")
    expected, delay = "", ""
    if event == "schedule":  # cron "23 * * * *" : dernier créneau prévu
        exp = now.replace(minute=23, second=0, microsecond=0)
        if now < exp:
            exp -= dt.timedelta(hours=1)
        expected, delay = exp.isoformat(timespec="seconds"), f"{(now - exp).total_seconds() / 60:.1f}"
    try:
        feats = sorted(k for k, v in np._core._multiarray_umath.__cpu_features__.items() if v)  # type: ignore[attr-defined]
    except Exception:
        feats = []
    info = {"utc": now.isoformat(timespec="seconds"), "event": event, "schedule": sched, "run_number": os.environ.get("RUN_NUMBER", ""),
            "machine": platform.machine(), "system": platform.system(), "python": platform.python_version(),
            "numpy": np.__version__, "cpu_features": feats[-12:], "probes": probes()}
    with open(os.path.join(outdir, "probe.json"), "w") as f:
        json.dump(info, f, indent=1)
    path = os.path.join(outdir, "runs.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["utc_start", "event", "run_number", "expected_utc", "delay_min"])
        w.writerow([info["utc"], event, info["run_number"], expected, delay])
    frames = []
    for k in range(6):  # petit GIF animé lent (< 3 Hz), texte en anglais
        im = Image.new("P", (240, 80), 0)
        im.putpalette([18, 12, 10, 255, 179, 71, 138, 59, 30] + [0] * (256 * 3 - 9))
        d = ImageDraw.Draw(im)
        d.rectangle([4, 60, 4 + k * 46, 70], fill=2)
        d.text((6, 8), "SOL-0 PROBE", fill=1)
        d.text((6, 26), f"{info['utc']} {event}", fill=1)
        d.text((6, 42), f"run {info['run_number']} {info['machine']}", fill=1)
        frames.append(im)
    frames[0].save(os.path.join(outdir, "probe.gif"), save_all=True, append_images=frames[1:], duration=500, loop=0, optimize=True)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
