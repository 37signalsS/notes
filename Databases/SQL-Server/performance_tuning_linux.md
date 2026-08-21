# SQL Server: Тюнинг производительности в Linux-контейнерах

## Определения

**mssql-conf** — основной инструмент настройки параметров SQL Server в Linux. Принимает изменения через переменные окружения или файл `/var/opt/mssql/mssql.conf`.

**cgroup v2** — механизм ядра Linux для ограничения и учета ресурсов. SQL Server 2025 полностью совместим с cgroup v2, что критично для корректной работы в Kubernetes.

---

## Оптимизация ресурсов в контейнерах (SRE Guide)

### 1. Управление памятью
SQL Server по умолчанию резервирует **80%** от доступной контейнеру памяти (Limit) под свой Buffer Pool.

**Рекомендация:** Если контейнер выделен исключительно под БД, увеличьте лимит до 90%, чтобы минимизировать риск OOM Killer на уровне ядра при пиковых нагрузках на PAL.

```bash
# Настройка через mssql-conf (требует перезапуска)
/opt/mssql/bin/mssql-conf set memory.memorylimitmb 36864 # Пример для 40ГБ лимита
```

### 2. CPU и Планировщик (Scheduler)
В высокоплотных средах (K8s) конкуренция за CPU может вызвать значительные задержки (Context Switching).

*   **Trace Flag 8002:** Включает динамическое распределение нагрузки планировщика SQL Server по всем доступным ядрам cgroup quota. Обязательно к включению в Kubernetes.
*   **Soft Affinity:** Используйте `process.softaffinitymask` для привязки процесса к конкретным NUMA-узлам или ядрам, если это поддерживается инфраструктурой.

### 3. Настройки операционной системы (Host-level)
Даже если SQL Server запущен в контейнере, некоторые настройки хоста напрямую влияют на PAL:

1.  **Transparent Huge Pages (THP):** В 2026 году Microsoft рекомендует оставлять THP в режиме `always` для современных ядер (RHEL 9/10, Ubuntu 24.04).
2.  **Madvise:** Если наблюдается высокий `sys` CPU, переключите THP в режим `madvise` и настройте SQL Server на использование огромных страниц.
3.  **Core Dumps:** Настройте `/proc/sys/kernel/core_pattern` на хосте, чтобы дампы падений PAL сохранялись вне контейнера для последующего анализа.

---

## Диагностика Linux-специфики (DMV)

В SQL Server 2025 появились новые системные представления для анализа хост-системы изнутри контейнера:

```sql
-- 1. Статистика ресурсов хоста (память, давление)
SELECT * FROM sys.dm_os_host_memory_resource_stats;

-- 2. Статистика процессов Linux (аналог 'top')
SELECT * FROM sys.dm_os_linux_process_stats;

-- 3. Проверка используемого планировщика и лимитов CPU
SELECT * FROM sys.dm_os_schedulers WHERE status = 'VISIBLE ONLINE';
```

---

## Практическая конфигурация Docker/K8s

**Рекомендуемый манифест (фрагмент):**
```yaml
resources:
  limits:
    cpu: "8"
    memory: "16Gi"
env:
  - name: MSSQL_MEMORY_LIMIT_MB
    value: "14745" # ~90% от лимита
  - name: MSSQL_TRACE_FLAGS
    value: "8002"
```

---

## Дополнительная информация

### См. также
- **[Обзор SQL Server](./overview.md)** — архитектурные основы.
- **[Отказоустойчивость: Always On AG](./high_availability.md)** — кластеризация в Linux.
- **[Официальный гайд по тюнингу Linux](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-performance-best-practices)**
