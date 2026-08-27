"""Contact-Finder Agent (phase 2).

Given a company (and optional list of likely titles), produces email-permutation
candidates and stores them in `data/companies/<slug>/contacts.csv` plus the DB.

This is intentionally **conservative**:
  - No real LinkedIn scraping of authenticated pages.
  - No paid enrichment services.
  - DNS MX validation only (no SMTP probes by default to avoid spam-trap risk).
  - You bring the names; this agent provides permutations and validation.

If you want light name discovery, pass `seed_names=[...]` to `run()`.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ..db import upsert_contact, upsert_company
from ..models import Company, Contact
from ..utils import slug
from .base import BaseAgent


PATTERNS = [
    "{first}.{last}@{domain}",
    "{first}{last}@{domain}",
    "{f}{last}@{domain}",
    "{first}@{domain}",
    "{first}_{last}@{domain}",
    "{first}-{last}@{domain}",
    "{last}.{first}@{domain}",
]


class ContactFinderAgent(BaseAgent):
    name = "contact_finder"

    def run(
        self,
        company_name: str,
        domain: str | None = None,
        seed_names: Iterable[tuple[str, str | None]] = (),
        validate_mx: bool = True,
    ) -> list[Contact]:
        sl = slug(company_name)
        domain = domain or _guess_domain(company_name)
        out_dir: Path = self.settings.paths.companies_dir / sl
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "contacts.csv"

        contacts: list[Contact] = []
        mx_ok = _has_mx(domain) if (validate_mx and domain) else True

        for full_name, title in seed_names:
            first, last = _split_name(full_name)
            if not (first and last):
                continue
            for pat in PATTERNS:
                email = pat.format(
                    first=first, last=last, f=first[:1], domain=domain or "example.com"
                )
                confidence = _confidence(pat, mx_ok=mx_ok)
                contact = Contact(
                    company_slug=sl,
                    name=f"{full_name} | {email}",
                    title=title,
                    source_url=None,
                    email_candidate=email,
                    confidence=confidence,
                )
                upsert_contact(contact)
                contacts.append(contact)

        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name", "title", "email_candidate", "confidence", "source_url"])
            for c in contacts:
                w.writerow(
                    [
                        c.name.split(" | ")[0],
                        c.title or "",
                        c.email_candidate or "",
                        f"{c.confidence:.2f}",
                        c.source_url or "",
                    ]
                )

        upsert_company(
            Company(
                slug=sl,
                name=company_name,
                domain=domain,
                last_scraped=datetime.utcnow(),
            )
        )
        self.emit(
            "contacts.end",
            {"slug": sl, "domain": domain, "mx_ok": bool(mx_ok), "n": len(contacts)},
        )
        return contacts


def _guess_domain(name: str) -> str:
    return slug(name).replace("-", "") + ".com"


def _split_name(full: str) -> tuple[str, str]:
    parts = [p for p in (full or "").strip().split() if p.isalpha()]
    if len(parts) < 2:
        return ("", "")
    return (parts[0].lower(), parts[-1].lower())


def _confidence(pattern: str, mx_ok: bool) -> float:
    base = {
        "{first}.{last}@{domain}": 0.65,
        "{first}{last}@{domain}": 0.45,
        "{f}{last}@{domain}": 0.55,
        "{first}@{domain}": 0.35,
    }.get(pattern, 0.30)
    return round(base * (1.0 if mx_ok else 0.5), 2)


def _has_mx(domain: str) -> bool:
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX", lifetime=5.0)
        return len(list(answers)) > 0
    except Exception:
        return False
