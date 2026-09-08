# Мониторинг и обслуживание Ceph

Руководство по обеспечению наблюдаемости (observability) и выполнению регламентных работ в кластере Ceph. Документ является базовым (авторитетным) справочником для процессов мониторинга здоровья и обслуживания данных в версиях **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

## Определения

**Мониторинг Ceph** — непрерывный сбор и анализ телеметрии (метрики, логи, события) для контроля производительности, доступности данных и физического состояния оборудования.

**Обслуживание (Maintenance)** — набор проактивных действий по проверке консистентности (Scrubbing), балансировке нагрузки (Balancer) и обновлению компонентов без прерывания обслуживания клиентов.

**Наблюдаемость (Observability)** — расширенный подход к мониторингу, включающий трассировку операций и глубокий анализ состояния внутренних компонентов (например, SeaStar в Crimson OSD).

---

## Базовые концепции

### Архитектура мониторинга через MGR

Демон **MGR (Manager)** является центральным узлом сбора данных и единственным источником метрик, поскольку напрямую читает состояние всех карт кластера (osdmap, pgmap, monmap) и агрегирует статистику от демонов. Вся внешняя наблюдаемость выстраивается вокруг модулей MGR, поэтому сначала включается нужный модуль (`ceph mgr module enable <module>`), а затем внешние системы опрашивают его HTTP-endpoint.

**Конвейер метрик (end-to-end):**

```text
Ceph (MON/OSD/MGR/MDS/RGW)
        │  внутренняя anycast-сеть сообщений
        ▼
ceph-mgr (модуль prometheus, порт 9283, /metrics)
        │  HTTP scrape (pull)
        ▼
Prometheus / VictoriaMetrics  ──►  (recording + alerting rules)
        │                            │
        ▼                            ▼
   Grafana дашборды           Alertmanager ──► Telegram / Email / PagerDuty ...
```

В 2026 году ключевыми модулями являются:

*   **Prometheus Exporter:** Модуль `prometheus` (порт 9283). Предоставляет более 1500 метрик. В новых версиях включены расширенные метрики для **Crimson OSD** (загрузка ядер SeaStar, задержки реактора) и **NVMe-over-Fabrics**. Эндпоинт отдаёт метрики в формате Prometheus (text/0.0.4), поэтому подходит для любого Prometheus-совместимого стека (Prometheus, VictoriaMetrics).
    ```bash
    # Включение модуля и проверка его состояния
    ceph mgr module enable prometheus
    ceph mgr services   # → покажет адрес: https://<mgr_host>:9283/

    # Прямой запрос метрик (на хосте MGR)
    curl -s http://<mgr_host>:9283/metrics | head -20
    ```
*   **Dashboard:** Полнофункциональный веб-интерфейс. Включает встроенные Grafana-панели и управление оповещениями. Dashboard работает через тот же модуль и служит единой точкой входа для визуализации.
*   **Telemetry:** Отправка анонимных данных в Ceph Foundation. Позволяет использовать глобальные модели для модуля **diskprediction** и получать отчеты о безопасности.
*   **Influx:** Модуль для прямой отправки метрик в InfluxDB (альтернатива Prometheus для долгосрочного хранения).

**Почему MGR, а не каждая нода?** В отличие от демонов нижнего уровня, MGR не имеет кворума и не является точкой отказа: он работает в режиме active/standby, и при сбое активного экземпляра роль автоматически переходит к резервному. Это делает MGR надёжной и простой точкой опроса — Prometheus продолжает видеть метрики без реконфигурации.

**Выбор между внешним и подопечным Prometheus.** Оркестратор `cephadm` умеет разворачивать Prometheus и Grafana прямо внутри кластера (`ceph orch apply prometheus`, `ceph orch apply grafana`). Для продуктовых сред общая рекомендация — опрашивать Ceph из **внешнего** стека мониторинга (уже существующего в организации), а встроенную связку использовать только для небольших или изолированных кластеров. Внешний стек сохраняет историю дольше и консолидирует алерты с другими системами.

**Federation и несколько MGR-узлов.** Для кластеров с несколькими активными MGR (активный + резервные) метрики отдают только активный экземпляр. При горизонтальном масштабировании экспортера (например, несколько активных MGR в тестовом режиме) в Prometheus используется `honor_labels: true` и агрегация по метке `instance`, чтобы не задваивать чувствительные счётчики.

### Семантика ключевых метрик Prometheus-экспортера

Понимание смысла метрик критично для корректной интерпретации дашбордов и алертов (путаница между `up`-статусами и счётчиками — частая причина ложных срабатываний):

| Метрика (префикс) | Тип | Смысл |
| :--- | :--- | :--- |
| `ceph_cluster_...` | Gauge | Общее состояние кластера: `ceph_cluster_total_used_bytes`, `ceph_cluster_total_used_raw_bytes` — фактически занято и «сырой» объём до репликации. |
| `ceph_pool_...` | Gauge | Состояние пулов: `ceph_pool_used_bytes`, `ceph_pool_stored_raw`, `ceph_pool_percent_used`. |
| `ceph_osd_...` | Gauge | Метрики по OSD: `ceph_osd_up`, `ceph_osd_in`, `ceph_osd_utilization`, `ceph_osd_bytes`, статистика commit/apply latency. |
| `ceph_pg_...` | Gauge | Состояние Placement Groups: `ceph_pg_total`, `ceph_pg_active`, `ceph_pg_degraded`, `ceph_pg_undersized`. |
| `ceph_daemon_...` | Gauge | Метрики конкретных демонов, включая `ceph_daemon_perf_counters` для детальных счётчиков (loadavg, in/out ops). |
| `ceph_health_status` | Gauge | Числовой код здоровья: `0` = `HEALTH_OK`, `1` = `HEALTH_WARN`, `2` = `HEALTH_ERR`. Идеальна для мгновенного алерта на `!= 0`. |

> **Счётчики vs Gauge.** Например, `ceph_osd_commit_latency_ms` — Gauge (мгновенное значение задержки), а `ceph_osd_op_r` — суммарный счётчик операций чтения, который корректно анализировать через `rate()`. Не применяйте `sum()` к счётчикам без `rate`/`increase`, иначе получите бессмысленный накопленный рост.

### Наблюдаемость по компонентам (MON, MGR, MDS, RGW)

Помимо общих метрик кластера, каждый тип демона требует отдельного внимания:

*   **MON (Мониторы):** Критичны кворум и синхронизация времени. Расхождение часов (`CLOCK_SKEW`) ломает Paxos-консенсус и приводит к деградации всего кластера. Контроль: `ceph mon stat` (список и `monmap`), `ceph health detail` (секция `CLOCK_SKEW`), сверка с локальным временем и `chronyc tracking` на самих хостах.
*   **MGR (Менеджеры):** Проверка active/standby пары `ceph mgr stat`. Мониторинг модулей `ceph mgr module ls` — отключённый модуль `prometheus` «молча» оставит без метрик весь стек.
*   **MDS (Metadata Server):** Для CephFS критичны активность рангов и задержки метаданных: `ceph fs status`, `ceph mds stat`, метрики `ceph_daemon_perf_counters` по `mds`. Медленный MDS проявляется как «висящие» операции ввода-вывода файловой системы.
*   **RGW / NFS / SMB (шлюзы):** Мониторинг сетевых endpoint-ов: количество активных соединений, задержки ответа, состояние Ingress (HAProxy). Метрика `haproxy_frontend_current_sessions` и счётчики HTTP-ошибок 4xx/5xx.

### Механизмы проверки целостности (Scrubbing)

Scrubbing защищает от "тихой" порчи данных (bit rot) и несоответствия реплик:

1.  **Light Scrub (ежедневно):** Проверка метаданных объектов (размер, атрибуты).
2.  **Deep Scrub (еженедельно):** Полное чтение данных и сравнение контрольных сумм. В v20+ оптимизирован для минимизации влияния на клиентский ввод-вывод за счет динамических приоритетов (mclock scheduler).

### Уровни оповещений (Alerting Levels)

| Уровень | Состояние здоровья | Критерии |
| :--- | :--- | :--- |
| **Info** | `HEALTH_OK` | Идет балансировка, плановое обновление. |
| **Warning** | `HEALTH_WARN` | Nearfull OSD (85%), `OSD_DOWN`, рассинхронизация времени (`CLOCK_SKEW`). |
| **Critical** | `HEALTH_ERR` | Full OSD (95%), потеря кворума MON, `PG_INCOMPLETE` (данные недоступны). |

---

## Практические сценарии

### 1. Мониторинг Crimson OSD и NVMe

Crimson OSD использует lockless-архитектуру на базе SeaStar, что требует специфического мониторинга:

```bash
# Проверка производительности реакторов Crimson
ceph daemon osd.<id> perf dump | grep seastar

# Мониторинг специфических метрик NVMe-oF
ceph orch ps --service_name rbd-mirror
```

**White Spot:** Для Crimson OSD критично отслеживать `seastar_reactor_utilization`. Если значение стабильно выше 90%, требуется горизонтальное масштабирование (добавление узлов) или перераспределение PG.

### 2. Подключение внешнего Prometheus и алертинг

Сценарий для SRE: подключить Ceph к существующему внешнему стеку мониторинга и получать алерты о деградации.

**Шаг 1. Включить экспортер и узнать адрес эндпоинта:**
```bash
ceph mgr module enable prometheus
ceph mgr services    # → {"prometheus": "http://<mgr_host>:9283"}
```
Для резервирования адрес экспортера в DNS/ansible должен указывать на *активный* MGR либо использовать виртуальный IP.

**Шаг 2. Конфигурация scrape-таргета (prometheus.yml):**
```yaml
scrape_configs:
  - job_name: 'ceph'
    # Метрик много и они крупные — скрейпить редко, но полно
    scrape_interval: 15s
    static_configs:
      - targets: ['<mgr_host>:9283']
        labels:
          cluster: 'ceph-prod'
    # Не подмешивать внутренние метки Prometheus в метрики Ceph
    honor_labels: true
```

**Шаг 3. Базовые алертинг-правила (правила для Alertmanager):**
```yaml
groups:
  - name: ceph-cluster
    rules:
      # Здоровье кластера — мгновенный сигнал о любой деградации
      - alert: CephClusterHealthError
        expr: ceph_health_status == 2
        for: 2m
        labels: { severity: critical, service: ceph }
        annotations:
          summary: "Ceph: HEALTH_ERR — требуются действия"
          description: "Кластер {{ $labels.cluster }} в состоянии HEALTH_ERR."
      - alert: CephClusterHealthWarn
        expr: ceph_health_status == 1
        for: 10m
        labels: { severity: warning, service: ceph }
        annotations:
          summary: "Ceph: HEALTH_WARN"
      # Отсутствие метрик = проблемы с экспортером или MGR
      - alert: CephExporterDown
        expr: up{job="ceph"} == 0
        for: 5m
        labels: { severity: critical, service: ceph }
      # OSD в состоянии down
      - alert: CephOSDDown
        expr: sum(ceph_osd_up) < count(ceph_osd_up)
        for: 5m
        labels: { severity: critical, service: ceph }
      # Деградированные или недостаточно скопированные PG
      - alert: CephPGNotActive
        expr: sum(ceph_pg_active) < sum(ceph_pg_total)
        for: 10m
        labels: { severity: warning, service: ceph }
```

**Валидация:** после применения правил в Prometheus вкладка `Rules` показывает статус правила, а в Alertmanager появляются уведомления. Проверка доставки: `curl http://<alertmanager>:9093/api/v2/alerts`.

> Список и семантика метрик — в разделе выше; базовое конфигурирование Prometheus/Alertmanager/Grafana — в соответствующих доменах базы знаний ([Prometheus](../../../../Prometheus/overview.md), [Grafana Alerting](../../../../Grafana/alerting/concepts.md)).

### 3. Управление емкостью и предсказание отказов

Ceph использует модуль `diskprediction` для превентивной замены дисков.

```bash
# Проверка текущих порогов заполнения
ceph osd dump | grep -i ratio

# Прогноз времени жизни диска (на основе локальной модели)
ceph device predict-life-expectancy <osd-id>

# Статус телеметрии
ceph telemetry status
```

**Рекомендация:** Используйте облачную модель телеметрии (`ceph telemetry enable_all`) для получения наиболее точных прогнозов на основе данных от тысяч кластеров.

**Пороги заполнения и capacity planning.** Помимо диагностики, администратор обязан заранее настроить пороги, чтобы успеть отреагировать до блокировки записи. По умолчанию: `mon_osd_nearfull_ratio` = 0.85, `mon_osd_full_ratio` = 0.95, `mon_osd_backfillfull_ratio` = 0.9. Рекомендуется занижать `nearfull` в высоконагруженных кластерах, чтобы начать расширение раньше.

```bash
# Просмотр текущих значений
ceph config get mon mon_osd_nearfull_ratio
ceph config get mon mon_osd_full_ratio

# Установка более раннего порога предупреждения (для планирования ёмкости)
ceph config set mon mon_osd_nearfull_ratio 0.80
```

> **Важно:** Толчком к масштабированию должен служить порог `nearfull`, а не `full`. Достижение `full_ratio` останавливает запись во всём кластере и является аварией — её обработка описана в [Операциях](./operations.md#8-аварийные-операции-emergency).

### 4. Оптимизация Scrubbing в нагруженных кластерах

В современных версиях рекомендуется использовать адаптивное расписание:

```bash
# Ограничение Scrubbing во время пиковых нагрузок (через конфигурацию OSD)
ceph config set global osd_scrub_priority 1
ceph config set global osd_scrub_sleep 0.1 # Пауза между операциями чтения

# Настройка расписания (только в ночное время)
ceph config set global osd_scrub_begin_hour 23
ceph config set global osd_scrub_end_hour 6
```

**Валидация запущенного Scrub:** убедиться, что scrub реально выполняется и завершается без зависаний:
```bash
# Статус PG, включая активные scrub-операции
ceph pg stat

# Детальный статус scrub по конкретной PG
ceph pg <pg_id> query | grep -E 'scrub|last_scrub'
```

**Типичная проблема — «зависший» scrub.** Если PG надолго застревает в состоянии `scrubbing`, проверьте активность и при необходимости прервите операцию:
```bash
ceph pg scrub cancel <pg_id>
```

### 5. Мониторинг объектов, OSD и реального времени

**Непрерывный просмотр событий (аналог `tail -f` по статусу):**
```bash
# Поток событий здоровья и изменений карт в реальном времени
ceph -w

# Снапшот текущего состояния (однократно)
ceph status
```

**Состояние OSD и их «пригодность»:**
```bash
# Обобщённый статус OSD (кол-во up/down, in/out, использование)
ceph osd status

# Физические диски и их SMART-состояние
ceph device ls

# Задержки записи/чтения: commit (в WAL) и apply (на диск) — по каждому OSD
ceph osd perf
```
> **Интерпретация `ceph osd perf`:** колонка `commit` — время записи в журнал (WAL/BlueStore), `apply` — время применения на диск, суммарно составляют задержку записи. Стабильно высокое `commit` > 50–100 мс обычно указывает на деградацию дисковой подсистемы или переполнение очереди. Подробный разбор задержек — в [Обзоре Ceph](../ceph_overview.md).

### 6. Наблюдаемость сетевых шлюзов (RGW, NFS, SMB)

С появлением модуля `ingress` (HAProxy + Keepalived) мониторинг точек входа стал централизованным:

```bash
# Проверка статуса Ingress-шлюзов
ceph orch ps --service_type ingress

# Просмотр статистики HAProxy через Dashboard или Prometheus
# Метрика: haproxy_frontend_current_sessions
```

**Мониторинг изнутри:** помимо HAProxy, проверяйте сами демоны шлюзов через их счетчики производительности:
```bash
# Счётчики производительности RGW (пропускная способность, ошибки)
ceph daemon <rgw_name> perf dump | head

# Живые сессии MDS (CephFS) — количество клиентов и их caps
ceph tell mds.0 session ls | head
```

### 7. Диагностика Slow Ops и задержек

«Медленные операции» (Slow Ops) — операции ввода-вывода, выполняющиеся дольше ~30 секунд. Их появление — первый признак серьёзной деградации.

```bash
# Где живёт "хвост" задержки: активные и зависшие операции на OSD
ceph daemon osd.<id> dump_ops_in_flight

# Какие PG отстают / в каком состоянии
ceph pg dump_stale

# Непосредственно соотношение задержек commit/apply
ceph osd perf
```

**Алгоритм поиска проблемного OSD:**
1.  `ceph health detail` — найти сообщения о slow ops и указанные OSD.
2.  `ceph daemon osd.<id> dump_ops_in_flight` — посмотреть, какие именно операции зависли (чтение/запись, целевой пул).
3.  Сопоставить с метриками диска (`iostat -x 1` на хосте OSD): высокий `%util`/`await` подтверждает диск/контроллер как причину.
4.  Проверить перестроение данных (recovery/backfill), которое само по себе может вызывать Slow Ops во время нагрузки.

**Типичный вывод `HEALTH_WARN` при Slow Ops:**
```text
SLOW_OPS: 12 slow ops, oldest one blocked for 35 sec, daemons [osd.3, osd.7]
```

### 8. Наблюдение за мониторами и синхронизацией времени

Отказоустойчивость кластера начинается с кворума MON и корректного времени. Рассинхронизация часов — одна из самых частых причин непонятных сбоев.

```bash
# Кворум и список мониторов
ceph mon stat

# Наличие всех мониторов в кворуме (поиск MON_DOWN)
ceph quorum_status

# Диагностика CLOCK_SKEW — в детальной проверке здоровья
ceph health detail | grep -i clock
```

**Рекомендация:** на всех узлах кластера (особенно MON) должен работать единый источник точного времени — `chrony`/`ntp`, синхронизирующийся с одним и тем же внешним пулом. Расхождение даже в сотни миллисекунд между MON ухудшает работу Paxos. Проверка на хосте: `chronyc tracking` → значение флага `Leap status` и `Clock offset`.

### 9. Анализ логов и глубокая отладка

В кластерах `cephadm` логи агрегируются оркестратором:

```bash
# Логи всех событий безопасности и аудита
ceph log last 100 audit

# Отслеживание операций оркестратора в реальном времени
ceph orch log watch

# Глубокая отладка конкретного компонента (включение debug-режима)
ceph config set osd.<id> debug_osd 20/20
# → Внимание: создает огромную нагрузку на диск, отключайте сразу после сбора данных!

# Обязательный "откат" debug-режима после завершения диагностики
ceph config set osd.<id> debug_osd 0/5
```

**Cleanup (возврат к норме):** после любой отладочной сессии верните настройки к рабочим значениям и проверьте, что лог не продолжает расти:
```bash
# Сброс debug-уровня к значению по умолчанию
ceph config set osd.<id> debug_osd 0/5

# Контроль, что демон снова работает в обычном режиме
ceph health detail
```

## Troubleshooting (типичные проблемы и решения)

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `health: HEALTH_ERR` + «жёсткий» `OSD_FULL` | Превышен `full_ratio` (95%), запись заблокирована | `ceph health detail`, `ceph osd df tree` | Освободить место или временно поднять порог (см. [Операции](./operations.md#8-аварийные-операции-emergency)) |
| `HEALTH_WARN: CLOCK_SKEW` | Расхождение времени между узлами | `ceph health detail \| grep -i clock`, `chronyc tracking` | Настроить единый `chrony`/`ntp`, перезапустить `chronyd` |
| `HEALTH_WARN: SLOW_OPS` | Деградация диска/контроллера, recovery | `ceph osd perf`, `ceph daemon osd.N dump_ops_in_flight`, `iostat -x` | Заменить проблемный диск, дождаться конца recovery |
| `HEALTH_WARN: PG_DEGRADED` дольше ожидаемого | Недостаточно live-OSD для нужного числа копий | `ceph pg stat`, `ceph osd tree` | Вернуть OSD в `in`, дождаться backfill |
| Метрики не появляются в Prometheus | Модуль `prometheus` выключен / активен другой MGR | `ceph mgr module ls`, `ceph mgr services` | Включить модуль, проверить адрес экспортера |
| Dashboard/Grafana пустой или ошибаются | Не настроен источник данных | `ceph mgr services` | Подключить Prometheus как data source, выбрать правильный интервал |

## Лучшие практики (Best Practices)

*   **Алертить на `ceph_health_status != 0`, а не на отдельные метрики.** Это единственный надёжный способ не пропустить неизвестные ранее классы проблем; детали — уже через `ceph health detail` и алертинг-правила.
*   **Настраивать порог `nearfull` раньше, чем `full`.** Расширение должно начинаться на `nearfull`, а не в момент блокировки записи.
*   **Включить `telemetry` (даже локальную модель)** — модуль `diskprediction` помогает заменить диск заранее, до фактического отказа.
*   **Хранить записи `ceph -w`/`ceph status` в историческом хранилище** (Prometheus + Grafana), а не только разовые выводы в консоль — без истории нельзя увидеть тренды и «собачьи лапы» (положительные/отрицательные дрейфы).
*   **Выполнять плановое обслуживание под флагами `noscrub`/`nodeep-scrub`** (см. [Операции](./operations.md)) и снимать их сразу после работ.
*   **Проверять время на всех узлах при непонятных сбоях** — `CLOCK_SKEW` маскируется под случайные проблемы кворума.

---

## Регламентное обслуживание

| Периодичность | Задача | Метод |
| :--- | :--- | :--- |
| **Real-time** | Мониторинг здоровья и алертов | Prometheus / Alertmanager |
| **Ежедневно** | Анализ Slow Ops и Latency | `ceph osd perf` / Dashboard |
| **Ежедневно** | Проверка заполнения и прироста ёмкости | `ceph df`, `ceph osd df tree` |
| **Еженедельно** | Контроль Deep Scrub и состояния NVMe | `ceph device ls`, `ceph pg stat` |
| **Ежемесячно** | Аудит прав доступа и ротация ключей | `ceph auth list` |
| **Ежеквартально** | Ревью алертинг-правил и порогов ёмкости | График `ceph_pool_percent_used`, `ceph osd dump` |
| **Раз в полгода** | Обновление версии кластера (LTS) | `ceph orch upgrade start --ceph_version <version>` |

---

## Дополнительная информация

### Связанные темы

- [Администрирование Ceph — Обзор](./index.md) — навигация и архитектура.
- [Операции Ceph](./operations.md) — управление OSD и пулами.
- [Расчет PG](../ceph_placement_groups.md) — влияние количества PG на скорость восстановления.

### Смежные инструменты наблюдаемости

- [Prometheus](../../../../Prometheus/overview.md) — сбор, хранение и PromQL-анализ метрик.
- [Grafana Alerting](../../../../Grafana/alerting/concepts.md) — конвейер оповещений и интеграции.

### Ссылки и ресурсы

- [Ceph Prometheus Module Guide](https://docs.ceph.com/en/latest/mgr/prometheus/)
- [SeaStar Metrics Documentation](https://seastar.io/monitoring-seastar/) — для отладки Crimson OSD.
- [Ceph Telemetry Privacy Policy](https://telemetry.ceph.com/privacy.html)
