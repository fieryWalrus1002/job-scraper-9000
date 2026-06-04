import re

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_BLANK_LINES_RE = re.compile(r"\n[ \t]*(\n[ \t]*)+")


def scrub(text: str) -> tuple[str, dict]:
    counts = {"email": 0, "phone": 0}
    if not text:
        return text, counts
    text, n = EMAIL_RE.subn("[EMAIL_REDACTED]", text)
    counts["email"] = n
    text, n = PHONE_RE.subn("[PHONE_REDACTED]", text)
    counts["phone"] = n
    text = _BLANK_LINES_RE.sub("\n\n", text).strip()
    return text, counts
