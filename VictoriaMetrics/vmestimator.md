# vmestimator: оценка кардинальности в реальном времени

## 1. Определения

**vmestimator** — инструмент экосистемы VictoriaMetrics для непрерывной оценки кардинальности (количества уникальных временных рядов) в реальном времени на этапе приёма метрик. Распространяется под лицензией Apache-2.0. В отличие от пост-фактум анализа TSDB, vmestimator оценивает кардинальность до записи данных в хранилище, что позволяет предотвратить взрыв кардинальности до наступления деградации системы.

Ключевая метрика, экспортируемая vmestimator, — `cardinality_estimate`. Она показывает текущую оценку количества уникальных серий за заданный интервал и группу лейблов.

## 2. Базовые концепции

### Принцип работы

vmestimator развёртывается на коллекторном узле (обычно рядом с `vmagent`) и наблюдает за входящим потоком метрик, не вмешиваясь в путь инжеста. На основе поступающих данных он строит оценки кардинальности по конфигурируемым измерениям (label dimensions) и экспортирует их в формате, совместимом с Prometheus.

```
Источники метрик → vmagent → vmestimator (наблюдатель) → VictoriaMetrics
                                   ↓
                             /metrics (scrape)
                                   ↓
                              Prometheus / VictoriaMetrics → Grafana / vmalert
```

### Зачем нужен vmestimator

Классические инструменты анализа кардинальности (`promtool tsdb analyze`, Cardinality Explorer в VMUI) работают с уже записанными данными. Это означает, что взрыв кардинальности обнаруживается постфактум, когда система уже деградировала.

vmestimator закрывает этот пробел:
- **Реальное время:** оценки строятся continuously, а не по завершении интервала сбора.
- **Проактивность:** алерты срабатывают до того, как кардинальность нанесёт ущерб.
- **Гибкость группировки:** можно оценивать кардинальность по произвольным лейблам (`job`, `__name__`, `tenant` и т.д.).

### Отличие от Cardinality Explorer (VMUI)

| Критерий | vmestimator | Cardinality Explorer (VMUI) |
| :--- | :--- | :--- |
| **Момент измерения** | До инжеста (source-side) | После записи (storage-side) |
| **Точность** | Оценка (гиперloglog) | Точный подсчёт |
| **Группировка** | Только предопределённые | Произвольные комбинации |
| **Исторические тренды** | Да | Нет |
| **Стоимость запроса** | Низкая (не нагружает хранилище) | Высокая (сканирует индекс) |
| **Алертинг** | Да (через vmalert) | Нет |

## 3. Требования к окружению

### Операционная система и среда

vmestimator — нативный Go-бинарник, не имеет внешних зависимостей (CGO не требуется). Работает на любом Linux-совместимом ОС с поддержкой `amd64` и `arm64`.

| Требование | Минимальное | Рекомендуемое |
| :--- | :--- | :--- |
| **CPU** | 1 ядро | 2+ ядра |
| **RAM** | 128 МБ | 256 МБ |
| **Диск** | 100 МБ (данные + WAL) | 1 ГБ (с запасом под retention) |
| **Сеть** | Доступ к vmagent (scrape) | Отдельный порт для `/metrics` |

> **Примечание:** vmestimator не хранит данные серий в долгосрочном хранилище, а только агрегированные оценки за интервал. Поэтому требования к диску минимальные. Основная нагрузка — на CPU при обновлении HyperLogLog-структур.

### Аппаратные требования

Ресурсы зависят от количества уникальных метрик и частоты обновления:

| Сценарий | Активных метрик | CPU | RAM | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Средний** | < 100 000 | 0.5 ядра | 128 МБ | Совместно с vmagent |
| **Большой** | 100 000 – 1 000 000 | 1–2 ядра | 256–512 МБ | Отдельный узел |
| **Очень большой** | > 1 000 000 | 2+ ядра | 1 ГБ+ | Кластеризация через несколько экземпляров |

### Программные зависимости

- **Стек:** Любой Prometheus-совместиный scraper (Prometheus, vmagent, Thanos Ruler).
- **Формат метрик:** Text exposition format (Prometheus format).
- **Совместимость:** Полностью совместим с Prometheus remote_write v1 и v2.

### Сеть

| Порт | Назначение | Протокол |
| :--- | :--- | :--- |
| `8490` | Метрики vmestimator (scrape endpoint) | HTTP |

## 4. Конфигурация

Поведение vmestimator задаётся в файле `streams.yaml`. Основные параметры:

```yaml
# streams.yaml

# Глобальная оценка кардинальности с интервалом 15 минут
- interval: '15m'

# Оценка по именам метрик
- interval: '15m'
  group_by: ['__name__']

# Оценка по job с дополнительным измерением по региону
- interval: '15m'
  group_by: ['job', 'region']

# Оценка по tenant (мультитенантные среды)
- interval: '30m'
  group_by: ['tenant']
```

### Параметры

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `interval` | `duration` | Интервал оценки (например, `15m`, `30m`, `1h`). Определяет, как часто пересчитывается оценка. |
| `group_by` | `[]string` | Список лейблов для группировки. Специальное значение `__global__` (дефолт) означает оценку без группировки. |

> **Важно:** Интервал — это компромисс между скоростью обнаружения и стабильностью оценки. Слишком короткий интервал (< 5m) даёт шумные данные при переменной нагрузке; слишком длинный (> 1h) замедляет обнаружение всплесков.

### Запуск

```bash
# Docker
docker run --rm \
  -p 8490:8490 \
  -v /path/to/streams.yaml:/streams.yaml \
  docker.io/victoriametrics/vmestimator:latest \
  -config=/streams.yaml
```

```bash
# Бинарник
vmestimator -config=/streams.yaml
# → метрики доступны на http://localhost:8490/metrics
```

## 5. Валидация установки

После запуска vmestimator необходимо проверить, что компонент корректно принимает и обрабатывает данные.

### Проверка работоспособности

```bash
# 1. Проверка доступности эндпоинта метрик
curl -s http://localhost:8490/metrics | head -n 20

# Ожидаемый результат: наличие метрик с префиксом vmestimator_
# Пример:
# vmestimator_scrape_interval_seconds 15
# vmestimator_cardinality_estimate ...
```

```bash
# 2. Проверка логов (Docker)
docker logs <container_id> 2>&1 | grep -E "listening|started|error"

# 3. Проверка процесса (bare-metal)
ps aux | grep vmestimator
systemctl status vmestimator
```

### Верификация данных

```bash
# 4. Проверка наличия данных в Prometheus/VM
curl -s 'http://<prometheus>:9090/api/v1/query?query=cardinality_estimate' | jq .

# Ожидаемый результат: массив с данными, а не пустой результат
```

```bash
# 5. Проверка интеграции с vmagent
curl -s http://localhost:8429/metrics | grep vmestimator
# Должны отображаться метрики vmestimator, собранные vmagent
```

### Диагностика типичных проблем

| Симптом | Возможная причина | Проверка |
| :--- | :--- | :--- |
| Пустой ответ на `/metrics` | Неверный путь к `streams.yaml` | `docker logs` / `journalctl -u vmestimator` |
| Метрика `cardinality_estimate` отсутствует | vmestimator не получает данные от vmagent | Проверьте `vmagent` scrape config |
| Нет данных в VictoriaMetrics | Слишком короткий `interval` или нет данных на входе | Увеличьте `interval` до `1h` для теста |
| Высокое потребление CPU | Слишком много streams с коротким interval | Оцените количество уникальных метрик |

## 6. Метрики и запросы

### Ключевая метрика

```promql
# Глобальная оценка за 15 минут
cardinality_estimate{interval="15m0s", group_by_keys="__global__"}

# Оценка по имени метрики
cardinality_estimate{interval="15m0s", group_by_keys="__name__"}

# Оценка по job
cardinality_estimate{interval="30m0s", group_by_keys="job"}
```

### Полезные запросы

```promql
# Топ-5 метрик по кардинальности за 15 минут
topk(5, cardinality_estimate{interval="15m0s", group_by_keys="__name__"})

# Топ-5 job по кардинальности
topk(5, cardinality_estimate{interval="30m0s", group_by_keys="job"})

# Churn rate: разница между 30m и 15m оценками (в процентах)
(
  max(cardinality_estimate{interval="30m0s", group_by_keys="job"}) without(instance)
  -
  max(cardinality_estimate{interval="15m0s", group_by_keys="job"}) without(instance)
)
/
max(cardinality_estimate{interval="30m0s", group_by_keys="job"}) without(instance) * 100
```

## 7. Практические сценарии

### Сценарий 1: Обнаружение всплеска кардинальности

**Задача:** Получать алерт, когда кардинальность для любого job превышает 20 000 серий за 30 минут.

```yaml
# vmalert rules
groups:
  - name: 'cardinality'
    rules:
      - alert: 'JobTooHighCardinality'
        expr: 'max(cardinality_estimate{group_by_keys="job", interval="30m0s"}) without(instance) > 20000'
        for: '15m'
        labels:
          severity: 'warning'
        annotations:
          dashboard: "{{ $externalURL }}/d/mktd5g9?var-group_by_keys=job&var-interval={{ $labels.interval }}"
          summary: "High cardinality for job {{ $labels.group_by_values }}"
          description: "Job {{ $labels.group_by_values }} has {{ $value }} estimated series over the last {{ $labels.interval }}, exceeding the 20000 series threshold."
```

### Сценарий 2: Алерт на высокий Churn Rate

**Задача:** Обнаружить job, у которых более 10% серий «умерло» и было заменено новыми между окнами 15m и 30m.

```yaml
      - alert: 'JobTooHighChurnRate'
        expr: |
          (
              max(cardinality_estimate{group_by_keys="job", interval="30m0s"}) without (instance)
              -
              max(cardinality_estimate{group_by_keys="job", interval="15m0s"}) without (instance)
          )
          /
          max(cardinality_estimate{group_by_keys="job", interval="30m0s"}) without (instance) * 100 > 10
        for: '15m'
        labels:
          severity: 'warning'
        annotations:
          dashboard: "{{ $externalURL }}/d/mktd5g9?var-group_by_keys=job&var-churn_short=15m0s&var-churn_long=30m0s"
          summary: "High churn rate for job {{ $labels.group_by_values }}"
          description: 'Job {{ $labels.group_by_values }} has {{ printf "%.0f%%" $value }} of series churned between the 15m and 30m cardinality windows, exceeding the 10% threshold.'
```

### Сценарий 3: Визуализация в Grafana

vmestimator поставляется с двумя готовыми дашбордами:

1. **vmestimator metrics** — метрики самого приложения (CPU, RAM, ingestion rate, concurrent inserts, saturation group keys).
2. **Cardinality Estimations** — общая кардинальность, churn rate, топ-10 метрик и job.

Дашборды импортируются из репозитория vmestimator или доступны в VictoriaMetrics Grafana Playground (разделы `cardinality` и `cardinality.recording`).

### Сценарий 4: Планирование capacity

Долгосрочные тренды кардинальности, собираемые vmestimator в VictoriaMetrics, полезны для capacity planning:

```promql
# Прогноз роста кардинальности на 30 дней
predict_linear(cardinality_estimate{group_by_keys="__global__"}[30d], 30 * 24 * 3600)
```

### Сценарий 5: Деплой на bare-metal (systemd)

**Задача:** Запустить vmestimator на сервере без контейнеризации, с автозапуском и ротацией логов.

```bash
# Создание пользователя и директорий
sudo useradd --system --no-create-home --shell /usr/sbin/nologin vmestimator
sudo mkdir -p /etc/vmestimator /var/lib/vmestimator
sudo chown vmestimator:vmestimator /var/lib/vmestimator
```

```yaml
# /etc/vmestimator/streams.yaml
- interval: '15m'
- interval: '15m'
  group_by: ['__name__']
- interval: '15m'
  group_by: ['job']
```

```ini
# /etc/systemd/system/vmestimator.service
[Unit]
Description=VictoriaMetrics Cardinality Estimator
After=network.target

[Service]
Type=simple
User=vmestimator
Group=vmestimator
ExecStart=/usr/local/bin/vmestimator \
  -config=/etc/vmestimator/streams.yaml
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
# Установка и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now vmestimator

# Проверка
systemctl status vmestimator
curl -s http://localhost:8490/metrics | head
```

### Сценарий 6: Resource Limits и тюнинг производительности

**Задача:** Ограничить потребление ресурсов vmestimator в production и подобрать оптимальные параметры.

```yaml
# streams.yaml с оптимизацией
- interval: '30m'
  group_by: ['job']
  # Для больших сред — уменьшайте количество streams
  # Каждый stream потребляет CPU при обновлении HyperLogLog
```

```bash
# Ограничение ресурсов через systemd
# /etc/systemd/system/vmestimator.service
[Service]
CPUQuota=50%
MemoryMax=256M
TasksMax=32
```

```bash
# Ограничение через Docker
docker run -d \
  --name vmestimator \
  --cpus=0.5 \
  --memory=256m \
  -p 8490:8490 \
  -v /etc/vmestimator/streams.yaml:/streams.yaml \
  docker.io/victoriametrics/vmestimator:latest \
  -config=/streams.yaml
```

> **Важно:** При высокой нагрузке (>1M уникальных метрик) увеличивайте `interval` до `30m` или `1h` и уменьшайте количество `group_by` dimensions. Это снижает шумность данных и потребление CPU.

### Сценарий 7: Production runbook — реакция на алерт кардинальности

**Задача:** Структурировать действия инженера при срабатывании `JobTooHighCardinality`.

**Шаг 1: Идентификация источника**

```promql
# Топ-10 метрик по кардинальности
topk(10, cardinality_estimate{interval="15m0s", group_by_keys="__name__"})

# Топ-10 job
topk(10, cardinality_estimate{interval="30m0s", group_by_keys="job"})
```

**Шаг 2: Анализ лейблов**

```bash
# Найти высококардинальные метрики в vmagent
curl -s http://localhost:8429/metrics | grep -E "vmagent_scrape_.*_total" | head

# Проверить конфигурацию relabeling в vmagent
cat /etc/vmagent/scrape.yml | grep -A 20 relabel_configs
```

**Шаг 3: Корректирующие действия**

| Действие | Описание |
| :--- | :--- |
| **metric_relabel_configs** | Удалить high-cardinality лейбл на уровне vmagent |
| **Уменьшение interval** | Увеличить `scrape_interval` для проблемного job |
| **Aggregation** | Добавить recording rule для агрегации метрики |
| **limits** | Установить `series_limit` в vmagent для таргета |

**Шаг 4: Верификация**

```promql
# Проверить, что кардинальность снизилась
max(cardinality_estimate{group_by_keys="job", interval="30m0s"}) without(instance)
```

## 8. Поиск и устранение неисправностей

### Типичные ошибки и диагностика

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `vmestimator` не стартует | Ошибка в `streams.yaml` | `journalctl -u vmestimator` / `docker logs` | Проверить YAML-синтаксис, права на файл |
| Нет метрик на `/metrics` | Пустой входной поток | `curl http://localhost:8490/metrics` | Проверить, что vmagent отправляет данные |
| `cardinality_estimate` = 0 | Слишком короткий `interval` | Увеличить interval до `1h` для диагностики | Подобрать оптимальный interval |
| Высокое CPU (>100%) | Слишком много streams | `top -p <pid>` | Уменьшить количество `group_by` или увеличить interval |
| Высокое RAM (>512M) | Утечка или слишком много streams | `ps aux --sort=-%mem` | Перезапустить, оптимизировать streams |
| Данные не поступают в VM | Ошибка scraping у vmagent | Проверить config vmagent | Добавить/исправить job в vmagent |
| Неточные оценки (шум) | Интервал < 5m при переменной нагрузке | Сравнить оценки за разные интервалы | Увеличить interval до `15m` или `30m` |
| Отсутствует `churn` метрика | Используется Prometheus без MetricsQL | Проверить версию VictoriaMetrics | Использовать MetricsQL или пересчитать вручную |

### Диагностические команды

```bash
# Проверка статуса сервиса
systemctl status vmestimator
journalctl -u vmestimator --since "1 hour ago" --no-pager

# Проверка ресурсов
ps -p $(pgrep vmestimator) -o pid,%cpu,%mem,cmd
cat /proc/$(pgrep vmestimator)/limits | grep "open files"

# Проверка сокетов (если используется unix socket)
ss -tlnp | grep 8490
```

### Восстановление после сбоя

```bash
# Перезапуск с очисткой состояния
sudo systemctl restart vmestimator

# Проверка после перезапуска
sleep 5
curl -s http://localhost:8490/metrics | grep vmestimator_up
# Ожидается: vmestimator_up 1
```

## 9. Рекомендации по эксплуатации

### Resource Limits и планирование

vmestimator — легковесный компонент, но при высокой нагрузке его требования растут:

| Компонент | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **CPU** | 0.5–2 ядра | Обновление HyperLogLog-структур при каждом входящем сэмпле |
| **RAM** | 128–512 МБ | Зависит от количества streams и уникальных метрик |
| **Диск** | 1–5 ГБ | В основном WAL и логи; данные не накапливаются долгосрочно |
| **Порт** | 8490/tcp | Только для scrape; не требует публичного доступа |

### Ограничение потребления ресурсов

```bash
# systemd: ограничение CPU и памяти
[Service]
CPUQuota=50%
MemoryMax=256M
TasksMax=32
IOWeight=50
```

```yaml
# Docker: ограничение ресурсов
docker run -d \
  --cpus=0.5 \
  --memory=256m \
  --pids-limit=64 \
  --name vmestimator \
  ...
```

### Безопасность

- **Сеть:** vmestimator экспонирует только `/metrics` на порту `8490`. Размещайте его в защищенной сети (не публичный IP).
- **Аутентификация:** Используйте обратный прокси (nginx, vmauth) для базовой аутентификации или mTLS при необходимости.
- **Файлы:** `streams.yaml` может содержать чувствительные имена метрик. Ограничьте права: `chmod 640 streams.yaml`.

### Upgrade и обновление

```bash
# Проверка текущей версии
vmestimator -version

# Обновление Docker
docker pull docker.io/victoriametrics/vmestimator:latest
docker stop vmestimator && docker rm vmestimator
# Перезапуск с той же конфигурацией
docker run -d ... (те же флаги)
```

```bash
# Обновление бинарника
wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/latest/download/vmestimator-linux-amd64.tar.gz
tar -xzf vmestimator-linux-amd64.tar.gz
sudo systemctl stop vmestimator
sudo cp vmestimator /usr/local/bin/
sudo systemctl start vmestimator
```

### Очистка окружения

```bash
# Удаление Docker-контейнера и volumes
docker stop vmestimator && docker rm vmestimator
docker volume rm vmestimator-data

# Удаление systemd-сервиса
sudo systemctl stop vmestimator
sudo systemctl disable vmestimator
sudo rm /etc/systemd/system/vmestimator.service
sudo rm -rf /etc/vmestimator /var/lib/vmestimator
sudo userdel vmestimator
sudo systemctl daemon-reload
```

## 10. Интеграция с vmagent

vmestimator не требует изменений в конфигурации vmagent. Достаточно запустить vmestimator рядом с vmagent и настроить scraping метрик vmestimator через Prometheus или vmagent:

```yaml
# vmagent scrape config
scrape_configs:
  - job_name: 'vmestimator'
    static_configs:
      - targets: ['localhost:8490']
```

## 11. Часто задаваемые вопросы

**В: Нужен ли VictoriaMetrics для использования vmestimator?**
Нет. vmestimator может работать автономно и экспортировать метрики через HTTP. Однако VictoriaMetrics + vmalert + Grafana дают полный цикл: хранение, запросы, визуализацию и алертинг.

**В: Совместим ли vmestimator с Prometheus?**
Да. vmestimator экспортирует метрики в формате Prometheus text exposition и совместим с любым клиентом, поддерживающим remote write v1.

**В: Какова точность оценок?**
vmestimator использует вероятностные структуры данных (HyperLogLog) для оценки кардинальности с контролируемой погрешностью. Точность зависит от выбранного интервала и объёма данных.

**В: Чем vmestimator отличается от `promtool tsdb analyze`?**
`promtool tsdb analyze` — это офлайн-инструмент для анализа уже записанных данных на диске. vmestimator работает в реальном времени на этапе сбора и позволяет получать алерты до попадания данных в TSDB.

**В: Нужно ли изменять конфигурацию vmagent для работы vmestimator?**
Нет. vmestimator работает как независимый scraper рядом с vmagent. Достаточно настроить scrape job для `localhost:8490` в Prometheus или vmagent. Изменений в конфигурацию vmagent не требуется.

**В: Какой interval выбрать для production?**
Для production рекомендуется `interval: '15m'` или `'30m'`. Короткие интервалы (< 5m) дают зашумленные данные при переменной нагрузке. Длинные (> 1h) замедляют обнаружение всплесков.

**В: Что такое churn rate и когда его нужно мониторить?**
Churn rate — процент серий, которые «умерли» и были заменены новыми между двумя окнами оценки. Высокий churn (>10%) указывает на нестабильность источников метрик (например, динамические `instance` лейблы, частое перезапуск подов).

**В: Как откатить изменения streams.yaml?**
Сохраняйте предыдущую версию конфигурации в системе контроля версий. При проблемах выполните `git checkout streams.yaml` и перезапустите vmestimator: `systemctl restart vmestimator` или `docker restart vmestimator`.

## 12. Ограничения и особые случаи

### Точность оценок (HyperLogLog)

vmestimator использует вероятностные структуры данных HyperLogLog. Ключевые особенности:

| Параметр | Влияние на точность |
| :--- | :--- |
| **Интервал оценки** | Короткий interval (< 5m) даёт завышенную погрешность при переменной нагрузке |
| **Объём данных** | При < 10K уникальных серий оценка может быть неточной (относительная погрешность >10%) |
| **Группировка** | Оценки по `group_by` менее точны, чем глобальная (`__global__`) |

> **Практический совет:** Используйте `interval: '15m'` или `'30m'` для production. Для отладки можно использовать `'5m'`, но учитывайте повышенную шумность.

### WAL и диск

vmestimator хранит промежуточные состояния в WAL (Write-Ahead Log) для восстановления после сбоя:

| Аспект | Ограничение |
| :--- | :--- |
| **Размер WAL** | Зависит от количества streams; обычно < 100 МБ |
| **Восстановление** | При сбое vmestimator восстанавливает состояние за последний interval |
| **Ротация логов** | Настроите `logrotate` или используйте `docker logs --log-opt max-size` |

### Сеть и зависимость от vmagent

vmestimator — пассивный наблюдатель. Если vmagent не передаёт данные (сетевой разрыв, остановка vmagent), оценки замирают:

| Сценарий | Поведение vmestimator | Действие |
| :--- | :--- | :--- |
| **Сеть недоступна** | Оценки не обновляются; `cardinality_estimate` показывает последнее значение | Настроить алерт на застывание `cardinality_estimate` |
| **vmagent остановлен** | vmestimator работает, но входной поток = 0 | Мониторить процесс vmagent отдельно |
| **Накопление backlog** | vmestimator не буферизует данные; при возобновлении — gap в данных | Использовать persistent queue в vmagent |

### Ограничения версий

- **Community Edition:** Поддерживаются все базовые features (streams, alerting, dashboards).
- **Enterprise Edition:** Дополнительно доступны per-series retention filters и интеграция с VictoriaMetrics Enterprise features.
- **Совместимость:** vmestimator v0.x+ совместим с VictoriaMetrics v1.90+ и Prometheus 2.40+.

### Известные проблемы

1. **Cardinality Explorer не показывает историю vmestimator:** Данные доступны только через метрики, а не через VMUI Cardinality Explorer.
2. **Плагин Grafana не обновляется автоматически:** При обновлении vmestimator проверяйте версию дашбордов вручную.
3. **Windows не поддерживается:** vmestimator доступен только для Linux и macOS (amd64/arm64).

## 13. Дополнительная информация

- **Официальная документация:** [vmestimator docs](https://docs.victoriametrics.com/vmestimator/)
- **Репозиторий:** [github.com/VictoriaMetrics/vmestimator](https://github.com/VictoriaMetrics/vmestimator)
- **Примеры конфигураций и алертов:** в репозитории vmestimator в директории `deploy/`
- **Grafana Playground:** онлайновые дашборды и алерты доступны в VictoriaMetrics Grafana Playground (разделы `cardinality` и `cardinality.recording`).

Связанные компоненты:
- [VictoriaMetrics — обзор](./overview.md) — платформа хранения метрик;
- [vmalert — обзор](./vmalert_overview.md) — алертинг на основе метрик vmestimator;
- [vmagent](./vmagent_overview.md) — сбор и forwarding метрик;
- [Cardinality в Prometheus](../Prometheus/concepts/labels_and_cardinality.md) — фундаментальные концепции кардинальности;
- [Мониторинг и алертинг](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md) — методологии алертинга.

# force reindex test
