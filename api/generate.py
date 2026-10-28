"""Vercel serverless function for DocGen·AI: POST /api/generate.

Stdlib only (no Flask, no requests) so Vercel needs no install step.
Provider note: `hermes` needs a local `hermes` binary, which does not
exist on Vercel, so on Vercel only `openai` (OpenAI-compatible endpoint,
e.g. 9Router / OpenRouter) works. The original Flask app (app.py) still
supports both providers when run locally.
"""
import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

DOCTYPES = {"prd", "workflow", "suggestions", "audit"}
NINE_BASE = "https://aws.jarvisrais.my.id/v1"
NINE_MODELS = ("mangoboost", "ilabs", "gonka", "gonka-ds", "okai")

SYSTEM = (
    "Kamu adalah CTO/Product consultant yang membangun dokumen produk tingkat"
    " enterprise. Keluarkan dokumen yang lengkap, terstruktur, bisa langsung"
    " dipakai. Pakai Markdown dengan heading dan bullet. Jangan tambahkan"
    " disclaimer atau pembukaan basa-basi. Bahasa: Indonesia."
)


def build_prompt(doc_type, payload):
    idea = payload.get("idea", "").strip()
    target = payload.get("target", "").strip()
    extra = payload.get("extra", "").strip()
    ctx = f"IDE/PRODUK: {idea}\n"
    if target:
        ctx += f"TARGET USER/MARKET: {target}\n"
    if extra:
        ctx += f"KONTEKS TAMBAHAN: {extra}\n"
    if doc_type == "prd":
        return (
            f"{ctx}\n"
            "Tuliskan PRD (Product Requirements Document) yang lengkap untuk produk di atas. "
            "Struktur wajib:\n"
            "## 1. Ringkasan & Visi\n"
            "## 2. Problem & Peluang\n"
            "## 3. Tujuan & Metrik Sukses (KPI)\n"
            "## 4. Target Pengguna & Persona\n"
            "## 5. User Stories (prioritas MoSCoW)\n"
            "## 6. Persyaratan Fungsional (FR) — diperinci, dengan acceptance criteria\n"
            "## 7. Persyaratan Non-Fungsional (NFR) — performance, security, scalability\n"
            "## 8. Di Luar Cakupan (Out of Scope)\n"
            "## 9. Milestone & Roadmap\n"
            "## 10. Risiko & Open Questions\n"
        )
    if doc_type == "workflow":
        return (
            f"{ctx}\n"
            "Tuliskan workflow/alur proses end-to-end untuk produk di atas. "
            "Sertakan:\n"
            "- Tahapan utama (numbered steps) dari trigger sampai selesai\n"
            "- Decision points (percabangan) dengan kondisi eksplisit\n"
            "- Input/output tiap tahapan\n"
            "- Actors/system yang terlibat (user, backend, third-party)\n"
            "- Error handling & edge cases\n"
            "- Jika relevan, tampilkan juga skema Mermaid atau pseudo-flow berbasis teks (indent)\n"
        )
    if doc_type == "suggestions":
        return (
            f"{ctx}\n"
            "Berikan saran tambahan yang tajam dan actionable untuk produk di atas, "
            "dalam kategori:\n"
            "- Fitur yang belum terpikir (dengan alasan & impact)\n"
            "- Strategi growth & akuisisi\n"
            "- Monetisasi\n"
            "- Trade-off teknis / arsitektur\n"
            "- Risiko yang sering terlewat + mitigasi\n"
            "Prioritaskan: High / Medium / Low impact untuk tiap saran.\n"
        )
    docs = {k: payload.get(k, "") for k in ("prd", "workflow", "suggestions")}
    return (
        f"{ctx}\n"
        f"PRD TERGENERATE:\n{docs['prd'] if docs['prd'] else '(belum ada)'}\n\n"
        f"WORKFLOW TERGENERATE:\n{docs['workflow'] if docs['workflow'] else '(belum ada)'}\n\n"
        f"SARAN TERGENERATE:\n{docs['suggestions'] if docs['suggestions'] else '(belum ada)'}\n\n"
        "Lakukan AUTO-AUDIT dengan DUA lapisan:\n"
        "Lapisan 1 — AUDIT KONTEN (kualitas dokumen):\n"
        "- Kelengkapan struktur (apakah semua section PRD ada?)\n"
        "- Kekhususan & ketajaman (vague? generik?)\n"
        "- Kredibilitas: klaim metrik/target yang realistis?\n"
        "- Konsistensi internal antar dokumen (PRD vs Workflow vs Saran)\n"
        "Lapisan 2 — AUDIT COMPLIANCE (kepatuhan terhadap requirement asli):\n"
        "- Bandingkan tiap requirement asli dengan cakupan dokumen\n"
        "- Tandai yang TIDAK tercakup (gap) dengan tegas\n"
        "Format output wajib:\n"
        "## Ringkasan Audit (nilai A-F + skor /100)\n"
        "## Temuan (list dengan severity: Critical/High/Medium/Low + bukti singkat)\n"
        "## Kepatuhan Requirement (tabel/checklist: requirement -> status Covered/Partial/Gap)\n"
        "## Rekomendasi Perbaikan (actionable)\n"
    )


def run_openai(base_url, api_key, model, prompt):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.6,
        "max_tokens": 4096,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=50) as resp:
            text = resp.read().decode("utf-8")
            # 9Router non-stream responses append an SSE trailer "data: [DONE]"
            # after the JSON body; strip it before parsing.
            if "data: [DONE]" in text:
                text = text.split("data: [DONE]")[0].strip()
            data = json.loads(text)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Provider error {e.code}: {detail}")
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Format respons tidak dikenal: {str(data)[:500]}")


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
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
        doc_type = data.get("doc_type", "")
        if doc_type not in DOCTYPES:
            self._send(400, {"error": f"doc_type tidak valid: {doc_type}"})
            return
        if not data.get("idea", "").strip():
            self._send(400, {"error": "idea wajib diisi"})
            return
        provider = data.get("provider", "openai")
        if provider == "9router":
            # Full auto: key lives only as a Vercel env var, never in the repo
            # or the browser. Model comes from the UI dropdown, default mangoboost.
            base_url = NINE_BASE
            api_key = os.environ.get("DOCGEN_9ROUTER_API_KEY", "")
            model = (data.get("model") or "").strip() or "mangoboost"
            if not api_key:
                self._send(500, {"error": "Key 9Router belum diset sebagai env var DOCGEN_9ROUTER_API_KEY di Vercel."})
                return
        elif provider == "openai":
            base_url = (data.get("base_url") or "").strip()
            api_key = (data.get("api_key") or "").strip()
            model = (data.get("model") or "").strip()
            if not base_url or not api_key or not model:
                self._send(400, {"error": "Provider openai butuh base_url, api_key, dan model"})
                return
        else:
            self._send(400, {"error": "Di Vercel provider hermes tidak tersedia (butuh binary hermes lokal). Pakai 9Router (auto) atau OpenAI-compatible."})
            return
        try:
            content = run_openai(base_url, api_key, model, build_prompt(doc_type, data))
        except Exception as e:
            self._send(500, {"error": str(e)})
            return
        self._send(200, {"ok": True, "doc_type": doc_type, "content": content})

    def log_message(self, *args):
        pass
