import re


TELEFONO_REGEX = re.compile(r'^\+569\d{8}$')


def normalizar_telefono(valor: str) -> str:
    """
    Elimina espacios y deja el telefono en formato compactado.
    """
    return (valor or '').strip().replace(' ', '')


def validar_telefono_formato(valor: str) -> str:
    """
    Valida que el telefono cumpla el formato +569XXXXXXXX.
    Devuelve el valor normalizado o levanta ValueError con mensaje descriptivo.
    """
    valor_normalizado = normalizar_telefono(valor)
    if not valor_normalizado:
        return valor_normalizado

    if not TELEFONO_REGEX.match(valor_normalizado):
        raise ValueError('Ingresa un nÇ§mero de telÇ¸fono con formato +569XXXXXXXX.')

    return valor_normalizado
