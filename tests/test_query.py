import pytest
from job_scraper.query import (
    LinkedInSearchQuery,
    SALARY_FLOOR,
    TIME_DAY,
    TIME_WEEK,
    TIME_MONTH,
    TIME_ANY,
)


def test_default_params_include_required_keys():
    params = LinkedInSearchQuery(keywords="Python").to_params()
    assert params["keywords"] == "Python"
    assert params["geoId"] == "103644278"
    assert "f_TPR" in params  # TIME_DAY is the default


def test_start_offset_passed_through():
    params = LinkedInSearchQuery(keywords="Python").to_params(start=25)
    assert params["start"] == 25


def test_time_any_omits_f_tpr():
    params = LinkedInSearchQuery(keywords="Python", time_posted=TIME_ANY).to_params()
    assert "f_TPR" not in params


def test_time_day_value():
    params = LinkedInSearchQuery(keywords="Python", time_posted=TIME_DAY).to_params()
    assert params["f_TPR"] == "r86400"


def test_time_week_value():
    params = LinkedInSearchQuery(keywords="Python", time_posted=TIME_WEEK).to_params()
    assert params["f_TPR"] == "r604800"


def test_time_month_value():
    params = LinkedInSearchQuery(keywords="Python", time_posted=TIME_MONTH).to_params()
    assert params["f_TPR"] == "r2592000"


@pytest.mark.parametrize("salary,expected_sb2", list(SALARY_FLOOR.items()))
def test_salary_floor_encoding(salary, expected_sb2):
    params = LinkedInSearchQuery(keywords="Python", salary_floor=salary).to_params()
    assert params["f_SB2"] == expected_sb2


def test_invalid_salary_floor_omitted():
    params = LinkedInSearchQuery(keywords="Python", salary_floor=99_999).to_params()
    assert "f_SB2" not in params


def test_no_salary_floor_omits_f_sb2():
    params = LinkedInSearchQuery(keywords="Python", salary_floor=None).to_params()
    assert "f_SB2" not in params


def test_to_url_contains_base_and_params():
    q = LinkedInSearchQuery(keywords="LLM Ops", time_posted=TIME_ANY)
    url = q.to_url("https://example.com/api", start=0)
    assert url.startswith("https://example.com/api?")
    assert "keywords=LLM+Ops" in url


def test_to_url_start_param_in_url():
    q = LinkedInSearchQuery(keywords="Python", time_posted=TIME_ANY)
    url = q.to_url("https://example.com/api", start=50)
    assert "start=50" in url


def test_experience_default():
    params = LinkedInSearchQuery(keywords="Python").to_params()
    assert params["f_E"] == "2,3,4,5"


def test_workplace_default_is_remote():
    params = LinkedInSearchQuery(keywords="Python").to_params()
    assert params["f_WT"] == "2"


def test_job_type_default_is_fulltime():
    params = LinkedInSearchQuery(keywords="Python").to_params()
    assert params["f_JT"] == "F"
