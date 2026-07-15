with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2015-01-01' as date)",
        end_date="cast('2030-12-31' as date)"
    ) }}
)

select
    date_day::date as date_day,
    extract(year from date_day)::int as year,
    extract(month from date_day)::int as month,
    extract(day from date_day)::int as day_of_month,
    extract(dow from date_day)::int as day_of_week,  -- 0 = Sunday
    extract(quarter from date_day)::int as quarter,
    trim(to_char(date_day, 'Day')) as day_name,
    trim(to_char(date_day, 'Month')) as month_name,
    extract(dow from date_day) in (0, 6) as is_weekend
from spine
