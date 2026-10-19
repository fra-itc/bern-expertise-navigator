"""Explicit SMTP delivery with durable idempotency. No SMTP is used until configured."""
from __future__ import annotations
import hashlib
import json
import os
import smtplib
import sqlite3
import ssl
from email.message import EmailMessage
from .config import DATA_DIR

DB = DATA_DIR / 'delivery.db'

def configured():
    return bool(os.getenv('SMTP_HOST') and os.getenv('SMTP_FROM') and os.getenv('PITCH_PUBLIC_BASE_URL'))

def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=20)
    db.execute('CREATE TABLE IF NOT EXISTS delivery (key TEXT PRIMARY KEY, case_id TEXT, fingerprint TEXT, status TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP)')
    return db


def history(case_id):
    with connection() as db:
        return [{'status': status, 'at': at.replace(' ', 'T') + 'Z'} for status, at in db.execute(
            'SELECT status,at FROM delivery WHERE case_id=? ORDER BY rowid DESC LIMIT 10', (case_id,))]

def send(case, subject: str, body: str, key: str, pdf: bytes):
    if not configured():
        raise ValueError('SMTP delivery is not configured.')
    if '\n' in subject or '\r' in subject or '\n' in case.contact_email or '\r' in case.contact_email or '@' not in case.contact_email:
        raise ValueError('Invalid email headers or recipient.')
    fingerprint = hashlib.sha256(json.dumps([case.id, case.contact_email, subject, body, hashlib.sha256(pdf).hexdigest()]).encode()).hexdigest()
    with connection() as db:
        row = db.execute('SELECT fingerprint,status FROM delivery WHERE key=?', (key,)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise ValueError('This delivery key belongs to different content.')
            return {'status': row[1], 'duplicate': True}
        try:
            db.execute('INSERT INTO delivery(key,case_id,fingerprint,status) VALUES(?,?,?,?)', (key, case.id, fingerprint, 'pending'))
        except sqlite3.IntegrityError:
            row = db.execute('SELECT fingerprint,status FROM delivery WHERE key=?', (key,)).fetchone()
            if row[0] != fingerprint:
                raise ValueError('This delivery key belongs to different content.')
            return {'status': row[1], 'duplicate': True}
    message = EmailMessage()
    message['From'] = os.environ['SMTP_FROM']
    message['To'] = case.contact_email
    message['Subject'] = subject
    message.set_content(body)
    message.add_attachment(pdf, maintype='application', subtype='pdf', filename='Bern-pitch.pdf')
    try:
        with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '587')), timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            if os.getenv('SMTP_USER'):
                server.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASSWORD', ''))
            server.send_message(message)
    except Exception:
        # SMTP acknowledgement can be lost after acceptance: never automatically resend.
        with connection() as db:
            db.execute('UPDATE delivery SET status=? WHERE key=?', ('uncertain', key))
        return {'status': 'uncertain', 'duplicate': False}
    with connection() as db:
        db.execute('UPDATE delivery SET status=? WHERE key=?', ('sent', key))
    return {'status': 'sent', 'duplicate': False}
