#!/usr/bin/env python3
"""
EMA Screener — เครื่องคำนวณข้อมูลสำหรับเว็บไซต์

สคริปต์นี้ทำหน้าที่เดียว: ดึงราคาหุ้น คำนวณระยะห่างจากเส้น EMA ทุกเส้น
ของหุ้น "ทุกตัว" แล้วเขียนลง docs/data.js

การกรอง (ระยะกี่ %, เอาเฉพาะขาขึ้น, ชนกี่เส้น ฯลฯ) ไปทำในเบราว์เซอร์
เพราะฉะนั้นปรับเงื่อนไขบนเว็บได้ทันทีโดยไม่ต้องรันใหม่

    python screener.py            # สแกน S&P 500 จาก Yahoo Finance
    python screener.py --demo     # ข้อมูลจำลอง ไม่ต้องต่อเน็ต
    python screener.py --limit 50 # ทดลองกับ 50 ตัวแรก
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

EMAS = [5, 10, 20, 50, 100, 200]
SPARK_BARS = 60                       # จำนวนแท่งของกราฟจิ๋วในการ์ด
HERE = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────── รายชื่อหุ้น + ข้อมูลราคา ───────────────────────────

def load_universe(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(f"ไม่พบไฟล์รายชื่อหุ้น: {path}")
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            sym = (r.get("symbol") or "").strip().upper().replace(".", "-")
            if sym:
                rows.append({"s": sym,
                             "n": (r.get("name") or "").strip(),
                             "g": (r.get("sector") or "").strip()})
    return rows


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "close" not in df.columns and "adj close" in df.columns:
        df["close"] = df["adj close"]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[["close", "volume"]]
    df.index = pd.to_datetime(df.index, errors="coerce")
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df = df[df.index.notna()].sort_index()
    return df.apply(pd.to_numeric, errors="coerce").dropna(subset=["close"])


def fetch_yahoo(symbols, period, interval, batch=40) -> dict[str, pd.DataFrame]:
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("ยังไม่ได้ติดตั้งไลบรารี -> pip install pandas numpy yfinance")

    out = {}
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        print(f"  ดาวน์โหลด {i + 1}-{i + len(chunk)} / {len(symbols)}")
        try:
            raw = yf.download(chunk, period=period, interval=interval,
                              auto_adjust=True, group_by="ticker",
                              threads=True, progress=False)
        except Exception as e:
            print(f"  ! พลาดชุดนี้: {e}")
            continue
        if raw is None or len(raw) == 0:
            continue
        for s in chunk:
            try:
                sub = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = normalize(sub)
                if len(d):
                    out[s] = d
            except Exception:
                continue
    return out


def demo_data(symbols, bars=700) -> dict[str, pd.DataFrame]:
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=bars)
    n = len(idx)
    out = {}
    for i, s in enumerate(symbols):
        rng = np.random.default_rng(2000 + i)
        ret = rng.normal(rng.normal(0.0004, 0.0007), rng.uniform(0.010, 0.028), n)
        ret += 0.004 * np.sin(np.linspace(0, rng.uniform(4, 12) * np.pi, n))
        close = 10 * np.exp(np.cumsum(ret)) * rng.uniform(0.6, 25)
        out[s] = pd.DataFrame(
            {"close": close, "volume": rng.integers(8e5, 5e7, n)}, index=idx)
    return out


# ─────────────────────────── การคำนวณ ───────────────────────────

def spark(series: pd.Series) -> list[int]:
    """ย่อราคาช่วงท้ายให้เป็นเลข 0-100 สำหรับวาดกราฟจิ๋ว (ประหยัดขนาดไฟล์)"""
    v = series.tail(SPARK_BARS).to_numpy(dtype=float)
    lo, hi = float(v.min()), float(v.max())
    if not np.isfinite(lo) or hi <= lo:
        return [50] * len(v)
    return [int(round((x - lo) / (hi - lo) * 100)) for x in v]


def analyse(info: dict, df: pd.DataFrame) -> dict | None:
    if len(df) < max(EMAS) + 10:
        return None

    close = df["close"]
    ema = {p: close.ewm(span=p, adjust=False).mean() for p in EMAS}
    price = float(close.iloc[-1])
    if not np.isfinite(price) or price <= 0:
        return None

    last = {p: float(ema[p].iloc[-1]) for p in EMAS}
    dists = [round((price - last[p]) / last[p] * 100, 2) if last[p] else None
             for p in EMAS]
    if any(d is None for d in dists):
        return None

    e50, e200 = last[50], last[200]
    trend = "up" if (price > e200 and e50 > e200) else \
            "down" if (price < e200 and e50 < e200) else "flat"

    aligned = all(last[EMAS[i]] > last[EMAS[i + 1]] for i in range(len(EMAS) - 1))
    ribbon = round((max(last.values()) - min(last.values())) / price * 100, 2)

    s200 = ema[200]
    slope = round((s200.iloc[-1] - s200.iloc[-11]) / abs(s200.iloc[-11]) * 100, 2) \
        if len(s200) > 11 and s200.iloc[-11] else 0.0

    turnover = float((close * df["volume"]).tail(20).mean())
    chg = round((price / float(close.iloc[-2]) - 1) * 100, 2) if len(close) > 1 else 0.0

    return {**info,
            "p": round(price, 2),          # ราคาปิดล่าสุด
            "c": chg,                       # เปลี่ยนแปลงวันล่าสุด %
            "d": dists,                     # ระยะห่างจาก EMA แต่ละเส้น %
            "t": trend,                     # up / down / flat
            "a": 1 if aligned else 0,       # เส้นเรียงสวย
            "r": ribbon,                    # ความกว้างกลุ่มเส้น %
            "sl": slope,                    # ความชัน EMA200 %
            "v": round(turnover / 1e6, 1) if np.isfinite(turnover) else 0,
            "h": spark(close)}              # กราฟจิ๋ว


# ─────────────────────────── main ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="คำนวณข้อมูล EMA สำหรับเว็บไซต์")
    ap.add_argument("--tickers-file", default=os.path.join(HERE, "sp500.csv"))
    ap.add_argument("--tickers", help="ระบุเอง เช่น AAPL,MSFT,NVDA")
    ap.add_argument("--period", default="3y")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "docs", "data.js"))
    a = ap.parse_args()

    if a.tickers:
        universe = [{"s": x.strip().upper().replace(".", "-"), "n": "", "g": ""}
                    for x in a.tickers.split(",") if x.strip()]
    else:
        universe = load_universe(a.tickers_file)
    if a.limit:
        universe = universe[:a.limit]

    syms = [u["s"] for u in universe]
    print(f"เริ่มดึงข้อมูล {len(syms)} ตัว ({a.interval}, ย้อนหลัง {a.period})")
    data = demo_data(syms) if a.demo else fetch_yahoo(syms, a.period, a.interval)
    print(f"ได้ข้อมูล {len(data)}/{len(syms)} ตัว")
    if not data:
        print("ดึงข้อมูลไม่ได้เลย — ลองรันซ้ำอีกครั้ง")
        return 1

    rows, last_date = [], None
    for u in universe:
        df = data.get(u["s"])
        if df is None:
            continue
        try:
            r = analyse(u, df)
        except Exception:
            r = None
        if r:
            rows.append(r)
            last_date = df.index[-1].date().isoformat()

    rows.sort(key=lambda r: r["s"])
    tz = timezone(timedelta(hours=7))
    payload = {
        "meta": {
            "emas": EMAS,
            "count": len(rows),
            "date": last_date or "-",
            "generated": datetime.now(tz).strftime("%d/%m/%Y %H:%M"),
            "sectors": sorted({r["g"] for r in rows if r["g"]}),
            "interval": a.interval,
            "demo": bool(a.demo),
        },
        "rows": rows,
    }

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    # data.js สำหรับหน้าเว็บ static (เปิดจากไฟล์ตรง ๆ ได้)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("window.EMA_DATA = " + body + ";\n")

    # data.json สำหรับแอป Streamlit และการเอาไปใช้ต่อ
    json_path = os.path.join(os.path.dirname(a.out), "data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(body)

    size = os.path.getsize(a.out) / 1024
    print(f"\nคำนวณเสร็จ {len(rows)} ตัว · ข้อมูลวันที่ {last_date}")
    print(f"เขียนไฟล์ -> {a.out} และ {json_path} ({size:.0f} KB)")

    # สรุปคร่าว ๆ ให้เห็นใน log ว่าผลเป็นอย่างไร
    for tol in (1.0, 1.5, 3.0):
        hit = [r for r in rows if any(abs(d) <= tol for d in r["d"])]
        upd = [r for r in hit if r["t"] == "up"]
        print(f"  ระยะ {tol}% : ใกล้เส้น {len(hit)} ตัว (เป็นขาขึ้น {len(upd)} ตัว)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
