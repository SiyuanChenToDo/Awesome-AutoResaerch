"""Conservative Semantic Scholar DateOrYear windows for every retrieval path."""
from datetime import date
from calendar import monthrange
import re
from .errors import ConfigurationError


def date_interval(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}(?:-\d{2}(?:-\d{2})?)?', value):
        raise ConfigurationError('publication_date must use YYYY, YYYY-MM or YYYY-MM-DD bounds')
    parts = [int(x) for x in value.split('-')]
    try:
        year = parts[0]
        month = parts[1] if len(parts) >= 2 else 1
        first = date(year, month, parts[2] if len(parts) == 3 else 1)
        last = first if len(parts) == 3 else date(year, month, monthrange(year, month)[1]) if len(parts) == 2 else date(year, 12, 31)
    except (ValueError, OverflowError):
        raise ConfigurationError('publication_date contains an invalid calendar date') from None
    return first, last


def publication_window(value):
    if not isinstance(value, str) or value.count(':') > 1:
        raise ConfigurationError('publication_date must be a date or an inclusive start:end range')
    if ':' not in value:
        return date_interval(value)
    left, right = value.split(':')
    if not left and not right:
        raise ConfigurationError('publication_date range cannot have two empty bounds')
    start = date_interval(left)[0] if left else date.min
    end = date_interval(right)[1] if right else date.max
    if start > end:
        raise ConfigurationError('publication_date range is reversed')
    return start, end


def within_window(paper, window):
    if window is None:
        return True
    value = paper.publication_date or (str(paper.year) if paper.year is not None else None)
    if value is None:
        return False
    try:
        start, end = date_interval(value)
    except ConfigurationError:
        return False
    lower, upper = publication_window(window)
    # Year-only metadata crossing a precise day boundary cannot prove inclusion.
    return start >= lower and end <= upper
