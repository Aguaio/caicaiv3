
from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()


@register.filter
def get_item(d, key):
    return d.get(key, [])


@register.filter
def precio_clp(value):
    """
    Formatea un valor numerico como CLP: $8.000 (sin decimales, miles con punto).
    """
    if value in (None, ''):
        return '$0'
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return '$0'

    dec = dec.quantize(Decimal('1'))
    num = int(dec)
    formatted = f'{num:,}'.replace(',', '.')
    return f'${formatted}'
