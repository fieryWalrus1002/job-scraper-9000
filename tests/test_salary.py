import pytest

from utils.salary import SalaryResult, extract_salary


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Pay Range Data: Lead Software Engineer - $115, 290 - 170,349",
            SalaryResult(115_290, 170_349, "yearly"),
        ),
        (
            "$120,000 - $150'000 salary Plus equity",
            SalaryResult(120_000, 150_000, "yearly"),
        ),
        (
            r"This position has an estimated base salary of $160,000 \- $190,000 plus bonus.",
            SalaryResult(160_000, 190_000, "yearly"),
        ),
        (
            "The base salary hiring range is $90,000 to $170,000 per year.",
            SalaryResult(90_000, 170_000, "yearly"),
        ),
        (
            "Salary Range: $103,500.00 - $181,100.00",
            SalaryResult(103_500, 181_100, "yearly"),
        ),
        (
            "Salary Range: $133,400 - 200,100, plus 10% annual bonus",
            SalaryResult(133_400, 200_100, "yearly"),
        ),
        (
            "Tier 1 Salary Hiring Range: $202,542 USD - $245,434 USD",
            SalaryResult(202_542, 245_434, "yearly"),
        ),
        (
            "Payment: Current payrate will be $60 - $110 per hour.",
            SalaryResult(124_800, 228_800, "hourly"),
        ),
        (
            "Title: AI Forward Engineer Location: Remote, USA Budget: $120k",
            SalaryResult(120_000, None, "yearly"),
        ),
        (
            "US: $147000 - $211000 (USD) + 15% bonus target + equity + benefits",
            SalaryResult(147_000, 211_000, "yearly"),
        ),
        (
            "Pay Rate : $19.00 an hour + Shift Differential ($0.75/hr)",
            SalaryResult(39_520, None, "hourly"),
        ),
    ],
)
def test_extract_salary_handles_real_world_missed_formats(text, expected):
    assert extract_salary(text) == expected


def test_extract_salary_ignores_tiny_hourly_shift_differential():
    assert extract_salary("Shift Differential (+ $0.75/hr)") is None


@pytest.mark.parametrize(
    "text",
    [
        "Project budget: $120k for infrastructure modernization.",
        "Manage annual project budget: $120,000 - $150,000.",
        "Team budget is $500,000 - $700,000 and salary is competitive.",
        "Equipment budget: $120-160k.",
    ],
)
def test_extract_salary_ignores_non_compensation_budgets(text):
    assert extract_salary(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Salary Range: $950,000 - $1,200,000.",
        "Base salary $1000k plus equity.",
        "Salary Range: $950k-$1200k.",
        "Payment: Current payrate will be $500 per hour.",
    ],
)
def test_extract_salary_ignores_values_above_yearly_cap(text):
    assert extract_salary(text) is None


def test_extract_salary_accepts_yearly_cap_boundary():
    assert extract_salary("Salary Range: $500,000 - $999,999.00") == SalaryResult(
        500_000,
        999_999,
        "yearly",
    )
