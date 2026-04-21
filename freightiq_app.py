"""
FreightIQ — Air Freight Rate Quote Analyzer
Upload multiple carrier quotes, get a side-by-side comparison and recommendation.
Run with: python app.py
Open: http://localhost:5000
"""

import os
import json
import base64
import anthropic
from flask import Flask, request, jsonify, render_template_string
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024 * 10  # 10 files x 20MB

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}

# ── Prompts ───────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are an air freight rate analyst. Extract structured data from this rate quote document.

Return ONLY a JSON object with this exact format:
{
  "carrier": "carrier name",
  "quote_ref": "quote reference number",
  "valid_until": "expiry date as written",
  "origin": "origin airport code and city",
  "destination": "destination airport code and city",
  "routing": "routing description",
  "transit_days_min": number,
  "transit_days_max": number,
  "chargeable_weight_kg": number,
  "currency": "USD or other",
  "charges": [
    {"name": "charge name", "basis": "per KG / per AWB / flat", "rate": number, "amount": number}
  ],
  "total_amount": number,
  "rate_per_kg": number,
  "notes": ["any important notes, warnings, or flags from the terms section"]
}

For transit_days_min and transit_days_max: extract the numeric range (e.g. "3-4 business days" = min 3, max 4).
For rate_per_kg: calculate total_amount / chargeable_weight_kg.
Respond with ONLY the JSON object."""

COMPARISON_PROMPT = """You are a senior air freight procurement specialist. Analyze these carrier quotes and provide a recommendation.

QUOTES DATA:
{quotes_json}

Provide your analysis as a JSON object with this exact format:
{{
  "recommended_carrier": "carrier name",
  "recommendation_reason": "2-3 sentence explanation of why this carrier is recommended",
  "ranking": [
    {{
      "rank": 1,
      "carrier": "carrier name",
      "total_cost": number,
      "cost_per_kg": number,
      "transit_days": "X-Y days",
      "key_advantage": "main advantage in one phrase",
      "key_risk": "main risk or flag in one phrase"
    }}
  ],
  "flags": [
    {{
      "carrier": "carrier name",
      "flag_type": "EXPIRING_SOON | HIDDEN_CHARGE | HIGH_COST | SLOW_TRANSIT | OTHER",
      "message": "specific warning message"
    }}
  ],
  "cost_analysis": {{
    "cheapest_carrier": "name",
    "most_expensive_carrier": "name",
    "cost_difference": number,
    "cost_difference_pct": number
  }},
  "transit_analysis": {{
    "fastest_carrier": "name",
    "slowest_carrier": "name",
    "transit_difference_days": number
  }},
  "summary": "one paragraph executive summary of the market for this lane"
}}

Flag EXPIRING_SOON if valid_until is within 7 days of today (April 2026).
Flag HIDDEN_CHARGE if any charge seems unusual or not standard (e.g. hub transfer fees, special handling).
Be specific and data-driven in your analysis.
Respond with ONLY the JSON object."""

# ── Document processing ───────────────────────────────────────────────────────

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_quote(file_bytes, filename):
    """Extract structured data from a single quote document."""
    ext = filename.rsplit(".", 1)[1].lower()
    media_type_map = {
        "pdf": "application/pdf", "png": "image/png",
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"
    }
    media_type = media_type_map.get(ext, "application/pdf")
    encoded = base64.standard_b64encode(file_bytes).decode("utf-8")

    client = anthropic.Anthropic()

    doc_block = (
        {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
        if media_type == "application/pdf"
        else {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}
    )

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": [
            doc_block,
            {"type": "text", "text": EXTRACTION_PROMPT}
        ]}]
    )

    raw = response.content[0].text.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        return json.loads(raw[start:end])
    raise ValueError("Could not parse quote data")


def compare_quotes(quotes):
    """Compare all extracted quotes and produce a recommendation."""
    client = anthropic.Anthropic()
    quotes_json = json.dumps(quotes, indent=2)
    prompt = COMPARISON_PROMPT.format(quotes_json=quotes_json)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        return json.loads(raw[start:end])
    raise ValueError("Could not parse comparison")


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FreightIQ — Rate Quote Analyzer</title>
<meta property="og:title" content="FreightIQ — Air Freight Rate Analyzer">
<meta property="og:description" content="Upload multiple carrier quotes and get an instant side-by-side comparison with AI-powered recommendation.">
<meta property="og:image" content="https://raw.githubusercontent.com/irfaan-mukul/freightiq/main/freightiq_preview.png">
<meta property="og:url" content="https://freightiq.onrender.com">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Inter:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0c0e14;
    --surface: #13161f;
    --surface-2: #1a1e2e;
    --border: rgba(255,255,255,0.07);
    --border-2: rgba(255,255,255,0.12);
    --text: #e8eaf0;
    --text-mid: #8891a8;
    --text-light: #5a6278;
    --accent: #4fffb0;
    --accent-dim: rgba(79,255,176,0.12);
    --accent-border: rgba(79,255,176,0.25);
    --red: #ff5f6d;
    --yellow: #ffd166;
    --blue: #4cc9f0;
    --font-display: 'Syne', system-ui, sans-serif;
    --font-body: 'Inter', system-ui, sans-serif;
    --font-mono: 'JetBrains Mono', monospace;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font-body); min-height: 100vh; overflow-x: hidden; }

  /* Grid background */
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image: linear-gradient(rgba(79,255,176,0.03) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(79,255,176,0.03) 1px, transparent 1px);
    background-size: 48px 48px;
    pointer-events: none; z-index: 0;
  }

  .container { max-width: 960px; margin: 0 auto; padding: 40px 24px; position: relative; z-index: 1; }

  /* Header */
  header { text-align: center; margin-bottom: 52px; padding-top: 20px; }

  .logo { display: inline-flex; align-items: center; gap: 10px; margin-bottom: 20px; }
  .logo-icon { width: 40px; height: 40px; background: var(--accent); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 18px; }
  .logo-name { font-family: var(--font-display); font-size: 26px; font-weight: 800; color: var(--text); letter-spacing: -0.5px; }
  .logo-name span { color: var(--accent); }

  header p { color: var(--text-mid); font-size: 15px; font-weight: 300; max-width: 440px; margin: 0 auto; line-height: 1.6; }

  /* Upload zone */
  .upload-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 36px;
    margin-bottom: 28px;
    position: relative;
    overflow: hidden;
  }

  .upload-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
  }

  .upload-label {
    font-family: var(--font-display);
    font-size: 13px;
    font-weight: 600;
    color: var(--accent);
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 16px;
    display: block;
  }

  .drop-zone {
    border: 1.5px dashed rgba(79,255,176,0.25);
    border-radius: 12px;
    padding: 36px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    position: relative;
  }

  .drop-zone:hover, .drop-zone.dragover {
    border-color: var(--accent);
    background: var(--accent-dim);
  }

  .drop-zone input[type="file"] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }

  .drop-icon { font-size: 32px; margin-bottom: 10px; display: block; }
  .drop-title { font-family: var(--font-display); font-size: 16px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
  .drop-sub { font-size: 13px; color: var(--text-mid); }

  /* File list */
  .file-list { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }

  .file-item {
    display: flex; align-items: center; gap: 10px;
    background: var(--surface-2); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 14px;
    animation: slideIn 0.2s ease;
  }

  @keyframes slideIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } }

  .file-item .file-name { font-family: var(--font-mono); font-size: 12px; color: var(--accent); flex: 1; }
  .file-item .file-remove { background: none; border: none; color: var(--text-light); cursor: pointer; font-size: 16px; padding: 0 4px; transition: color 0.2s; }
  .file-item .file-remove:hover { color: var(--red); }

  .file-count { font-size: 12px; color: var(--text-mid); margin-top: 8px; }

  /* Analyze button */
  .btn-analyze {
    width: 100%; margin-top: 20px; padding: 16px;
    background: var(--accent); color: var(--bg);
    border: none; border-radius: 10px;
    font-family: var(--font-display); font-size: 15px; font-weight: 700;
    cursor: pointer; transition: all 0.2s; letter-spacing: 0.5px;
    display: flex; align-items: center; justify-content: center; gap: 8px;
  }

  .btn-analyze:hover { transform: translateY(-1px); box-shadow: 0 8px 28px rgba(79,255,176,0.25); }
  .btn-analyze:active { transform: translateY(0); }
  .btn-analyze:disabled { opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none; }

  /* Loading */
  .loading { display: none; text-align: center; padding: 56px 32px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; margin-bottom: 28px; }
  .loading.visible { display: block; }

  .loading-steps { display: flex; flex-direction: column; gap: 10px; max-width: 320px; margin: 20px auto 0; }
  .loading-step { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-mid); }
  .step-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--border-2); flex-shrink: 0; transition: background 0.3s; }
  .loading-step.active .step-dot { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
  .loading-step.active { color: var(--text); }

  .spinner { width: 40px; height: 40px; border: 2px solid rgba(79,255,176,0.15); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.7s linear infinite; margin: 0 auto 16px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading strong { font-family: var(--font-display); font-size: 18px; color: var(--text); display: block; margin-bottom: 4px; }
  .loading p { font-size: 13px; color: var(--text-mid); }

  /* Results */
  #results { display: none; }
  #results.visible { display: block; }

  /* Recommendation banner */
  .rec-banner {
    background: var(--accent-dim);
    border: 1px solid var(--accent-border);
    border-radius: 14px; padding: 24px 28px;
    margin-bottom: 24px; display: flex; gap: 18px; align-items: flex-start;
  }

  .rec-icon { font-size: 32px; flex-shrink: 0; }
  .rec-label { font-family: var(--font-mono); font-size: 10px; color: var(--accent); letter-spacing: 2px; text-transform: uppercase; margin-bottom: 4px; }
  .rec-carrier { font-family: var(--font-display); font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
  .rec-reason { font-size: 14px; color: var(--text-mid); line-height: 1.6; }

  /* Flags */
  .flags-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }

  .flag {
    display: flex; align-items: center; gap: 6px;
    padding: 7px 14px; border-radius: 6px;
    font-size: 12px; font-weight: 500;
  }

  .flag.EXPIRING_SOON { background: rgba(255,209,102,0.12); border: 1px solid rgba(255,209,102,0.3); color: var(--yellow); }
  .flag.HIDDEN_CHARGE { background: rgba(255,95,109,0.12); border: 1px solid rgba(255,95,109,0.3); color: var(--red); }
  .flag.HIGH_COST { background: rgba(255,95,109,0.08); border: 1px solid rgba(255,95,109,0.2); color: var(--red); }
  .flag.OTHER { background: rgba(76,201,240,0.1); border: 1px solid rgba(76,201,240,0.2); color: var(--blue); }

  /* Comparison table */
  .section-title { font-family: var(--font-display); font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }

  .comparison-table { width: 100%; border-collapse: collapse; margin-bottom: 28px; font-size: 13px; }
  .comparison-table th { background: var(--surface-2); color: var(--text-mid); font-weight: 500; padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
  .comparison-table td { padding: 14px 16px; border-bottom: 1px solid var(--border); color: var(--text); background: var(--surface); vertical-align: top; }
  .comparison-table tr:last-child td { border-bottom: none; }
  .comparison-table tr.recommended td { background: var(--accent-dim); border-left: 3px solid var(--accent); }
  .comparison-table tr.recommended td:first-child { padding-left: 13px; }

  .rank-badge { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 50%; font-family: var(--font-mono); font-size: 11px; font-weight: 600; }
  .rank-1 { background: var(--accent); color: var(--bg); }
  .rank-2 { background: var(--surface-2); color: var(--text-mid); border: 1px solid var(--border-2); }
  .rank-3 { background: var(--surface-2); color: var(--text-mid); border: 1px solid var(--border-2); }

  .carrier-name { font-family: var(--font-display); font-weight: 600; font-size: 14px; }
  .cost-main { font-family: var(--font-mono); font-size: 15px; font-weight: 500; color: var(--accent); }
  .cost-sub { font-size: 11px; color: var(--text-mid); margin-top: 2px; }
  .transit-val { font-family: var(--font-mono); font-size: 14px; }

  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 2px 2px 2px 0; }
  .tag-green { background: rgba(79,255,176,0.1); color: var(--accent); }
  .tag-red { background: rgba(255,95,109,0.1); color: var(--red); }
  .tag-yellow { background: rgba(255,209,102,0.1); color: var(--yellow); }

  /* Charge breakdown */
  .charge-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; margin-bottom: 28px; }

  .charge-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .charge-card-header { background: var(--surface-2); padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); }
  .charge-card-carrier { font-family: var(--font-display); font-size: 13px; font-weight: 600; }
  .charge-card-total { font-family: var(--font-mono); font-size: 13px; color: var(--accent); }
  .charge-list { padding: 12px 16px; }
  .charge-row { display: flex; justify-content: space-between; padding: 5px 0; font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.04); }
  .charge-row:last-child { border-bottom: none; }
  .charge-name { color: var(--text-mid); }
  .charge-amount { font-family: var(--font-mono); color: var(--text); }

  /* Summary */
  .summary-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px 24px; margin-bottom: 28px; }
  .summary-card p { font-size: 14px; color: var(--text-mid); line-height: 1.7; }

  /* Reset button */
  .btn-reset { background: transparent; border: 1px solid var(--border); color: var(--text-mid); padding: 12px 24px; border-radius: 8px; font-family: var(--font-body); font-size: 14px; cursor: pointer; transition: all 0.2s; display: block; margin: 0 auto; }
  .btn-reset:hover { border-color: var(--text-mid); color: var(--text); }

  /* Help section */
  .help-toggle {
    display: flex; align-items: center; justify-content: center; gap: 8px;
    background: transparent; border: 1px solid var(--border);
    color: var(--accent); padding: 10px 20px; border-radius: 8px;
    font-family: var(--font-body); font-size: 13px; font-weight: 500;
    cursor: pointer; transition: all 0.2s; margin: 0 auto 24px;
    letter-spacing: 0.3px;
  }
  .help-toggle:hover { border-color: var(--accent); background: var(--accent-dim); }
  .help-toggle .arrow { transition: transform 0.2s; font-size: 11px; }
  .help-toggle.open .arrow { transform: rotate(180deg); }

  .help-panel {
    display: none; background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 32px; margin-bottom: 28px; position: relative; overflow: hidden;
  }
  .help-panel::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
  }
  .help-panel.visible { display: block; }

  .help-section { margin-bottom: 24px; }
  .help-section:last-child { margin-bottom: 0; }
  .help-section h3 { font-family: var(--font-display); font-size: 15px; font-weight: 700; color: var(--accent); margin-bottom: 10px; }
  .help-section p { font-size: 13px; color: var(--text-mid); line-height: 1.7; margin-bottom: 6px; }

  .help-steps { list-style: none; padding: 0; counter-reset: steps; }
  .help-steps li {
    counter-increment: steps; display: flex; gap: 12px;
    margin-bottom: 12px; font-size: 13px; color: var(--text); line-height: 1.6;
  }
  .help-steps li::before {
    content: counter(steps); flex-shrink: 0; width: 24px; height: 24px;
    background: var(--accent-dim); color: var(--accent); border: 1px solid var(--accent-border);
    border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-family: var(--font-mono); font-size: 11px; font-weight: 600; margin-top: 1px;
  }

  .help-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
  .help-item {
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; display: flex; align-items: center; gap: 8px;
    font-size: 13px; color: var(--text-mid);
  }

  .flag-legend { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
  .flag-item { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; color: var(--text-mid); }
  .flag-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }

  @media (max-width: 600px) { .help-grid { grid-template-columns: 1fr; } }

  footer { text-align: center; padding: 32px 0 16px; color: var(--text-light); font-size: 12px; position: relative; z-index: 1; }

  @media (max-width: 600px) {
    .charge-cards { grid-template-columns: 1fr; }
    .comparison-table { font-size: 12px; }
    .comparison-table th, .comparison-table td { padding: 10px 10px; }
  }
</style>
</head>
<body>

<div class="container">
  <header>
    <div class="logo">
      <div class="logo-icon">✈</div>
      <div class="logo-name">Freight<span>IQ</span></div>
    </div>
    <p>Upload air freight rate quotes from multiple carriers and get an instant comparison with AI-powered recommendation.</p>
  </header>

  <!-- Help toggle -->
  <button class="help-toggle" id="helpToggle" onclick="toggleHelp()">
    <span>📖</span> How It Works <span class="arrow">▾</span>
  </button>

  <!-- Help panel -->
  <div class="help-panel" id="helpPanel">

    <div class="help-section">
      <h3>What FreightIQ Does</h3>
      <p>FreightIQ uses AI to read and compare air freight rate quotes from multiple carriers. It extracts all charges, normalizes them for comparison, flags risks like expiring quotes or hidden fees, and recommends the best option for your shipment.</p>
    </div>

    <div class="help-section">
      <h3>How to Use It</h3>
      <ol class="help-steps">
        <li>Collect rate quotes from 2 or more carriers in PDF or image format.</li>
        <li>Upload all quotes at once by dragging them onto the upload area or clicking to browse. You can upload up to 6 quotes per analysis.</li>
        <li>Click <strong>Analyze Quotes</strong> and wait 20–40 seconds while the AI reads each quote and runs the comparison.</li>
        <li>Review the results — the recommended carrier is shown at the top, followed by a side-by-side comparison table, individual charge breakdowns, and a market summary.</li>
      </ol>
    </div>

    <div class="help-section">
      <h3>Supported Document Types</h3>
      <div class="help-grid">
        <div class="help-item">✈️ Air Freight Rate Quotes</div>
        <div class="help-item">📧 Email Quote Screenshots</div>
        <div class="help-item">📄 PDF Rate Sheets</div>
        <div class="help-item">🖼️ PNG / JPG Images</div>
      </div>
      <p style="margin-top:10px;">Accepted formats: PDF, PNG, JPG — up to 20MB per file. Up to 6 quotes per session.</p>
    </div>

    <div class="help-section">
      <h3>What FreightIQ Analyzes</h3>
      <p>For each quote, the AI extracts: carrier name, routing and transit time, chargeable weight, base freight rate, all surcharges (FSC, security, terminal, handling), total all-in cost, validity date, and any special terms. It then compares all quotes on cost per kg, total cost, transit time, and flags any risks.</p>
    </div>

    <div class="help-section">
      <h3>Understanding the Flags</h3>
      <div class="flag-legend">
        <div class="flag-item"><div class="flag-dot" style="background:#ffd166;"></div><div><strong style="color:#ffd166;">Expiring Soon</strong> — Quote validity expires within 7 days. Book immediately or request an extension.</div></div>
        <div class="flag-item"><div class="flag-dot" style="background:#ff5f6d;"></div><div><strong style="color:#ff5f6d;">Hidden Charge</strong> — An unusual or non-standard fee was detected that may not be obvious at first glance.</div></div>
        <div class="flag-item"><div class="flag-dot" style="background:#ff5f6d;"></div><div><strong style="color:#ff5f6d;">High Cost</strong> — This carrier is significantly more expensive than the alternatives on this lane.</div></div>
        <div class="flag-item"><div class="flag-dot" style="background:#4cc9f0;"></div><div><strong style="color:#4cc9f0;">Other</strong> — Informational note worth reviewing before booking.</div></div>
      </div>
    </div>

    <div class="help-section">
      <h3>Important Notes</h3>
      <p>FreightIQ is a procurement analysis tool — it does not book shipments or replace your freight forwarder. Always verify the final rate and terms directly with your carrier before confirming. Rates are subject to space availability and carrier conditions. Documents are processed in real-time and are not stored on our servers.</p>
    </div>

  </div>

  <!-- Upload -->
  <div class="upload-card" id="uploadSection">
    <span class="upload-label">Upload Rate Quotes</span>
    <div class="drop-zone" id="dropZone">
      <input type="file" id="fileInput" accept=".pdf,.png,.jpg,.jpeg,.webp" multiple>
      <span class="drop-icon">📂</span>
      <div class="drop-title">Drop carrier quotes here</div>
      <div class="drop-sub">Upload 2–6 quotes · PDF, PNG, or JPG · Up to 20MB each</div>
    </div>
    <div class="file-list" id="fileList"></div>
    <div class="file-count" id="fileCount"></div>
    <button class="btn-analyze" id="analyzeBtn" disabled onclick="runAnalysis()">
      <span>⚡</span> Analyze Quotes
    </button>
  </div>

  <!-- Loading -->
  <div class="loading" id="loading">
    <div class="spinner"></div>
    <strong>Analyzing Quotes</strong>
    <p>Extracting data from each carrier quote...</p>
    <div class="loading-steps" id="loadingSteps"></div>
  </div>

  <!-- Results -->
  <div id="results">
    <!-- Recommendation -->
    <div class="rec-banner">
      <div class="rec-icon">🏆</div>
      <div>
        <div class="rec-label">Recommended Carrier</div>
        <div class="rec-carrier" id="recCarrier"></div>
        <div class="rec-reason" id="recReason"></div>
      </div>
    </div>

    <!-- Flags -->
    <div class="flags-row" id="flagsRow"></div>

    <!-- Comparison table -->
    <div class="section-title">📊 Side-by-Side Comparison</div>
    <table class="comparison-table" id="compTable">
      <thead>
        <tr>
          <th>Rank</th>
          <th>Carrier</th>
          <th>All-In Cost</th>
          <th>Transit Time</th>
          <th>Key Advantage</th>
          <th>Risk / Flag</th>
        </tr>
      </thead>
      <tbody id="compBody"></tbody>
    </table>

    <!-- Charge breakdown -->
    <div class="section-title">💰 Charge Breakdown by Carrier</div>
    <div class="charge-cards" id="chargeCards"></div>

    <!-- Market summary -->
    <div class="section-title">📋 Market Summary</div>
    <div class="summary-card">
      <p id="summaryText"></p>
    </div>

    <button class="btn-reset" onclick="resetForm()">← Analyze New Quotes</button>
  </div>
</div>

<footer>FreightIQ &nbsp;·&nbsp; Powered by Claude AI &nbsp;·&nbsp; For procurement guidance only</footer>

<script>
  const fileInput = document.getElementById('fileInput');
  const dropZone = document.getElementById('dropZone');
  const fileList = document.getElementById('fileList');
  const fileCount = document.getElementById('fileCount');
  const analyzeBtn = document.getElementById('analyzeBtn');
  let selectedFiles = [];

  fileInput.addEventListener('change', e => {
    addFiles(Array.from(e.target.files));
    fileInput.value = '';
  });

  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    addFiles(Array.from(e.dataTransfer.files));
  });

  function addFiles(files) {
    files.forEach(f => {
      if (selectedFiles.length < 6 && !selectedFiles.find(x => x.name === f.name)) {
        selectedFiles.push(f);
      }
    });
    renderFileList();
  }

  function removeFile(i) {
    selectedFiles.splice(i, 1);
    renderFileList();
  }

  function renderFileList() {
    fileList.innerHTML = selectedFiles.map((f, i) => `
      <div class="file-item">
        <span style="font-size:16px;">📄</span>
        <span class="file-name">${f.name}</span>
        <button class="file-remove" onclick="removeFile(${i})">✕</button>
      </div>`).join('');
    fileCount.textContent = selectedFiles.length > 0
      ? `${selectedFiles.length} quote${selectedFiles.length > 1 ? 's' : ''} selected${selectedFiles.length < 2 ? ' — add at least 1 more to compare' : ''}`
      : '';
    analyzeBtn.disabled = selectedFiles.length < 2;
  }

  async function runAnalysis() {
    if (selectedFiles.length < 2) return;

    document.getElementById('uploadSection').style.display = 'none';
    document.getElementById('loading').classList.add('visible');
    document.getElementById('results').classList.remove('visible');

    // Show loading steps
    const steps = document.getElementById('loadingSteps');
    steps.innerHTML = selectedFiles.map((f, i) =>
      `<div class="loading-step" id="step${i}"><div class="step-dot"></div>Extracting: ${f.name}</div>`
    ).join('') + `<div class="loading-step" id="stepFinal"><div class="step-dot"></div>Comparing all carriers...</div>`;

    const formData = new FormData();
    selectedFiles.forEach((f, i) => {
      formData.append('files', f);
      setTimeout(() => {
        document.getElementById(`step${i}`)?.classList.add('active');
      }, i * 800);
    });

    setTimeout(() => document.getElementById('stepFinal')?.classList.add('active'), selectedFiles.length * 800);

    try {
      const res = await fetch('/analyze', { method: 'POST', body: formData });
      const data = await res.json();
      document.getElementById('loading').classList.remove('visible');
      if (data.error) {
        alert('Error: ' + data.error);
        resetForm();
      } else {
        renderResults(data);
      }
    } catch (err) {
      alert('Something went wrong. Please try again.');
      resetForm();
    }
  }

  function renderResults(data) {
    const comparison = data.comparison;
    const quotes = data.quotes;

    // Recommendation
    document.getElementById('recCarrier').textContent = comparison.recommended_carrier || '';
    document.getElementById('recReason').textContent = comparison.recommendation_reason || '';

    // Flags
    const flagsRow = document.getElementById('flagsRow');
    const flags = comparison.flags || [];
    if (flags.length > 0) {
      const icons = { EXPIRING_SOON: '⏰', HIDDEN_CHARGE: '⚠️', HIGH_COST: '💸', OTHER: 'ℹ️' };
      flagsRow.innerHTML = flags.map(f =>
        `<div class="flag ${f.flag_type}">${icons[f.flag_type] || 'ℹ️'} <strong>${f.carrier}:</strong> ${f.message}</div>`
      ).join('');
    }

    // Comparison table
    const compBody = document.getElementById('compBody');
    const ranking = comparison.ranking || [];
    compBody.innerHTML = ranking.map(r => `
      <tr class="${r.rank === 1 ? 'recommended' : ''}">
        <td><span class="rank-badge rank-${r.rank}">${r.rank}</span></td>
        <td><div class="carrier-name">${r.carrier}</div></td>
        <td>
          <div class="cost-main">$${r.total_cost?.toLocaleString()}</div>
          <div class="cost-sub">$${r.cost_per_kg?.toFixed(2)}/kg</div>
        </td>
        <td><span class="transit-val">${r.transit_days}</span></td>
        <td><span class="tag tag-green">${r.key_advantage}</span></td>
        <td><span class="tag tag-red">${r.key_risk}</span></td>
      </tr>`).join('');

    // Charge breakdown cards
    const chargeCards = document.getElementById('chargeCards');
    chargeCards.innerHTML = quotes.map(q => `
      <div class="charge-card">
        <div class="charge-card-header">
          <span class="charge-card-carrier">${q.carrier}</span>
          <span class="charge-card-total">$${q.total_amount?.toLocaleString()}</span>
        </div>
        <div class="charge-list">
          ${(q.charges || []).map(c => `
            <div class="charge-row">
              <span class="charge-name">${c.name}</span>
              <span class="charge-amount">$${c.amount?.toLocaleString()}</span>
            </div>`).join('')}
        </div>
      </div>`).join('');

    // Summary
    document.getElementById('summaryText').textContent = comparison.summary || '';

    document.getElementById('results').classList.add('visible');
    document.getElementById('results').scrollIntoView({ behavior: 'smooth' });
  }

  function toggleHelp() {
    const panel = document.getElementById('helpPanel');
    const toggle = document.getElementById('helpToggle');
    panel.classList.toggle('visible');
    toggle.classList.toggle('open');
  }

  function resetForm() {
    selectedFiles = [];
    renderFileList();
    document.getElementById('uploadSection').style.display = 'block';
    document.getElementById('loading').classList.remove('visible');
    document.getElementById('results').classList.remove('visible');
    document.getElementById('flagsRow').innerHTML = '';
    document.getElementById('compBody').innerHTML = '';
    document.getElementById('chargeCards').innerHTML = '';
  }
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/analyze", methods=["POST"])
def analyze():
    files = request.files.getlist("files")
    if not files or len(files) < 2:
        return jsonify({"error": "Please upload at least 2 quotes to compare"}), 400

    quotes = []
    for file in files:
        if not file.filename or not allowed_file(file.filename):
            return jsonify({"error": f"Invalid file type: {file.filename}"}), 400
        try:
            file_bytes = file.read()
            filename = secure_filename(file.filename)
            quote_data = extract_quote(file_bytes, filename)
            quotes.append(quote_data)
        except Exception as e:
            return jsonify({"error": f"Could not read {file.filename}: {str(e)}"}), 500

    try:
        comparison = compare_quotes(quotes)
    except Exception as e:
        return jsonify({"error": f"Comparison failed: {str(e)}"}), 500

    return jsonify({"quotes": quotes, "comparison": comparison})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_ENV") != "production"
    print(f"\nFreightIQ running at http://localhost:{port}")
    print("Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
