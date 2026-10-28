#!/usr/bin/env python3
"""
DocGen·AI — auto-generation web app (PRD / Workflow / Saran / Auto-audit).
Backend provider-agnostic:
  1. hermes  -> jalankan `hermes -z` lokal (pakai model/provider konfigurasi Hermes)
  2. openai  -> OpenAI-compatible endpoint (OpenRouter / 9ROUTER dll) via base URL + API key
Backend holds secrets: API key dimasukkan lewat UI, dikirim per-request,
tidak disimpan di disk.
"""
import os, subprocess, json, re
from flask import Flask, request, jsonify, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
DOCTYPES = {"prd", "workflow", "suggestions", "audit"}

app = Flask(__name__, static_folder=STATIC)

HERMES_FOOTER = "You run on Hermes Agent"
HERMES_EXE = os.environ.get("HERMES_EXE", "hermes")
HERMES_TIMEOUT = int(os.environ.get("DOCGEN_HERMES_TIMEOUT", "420"))


# ----------------------------------------------------------------------------
# Provider runners
# ----------------------------------------------------------------------------
def run_hermes(prompt, model=None):
    """Jalankan hermes -z, ambil respons murni (strip footer + UI chrome)."""
    cmd = [HERMES_EXE, "-z", prompt]
    if model and model.strip() and model.lower() not in ("auto", "default", ""):
        cmd += ["-m", model.strip()]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=HERMES_TIMEOUT, encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    idx = out.find(HERMES_FOOTER)
    if idx != -1:
        out = out[:idx]
    out = out.strip()
    if not out:
        raise RuntimeError(f"Hermes tidak mengembalikan output (exit={proc.returncode})")
    return out


def run_openai(base_url, api_key, model, messages, timeout=420):
    import requests
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 4096,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:500]
        raise RuntimeError(f"Provider error {r.status_code}: {detail}")
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Format respons tidak dikenal: {str(data)[:500]}")


# ----------------------------------------------------------------------------
# Prompt builders
# ----------------------------------------------------------------------------
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
    req = payload.get("req", "").strip()  # requirement asli utk audit compliance

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
    # audit
    docs = {
        k: payload.get(k, "") for k in ("prd", "workflow", "suggestions")
    }
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


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    doc_type = data.get("doc_type", "")
    if doc_type not in DOCTYPES:
        return jsonify({"error": f"doc_type tidak valid: {doc_type}"}), 400

    provider = data.get("provider", "hermes")
    prompt = build_prompt(doc_type, data)

    try:
        if provider == "openai":
            base_url = data.get("base_url", "").strip()
            api_key = data.get("api_key", "").strip()
            model = data.get("model", "").strip()
            if not base_url or not api_key or not model:
                return jsonify({"error": "Provider openai butuh base_url, api_key, dan model"}), 400
            content = run_openai(
                base_url, api_key, model,
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": prompt}],
            )
        else:
            model = data.get("model", "")  # optional override utk hermes
            content = run_hermes(prompt, model=model)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout: proses generate terlalu lama (>%ds)" % HERMES_TIMEOUT}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "doc_type": doc_type, "content": content})


if __name__ == "__main__":
    port = int(os.environ.get("DOCGEN_PORT", "8080"))
    # 0.0.0.0 supaya bisa diakses dari device lain di LAN; ganti ke 127.0.0.1 utk lokal-only
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
