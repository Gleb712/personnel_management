from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from core.models import Employee, Workshop
from datetime import date
from collections import defaultdict, OrderedDict

CATEGORY_RSS     = 'РСС'
CATEGORY_WORKERS = 'Рабочие'


def get_headcount_report(production_id=None, workshop_id=None):
    """
    Отчёт «Численность» — срез на текущий момент (только работающие).

    Структура: строки = цех, колонки = Всего / РСС / Рабочие.
    Строки сгруппированы по производству с промежуточными итогами.
    """
    # Фильтр активных сотрудников — путь через related name workshop_employees
    active_q = Q(workshop_employees__dismissal_date__isnull=True)
    if production_id:
        active_q &= Q(workshop_employees__production_id=production_id)
    if workshop_id:
        active_q &= Q(id=workshop_id)

    rows = list(
        Workshop.objects
        .annotate(
            total=Count(
                'workshop_employees',
                filter=Q(workshop_employees__dismissal_date__isnull=True)
                       & (Q(workshop_employees__production_id=production_id) if production_id else Q())
            ),
            rss=Count(
                'workshop_employees',
                filter=Q(workshop_employees__dismissal_date__isnull=True)
                       & Q(workshop_employees__employee_category__name=CATEGORY_RSS)
                       & (Q(workshop_employees__production_id=production_id) if production_id else Q())
            ),
            workers=Count(
                'workshop_employees',
                filter=Q(workshop_employees__dismissal_date__isnull=True)
                       & Q(workshop_employees__employee_category__name=CATEGORY_WORKERS)
                       & (Q(workshop_employees__production_id=production_id) if production_id else Q())
            ),
        )
        .filter(
            total__gt=0,
            **({'id': workshop_id} if workshop_id else {})
        )
        .select_related('production')
        .order_by('production__name', 'number')
    )

    # Группируем по производству
    by_production = OrderedDict()
    for ws in rows:
        prod_name = ws.production.name if ws.production else '—'
        if prod_name not in by_production:
            by_production[prod_name] = {
                'name':      prod_name,
                'workshops': [],
                'total':     0,
                'rss':       0,
                'workers':   0,
            }
        by_production[prod_name]['workshops'].append(ws)
        by_production[prod_name]['total']   += ws.total
        by_production[prod_name]['rss']     += ws.rss
        by_production[prod_name]['workers'] += ws.workers

    grand_total   = sum(p['total']   for p in by_production.values())
    grand_rss     = sum(p['rss']     for p in by_production.values())
    grand_workers = sum(p['workers'] for p in by_production.values())

    return {
        'by_production': list(by_production.values()),
        'grand_total':   grand_total,
        'grand_rss':     grand_rss,
        'grand_workers': grand_workers,
    }


def get_movement_report(production_id=None, workshop_id=None, year=None):
    """
    Отчёт «Движение персонала» за год.

    Таблица 1 — Помесячная динамика:
        Месяц / Принято / Уволено / Разница / Численность на конец месяца

    Таблица 2 — Текучесть по цехам:
        Производство / Цех / Среднесписочная / Принято / Уволено / Разница / Текучесть в %

    Таблица 3 — Причины увольнений (общая сводка):
        Причина / Кол-во / %

    Таблица 4 — Матрица цех × причина:
        Цех / Производство / <причина 1> / <причина 2> / ... / Итого
    """
    if year is None:
        year = date.today().year

    year_start = date(year, 1, 1)
    year_end   = date(year, 12, 31)

    base_q = Q()
    if production_id:
        base_q &= Q(production_id=production_id)
    if workshop_id:
        base_q &= Q(workshop_id=workshop_id)

    # Таблица 1: помесячная динамика
    hired_map = {
        r['month'].month: r['count']
        for r in Employee.objects
        .filter(base_q, hire_date__year=year)
        .annotate(month=TruncMonth('hire_date'))
        .values('month')
        .annotate(count=Count('id'))
    }
    dismissed_map = {
        r['month'].month: r['count']
        for r in Employee.objects
        .filter(base_q, dismissal_date__year=year)
        .annotate(month=TruncMonth('dismissal_date'))
        .values('month')
        .annotate(count=Count('id'))
    }

    MONTHS_RU = [
        'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
        'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
    ]

    # Численность на начало года
    headcount_start = Employee.objects.filter(
        base_q,
        hire_date__lt=year_start,
    ).filter(
        Q(dismissal_date__isnull=True) | Q(dismissal_date__gte=year_start)
    ).count()

    monthly_rows = []
    running = headcount_start
    for m in range(1, 13):
        h    = hired_map.get(m, 0)
        d    = dismissed_map.get(m, 0)
        diff = h - d
        running += diff
        monthly_rows.append({
            'month':     MONTHS_RU[m - 1],
            'hired':     h,
            'dismissed': d,
            'diff':      diff,
            'headcount': running,
        })

    total_hired     = sum(r['hired']     for r in monthly_rows)
    total_dismissed = sum(r['dismissed'] for r in monthly_rows)
    total_diff      = total_hired - total_dismissed

    # Таблица 2: текучесть по цехам
    ws_filter = Q()
    if production_id:
        ws_filter &= Q(production_id=production_id)
    if workshop_id:
        ws_filter &= Q(id=workshop_id)

    emp_q = Q(workshop_employees__production_id=production_id) if production_id else Q()

    workshop_rows = list(
        Workshop.objects
        .filter(ws_filter)
        .annotate(
            hired=Count(
                'workshop_employees',
                filter=emp_q & Q(workshop_employees__hire_date__year=year)
            ),
            dismissed=Count(
                'workshop_employees',
                filter=emp_q & Q(workshop_employees__dismissal_date__year=year)
            ),
            avg_count=Count(
                'workshop_employees',
                filter=emp_q
                       & Q(workshop_employees__hire_date__lte=year_end)
                       & (Q(workshop_employees__dismissal_date__isnull=True)
                          | Q(workshop_employees__dismissal_date__gte=year_start))
            ),
        )
        .filter(avg_count__gt=0)
        .order_by('production__name', 'number')
        .select_related('production')
    )

    # Считаем размер каждой группы производства для rowspan
    from collections import Counter
    prod_counts = Counter(
        ws.production.name if ws.production else '—'
        for ws in workshop_rows
    )
 
    prev_production = None
    for ws in workshop_rows:
        ws.diff          = ws.hired - ws.dismissed
        ws.turnover_rate = round(ws.dismissed / ws.avg_count * 100, 1) if ws.avg_count else 0
        current_production = ws.production.name if ws.production else '—'
        ws.is_first_in_production  = (current_production != prev_production)
        ws.production_group_size   = prod_counts[current_production]
        prev_production = current_production

    # Таблица 3: причины увольнений (общая сводка)
    reasons_total = list(
        Employee.objects
        .filter(base_q, dismissal_date__year=year, dismissal_reason__isnull=False)
        .values('dismissal_reason__name')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    total_with_reason = sum(r['count'] for r in reasons_total)
    max_count = reasons_total[0]['count'] if reasons_total else 1
    for r in reasons_total:
        # pct — доля от всех уволенных (для отображения числа)
        r['pct'] = round(r['count'] / total_with_reason * 100, 1) if total_with_reason else 0
        # bar_pct — ширина полоски относительно максимального значения (самая частая = 100%)
        r['bar_pct'] = round(r['count'] / max_count * 100, 1) if max_count else 0

    reason_order = [r['dismissal_reason__name'] for r in reasons_total]

    # Таблица 4: матрица цех × причина
    matrix_qs = list(
        Employee.objects
        .filter(base_q, dismissal_date__year=year, dismissal_reason__isnull=False)
        .values('workshop__number', 'workshop__production__name', 'dismissal_reason__name')
        .annotate(count=Count('id'))
        .order_by('workshop__number')
    )

    matrix      = defaultdict(lambda: defaultdict(int))
    ws_prod_map = {}
    for row in matrix_qs:
        ws_num  = row['workshop__number']
        ws_prod = row['workshop__production__name'] or '—'
        reason  = row['dismissal_reason__name']
        matrix[(ws_num, ws_prod)][reason] += row['count']
        ws_prod_map[ws_num] = ws_prod

    matrix_rows = []
    for ws_num, ws_prod in sorted(ws_prod_map.items()):
        row_data = matrix[(ws_num, ws_prod)]
        matrix_rows.append({
            'workshop':   ws_num,
            'production': ws_prod,
            'reasons':    {r: row_data.get(r, 0) for r in reason_order},
            'total':      sum(row_data.values()),
        })

    # Доступные годы для фильтра
    hire_years = set(
        Employee.objects.filter(base_q)
        .values_list('hire_date__year', flat=True).distinct()
    )
    dismissal_years = set(
        Employee.objects.filter(base_q, dismissal_date__isnull=False)
        .values_list('dismissal_date__year', flat=True).distinct()
    )
    available_years = sorted(hire_years | dismissal_years, reverse=True)

    return {
        'year':             year,
        'headcount_start':  headcount_start,
        'total_hired':      total_hired,
        'total_dismissed':  total_dismissed,
        'total_diff':       total_diff,
        'monthly_rows':     monthly_rows,
        'workshop_rows':    workshop_rows,
        'reasons_total':    reasons_total,
        'reason_order':     reason_order,
        'matrix_rows':      matrix_rows,
        'available_years':  available_years,
    }