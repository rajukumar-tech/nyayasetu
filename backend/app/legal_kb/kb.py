"""Legal knowledge base: versioned YAML under data/legal/ + verification overlay.

Nothing here decides eligibility. It only answers "what does the (possibly
unverified) data say about act X section Y" and computes derived maxima with a
recorded derivation.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from app.domain import Charge, Modifier

DAYS_PER_MONTH = 365.25 / 12
CORE_ACTS = {"IPC", "BNS"}


@dataclass(frozen=True)
class Term:
    """A punishment term. kind: term | life | death | none (fine only)."""
    kind: str
    months: int = 0

    @classmethod
    def parse(cls, raw: Any) -> "Term | None":
        if raw is None:
            return None
        if raw in ("life", "death"):
            return cls(raw)
        if isinstance(raw, dict):
            return cls("term", int(raw.get("years", 0)) * 12 + int(raw.get("months", 0)))
        raise ValueError(f"Unrecognised punishment term: {raw!r}")

    @property
    def is_death_or_life(self) -> bool:
        return self.kind in ("life", "death")

    @property
    def days(self) -> float:
        """Length in days (term only). Convention: 1 month = 365.25/12 days."""
        if self.kind != "term":
            raise ValueError(f"{self.kind} has no length in days")
        return self.months * DAYS_PER_MONTH

    def fraction_months(self, frac: Fraction) -> Fraction:
        return self.months * frac

    def __str__(self) -> str:
        if self.kind in ("life", "death"):
            return "death" if self.kind == "death" else "imprisonment for life"
        if self.kind == "none":
            return "fine only"
        y, m = divmod(self.months, 12)
        parts = ([f"{y} year{'s' if y != 1 else ''}"] if y else []) + ([f"{m} month{'s' if m != 1 else ''}"] if m else [])
        return " ".join(parts) or "0 months"


def term_from_months(months: Fraction | int) -> Term:
    # Round UP to whole months: a derived fraction never shortens the ceiling.
    return Term("term", math.ceil(months))


@dataclass
class LegalRecord:
    act: str
    section: str
    title: str
    punishment_summary: str = ""
    kind: str = "offence"  # offence | liability_rule
    max_imprisonment: Term | None = None
    aggravated_max_imprisonment: Term | None = None
    min_imprisonment: Term | None = None
    fine_only: bool = False
    cognizable: bool | None = None
    bailable: bool | None = None
    compoundable: str | None = None  # "no" | without_permission | with_permission | None (unknown)
    compoundable_by: str | None = None
    triable_by: str | None = None
    offence_categories: list[str] = field(default_factory=list)
    special_law: bool = False
    special_bail_restrictions: str | None = None
    default_bail_period_days: int | None = None
    source: str = ""
    source_url: str = ""
    notes: str | None = None
    verified: bool = False
    verified_by: str | None = None

    @property
    def key(self) -> str:
        return record_key(self.act, self.section)

    @property
    def effective_max(self) -> Term:
        if self.fine_only:
            return Term("none")
        if self.max_imprisonment is None:
            raise ValueError(f"{self.key} has no maximum punishment recorded")
        return self.max_imprisonment


@dataclass
class Rule:
    name: str
    data: dict[str, Any]
    verified: bool
    ref: str

    def __getitem__(self, k: str) -> Any:
        return self.data[k]

    def get(self, k: str, default: Any = None) -> Any:
        return self.data.get(k, default)

    def fraction(self, k: str) -> Fraction:
        n, d = self.data[k]
        return Fraction(n, d)


@dataclass
class Mapping:
    ipc: str
    bns: list[str]
    relation: str
    notes: str | None
    verified: bool


@dataclass
class Derivation:
    """Effective maximum for a charge and how it was obtained."""
    term: Term
    record: LegalRecord | None
    steps: list[str]
    records_used: list[LegalRecord]
    rules_used: list[Rule]
    flags: list[str] = field(default_factory=list)

    @property
    def unverified(self) -> list[str]:
        out = [r.key for r in self.records_used if not r.verified]
        out += [f"rule:{r.name}" for r in self.rules_used if not r.verified]
        return out


_SECTION_CLEAN = re.compile(r"\s+")


def normalise_section(section: str) -> str:
    return _SECTION_CLEAN.sub("", str(section)).upper()


def normalise_act(act: str) -> str:
    a = re.sub(r"[^A-Z]", "", act.upper())
    return {"INDIANPENALCODE": "IPC", "BHARATIYANYAYASANHITA": "BNS", "SCSTACT": "SCST", "NDPSACT": "NDPS",
            "POCSOACT": "POCSO", "ARMSACT": "ARMS"}.get(a, a)


def record_key(act: str, section: str) -> str:
    return f"{normalise_act(act)}:{normalise_section(section)}"


class KnowledgeBase:
    def __init__(self, records: dict[str, LegalRecord], rules: dict[str, Rule], mappings: list[Mapping],
                 version: str, meta: dict[str, Any]):
        self.records = records
        self.rules = rules
        self.mappings = mappings
        self.version = version
        self.meta = meta

    # ---------- loading ----------
    @classmethod
    def load(cls, directory: str | Path, overlay: dict[str, dict[str, Any]] | None = None) -> "KnowledgeBase":
        """Load all YAML in `directory`. `overlay` maps record keys (e.g. 'IPC:379' or
        'rule:section_479') to {'verified': bool, 'verified_by': str} from the DB."""
        directory = Path(directory)
        overlay = overlay or {}
        hasher = hashlib.sha256()
        records: dict[str, LegalRecord] = {}
        rules: dict[str, Rule] = {}
        mappings: list[Mapping] = []
        meta: dict[str, Any] = {}
        for path in sorted(directory.glob("*.yaml")):
            raw_text = path.read_text(encoding="utf-8")
            hasher.update(path.name.encode() + raw_text.encode())
            doc = yaml.safe_load(raw_text) or {}
            if "records" in doc:
                file_act = doc.get("act", "")
                meta[file_act] = {k: v for k, v in doc.items() if k != "records"}
                for r in doc["records"]:
                    rec = _record_from_yaml(r, file_act, doc)
                    records[rec.key] = rec
            if "rules" in doc:
                for name, data in doc["rules"].items():
                    rules[name] = _rule_from_yaml(name, data)
            if "mappings" in doc:
                mappings.extend(Mapping(m["ipc"], list(m.get("bns", [])), m["relation"], m.get("notes"),
                                        bool(m.get("verified", False))) for m in doc["mappings"])
        for key, ov in overlay.items():
            target = rules.get(key[5:]) if key.startswith("rule:") else records.get(key)
            if target is not None and "verified" in ov:
                target.verified = bool(ov["verified"])
                if isinstance(target, LegalRecord):
                    target.verified_by = ov.get("verified_by")
        hasher.update(json.dumps(overlay, sort_keys=True, default=str).encode())
        version = hasher.hexdigest()[:12]
        return cls(records, rules, mappings, version, meta)

    # ---------- queries ----------
    def get(self, act: str, section: str) -> LegalRecord | None:
        return self.records.get(record_key(act, section))

    def rule(self, name: str) -> Rule:
        return self.rules[name]

    def bns_for_ipc(self, section: str) -> Mapping | None:
        s = normalise_section(section)
        return next((m for m in self.mappings if normalise_section(m.ipc) == s), None)

    def ipc_for_bns(self, section: str) -> list[Mapping]:
        s = normalise_section(section)
        return [m for m in self.mappings if s in {normalise_section(b) for b in m.bns}]

    def unverified_records(self) -> list[LegalRecord]:
        return [r for r in self.records.values() if not r.verified]

    # ---------- governing law ----------
    def governing_record(self, charge: Charge) -> tuple[LegalRecord | None, list[str], list[str]]:
        """Return (record, steps, flags) for the law that governs PUNISHMENT for this charge.

        Offences before BNS commencement keep IPC punishment; the mapping is used only
        to locate the corresponding section when the charge was recorded under the
        other code, and that is always flagged."""
        act = normalise_act(charge.act)
        steps: list[str] = []
        flags: list[str] = []
        if act not in CORE_ACTS:
            rec = self.get(act, charge.section)
            if rec is None:
                flags.append("UNKNOWN_SECTION")
                steps.append(f"{act} {charge.section} is not in the legal knowledge base.")
            return rec, steps, flags

        transition = self.rule("transition")
        cutoff: date = transition["bns_commencement"]
        if charge.offence_date is None:
            flags.append("OFFENCE_DATE_UNKNOWN")
            steps.append(f"Offence date unknown — using the code charged ({act}) for punishment.")
            governing = act
        else:
            governing = transition["punishment_law_before"] if charge.offence_date < cutoff else transition["punishment_law_from"]
            steps.append(f"Offence date {charge.offence_date.isoformat()} is "
                         f"{'before' if governing == 'IPC' else 'on/after'} {cutoff.isoformat()} → punishment under {governing}.")

        if governing == act:
            rec = self.get(act, charge.section)
            if rec is None:
                flags.append("UNKNOWN_SECTION")
                steps.append(f"{act} {charge.section} is not in the legal knowledge base.")
            return rec, steps, flags

        flags.append("IPC_BNS_TRANSITION_MISMATCH")
        steps.append(f"Charged under {act} {charge.section} but {governing} governs punishment — looking up the mapping.")
        if act == "BNS":
            candidates = self.ipc_for_bns(charge.section)
            targets = [m.ipc for m in candidates]
        else:
            m = self.bns_for_ipc(charge.section)
            candidates = [m] if m else []
            targets = m.bns if m else []
        if len(targets) != 1:
            flags.append("MAPPING_AMBIGUOUS_OR_MISSING")
            steps.append(f"No unambiguous {governing} equivalent (found {targets or 'none'}) — needs lawyer review.")
            return None, steps, flags
        rec = self.get(governing, targets[0])
        if rec is None:
            flags.append("UNKNOWN_SECTION")
            steps.append(f"Mapped section {governing} {targets[0]} is not in the knowledge base.")
            return None, steps, flags
        if not all(c.verified for c in candidates):
            flags.append("UNVERIFIED_MAPPING")
        steps.append(f"Mapped to {governing} {targets[0]} ({rec.title}).")
        return rec, steps, flags

    # ---------- derived maxima ----------
    def effective_max(self, charge: Charge) -> Derivation:
        rec, steps, flags = self.governing_record(charge)
        if rec is None:
            return Derivation(Term("none"), None, steps, [], [], flags + ["NO_RECORD"])
        if rec.kind == "liability_rule":
            flags.append("LIABILITY_RULE_ONLY")
            steps.append(f"{rec.key} is a liability rule, not an offence — it has no maximum of its own.")
            return Derivation(Term("none"), rec, steps, [rec], [], flags)
        base = rec.effective_max
        if charge.aggravated and rec.aggravated_max_imprisonment:
            base = rec.aggravated_max_imprisonment
            steps.append(f"Aggravated form recorded → maximum {base}.")
        steps.append(f"{rec.key} ({rec.title}): maximum {base}.")
        rules_used: list[Rule] = []
        term = base
        derivs = self.rules["derivations"].data
        if charge.modifier is not None:
            name = {
                Modifier.ATTEMPT: "attempt",
                Modifier.ABETMENT: "abetment_committed",
                Modifier.ABETMENT_NOT_COMMITTED: "abetment_not_committed",
                Modifier.CONSPIRACY: "conspiracy",
                Modifier.COMMON_INTENTION: "common_intention",
            }[charge.modifier]
            d = derivs[name]
            drule = Rule(f"derivations.{name}", d, bool(d.get("verified", False)), d.get("ref", ""))
            rules_used.append(drule)
            term = self._derive(name, d, base, steps, rules_used)
        return Derivation(term, rec, steps, [rec], rules_used, flags)

    def _derive(self, name: str, d: dict[str, Any], base: Term, steps: list[str], rules_used: list[Rule]) -> Term:
        ref = d.get("ref", name)
        if base.kind == "none":
            steps.append(f"{ref}: base offence is fine-only → derived offence is fine-only.")
            return base
        if name == "conspiracy":
            serious = base.is_death_or_life or base.months >= int(d["serious_threshold_years"]) * 12
            if serious:
                steps.append(f"{ref}: object offence is serious → punished as abetment (same maximum as the offence): {base}.")
                return base
            t = Term("term", int(d["otherwise_max_months"]))
            steps.append(f"{ref}: object offence is not serious → maximum {t}.")
            return t
        frac = Fraction(*d["fraction_of_max"])
        if frac == 1:
            steps.append(f"{ref}: same maximum as the offence → {base}.")
            return base
        if base.is_death_or_life:
            if name == "abetment_not_committed" and d.get("if_death_or_life_max_years"):
                t = Term("term", int(d["if_death_or_life_max_years"]) * 12)
                steps.append(f"{ref}: offence punishable with death/life → maximum {t}.")
                return t
            life = self.rules["life_imprisonment_for_fractions"]
            rules_used.append(life)
            months = int(life["equivalent_years"]) * 12 * frac
            t = term_from_months(months)
            steps.append(f"{ref} with {life.ref}: life reckoned as {life['equivalent_years']} years for fractions → "
                         f"{frac} of that = {t}.")
            return t
        t = term_from_months(base.months * frac)
        steps.append(f"{ref}: {frac} of {base} = {t} (rounded up to whole months).")
        return t


def _record_from_yaml(r: dict[str, Any], file_act: str, doc: dict[str, Any]) -> LegalRecord:
    return LegalRecord(
        act=normalise_act(r.get("act", file_act)),
        section=str(r["section"]),
        title=r.get("title", ""),
        punishment_summary=r.get("punishment_summary", ""),
        kind=r.get("kind", "offence"),
        max_imprisonment=Term.parse(r.get("max_imprisonment")),
        aggravated_max_imprisonment=Term.parse(r.get("aggravated_max_imprisonment")),
        min_imprisonment=Term.parse(r.get("min_imprisonment")),
        fine_only=bool(r.get("fine_only", False)),
        cognizable=r.get("cognizable"),
        bailable=r.get("bailable"),
        compoundable=r.get("compoundable"),
        compoundable_by=r.get("compoundable_by"),
        triable_by=r.get("triable_by"),
        offence_categories=list(r.get("offence_categories") or []),
        special_law=bool(r.get("special_law", False)),
        special_bail_restrictions=r.get("special_bail_restrictions"),
        default_bail_period_days=r.get("default_bail_period_days"),
        source=r.get("source", doc.get("source", "")),
        source_url=r.get("source_url", doc.get("source_url", "")),
        notes=r.get("notes"),
        verified=bool(r.get("verified", False)),
    )


def _rule_from_yaml(name: str, data: dict[str, Any]) -> Rule:
    return Rule(name, data, bool(data.get("verified", False)), data.get("ref", ""))


_default_kb: KnowledgeBase | None = None


def get_kb(overlay: dict[str, dict[str, Any]] | None = None, reload: bool = False) -> KnowledgeBase:
    """Process-wide KB. Reloaded when the overlay changes (admin verifies a record)."""
    global _default_kb
    from app.core.config import settings
    if _default_kb is None or reload or overlay is not None:
        _default_kb = KnowledgeBase.load(settings.legal_data_dir, overlay)
    return _default_kb
