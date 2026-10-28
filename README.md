# DocGen·AI — Web App Auto-generation (PRD / Workflow / Saran / Auto-Audit)

Generate dokumen produk berbasis LLM.

## Vercel (live)

- Frontend: `index.html` di root (disajikan statis oleh Vercel).
- Backend: `api/generate.py` — serverless function Python stdlib-only,
  `POST /api/generate` dengan body JSON yang sama seperti versi Flask.
- **Di Vercel hanya provider `openai` (OpenAI-compatible) yang jalan** —
  isi `base_url` + `api_key` + `model` di UI (mis. 9Router / OpenRouter).
  Provider `hermes` butuh binary `hermes` lokal, jadi tidak tersedia di
  Vercel dan API akan menolaknya dengan pesan yang jelas.
- API key dikirim per-request dari browser, TIDAK disimpan di disk/server.
- Batas durasi function Vercel: 60 detik (timeout upstream diset 50 detik).

## Lokal (Flask, hermes + openai)

Persyaratan: Python 3.10+, `pip install flask requests`, opsional binary
`hermes` di PATH.

```bash
pip install flask requests
python3 app.py            # default port 8080, host 0.0.0.0
# atau
DOCGEN_PORT=9000 python3 app.py
# HERMES_EXE=/path/hermes DOCGEN_HERMES_TIMEOUT=420 python3 app.py
```

Buka `http://<host>:8080`. Versi lokal menyajikan `static/index.html`
dan mendukung provider `hermes` maupun `openai`.

## API

`POST /api/generate` — body JSON:

```json
{
  "doc_type": "prd|workflow|suggestions|audit",
  "provider": "hermes|openai",
  "idea": "...",
  "target": "...", "req": "...", "extra": "...",
  "prd": "", "workflow": "", "suggestions": "",
  "base_url": "...", "api_key": "...", "model": "..."
}
```

Response: `{"ok": true, "doc_type": "...", "content": "<markdown>"}`

Catatan: `req` (requirement asli) hanya dipakai pada `doc_type=audit`
sebagai lapisan kepatuhan.

## Struktur

- `app.py` — backend Flask lokal: provider runners + prompt builders + routes
- `api/generate.py` — backend Vercel serverless (stdlib-only, provider openai)
- `index.html` — frontend untuk Vercel (default provider openai)
- `static/index.html` — frontend untuk run Flask lokal (default provider hermes)
- `vercel.json` — konfigurasi durasi function Vercel

## Keamanan

- API key openai dikirim per-request dari browser, TIDAK disimpan di disk.
- Jika hanya akses lokal: ganti `host` di `app.py` dari `0.0.0.0` → `127.0.0.1`.
