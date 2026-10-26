"""The deliberately closed vocabulary used by extraction and scoring."""
from urllib.parse import urlparse

TACTICS = {
    "impersonation_authority": 4,
    "impersonation_bank": 4,
    "impersonation_family": 3,
    "urgency_pressure": 1,
    "secrecy_request": 2,
    "money_transfer_request": 5,
    "cash_handover_courier": 5,
    "blik_code_request": 5,
    "credentials_request": 5,
    "remote_access_install": 5,
    "safe_account": 4,
}

# Polish queries: the official warnings are written in Polish. Domains are filtered by include_domains.
TACTIC_QUERIES = {
    "impersonation_authority": "oszustwo metodą na policjanta CBŚP policja ostrzega",
    "impersonation_bank": "oszustwo na pracownika banku dział bezpieczeństwa policja ostrzega",
    "impersonation_family": "oszustwo metodą na wnuczka policja ostrzega",
    "urgency_pressure": "oszuści wywierają presję czasu policja ostrzega seniorów",
    "secrecy_request": "oszuści każą nikomu nie mówić policja ostrzega seniorów",
    "money_transfer_request": "oszustwo telefoniczne przelew pieniędzy policja ostrzega",
    "cash_handover_courier": "oszustwo przekazanie gotówki kurierowi policja ostrzega seniorów",
    "blik_code_request": "site:cert.pl BLIK code scam warning",
    "credentials_request": "site:knf.gov.pl credentials phishing warning",
    "remote_access_install": "oszustwo AnyDesk fałszywy pracownik banku policja ostrzega",
    "safe_account": "oszustwo bezpieczne konto policja ostrzega",
}

# A source may be the listed domain or one of its DNS subdomains, never a suffix lookalike.
OFFICIAL_DOMAINS = frozenset({
    "policja.pl", "cbzc.policja.gov.pl", "cert.pl", "knf.gov.pl", "zbp.pl",
    "gov.pl", "uokik.gov.pl", "europol.europa.eu",
})

COMBINATION_BONUSES = (
    (frozenset({"impersonation_authority", "money_transfer_request"}), 4),
    (frozenset({"impersonation_family", "cash_handover_courier"}), 3),
    (frozenset({"impersonation_bank", "remote_access_install"}), 4),
)


def is_official_domain(domain_or_url: str) -> bool:
    """Return true for exact allow-list domains and their real subdomains."""
    parsed = urlparse(domain_or_url if "://" in domain_or_url else f"//{domain_or_url}")
    host = (parsed.hostname or "").casefold().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS)
