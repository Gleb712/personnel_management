from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Позволяет обращаться к словарю по ключу в шаблоне: dict|get_item:key"""
    return dictionary.get(key, 0)
