"""Bounded wait accounting and strict visible-text output conversion."""

import re


class RecoveryBudget:
    def __init__(self, max_retries):
        self.max_retries = max_retries
        self.used = {}

    def remaining(self, rule):
        return max(0, min(rule.max_attempts, self.max_retries + 1) - self.used.get(rule.code, 0))

    def consume(self, rule):
        if self.remaining(rule) <= 0:
            raise ValueError("Recovery budget exhausted")
        self.used[rule.code] = self.used.get(rule.code, 0) + 1


def extract_value(spec, text):
    """No guessing currencies, stripping symbols, or treating arbitrary text as bool."""
    if not isinstance(text, str):
        raise ValueError("Read did not return text")
    if spec.type == "integer":
        if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", text) is None:
            raise ValueError("Invalid integer text")
        value = int(text)
    elif spec.type == "boolean":
        if text not in {"true", "false"}:
            raise ValueError("Invalid boolean text")
        value = text == "true"
    else:
        value = text
    spec.check(value)
    return value
