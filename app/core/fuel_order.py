"""Presentation order only; never changes product identity or prices."""
FUEL_IDS = ('NL000001', 'NL000002', 'NL000003')

def fuel_key(value):
    code = str(value).strip()
    return (FUEL_IDS.index(code) if code in FUEL_IDS else len(FUEL_IDS), code)

def ordered_fuels(values, key):
    return sorted(values, key=lambda item: fuel_key(key(item)))
