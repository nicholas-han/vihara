"""Financial Account reference data; no economic facts or account hierarchy."""

import re
import sqlite3
from ..errors import LedgerError

INSTITUTION_TYPES = {"BANK", "BROKER-DEALER", "INSURER"}


def text(value, field, *, optional=False, limit=200):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise LedgerError(
            "VALIDATION_ERROR",
            f"{field} must be a nonempty string.",
            field_errors={field: "Invalid reference value."},
        )
    return value.strip()


def code(value, field):
    value = text(value, field, limit=64)
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,63}", value):
        raise LedgerError(
            "VALIDATION_ERROR",
            f"{field} must use uppercase letters, digits, underscores or hyphens.",
        )
    return value


def identity(value, field):
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdigit()
        or not 0 < len(value) <= 18
        or int(value) < 1
    ):
        raise LedgerError(
            "VALIDATION_ERROR",
            f"{field} must be a valid ID string.",
            field_errors={field: "A valid ID is required."},
        )
    return int(value)


def require_account(conn, account_id):
    if not conn.execute(
        "SELECT 1 FROM financial_accounts WHERE financial_account_id=?", (account_id,)
    ).fetchone():
        raise LedgerError("REFERENCE_NOT_FOUND", "Financial Account not found.")


def scope_for_trade(conn, value, account_id):
    sid = identity(value, "position_scope_id")
    scope = conn.execute(
        "SELECT * FROM position_scopes WHERE position_scope_id=?", (sid,)
    ).fetchone()
    if scope is None:
        raise LedgerError(
            "REFERENCE_NOT_FOUND",
            "Position Scope not found.",
            field_errors={"position_scope_id": "Unknown Position Scope."},
        )
    if scope["financial_account_id"] != account_id:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Position Scope must belong to the Trade Financial Account.",
            field_errors={"position_scope_id": "Financial Account mismatch."},
        )
    return sid


def scopes(conn, account_id=None):
    if account_id is not None:
        require_account(conn, account_id)
    return [
        {
            **dict(r),
            "position_scope_id": str(r["position_scope_id"]),
            "financial_account_id": str(r["financial_account_id"]),
            "tax_scheme_id": (
                str(r["tax_scheme_id"]) if r["tax_scheme_id"] is not None else None
            ),
        }
        for r in conn.execute(
            "SELECT s.*,t.scheme_code AS tax_scheme_code,t.display_name AS tax_scheme_name "
            "FROM position_scopes s LEFT JOIN tax_schemes t USING(tax_scheme_id)"
            + (" WHERE s.financial_account_id=?" if account_id is not None else "")
            + " ORDER BY s.position_scope_id",
            (account_id,) if account_id is not None else (),
        )
    ]


def external_references(conn, account_id):
    require_account(conn, account_id)
    return [
        {
            **dict(r),
            "external_account_reference_id": str(r["external_account_reference_id"]),
            "financial_account_id": str(r["financial_account_id"]),
        }
        for r in conn.execute(
            "SELECT * FROM external_account_references WHERE financial_account_id=? ORDER BY external_account_reference_id",
            (account_id,),
        )
    ]


def add_scope(conn, account_id, item, *, existing_ok=False):
    if not isinstance(item, dict) or set(item) - {
        "scope_code",
        "display_name",
        "tax_scheme_id",
        "tax_scheme_code",
    }:
        raise LedgerError("VALIDATION_ERROR", "Invalid Position Scope fields.")
    scode = code(item.get("scope_code"), "scope_code")
    name = text(item.get("display_name"), "display_name")
    tax = item.get("tax_scheme_id")
    if item.get("tax_scheme_code"):
        if tax is not None:
            raise LedgerError("VALIDATION_ERROR", "Use one TaxScheme reference.")
        row = conn.execute(
            "SELECT tax_scheme_id FROM tax_schemes WHERE scheme_code=?",
            (item["tax_scheme_code"],),
        ).fetchone()
        if row is None:
            raise LedgerError("REFERENCE_NOT_FOUND", "TaxScheme not found.")
        tax = str(row[0])
    if tax is not None:
        tax = identity(tax, "tax_scheme_id")
        if not conn.execute(
            "SELECT 1 FROM tax_schemes WHERE tax_scheme_id=?", (tax,)
        ).fetchone():
            raise LedgerError("REFERENCE_NOT_FOUND", "TaxScheme not found.")
    previous = conn.execute(
        "SELECT * FROM position_scopes WHERE financial_account_id=? AND scope_code=?",
        (account_id, scode),
    ).fetchone()
    if (
        previous
        and existing_ok
        and (previous["display_name"], previous["tax_scheme_id"]) == (name, tax)
    ):
        return previous["position_scope_id"]
    return conn.execute(
        "INSERT INTO position_scopes(financial_account_id,scope_code,display_name,tax_scheme_id) VALUES (?,?,?,?)",
        (account_id, scode, name, tax),
    ).lastrowid


def create_account(
    conn,
    account_code,
    display_name,
    institution_type,
    country_or_region=None,
    position_scopes=None,
    external_account_numbers=None,
):
    acode = code(account_code, "account_code")
    name = text(display_name, "display_name")
    country = text(country_or_region, "country_or_region", optional=True, limit=64)
    if (
        not isinstance(institution_type, str)
        or institution_type not in INSTITUTION_TYPES
    ):
        raise LedgerError(
            "VALIDATION_ERROR",
            "Institution Type must be BANK, BROKER-DEALER or INSURER.",
        )
    if position_scopes is None:
        position_scopes = (
            [{"scope_code": "DEFAULT", "display_name": "Default"}]
            if institution_type == "BROKER-DEALER"
            else []
        )
    if not isinstance(position_scopes, list) or (
        institution_type == "BROKER-DEALER" and not position_scopes
    ):
        raise LedgerError(
            "VALIDATION_ERROR", "Broker accounts require at least one Position Scope."
        )
    if external_account_numbers is None:
        external_account_numbers = []
    if not isinstance(external_account_numbers, list):
        raise LedgerError(
            "VALIDATION_ERROR", "External account numbers must be a list."
        )
    if conn.execute(
        "SELECT 1 FROM financial_accounts WHERE account_code=?", (acode,)
    ).fetchone():
        raise LedgerError(
            "VALIDATION_ERROR",
            "Financial Account code already exists.",
            "DUPLICATE_ACCOUNT",
        )
    aid = conn.execute(
        "INSERT INTO financial_accounts(account_code,display_name,country_or_region,institution_type) VALUES (?,?,?,?)",
        (acode, name, country, institution_type),
    ).lastrowid
    for item in position_scopes:
        add_scope(conn, aid, item)
    for number in external_account_numbers:
        conn.execute(
            "INSERT INTO external_account_references(financial_account_id,external_account_number) VALUES (?,?)",
            (aid, text(number, "external_account_number")),
        )
    return {
        "financial_account_id": str(aid),
        "account_code": acode,
        "display_name": name,
        "country_or_region": country,
        "institution_type": institution_type,
    }


def bootstrap(conn, document):
    """Append explicitly supplied references atomically; repeated identical input is a no-op."""
    if not isinstance(document, dict) or set(document) - {"tax_schemes", "accounts"}:
        raise LedgerError(
            "VALIDATION_ERROR", "Reference input requires tax_schemes and/or accounts."
        )
    if any(
        not isinstance(document.get(k, []), list) for k in ("tax_schemes", "accounts")
    ):
        raise LedgerError("VALIDATION_ERROR", "Reference collections must be lists.")
    for item in document.get("tax_schemes", []):
        if not isinstance(item, dict) or set(item) - {
            "scheme_code",
            "display_name",
            "country_or_region",
        }:
            raise LedgerError("VALIDATION_ERROR", "Invalid TaxScheme fields.")
        values = (
            code(item.get("scheme_code"), "scheme_code"),
            text(item.get("display_name"), "display_name"),
            text(
                item.get("country_or_region"),
                "country_or_region",
                optional=True,
                limit=64,
            ),
        )
        old = conn.execute(
            "SELECT scheme_code,display_name,country_or_region FROM tax_schemes WHERE scheme_code=?",
            (values[0],),
        ).fetchone()
        if old:
            if tuple(old) != values:
                raise LedgerError(
                    "VALIDATION_ERROR",
                    "Existing TaxScheme differs; reference import never rewrites it.",
                )
        else:
            conn.execute(
                "INSERT INTO tax_schemes(scheme_code,display_name,country_or_region) VALUES (?,?,?)",
                values,
            )
    for item in document.get("accounts", []):
        if not isinstance(item, dict) or set(item) - {
            "account_code",
            "display_name",
            "institution_type",
            "country_or_region",
            "position_scopes",
            "external_account_numbers",
        }:
            raise LedgerError("VALIDATION_ERROR", "Invalid Financial Account fields.")
        acode = code(item.get("account_code"), "account_code")
        old = conn.execute(
            "SELECT * FROM financial_accounts WHERE account_code=?", (acode,)
        ).fetchone()
        if old is None:
            create_account(conn, **item)
            continue
        expected = (
            text(item.get("display_name"), "display_name"),
            text(
                item.get("country_or_region"),
                "country_or_region",
                optional=True,
                limit=64,
            ),
            item.get("institution_type"),
        )
        if (
            old["display_name"],
            old["country_or_region"],
            old["institution_type"],
        ) != expected:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Existing Financial Account differs; reference import never rewrites it.",
            )
        items = item.get("position_scopes")
        if items is None:
            # Defaults apply only when creating an account, never when appending references.
            items = []
        numbers = item.get("external_account_numbers", [])
        if not isinstance(items, list) or not isinstance(numbers, list):
            raise LedgerError(
                "VALIDATION_ERROR", "Scopes and external numbers must be lists."
            )
        for scope in items:
            add_scope(conn, old["financial_account_id"], scope, existing_ok=True)
        for number in numbers:
            number = text(number, "external_account_number")
            if not conn.execute(
                "SELECT 1 FROM external_account_references WHERE financial_account_id=? AND external_account_number=?",
                (old["financial_account_id"], number),
            ).fetchone():
                conn.execute(
                    "INSERT INTO external_account_references(financial_account_id,external_account_number) VALUES (?,?)",
                    (old["financial_account_id"], number),
                )
    return {
        "financial_accounts": conn.execute(
            "SELECT COUNT(*) FROM financial_accounts"
        ).fetchone()[0],
        "position_scopes": conn.execute(
            "SELECT COUNT(*) FROM position_scopes"
        ).fetchone()[0],
        "tax_schemes": conn.execute("SELECT COUNT(*) FROM tax_schemes").fetchone()[0],
    }
