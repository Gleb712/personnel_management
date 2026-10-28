from functools import wraps
from django.http import JsonResponse
from django.utils import timezone

from .models import APIAccessKey

def api_key_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.GET.get('api_key')

        if not api_key:
            return JsonResponse({
                'error': 'API ключ обязателен',
                'hint': 'Передайте ключ в заголовке X-API-Key'
            }, status=401)
        
        try:
            key_obj = APIAccessKey.objects.get(key=api_key)

            if not key_obj.is_valid():
                return JsonResponse({
                    'error': 'API ключ недествителен или истек'
                }, status=401)
            
            key_obj.last_used = timezone.now()
            key_obj.save()

            request.api_user = key_obj.user
        except APIAccessKey.DoesNotExist:
            return JsonResponse({
                'error': 'Недействительный API ключ'
            }, status=403)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper
