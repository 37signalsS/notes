# Самомониторинг стека VictoriaMetrics

**Актуально для:** VictoriaMetrics v1.154.x (Community)

## Определения

**Мета-мониторинг (self-monitoring)** — мониторинг самого стека мониторинга: компонентов VictoriaMetrics (vmsingle/vmcluster, vmagent, vmalert, vmauth), их метрик `/health` и `/metrics`, и доставки уведомлений. Общая концепция и сценарии для всего стека наблюдаемости — в [Мета-мониторинге](../Concepts/Observability_and_Monitoring/meta-monitoring.md).

**Self-scrape** — сбор компонентом собственных метрик (`/metrics`) своим же скрейпером или встроенным флагом.

**Watchdog (Dead Man's Switch)** — метрика, которая должна записываться с постоянной периодичностью; алерт по её отсутствию срабатывает, когда «замирает» весь конвейер, включая хранилище и alerting.

## Базовые концепции

### Что и на каком уровне мониторим

| Уровень | Что проверяем | Чем |
| :--- | :--- | :--- |
| **Компоненты** | живы ли vmsingle/vmstorage/vminsert/vmselect/vmagent/vmalert/vmauth | `/health`, `/metrics`, готовые пакеты алертов |
| **Доставка данных** | доходят ли сэмплы до хранилища | метрики vmagent remote write |
| **Доставка уведомлений** | доходят ли алерты до получателей | метрики vmalert/Alertmanager, watchdog снаружи |
| **Ресурсы** | диск, read-only, части, merge | `vm_free_disk_space_bytes`, `vm_parts`, `vm_merges_*` |

Ключевой принцип: **мета-мониторинг не должен целиком зависеть от того, что мониторит.** Минимум — внешний watchdog и возможность прочитать `/metrics` компонентов напрямую, минуя сам основной пайплайн.

## Практические сценарии

### 1. Самоскрейп компонентов

**Single-node.** Включите встроенный скрейпер:

```yaml
# /etc/victoriametrics/victoriametrics.yml (параметры запуска)
selfScrapeInterval: "15s"
```

Без него метрики самого vmsingle (очередь приёма, кэши, состояние скрейпера) недоступны — типичная лакуна standalone-деплоя. Подробнее: [vmsingle: самоскрейп](./vmsingle_single_node.md).

**Kubernetes (k8s-stack).** Чарт поставляет ServiceScrape для компонентов и правил ([helm k8s-stack](./helm_victoria_metrics_k8s_stack.md)); VictoriaMetrics Operator автоматически добавляет Service + VMServiceScrape для VMAgent — скрейп агента включается сам при его создании.

**Ручной кластерный деплой.** Добавьте scrape-джобы для компонентов в конфиг скрейпера (vmagent/Prometheus): [Базовая конфигурация скрейпинга](./vmagent_overview.md#1-базовая-конфигурация-скрейпинга). Порты по умолчанию: `vminsert` 8480, `vmselect` 8481, `vmstorage` 8482, vmagent 8429, vmalert 8880.

### 2. Официальные пакеты алертов

Пакеты правил лежат в репозитории VictoriaMetrics, каталог [`deployment/docker/rules`](https://github.com/VictoriaMetrics/VictoriaMetrics/tree/master/deployment/docker/rules):

| Файл | Покрывает |
| :--- | :--- |
| `alerts-health.yml` | общее здоровье (например, `ServiceDown`) |
| `alerts-single-node.yml` | vmsingle |
| `alerts-cluster.yml` | кластерные vminsert/vmselect/vmstorage |
| `alerts-vmagent.yml` | vmagent (доставка данных) |
| `alerts-vmalert.yml` | vmalert (ошибки правил, remote write) |
| `alerts-vmauth.yml` | vmauth |
| `alerts-vmanomaly.yml` | vmanomaly (Enterprise) |
| `alerts-vmbackupmanager.yml` | vmbackupmanager |
| `tests/` | тестовые данные для проверки пакетов |

Смежные пакеты в других репозиториях: `alerts-vtraces.yml` и `alerts-health.yml` в [VictoriaTraces](https://github.com/VictoriaMetrics/VictoriaTraces/tree/master/deployment/docker/rules), `alerts-cardinality.yml` в [vmestimator](https://github.com/VictoriaMetrics/vmestimator/tree/master/deployment/docker/rules) — детекция взрыва кардинальности.

Загрузка:

```bash
mkdir -p /etc/vmalert/rules
for f in alerts-health.yml alerts-cluster.yml; do
  curl -sL "https://raw.githubusercontent.com/VictoriaMetrics/VictoriaMetrics/master/deployment/docker/rules/$f" \
    -o "/etc/vmalert/rules/$f"
done
ls /etc/vmalert/rules/
# → alerts-cluster.yml  alerts-health.yml
```

Дальше файлы подключаются флагом `-rule=/etc/vmalert/rules/*.yml` у vmalert либо манифестами VMRule/ConfigMap в Kubernetes — [Управление правилами](./vmalert_rules_management_with_manifests.md). Проверка после подключения:

```bash
curl -s http://vmalert:8880/api/v1/rules | jq -r '.status'
# → success

curl -s http://vmalert:8880/metrics | grep '^vmalert_alerting_rules_errors_total'
# → vmalert_alerting_rules_errors_total 0
```

### 3. Ключевые метрики по компонентам

| Компонент | Метрика | Сигнал |
| :--- | :--- | :--- |
| **vmagent** | `vmagent_remotewrite_errors_total` | ошибки HTTP-доставки в хранилище |
| **vmagent** | `vmagent_remotewrite_queue_blocked` | очередь заблокирована (backpressure) |
| **vmagent** | `vmagent_remotewrite_samples_dropped_total` | прямая потеря данных |
| **vmagent** | `vmagent_remotewrite_pending_data_bytes` | объём буфера на диске |
| **vminsert** | `vm_rows_inserted_total` | поток приёма данных |
| **vminsert** | `vm_dropped_rows_total` | строки отброшены при приёме (потеря) |
| **vminsert** | `vm_rpc_dial_errors_total`, `vm_rpc_vmstorage_is_reachable` | связность с vmstorage |
| **vmselect** | `vm_active_queries`, `vm_slow_queries` | нагрузка на чтение |
| **vmstorage/vmsingle** | `vm_rows`, `vm_parts` | объём и фрагментация данных |
| **vmstorage/vmsingle** | `vm_free_disk_space_bytes` | приближение к read-only |
| **vmalert** | `vmalert_config_last_reload_successful` | конфиг правил применён |
| **vmalert** | `vmalert_alerting_rules_errors_total`, `vmalert_recording_rules_errors_total` | ошибки оценки правил |
| **vmalert** | `vmalert_remotewrite_errors_total`, `vmalert_iteration_missed_total` | доставка recording rules и дрейф расписания |
| **все компоненты** | `up{job=...}` | сам факт скрейпа компонента |

Сценарии с примерами алертов: [Самомониторинг vmagent](../Concepts/Observability_and_Monitoring/meta-monitoring.md#сценарий-2-самомониторинг-victoriametrics-vmagent), [Мониторинг VictoriaMetrics (кластер)](../Concepts/Observability_and_Monitoring/meta-monitoring.md#сценарий-8-мониторинг-victoriametrics-кластерный-режим) (`VictoriaMetricsDroppedRows`, `VictoriaMetricsActiveQueriesHigh`). Метрики vmalert — [vmalert FAQ](./vmalert_overview.md#11-faq), аудит и логирование запросов — [Аудит и самомониторинг](./vmalert_overview.md#аудит-и-самомониторинг).

### 4. Дашборды

- **vmalert** — [Grafana 14950](https://grafana.com/grafana/dashboards/14950).
- **Компоненты VictoriaMetrics** — чарт k8s-stack поставляет готовые дашборды (victoriametrics-cluster, vmagent, vmalert, operator) — [Дашборды VictoriaMetrics](./grafana_integration.md#9-дашборды-victoriametrics).
- **VictoriaTraces** — [24136 (single)](https://grafana.com/grafana/dashboards/24136) и [24134 (cluster)](https://grafana.com/grafana/dashboards/24134).

### 5. Watchdog снаружи стека

Собственные алерты VictoriaMetrics молчат, когда недоступно всё: хранилище в read-only, vmagent не пишет, vmalert не доносит. Поэтому поверх пакетов из п. 2 держите минимум один внешний сторож:

- метрика-«пульс», которую шлёт внешний агент снаружи мониторинга, и алерт по `absent_over_time(...)` на ней;
- либо готовый Dead Man's Switch (например, healthchecks.io self-hosted) — [Внешний watchdog](../Concepts/Observability_and_Monitoring/meta-monitoring.md#сценарий-9-внешний-watchdog-на-bare-metal-healthchecksio-self-hosted);
- мониторинг самих бэкапов — [Сценарий 10: мониторинг выполнения резервного копирования](../Concepts/Observability_and_Monitoring/meta-monitoring.md#сценарий-10-мониторинг-выполнения-резервного-копирования-backup-dead-mans-switch).

Для алертов самого Alertmanager (включая рост числа silences) используйте [метрики самомониторинга Alertmanager](../Prometheus/alertmanager.md#метрики-самомониторинга).

## Рекомендации по эксплуатации

- **Минимальный набор первого дня:** `up` по всем компонентам, ошибки remote write (vmagent/vmalert), `vm_dropped_rows_total`, `vm_free_disk_space_bytes` с запасом до read-only, watchdog снаружи.
- **Отделите «данные не пишутся» от «данные не читаются»**: первое ловят метрики вставки, второе — тестовый запрос чтения из Grafana/CI (синтетический запрос к `/api/v1/query`).
- **Алерты на сами правила vmalert:** `vmalert_alerting_rules_errors_total > 0` держится постоянно — правило сломано и не работает, при этом тишина в Alertmanager это не покажет.
- **Синтетический end-to-end:** периодический тестовый scrape-конвейер «экспортёр → хранилище → запрос» работает как canary всего стека; методология — [триаж цепочки](./metrics-flow-troubleshooting.md).
- **Валидируйте пакеты перед продом:** `tests/` в каталоге пакетов и [vmalert-tool test](./vmalert_rules_management_with_manifests.md#unit-тестирование-правил-vmalert-tool-test) позволяют прогнать правила на синтетических данных.
- **Самомониторинг не заменяет внешний сторож** — см. ограничения ниже.

## Ограничения и особые случаи

- **Тишина при disk full:** переполнение хранилища — «тихий» отказ: процессы продолжают работать, но данные не пишутся/не индексируются корректно. Мета-мониторинг обязан иметь дискриминатор (`vm_free_disk_space_bytes`, read-only состояние) и watchdog снаружи — [Причины отказа систем мониторинга](../Concepts/Observability_and_Monitoring/meta-monitoring.md#причины-отказа-систем-мониторинга).
- **Скрейп мета-метрик через то же хранилище** создаёт петлю отказа: при деградации чтения исчезают и метрики деградации. Выносите `up`/watchdog на отдельный скрейпер или хранилище.
- **Готовые правила — ориентир, а не готовый прод:** пороги рассчитаны на типовые нагрузки, их нужно сверять с фактическими базовыми значениями (медианы за 1–2 недели).
- **Enterprise-пакеты** (`alerts-vmanomaly.yml`) требуют запущенного соответствующего компонента; в Community-стеке они бесполезны.

## Дополнительная информация

Смотрите также:

* [Мета-мониторинг](../Concepts/Observability_and_Monitoring/meta-monitoring.md) — концепция и сценарии для Prometheus/Loki/Zabbix/VM;
* [vmalert: обзор](./vmalert_overview.md) — аудит, метрики, диагностика;
* [Управление правилами манифестами](./vmalert_rules_management_with_manifests.md) — VMRule, CI/CD, мониторинг самих правил;
* [vmagent: обзор](./vmagent_overview.md) — метрики доставки, persistent queue;
* [VictoriaMetrics: обзор](./overview.md) — capacity, read-only, troubleshooting;
* [Нет данных: триаж цепочки](./metrics-flow-troubleshooting.md) — от симптома до места отказа;
* [Alertmanager: метрики самомониторинга](../Prometheus/alertmanager.md#метрики-самомониторинга) — уведомительный конец пайплайна;
* [Grafana: дашборды](../Grafana/grafana-dashboards.md) — организация дашбордов в базе.
