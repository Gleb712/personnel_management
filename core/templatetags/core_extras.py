from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Позволяет обращаться к словарю по ключу в шаблоне: dict|get_item:key"""
    return dictionary.get(key, 0)

@register.filter
def intspace(value):
    if value is None:
        return "0"
    try:
        num = float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return value
    return f"{num:,.2f}".replace(",", " ").replace(".", ",")
