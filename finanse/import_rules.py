"""Reguły importu: kategoria, nazwa produktu i tagi dla opisu zawierającego tekst.

Tekst reguły porównuje się bez wielkości liter, polskich znaków i nadmiarowych spacji,
więc „Żabka” pasuje do „ZABKA 1234 KRAKOW”. Wygrywa pierwsza pasująca reguła z listy.
"""

from .errors import ValidationError
from .fuzzy import normalize
from .tags import format_tags, parse_tags

MAX_PATTERN_LENGTH = 100
MAX_PRODUCT_NAME_LENGTH = 200
KINDS = (None, "expense", "income")


def _key(text):
    return " ".join(normalize(text).split())


def list_rules(db):
    return db.execute(
        """
        SELECT r.*, c.name AS category_name
        FROM import_rules r
        LEFT JOIN categories c ON c.id = r.category_id
        ORDER BY r.position, r.id
        """
    ).fetchall()


def _validate(db, pattern, kind, category_id, product_name, tags):
    errors = []
    pattern = " ".join(pattern.split())
    if not _key(pattern) or len(pattern) > MAX_PATTERN_LENGTH:
        errors.append(f"Podaj tekst, którego szukać w opisie (do {MAX_PATTERN_LENGTH} znaków).")
    if kind not in KINDS:
        errors.append("Wybierz, czy reguła dotyczy wydatków, przychodów, czy obu.")
    if category_id is not None and db.execute(
        "SELECT 1 FROM categories WHERE id = ?", (category_id,)
    ).fetchone() is None:
        errors.append("Wybrana kategoria już nie istnieje.")
    product_name = " ".join((product_name or "").split())
    if len(product_name) > MAX_PRODUCT_NAME_LENGTH:
        errors.append(f"Nazwa produktu może mieć do {MAX_PRODUCT_NAME_LENGTH} znaków.")
    names, tag_errors = parse_tags(tags or "")
    errors += tag_errors
    if category_id is None and not product_name and not names:
        errors.append("Reguła musi ustawiać kategorię, nazwę produktu albo tagi.")
    if errors:
        raise ValidationError(errors)
    return pattern, product_name or None, format_tags(names)


def create_rule(db, pattern, kind=None, category_id=None, product_name="", tags=""):
    pattern, product_name, tags = _validate(db, pattern, kind, category_id, product_name, tags)
    with db:
        position = db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM import_rules"
        ).fetchone()[0]
        return db.execute(
            """
            INSERT INTO import_rules (position, pattern, kind, category_id, product_name, tags)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (position, pattern, kind, category_id, product_name, tags),
        ).lastrowid


def update_rule(db, rule_id, pattern, kind=None, category_id=None, product_name="", tags=""):
    pattern, product_name, tags = _validate(db, pattern, kind, category_id, product_name, tags)
    with db:
        db.execute(
            """
            UPDATE import_rules
            SET pattern = ?, kind = ?, category_id = ?, product_name = ?, tags = ?
            WHERE id = ?
            """,
            (pattern, kind, category_id, product_name, tags, rule_id),
        )


def delete_rule(db, rule_id):
    with db:
        db.execute("DELETE FROM import_rules WHERE id = ?", (rule_id,))


def move_rule(db, rule_id, offset):
    """Przesuwa regułę o `offset` miejsc na liście; pierwsza pasująca wygrywa."""
    ids = [rule["id"] for rule in list_rules(db)]
    if rule_id not in ids:
        return
    index = ids.index(rule_id)
    target = max(0, min(len(ids) - 1, index + offset))
    if target == index:
        return
    ids.insert(target, ids.pop(index))
    with db:
        for position, current in enumerate(ids, 1):
            db.execute(
                "UPDATE import_rules SET position = ? WHERE id = ? AND position != ?",
                (position, current, position),
            )


def matching_rule(rules, description, kind):
    """Pierwsza reguła pasująca do opisu i rodzaju operacji albo None."""
    text = _key(description)
    for rule in rules:
        if rule["kind"] not in (None, kind):
            continue
        if _key(rule["pattern"]) in text:
            return rule
    return None


def kind_label(kind):
    return {None: "wydatki i przychody", "expense": "wydatki", "income": "przychody"}[kind]
