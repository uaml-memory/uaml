"""
UAML Email Templates
~~~~~~~~~~~~~~~~~~~~

Bilingual (EN/CS) email templates for license lifecycle events.
Each function returns ``{subject, body_html, body_text}``.
"""

from __future__ import annotations

import html as html_mod
from typing import Dict

# ---------------------------------------------------------------------------
# Shared HTML scaffold
# ---------------------------------------------------------------------------

_CSS = """
body { margin:0; padding:0; background:#f4f4f7; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }
.wrapper { max-width:600px; margin:0 auto; background:#fff; }
.header { background:#0f3460; color:#fff; padding:28px 32px; }
.header h1 { margin:0; font-size:22px; letter-spacing:0.5px; }
.header .sub { font-size:13px; color:#a8c0e8; margin-top:4px; }
.content { padding:32px; color:#1a1a2e; font-size:14px; line-height:1.6; }
.content h2 { font-size:18px; color:#0f3460; margin:0 0 16px; }
.license-box {
    background:#f0f4fa; border:1px solid #c8d6e5; border-radius:8px;
    padding:16px 20px; margin:20px 0; text-align:center;
}
.license-box .key { font-size:18px; font-weight:700; color:#0f3460; letter-spacing:1px; font-family:monospace; }
.license-box .hint { font-size:12px; color:#888; margin-top:8px; }
.activation {
    background:#e8f5e9; border-left:4px solid #43a047; padding:12px 16px;
    margin:20px 0; border-radius:0 6px 6px 0;
}
.activation code { font-size:13px; color:#2e7d32; }
.invoice-note { background:#fff8e1; border-left:4px solid #f9a825; padding:12px 16px; margin:20px 0; border-radius:0 6px 6px 0; font-size:13px; }
.footer {
    background:#f8f9fa; padding:20px 32px; font-size:11px; color:#999;
    text-align:center; border-top:1px solid #eee;
}
.footer a { color:#0f3460; text-decoration:none; }
"""

_FOOTER_EN = """GLG, a.s. | Středisko SW | Podnásepní 466/1d, Brno 602 00, Czech Republic
IČ: 26288087 | DIČ: CZ26288087
<a href="mailto:sales@uaml.ai">sales@uaml.ai</a> | <a href="https://uaml-memory.com">uaml-memory.com</a>"""

_FOOTER_CS = """GLG, a.s. | Středisko SW | Podnásepní 466/1d, Brno 602 00, Česká republika
IČ: 26288087 | DIČ: CZ26288087
<a href="mailto:sales@uaml.ai">sales@uaml.ai</a> | <a href="https://uaml-memory.com">uaml-memory.com</a>"""


def _wrap_html(title: str, body_inner: str, lang: str = "en") -> str:
    footer = _FOOTER_CS if lang == "cs" else _FOOTER_EN
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{html_mod.escape(title)}</title>
<style>{_CSS}</style></head>
<body>
<div class="wrapper">
<div class="header"><h1>UAML</h1><div class="sub">Universal Adaptive Memory Layer</div></div>
<div class="content">{body_inner}</div>
<div class="footer">{footer}</div>
</div>
</body></html>"""


def _license_block(license_key: str, lang: str) -> str:
    e = html_mod.escape
    if lang == "cs":
        label = "Váš licenční klíč"
        activate = "Aktivace"
    else:
        label = "Your license key"
        activate = "Activation"
    return f"""
<div class="license-box">
    <div style="font-size:12px;color:#888;margin-bottom:4px;">{label}</div>
    <div class="key">{e(license_key)}</div>
    <div class="hint">Keep this key safe — store it securely / Uchovejte klíč v bezpečí</div>
</div>
<div class="activation">
    <strong>{activate}:</strong><br>
    <code>uaml license activate {e(license_key)}</code>
</div>"""


def _invoice_note(invoice_html: str | None, lang: str) -> str:
    if not invoice_html:
        return ""
    if lang == "cs":
        return '<div class="invoice-note">📄 Faktura je přiložena k tomuto e-mailu.</div>'
    return '<div class="invoice-note">📄 Your invoice is attached to this email.</div>'


def _plain_footer() -> str:
    return (
        "\n---\n"
        "GLG, a.s. | Středisko SW | Podnásepní 466/1d, Brno 602 00, Czech Republic\n"
        "IČ: 26288087 | DIČ: CZ26288087\n"
        "sales@uaml.ai | https://uaml-memory.com\n"
    )


# ---------------------------------------------------------------------------
# Email functions
# ---------------------------------------------------------------------------

def purchase_email(
    customer_name: str,
    license_key: str,
    tier: str,
    invoice_html: str | None = None,
    lang: str = "en",
) -> Dict[str, str]:
    """Return {subject, body_html, body_text} for a new purchase."""
    e = html_mod.escape

    if lang == "cs":
        subject = f"UAML – Potvrzení nákupu ({tier})"
        greeting = f"Dobrý den, {e(customer_name)},"
        body_text_greeting = f"Dobrý den, {customer_name},"
        intro = f"Děkujeme za nákup licence <strong>UAML {e(tier)}</strong>!"
        intro_text = f"Děkujeme za nákup licence UAML {tier}!"
        next_steps = "Další kroky"
        step1 = "Nainstalujte UAML: <code>pip install uaml</code>"
        step2 = "Aktivujte licenci příkazem níže"
        step3 = "Začněte integrovat paměť do svých AI agentů"
        questions = 'Máte dotazy? Napište nám na <a href="mailto:sales@uaml.ai">sales@uaml.ai</a>.'
    else:
        subject = f"UAML – Purchase Confirmation ({tier})"
        greeting = f"Hi {e(customer_name)},"
        body_text_greeting = f"Hi {customer_name},"
        intro = f"Thank you for purchasing <strong>UAML {e(tier)}</strong>!"
        intro_text = f"Thank you for purchasing UAML {tier}!"
        next_steps = "Next steps"
        step1 = "Install UAML: <code>pip install uaml</code>"
        step2 = "Activate your license using the command below"
        step3 = "Start integrating memory into your AI agents"
        questions = 'Questions? Reach us at <a href="mailto:sales@uaml.ai">sales@uaml.ai</a>.'

    inner = f"""
<h2>{greeting}</h2>
<p>{intro}</p>
{_license_block(license_key, lang)}
{_invoice_note(invoice_html, lang)}
<h3>{next_steps}</h3>
<ol><li>{step1}</li><li>{step2}</li><li>{step3}</li></ol>
<p style="margin-top:20px">{questions}</p>"""

    body_text = f"""{body_text_greeting}

{intro_text}

License key: {license_key}

Activation:
  uaml license activate {license_key}

{_plain_footer()}"""

    return {
        "subject": subject,
        "body_html": _wrap_html(subject, inner, lang),
        "body_text": body_text,
    }


def upgrade_email(
    customer_name: str,
    license_key: str,
    old_tier: str,
    new_tier: str,
    invoice_html: str | None = None,
    lang: str = "en",
) -> Dict[str, str]:
    """Return {subject, body_html, body_text} for an upgrade."""
    e = html_mod.escape

    if lang == "cs":
        subject = f"UAML – Upgrade na {new_tier}"
        greeting = f"Dobrý den, {e(customer_name)},"
        body_text_greeting = f"Dobrý den, {customer_name},"
        intro = f"Vaše licence byla úspěšně upgradována z <strong>{e(old_tier)}</strong> na <strong>{e(new_tier)}</strong>."
        intro_text = f"Vaše licence byla úspěšně upgradována z {old_tier} na {new_tier}."
        note = "Nové funkce jsou ihned dostupné. Stačí restartovat váš UAML proces."
        questions = 'Máte dotazy? Napište nám na <a href="mailto:sales@uaml.ai">sales@uaml.ai</a>.'
    else:
        subject = f"UAML – Upgrade to {new_tier}"
        greeting = f"Hi {e(customer_name)},"
        body_text_greeting = f"Hi {customer_name},"
        intro = f"Your license has been upgraded from <strong>{e(old_tier)}</strong> to <strong>{e(new_tier)}</strong>."
        intro_text = f"Your license has been upgraded from {old_tier} to {new_tier}."
        note = "New features are available immediately. Just restart your UAML process."
        questions = 'Questions? Reach us at <a href="mailto:sales@uaml.ai">sales@uaml.ai</a>.'

    inner = f"""
<h2>{greeting}</h2>
<p>{intro}</p>
<p>{note}</p>
{_license_block(license_key, lang)}
{_invoice_note(invoice_html, lang)}
<p style="margin-top:20px">{questions}</p>"""

    body_text = f"""{body_text_greeting}

{intro_text}
{note}

License key: {license_key}

Activation:
  uaml license activate {license_key}

{_plain_footer()}"""

    return {
        "subject": subject,
        "body_html": _wrap_html(subject, inner, lang),
        "body_text": body_text,
    }


def downgrade_email(
    customer_name: str,
    license_key: str,
    old_tier: str,
    new_tier: str,
    lang: str = "en",
) -> Dict[str, str]:
    """Return {subject, body_html, body_text} for a downgrade."""
    e = html_mod.escape

    if lang == "cs":
        subject = f"UAML – Změna plánu na {new_tier}"
        greeting = f"Dobrý den, {e(customer_name)},"
        body_text_greeting = f"Dobrý den, {customer_name},"
        intro = f"Vaše licence byla změněna z <strong>{e(old_tier)}</strong> na <strong>{e(new_tier)}</strong>."
        intro_text = f"Vaše licence byla změněna z {old_tier} na {new_tier}."
        note = "Změna vstoupí v platnost na konci aktuálního fakturačního období."
        upgrade_hint = 'Pokud chcete znovu upgradovat, navštivte <a href="https://uaml-memory.com">uaml-memory.com</a>.'
        questions = 'Máte dotazy? Napište nám na <a href="mailto:sales@uaml.ai">sales@uaml.ai</a>.'
    else:
        subject = f"UAML – Plan Changed to {new_tier}"
        greeting = f"Hi {e(customer_name)},"
        body_text_greeting = f"Hi {customer_name},"
        intro = f"Your license has been changed from <strong>{e(old_tier)}</strong> to <strong>{e(new_tier)}</strong>."
        intro_text = f"Your license has been changed from {old_tier} to {new_tier}."
        note = "The change will take effect at the end of your current billing period."
        upgrade_hint = 'Want to upgrade again? Visit <a href="https://uaml-memory.com">uaml-memory.com</a>.'
        questions = 'Questions? Reach us at <a href="mailto:sales@uaml.ai">sales@uaml.ai</a>.'

    inner = f"""
<h2>{greeting}</h2>
<p>{intro}</p>
<p>{note}</p>
{_license_block(license_key, lang)}
<p>{upgrade_hint}</p>
<p style="margin-top:20px">{questions}</p>"""

    body_text = f"""{body_text_greeting}

{intro_text}
{note}

License key: {license_key}

Activation:
  uaml license activate {license_key}

{_plain_footer()}"""

    return {
        "subject": subject,
        "body_html": _wrap_html(subject, inner, lang),
        "body_text": body_text,
    }


def renewal_email(
    customer_name: str,
    license_key: str,
    tier: str,
    invoice_html: str | None = None,
    lang: str = "en",
) -> Dict[str, str]:
    """Return {subject, body_html, body_text} for a renewal."""
    e = html_mod.escape

    if lang == "cs":
        subject = f"UAML – Obnovení licence ({tier})"
        greeting = f"Dobrý den, {e(customer_name)},"
        body_text_greeting = f"Dobrý den, {customer_name},"
        intro = f"Vaše licence <strong>UAML {e(tier)}</strong> byla úspěšně obnovena."
        intro_text = f"Vaše licence UAML {tier} byla úspěšně obnovena."
        note = "Žádná akce z vaší strany není potřeba — vše funguje dál bez přerušení."
        questions = 'Máte dotazy? Napište nám na <a href="mailto:sales@uaml.ai">sales@uaml.ai</a>.'
    else:
        subject = f"UAML – License Renewed ({tier})"
        greeting = f"Hi {e(customer_name)},"
        body_text_greeting = f"Hi {customer_name},"
        intro = f"Your <strong>UAML {e(tier)}</strong> license has been successfully renewed."
        intro_text = f"Your UAML {tier} license has been successfully renewed."
        note = "No action required — everything continues to work without interruption."
        questions = 'Questions? Reach us at <a href="mailto:sales@uaml.ai">sales@uaml.ai</a>.'

    inner = f"""
<h2>{greeting}</h2>
<p>{intro}</p>
<p>{note}</p>
{_license_block(license_key, lang)}
{_invoice_note(invoice_html, lang)}
<p style="margin-top:20px">{questions}</p>"""

    body_text = f"""{body_text_greeting}

{intro_text}
{note}

License key: {license_key}

Activation:
  uaml license activate {license_key}

{_plain_footer()}"""

    return {
        "subject": subject,
        "body_html": _wrap_html(subject, inner, lang),
        "body_text": body_text,
    }
