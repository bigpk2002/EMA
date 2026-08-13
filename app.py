"""
EMA Screener — เวอร์ชันแอป Streamlit
รันบน Streamlit Community Cloud ได้ฟรี

หลักการทำงาน: อ่านข้อมูลที่ GitHub Actions คำนวณไว้แล้วจาก docs/data.json
(ไม่ยิง Yahoo Finance ตอนมีคนเปิดแอป จึงเร็วและไม่ติดลิมิต)
ส่วนกราฟรายตัวจะดึงสดเฉพาะหุ้นที่กดดู แล้วแคชไว้ 1 ชั่วโมง

รันในเครื่อง:  streamlit run app.py
"""

from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

EMAS = [5, 10, 20, 50, 100, 200]
W = {5: 1.0, 10: 1.0, 20: 1.5, 50: 2.0, 100: 2.5, 200: 3.0}
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data.json")

st.set_page_config(page_title="EMA Screener", page_icon="📈", layout="wide")


# ─────────────────────────── โหลดข้อมูล ───────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def load_data(path: str, mtime: float) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_data() -> dict | None:
    if not os.path.exists(DATA_PATH):
        return None
    return load_data(DATA_PATH, os.path.getmtime(DATA_PATH))


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_history(symbol: str, period: str = "2y") -> pd.DataFrame | None:
    """ดึงราคาย้อนหลังของหุ้นตัวเดียว ใช้ตอนกดดูกราฟ (แคช 1 ชม.)"""
    try:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or len(df) == 0:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        out = pd.DataFrame({"ราคา": df["Close"].astype(float)})
        for p in EMAS:
            out[f"EMA{p}"] = out["ราคา"].ewm(span=p, adjust=False).mean()
        return out
    except Exception:
        return None


data = get_data()
if not data:
    st.title("📈 EMA Screener")
    st.error("ยังไม่มีไฟล์ข้อมูล `docs/data.json`")
    st.markdown(
        "รัน `python screener.py --demo` เพื่อสร้างข้อมูลทดลอง "
        "หรือ `python screener.py` เพื่อดึงข้อมูลจริง "
        "หรือกด **Run workflow** บน GitHub Actions แล้ว deploy ใหม่"
    )
    st.stop()

meta, rows = data["meta"], data["rows"]


# ─────────────────────────── แถบด้านข้าง ───────────────────────────

st.sidebar.header("เงื่อนไขการคัดกรอง")

tol = st.sidebar.slider("ระยะที่ถือว่า “ใกล้เส้น” (%)", 0.3, 6.0, 1.5, 0.1,
                        help="ราคาห่างจากเส้นไม่เกินกี่ % ถึงนับว่าชนเส้นนั้น")

lines = st.sidebar.multiselect("นับเฉพาะเส้น", EMAS, default=EMAS,
                               help="เช่นเลือกแค่ 100 กับ 200 เพื่อหาหุ้นที่มาทดสอบแนวรับใหญ่")
if not lines:
    lines = EMAS

min_near = st.sidebar.select_slider("ต้องชนอย่างน้อยกี่เส้น", [1, 2, 3, 4, 5, 6], value=1)

trend_pick = st.sidebar.radio("เทรนด์", ["ทั้งหมด", "ขาขึ้น", "ขาลง", "ออกข้าง"], horizontal=True)
TREND_MAP = {"ขาขึ้น": "up", "ขาลง": "down", "ออกข้าง": "flat"}

sectors = st.sidebar.multiselect("เซกเตอร์", meta.get("sectors", []))

with st.sidebar.expander("ตัวกรองเพิ่มเติม"):
    side = st.radio("ตำแหน่งราคาเทียบเส้น", ["ทั้งสองฝั่ง", "เหนือเส้น (แนวรับ)", "ใต้เส้น (แนวต้าน)"])
    min_price = st.number_input("ราคาขั้นต่ำ (USD)", 0.0, 10000.0, 0.0, 5.0)
    min_vol = st.number_input("มูลค่าซื้อขายเฉลี่ยขั้นต่ำ (ล้าน USD)", 0.0, 5000.0, 0.0, 10.0)
    aligned_only = st.checkbox("เฉพาะที่เส้นเรียงสวย 5>10>20>50>100>200")

st.sidebar.caption(f"ข้อมูลปิดตลาด {meta['date']} · อัปเดต {meta['generated']} (เวลาไทย)")
if meta.get("demo"):
    st.sidebar.warning("กำลังแสดงข้อมูลจำลอง")


# ─────────────────────────── คำนวณ ───────────────────────────

def evaluate(r: dict) -> dict | None:
    near, score = [], 0.0
    for i, p in enumerate(EMAS):
        if p not in lines:
            continue
        d = r["d"][i]
        if side == "เหนือเส้น (แนวรับ)" and d < 0:
            continue
        if side == "ใต้เส้น (แนวต้าน)" and d > 0:
            continue
        if abs(d) <= tol:
            near.append(p)
            score += W[p] * (0.5 + 0.5 * (1 - abs(d) / tol))

    if len(near) < min_near:
        return None
    if r["a"]:
        score += 2
    if r["t"] == "up":
        score += 1
    if r["sl"] > 0:
        score += 0.5

    short = any(p <= 20 for p in near)
    long_ = any(p >= 50 for p in near)
    if r["t"] == "up" and short and len(near) >= 2:
        sig = "ย่อเข้าหาเส้น (ขาขึ้น)"
    elif r["t"] == "up" and long_:
        sig = "ทดสอบแนวรับใหญ่"
    elif r["t"] == "up":
        sig = "ย่อสั้น ๆ ในขาขึ้น"
    elif r["t"] == "down" and long_:
        sig = "เด้งชนแนวต้านใหญ่"
    elif r["t"] == "down":
        sig = "เด้งชนเส้นสั้น (ขาลง)"
    elif r["r"] <= 3:
        sig = "เส้นบีบตัว (รอ breakout)"
    else:
        sig = "ราคาชนเส้น"

    return {"near": near, "score": round(score, 2), "signal": sig,
            "nearest": min(abs(r["d"][EMAS.index(p)]) for p in near)}


TREND_TH = {"up": "ขาขึ้น", "down": "ขาลง", "flat": "ออกข้าง"}
records = []
for r in rows:
    if sectors and r["g"] not in sectors:
        continue
    if trend_pick != "ทั้งหมด" and r["t"] != TREND_MAP[trend_pick]:
        continue
    if r["p"] < min_price or r["v"] < min_vol:
        continue
    if aligned_only and not r["a"]:
        continue
    ev = evaluate(r)
    if not ev:
        continue
    rec = {
        "หุ้น": r["s"], "ชื่อ": r["n"], "เซกเตอร์": r["g"],
        "ราคา": r["p"], "วันนี้ %": r["c"],
        "เทรนด์": TREND_TH[r["t"]], "สัญญาณ": ev["signal"],
        "ชนเส้น": "/".join(map(str, ev["near"])),
        "จำนวนเส้น": len(ev["near"]), "คะแนน": ev["score"],
    }
    for i, p in enumerate(EMAS):
        rec[f"EMA{p}"] = r["d"][i]
    rec["มูลค่า(ล้าน)"] = r["v"]
    rec["_near"] = ev["near"]
    records.append(rec)

df = pd.DataFrame(records)


# ─────────────────────────── ส่วนแสดงผล ───────────────────────────

st.title("📈 หุ้นสหรัฐที่ราคาใกล้เส้น EMA")
st.caption(f"S&P 500 · คำนวณจากหุ้น {meta['count']} ตัว · "
           f"ข้อมูลปิดตลาดวันที่ {meta['date']} · ไทม์เฟรม {meta.get('interval', '1d')}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("เข้าเงื่อนไข", len(df))
if len(df):
    c2.metric("อยู่ในขาขึ้น", int((df["เทรนด์"] == "ขาขึ้น").sum()))
    c3.metric("ชน 3 เส้นขึ้นไป", int((df["จำนวนเส้น"] >= 3).sum()))
    c4.metric("ชนเส้น 100/200",
              int(df["_near"].apply(lambda n: any(p >= 100 for p in n)).sum()))
else:
    c2.metric("อยู่ในขาขึ้น", 0); c3.metric("ชน 3 เส้นขึ้นไป", 0); c4.metric("ชนเส้น 100/200", 0)

if not len(df):
    st.info("ไม่มีหุ้นตรงเงื่อนไข — ลองเพิ่มระยะ % หรือลดจำนวนเส้นที่ต้องชน")
    st.stop()

tab_table, tab_chart, tab_sector = st.tabs(["ตารางผลสแกน", "กราฟรายตัว", "สรุปตามเซกเตอร์"])

with tab_table:
    left, right = st.columns([3, 1])
    q = left.text_input("ค้นหา", placeholder="AAPL, Apple, Energy…", label_visibility="collapsed")
    sort_by = right.selectbox("เรียงตาม", ["คะแนน", "จำนวนเส้น", "วันนี้ %", "มูลค่า(ล้าน)", "หุ้น"],
                              label_visibility="collapsed")

    view = df
    if q:
        k = q.strip().lower()
        mask = (view["หุ้น"].str.lower().str.contains(k)
                | view["ชื่อ"].str.lower().str.contains(k)
                | view["เซกเตอร์"].str.lower().str.contains(k))
        view = view[mask]

    view = view.sort_values(sort_by, ascending=(sort_by == "หุ้น")).drop(columns=["_near"])
    dist_cols = [f"EMA{p}" for p in EMAS]

    def paint(v):
        return "background-color: rgba(251,191,36,.25); font-weight:600" if abs(v) <= tol else ""

    styled = (view.style
              .map(paint, subset=dist_cols)
              .format({"ราคา": "{:.2f}", "วันนี้ %": "{:+.2f}", "คะแนน": "{:.2f}",
                       "มูลค่า(ล้าน)": "{:,.0f}", **{c: "{:+.2f}" for c in dist_cols}}))

    st.dataframe(styled, width="stretch", height=560, hide_index=True)
    st.caption(f"แสดง {len(view)} ตัว · ช่องไฮไลต์เหลืองคือเส้นที่ราคาอยู่ในระยะ {tol}% · "
               "ตัวเลขคือระยะห่างเป็น % (บวก = ราคาอยู่เหนือเส้น)")
    st.download_button("ดาวน์โหลด CSV", view.to_csv(index=False).encode("utf-8-sig"),
                       f"ema-screen-{meta['date']}.csv", "text/csv")

with tab_chart:
    pick = st.selectbox("เลือกหุ้นเพื่อดูกราฟราคากับเส้น EMA",
                        df["หุ้น"].tolist(),
                        format_func=lambda s: f"{s} — {df.loc[df['หุ้น'] == s, 'ชื่อ'].iloc[0]}")
    show = st.multiselect("เส้นที่แสดงบนกราฟ", EMAS, default=[20, 50, 200])
    row = df[df["หุ้น"] == pick].iloc[0]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("ราคา", f"${row['ราคา']:.2f}", f"{row['วันนี้ %']:+.2f}%")
    m2.metric("เทรนด์", row["เทรนด์"])
    m3.metric("ชนเส้น", row["ชนเส้น"] or "-")
    m4.metric("คะแนน", f"{row['คะแนน']:.2f}")
    st.caption(f"{row['ชื่อ']} · {row['เซกเตอร์']} · {row['สัญญาณ']}")

    hist = fetch_history(pick)
    if hist is None:
        st.info("ดึงกราฟไม่สำเร็จ (อาจติดลิมิตของ Yahoo หรือกำลังใช้ข้อมูลจำลอง) — ลองใหม่อีกครั้ง")
    else:
        cols = ["ราคา"] + [f"EMA{p}" for p in show]
        st.line_chart(hist[cols].tail(260), height=420)

with tab_sector:
    g = df.groupby("เซกเตอร์").agg({
        "หุ้น": "count",
        "คะแนน": "mean",
        "เทรนด์": lambda s: int((s == "ขาขึ้น").sum()),
    })
    g.columns = ["จำนวน", "คะแนนเฉลี่ย", "ขาขึ้น"]
    g = g.sort_values("จำนวน", ascending=False)
    st.bar_chart(g["จำนวน"], height=320)
    st.dataframe(g.style.format({"คะแนนเฉลี่ย": "{:.2f}"}), width="stretch")

st.divider()
st.caption("คะแนน = ชนหลายเส้นยิ่งสูง เส้นยาว (100/200) มีน้ำหนักมากกว่า บวกเพิ่มถ้าเรียงเส้นสวยหรือเป็นขาขึ้น · "
           "เครื่องมือนี้ช่วยคัดกรองเบื้องต้นเท่านั้น ไม่ใช่คำแนะนำการลงทุน")
