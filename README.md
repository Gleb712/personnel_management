# Очистка БД через clear_employees.py
Использование:

# Только сотрудники
python manage.py clear_employees

# Сотрудники + все справочники
python manage.py clear_employees --all

# Без подтверждения (для скриптов)
python manage.py clear_employees --all --yes