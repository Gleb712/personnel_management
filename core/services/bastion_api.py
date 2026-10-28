import json
import requests
from datetime import datetime
from django.utils import timezone
from django.conf import settings
from typing import Optional, Dict, Any

class BastionApi:
    def __init__(self):
        self.api_ready = getattr(settings, 'API_READY_ENDPOINT', None)
        self.api_health = getattr(settings, 'API_HEALTH_ENDPOINT', None)
        self.api_settings = getattr(settings, 'API_SETTINGS_ENDPOINT', None)

    def check_ready_status(self, token: Optional[str] = None):
        """Проверяет статус ready"""
        if not self.api_ready:
            return {
                'is_ready': False,
                'detail': 'API_READY_ENDPOINT не настроен',
                'timestamp': timezone.now().isoformat(),
                'error': True
            }
        
        try:
            headers = {}
            if token:
                headers['Authorization'] = f'Bearer {token}'
            
            response = requests.get(self.api_ready, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            return {
                'is_ready': data.get('ready', False),
                'detail': data.get('detail', ''),
                'timestamp': timezone.now().isoformat(),
                'raw_data': data
            }
        except Exception as e:
            return {
                'is_ready': False,
                'detail': f'Ошибка подключения: {str(e)}',
                'timestamp': timezone.now().isoformat(),
                'error': True,
                'error_message': str(e)
            }
    
    def check_health_status(self, token: Optional[str] = None):
        """Проверяет статус health"""
        if not self.api_health:
            return {
                'is_healthy': False,
                'jobs': [],
                'timestamp': timezone.now().isoformat(),
                'error': True,
                'error_message': 'API_HEALTH_ENDPOINT not configured'
            }
        
        try:
            headers = {}
            if token:
                headers['Authorization'] = f'Bearer {token}'
            
            response = requests.get(self.api_health, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            jobs_status = []
            for job_name, job_data in data.get('jobs', {}).items():
                jobs_status.append({
                    'name': job_name,
                    'alive': job_data.get('alive', False),
                    'status': 'alive' if job_data.get('alive', False) else 'dead',
                    'last_status': job_data.get('last_status', 'unknown'),
                    'last_message': job_data.get('last_message', ''),
                    'consecutive_errors': job_data.get('consecutive_errors', 0),
                    'seconds_since_last_activity': job_data.get('seconds_since_last_activity'),
                    'max_staleness_seconds': job_data.get('max_staleness_seconds', 0),
                    'raw_data': job_data
                })
            
            is_healthy = data.get('status') == 'ok'
            
            return {
                'is_healthy': is_healthy,
                'jobs': jobs_status,
                'timestamp': timezone.now().isoformat(),
                'raw_data': data
            }
        except Exception as e:
            return {
                'is_healthy': False,
                'jobs': [],
                'timestamp': timezone.now().isoformat(),
                'error': True,
                'error_message': str(e)
            }
        
    def get_full_status(self, token: Optional[str] = None):
        ready_status = self.check_ready_status(token)
        health_status = self.check_health_status(token)
        
        return {
            'ready': ready_status,
            'health': health_status,
            'overall_status': 'OK' if ready_status.get('is_ready') and health_status.get('is_healthy') else 'FAIL',
            'timestamp': timezone.now().isoformat()
        }
    
    def get_settings(self, token: str) -> Dict[str, Any]:
        """
        GET /api/settings - получает все настройки
        """
        result = {
            'success': False,
            'settings': None,
            'error': None,
            'status_code': None
        }
        
        if not self.api_settings:
            result['error'] = 'API_SETTINGS_ENDPOINT не настроен'
            return result
        
        try:
            headers = {'Authorization': f'Bearer {token}'}
            url = self.api_settings
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            result['settings'] = response.json()
            result['status_code'] = response.status_code
            result['success'] = True
            
        except requests.exceptions.RequestException as e:
            result['error'] = f'Ошибка запроса: {str(e)}'
            if hasattr(e, 'response') and e.response:
                result['status_code'] = e.response.status_code
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def patch_setting(self, token: str, key: str, value: int) -> Dict[str, Any]:
        """
        PATCH /api/settings/{key} - изменяет одну настройку
        """
        result = {
            'success': False,
            'key': key,
            'value': None,
            'error': None,
            'status_code': None
        }
        
        if not self.api_settings:
            result['error'] = 'API_SETTINGS_ENDPOINT не настроен'
            return result
        
        # Проверка допустимых ключей
        valid_keys = ['poll_interval_seconds', 'cron_hours', 'cron_minutes', 'external_queue_interval_seconds']
        if key not in valid_keys:
            result['error'] = f'Неизвестный ключ: {key}. Допустимые: {", ".join(valid_keys)}'
            result['status_code'] = 404
            return result
        
        try:
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            url = f"{self.api_settings.rstrip('/')}/{key}"
            payload = {'value': value}
            
            response = requests.patch(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            result['value'] = data.get('value')
            result['status_code'] = response.status_code
            result['success'] = True
            
        except requests.exceptions.RequestException as e:
            result['error'] = f'Ошибка запроса: {str(e)}'
            if hasattr(e, 'response') and e.response:
                result['status_code'] = e.response.status_code
                try:
                    result['response_data'] = e.response.json()
                except:
                    pass
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def send_api_request(self, method: str, key: str, token: str, value: Optional[int] = None) -> Dict[str, Any]:
        """
        Отправляет запрос к API настроек
        """
        if method == 'GET':
            return self.get_settings(token)
        elif method == 'PATCH':
            return self.patch_setting(token, key, value)
        else:
            return {
                'success': False,
                'error': f'Метод {method} не поддерживается'
            }