from datetime import UTC, datetime

from mathscout.admin.routes import _display
from mathscout.utils.time import display_datetime


def test_admin_display_treats_naive_datetimes_as_utc_and_shows_utc_plus_8() -> None:
    assert _display(datetime(2026, 6, 5, 2, 30)) == "2026-06-05 10:30"


def test_display_datetime_converts_aware_utc_to_shanghai_time() -> None:
    value = datetime(2026, 6, 5, 2, 30, tzinfo=UTC)

    converted = display_datetime(value)

    assert converted.hour == 10
    assert converted.minute == 30
