/* EMA Screener — ตัวเว็บ: กรอง/ให้คะแนน/แสดงผล ทำในเบราว์เซอร์ทั้งหมด
   ข้อมูลมาจาก data.js (window.EMA_DATA) ที่ screener.py สร้างไว้ */

(function () {
  "use strict";

  var D = window.EMA_DATA;
  if (!D || !D.rows) {
    document.getElementById("meta").textContent =
      "ยังไม่มีไฟล์ข้อมูล (data.js) — ให้รัน screener.py ก่อน หรือกด Run workflow บน GitHub";
    return;
  }

  var EMAS = D.meta.emas;
  // น้ำหนักคะแนน: เส้นยาวเป็นแนวรับ/ต้านที่คนมองกันมากกว่า
  var W = { 5: 1, 10: 1, 20: 1.5, 50: 2, 100: 2.5, 200: 3 };

  var state = {
    q: "",
    sector: "",
    sort: "score",
    tol: 1.5,
    minNear: 1,
    trend: "all",
    lines: new Set(EMAS)
  };

  var $ = function (id) { return document.getElementById(id); };

  /* ── หัวเรื่อง ── */
  $("meta").innerHTML =
    "ข้อมูลปิดตลาดวันที่ <b>" + D.meta.date + "</b> · " +
    "คำนวณจากหุ้น <b>" + D.meta.count + "</b> ตัว · " +
    "อัปเดต " + D.meta.generated + " (เวลาไทย)";
  if (D.meta.demo) $("demoBadge").hidden = false;

  /* ── ตัวเลือกเซกเตอร์ ── */
  var sel = $("sector");
  (D.meta.sectors || []).forEach(function (s) {
    var o = document.createElement("option");
    o.value = s; o.textContent = s;
    sel.appendChild(o);
  });

  /* ── ปุ่มเลือกเส้น ── */
  var linesBox = $("lines");
  EMAS.forEach(function (p) {
    var b = document.createElement("button");
    b.textContent = p;
    b.dataset.v = p;
    b.className = "on";
    b.addEventListener("click", function () {
      if (state.lines.has(p)) {
        if (state.lines.size === 1) return;   // ต้องเหลืออย่างน้อย 1 เส้น
        state.lines.delete(p); b.classList.remove("on");
      } else {
        state.lines.add(p); b.classList.add("on");
      }
      render();
    });
    linesBox.appendChild(b);
  });

  /* ── คำนวณว่าใกล้เส้นไหน + คะแนน + สัญญาณ ── */
  function evaluate(r) {
    var near = [], score = 0;
    for (var i = 0; i < EMAS.length; i++) {
      var p = EMAS[i], d = r.d[i];
      if (!state.lines.has(p)) continue;
      if (Math.abs(d) <= state.tol) {
        near.push(p);
        score += (W[p] || 1) * (0.5 + 0.5 * (1 - Math.abs(d) / state.tol));
      }
    }
    if (r.a) score += 2;
    if (r.t === "up") score += 1;
    if (r.sl > 0) score += 0.5;

    var short = near.some(function (p) { return p <= 20; });
    var long = near.some(function (p) { return p >= 50; });
    var sig;
    if (r.t === "up" && short && near.length >= 2) sig = "ย่อเข้าหาเส้น (ขาขึ้น)";
    else if (r.t === "up" && long) sig = "ทดสอบแนวรับใหญ่";
    else if (r.t === "up") sig = "ย่อสั้น ๆ ในขาขึ้น";
    else if (r.t === "down" && long) sig = "เด้งชนแนวต้านใหญ่";
    else if (r.t === "down") sig = "เด้งชนเส้นสั้น (ขาลง)";
    else if (r.r <= 3) sig = "เส้นบีบตัว (รอ breakout)";
    else sig = "ราคาชนเส้น";

    var nd = 999;
    near.forEach(function (p) {
      var d = Math.abs(r.d[EMAS.indexOf(p)]);
      if (d < nd) nd = d;
    });

    return { near: near, score: Math.round(score * 100) / 100, sig: sig, nd: nd };
  }

  function sparkPath(h) {
    var w = 100, step = h.length > 1 ? w / (h.length - 1) : w, out = "";
    for (var i = 0; i < h.length; i++) {
      out += (i ? "L" : "M") + (i * step).toFixed(1) + " " + (26 - h[i] * 0.24).toFixed(1) + " ";
    }
    return out.trim();
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var current = [];   // แถวที่แสดงอยู่ ใช้ตอน export CSV

  function render() {
    $("tolOut").textContent = state.tol.toFixed(1) + "%";

    var q = state.q.toLowerCase();
    var out = [];

    for (var i = 0; i < D.rows.length; i++) {
      var r = D.rows[i];
      if (state.sector && r.g !== state.sector) continue;
      if (state.trend !== "all" && r.t !== state.trend) continue;
      if (q && (r.s + " " + r.n + " " + r.g).toLowerCase().indexOf(q) < 0) continue;

      var ev = evaluate(r);
      if (ev.near.length < state.minNear) continue;
      out.push({ r: r, ev: ev });
    }

    var k = state.sort;
    out.sort(function (a, b) {
      if (k === "sym") return a.r.s.localeCompare(b.r.s);
      if (k === "near") return b.ev.near.length - a.ev.near.length || b.ev.score - a.ev.score;
      if (k === "dist") return a.ev.nd - b.ev.nd;
      if (k === "chg") return b.r.c - a.r.c;
      if (k === "vol") return b.r.v - a.r.v;
      return b.ev.score - a.ev.score;
    });
    current = out;

    /* สรุปตัวเลขด้านบน */
    var up = 0, multi = 0, big = 0;
    out.forEach(function (o) {
      if (o.r.t === "up") up++;
      if (o.ev.near.length >= 3) multi++;
      if (o.ev.near.some(function (p) { return p >= 100; })) big++;
    });
    $("stats").innerHTML = [
      ["เข้าเงื่อนไข", out.length],
      ["อยู่ในขาขึ้น", up],
      ["ชน 3 เส้นขึ้นไป", multi],
      ["ชนเส้น 100/200", big]
    ].map(function (x) {
      return '<div class="stat"><div class="k">' + x[0] +
             '</div><div class="v mono">' + x[1] + "</div></div>";
    }).join("");

    $("count").textContent = "แสดง " + out.length + " จาก " + D.rows.length + " ตัว";
    $("empty").hidden = out.length > 0;

    /* การ์ด */
    var html = out.map(function (o) {
      var r = o.r, ev = o.ev;
      var cls = r.t === "up" ? "up" : r.t === "down" ? "down" : "";
      var col = r.t === "up" ? "var(--up)" : r.t === "down" ? "var(--down)" : "var(--faint)";

      var chips = EMAS.map(function (p, i) {
        var d = r.d[i];
        var c = ev.near.indexOf(p) >= 0 ? "hit" : (state.lines.has(p) ? "" : "off");
        return '<div class="e ' + c + '"><div class="lb">' + p + '</div>' +
               '<div class="dv mono">' + (d > 0 ? "+" : "") + d + "</div></div>";
      }).join("");

      return '<article class="card ' + cls + '">' +
        '<svg class="spark" viewBox="0 0 100 28" preserveAspectRatio="none">' +
          '<path d="' + sparkPath(r.h) + '" fill="none" stroke="' + col +
          '" stroke-width="1.4" vector-effect="non-scaling-stroke"/></svg>' +
        '<div class="top"><span class="sym">' + esc(r.s) + '</span>' +
          '<span class="chg ' + (r.c >= 0 ? "p" : "n") + ' mono">' +
            (r.c >= 0 ? "+" : "") + r.c + '%</span>' +
          '<span class="px mono">$' + r.p + '</span></div>' +
        '<div class="nm">' + esc(r.n || "&nbsp;") + '</div>' +
        '<div class="badges">' +
          '<span class="b ' + cls + '">' +
            (r.t === "up" ? "ขาขึ้น" : r.t === "down" ? "ขาลง" : "ออกข้าง") + '</span>' +
          '<span class="b sig">' + ev.sig + '</span>' +
          (r.g ? '<span class="b">' + esc(r.g) + "</span>" : "") +
        '</div>' +
        '<div class="emas">' + chips + '</div>' +
        '<div class="foot"><span>คะแนน <b class="mono">' + ev.score + '</b></span>' +
          '<span>ชน ' + ev.near.length + ' เส้น</span>' +
          (r.v ? '<span>' + r.v + "M</span>" : "") + "</div>" +
      "</article>";
    }).join("");

    $("grid").innerHTML = html;
  }

  /* ── การควบคุม ── */
  var t;
  function debounced() { clearTimeout(t); t = setTimeout(render, 60); }

  $("q").addEventListener("input", function (e) { state.q = e.target.value.trim(); debounced(); });
  $("sector").addEventListener("change", function (e) { state.sector = e.target.value; render(); });
  $("sort").addEventListener("change", function (e) { state.sort = e.target.value; render(); });
  $("tol").addEventListener("input", function (e) {
    state.tol = parseFloat(e.target.value);
    $("tolOut").textContent = state.tol.toFixed(1) + "%";
    debounced();
  });

  function segment(id, key, cast) {
    $(id).addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      this.querySelectorAll("button").forEach(function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      state[key] = cast ? cast(b.dataset.v) : b.dataset.v;
      render();
    });
  }
  segment("minNear", "minNear", Number);
  segment("trend", "trend");

  /* ── ดาวน์โหลด CSV ตามที่กรองอยู่ ── */
  $("csv").addEventListener("click", function () {
    var head = ["symbol", "name", "sector", "price", "chg%", "trend", "signal",
                "score", "near"].concat(EMAS.map(function (p) { return "dist" + p; }));
    var lines = [head.join(",")];
    current.forEach(function (o) {
      var r = o.r;
      var cells = [r.s, '"' + (r.n || "").replace(/"/g, "") + '"', '"' + r.g + '"',
                   r.p, r.c, r.t, '"' + o.ev.sig + '"', o.ev.score,
                   '"' + o.ev.near.join("/") + '"'].concat(r.d);
      lines.push(cells.join(","));
    });
    var blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "ema-screen-" + D.meta.date + ".csv";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  render();
})();
