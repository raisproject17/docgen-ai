"""Vercel serverless function for the DocGen wizard (ala NgodingPakeAI flow).

POST /api/wizard, JSON body:
  { "step": "clarify|workflow|prd",
    "idea": "...", "target": "...", "answers": [{"q": "...", "a": "..."}],
    "tech": "...", "workflow": {...}, "model": "mangoboost" }

Uses ONLY the 9Router auto key from the Vercel env var
DOCGEN_9ROUTER_API_KEY (same dedicated DOCGEN client key as /api/generate
with provider 9router). No key is ever sent from the browser or stored in
the repo. Stdlib only.
"""
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

NINE_BASE = "https://aws.jarvisrais.my.id/v1"
SYSTEM = (
    "Kamu adalah CTO/Product consultant yang membangun dokumen produk tingkat"
    " enterprise. Jawab dalam Bahasa Indonesia, ringkas tapi spesifik, tanpa"
    " basa-basi dan tanpa disclaimer."
)


def _call(prompt, model, max_tokens):
    api_key = os.environ.get("DOCGEN_9ROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("Key 9Router belum diset sebagai env var DOCGEN_9ROUTER_API_KEY di Vercel.")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.6,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        NINE_BASE + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=50) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Provider error {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
    if "data: [DONE]" in text:
        text = text.split("data: [DONE]")[0].strip()
    data = json.loads(text)
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Format respons tidak dikenal: {str(data)[:500]}")


def _parse_json(text):
    """Parse AI JSON output, tolerating ```json fences and stray prose."""
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                t = part
                break
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            t = t[start:end + 1]
    return json.loads(t)


def _ctx(data):
    idea = (data.get("idea") or "").strip()
    target = (data.get("target") or "").strip()
    ctx = f"IDE/PRODUK: {idea}\n"
    if target:
        ctx += f"TARGET USER/MARKET: {target}\n"
    answers = data.get("answers") or []
    if answers:
        ctx += "JAWABAN KLARIFIKASI USER:\n"
        for a in answers:
            q = (a.get("q") or "").strip()
            ans = (a.get("a") or "").strip()
            if q:
                ctx += f"- {q} => {ans if ans else '(tidak dijawab / bantu pilihkan)'}\n"
    return ctx


def build_prompt(step, data):
    ctx = _ctx(data)
    tech = (data.get("tech") or "").strip()
    if step == "clarify":
        return (
            f"{ctx}\n"
            "Buatkan 8 pertanyaan klarifikasi untuk mematangkan ide di atas, "
            "meliputi: tujuan utama, target pengguna, fitur utama, cara "
            "pesan/bayar/transaksi (bila relevan), konten/foto/media, cara "
            "kelola (admin/panel/stok/pesanan), akun & hak akses, dan teknologi. "
            "Sesuaikan pertanyaan dengan ide ini, jangan pakai template homestay "
            "atau toko bila idenya berbeda.\n"
            "KELUARKAN HANYA JSON valid, tanpa teks lain, tanpa code fence:\n"
            '{"questions": [{"q": "pertanyaan", '
            '"options": ["pilihan 1", "pilihan 2", "pilihan 3", '
            '"Tidak tahu, bantu pilihkan"]}]}\n'
            "Tiap pertanyaan wajib punya 3-4 opsi, opsi terakhir selalu "
            '"Tidak tahu, bantu pilihkan".'
        )
    if step == "workflow":
        if tech:
            ctx += f"TEKNOLOGI DIPILIH: {tech}\n"
        return (
            f"{ctx}\n"
            "Buatkan peta workflow/fitur dalam 3-4 fase implementasi, total "
            "6-10 fitur, masing-masing dengan 2-4 sub-fitur. Urutkan dari MVP "
            "dulu. Semua fitur berstatus Direncanakan.\n"
            "KELUARKAN HANYA JSON valid, tanpa teks lain, tanpa code fence:\n"
            '{"phases": [{"name": "FASE 1 Nama Fase", "features": '
            '[{"name": "Nama Fitur", "sub": ["Sub-fitur 1", "Sub-fitur 2"]}]}]}'
        )
    # prd
    wf = data.get("workflow")
    if wf:
        ctx += f"PETA WORKFLOW (JSON): {json.dumps(wf, ensure_ascii=False)}\n"
    if tech:
        ctx += f"TEKNOLOGI DIPILIH: {tech}\n"
    return (
        f"{ctx}\n"
        "Tuliskan PRD (Product Requirements Document) final yang lengkap untuk "
        "produk di atas, KONSISTEN dengan jawaban klarifikasi, teknologi, dan "
        "peta workflow di atas. Struktur wajib:\n"
        "## 1. Ringkasan & Visi\n"
        "## 2. Problem & Peluang\n"
        "## 3. Tujuan & Metrik Sukses (KPI)\n"
        "## 4. Target Pengguna & Persona\n"
        "## 5. User Stories (prioritas MoSCoW)\n"
        "## 6. Persyaratan Fungsional (FR) — diperinci, dengan acceptance criteria, "
        "dikelompokkan per fase workflow\n"
        "## 7. Persyaratan Non-Fungsional (NFR) — performance, security, scalability\n"
        "## 8. Teknologi & Arsitektur (sesuai teknologi yang dipilih)\n"
        "## 9. Di Luar Cakupan (Out of Scope)\n"
        "## 10. Milestone & Roadmap (per fase)\n"
        "## 11. Risiko & Open Questions\n"
    )


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._send(400, {"error": "Body JSON tidak valid"})
            return
        step = data.get("step", "")
        if step not in ("clarify", "workflow", "prd"):
            self._send(400, {"error": "step harus clarify, workflow, atau prd"})
            return
        if not (data.get("idea") or "").strip():
            self._send(400, {"error": "idea wajib diisi"})
            return
        model = (data.get("model") or "").strip() or "ilabs"
        try:
            raw = _call(build_prompt(step, data), model, 4096)
            if step == "prd":
                self._send(200, {"ok": True, "step": step, "content": raw})
            else:
                self._send(200, {"ok": True, "step": step, "data": _parse_json(raw)})
        except Exception as e:
            self._send(500, {"error": str(e)[:1000]})
            return

    def log_message(self, *args):
        pass
