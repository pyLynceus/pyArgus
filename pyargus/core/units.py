"""Length units.

Two different feet exist in this work and mixing them is a real error,
not a rounding one: over the coordinates of a Georgia state-plane
project the difference is several feet of easting. Every conversion in
the suite goes through this module so the choice is always explicit.
"""

# Exact by definition.
M_PER_US_SURVEY_FOOT = 1200.0 / 3937.0
M_PER_INTL_FOOT = 0.3048


def usft_to_m(value):
    return value * M_PER_US_SURVEY_FOOT


def m_to_usft(value):
    return value / M_PER_US_SURVEY_FOOT


def ift_to_m(value):
    return value * M_PER_INTL_FOOT


def m_to_ift(value):
    return value / M_PER_INTL_FOOT
