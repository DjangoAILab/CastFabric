#!/usr/bin/env python3
"""Validate that a CastFabric prototype only uses registered product data."""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path


class ContractBindings(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: set[str] = set()
        self.actions: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        values = dict(attrs)
        if values.get("data-field"):
            self.fields.add(str(values["data-field"]))
        if values.get("data-action"):
            self.actions.add(str(values["data-action"]))


def validate(prototype: Path, contract_path: Path) -> list[str]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    bindings = ContractBindings()
    bindings.feed(prototype.read_text(encoding="utf-8"))
    errors: list[str] = []

    fields = contract.get("fields", {})
    actions = contract.get("actions", {})
    allowed = set(contract.get("availability", []))

    for field_id in sorted(bindings.fields):
        item = fields.get(field_id)
        if item is None:
            errors.append(f"unknown field: {field_id}")
            continue
        if item.get("availability") == "forbidden":
            errors.append(f"forbidden field used by prototype: {field_id}")

    for action_id in sorted(bindings.actions):
        if action_id not in actions:
            errors.append(f"unknown action: {action_id}")

    for collection_name, collection in (("field", fields), ("action", actions)):
        for item_id, item in collection.items():
            availability = item.get("availability")
            if availability not in allowed:
                errors.append(f"{collection_name} {item_id}: invalid availability")
            if not item.get("owner"):
                errors.append(f"{collection_name} {item_id}: owner is required")
            if availability == "planned" and not item.get("fallback"):
                errors.append(f"{collection_name} {item_id}: planned item needs fallback")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    prototype = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "docs/prototypes/castfabric-console-v6.html"
    contract = root / "docs/design/contracts/castfabric-console-fields.json"
    errors = validate(prototype, contract)
    if errors:
        print("FAIL: console prototype data contract")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS: console prototype data contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
