# Мониторинг миграций баз данных

## Определения

**Мониторинг миграций** — это процесс непрерывного наблюдения за выполнением изменений в схеме и данных базы данных с целью раннего обнаружения сбоев, оценки влияния на производительность системы и подтверждения успешного завершения операций.

## Основные концепции

Эффективный мониторинг миграций строится на методологии **RED** (Rate, Errors, Duration):

- **Успешность (Rate/Success):** количество успешно примененных файлов миграций.
- **Ошибки (Errors):** типы и количество исключений, возникших в процессе выполнения (блокировки, нарушение ограничений, ошибки синтаксиса).
- **Длительность (Duration):** время выполнения каждой миграции, что критично для оценки риска блокировок в production-среде.

## Практические сценарии

### Сценарий 1: Сбор метрик выполнения (Python + StatsD)

Пример интеграции сбора метрик непосредственно в код исполнителя миграций.

```python
from datadog import statsd
import time

def run_migration(migration_file):
    start_time = time.time()
    
    try:
        # Основная логика применения миграции
        execute_migration(migration_file)
        
        # Метрика успеха
        statsd.increment('db.migration.success', 
                        tags=[f'file:{migration_file}'])
        
        # Гистограмма длительности выполнения
        statsd.histogram('db.migration.duration',
                        time.time() - start_time,
                        tags=[f'file:{migration_file}'])
        
    except Exception as e:
        # Метрика ошибки с указанием типа исключения
        statsd.increment('db.migration.failure',
                        tags=[f'file:{migration_file}', f'error:{type(e).__name__}'])
        raise
```

### Сценарий 2: Правила оповещения (Prometheus Alerts)

Настройка алертов для обнаружения зависших или упавших миграций.

```yaml
# Alerting rules
groups:
- name: DatabaseMigrations
  rules:
  - alert: LongRunningMigration
    expr: db_migration_duration_seconds > 300
    for: 1m
    labels:
      severity: warning
    annotations:
      summary: "Миграция {{ $labels.file }} выполняется слишком долго"
      description: "Выполнение миграции превысило 5 минут. Возможна блокировка таблиц."

  - alert: FailedMigration
    expr: increase(db_migration_failure_total[5m]) > 0
    labels:
      severity: critical
    annotations:
      summary: "Ошибка миграции базы данных"
      description: "Миграция {{ $labels.file }} завершилась с ошибкой: {{ $labels.error }}."
```

## Дополнительная информация

### Рекомендации по мониторингу

- **Логирование:** всегда дополняйте метрики подробными логами (stdout/stderr) с указанием конкретных SQL-запросов, вызвавших ошибку.
- **Инструментарий:** используйте нативные возможности инструментов миграций (Flyway `info`, Liquibase `history`) для сопоставления метрик с реальным состоянием БД.
- **Блокировки:** настройте мониторинг активных сессий и блокировок в БД (например, `pg_stat_activity` в PostgreSQL) во время выполнения миграций.

### Смежные темы

- **[Миграции баз данных: Основы](migration_basics.md)** — базовые понятия и инструменты.
- **[Лучшие практики](migration_practices.md)** — идемпотентность и транзакционность.
- **[Стратегии отката (Rollback)](rollback_strategies.md)** — действия при срабатывании алертов об ошибках.
