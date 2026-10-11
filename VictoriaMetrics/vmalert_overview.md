# Обзор vmalert

## 1. Определения

**vmalert** — это высокопроизводительный компонент стека [VictoriaMetrics](./overview.md), предназначенный для выполнения правил алертинга и правил записи (recording rules). Он является полноценной заменой встроенного механизма правил Prometheus, полностью совместим с его синтаксисом и предлагает расширенные возможности масштабирования и интеграции.

`vmalert` лёгкий, не имеет внешних зависимостей и запускается как отдельный бинарник или контейнер (`victoriametrics/vmalert`).

## 2. Базовые концепции

`vmalert` периодически выполняет выражения, объявленные в **правилах** (`-rule`), против источника данных, заданного через `-datasource.url`. По результатам выполнения он отправляет оповещения в [Alertmanager](../Prometheus/alertmanager.md) (флаг `-notifier.url`) или записывает новые (агрегированные) метрики обратно через Remote Write (флаг `-remoteWrite.url`).

### Поддерживаемые источники данных и типы правил

Язык выражения `expr` определяется полем `type` на уровне группы правил (глобальный дефолт задаётся флагом `-rule.defaultRuleType`):

| Тип | Язык запросов | Источник данных |
| :--- | :--- | :--- |
| `prometheus` (default) | PromQL / MetricsQL | VictoriaMetrics (single/cluster), Prometheus и другие Prometheus-совместимые хранилища |
| `vlogs` | LogsQL | логи [VictoriaLogs](https://docs.victoriametrics.com/victorialogs/), трейсы [VictoriaTraces](https://docs.victoriametrics.com/victoriatraces/) |
| `graphite` | Graphite | Graphite-совместимые хранилища |

`vmalert` работает только с одним `-datasource.url`. Для одновременного использования метрик и логов используется [vmauth](https://docs.victoriametrics.com/vmauth/) с маршрутизацией запросов по пути (`/api/v1/query*` → VictoriaMetrics, `/select/logsql/*` → VictoriaLogs/VictoriaTraces).

### Ключевые функции

- **Выполнение правил алертинга** — запрашивает данные из источника, оценивает условия и генерирует алерты. Поддерживает сложные условия благодаря MetricsQL/LogsQL.
- **Выполнение правил записи (recording rules)** — позволяет предварительно вычислять сложные запросы и сохранять их как новые метрики. Это критично для ускорения тяжёлых дашбордов в Grafana и для агрегации данных с высокой точностью из хранилища с коротким сроком хранения в долгосрочное хранилище.
- **Интеграция с VictoriaLogs и VictoriaTraces** — поддержка алертинга на основе логов (LogsQL, `type: vlogs`) с версии `v1.106.0` также работает с трейсами VictoriaTraces.
- **Сохранение состояния (Stateful Alerting)** — `vmalert` может сохранять состояние алертов (Pending/Firing) в удалённое хранилище через Remote Write. Это позволяет не терять историю алертов при перезапуске компонента.
- **Поддержка множества источников и нотификаторов** — может работать с несколькими источниками данных (через vmauth) и отправлять уведомления в несколько кластеров Alertmanager (несколько флагов `-notifier.url` или через конфигурационный файл).
- **Шаблонизация аннотаций** — расширенная поддержка Go-templates с дополнительными функциями (`now`, `query`, `label`, `humanize`, `toTime`, `parseDuration` и т. д.).
- **Relabeling** — поддержка переименования и фильтрации меток (labels) как для алертов перед отправкой, так и для записываемых метрик.
- **Hot reload** — обновление конфигурации без простоя через сигнал SIGHUP или HTTP-эндпоинт `/-/reload`.
- **Гибкая загрузка правил** — `-rule` принимает пути, wildcard-шаблоны, рекурсивные маски, HTTP URL; для Enterprise-версии дополнительно доступны S3 и GCS.
- **Валидация** — дубликаты правил (одинаковые `name` + `expr` + labels в одной группе) запрещены; проверка синтаксиса выполняется через `vmalert-tool`.

### Отличие от Alertmanager

Важно понимать различие в ролях:

| Компонент | Назначение | Пример |
| :--- | :--- | :--- |
| **`vmalert`** | **Генерирует** алерты (логика "когда бить тревогу"): выполняет запросы к БД, оценивает условия и формирует алерты | `IF rate(errors) > 5 THEN fire alert` |
| **`Alertmanager`** | **Обрабатывает** алерты (маршрутизация, дедупликация, группировка, нотификации) | Группировка 100 алертов в одно письмо в Slack |

`vmalert` — это "движок" выполнения логики, который делает запросы к БД, в то время как Alertmanager — система управления уведомлениями. Зоны ответственности не пересекаются.

### Ограничения

- Выполнение правил внутри группы происходит **последовательно** (по умолчанию `concurrency: 1`), но запись результатов в удалённое хранилище — **асинхронно**. Поэтому в рекурсивных сценариях, когда результат одного recording rule переиспользуется в следующем, полагаться на цепочку нельзя — используйте механизм **chaining groups** (группы с зависимостями) либо перестраивайте запросы.
- Выполнение запросов к источнику идёт по сети, поэтому существует риск сетевых сбоев — пороговые значения срабатываний следует проектировать с учётом возможных ошибок запросов.
- Для корректного backfilling правил с *кастомным* time filter (LogsQL) поддержка ещё не реализована.

## 3. Практические сценарии

### Пример конфигурации правил алертинга

Файл правил `alert-rules.yaml`:

```yaml
groups:
  - name: node-alerts
    interval: 30s  # Как часто выполнять правила
    rules:
      - alert: HighCpuUsage
        expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 5m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is above 85% for more than 5 minutes on {{ $labels.instance }}. Current value: {{ $value }}%"

      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is above 90% for more than 5 minutes. Current value: {{ $value }}%"

      - alert: DiskSpaceLow
        expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 10
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Low disk space on {{ $labels.instance }}"
          description: "Disk space is below 10% on {{ $labels.instance }}. Current value: {{ $value }}%"
```

> Примечание: для каждого правила в `expr` используется MetricsQL/PromQL, `for` задаёт минимальную длительность непрерывного отклонения для перехода в состояние Firing, а `annotations` поддерживают Go-шаблоны (`$labels`, `$value`, функции `printf`, `humanize`, `query` и др.).

### Пример алертинга на основе логов (VictoriaLogs)

Для правил на основе LogsQL на **уровне группы** обязательно указать `type: vlogs`, иначе выражение будет проверено как PromQL и не запустится. Правило срабатывает, когда в логах сервиса `auth` за 5 минут на одном поде появилось более 10 ошибок:

```yaml
groups:
  - name: log-alerts
    type: vlogs  # Обязательно для LogsQL
    interval: 1m
    rules:
      - alert: AuthServiceHighErrorRate
        expr: '{env=prod} status:in(error,warn) | stats by (k8s.pod.name) count() | filter count:>10'
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate in logs for {{ index $labels "k8s.pod.name" }}"
          description: "Found more than 10 errors in auth service logs within last 5 minutes."
```

В LogsQL-выражениях (`type: vlogs`) обязательно наличие `stats pipe` для агрегации и `filter pipe`, чтобы отфильтровать результат по порогу. По умолчанию `vmalert` сам добавляет ко времени фильтр `_time: <group_interval>` — указывать его в выражении не нужно (можно для переопределения). См. также [Alerting with Logs](https://docs.victoriametrics.com/victorialogs/vmalert/).

### Пример правил записи (recording rules)

Recording rules полезны для предварительного вычисления сложных запросов:

```yaml
groups:
  - name: rec
    interval: 1m
    rules:
      # Предварительный расчет среднего CPU usage по кластеру (MetricsQL)
      - record: cluster:node_cpu:avg_rate5m
        expr: avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
      # Расчет процента использования памяти
      - record: node:memory_usage_percent:ratio
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### Replay API: Пересчёт исторических данных

Уникальная функция `vmalert` — **backfilling (aka replay)**: позволяет выполнить правила на исторических данных. Это полезно, если вы создали новое правило записи и хотите заполнить историю метрики за прошлый месяц.

Запуск отдельного процесса пересчёта:

```bash
vmalert -rule=rules.yaml \
  -replay.timeFrom=2024-01-01T00:00:00Z \
  -replay.timeTo=2024-01-31T23:59:59Z \
  -datasource.url=http://victoriametrics:8428 \
  -remoteWrite.url=http://victoriametrics:8428
```

Ограничения backfill: не поддерживается для правил с кастомным time filter в LogsQL (и добавить её невозможно — см. выше), а также — при backfill правила, результат складывается с уже существующими данными.

### Пример запуска vmalert

#### Локальный запуск (с сохранением состояния)

```bash
vmalert \
  -datasource.url=http://localhost:8428 \
  -notifier.url=http://localhost:9093 \
  -remoteWrite.url=http://localhost:8428 \
  -remoteRead.url=http://localhost:8428 \
  -rule=/path/to/rules/*.yaml
```
*Флаг `-remoteWrite.url` включает сохранение состояния алертов в саму VictoriaMetrics.*

#### Деплой на bare-metal (systemd)

Для production-эксплуатации на физических серверах или VM без оркестратора:

```bash
# Создание пользователя и директорий
sudo useradd --system --no-create-home --shell /usr/sbin/nologin vmalert
sudo mkdir -p /etc/vmalert /var/lib/vmalert /var/log/vmalert
sudo chown -R vmalert:vmalert /etc/vmalert /var/lib/vmalert /var/log/vmalert
```

Скачайте бинарный файл:

```bash
VL_VERSION="v1.136.0"
wget -O /tmp/vmalert.tar.gz \
  "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VL_VERSION}/vmalert-${VL_VERSION}-linux-amd64.tar.gz"
sudo tar -xzf /tmp/vmalert.tar.gz -C /usr/local/bin/
sudo chmod +x /usr/local/bin/vmalert
```

Файл `/etc/systemd/system/vmalert.service`:

```ini
[Unit]
Description=VictoriaMetrics Alert
Documentation=https://docs.victoriametrics.com/vmalert/
After=network.target

[Service]
User=vmalert
Group=vmalert
Type=simple
ExecStart=/usr/local/bin/vmalert \
  -datasource.url=http://localhost:8428 \
  -notifier.url=http://localhost:9093 \
  -remoteWrite.url=http://localhost:8428 \
  -remoteRead.url=http://localhost:8428 \
  -rule=/etc/vmalert/rules/*.yaml \
  -httpListenAddr=:8880 \
  -loggerTimezone=UTC \
  -remoteWrite.maxQueueSize=10000 \
  -datasource.queryTimeout=1m
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

Активация и запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vmalert
sudo systemctl status vmalert
# → active (running)
```

Проверка:

```bash
# Проверка health endpoint
curl -s http://localhost:8880/-/healthy
# → OK

# Проверка правил
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups[].name'
# → "node-alerts"
```

#### Kubernetes (фрагмент Deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vmalert
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: vmalert
          # Рекомендуется использовать LTS версию или последнюю стабильную
          image: victoriametrics/vmalert:v1.136.0
          args:
            - -datasource.url=http://vmstorage.monitoring.svc:8428
            - -notifier.url=http://alertmanager.monitoring.svc:9093
            - -remoteWrite.url=http://vmstorage.monitoring.svc:8428
            - -remoteRead.url=http://vmstorage.monitoring.svc:8428
            - -rule=/config/rules/*.yaml
            - -httpListenAddr=:8080
            - -external.label=replica=$(POD_NAME)  # чтобы отличать инстансы при HA
          ports:
            - containerPort: 8080
              name: http
```

При запуске нескольких реплик `vmalert` (HA) каждому инстансу задаётся уникальный `-external.label` (например, `replica=instance-1`), чтобы логирование и отправка уведомлений не дублировались.

### Проверка состояния vmalert

`vmalert` запускает веб-сервер (по умолчанию на порту **`8880`**, переопределяется через `-httpListenAddr`) и интегрируется в основной `vmui`:

- `/api/v1/rules` — список групп правил и их состояние.
- `/api/v1/alerts` — список активных алертов с текущим статусом (Firing/Pending) и метками.
- `/vmalert/rule` и `/vmalert/alert` — страницы правил и алертов в веб-UI.
- `/metrics` — внутренние метрики компонента (формат Prometheus).
- `/-/reload` — «горячее» обновление конфигурации без рестарта.

### Сохранение и восстановление состояния алертов

Каждый процесс `vmalert` хранит состояние алертов в памяти. Для восстановления при рестарте используются два флага:

- `-remoteWrite.url` — URL, куда сохраняется состояние в виде временных серий `ALERTS` и `ALERTS_FOR_STATE` через Remote Write;
- `-remoteRead.url` — URL (MetricsQL-совместимый, VictoriaMetrics или vmselect), откуда при старте восстанавливается состояние по серии `ALERTS_FOR_STATE`.

Восстановление происходит **только один раз при старте** (не при hot reload). Если серии отсутствуют, не обновлялись дольше `-remoteRead.lookback` (по умолчанию 1 час) или не соответствуют текущей конфигурации правил — восстановление не выполнится. Успешно восстановленные правила помечаются меткой `restored` в веб-UI.

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Правила не выполняются | Неверный путь или права доступа | Проверить `-rule`-параметр и логи контейнера |
| Алерты пропадают после рестарта | Не настроен Remote Write | Добавить флаг `-remoteWrite.url` (+ `-remoteRead.url`) |
| "Failed to execute request" (на старте/в логах) | Тайм-аут источника данных | Увеличить `-datasource.queryTimeout` или оптимизировать запрос |
| Восстановление состояния не сработало | Серия `ALERTS_FOR_STATE` устарела на >1 час | Настроить `-remoteRead.lookback` |
| Ошибки синтаксиса | Ошибка в YAML или MetricsQL/LogsQL | Запустить `vmalert-tool check` и unit-testing (`vmalert-tool test`) |
| Горячая перезагрузка не работает | Отсутствует флаг `-web.enable-lifecycle` или `/-/reload` возвращает 404 | Добавить флаг запуска или проверить служебный порт |
| Дубли алертов при нескольких репликах | Не задан уникальный `-external.label` для каждого инстанса | Задать уникальный label (например, `replica=$(HOSTNAME)`) |
| Запросы зависают / высокий CPU | Слишком сложный MetricsQL/LogsQL запрос или низкий `-search.maxQueryDuration` | Оптимизировать запрос, увеличить timeout, ограничить `-search.maxQueries` |

## 4. Требования к окружению

### Операционная система

`vmalert` доступен для Linux (amd64, arm64) и macOS (amd64). Для production эксплуатации рекомендуется Linux-based ОС с актуальным LTS-ядром.

### Аппаратные требования

| Сценарий | CPU | RAM | Диск | Сеть |
| :--- | :--- | :--- | :--- | :--- |
| **Малая нагрузка** (< 5000 активных алертов, < 50 recording rules) | 2 ядра | 2 GB | 20 GB SSD | 10 MB/s |
| **Средняя нагрузка** (5K–50K алертов, 50–500 recording rules) | 4–8 ядер | 4–8 GB | 50 GB SSD | 50 MB/s |
| **Высокая нагрузка** (> 50K алертов, сложный MetricsQL) | 8+ ядер | 8+ GB | 100+ GB SSD | 100+ MB/s |

### Программные зависимости

- Для запуска бинарного файла: никаких внешних зависимостей не требуется.
- Для контейнеризации: Docker, Podman или containerd.
- Для интеграции с Alertmanager: работающий инстанс Alertmanager (порт `9093`).
- Для хранения состояния: VictoriaMetrics (single/cluster) с поддержкой Remote Write/Read.

### Сетевые порты

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `8880` | HTTP | Веб-UI, `/api/v1/rules`, `/api/v1/alerts`, `/-/reload` |
| `9093` | HTTP | Alertmanager (внешний) |
| `8428` | HTTP | VictoriaMetrics (datasource, remote write/read) |

### Хранение

- **Тип диска:** SSD или NVMe рекомендуется для production.
- **Размер:** Зависит от количества правил и интервала оценки. Состояние алертов (`ALERTS_FOR_STATE`) хранится в VictoriaMetrics, поэтому учтите её retention.
- **Разделы:** Данные состояния алертов organizуются как временные ряды в VictoriaMetrics; управление retention происходит на стороне хранилища.

## 5. Валидация установки

### Health checks

```bash
# Проверка доступности HTTP-эндпоинта
curl -s http://localhost:8880/-/healthy
# → OK

# Проверка readiness
curl -s http://localhost:8880/-/ready
# → OK

# Проверка метрик самомониторинга
curl -s http://localhost:8880/metrics | grep vmalert_up
# → vmalert_up 1
```

### Верификация данных

```bash
# Проверить, что правила загружены
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups[].rules[] | .name'
# → "HighCpuUsage"
# → "HighMemoryUsage"

# Проверить, что запросы выполняются (в логах)
journalctl -u vmalert -f | grep "successfully evaluated rule group"
# → ... successfully evaluated rule group "node-alerts" ...
```

### Диагностика типичных проблем

| Симптом | Диагностика | Решение |
| :--- | :--- | :--- |
| `/-/healthy` возвращает 503 | Источник данных недоступен | Проверить `-datasource.url` и доступность VictoriaMetrics/Prometheus |
| Правила не загружаются | Неверный glob в `-rule` или права | `ls /etc/vmalert/rules/*.yaml`, проверить права |
| Метрики `vmalert_up` = 0 | Процесс упал | `journalctl -u vmalert`, проверить `LimitNOFILE` и OOM |
| Нет алертов в `/api/v1/alerts` | Условия не выполняются или `for` не истёк | Снизить порог временно или уменьшить `for` |
| Запросы к источнику зависают | Сетевой файрвол или timeout | Увеличить `-datasource.queryTimeout` |

## 6. Resource Limits и тюнинг производительности

### Ограничение ресурсов через systemd

```ini
# /etc/systemd/system/vmalert.service
[Service]
# Ограничение памяти (например, 4 GB)
MemoryMax=4G
MemoryHigh=3G

# Ограничение CPU (например, 4 ядра)
CPUQuota=400%

# Ограничение числа открытых файлов
LimitNOFILE=65535

# Защита от OOM
OOMScoreAdjust=-500
```

### Ограничение через Docker

```bash
docker run -d --name vmalert \
  --memory=4g \
  --cpus=4 \
  --ulimit nofile=65535:65535 \
  -p 8880:8880 \
  victoriametrics/vmalert:v1.136.0 \
  -datasource.url=http://victoriametrics:8428 \
  -notifier.url=http://alertmanager:9093 \
  -remoteWrite.url=http://victoriametrics:8428 \
  -remoteRead.url=http://victoriametrics:8428 \
  -rule=/rules/*.yaml
```

### Ключевые флаги производительности

| Флаг | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-datasource.queryTimeout` | Таймаут запросов к источнику | `30s`–`1m` для сложных запросов |
| `-remoteWrite.maxQueueSize` | Размер очереди Remote Write | `10000` (по умолчанию) |
| `-remoteWrite.maxBatchSize` | Размер батча для Remote Write | `1000`–`5000` |
| `-httpListenAddr` | Адрес HTTP-сервера | `:8880` (изменить при конфликте) |
| `-loggerTimezone` | Часовой пояс логов | `UTC` для корреляции |
| `-evaluationInterval` (в группе) | Частота оценки правил | Не менее `10s`; для логов `1m`–`5m` |

### Рекомендации по нагрузке

- **Снизьте частоту оценки (`interval`) для LogsQL-правил:** запросы к логам ресурсоёмкие. Используйте `interval: 1m`–`5m` вместо `10s`.
- **Ограничьте количество правил в одной группе:** при >100 rules в группе evaluation time может превысить `interval`.
- **Используйте recording rules** для предварительного вычисления сложных MetricsQL-запросов, которые используются в нескольких alert rules.

## 7. Безопасность и управление доступом

### Аутентификация и авторизация

`vmalert` не имеет встроенной аутентификации. Для защиты веб-интерфейса и API используйте один из подходов:

1. **vmauth** — прокси входит в стек VictoriaMetrics, поддерживает Basic Auth, JWT, OIDC и ACL по путям запроса.
2. **Обратный прокси (Nginx/Traefik)** — TLS-терминация и Basic Auth перед `vmalert`.
3. **Firewall** — ограничьте доступ к порту `8880` только адресам систем мониторинга и bastion-хостам.

Пример Nginx-конфигурации:

```nginx
server {
    listen 8443 ssl;
    server_name vmalert.internal;

    ssl_certificate     /etc/nginx/tls/vmalert.crt;
    ssl_certificate_key /etc/nginx/tls/vmalert.key;

    location / {
        auth_basic "VictoriaMetrics Alert";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8880;
        proxy_set_header Host $host;
    }
}
```

### Шифрование трафика

- **Источник данных (`-datasource.url`):** используйте `https://` и настройте доверенные сертификаты. Для самоподписанных сертификатов используйте флаг `-datasource.tlsInsecureSkipVerify` (только для тестовых сред).
- **Remote Write/Read:** по умолчанию поддерживает TLS при использовании `https://` URL.
- **Alertmanager (`-notifier.url`):** если Alertmanager имеет TLS, используйте `https://` и соответствующие флаги.

### Аудит

Включите аудит запросов к источнику данных через логи VictoriaMetrics/vmselect. Для самомониторинга `vmalert` добавьте алерты на метрики:

```yaml
groups:
  - name: vmalert-self-monitoring
    rules:
      - alert: VmalertDown
        expr: up{job="vmalert"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "vmalert {{ $labels.instance }} недоступен"

      - alert: VmalertQueryErrors
        expr: rate(vmalert_queries_failed_total[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Ошибки запросов в vmalert {{ $labels.instance }}"
```

## 8. Процедура обновления и отката

### Обновление бинарного файла (bare-metal)

```bash
# 1. Остановка сервиса
sudo systemctl stop vmalert

# 2. Бэкап конфигурации
sudo cp -r /etc/vmalert /etc/vmalert.bak.$(date +%Y%m%d)

# 3. Загрузка новой версии
VL_NEW="v1.136.0"
wget -O /tmp/vmalert.tar.gz \
  "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VL_NEW}/vmalert-${VL_NEW}-linux-amd64.tar.gz"
sudo tar -xzf /tmp/vmalert.tar.gz -C /usr/local/bin/

# 4. Валидация конфигурации (не запуская vmalert)
vmalert-tool check /etc/vmalert/rules/*.yaml
# → SUCCESS

# 5. Запуск
sudo systemctl start vmalert
sudo systemctl status vmalert
# → active (running)

# 6. Проверка правил
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups[].name'
```

### Откат

При проблемах с новой версией:

```bash
# 1. Остановка
sudo systemctl stop vmalert

# 2. Возврат предыдущей версии (если сохранили бин)
sudo cp /usr/local/bin/vmalert /usr/local/bin/vmalert.new
sudo cp /path/to/previous/vmalert /usr/local/bin/vmalert

# 3. Или восстановление конфигурации
sudo rm -rf /etc/vmalert
sudo cp -r /etc/vmalert.bak.20260920 /etc/vmalert

# 4. Запуск
sudo systemctl start vmalert
```

### Обновление в Docker

```bash
# 1. Остановка старого контейнера
docker stop vmalert && docker rm vmalert

# 2. Загрузка нового образа
docker pull victoriametrics/vmalert:v1.136.0

# 3. Запуск с той же конфигурацией
docker run -d --name vmalert \
  -p 8880:8880 \
  -v /etc/vmalert/rules:/rules \
  victoriametrics/vmalert:v1.136.0 \
  -datasource.url=http://victoriametrics:8428 \
  -notifier.url=http://alertmanager:9093 \
  -remoteWrite.url=http://victoriametrics:8428 \
  -remoteRead.url=http://victoriametrics:8428 \
  -rule=/rules/*.yaml
```

### Проверка после обновления

```bash
# Проверка версии через UI/API
curl -s http://localhost:8880/metrics | grep vmalert_build_info
# → vmalert_build_info{version="v1.136.0",...} 1

# Проверка загрузки правил
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups | length'
# → 3

# Проверка active alerts
curl -s http://localhost:8880/api/v1/alerts | jq '.data.alerts | length'
# → 0
```

## 9. Ограничения и особые случаи

### Точность и кардинальность

- **Sequential evaluation:** правила внутри одной группы выполняются последовательно (`concurrency: 1`). При большом количестве правил (`>50`) в группе время evaluation может превысить `interval`, что приведёт к накоплению отставания.
- **Chaining не гарантирует порядок:** результат recording rule может быть не готов к моменту оценки следующего правила в той же группе. Используйте chaining groups с зависимостями.

### Сеть и отказоустойчивость

- При недоступности источника данных (`-datasource.url`) `vmalert` логирует ошибку, но продолжает работу с другими правилами. Нет circuit breaker — планируйте `for` и пороги с учётом возможных пропусков.
- При потере connectivity с Alertmanager алерты генерируются, но не доставляются. Проверяйте `alertmanager_notifications_failed_total` (если Alertmanager доступен) или логи `vmalert`.

### State Recovery

- Восстановление состояния выполняется **один раз при старте**. При hot reload (`SIGHUP` или `/-/reload`) состояние не восстанавливается.
- Если конфигурация правил изменилась (удалены/добавлены правила), восстановление для удалённых правил не произойдёт — `ALERTS_FOR_STATE` серии будут игнорированы.

### Версионные особенности

- Поддержка `type: vlogs` появилась в `v1.106.0`.
- Enterprise-функции (`-clusterMode`, S3/GCS rules) требуют лицензии.
- Replay API не поддерживает LogsQL с кастомным time filter.

### Известные проблемы

- При использовании `for` с большим значением (`>10m`) и высокой `interval` группам требуется больше времени для перехода в Firing при срабатывании.
- При рестарте `vmalert` без `-remoteRead.url` все алерты переходят в состояние Pending заново.

## 10. FAQ

**Q: Какой `interval` выбрать для правил алертинга?**
A: Для метрик infrastructure (`node_cpu`, `node_memory`) используйте `30s`. Для бизнес-метрик и логов — `1m`–`5m`. Чем ниже interval, тем выше нагрузка на источник данных и `vmalert`.

**Q: Нужно ли использовать recording rules для простых запросов?**
A: Нет. Recording rules целесообразны для сложных aggregations (`rate()`, `histogram_quantile`), которые переиспользуются в 3+ алертах или дэшбордах.

**Q: Что происходит при перезапуске Alertmanager?**
A: `vmalert` повторно отправит алерты в новый инстанс Alertmanager. Для подавления дублей используйте `-external.label` и настройте Alertmanager на дедупликацию.

**Q: Как откатить изменение правила без перезапуска?**
A: Используйте `/-/reload` после отката файла правил. При использовании Kubernetes/VMRule оператор применит изменения автоматически.

**Q: Можно ли использовать один `vmalert` и для метрик, и для логов?**
A: Да, через [vmauth](https://docs.victoriametrics.com/vmauth/) с маршрутизацией по пути запроса. Альтернатива — запуск отдельных инстансов `vmalert` под каждый тип правил.

**Q: Где хранится состояние алертов?**
A: В памяти процесса. Для персистентности используйте `-remoteWrite.url` (сохранение) и `-remoteRead.url` (восстановление).

**Q: Как мониторить сам `vmalert`?**
A: Используйте эндпоинт `/metrics` и добавьте в VictoriaMetrics алерты на `up{job="vmalert"}`, `vmalert_queries_failed_total`, `vmalert_rule_group_last_duration_seconds`.

**Q: Что такое vmalert-tool и зачем он нужен?**
A: Это CLI-утилита для валидации YAML-конфигурации и unit-тестирования правил на синтетических данных. Обязательна для CI/CD пайплайнов.

**Q: Поддерживает ли `vmalert` multi-tenancy?**
A: В Enterprise-версии да (`-clusterMode=true` + поле `tenant` в правилах). В Community — нет встроенного механизма, используйте отдельные инстансы `vmalert` с разными `-datasource.url`.

## 11. Отладка и устранение неполадок

### Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Правила не отображаются в UI | `-rule` указывает на неверный путь | Проверить `ls /etc/vmalert/rules/*.yaml` и права доступа |
| Ошибка в MetricsQL/LogsQL | Синтаксическая ошибка или неверный `type` группы | Убедиться в `type: vlogs` для LogsQL; запустить `vmalert-tool check` |
| LogsQL-правило молчит | Пропущен `stats`-пайп или `filter`-пайп в `expr` | Добавить обязательные пайпы; проверить time filter |
| Запрос зависает | Слишком сложный запрос или таймаут | Увеличить `-datasource.queryTimeout` или упростить expr |
| Восстановление состояния не сработало | Серия `ALERTS_FOR_STATE` устарела | Настроить `-remoteRead.lookback` (по умолчанию 1h) |
| Дубли уведомлений | Несколько реплик без `-external.label` | Задать уникальный label для каждого инстанса |
| `/-/reload` возвращает 404 | Отсутствует `-web.enable-lifecycle` | Добавить флаг в аргументы запуска |
| Алерты не доставляются в Alertmanager | Alertmanager недоступен или неверный URL | Проверить `-notifier.url` и доступность Alertmanager |

### Диагностические команды

```bash
# Проверка статуса сервиса (systemd)
sudo systemctl status vmalert
journalctl -u vmalert -n 100 --no-pager

# Проверка ресурсов
ps aux | grep vmalert
cat /proc/$(pgrep -f vmalert)/limits | grep "open files"
# → Max open files            65535                65535                files

# Проверка диска
df -h /var/lib/vmalert

# Проверка загрузки правил
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups[].name'

# Проверка active alerts
curl -s http://localhost:8880/api/v1/alerts | jq '.data.alerts[] | {name: .labels.alertname, status: .status}'

# Валидация всех правил
vmalert-tool check /etc/vmalert/rules/*.yaml

# Unit-тестирование правил (синтетические данные)
vmalert-tool test -rule=/etc/vmalert/rules/*.yaml

# Проверка Remote Write/Read connectivity
curl -s http://localhost:8880/metrics | grep -E "vmalert_remote_write|vmalert_remote_read"
```

### Восстановление после сбоя

```bash
# Перезапуск с очисткой in-memory состояния (если восстановление не требуется)
sudo systemctl restart vmalert

# Проверка после перезапуска
sleep 5
curl -s http://localhost:8880/-/healthy
# → OK

curl -s http://localhost:8880/api/v1/rules | jq '.data.groups | length'
# → количество загруженных групп
```

## 12. Рекомендации по эксплуатации

### Resource Limits и планирование

- **Memory:** выделяйте не менее 4 GB RAM для средних нагрузок. При >100K правил рассмотрите 8+ GB.
- **CPU:** vmalert CPU-bound при сложных MetricsQL запросах. Мониторьте `vmalert_rule_group_last_duration_seconds` и сравнивайте с `interval`.
- **Диск:** для state persistence нужен минимальный объём, так как состояние хранится в VictoriaMetrics. Однако логи `vmalert` могут занимать десятки MB в день — настройте ротацию через `logrotate`.

### Безопасность

- Никогда не открывайте порт `8880` в интернет без reverse proxy с аутентификацией.
- Используйте TLS для соединений с источником данных и Alertmanager.
- Ограничьте `-datasource.url` минимально необходимыми правами (read-only для источников).
- Регулярно обновляйте `vmalert` до последних патчей безопасности (LTS-версии).

### Процедура обновления

1. Остановка сервиса.
2. Бэкап конфигурации и данных (`/etc/vmalert`, `-remoteWrite.url`).
3. Обновление бинарного файла или образа.
4. Валидация конфигурации через `vmalert-tool check`.
5. Запуск и проверка `/-/healthy`, `/api/v1/rules`.
6. Мониторинг в течение 15–30 минут (проверка `vmalert_queries_failed_total`, `vmalert_rule_group_last_duration_seconds`).

### Очистка и обслуживание

- **Ротация логов:** настройте `logrotate` для `/var/log/vmalert/*.log` (если используется файловый логгер).
- **Очистка старых правил:** удаляйте неиспользуемые `VMRule`/YAML-файлы, чтобы не засорять конфигурацию.
- **Аудит recording rules:** периодически проверяйте, какие pre-computed метрики используются. Удаляйте неиспользуемые, чтобы снизить нагрузку на источник данных.

## 13. Дополнительная информация

- **VMUI (Alerting Tab):** современный способ визуализации алертов `vmalert` доступен напрямую в UI VictoriaMetrics.
- **vmalert-tool:** утилита для валидации синтаксиса и модульного тестирования правил (unit testing: `vmalert-tool check` / `vmalert-tool test`) — рекомендуется добавить в CI/CD перед деплоем.
- **vmauth:** позволяет направлять запросы vmalert на разные хранилища (метрики/логи/трейсы) по пути запроса (`/api/v1/query*` vs `/select/logsql/*`), интегрируя единый доступ. Подробнее — [vmauth](./vmauth_overview.md).

Официальная документация: [vmalert docs](https://docs.victoriametrics.com/vmalert/), [Troubleshooting vmalert](https://docs.victoriametrics.com/vmalert/#troubleshooting), [Alerting with VictoriaLogs](https://docs.victoriametrics.com/victorialogs/vmalert/).

Связанные компоненты: [VictoriaMetrics](./overview.md), [Управление правилами vmalert в Kubernetes](./vmalert_rules_management_with_manifests.md), [MetricsQL](./metricsql_reference.md), [Alertmanager](../Prometheus/alertmanager.md).

# force reindex test
