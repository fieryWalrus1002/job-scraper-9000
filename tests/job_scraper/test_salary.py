from utils.salary import extract_salary, annualise

_HOURS_PER_YEAR = 2080


# --- annualise ---


def test_annualise_yearly():
    assert annualise(120_000, "yearly") == 120_000


def test_annualise_hourly():
    assert annualise(54, "hourly") == 54 * _HOURS_PER_YEAR


def test_annualise_monthly():
    assert annualise(10_000, "monthly") == 120_000


def test_annualise_unknown_period_defaults_to_yearly():
    assert annualise(100_000, "unknown") == 100_000


# --- extract_salary: ranges (no context guard needed) ---


def test_k_range_both_dollar_signs():
    r = extract_salary("Compensation: $170k–$190k DOE")
    assert r is not None
    assert r.salary_min_usd == 170_000
    assert r.salary_max_usd == 190_000
    assert r.salary_period == "yearly"


def test_k_range_one_dollar_sign():
    r = extract_salary("base ($200-275k)")
    assert r is not None
    assert r.salary_min_usd == 200_000
    assert r.salary_max_usd == 275_000
    assert r.salary_period == "yearly"


def test_k_range_em_dash():
    r = extract_salary("We offer $120k — $160k annually.")
    assert r is not None
    assert r.salary_min_usd == 120_000
    assert r.salary_max_usd == 160_000


def test_comma_range():
    r = extract_salary("The salary range is $100,000 - $150,000.")
    assert r is not None
    assert r.salary_min_usd == 100_000
    assert r.salary_max_usd == 150_000
    assert r.salary_period == "yearly"


# --- extract_salary: hourly ---


def test_hourly_single():
    r = extract_salary("Pay rate: $54/hr")
    assert r is not None
    assert r.salary_min_usd == 54 * _HOURS_PER_YEAR
    assert r.salary_max_usd is None
    assert r.salary_period == "hourly"


def test_hourly_range():
    r = extract_salary("$45 - $60/hour DOE")
    assert r is not None
    assert r.salary_min_usd == 45 * _HOURS_PER_YEAR
    assert r.salary_max_usd == 60 * _HOURS_PER_YEAR
    assert r.salary_period == "hourly"


# --- extract_salary: single k with context ---


def test_single_k_with_base_context():
    r = extract_salary("Base $400k + Bonus and sign on.")
    assert r is not None
    assert r.salary_min_usd == 400_000
    assert r.salary_max_usd is None
    assert r.salary_period == "yearly"


def test_single_k_with_salary_context():
    r = extract_salary("Salary: $120k plus equity.")
    assert r is not None
    assert r.salary_min_usd == 120_000


def test_single_k_no_context_ignored():
    # "$50k in Series A funding" should not match
    r = extract_salary("The company raised $50k in their seed round.")
    assert r is None


def test_single_k_out_of_range_ignored():
    r = extract_salary("Base salary $5k (per day contract)")
    assert r is None


# --- extract_salary: edge cases ---


def test_none_input():
    assert extract_salary(None) is None  # type: ignore[arg-type]


def test_empty_string():
    assert extract_salary("") is None


def test_no_salary_in_text():
    r = extract_salary("We are looking for a talented engineer to join our team.")
    assert r is None


def test_real_recruiter_text():
    text = (
        "Compensation Package will include base ($200-275k) + "
        "a extremely competitive equity portion."
    )
    r = extract_salary(text)
    assert r is not None
    assert r.salary_min_usd == 200_000
    assert r.salary_max_usd == 275_000


def test_approach_phrasing():
    text = "Base can approach $400k + equity."
    r = extract_salary(text)
    assert r is not None
    assert r.salary_min_usd == 400_000
