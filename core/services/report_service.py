from django.db.models import Count, Q, F, DurationField, ExpressionWrapper, fields, Case, When, Value, Window, Avg, Func, Max
from django.db.models.functions import TruncMonth, RowNumber, Extract, Now, ExtractYear
from core.models import Employee, Workshop, EmployeeCategory, DismissalReason, HireSource, Production, EmployeeTransfers, EmployeeHistory, ReportTable
from datetime import date, timedelta, datetime
import calendar
from collections import defaultdict, OrderedDict

MONTHS_RU = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]


def get_headcount_report(production_id=None, workshop_id=None):
    # Получаем все категории из БД
    # categories = list(EmployeeCategory.objects.values_list('name', flat=True).order_by('name'))
    categories = list(EmployeeCategory.objects.values('pk', 'name').order_by('name'))

    active_filter = Q(workshop_employees__dismissal_date__isnull=True, workshop_employees__employee_category__isnull=False)
    if production_id:
        active_filter &= Q(workshop_employees__production_id=production_id)

    annotations = {
        'total': Count(
            'workshop_employees',
            filter=Q(workshop_employees__dismissal_date__isnull=True)
                   & (Q(workshop_employees__production_id=production_id) if production_id else Q())
        ),
    }
    # Динамически добавляем аннотацию для каждой категории
    # for cat_name in categories:
    #     safe_key = f'cat_{cat_name}'  # ключ для аннотации
    #     annotations[safe_key] = Count(
    #         'workshop_employees',
    #         filter=Q(workshop_employees__dismissal_date__isnull=True)
    #                & Q(workshop_employees__employee_category__name=cat_name)
    #                & (Q(workshop_employees__production_id=production_id) if production_id else Q())
    #     )
    for cat in categories:
        safe_key = f'cat_{cat["pk"]}'  # ключ для аннотации
        if cat['name'] in {'Вспомогательные', 'РСС'}:
            annotations[safe_key] = Count(
                'workshop_employees',
                filter=Q(workshop_employees__dismissal_date__isnull=True)
                    & Q(workshop_employees__employee_category_id=cat['pk'])
                    & (Q(workshop_employees__production_id=production_id) if production_id else Q())
                    & (Q(workshop_employees__hire_category__name__in=('основная постояннаяШ', 'основная постоянная')))
            )
        elif cat['name'] == 'Ученики':
            annotations[safe_key] = Count(
                'workshop_employees',
                filter=Q(workshop_employees__dismissal_date__isnull=True)
                    & Q(workshop_employees__employee_category_id=cat['pk'])
                    & (Q(workshop_employees__production_id=production_id) if production_id else Q())
                    & (~Q(workshop_employees__hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
                       | Q(workshop_employees__hire_category__isnull=True))
            )
        elif cat['name'] == 'Основные':
            annotations[safe_key] = Count(
                'workshop_employees',
                filter=Q(workshop_employees__dismissal_date__isnull=True)
                & Q(workshop_employees__employee_category_id=cat['pk'])
                & (Q(workshop_employees__production_id=production_id) if production_id else Q())
                & Q(workshop_employees__hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
            ) +Count(
                'workshop_employees',
                filter=Q(workshop_employees__dismissal_date__isnull=True)
                & Q(workshop_employees__employee_category__name='Ученики')
                & (Q(workshop_employees__production_id=production_id) if production_id else Q())
                & Q(workshop_employees__hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
            )
        else:
            annotations[safe_key] = Count(
                'workshop_employees',
                filter=Q(workshop_employees__dismissal_date__isnull=True)
                    & Q(workshop_employees__employee_category_id=cat['pk'])
                    & (Q(workshop_employees__production_id=production_id) if production_id else Q())
            )

    rows = list(
        Workshop.objects
        .annotate(**annotations)
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
            # cat_totals = {cat: 0 for cat in categories}
            cat_totals = {cat['name']: 0 for cat in categories}
            by_production[prod_name] = {
                'name': prod_name,
                'workshops': [],
                'total': 0,
                'categories': cat_totals,
            }
        # Записываем значения категорий в объект цеха для доступа в шаблоне
        # ws.cat_values = {cat: getattr(ws, f'cat_{cat}', 0) for cat in categories}
        ws.cat_values = {cat['name']: getattr(ws, f'cat_{cat["pk"]}', 0) for cat in categories}
        by_production[prod_name]['workshops'].append(ws)
        by_production[prod_name]['total'] += ws.total
        for cat in categories:
            # by_production[prod_name]['categories'][cat] += ws.cat_values.get(cat, 0)
            by_production[prod_name]['categories'][cat['name']] += ws.cat_values.get(cat['name'], 0)            

    grand_total = sum(p['total'] for p in by_production.values())
    work_atm = Employee.objects.filter(
        dismissal_date__isnull=True,
        employee_category__isnull=False,
        hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
    ).exclude(
        employee_category__name__in=('Аутстафферы', 'Научно-производственное')
    ).count()
    # grand_categories = {cat: 0 for cat in categories}
    grand_categories = {cat['name']: 0 for cat in categories}
    for p in by_production.values():
        for cat in categories:
            # grand_categories[cat] += p['categories'][cat]
            grand_categories[cat['name']] += p['categories'][cat['name']]

    return {
        'by_production':    list(by_production.values()),
        'grand_total':      grand_total,
        'work_atm':         work_atm,
        'grand_categories': grand_categories,  # {'РСС': 120, 'Рабочие': 340, 'Стажёры': 15, ...}
        # 'categories':       categories,        # ['РСС', 'Рабочие', 'Стажёры', ...]
        'categories':       [cat['name'] for cat in categories],        # ['РСС', 'Рабочие', 'Стажёры', ...]
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

    base_q = Q(employee_category__isnull=False)
    if production_id:
        base_q &= Q(production_id=production_id)
    if workshop_id:
        base_q &= Q(workshop_id=workshop_id)

    # Таблица 1: помесячная динамика
    hired_map_1 = {
        r['month'].month: r['count']
        for r in Employee.objects
        .filter(base_q, hire_date__year=year, employee_category__isnull=False, hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
        .exclude(employee_category__name__in=('Аутстафферы', 'Научно-производственное'))
        .annotate(month=TruncMonth('hire_date'))
        .values('month')
        .annotate(count=Count('id'))
    }
    hired_map = {
        r['month'].month: r['count']
        for r in EmployeeHistory.objects
        .filter(
            hiring_date__year=year, 
            employee__employee_category__isnull=False, 
            hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
        )
        .exclude(employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное'))
        .annotate(month=TruncMonth('hiring_date'))
        .values('month')
        .annotate(count=Count('id'))
    }
    dismissed_map_1 = {
        r['month'].month: r['count']
        for r in Employee.objects
        .filter(base_q, dismissal_date__year=year, employee_category__isnull=False, hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
        .exclude(employee_category__name__in=('Аутстафферы', 'Научно-производственное'))
        .annotate(month=TruncMonth('dismissal_date'))
        .values('month')
        .annotate(count=Count('id'))
    }
    dismissed_map = {
        r['month'].month: r['count']
        for r in EmployeeHistory.objects
        .filter(
            dismissal_date__year=year, 
            employee__employee_category__isnull=False, 
            # employee__hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
        ).filter(Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')) | Q(hire_category__isnull=True))
        .exclude(
            Q(employee__employee_category__name='Аутстафферы')
            | Q(employee__employee_category__name='Научно-производственное')
            | (Q(employee__employee_category__name='Ученики') & ~Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')))
        )
        .annotate(month=TruncMonth('dismissal_date'))
        .values('month')
        .annotate(count=Count('id'))
    }

    hired_trainees_map = {
        r['month'].month: r['count']
        for r in Employee.objects
        .filter(base_q, hire_date__year=year, employee_category__name='Ученики')
        .exclude(hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
        .annotate(month=TruncMonth('hire_date'))
        .values('month')
        .annotate(count=Count('id'))
    }
    dismissed_trainees_map = {
        r['month'].month: r['count']
        for r in Employee.objects
        .filter(base_q, dismissal_date__year=year, employee_category__name='Ученики')
        .exclude(hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
        .annotate(month=TruncMonth('dismissal_date'))
        .values('month')
        .annotate(count=Count('id'))
    }

    # Численность на начало года
    headcount_start = Employee.objects.filter(
        base_q,
        hire_date__lte=year_start,
        hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
    ).filter(
        Q(dismissal_date__isnull=True) | Q(dismissal_date__gte=year_start)
    ).exclude(employee_category__name__in=('Аутстафферы', 'Научно-производственное')).count()

    monthly_rows = []
    running = headcount_start
    for m in range(1, 13):
        h    = hired_map.get(m, 0)
        d    = dismissed_map.get(m, 0)
        h_1  = hired_map_1.get(m, 0)
        d_1  = dismissed_map_1.get(m, 0)
        ht   = hired_trainees_map.get(m, 0)
        dt   = dismissed_trainees_map.get(m, 0)
        # diff = h - d
        diff = h_1 - d_1
        running += diff
        monthly_rows.append({
            'month':                MONTHS_RU[m - 1],
            'hired':                h,
            'dismissed':            d,
            'hired_trainees':       ht,
            'dismissed_trainees':   dt,
            'diff':                 diff,
            'headcount':            running,
        })

    total_hired                 = sum(r['hired']                for r in monthly_rows)
    total_dismissed             = sum(r['dismissed']            for r in monthly_rows)
    total_trainees_hired        = sum(r['hired_trainees']       for r in monthly_rows)
    total_trainees_dismissed    = sum(r['dismissed_trainees']   for r in monthly_rows)
    total_diff                  = total_hired - total_dismissed

    # Таблица 2: текучесть по цехам
    ws_filter = Q()
    if production_id:
        ws_filter &= Q(production_id=production_id)
    if workshop_id:
        ws_filter &= Q(id=workshop_id)

    emp_q = Q(workshop_employees__production_id=production_id) if production_id else Q()
    emp_q &= ~Q(workshop_employees__employee_category__name='Ученики')
    emp_q &= ~Q(workshop_employees__employee_category__name='Аутстафферы')
    emp_q &= ~Q(workshop_employees__employee_category__name='Научно-производственное')
    emp_q &= Q(workshop_employees__employee_history__hire_category__name__in=('основная постояннаяШ', 'основная постоянная')) 

    workshop_rows = list(
        Workshop.objects
        .filter(ws_filter)
        .annotate(
            hired=Count(
                'workshop_employees__employee_history',
                filter=emp_q 
                    & Q(workshop_employees__employee_history__hiring_date__year=year)
            ),
            dismissed=Count(
                'workshop_employees__employee_history',
                filter=emp_q & Q(workshop_employees__employee_history__dismissal_date__year=year)
            ),
            avg_count=Count(
                'workshop_employees__employee_history',
                filter=emp_q
                       & Q(workshop_employees__employee_history__hiring_date__lte=year_end)
                       & (Q(workshop_employees__employee_history__dismissal_date__isnull=True)
                          | Q(workshop_employees__employee_history__dismissal_date__gte=year_start))
            ),
            on_year_start=Count(
                'workshop_employees__employee_history',
                filter=emp_q
                       & Q(workshop_employees__employee_history__hiring_date__year__lte=year)
                       & (Q(workshop_employees__employee_history__dismissal_date__year__gt=year)
                       | Q(workshop_employees__employee_history__dismissal_date__isnull=True))
            ),
            # on_year_end=Count(
            #     'workshop_employees',
            #     filter=emp_q
            #            & Q(workshop_employees__hire_date__year__lte=year)
            #            & ~Q(workshop_employees__dismissal_date__year__lte=year)
            #            | Q(workshop_employees__dismissal_date__isnull=True)
            # ),
        ).annotate(
            on_year_end=F('on_year_start') + F('hired') - F('dismissed'),
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
        ws.new_turnover_rate = round(ws.dismissed / ws.on_year_start * 100, 1) if ws.on_year_start else 0 # С учётом on_year_start
        current_production = ws.production.name if ws.production else '—'
        ws.is_first_in_production  = (current_production != prev_production)
        ws.production_group_size   = prod_counts[current_production]
        prev_production = current_production

    # Таблица 3: причины увольнений (общая сводка)
    # reasons_total = list(
    #     Employee.objects
    #     # .filter(base_q, dismissal_date__year=year, dismissal_reason__isnull=False)
    #     .filter(base_q, dismissal_date__year=year, dismissal_reason__isnull=False, hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
    #     .exclude(employee_category__name__in=('Ученики', 'Аутстафферы'))
    #     .values('dismissal_reason__name')
    #     .annotate(count=Count('id'))
    #     .order_by('-count')
    # )
    reasons_total = list(
        EmployeeHistory.objects
        .filter(
            employee__employee_category__isnull=False,
            dismissal_date__year=year, 
            dismissal_reason__isnull=False, 
        )
        .filter(Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')) | Q(hire_category__isnull=True))
        .exclude(
            Q(employee__employee_category__name=('Аутстафферы'))
            | Q(employee__employee_category__name=('Научно-производственное'))
            | (Q(employee__employee_category__name='Ученики') & ~Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')))
        )
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
        EmployeeHistory.objects
        .filter(
            employee__employee_category__isnull=False,
            dismissal_date__year=year, 
            dismissal_reason__isnull=False)
        .filter(Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
                | Q(hire_category__isnull=True))
        .exclude(
            Q(employee__employee_category__name='Аутстафферы')
              | Q(employee__employee_category__name='Научно-производственное')
              | (Q(employee__employee_category__name='Ученики')
                   & ~Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')))
        )
        .values(
            'employee__workshop__number', 
            'employee__workshop__production__name', 
            'dismissal_reason__name'
        )
        .annotate(count=Count('id'))
        .order_by('employee__workshop__number')
    )

    matrix      = defaultdict(lambda: defaultdict(int))
    ws_prod_map = {}
    for row in matrix_qs:
        ws_num  = row['employee__workshop__number']
        ws_prod = row['employee__workshop__production__name'] or '—'
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
        Employee.objects.filter(base_q, hire_date__year__gte=2020)
        .values_list('hire_date__year', flat=True).distinct()
    )
    dismissal_years = set(
        Employee.objects.filter(base_q, dismissal_date__isnull=False, dismissal_date__year__gte=2020)
        .values_list('dismissal_date__year', flat=True).distinct()
    )
    available_years = sorted(hire_years | dismissal_years, reverse=True)

    meaningful_transfer = ~Q(
        from_workshop__production_id=F('to_workshop__production_id'),
        # from_category=F('to_category')
    )
    transfers_count = EmployeeTransfers.objects.filter(
        meaningful_transfer,
        transfer_date__range=(year_start, year_end),
        employee__employee_category__name__isnull=False,
        employee__hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
    ).exclude(
        employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
    ).count()

    return {
        'year':              year,
        'headcount_start':   headcount_start,
        'total_hired':       total_hired,
        'total_dismissed':   total_dismissed,
        'total_t_hired':     total_trainees_hired,
        'total_t_dismissed': total_trainees_dismissed,   
        'total_diff':        total_diff,
        'monthly_rows':      monthly_rows,
        'workshop_rows':     workshop_rows,
        'reasons_total':     reasons_total,
        'reason_order':      reason_order,
        'matrix_rows':       matrix_rows,
        'available_years':   available_years,
        'transfers_count':   transfers_count,
        'work_atm':          monthly_rows[date.today().month]['headcount']
    }

def get_dashboard_details_report(details_type=None, details_date=None):
    '''
        details_type:
            0 - Принято
            1 - Уволено
            2 - Работает сейчас
            3 - Принято учеников
            4 - Уволено учеников
    '''
    if details_type is None:
        details_type = 0
    if details_date is None:
        details_date = date.today() - timedelta(days=1)
    
    match details_date.weekday():
        case 5: details_date -= timedelta(days=1)
        case 6: details_date -= timedelta(days=2)

    period_end = details_date
    period_start = details_date - timedelta(days=2) if details_date.weekday() == 0 else details_date

    month_start = date(details_date.year, details_date.month, 1)
    year_start = date(details_date.year, 1, 1)
    month_end = date(details_date.year, details_date.month, calendar.monthrange(details_date.year, details_date.month)[1])
    year_end = date(details_date.year, 12, 31)
    reasons_stats = []
    less_year_stats = []
    total_today = 0
    total_month = 0
    total_year = 0     
    type_string = ''
    base_q = Q(employee_category__isnull=False)        

    match details_type:
        case 0:
            # reasons_stats = Employee.objects.filter(
            #     base_q, 
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            # ).annotate(
            #     reason_group=Case(
            #         When(hire_source__isnull=True, then=Value('Источник не указан')),
            #         When(hire_source__isnull=False, then=F('hire_source__name')),
            #     )                
            # ).exclude(
            #     employee_category__name__in=('Ученики', 'Аутстафферы', 'Научно-производственное')
            # ).values(
            #     'reason_group', 
            #     'hire_source_id'
            # ).annotate(
            #     today_count = Count('id', filter=Q(hire_date=details_date)),
            #     month_count = Count('id', filter=Q(hire_date__range=(month_start, month_end))),
            #     year_count = Count('id', filter=Q(hire_date__range=(year_start, year_end))),
            # ).order_by('-year_count')    
            reasons_stats = EmployeeHistory.objects.filter(
                employee__employee_category__isnull=False, 
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            ).annotate(
                reason_group=Case(
                    When(hire_source__isnull=True, then=Value('Источник не указан')),
                    When(hire_source__isnull=False, then=F('hire_source__name')),
                )                
            ).exclude(
                employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            ).values(
                'reason_group', 
                'hire_source_id'
            ).annotate(
                today_count = Count('id', filter=Q(hiring_date__range=(period_start, period_end))),
                month_count = Count('id', filter=Q(hiring_date__range=(month_start, month_end))),
                year_count = Count('id', filter=Q(hiring_date__range=(year_start, year_end))),
            ).order_by('-year_count')   

            total_today = sum(item['today_count'] for item in reasons_stats)
            total_month = sum(item['month_count'] for item in reasons_stats)
            total_year = sum(item['year_count'] for item in reasons_stats)   

            for item in reasons_stats:
                item['today_percent'] = round((item['today_count'] / total_today * 100), 1) if total_today > 0 else 0         
                item['month_percent'] = round((item['month_count'] / total_month * 100), 1) if total_month > 0 else 0
                item['year_percent'] = round((item['year_count'] / total_year * 100), 1) if total_year > 0 else 0      
            type_string = 'Принято'
        case 1:
            # reasons_stats = Employee.objects.filter(
            #     base_q,
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
            # ).exclude(
            #     employee_category__name__in=('Ученики', 'Аутстафферы', 'Научно-производственное')
            # ).annotate(
            #     reason_group=Case(
            #         When(dismissal_reason__isnull=True, then=Value('Причина не указана')),
            #         When(dismissal_reason__isnull=False, then=F('dismissal_reason__name')),
            #     )
            # ).values(
            #     'reason_group', 
            #     'dismissal_reason_id'
            # ).annotate(
            #     today_count = Count('id', filter=Q(dismissal_date=details_date)),
            #     month_count = Count('id', filter=Q(dismissal_date__range=(month_start, month_end))),
            #     year_count = Count('id', filter=Q(dismissal_date__range=(year_start, year_end))),
            # ).order_by('-year_count')    
            reasons_stats = EmployeeHistory.objects.filter(
                employee__employee_category__isnull=False, 
            ).filter(
                Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
            ).annotate(
                reason_group=Case(
                    When(dismissal_reason__isnull=True, then=Value('Причина не указана')),
                    When(dismissal_reason__isnull=False, then=F('dismissal_reason__name')),
                )
            ).exclude(
                Q(employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное'))
                | (Q(employee__employee_category__name='Ученики') & ~Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))),
            ).values(
                'reason_group', 
                'dismissal_reason_id'
            ).annotate(
                today_count = Count('id', filter=Q(dismissal_date__range=(period_start, period_end))),
                month_count = Count('id', filter=Q(dismissal_date__range=(month_start, month_end))),
                year_count = Count('id', filter=Q(dismissal_date__range=(year_start, year_end))),
            ).order_by('-year_count')  

            # less_year_today = Employee.objects.filter(
            #     dismissal_date=details_date,
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
            # ).exclude(
            #     employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            # ).annotate(
            #     tenure_days = ExpressionWrapper(
            #         F('dismissal_date') - F('hire_date'),
            #         output_field = fields.DurationField()
            #     )
            # ).filter(tenure_days__lt=timedelta(days=365)).count()

            # less_year_month = Employee.objects.filter(
            #     dismissal_date__gte=month_start, 
            #     dismissal_date__lte=month_end,
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            # ).exclude(
            #     employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            # ).annotate(
            #     tenure_days = ExpressionWrapper(
            #         F('dismissal_date') - F('hire_date'),
            #         output_field = fields.DurationField()
            #     )
            # ).filter(tenure_days__lt=timedelta(days=365)).count()        

            # less_year_year = Employee.objects.filter(
            #     dismissal_date__gte=year_start, 
            #     dismissal_date__lte=year_end,
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            # ).exclude(
            #     employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            # ).annotate(
            #     tenure_days = ExpressionWrapper(
            #         F('dismissal_date') - F('hire_date'),
            #         output_field = fields.DurationField()
            #     )
            # ).filter(tenure_days__lt=timedelta(days=365)).count()                 

            less_year_today = EmployeeHistory.objects.filter(
                dismissal_date__range=(period_start, period_end),
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
            ).exclude(
                employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            ).annotate(
                tenure_days = ExpressionWrapper(
                    F('dismissal_date') - F('hiring_date'),
                    output_field = fields.DurationField()
                )
            ).filter(tenure_days__lt=timedelta(days=365)).count()

            less_year_month = EmployeeHistory.objects.filter(
                dismissal_date__gte=month_start, 
                dismissal_date__lte=month_end,
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            ).exclude(
                employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            ).annotate(
                tenure_days = ExpressionWrapper(
                    F('dismissal_date') - F('hiring_date'),
                    output_field = fields.DurationField()
                )
            ).filter(tenure_days__lt=timedelta(days=365)).count()        

            less_year_year = EmployeeHistory.objects.filter(
                dismissal_date__gte=year_start, 
                dismissal_date__lte=year_end,
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            ).exclude(
                employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            ).annotate(
                tenure_days = ExpressionWrapper(
                    F('dismissal_date') - F('hiring_date'),
                    output_field = fields.DurationField()
                )
            ).filter(tenure_days__lt=timedelta(days=365)).count()

            total_today = sum(item['today_count'] for item in reasons_stats)
            total_month = sum(item['month_count'] for item in reasons_stats)
            total_year = sum(item['year_count'] for item in reasons_stats)   

            for item in reasons_stats:
                item['today_percent'] = round((item['today_count'] / total_today * 100), 1) if total_today > 0 else 0         
                item['month_percent'] = round((item['month_count'] / total_month * 100), 1) if total_month > 0 else 0
                item['year_percent'] = round((item['year_count'] / total_year * 100), 1) if total_year > 0 else 0

            less_year_stats = {
                'less_year_today':              less_year_today,
                'less_year_today_percent':      round((less_year_today / total_today * 100), 1) if total_today > 0 else 0,
                'less_year_month':              less_year_month,
                'less_year_month_percent':      round((less_year_month / total_month * 100), 1) if total_month > 0 else 0,
                'less_year_year':               less_year_year,
                'less_year_year_percent':       round((less_year_year / total_year * 100), 1) if total_year > 0 else 0,
            }
            type_string = 'Уволено'
        case 2:
            trainees_ve = Employee.objects.filter(
                dismissal_date__isnull=True, 
                employee_category__name='Ученики', 
                hire_date__gte=year_start
            ).exclude(
                    hire_source__name='практика ЦПП'
            ).count()
            trainees_tc = Employee.objects.filter(
                employee_category__name='Ученики', 
                dismissal_date__isnull=True, 
                hire_source__name='практика ЦПП', 
                hire_date__gte=year_start).count()
            trainees_total = trainees_ve + trainees_tc

            students_prev_year = Employee.objects.filter(
                # dismissal_date__isnull=True,
                hire_date__range=(date(details_date.year - 1, 1, 1), date(details_date.year - 1, 12, 31)),
                hire_order_num__icontains='кт',
                # hire_source__name__in=(
                #     'по окончании среднего спец.уч.заведения(без напр.)', 
                #     'по окончании института (без направления)', 
                #     'по окончании среднего спец.уч.заведения(с напр.)',
                #     'по окончании института (по направлению)',
                #     'по окончании ПТУ',
                # )
            ).count
            students_curr_year = Employee.objects.filter(
                # dismissal_date__isnull=True,
                hire_date__range=(date(details_date.year, 1, 1), date(details_date.year, 12, 31)),
                # hire_source__name__in=(
                #     'по окончании среднего спец.уч.заведения(без напр.)', 
                #     'по окончании института (без направления)', 
                #     'по окончании среднего спец.уч.заведения(с напр.)',
                #     'по окончании института (по направлению)', 
                #     'по окончании ПТУ',
                # )
                hire_order_num__icontains='кт',
            ).count
            from_tc = Employee.objects.filter(
                dismissal_date__isnull=True,
                hire_date__range=(date(details_date.year, 1, 1), date(details_date.year, 12, 31)),
                hire_source__name='практика ЦПП',
            ).count

            outstaffers_wap = Employee.objects.filter(
                dismissal_date__isnull=True,
                production__name='Вагоносборочное производство',
                employee_category__name='Аутстафферы'
            ).count
            outstaffers_map = Employee.objects.filter(
                dismissal_date__isnull=True,
                production__name='Механосборочное производство',
                employee_category__name='Аутстафферы'
            ).count
            outstaffers_mp = Employee.objects.filter(
                dismissal_date__isnull=True,
                production__name='Металлургическое производство',
                employee_category__name='Аутстафферы'
            ).count
            outstaffers_total = outstaffers_wap() + outstaffers_map() + outstaffers_mp()

            non_local_emps = Employee.objects.filter(
                dismissal_date__isnull=True,
                reg_address__isnull=True,
                employee_category__isnull=False,
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
            ).exclude(
                employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики')
            ).count

            male_count = Employee.objects.filter(
                gender='Мужской', 
                dismissal_date__isnull=True,
                employee_category__isnull=False,
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
            ).exclude(
                employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            ).count
            female_count = Employee.objects.filter(
                gender='Женский', 
                dismissal_date__isnull=True,
                employee_category__isnull=False,
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
            ).exclude(
                employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            ).count
            avg_age = Employee.objects.filter(
                dismissal_date__isnull=True,
                employee_category__isnull=False,
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
            ).exclude(
                employee_category__name__in=('Аутстафферы', 'Научно-производственное')
            ).annotate(
                age=Extract(Func(F('birth_date'), function='AGE'), 'year')
            ).aggregate(avg_age=Avg('age'))
            total_emps = male_count() + female_count()
            male_percent = round(male_count() / total_emps * 100, 1)
            female_percent = round(female_count() / total_emps * 100, 1)

            employees_stats = {
                'male_count':       male_count,
                'male_percent':     male_percent,
                'female_count':     female_count,
                'female_percent':   female_percent,
                'total_emps':       total_emps,
                'avg_age':          round(avg_age['avg_age'], 1),
            }

            headcount_stats = Employee.objects.filter(
                dismissal_date__isnull=True,
                employee_category__isnull=False,
            ).exclude(
                employee_category__name__in=('Аутстафферы', 'Научно-производственное'),
            ).values(
                'production__name',
            ).annotate(
                dl_count=Count('id', filter=Q(employee_category__name__in=('Основные', 'Ученики'), hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))),
                idl_count=Count('id', filter=Q(employee_category__name='Вспомогательные', hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))),
                mss_count=Count('id', filter=Q(employee_category__name='РСС', hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))),
                trainees_count=Count('id', filter=Q(employee_category__name='Ученики')
                    & (~Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
                    | Q(hire_category__isnull=True))),
                total_count=Count('id', filter=(
                    Q(employee_category__name__in=('Основные', 'РСС', 'Вспомогательные'),
                      hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
                    | Q(employee_category__name='Ученики')
                )),
            ).order_by('-total_count')

            total_dl = sum(item['dl_count'] for item in headcount_stats)
            total_idl = sum(item['idl_count'] for item in headcount_stats)
            total_mss = sum(item['mss_count'] for item in headcount_stats)
            total_trainees = sum(item['trainees_count'] for item in headcount_stats)
            total_all = sum(item['total_count'] for item in headcount_stats)

            headcount_summary = {
                'dl':           total_dl,
                'idl':          total_idl,
                'mss':          total_mss,
                'trainees':     total_trainees,
                'all':          total_all,
            }

            for item in headcount_stats:
                item['dl_percent'] = (round(item['dl_count'] / total_dl * 100, 1)) if total_dl > 0 else 0
                item['idl_percent'] = (round(item['idl_count'] / total_idl * 100, 1)) if total_idl > 0 else 0
                item['mss_percent'] = (round(item['mss_count'] / total_mss * 100, 1)) if total_mss > 0 else 0
                item['trainees_percent'] = (round(item['trainees_count'] / total_trainees * 100, 1)) if total_trainees > 0 else 0
                item['total_percent'] = (round(item['total_count'] / total_all * 100, 1)) if total_all > 0 else 0

            headcount_table = {
                'headcount_stats':      headcount_stats,
                'headcount_summary':    headcount_summary,    
            }

            # zov_count = Employee.objects.annotate(year=ExtractYear('hire_date')).filter(
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
            #     year__gte=2020,
            #     hire_source__name='СВО',
            # ).exclude(
            #     employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
            # ).values('year').annotate(
            #     count=Count('*'),
            # ).order_by('year')

            # zov_count_curr_month = Employee.objects.filter(
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
            #     hire_date__range=(month_start, month_end),
            #     hire_source__name='СВО',
            # ).exclude(
            #     employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
            # ).annotate(
            #     count=Count('*'),
            # ).count()

            # zov_total = sum(item['count'] for item in zov_count)
            zov_count = EmployeeHistory.objects.annotate(year=ExtractYear('hiring_date')).filter(
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
                year__gte=2020,
                hire_source__name='СВО',
            ).exclude(
                # employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
            ).values('year').annotate(
                count=Count('*'),
            ).order_by('year')

            zov_count_curr_month = EmployeeHistory.objects.filter(
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
                hiring_date__range=(month_start, month_end),
                hire_source__name='СВО',
            ).exclude(
                # employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
            ).annotate(
                count=Count('*'),
            ).count()

            zov_total = sum(item['count'] for item in zov_count)

            # pensioners_return = Employee.objects.annotate(year=ExtractYear('hire_date')).filter(
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
            #     year__gte=2026,
            #     hire_source__name='пенсионеры УВЗ',
            # ).exclude(
            #     employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
            # ).values('year').annotate(
            #     count=Count('*'),
            # ).order_by('year')

            # pensioners_left = Employee.objects.annotate(year=ExtractYear('dismissal_date')).filter(
            #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
            #     year__gte=2026,
            #     dismissal_reason__name='на пенсию по возрасту',
            # ).exclude(
            #     employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
            # ).values('year').annotate(
            #     count=Count('*'),
            # ).order_by('year')
            pensioners_return = EmployeeHistory.objects.annotate(year=ExtractYear('hiring_date')).filter(
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
                year__gte=2026,
                hire_source__name='пенсионеры УВЗ',
            ).exclude(
                # employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
            ).values('year').annotate(
                count=Count('*'),
            ).order_by('year')

            pensioners_left = EmployeeHistory.objects.annotate(year=ExtractYear('dismissal_date')).filter(
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
                year__gte=2026,
                dismissal_reason__name='на пенсию по возрасту',
            ).exclude(
                # employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики'),
            ).values('year').annotate(
                count=Count('*'),
            ).order_by('year')

            pensioners_percent = (
                round(pensioners_return[0]['count'] / pensioners_left[0]['count'] * 100, 1)
                if pensioners_return and pensioners_left else 0
            )

            army_left = EmployeeHistory.objects.annotate(year=ExtractYear('hiring_date')).filter(
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
                year__gte=2026,
                hire_source__name__in=('из Российской армии', 'возврат из Российской армии'),              
            ).values('year').annotate(
                count=Count('*'),
            ).order_by('year')

            army_return = EmployeeHistory.objects.annotate(year=ExtractYear('hiring_date')).filter(
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
                year__gte=2026,
                hire_source__name='возврат из Российской армии',                
            ).values('year').annotate(
                count=Count('*'),
            ).order_by('year')

            army_curr_month_left = EmployeeHistory.objects.filter(
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
                hiring_date__range=(month_start, month_end),
                hire_source__name__in=('из Российской армии', 'возврат из Российской армии'),
            ).annotate(
                count=Count('*'),
            ).count()

            army_curr_month_return = EmployeeHistory.objects.filter(
                hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),  
                hiring_date__range=(month_start, month_end),
                hire_source__name='возврат из Российской армии',
            ).annotate(
                count=Count('*'),
            ).count()

            army_zipped = zip(list(army_left), list(army_return))

            curr_year = details_date.year
            curr_month = MONTHS_RU[details_date.month - 1]

            stats = {
                'curr_year':              curr_year,
                'curr_month':             curr_month,
                'trainees_ve':            trainees_ve,
                'trainees_tc':            trainees_tc,
                'trainees_total':         trainees_total,
                'prev_year':              details_date.year - 1,
                'students_prev_year':     students_prev_year,
                'students_curr_year':     students_curr_year,
                'from_tc':                from_tc,
                'outstaffers_wap':        outstaffers_wap,
                'outstaffers_map':        outstaffers_map,
                'outstaffers_mp':         outstaffers_mp,
                'outstaffers_total':      outstaffers_total,
                'non_local_emps':         non_local_emps,
                'employees_stats':        employees_stats,
                'headcount_table':        headcount_table,
                'zov_count':              zov_count,
                'zov_total':              zov_total,
                'zov_count_curr_month':   zov_count_curr_month,
                'pensioners_return':      pensioners_return,
                'pensioners_left':        pensioners_left,
                'pensioners_percent':     pensioners_percent,
                'army':                   army_zipped,
                'army_curr_month_left':   army_curr_month_left,
                'army_curr_month_return': army_curr_month_return,
            }
            type_string = 'Работает'
        case 3:
            reasons_stats = Employee.objects.filter(
                employee_category__name='Ученики'
            ).exclude(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            ).annotate(
                reason_group=Case(
                    When(hire_source__isnull=True, then=Value('Источник не указан')),
                    When(hire_source__isnull=False, then=F('hire_source__name')),
                )
            ).values(
                'reason_group',
                'hire_source_id'
            ).annotate(
                today_count = Count('id', filter=Q(hire_date__range=(period_start, period_end))),
                month_count = Count('id', filter=Q(hire_date__range=(month_start, month_end))),
                year_count = Count('id', filter=Q(hire_date__range=(year_start, year_end))),
            ).order_by('-year_count')

            total_today = sum(item['today_count'] for item in reasons_stats)
            total_month = sum(item['month_count'] for item in reasons_stats)
            total_year = sum(item['year_count'] for item in reasons_stats)   

            for item in reasons_stats:
                item['today_percent'] = round((item['today_count'] / total_today * 100), 1) if total_today > 0 else 0         
                item['month_percent'] = round((item['month_count'] / total_month * 100), 1) if total_month > 0 else 0
                item['year_percent'] = round((item['year_count'] / total_year * 100), 1) if total_year > 0 else 0      
            type_string = 'Принято учеников'
        case 4:
            reasons_stats = Employee.objects.filter(
                employee_category__name='Ученики'
            ).exclude(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
            ).annotate(
                reason_group=Case(
                    When(dismissal_reason__isnull=True, then=Value('Причина не указана')),
                    When(dismissal_reason__isnull=False, then=F('dismissal_reason__name')),
                )
            ).values(
                'reason_group',
                'dismissal_reason_id'
            ).annotate(
                today_count = Count('id', filter=Q(dismissal_date__range=(period_start, period_end))),
                month_count = Count('id', filter=Q(dismissal_date__range=(month_start, month_end))),
                year_count = Count('id', filter=Q(dismissal_date__range=(year_start, year_end))),
            ).order_by('-year_count')

            less_year_today = Employee.objects.filter(dismissal_date__range=(period_start, period_end)).exclude(
                employee_category__name__in=('Ученики', 'Аутстафферы', 'Научно-производственное')
            ).annotate(
                tenure_days = ExpressionWrapper(
                    F('dismissal_date') - F('hire_date'),
                    output_field = fields.DurationField()
                )
            ).filter(tenure_days__lt=timedelta(days=365)).count()

            less_year_month = Employee.objects.filter(dismissal_date__range=(month_start, month_end)).exclude(
                employee_category__name__in=('Ученики', 'Аутстафферы', 'Научно-производственное')
            ).annotate(
                tenure_days = ExpressionWrapper(
                    F('dismissal_date') - F('hire_date'),
                    output_field = fields.DurationField()
                )
            ).filter(tenure_days__lt=timedelta(days=365)).count()        

            less_year_year = Employee.objects.filter(dismissal_date__range=(year_start, year_end)).exclude(
                employee_category__name__in=('Ученики', 'Аутстафферы', 'Научно-производственное')
            ).annotate(
                tenure_days = ExpressionWrapper(
                    F('dismissal_date') - F('hire_date'),
                    output_field = fields.DurationField()
                )
            ).filter(tenure_days__lt=timedelta(days=365)).count()

            total_today = sum(item['today_count'] for item in reasons_stats)
            total_month = sum(item['month_count'] for item in reasons_stats)
            total_year = sum(item['year_count'] for item in reasons_stats)   

            for item in reasons_stats:
                item['today_percent'] = round((item['today_count'] / total_today * 100), 1) if total_today > 0 else 0         
                item['month_percent'] = round((item['month_count'] / total_month * 100), 1) if total_month > 0 else 0
                item['year_percent'] = round((item['year_count'] / total_year * 100), 1) if total_year > 0 else 0      

            less_year_stats = {
                'less_year_today':              less_year_today,
                'less_year_today_percent':      round((less_year_today / total_today * 100), 1) if total_today > 0 else 0,
                'less_year_month':              less_year_month,
                'less_year_month_percent':      round((less_year_month / total_month * 100), 1) if total_month > 0 else 0,
                'less_year_year':               less_year_year,
                'less_year_year_percent':       round((less_year_year / total_year * 100), 1) if total_year > 0 else 0,
            }

            type_string = 'Уволено учеников'

    if details_type in (0, 1, 3, 4):
        return {
            'reasons_stats':    reasons_stats,
            'less_year_stats':  less_year_stats,
            'total_today':      total_today,
            'total_month':      total_month,
            'total_year':       total_year,
            'dtype_num':        details_type,
            'details_type':     type_string,
            'details_date':     details_date,
            'month_start':      month_start,
            'year_start':       year_start,
        }
    elif details_type == 2:
        return {
            'stats':            stats,
            'dtype_num':        details_type,
            'details_type':     type_string,
            'details_date':     details_date,
        }
    else:
        return {'details_type': 'undefined type'}

def get_dashboard_reason_details(reason_id=None, action='hire', period='day', employee_type='regular', details_date=None):
    '''
        reason_id: Источник/причина увольнения, если 0, то выводим итоговый отчёт;
        action: hire(Приняты) или dismissal(Уволены);
        period: day за прошлый день, month с начала месяца, year с начала года;
        employee_type: 
                        regular:    {Основные, Вспомогательные, РСС);
                        trainee:    Ученики;
                        probation:  Стаж до года;
        details_date: Дата выборки, если None, то сегодня - 1 день;
    '''
    
    valid_actions = ('hire', 'dismissal')
    valid_periods = ('day', 'month', 'year')
    valid_employee_types = ('regular', 'trainee', 'probation')

    if action not in valid_actions:
        raise ValueError(f'action должен быть одним из {valid_actions}')
    if period not in valid_periods:
        raise ValueError(f'period должен быть одним из {valid_periods}')
    if employee_type not in valid_employee_types:
        raise ValueError(f'employee_type должен быть одним из {valid_employee_types}')

    if details_date is None:
        details_date = date.today() - timedelta(days=1)
        match details_date.weekday():
            case 5: details_date -= timedelta(days=1)
            case 6: details_date -= timedelta(days=2)

    period_end = details_date
    period_start = details_date - timedelta(days=2) if details_date.weekday() == 0 else details_date

    if action == 'hire': action = 'hiring'
    if employee_type == 'trainee':
        emp_prefix = ''
        date_field_prefix = 'hire' if action == 'hiring' else 'dismissal'
    else:
        emp_prefix = 'employee__'
        date_field_prefix = action

    match period:
        case 'day':
            date_filter = {f'{date_field_prefix}_date__range': (period_start, period_end)}
        case 'month':
            filter_date_start = date(details_date.year, details_date.month, 1)
            filter_date_end = date(details_date.year, details_date.month, calendar.monthrange(details_date.year, details_date.month)[1])
            date_filter = {f'{date_field_prefix}_date__gte': filter_date_start, f'{date_field_prefix}_date__lte': filter_date_end}
        case 'year':
            filter_date_start = date(details_date.year, 1, 1)
            filter_date_end = date(details_date.year, 12, 31)
            date_filter = {f'{date_field_prefix}_date__gte': filter_date_start, f'{date_field_prefix}_date__lte': filter_date_end}

    if action in ('hire', 'hiring'):
        hire_date_field = 'hire_date' if employee_type == 'trainee' else 'hiring_date'
        filter_field = 'hire_source'
        filter_field_id = 'hire_source_id'
        model = HireSource
        action_verbose = 'Принято'
        extra_annotations = {}
    elif action == 'dismissal':
        filter_field = 'dismissal_reason'
        filter_field_id = 'dismissal_reason_id'
        model = DismissalReason
        action_verbose = 'Уволено'
        extra_annotations = {}      

    match employee_type:
        case 'trainee':
            employee_filter = Q(employee__employee_category__name='Ученики')
            type_verbose = 'учеников'
            exclude_categories = ()
        case 'regular':
            employee_filter = Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
            type_verbose = ''
            exclude_categories = ('Аутстафферы', 'Научно-производственное')   
        case 'probation':
            if action != 'dismissal':
                raise ValueError(f'Действие {action} имеет недопустимый тип сотрудника: {employee_type}')
            employee_filter = Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная'))
            exclude_categories = ('Аутстафферы', 'Научно-производственное')
            type_verbose = 'со стажем до года'
            extra_annotations['tenure_days'] = ExpressionWrapper(
                F('dismissal_date') - F('hiring_date'),
                output_field=fields.DurationField(),
            )

    if employee_type == "trainee":
        trainee_qs = Employee.objects.filter(
            employee_category__name="Ученики"
        ).exclude(
            hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
        )
        if reason_id:
            base_queryset = trainee_qs.filter(**date_filter, **{filter_field_id: reason_id})
            reason = model.objects.get(id=reason_id)
        else:
            base_queryset = trainee_qs.filter(**date_filter)
            reason = 'Итого'
    
    else:
        if reason_id:
            base_queryset = EmployeeHistory.objects.filter(
                **date_filter,
                **{filter_field_id:reason_id}
            ).filter(employee_filter)
            reason = model.objects.get(id=reason_id)
        else:
            base_queryset = EmployeeHistory.objects.filter(
                **date_filter,
            ).filter(employee_filter)
            reason = 'Итого'

    if exclude_categories:
        base_queryset = base_queryset.exclude(
            **{f'{emp_prefix}employee_category__name__in': exclude_categories}
        )       

    reason_details = base_queryset.annotate(
        row_number=Window(expression=RowNumber(), order_by=(f'{emp_prefix}workshop')),
        c_grade=Case(
            When(**{f'{emp_prefix}grade__isnull': True}, then=Value('-')),
            When(**{f'{emp_prefix}grade__isnull': False}, then=F(f'{emp_prefix}grade__name')),
        ),
        **extra_annotations
    ).order_by('row_number')    

    if employee_type == 'probation':
        reason_details = reason_details.filter(tenure_days__lt=timedelta(days=365))

    return {
        'reason_details':   reason_details,
        'action_type':           action,
        'details_type':     action_verbose,
        'details_date':     details_date,
        'reason':           reason,
    }

def get_daily_report(report_date=None):
    from django.contrib.postgres.aggregates import StringAgg, ArrayAgg

    def _month_passed_text(month_num):
        words = [
            'ноль',
            'один', 
            'два', 
            'три',
            'четыре',
            'пять',
            'шесть',
            'семь',
            'восемь',
            'девять',
            'десять',
            'одиннадцать',
        ]

        if month_num > 11:
            raise ValueError(f'month_num({month_num}) out of bounds ({len(words) - 1})')

        month_word = ''
        if month_num % 10 == 1 and month_num % 100 != 11:
            month_word = 'месяц'
        elif 2 <= month_num % 10 <= 4 and (month_num % 100 < 10 or month_num % 100 >= 20):
            month_word = 'месяца'
        else:
            month_word = 'месяцев'

        return f'{words[month_num]} {month_word}'

    if report_date is None:
        report_date = date.today() - timedelta(days=1) 

    match report_date.weekday():
        case 5: report_date -= timedelta(days=1)
        case 6: report_date -= timedelta(days=2)

    period_end = report_date
    period_start = report_date - timedelta(days=2) if report_date.weekday() == 0 else report_date

    month_passed = report_date.month - 1
    year = report_date.year

    hired_employees = Employee.objects.filter(
        hire_date__range=(period_start, period_end),
        hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
    ).exclude(
        employee_category__name__in=('Аутстафферы', 'Научно-производственное'),
    ).values(
        'production__name',
    ).annotate(
        total=Count('id'),
        mss_total=Count('id', filter=Q(employee_category__name='РСС')),
        dl_total=Count('id', filter=Q(employee_category__name__in=('Основные', 'Ученики'))),
        idl_total=Count('id', filter=Q(employee_category__name='Вспомогательные')),

        mss_deps=StringAgg('workshop__number', delimiter=', ', filter=Q(employee_category__name='РСС'), order_by='-workshop__number', distinct=False),
        dl_deps=StringAgg('workshop__number', delimiter=', ', filter=Q(employee_category__name__in=('Основные', 'Ученики')), order_by='-workshop__number', distinct=False),
        idl_deps=StringAgg('workshop__number', delimiter=', ', filter=Q(employee_category__name='Вспомогательные'), order_by='-workshop__number', distinct=False),
    )

    dismissed_employees = Employee.objects.filter(
        dismissal_date__isnull=False,
        dismissal_date__range=(period_start, period_end),
        hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
    ).exclude(
        employee_category__name__in=('Аутстафферы', 'Научно-производственное'),
    ).values(
        'production__name',
    ).annotate(
        total=Count('id'),
        mss_total=Count('id', filter=Q(employee_category__name='РСС')),
        dl_total=Count('id', filter=Q(employee_category__name__in=('Основные', 'Ученики'))),
        idl_total=Count('id', filter=Q(employee_category__name='Вспомогательные')),

        mss_deps=StringAgg('workshop__number', delimiter=', ', filter=Q(employee_category__name='РСС'), order_by='-workshop__number', distinct=False),
        dl_deps=StringAgg('workshop__number', delimiter=', ', filter=Q(employee_category__name__in=('Основные', 'Ученики')), order_by='-workshop__number', distinct=False),
        idl_deps=StringAgg('workshop__number', delimiter=', ', filter=Q(employee_category__name='Вспомогательные'), order_by='-workshop__number', distinct=False),
    )

    # Ученики считаются отдельно от общего запроса, т.к. он отфильтрован по hire_category='основная постоянная',
    # а обычные ученики этой категории приема, как правило, не имеют.
    # Основной вариант — ученики БЕЗ категории приема "основная постоянная".
    hired_trainees = Employee.objects.filter(
        hire_date__range=(period_start, period_end),
        employee_category__name='Ученики',
    ).exclude(
        hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
    ).values(
        'production__name',
    ).annotate(
        t_total=Count('id'),
        t_deps=StringAgg('workshop__number', delimiter=', ', order_by='-workshop__number', distinct=False),
    )
    dismissed_trainees = Employee.objects.filter(
        dismissal_date__isnull=False,
        dismissal_date__range=(period_start, period_end),
        employee_category__name='Ученики',
    ).exclude(
        hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
    ).values(
        'production__name',
    ).annotate(
        t_total=Count('id'),
        t_deps=StringAgg('workshop__number', delimiter=', ', order_by='-workshop__number', distinct=False),
    )

    hired_total = sum(item['total'] for item in hired_employees)
    hired_mss_total = sum(item['mss_total'] for item in hired_employees)
    hired_dl_total = sum(item['dl_total'] for item in hired_employees)
    hired_idl_total = sum(item['idl_total'] for item in hired_employees)
    hired_t_total = sum(item['t_total'] for item in hired_trainees)

    dismissed_total = sum(item['total'] for item in dismissed_employees)
    dismissed_mss_total = sum(item['mss_total'] for item in dismissed_employees)
    dismissed_dl_total = sum(item['dl_total'] for item in dismissed_employees)
    dismissed_idl_total = sum(item['idl_total'] for item in dismissed_employees)
    dismissed_t_total = sum(item['t_total'] for item in dismissed_trainees)

    # Переводы
    CATEGORIES = list(EmployeeCategory.objects.exclude(
            name__in=('Аутстафферы', 'Научно-производственное', 'Ученики')
    ).values_list(
        'name', 
        flat=True
    ).order_by('-name'))

    raw = defaultdict(lambda: defaultdict(lambda: {
        'arrived': 0, 
        'departed': 0, 
        'hired': 0, 
        'dismissed': 0
    }))

    meaningful_transfer = ~Q(
        from_workshop__production_id=F('to_workshop__production_id'),
        # from_category=F('to_category')
    )

    # Переводы - прибыло
    for row in (EmployeeTransfers.objects.filter(
            meaningful_transfer,
            transfer_date__year=year,
            to_workshop__production__isnull=False,
            employee__hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
    ).exclude(
        employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики')
    ).values(
        prod_name=F('to_workshop__production__name'),
        cat_name=F('to_category__name')
        # cat_name=F('employee__employee_category__name')
    ).annotate(
        count=Count('id')
    ).order_by('to_workshop__production__name')):
        raw[row['prod_name']][row['cat_name']]['arrived'] += row['count']

    # Переводы - убыло
    for row in (EmployeeTransfers.objects.filter(
            meaningful_transfer,
            transfer_date__year=year,
            from_workshop__production__isnull=False,
            employee__hire_category__name__in=('основная постояннаяШ', 'основная постоянная'),
    ).exclude(
        employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики')
    ).values(
        prod_name=F('from_workshop__production__name'),
        cat_name=F('from_category__name'),
        # cat_name=F('employee__employee_category__name')
    ).annotate(
        count=Count('id')
    ).order_by('to_workshop__production__name')):
        raw[row['prod_name']][row['cat_name']]['departed'] += row['count']

    # # Переводы - принятые
    # for row in (Employee.objects.filter(
    #     hire_date__year=year,
    #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
    # ).exclude(
    #     employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики')
    # ).values(
    #     prod_name=F('workshop__production__name'),
    #     cat_name=F('employee_category__name'),
    # ).annotate(
    #     count=Count('id'),
    # )):
    #     raw[row['prod_name']][row['cat_name']]['hired'] += row['count']

    # # Переводы - уволенные
    # for row in (Employee.objects.filter(
    #     dismissal_date__year=year,
    #     hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
    # ).exclude(
    #     employee_category__name__in=('Аутстафферы', 'Научно-производственное', 'Ученики')
    # ).values(
    #     prod_name=F('workshop__production__name'),
    #     cat_name=F('employee_category__name'),
    # ).annotate(
    #     count=Count('id'),
    # )):
    #     raw[row['prod_name']][row['cat_name']]['dismissed'] += row['count']

    # Переводы - принятые
    for row in (EmployeeHistory.objects.filter(
        hiring_date__year=year,
        employee__employee_category__isnull=False,
        hire_category__name__in=('основная постояннаяШ', 'основная постоянная')
    ).exclude(
        employee__employee_category__name__in=('Аутстафферы', 'Научно-производственное')
    ).values(
        prod_name=F('employee__production__name'),
        cat_name=Case(
            When(employee__employee_category__name='Ученики', then=Value('Основные')),
            default=F('employee__employee_category__name'),
        ),
    ).annotate(
        count=Count('id'),
    )):
        raw[row['prod_name']][row['cat_name']]['hired'] += row['count']

    # Переводы - уволенные
    for row in (EmployeeHistory.objects.filter(
        dismissal_date__year=year,
        employee__employee_category__isnull=False,
    ).filter(
        Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')) | Q(hire_category__isnull=True)
    ).exclude(
        Q(employee__employee_category__name='Аутстафферы')
        | Q(employee__employee_category__name='Научно-производственное')
        | (Q(employee__employee_category__name='Ученики') & ~Q(hire_category__name__in=('основная постояннаяШ', 'основная постоянная')))
    ).values(
        prod_name=F('employee__production__name'),
        cat_name=Case(
            When(employee__employee_category__name='Ученики', then=Value('Основные')),
            default=F('employee__employee_category__name'),
        ),
    ).annotate(
        count=Count('id'),
    )):
        raw[row['prod_name']][row['cat_name']]['dismissed'] += row['count']

    transfers_table = []
    category_totals = {cat: {'arrived': 0, 'departed': 0, 'hired': 0, 'dismissed': 0} for cat in CATEGORIES}
    grand_total = {
        'arrived':   0,
        'departed':  0,
        'hired':     0,
        'dismissed': 0,
        'balance':   0
    }

    for prod_name, cats in sorted(raw.items()):
        row = {'production': prod_name, 'categories': []}
        total = {
            'arrived': 0, 
            'departed': 0,
            'hired': 0,
            'dismissed': 0,
        }

        for cat in CATEGORIES:
            cell = cats.get(cat, {
                'arrived': 0, 
                'departed': 0, 
                'hired': 0, 
                'dismissed': 0
            })
            cell['balance'] = (cell['arrived'] + cell['hired']) - (cell['departed'] + cell['dismissed'])
            row['categories'].append(cell)
            for key in total:
                total[key] += cell[key]
                category_totals[cat][key] += cell[key]
        
        total['balance'] = (total['arrived'] + total['hired']) - (total['departed'] + total['dismissed'])
        row['categories'].append(total)
        
        transfers_table.append(row)

    for cat in CATEGORIES:
        ct = category_totals[cat]
        ct['balance'] = (ct['arrived'] + ct['hired']) - (ct['departed'] + ct['dismissed'])

    for cat in CATEGORIES:
        ct = category_totals[cat]
        for key in ('arrived', 'departed', 'hired', 'dismissed', 'balance'):
            grand_total[key] += ct[key]

    # Костыль       
    category_totals['РСС']['departed'] += grand_total['arrived'] - grand_total['departed']
    category_totals['РСС']['balance'] -= grand_total['arrived'] - grand_total['departed']
    grand_total['balance'] -= grand_total['arrived'] - grand_total['departed']
    grand_total['departed'] += grand_total['arrived'] - grand_total['departed']
    
    summary_row = {
        'production':       'Все производства',
        'categories':       [category_totals[cat] for cat in CATEGORIES] + [grand_total],
    }

    transfers_table.insert(0, summary_row)

    transfers = {
        'cats':            CATEGORIES,
        'table':           transfers_table,
        'grand_total':     grand_total,
    }

    total = {
        'hired_total':          hired_total,
        'hired_mss_total':      hired_mss_total,
        'hired_dl_total':       hired_dl_total,
        'hired_idl_total':      hired_idl_total,
        'hired_t_total':        hired_t_total,
        'dismissed_total':      dismissed_total,
        'dismissed_mss_total':  dismissed_mss_total,
        'dismissed_dl_total':   dismissed_dl_total,
        'dismissed_idl_total':  dismissed_idl_total,      
        'dismissed_t_total':    dismissed_t_total,            
    }

    return {
        'report_date':          report_date,
        'year':                 report_date.year,
        'month_passed':         _month_passed_text(month_passed),
        'total':                total,
        'hired_employees':      hired_employees,
        'dismissed_employees':  dismissed_employees,
        'hired_trainees':       hired_trainees,
        'dismissed_trainees':   dismissed_trainees,
        'transfers':            transfers,
        'mss_deps_h':           ', '.join(filter(None, hired_employees.values_list('mss_deps', flat=True))),
        'mss_deps_d':           ', '.join(filter(None, dismissed_employees.values_list('mss_deps', flat=True))),
    }

def get_table_report(table_date=None):
    if table_date is None:
        table_date = ReportTable.objects.aggregate(latest_date=Max('table_date'))['latest_date']

    # match table_date.weekday():
    #     case 5: table_date -= timedelta(days=1)
    #     case 6: table_date -= timedelta(days=2) 

    table = ReportTable.objects.filter(table_date=table_date).exclude(dep='').values().all()
    summary = ReportTable.objects.filter(table_date=table_date, dep='').values().all()
    return {
        'table':        table,
        'summary':      summary,
        'table_date':   table_date,
    }