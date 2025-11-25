# Руководство по Prometheus Pushgateway

**Pushgateway** — это компонент-посредник в экосистеме Prometheus, предназначенный для сбора метрик от короткоживущих или периодических задач (`batch jobs`, `cron`), которые не могут быть эффективно опрошены (scraped) самим Prometheus по его стандартной pull-модели.

## 1. Установка Pushgateway

Процесс установки аналогичен установке Prometheus.

### Шаг 1: Создание пользователя

```bash
useradd pushgateway --comment "Pushgateway server user" --shell /bin/false 
```

### Шаг 2: Загрузка и установка

Скачиваем архив с последней версией Pushgateway. В примере используется `v1.4.0`.

```bash
cd /tmp
wget https://github.com/prometheus/pushgateway/releases/download/v1.4.0/pushgateway-1.4.0.linux-amd64.tar.gz
tar xvfz pushgateway-1.4.0.linux-amd64.tar.gz
cd pushgateway-1.4.0.linux-amd64
mv pushgateway /usr/local/bin/
```
Актуальные версии можно найти на [странице релизов](https://github.com/prometheus/pushgateway/releases).

### Шаг 3: Настройка опций запуска

Pushgateway настраивается через флаги командной строки. Вынесем их в отдельный файл для удобства.

```bash
cat <<EOF > /etc/sysconfig/pushgateway
OPTIONS="--web.listen-address=:9091 \
    --web.telemetry-path=/metrics \
    --persistence.file=/tmp/metric.store \
    --persistence.interval=5m \
    --log.level=info"
EOF
```

### Шаг 4: Создание systemd-сервиса

```bash
cat <<EOF > /usr/lib/systemd/system/pushgateway.service 
[Unit]
Description=Prometheus Pushgateway
Documentation=https://github.com/prometheus/pushgateway

[Service]
User=pushgateway
Group=pushgateway
EnvironmentFile=/etc/sysconfig/pushgateway
Restart=always
ExecStart=/usr/local/bin/pushgateway $OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
TimeoutStopSec=20s
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
EOF
```

### Шаг 5: Запуск и проверка

```bash
systemctl daemon-reload
systemctl start pushgateway
systemctl enable pushgateway

# Проверяем доступность
curl -XGET -IL http://localhost:9091
```
Ответ должен быть `HTTP/1.1 200 OK`.

## 2. Ключи запуска Pushgateway

| Флаг | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--web.listen-address` | `:9091` | Адрес и порт, который будет слушать Pushgateway. |
| `--web.telemetry-path` | `/metrics` | Путь, по которому доступны собственные метрики Pushgateway. |
| `--persistence.file` | `-` | Файл для сохранения состояния метрик между перезапусками. По умолчанию метрики хранятся только в памяти. |
| `--persistence.interval` | `5m` | Интервал сохранения данных в файл. |
| `--web.enable-admin-api` | `false` | Разрешает использование административных эндпоинтов (например, для очистки всех метрик). |
| `--log.level` | `info` | Уровень логирования (`debug`, `info`, `warn`, `error`). |

## 3. Взаимодействие с Pushgateway API

Взаимодействие происходит по HTTP API. Все метрики группируются на основе URL, в который они были отправлены.

### Структура URL

`/metrics/job/<JOB_NAME>{/<LABEL_NAME>/<LABEL_VALUE>}`

*   `<JOB_NAME>`: Обязательная часть. Используется как значение для метки `job`.
*   `/<LABEL_NAME>/<LABEL_VALUE>`: Пары меток для группировки. Их может быть сколько угодно.

**Пример:** метрика `my_metric{job="batch", instance="host1"}` будет отправлена по URL:
`/metrics/job/batch/instance/host1`

> **Важно:** Если значение метки содержит спецсимволы (например, `/`), его необходимо закодировать в **base64** и добавить к имени метки `@base64`.
> Пример для `path="/var/log"`: `/metrics/job/my_job/path@base64/L3Zhci9sb2c=`

### Методы API

*   `POST`: **Добавляет или обновляет** метрики в указанной группе. Существующие в группе метрики, которых нет в теле запроса, остаются без изменений. Если запрос выполняется с пустым телом, метрика `push_times_seconds` обновляется, но ранее переданные метрики не изменяются.
*   `PUT`: **Полностью заменяет** все метрики в группе на те, что переданы в теле запроса. Если запрос выполняется с пустым телом, это приводит к удалению всех метрик для данной группы. При этом метрика `push_times_seconds` не обновляется.
*   `DELETE`: **Удаляет всю группу** метрик, идентифицируемую по URL.

### Практический пример: отправка метрик

Отправим две метрики (counter и gauge) в Pushgateway.

```bash
cat <<EOF | curl --data-binary @- http://127.0.0.1:9091/metrics/job/my_batch_job/instance/server1
# TYPE my_batch_duration_seconds gauge
my_batch_duration_seconds 34.4
# TYPE my_batch_records_processed_total counter
my_batch_records_processed_total 1024
EOF
```

Теперь, если проверить метрики самого Pushgateway (`curl http://localhost:9091/metrics`), вы увидите не только отправленные вами метрики, но и служебные:
*   `push_time_seconds`: Время последнего успешного `POST` или `PUT` запроса для группы.
*   `push_failure_time_seconds`: Время последнего неудачного запроса.

## 4. Настройка Prometheus для сбора метрик из Pushgateway

Настройка сбора метрик с Pushgateway ничем не отличается от настройки сбора с любого другого экспортера.

Добавьте в `prometheus.yml` новую `job`:

```yaml
# /etc/prometheus/prometheus.yml

scrape_configs:
  - job_name: 'pushgateway'
    # honor_labels: true говорит Prometheus не перезаписывать метки job и instance, 
    # которые уже были установлены при отправке в Pushgateway.
    honor_labels: true 
    static_configs:
      - targets: ['localhost:9091']
```

После перезагрузки конфигурации Prometheus (`systemctl reload prometheus`) он начнет собирать метрики, которые хранятся в Pushgateway.

---
**Связанные темы:**
*   [[./overview.md]]
*   [[./concepts/metrics_collection_strategies.md]]
