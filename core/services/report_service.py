from django.db.models import Count, Q
from core.models import Employee, Production, Workshop, Position, EmployeeCategory


def get_headcount_report(production_id=None, workshop_id=None):
    """
    Отчет "Численность по подразделениям"
    Возвращает агрегированные данные для таблицы и графиков

    Args:
        production_id: фильтр по производству (необязательный)
        workshop_id: фильтр по цеху (необязательный)

    Returns:
        dict: все срезы данных + итоговые цифры
    """

    # Итоговые цифры считаем напрямую по Employee
    base_qs = Employee.objects.all()
    if production_id:
        base_qs = base_qs.filter(production_id=production_id)
    if workshop_id:
        base_qs = base_qs.filter(workshop_id=workshop_id)

    total           = base_qs.count()
    total_active    = base_qs.filter(dismissal_date__isnull=True).count()
    total_dismissed = base_qs.filter(dismissal_date__isnull=False).count()

    # Срез 1: по производствам
    # Фильтр внутри Count строится относительно Production, путь к сотруднику идет через related_name и production_employees
    prod_qs = Production.objects.all()
    if production_id:
        prod_qs = prod_qs.filter(id=production_id)

    # Фильтр по цеху для среза производств - через сотрудника
    ws_q = Q(production_employees__workshop_id=workshop_id) if workshop_id else Q()

    by_production = list(
        prod_qs.annotate(
            active=Count(
                'production_employees',
                filter=ws_q & Q(production_employees__dismissal_date__isnull=True)
            ),
            dismissed=Count(
                'production_employees',
                filter=ws_q & Q(production_employees__dismissal_date__isnull=False)
            ),
            total=Count('production_employees', filter=ws_q),
        )
        .filter(total__gt=0)
        .order_by('-total')
    )

    # Срез 2: по цехам
    # Фильтр по производству - через поле production на самой Workshop
    ws_qs = Workshop.objects.select_related('production')
    if production_id:
        ws_qs = ws_qs.filter(production_id=production_id)
    if workshop_id:
        ws_qs = ws_qs.filter(id=workshop_id)

    # Фильтр по production_id внутри Count через related сотрудника
    prod_q = Q(workshop_employees__production_id=production_id) if production_id else Q()

    by_workshop = list(
        ws_qs.annotate(
            active=Count(
                'workshop_employees',
                filter=prod_q & Q(workshop_employees__dismissal_date__isnull=True)
            ),
            dismissed=Count(
                'workshop_employees',
                filter=prod_q & Q(workshop_employees__dismissal_date__isnull=False)
            ),
            total=Count('workshop_employees', filter=prod_q),
        )
        .filter(total__gt=0)
        .order_by('-total')
    )

    # Срез 3: по должностям
    # Фильтры по производству и цеху через related_name и position_employees
    pos_filter = Q()
    if production_id:
        pos_filter &= Q(position_employees__production_id=production_id)
    if workshop_id:
        pos_filter &= Q(position_employees__workshop_id=workshop_id)

    by_position = list(
        Position.objects.annotate(
            active=Count(
                'position_employees',
                filter=pos_filter & Q(position_employees__dismissal_date__isnull=True)
            ),
            dismissed=Count(
                'position_employees',
                filter=pos_filter & Q(position_employees__dismissal_date__isnull=False)
            ),
            total=Count('position_employees', filter=pos_filter),
        )
        .filter(total__gt=0)
        .order_by('-total')
    )

    # Срез 4: по категориям работников
    # Фильтры через related_name и category_employees
    cat_filter = Q()
    if production_id:
        cat_filter &= Q(category_employees__production_id=production_id)
    if workshop_id:
        cat_filter &= Q(category_employees__workshop_id=workshop_id)

    by_category = list(
        EmployeeCategory.objects.annotate(
            active=Count(
                'category_employees',
                filter=cat_filter & Q(category_employees__dismissal_date__isnull=True)
            ),
            dismissed=Count(
                'category_employees',
                filter=cat_filter & Q(category_employees__dismissal_date__isnull=False)
            ),
            total=Count('category_employees', filter=cat_filter),
        )
        .filter(total__gt=0)
        .order_by('-total')
    )

    return {
        'total':           total,
        'total_active':    total_active,
        'total_dismissed': total_dismissed,
        'by_production':   by_production,
        'by_workshop':     by_workshop,
        'by_position':     by_position,
        'by_category':     by_category,
    }
