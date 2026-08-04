# Централизованное логирование Docker: Лог-драйверы

## Определения

**Лог-драйвер (Logging Driver)** — это встроенный в Docker Engine механизм, который перехватывает потоки `STDOUT` и `STDERR` контейнера и перенаправляет их в указанное место назначения: локальный файл, системный журнал (Journald, Syslog) или сетевой эндпоинт (Loki, GELF, Fluentd).

**Централизованное логирование** — архитектурный паттерн, при котором логи со всех узлов инфраструктуры собираются в единое хранилище для обеспечения наблюдаемости (Observability), упрощения отладки и проведения аудита безопасности.

## Базовые концепции

При использовании лог-драйверов Docker Engine берет на себя роль транспортного агента. Это избавляет от необходимости запускать сторонние процессы для сбора логов, но перекладывает нагрузку по сетевой передаче на Docker daemon.

**Схема работы:**
`Приложение → STDOUT/STDERR → Docker Engine (Log Driver) → Сеть/Сокет → Приемник (Loki, Graylog, Splunk)`

### Режим работы: Blocking vs Non-blocking

По умолчанию большинство сетевых драйверов работают в **блокирующем (blocking)** режиме.
*   **Blocking**: Docker ждет подтверждения от приемника о получении лога. Если сеть нестабильна или приемник перегружен, Docker daemon приостанавливает (freezes) контейнер, чтобы не потерять данные. Это может привести к каскадным сбоям приложения.
*   **Non-blocking**: Docker пишет логи в промежуточный кольцевой буфер в оперативной памяти хоста.
    *   **Механизм**: Если буфер заполняется (например, при обрыве связи с Loki), новые входящие логи начинают вытеснять самые старые записи в буфере (принцип FIFO).
    *   **Преимущество**: Стабильность приложения гарантирована, даже если система логирования полностью недоступна.

### Механизм Dual Logging

Начиная с Docker 20.10, сетевые драйверы по умолчанию работают в режиме **Dual Logging**. Это решает проблему "слепой зоны", когда при использовании удаленного драйвера команда `docker logs` переставала работать.
*   **Суть**: Логи пишутся параллельно во внешний драйвер и в локальный бинарный кэш (драйвер `local`).
*   **Контроль**: Локальный кэш автоматически ротируется и не занимает много места.

## Практические сценарии

### Глобальная настройка стабильности (`daemon.json`)

Для продакшена рекомендуется всегда использовать неблокирующий режим с адекватным размером буфера.

**Пример в `/etc/docker/daemon.json`:**
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "mode": "non-blocking",
    "max-buffer-size": "4m"
  }
}
```
*   `max-buffer-size`: 4 МБ буфера обычно достаточно для компенсации кратковременных сетевых задержек без риска исчерпания RAM.

### Сценарий 1: Драйвер Journald (Интеграция с ОС)

Предпочтителен для систем на базе systemd, так как позволяет использовать `journalctl` для анализа инфраструктуры.

**Параметры запуска:**
```bash
docker run -d \
  --log-driver=journald \
  --log-opt tag="{{.Name}}/{{.ID}}" \
  nginx
```
**Важно (Тюнинг rsyslog/journald):**
Если на хосте стоит `rsyslog`, он может дублировать логи контейнеров в `/var/log/syslog`. Чтобы этого избежать, настройте фильтрацию или отключите `ForwardToSyslog=yes` в `/etc/systemd/journald.conf`.

### Сценарий 2: Драйвер GELF (Graylog / Logstash)

Протокол GELF позволяет передавать структурированные данные и поддерживает сжатие.

**Конфигурация в Docker Compose:**
```yaml
services:
  api:
    image: my-api:latest
    logging:
      driver: gelf
      options:
        gelf-address: "udp://graylog-server:12201"
        gelf-compression-type: "gzip"
        gelf-compression-level: "2"
        tag: "api-prod"
```
*   `gelf-address`: Поддерживает `udp` и `tcp`. UDP рекомендуется для минимизации задержек.

### Сценарий 3: Драйвер Fluentd (Маршрутизация логов)

Используется, когда Docker должен отправить логи в сложную цепочку обработки.

**Конфигурация Docker:**
```bash
docker run -d \
  --log-driver=fluentd \
  --log-opt fluentd-address=localhost:24224 \
  --log-opt fluentd-async-connect=true \
  --log-opt tag="docker.{{.Name}}" \
  my-app
```
**Пример `fluent.conf` (Прием и склейка Multiline):**
```conf
<source>
  @type forward
  port 24224
  bind 0.0.0.0
</source>

# Склеивание Java Stack Traces
<filter docker.**>
  @type concat
  key log
  multiline_start_regexp /^\d{4}-\d{2}-\d{2}/
  flush_interval 3s
</filter>

<match docker.**>
  @type stdout
</match>
```

### Сценарий 4: Драйвер AWS Logs (Cloud Native)

Используется для прямой отправки логов в CloudWatch при запуске в AWS (EC2, Fargate).

**Параметры:**
```bash
docker run -d \
  --log-driver=awslogs \
  --log-opt awslogs-region=us-east-1 \
  --log-opt awslogs-group=my-app-logs \
  --log-opt awslogs-stream=web-server-01 \
  --log-opt awslogs-create-group=true \
  nginx
```
*   Требует настроенных IAM-прав (Policy `logs:CreateLogStream`, `logs:PutLogEvents`) на уровне инстанса.

### Сценарий 5: Драйвер Splunk

Для интеграции с корпоративной SIEM Splunk через HTTP Event Collector (HEC).

**Параметры:**
```bash
docker run -d \
  --log-driver=splunk \
  --log-opt splunk-url=https://splunk.example.com:8088 \
  --log-opt splunk-token=12345-abcde \
  --log-opt splunk-insecureskipverify=true \
  --log-opt splunk-format=json \
  nginx
```

## Дополнительная информация

### Выбор метода: Драйвер или Агент?

| Параметр | Лог-драйверы | Агенты (Vector/Alloy) |
| :--- | :--- | :--- |
| **Отказоустойчивость** | Низкая (буфер только в RAM). | Высокая (буфер на диске). |
| **Трансформация** | Почти отсутствует. | Полноценный ETL (парсинг, маскирование). |
| **Нагрузка** | На Docker Engine. | На отдельный процесс (агент). |

**Рекомендация:** Используйте лог-драйверы для быстрой интеграции в облачных средах (AWS/GCP) или при малых нагрузках. Для высоконагруженных систем с требованиями к сохранности данных (compliance) переходите на **[Агентный сбор логов Docker](./docker_agent_based_logging.md)**.

### Ссылки на смежные темы
*   **[Обзор системы логирования в Docker](./docker_logging_drivers_overview.md)** — база и сравнение методов.
*   **[Настройка лог-драйвера Grafana Loki](./loki_logging_driver_setup.md)** — детальный разбор драйвера Loki.
*   **[Агентный сбор логов Docker](./docker_agent_based_logging.md)** — альтернативный, более надежный подход.
*   **[rsyslog: Фильтрация и пересылка](../../Linux/SystemAdministration/Logging/rsyslog.md)** — настройка приемника для драйвера syslog.
