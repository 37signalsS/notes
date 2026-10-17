# vmestimator: оценка кардинальности в реальном времени

**Актуально для:** vmestimator v0.1.17 (независимый проект в стадии 0.x, свой релизный цикл)

## Определения

**vmestimator** — инструмент экосистемы VictoriaMetrics (лицензия Apache-2.0) для непрерывной оценки кардинальности метрик в реальном времени на этапе приёма данных. Принимает поток метрик через Prometheus Remote-Write v1, считает количество уникальных временных серий по конфигурируемым измерениям (лейблам) и отдаёт оценки в формате Prometheus exposition. В отличие от анализа уже записанных данных, vmestimator работает по живому потоку, что позволяет поймать взрыв кардинальности до деградации хранилища.

Ключевые термины:

- **Оценка кардинальности (cardinality estimate)** — вероятностная оценка числа уникальных серий за окно измерения; экспонируется метрикой `cardinality_estimate`.
- **HyperLogLog (HLL)** — вероятностная структура данных, стоящая за оценкой: фиксирует множество серий в компактном скетче, точность зависит от `hll_precision`.
- **Окно измерения (`interval`)** — длительность, в течение которой увиденные серии удерживаются в скетче до его сброса.
- **Stream (поток)** — отдельная запись в `streams.yaml` со своим окном, фильтром и группировкой.
- **Churn** — скорость, с которой серии появляются и исчезают; высокий churn создаёт нагрузку на индекс базы даже при умеренной активной кардинальности.
- **`group_limit`** — предельное число отслеживаемых групп на поток; избыток групп учитывается в общем «rejected»-скетче.
- **Storage node / selector node** — роли кластерного развёртывания: узлы приёма и хранения скетчей и узлы-селекторы, объединяющие их.

## Базовые концепции

### Зачем измерять кардинальность

Типичный сценарий взрыва: команда добавляет в сервис лейбл `trace_id` или `user_id`, и за ночь кардинальность job вырастает с 500 до 500 000 серий — база начинает потреблять кратно больше памяти и диска, инжест деградирует. К моменту пейжа ущерб уже нанесён: индексы раздуты, кеши перераспределены.

Фундаментальные концепции лейблов и кардинальности — в [Cardinality в Prometheus](../Prometheus/concepts/labels_and_cardinality.md); vmestimator закрывает именно инструментальный пробел: **реальное время** (оценки по живому потоку, а не по завершении интервала), **проактивность** (алерты до деградации), **произвольные измерения группировки** (`job`, `__name__`, `vm_account_id` и т.д.).

### Как устроен

vmestimator **принимает** трафик через Prometheus Remote-Write v1 на пути `http://<host>:8490/cardinality/api/v1/write`, вычисляет кардинальность согласно `streams.yaml` и экспонирует результаты на `/metrics` в Prometheus exposition format — их скрайпит любой совместимый коллектор (vmagent, Prometheus).

Рекомендуемая архитектура (из документации): зеркалирование потока от `vmagent` и **выделенный контур** сбора оценок:

```
                     ┌──→ основное хранилище (vmsingle / vmcluster)
Источники → vmagent ─┤
                     └──→ vmestimator :8490/cardinality/api/v1/write   (зеркало RW)
                                    │
                                    ↓ /metrics (Prometheus exposition)
                     vmagent/Prometheus выделенного контура
                                    │
                                    ↓
                     отдельный vmsingle → vmalert / Grafana
```

Так кардинальность остаётся видимой, даже когда основной контур мониторинга недоступен. vmestimator не влияет на источник и на основное хранилище: он получает только зеркальную копию потока.

Заявленная производительность документации: порядка **1 ядра на 800 тыс. сэмплов/с** и около **150 МиБ на каждый настроенный stream** (в тестовом окружении 2 потока на 3 млн уникальных серий — 200 МиБ). Один экземпляр рассчитан на миллионы сэмплов в секунду и сотни миллионов уникальных серий; при нехватке CPU масштабирование горизонтальное (кластерный режим ниже).

### Отличие от других инструментов анализа кардинальности

| Критерий | vmestimator | Cardinality Explorer (VMUI) | PromQL `count()` | `promtool tsdb analyze` |
| :--- | :--- | :--- | :--- | :--- |
| Момент измерения | До инжеста (по живому потоку) | После записи в базу | После записи в базу | Офлайн по файлам TSDB |
| Точность | Оценка (HyperLogLog) | Точный подсчёт | Точный подсчёт | Точный подсчёт |
| Группировка | Предопределённые `group_by` | Произвольные комбинации | Произвольные `by` | Произвольные |
| Исторические тренды | Да (через хранилище) | Нет (точечный срез) | Через хранилище | Нет |
| Стоимость | Низкая (не нагружает хранилище) | Сканирует индекс | Сканирует все ряды | Читает диск локально |
| Алертинг в реальном времени | Да (vmalert) | Нет | Да, но только по хранилищу | Нет |
| Работа при недоступном хранилище | Да (выделенный контур) | Нет | Нет | Нет (только локальный файл) |

Все инструменты дополняют друг друга: vmestimator — непрерывный мониторинг и алертинг, Cardinality Explorer — глубокое разовое исследование, PromQL/`promtool` — точные разовые подсчёты.

## Установка и запуск

### Предварительные требования

- Платформы из [GitHub Releases](https://github.com/VictoriaMetrics/vmestimator/releases): Linux (386, amd64, arm, arm64, s390x), macOS (amd64, arm64), Windows (amd64), FreeBSD/OpenBSD (amd64).
- Файл конфигурации `streams.yaml` обязателен (кроме роли чистого selector-узла в кластерном режиме).
- Доступ к сети мониторинга; отдельных БД, томов и persistent-состояния vmestimator не требует.

Способы получения:

```bash
# Бинарник (пример для Linux amd64, версия зафиксирована осознанно)
VER=v0.1.17
curl -LO "https://github.com/VictoriaMetrics/vmestimator/releases/download/${VER}/vmestimator-linux-amd64-${VER}.tar.gz"
curl -LO "https://github.com/VictoriaMetrics/vmestimator/releases/download/${VER}/vmestimator-linux-amd64-${VER}_checksums.txt"
sha256sum -c "vmestimator-linux-amd64-${VER}_checksums.txt" --ignore-missing
# → vmestimator-linux-amd64-v0.1.17.tar.gz: OK
tar -xzf "vmestimator-linux-amd64-${VER}.tar.gz"
# → архив содержит бинарник vmestimator-prod
sha256sum -c "vmestimator-linux-amd64-${VER}_checksums.txt" --ignore-missing
# → vmestimator-prod: OK
```

```bash
# Docker (Docker Hub или Quay)
docker pull docker.io/victoriametrics/vmestimator:v0.1.17
# зеркало: quay.io/victoriametrics/vmestimator:v0.1.17
```

Для Kubernetes доступен Helm-чарт [victoria-metrics-estimator](https://docs.victoriametrics.com/helm/victoria-metrics-estimator/).

### Конфигурация streams.yaml

Поведение задаётся одним YAML-файлом с ключом `streams` (списком потоков). Пример конфигурации из репозитория проекта:

```yaml
# streams.yaml
streams:
  - interval: '15m'
    calculate_churn: true

  - interval: '15m'
    calculate_churn: true
    group_by: ["__name__"]

  - interval: '15m'
    calculate_churn: true
    group_by: ["job"]
```

Параметры потока:

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `interval` | `5m` | Окно измерения: сколько уникальных серий удерживается до сброса HLL-скетча. **Рост оценки отражается мгновенно**; интервал влияет только на то, как быстро оценка спадает после исчезновения серий. |
| `calculate_churn` | `false` | Эмитит метрику `cardinality_churn_ratio` (отношение в `[0, 1]`: `0` — множество серий стабильно, `1` — полностью заменено). Формула: `(2·\|A∪B\| − \|A\| − \|B\|) / \|A∪B\|`, где A — снимок скетча за окно назад, B — текущий. |
| `filter` | нет | MetricsQL-селектор для предварительной фильтрации: `=`, `!=`, `=~`, `!~`. Считаются только ряды, прошедшие все матчеры. |
| `group_by` | нет (глобальная оценка) | Список лейблов для группировки: `["job"]`, `["__name__"]`, `["vm_account_id","vm_project_id"]`. Псевдолейбл `__label__` — только последним элементом: оценивает число уникальных **значений каждого лейбла** (например, `["job", "__label__"]` — уникальные значения лейблов по каждому job). |
| `group_limit` | `10000` | Максимум отслеживаемых групп на поток; избыток считается в общем «rejected»-скетче. Защита от OOM при неограниченном росте значений лейблов. Верх памяти потока: `group_limit × 2^hll_precision` байт. |
| `min_cardinality` | `0` | Порог подавления «тихих» групп у `group_by`-потоков: `>0` — перекрывает глобальный флаг `-cardinalityMetrics.minCardinality`; `0` — используется глобальный; `<0` — порог не применяется. |
| `buckets` | `min(64, 2×CPU)` | Число шардов для снижения lock contention при параллельном инжесте. Менять только после профилировки. |
| `hll_precision` | `14` | Точность HLL, `4..18`: `p=14` → ошибка ~0,81%, ~16 КиБ на скетч; `p=18` → ~0,20%, ~256 КиБ (точность «для биллинга»); `p=10` → ~3,25%, ~1 КиБ (тысячи групп, экономия памяти). |
| `hll_sparse` | `true` | Sparse-представление для низкокардинальных групп до `~2^(p-1)` серий, затем автоматически dense. |
| `labels` | — | Статические лейблы, добавляемые ко всем метрикам потока (например, `instance` для различения экземпляров при общей базе). |

Типовые конфигурации:

```yaml
streams:
  # Глобальная оценка (group_by отсутствует)
  - interval: '15m'

  # Кардинальность по именам метрик
  - interval: '15m'
    group_by: ['__name__']

  # Только job=api
  - interval: '15m'
    filter: '{job="api"}'
    group_by: ['__name__']

  # Всё, кроме dev/staging
  - interval: '15m'
    filter: '{env!~"dev|staging"}'

  # Уникальные значения каждого лейбла — поиск «виновника» взрыва
  - interval: '15m'
    group_by: ['__label__']

  # Мультитенантность (кластерная редакция VM)
  - interval: '5m'
    group_by: ['vm_account_id', 'vm_project_id']
    min_cardinality: 1000
```

### Перезагрузка конфигурации без перезапуска

vmestimator перечитывает `-config` при:

- сигнале `SIGHUP`: `kill -HUP $(pidof vmestimator)`;
- HTTP-запросе к `/-/reload` (защищается `-reloadAuthKey`, передаётся через query-аргумент `authKey`);
- каждом срабатывании `-configCheckInterval`, если флаг задан (по умолчанию проверка отключена).

Семантика применения: неизменённые потоки сохраняют накопленные оценки; добавленные и любые изменённые потоки стартуют с пустым состоянием; удалённые останавливаются и их оценки больше не экспонируются. Если изменён хоть один поток — сбрасывается состояние дедупликации. При невалидном новом конфиге ошибка пишется в лог, активной остаётся прежняя версия. Изменение command-line флагов требует перезапуска. Статус перезагрузки виден в метриках `vmestimator_config_reloads_total`, `vmestimator_config_reloads_errors_total`, `vmestimator_config_last_reload_successful`, `vmestimator_config_last_reload_success_timestamp_seconds`.

### Запуск

```bash
# Бинарник (по умолчанию слушает :8490)
./vmestimator-prod -config=/etc/vmestimator/streams.yaml
# → оценки: http://127.0.0.1:8490/metrics
# → приём RW:  http://127.0.0.1:8490/cardinality/api/v1/write
```

```bash
# Docker
docker run -d --name vmestimator \
  -p 8490:8490 \
  -v /etc/vmestimator/streams.yaml:/streams.yaml \
  docker.io/victoriametrics/vmestimator:v0.1.17 \
  -config=/streams.yaml
```

```bash
# Docker Compose из репозитория (включает Grafana на :3000, login:admin, пароль:admin)
git clone https://github.com/VictoriaMetrics/vmestimator.git && cd vmestimator
make docker-up
# → http://127.0.0.1:3000 — Grafana с готовыми дашбордами
make docker-down   # остановка окружения
```

### Подключение vmagent (зеркалирование потока)

vmestimator ничего не скрайпит сам — ему зеркалируют поток. Добавьте второй `-remoteWrite.url` к vmagent рядом с основным назначением:

```bash
vmagent \
  -remoteWrite.url=http://127.0.0.1:8428/api/v1/write \
  -remoteWrite.url=http://127.0.0.1:8490/cardinality/api/v1/write \
  -remoteWrite.disableOnDiskQueue=false,true \
  -remoteWrite.disableMetadata=false,true
```

Значения флагов задаются по индексам remoteWrite-назначений: первое значение — для основного хранилища, второе — для vmestimator. `disableOnDiskQueue` и `disableMetadata` снимают лишнюю нагрузку с vmagent для зеркального потока (нет on-disk очереди и обработки metadata). Подробнее о режимах vmagent — в [vmagent — обзор](./vmagent_overview.md).

Сбор самих оценок:

```yaml
# scrape-конфигурация vmagent/Prometheus выделенного контура
scrape_configs:
  - job_name: 'vmestimator'
    static_configs:
      - targets: ['localhost:8490']
```

Рекомендуется отправлять оценки в **отдельный** `vmsingle`: кардинальность остаётся видимой при аварии основного контура и не конкурирует с продовыми данными.

## Метрики и запросы

### Оценки кардинальности

Все метрики несут лейблы `interval`, `filter`, `group_by_keys`, `group_by_values` и статические `labels` из конфига потока.

Глобальная оценка (без `group_by`) — `group_by_keys="__global__"`, без `group_by_values`:

```promql
cardinality_estimate{interval="1h0m0s", filter="", group_by_keys="__global__"}
```

Группированная оценка: одна сводная строка `group_by_keys="__group__"` (число групп) плюс строка на комбинацию значений с лейблами `by_{key}="{val}"`:

```
cardinality_estimate{interval="5m0s",filter="",group_by_keys="__group__",group_by_values="instance,job"} 2
cardinality_estimate{interval="5m0s",filter="",group_by_keys="instance,job",group_by_values="host1:9090,prometheus",by_instance="host1:9090",by_job="prometheus"} 312
```

Для `__label__`-потоков сводка содержит `group_by_values="__label__"`, а в строках групп — `by__label__="<имя лейбла>"`.

> Сводная строка может быть больше числа строк групп: при достижении `group_limit` избыток групп считается в одном общем rejected-скетче.

Churn (только при `calculate_churn: true`):

```promql
cardinality_churn_ratio{interval="15m0s",filter="",group_by_keys="job",group_by_values="api",by_job="api"}
# значение в [0, 1]: 0 — стабильное множество серий, 1 — полная замена
```

### Экспозиция оценок

Управляется флагом `-cardinalityMetrics.exposeAt`:

- `/metrics` (по умолчанию) — оценки слиты с операционными метриками;
- `/cardinality/metrics` — оценки на отдельном пути;
- пустое значение — оценки не экспонируются по HTTP.

Вычисление оценок дорогое, поэтому результат кешируется: `-cardinalityMetrics.cacheTTL` (по умолчанию `30s`, `0` — отключить кеш). Флаг `-cardinalityMetrics.minCardinality=N` подавляет групповые оценки ниже `N`; число подавленных групп видно в `vmestimator_cardinality_estimates_dropped`.

### Операционные метрики

На `/metrics` (для потоков с непустым `group_by`):

| Метрика | Назначение |
| :--- | :--- |
| `vmestimator_estimator_group_size{interval,filter,group_by_keys}` | Текущее число отслеживаемых групп |
| `vmestimator_estimator_group_rejected_size{interval,filter,group_by_keys}` | Число групп, отвергнутых после исчерпания `group_limit` |
| `vmestimator_estimator_group_limit{interval,filter,group_by_keys}` | Настроенный `group_limit` для потока |

Для всех потоков (включая глобальные): `vmestimator_estimator_insert_total{group_by_keys,interval,filter}` — суммарное число сэмплов, вставленных в оценщик (только ряды, прошедшие `filter`). Плюс метрики перезагрузки конфигурации (секция выше).

### Полезные запросы

```promql
# Топ-10 метрик по кардинальности
topk(10, cardinality_estimate{group_by_keys="__name__"})

# Топ-10 job по кардинальности
topk(10, max without(instance) (cardinality_estimate{group_by_keys="job"}))

# Глобальная оценка (для селектора с несколькими узлами — дедупликация)
max without(instance) (cardinality_estimate{group_by_keys="__global__"})

# Глобальный churn выше 10%
max without(instance) (cardinality_churn_ratio{group_by_keys="__global__"}) * 100 > 10

# Группы, приближающиеся к group_limit (доля в процентах)
sum(vmestimator_estimator_group_size) by (group_by_keys, interval)
  / sum(vmestimator_estimator_group_limit) by (group_by_keys, interval) * 100
```

Для оценки кардинальности **уже хранящихся** данных используйте `/api/v1/status/tsdb` и Cardinality Explorer (см. [HTTP API](./http_api_reference.md)); PromQL-альтернатива для малых баз — `count({__name__=~".*"})` и `topk(10, count({__name__=~".*"}) by (__name__))`, но такие запросы сканируют весь набор рядов и не работают при недоступном хранилище.

## Практические сценарии

### 1. Алертинг на готовых правилах

Предзаготовленные правила — `deployment/docker/rules/alerts-cardinality.yml` в репозитории проекта: группа `cardinality.recording` (recording rules `cardinality_estimate:weekly_avg`, `cardinality_estimate:weekly_stddev` — недельная средняя и стандартное отклонение) и группа `cardinality` (алерты).

Конфигурация потоков, которую требуют правила:

```yaml
streams:
  - interval: '15m'
    calculate_churn: true
  - interval: '15m'
    calculate_churn: true
    group_by: ['job']
```

| Алерт | Условие (порог требует калибровки под среду) |
| :--- | :--- |
| `GlobalChurnTooHigh` | глобальный churn `> 10%` в течение `15m` |
| `JobChurnTooHigh` | churn job `> 20%` в течение `30m` |
| `GlobalCardinalityTooHigh` | глобальная оценка выше недельной средней + 3σ **и** на 20% выше средней; базовая линия — 100 тыс. серий; `for: 30m` |
| `JobCardinalityTooHigh` | то же по job; базовая линия — 10 тыс. серий на job; `for: 30m` |
| `CardinalityGroupLimitNearlyReached` | `group_size / group_limit > 80%` в течение `15m` |
| `CardinalityGroupLimitReached` | `group_rejected_size > 0` в течение `5m`, `severity: critical` |

Пример правила (аномалия по недельной средней для глобальной оценки сформирована из recording rules):

```yaml
# фрагмент alerts-cardinality.yml, группа cardinality.recording
- record: 'cardinality_estimate:weekly_avg'
  expr: 'avg_over_time((max(cardinality_estimate{group_by_keys=~"__global__|job",interval="15m0s"}) without(instance))[1w:5m])'
- record: 'cardinality_estimate:weekly_stddev'
  expr: 'stddev_over_time((max(cardinality_estimate{group_by_keys=~"__global__|job",interval="15m0s"}) without(instance))[1w:5m])'
```

Подключаются к vmalert как обычные `-rule` (см. [vmalert — обзор](./vmalert_overview.md)).

### 2. Runbook: реакция на алерт о росте кардинальности

**Шаг 1 — локализация.** Определить, глобальный это рост или конкретный job:

```promql
topk(10, max without(instance) (cardinality_estimate{group_by_keys="job"}))
topk(10, cardinality_estimate{group_by_keys="__name__"})
```

**Шаг 2 — поиск лейбла-виновника.** Включить `group_by: ['__label__']` для проблемного потока (сузить `filter` по job) и посмотреть, у какого лейбла взято число уникальных значений:

```yaml
streams:
  - interval: '15m'
    filter: '{job="api"}'
    group_by: ['__label__']
```

```promql
topk(10, cardinality_estimate{group_by_keys="__label__"})
```

**Шаг 3 — корректирующие действия:** удалить/обрезать high-cardinality лейбл через `metric_relabel_configs` в vmagent, увеличить `scrape_interval` проблемного job, добавить recording rule с агрегацией, задать ограничения в конфигурации scrape. Методы редактирования лейблов — в [relabeling/базовых концепциях](../Prometheus/concepts/labels_and_cardinality.md).

**Шаг 4 — верификация:** дождаться спада оценки (окно измерения должно «забыть» старые серии) и убедиться, что `cardinality_estimate` по job снижается:

```promql
max without(instance) (cardinality_estimate{group_by_keys="job"})
```

### 3. Визуализация в Grafana

Два дашборда в каталоге `dashboards` репозитория проекта:

1. **VictoriaMetrics — vmestimator** ([mkv22l4](https://play-grafana.victoriametrics.com/d/mkv22l4/victoriametrics-vmestimator)) — здоровье приложения: CPU, память, скорости инжеста, конкурентные вставки, насыщение групп.
2. **VictoriaMetrics — Cardinality Estimations** ([mktd5g9](https://play-grafana.victoriametrics.com/d/mktd5g9/victoriametrics-cardinality-estimations)) — оценки кардинальности и churn по настроенным измерениям.

Все алерты из комплекта ссылаются на панели дашборда `mktd5g9`. Ошибки (если дашборд старый) ищите в каталоге `dashboards` актуальной версии — при обновлении vmestimator проверяйте дашборды вместе с бинарником.

### 4. Выделенный контур сбора оценок

Задача: оценки кардинальности должны пережить аварию основного контура мониторинга.

1. Отдельный `vmagent` (или тот же, но отдельным `-remoteWrite.url`) скрайпит `:8490/metrics`.
2. Оценки пишутся в отдельный `vmsingle` (минимальный объём данных — только оценки и операционные метрики).
3. `vmalert` этого контура работает с `alerts-cardinality.yml`; Grafana читает тот же `vmsingle`.

Изолированный контур не зависит от основного инжеста: кардинальность видна именно тогда, когда основное хранилище деградирует.

### 5. Развёртывание на bare-metal (systemd)

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin vmestimator
sudo mkdir -p /etc/vmestimator
sudo install -o root -g root -m 755 vmestimator-prod /usr/local/bin/vmestimator
```

```ini
# /etc/systemd/system/vmestimator.service
[Unit]
Description=VictoriaMetrics cardinality estimator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vmestimator
Group=vmestimator
ExecStart=/usr/local/bin/vmestimator -config=/etc/vmestimator/streams.yaml
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
# hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadOnlyPaths=/etc/vmestimator

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vmestimator
systemctl status vmestimator
# → active (running)

# Перезагрузка конфигурации без рестарта
sudo systemctl reload vmestimator
# → сигнал SIGHUP, статус виден в vmestimator_config_last_reload_successful
```

### 6. Ограничение ресурсов и тюнинг

```ini
# /etc/systemd/system/vmestimator.service, фрагмент [Service]
CPUQuota=100%
MemoryMax=512M
TasksMax=64
```

```bash
# Docker
docker run -d --name vmestimator \
  --cpus=1.0 --memory=512m --pids-limit=64 \
  -p 8490:8490 \
  -v /etc/vmestimator/streams.yaml:/streams.yaml \
  docker.io/victoriametrics/vmestimator:v0.1.17 \
  -config=/streams.yaml \
  -deduplication.interval=2m
```

Направления оптимизации при высокой нагрузке:

- `-deduplication.interval=2m` — bloom-фильтры отбрасывают уже увиденные серии до обработки (значительно экономит CPU; устанавливайте в 3–5 раз меньше самого короткого `interval` потока). Бюджет памяти дедупликации — 5% от разрешённой (`-memory.allowedBytes`/`-memory.allowedPercent`), переопределяется `-deduplication.maxSizeBytes` (например, `100MB`) или `-deduplication.maxSize` (число серий); при 80% заполнения дедупликатор плавно переходит в pass-through, чтобы bloom-фильтры не насыщались.
- Увеличить `interval` потоков и сократить число `group_by`-измерений.
- Поднять `hll_precision`/`group_limit` только по результатам замеров (память растёт как `group_limit × 2^hll_precision`).
- Горизонтально: кластерный режим (см. ниже).

### 7. Кластерный режим (HA и масштабирование)

Роли:

- **Storage-узлы** принимают Prometheus remote write и ведут локальные HLL-скетчи:

```bash
vmestimator -config=streams.yaml -httpListenAddr=:8491 -cardinalityMetrics.exposeAt=/cardinality/metrics
vmestimator -config=streams.yaml -httpListenAddr=:8492 -cardinalityMetrics.exposeAt=/cardinality/metrics
vmestimator -config=streams.yaml -httpListenAddr=:8493 -cardinalityMetrics.exposeAt=/cardinality/metrics
```

- **Selector-узлы** опрашивают все storage-узлы, объединяют скетчи и отдают единую оценку; именно их и скрайпят:

```bash
vmestimator \
  -storageNode=http://vmestimator-storage-1:8491 \
  -storageNode=http://vmestimator-storage-2:8492 \
  -storageNode=http://vmestimator-storage-3:8493 \
  -httpListenAddr=:8490
```

Selector только со `-storageNode` и без `-config` работает без локальных оценщиков. На storage-узлах `-cardinalityMetrics.exposeAt=/cardinality/metrics` убирает локальные оценки с общего `/metrics` (остаются операционные метрики; локальная оценка доступна отдельно для отладки). При скрайпе нескольких selector-узлов каждый возвращает полностью объединённую оценку — дедуплицируйте на уровне запроса: `max(cardinality_estimate) without (instance)`.

При различии `min_cardinality` между storage-узлами selector использует наибольшее значение.

## Валидация установки

Команды выполняются после запуска vmestimator и настройки зеркалирования vmagent:

```bash
ADDR=127.0.0.1:8490

# 1. HTTP-эндпоинт метрик отвечает
curl -s -o /dev/null -w '%{http_code}\n' http://${ADDR}/metrics
# → 200

# 2. Оценки присутствуют (спустя окно измерения после запуска потока)
curl -s http://${ADDR}/metrics | grep '^cardinality_estimate{' | head -3
# → cardinality_estimate{interval="15m0s",filter="",group_by_keys="__global__"} 41230
# → cardinality_estimate{interval="15m0s",filter="",group_by_keys="__group__",group_by_values="job"} 17
# → cardinality_estimate{interval="15m0s",filter="",group_by_keys="job",group_by_values="api",by_job="api"} 3120

# 3. Поток реально обрабатывается (счётчик insert растёт)
curl -s http://${ADDR}/metrics | grep '^vmestimator_estimator_insert_total'
# → vmestimator_estimator_insert_total{group_by_keys="__global__",interval="15m0s",filter=""} 18234412

# 4. Статус перезагрузки конфигурации
curl -s http://${ADDR}/metrics | grep '^vmestimator_config_'
# → vmestimator_config_last_reload_successful 1
# → vmestimator_config_reloads_total 0

# 5. В конфигурации vmagent два remoteWrite-назначения (основное + зеркало)
grep -c 'remoteWrite.url' /etc/vmagent/vmagent.yml
# → 2

# 6. Оценки дошли в хранилище выделенного контура
curl -s -G 'http://vmsingle-card:8428/api/v1/query' \
  --data-urlencode 'query=count(cardinality_estimate) by (group_by_keys)' \
  | jq -r '.data.result[].metric.group_by_keys'
# → __global__
# → job
```

Шаги 2–3 заполняются постепенно: счётчик `insert_total` растёт сразу после подключения потока, оценки по группам — по истечении окон `interval`.

## Поиск и устранение неисправностей

| Симптом | Причина | Диагностика и решение |
| :--- | :--- | :--- |
| vmestimator не стартует без `-storageNode` | Не указан обязательный `-config` | Задать `-config=/path/streams.yaml`; проверить YAML-синтаксис и права на файл (`journalctl -u vmestimator` / `docker logs vmestimator`) |
| Нет `cardinality_estimate` на `/metrics` | Нет входящего потока | Проверить второй `-remoteWrite.url` у vmagent и доступность `:8490/cardinality/api/v1/write`; смотреть `vmestimator_estimator_insert_total` |
| `insert_total` растёт, оценки нулевые | Слишком короткий `interval` ещё не накопил окно | Оценки растут мгновенно для новых серий; проверить `filter` — возможно, он отсекает все ряды |
| Оценки выше реальной кардинальности | Клиент шлёт серии с непорядочными лейблами (`{a=1,b=2}` и `{b=2,a=1}` считаются разными) | Привести отправителей к детерминированному порядку лейблов (см. «Ограничения») |
| Оценка не убывает после исчезновения серий | Работает окно измерения | Норма: спад равен длине `interval`; при необходимости сократить `interval` |
| `vmestimator_estimator_group_rejected_size > 0` | Достигнут `group_limit` | Увеличить `group_limit`, сузить `filter` или уменьшить число `group_by` |
| Шум от низкокардинальных групп | Много групп с малой кардинальностью | Задать `-cardinalityMetrics.minCardinality` или `min_cardinality` на потоке; смотреть `vmestimator_cardinality_estimates_dropped` |
| Нет `cardinality_churn_ratio` | `calculate_churn` не включён | Добавить `calculate_churn: true` в нужные потоки |
| Высокое CPU | Много потоков/групп, нет дедупликации | Включить `-deduplication.interval`, увеличить `interval`, сократить `group_by` |
| После SIGHUP пропали оценки потока | Поток изменён в конфиге — состояние сброшено штатно | Норма по семантике reload; оценки переформируются за окно; невалидный конфиг откатывается автоматически (старый остаётся) |
| У селектора нет данных | Storage-узлы недоступны или не скрайпятся | Проверить флаги `-storageNode`, сетевую доступность storage-портов; при нескольких selector — дедуплицировать `max(...) without(instance)` |
| Кардинальность «прыгает» при backfill | Приём backfill считается по времени прихода, а не по таймстемпам | Ограничить поток фильтром или маршрутизировать backfill мимо зеркала на vmestimator |

### Диагностические команды

```bash
systemctl status vmestimator
journalctl -u vmestimator --since "1 hour ago" --no-pager

ps -p $(pgrep vmestimator) -o pid,%cpu,%mem,cmd
ss -tlnp | grep 8490

# все ключевые метрики одним запросом
curl -s http://127.0.0.1:8490/metrics | grep -E '^vmestimator_(config|estimator)'
```

## Рекомендации по эксплуатации

### Размеры ресурсов

Ориентиры из документации: ~1 ядро CPU на 800 тыс. сэмплов/с; ~150 МиБ памяти на каждый настроенный stream (тест: 2 потока на 3 млн серий — 200 МиБ). Дисковое хранилище vmestimator не использует — состояние живёт в памяти и пересобирается по окнам после рестарта. Практика: наблюдайте за потреблением на дашборде «VictoriaMetrics — vmestimator» и учитывайте нагрузку потока зеркалирования на vmagent (для него это дополнительный `-remoteWrite.url` без on-disk очереди).

### Безопасность

- Порт `8490` (HTTP + приём remote write) открывайте только для сети мониторинга; публичная экспозиция недопустима.
- vmestimator поддерживает общие флаги защиты семейства VictoriaMetrics: `-httpAuth.username`/`-httpAuth.password`, `-metricsAuthKey`, `-flagsAuthKey`, `-pprofAuthKey`, `-reloadAuthKey` (обязателен для открытого `/-/reload`), `-tls`/`-tlsCertFile`/`-tlsKeyFile`/`-tlsMinVersion`. Подробно — в [Безопасность VictoriaMetrics](./security.md).
- `streams.yaml` секретов не содержит, отдельных мер хранения не требует.

### Обновление

```bash
# текущая версия
vmestimator -version

# бинарник: скачать нужный архив с GitHub Releases, проверить checksums,
# заменить бинарник и перезапустить (изменения флагов требуют рестарта)
sudo systemctl stop vmestimator
sudo cp vmestimator-prod /usr/local/bin/vmestimator
sudo systemctl start vmestimator

# Docker: тег фиксируется, не latest
docker pull docker.io/victoriametrics/vmestimator:v0.1.17
docker rm -f vmestimator
# запустить с теми же флагами и монтированием конфигурации
```

При обновлении сверяйте `streams.yaml` с новой документацией: добавленные/изменённые потоки после reload стартуют с пустым состоянием. Правила алертов и дашборды проверяйте вместе с бинарником (каталоги `deployment/docker/rules/` и `dashboards/` репозитория).

### Очистка окружения

```bash
# Docker
docker rm -f vmestimator

# systemd
sudo systemctl disable --now vmestimator
sudo rm /etc/systemd/system/vmestimator.service
sudo rm -rf /etc/vmestimator
sudo userdel vmestimator
sudo systemctl daemon-reload
```

## Ограничения и особые случаи

### Точность (HyperLogLog)

Оценка вероятностная; погрешность управляется `hll_precision`:

| `hll_precision` | Относительная ошибка | Память на скетч | Применение |
| :--- | :--- | :--- | :--- |
| `10` | ~3,25% | ~1 КиБ | Тысячи групп, жёсткая экономия памяти |
| `14` (по умолчанию) | ~0,81% | ~16 КиБ | Большинство случаев |
| `18` | ~0,20% | ~256 КиБ | Точность «для биллинга», спорные перерасчёты |

Глобальная оценка точнее групповых (меньше независимых скетчей). Sparse-режим (`hll_sparse`) экономит память на низкокардинальных группах.

### Ограничения обработки (из документации)

Для производительности vmestimator **не декодирует значения сэмплов** в remote-write запросах, только лейблы. Следствия:

1. Кардинальность оценивается по **времени прихода запроса**, а не по таймстемпам: backfill со старыми таймстемпами засчитывается как «сейчас».
2. Staleness-маркеры не декодируются — ряд с маркером считается как обычный series.
3. Порядок лейблов должен быть детерминированным: `metric{foo=bar, baz=qux}` и `metric{baz=qux, foo=bar}` считаются двумя разными сериями, что завышает оценку. Отправляющие системы должны сортировать лейблы.

### Состояние и рестарт

Всё состояние — HLL-скетчи в памяти. После рестарта оценки пересобираются по входящему потоку за окно `interval`; долговременные тренды живут в хранилище, куда скрапятся оценки. Отдельный WAL и дисковое состояние отсутствуют, требования к диску — только под бинарник и конфигурацию.

### Версионирование

Проект 0.x: API конфигурации и набор метрик могут меняться между минорными релизами — фиксируйте версию бинарника/тега и сверяйте CHANGELOG проекта. vmestimator не является компонентом основного релиза VictoriaMetrics и не наследует его LTS-цикл; разделения на Community/Enterprise у него нет (Apache-2.0).

## Дополнительная информация

- **Документация:** [docs.victoriametrics.com/victoriametrics/vmestimator](https://docs.victoriametrics.com/victoriametrics/vmestimator/)
- **Репозиторий:** [github.com/VictoriaMetrics/vmestimator](https://github.com/VictoriaMetrics/vmestimator) — примеры конфигураций (`streams.yaml`), правила алертов (`deployment/docker/rules/alerts-cardinality.yml`), дашборды (`dashboards/`)
- **Анонс:** [Announcing vmestimator (блог VictoriaMetrics)](https://victoriametrics.com/blog/vmestimator-announcement/)
- **Helm:** [victoria-metrics-estimator](https://docs.victoriametrics.com/helm/victoria-metrics-estimator/)

Связанные компоненты:

- [VictoriaMetrics — обзор](./overview.md) — платформа хранения метрик;
- [vmagent — обзор](./vmagent_overview.md) — зеркалирование потока в vmestimator;
- [vmalert — обзор](./vmalert_overview.md) — алертинг на оценках и churn;
- [HTTP API VictoriaMetrics](./http_api_reference.md) — `/api/v1/status/tsdb` для кардинальности уже хранимых серий;
- [storage_internals.md](./storage_internals.md) — RAM/indexdb под кардинальность и формулы оценки;
- [Безопасность VictoriaMetrics](./security.md) — аутентификация, TLS и AuthKey;
- [Cardinality в Prometheus](../Prometheus/concepts/labels_and_cardinality.md) — теория лейблов и кардинальности;
- [Планирование ёмкости](../Concepts/capacity-planning.md) — методология capacity planning с учётом кардинальности.
