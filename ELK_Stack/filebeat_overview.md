# Filebeat: Обзор и конфигурация

> Эта заметка является авторитетным источником по вопросам сбора и пересылки логов с использованием Filebeat. Она описывает архитектуру, современные методы идентификации файлов и практические сценарии развертывания в различных средах.

## Определения

* **Filebeat** — легковесный агент (shipper), написанный на Go, предназначенный для сбора, фильтрации и отправки логов в Elasticsearch, Logstash или Kafka.
* **Filestream** — основной и рекомендуемый тип входных данных (input) в Filebeat 8.x/9.x, обеспечивающий высокую производительность и гибкость настройки парсеров.
* **Harvester (Сборщик)** — процесс внутри Filebeat, отвечающий за чтение одной конкретной линии в одном файле.
* **Registry (Реестр)** — служебный файл, хранящий состояние чтения (offset) для каждого файла. В версиях 9.x реестр использует формат **append-only log** для повышения скорости работы.
* **Fingerprinting** — метод идентификации файла путем хеширования его начального блока (обычно 1024 байта). Позволяет корректно отслеживать файлы при смене inode или агрессивной ротации.
* **Backpressure (Обратное давление)** — механизм, при котором Filebeat замедляет чтение данных, если система-приемник перегружена, предотвращая потерю событий и переполнение памяти.
* **Ingest Pipeline** — конвейер обработки данных в Elasticsearch, который выполняет преобразования (парсинг, обогащение, фильтрацию) перед индексацией. Filebeat может загружать pipelines автоматически при использовании модулей.

## Основные концепции

### Архитектура входа Filestream

Вход `filestream` полностью заменяет устаревший тип `log`. Его ключевые особенности:
1.  **Порядок обработки**: Позволяет настраивать цепочку парсеров (например, сначала JSON, затем multiline), что было невозможно в старых версиях.
2.  **Идентификация (File Identity)**: В Filebeat 9.x по умолчанию используется **fingerprint**.
    *   *Проблема 1KB*: Filebeat не начнет читать новый файл, пока тот не достигнет размера 1024 байта. Для очень мелких логов длину фингерпринта нужно уменьшать вручную.
3.  **Registry Performance**: Новый формат реестра исключает перезапись огромных JSON-файлов, выполняя только инкрементальные обновления, что критично при мониторинге тысяч файлов.
4.  **Clean Options**: Настраивает поведение при обнаружении удаленных файлов. Опции: `none` (оставлять offset), `removed` (удалять из реестра), `renamed` (удалять при переименовании).

### Сравнение типов входов

| Характеристика | `filestream` (рекомендуемый) | `log` (устаревший) |
| :--- | :--- | :--- |
| **Идентификация файлов** | Fingerprint (хеш начальных байтов) | inode + device |
| **Парсеры** | Цепочка (JSON → multiline) | Ограниченный набор |
| **Производительность** | Высокая (инкрементальный реестр) | Средняя (полная перезапись JSON) |
| **Ротация файлов** | Полная поддержка через `clean_*` | Базовая поддержка |
| **Миграция** | `take_over: true` | Не поддерживается |

### Автоматическое обнаружение (Autodiscover)

Filebeat поддерживает динамическое обнаружение источников логов в контейнерных средах:
*   **Docker**: Следит за событиями Docker API и автоматически подключает сбор логов для новых контейнеров.
*   **Kubernetes**: Использует метаданные Pods (лейблы, аннотации) для применения специфических конфигураций парсинга к разным приложениям.

#### Пример autodiscover для Docker

```yaml
filebeat.autodiscover:
  providers:
    - type: docker
      hints.enabled: true
      hints.default_config:
        type: container
        paths:
          - /var/lib/docker/containers/${data.docker.container.id}/*.log
```

#### Пример autodiscover для Kubernetes

```yaml
filebeat.autodiscover:
  providers:
    - type: kubernetes
      node: ${NODE_NAME}
      hints.enabled: true
      hints.default_config:
        type: container
        paths:
          - /var/log/containers/*-${data.kubernetes.pod.id}.log
```

### Безопасность и хранение секретов

Для предотвращения утечки паролей в конфигурационных файлах используется **Filebeat Keystore**:
*   Позволяет хранить API-ключи и пароли в зашифрованном виде.
*   Обращение к секретам в YAML через синтаксис `${SECRET_NAME}`.

```bash
# Создание keystore
filebeat keystore create

# Добавление секрета
filebeat keystore add ES_API_KEY

# Просмотр списка (без значений)
filebeat keystore list
```

### Процессоры (Processors)

Processors выполняют обогащение, фильтрацию и преобразование событий перед отправкой:

*   **add_host_metadata** — добавляет информацию о хосте (IP, имя, ОС).
*   **add_cloud_metadata** — добавляет метаданные облачного провайдера (AWS, GCP, Azure).
*   **add_docker_metadata** — добавляет информацию о Docker-контейнере (имя, лейблы, образ).
*   **add_kubernetes_metadata** — добавляет информацию о Kubernetes Pod (имя, namespace, лейблы).
*   **drop_fields** — удаляет ненужные поля для уменьшения размера события.
*   **rename** — переименовывает поля для соответствия ECS (Elastic Common Schema).

## Практические сценарии

### 1. Настройка входа filestream с парсингом JSON

Пример для Filebeat 9.x с использованием уникального ID и миграцией со старого типа `log`.

```yaml
filebeat.inputs:
- type: filestream
  id: "app-prod-v1" # Уникальный ID обязателен
  paths:
    - /var/log/myapp/*.log
  
  # Миграция: забирает offset из реестра старого входа 'log'
  take_over: true 

  file_identity.fingerprint:
    length: 1024 # Можно уменьшить до 64 для мелких файлов

  parsers:
    - ndjson:
        target: "" # Раскрывать JSON в корень документа
        overwrite_keys: true
    - multiline:
        type: pattern
        pattern: '^\['
        negate: true
        match: after

output.elasticsearch:
  hosts: ["https://es-cluster:9200"]
  api_key: "${ES_API_KEY}" # Секрет из Keystore
  ssl.certificate_authorities: ["/etc/filebeat/certs/ca.crt"]
```

### 2. Использование модулей (Nginx)

Модули включают в себя Ingest Pipelines для Elasticsearch и готовые дашборды для Kibana.

```bash
# 1. Включение модуля
filebeat modules enable nginx

# 2. Настройка путей (в /etc/filebeat/modules.d/nginx.yml)
# - module: nginx
#   access:
#     enabled: true
#     var.paths: ["/var/log/nginx/access.log*"]

# 3. Загрузка ресурсов в ES и Kibana
filebeat setup -e
```

### 3. Глобальные процессоры для обогащения данных

```yaml
processors:
  - add_host_metadata: ~
  - add_cloud_metadata: ~
  - add_docker_metadata: ~
  - drop_fields:
      fields: ["agent.ephemeral_id", "agent.id", "ecs.version"]
      ignore_missing: true
```

### 4. Развертывание в Docker

Для сбора логов контейнеров с хоста:

```yaml
services:
  filebeat:
    image: elastic/filebeat:8.15.0
    container_name: filebeat-logger
    volumes:
      - /var/lib/docker/containers:/usr/share/dockerlogs:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./filebeat/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - ./filebeat/registry:/usr/share/filebeat/data
    user: root
    restart: unless-stopped
```

### 5. Развертывание в Kubernetes (DaemonSet)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: filebeat
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: filebeat
  template:
    metadata:
      labels:
        app: filebeat
    spec:
      containers:
      - name: filebeat
        image: elastic/filebeat:8.15.0
        args: ["-c", "/etc/filebeat/filebeat.yml", "-e"]
        resources:
          limits:
            memory: 300Mi
          requests:
            memory: 200Mi
        volumeMounts:
        - name: varlog
          mountPath: /var/log
        - name: containers
          mountPath: /var/lib/docker/containers
          readOnly: true
        - name: filebeat-config
          mountPath: /etc/filebeat/filebeat.yml
          subPath: filebeat.yml
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: containers
        hostPath:
          path: /var/lib/docker/containers
      - name: filebeat-config
        configMap:
          name: filebeat-config
```

### 6. Отправка данных через Kafka

Для высоконагруженных сред с буферизацией:

```yaml
output.kafka:
  hosts: ["kafka1:9092", "kafka2:9092"]
  topic: "logs-%{[agent.version]}"
  partition.round_robin:
    reachable_only: true
  required_acks: 1
  compression: gzip
  max_message_bytes: 1000000
```

## Требования и предварительная подготовка

### Системные требования

*   **ОС**: Linux (amd64, arm64), macOS (amd64), Windows (amd64)
*   **RAM**: Минимум 256 MiB, рекомендуется 512 MiB для производственных сред
*   **Диск**: 50 MiB для установки + пространство для реестра (зависит от количества файлов)
*   **Сеть**: Доступ к Elasticsearch/Logstash/Kafka (порты 9200/5044/9092)

### Установка

```bash
# Debian/Ubuntu
wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo apt-key add -
echo "deb https://artifacts.elastic.co/packages/8.x/apt stable main" | sudo tee /etc/apt/sources.list.d/elastic-8.x.list
sudo apt update && sudo apt install filebeat

# RHEL/CentOS
sudo rpm --import https://artifacts.elastic.co/GPG-KEY-elasticsearch
sudo tee /etc/yum.repos.d/elastic.repo <<EOF
[elastic-8.x]
name=Elastic repository for 8.x packages
baseurl=https://artifacts.elastic.co/packages/8.x/yum
gpgcheck=1
gpgkey=https://artifacts.elastic.co/GPG-KEY-elasticsearch
enabled=1
autorefresh=1
type=rpm-md
EOF
sudo yum install filebeat
```

### Проверка работоспособности

```bash
# Проверка конфигурации
sudo filebeat test config

# Проверка подключения к Elasticsearch
sudo filebeat test output

# Просмотр логов в реальном времени
journalctl -u filebeat -f
```

## Устранение неполадок

### Типичные ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `data path already locked` | Другой экземпляр Filebeat уже запущен | Остановите предыдущий процесс или проверьте `ps aux | grep filebeat` |
| `Could not find index pattern` | Kibana не содержит шаблон индекса | Выполните `filebeat setup --dashboards` |
| `no outputs are defined` | Output не настроен или опечатка | Проверьте секцию `output` в `filebeat.yml` |
| `connection refused` | Elasticsearch/Logstash недоступен | Проверьте сетевую доступность: `curl -I http://es:9200` |
| `certificate signed by unknown authority` | Проблема с TLS-сертификатом | Укажите правильный CA в `ssl.certificate_authorities` |
| `permission denied` | Нет прав на чтение лог-файлов | Запустите от root или добавьте пользователя в группу |

### Отладка

```bash
# Включение отладочного логирования
filebeat -e -d "*"

# Проверка конкретного модуля
filebeat -e -d "publish"

# Просмотр метрик (JSON)
curl -s http://localhost:5066/stats | jq .
```

### Мониторинг Filebeat

Filebeat предоставляет HTTP-эндпоинт для сбора метрик:

```yaml
http.enabled: true
http.port: 5066
```

Ключевые метрики:
*   `filebeat.harvester.open_files` — количество активных harvester'ов
*   `filebeat.harvester.running` — количество запущенных harvester'ов
*   `filebeat.registrar.registry_file.entries` — количество отслеживаемых файлов
*   `filebeat.events.published` — общее количество отправленных событий

## Граничные случаи и ограничения

### Ротация файлов

Filebeat корректно обрабатывает ротацию при соблюдении условий:
*   **Способ ротации**: `copytruncate` (рекомендуется) или `rename` + создание нового файла
*   **Идентификация**: При использовании `filestream` с fingerprint Filebeat отслеживает файл по хешу, а не по inode
*   **Таймаут**: Настройка `close_renamed` / `close_removed` определяет, когда закрывать harvester после ротации

### Большие файлы

*   Filebeat не загружает весь файл в память — чтение идет построчно
*   Для очень больших файлов (>100 GiB) настройте `close_inactive` для освобождения ресурсов
*   Используйте `harvester_buffer_size` (по умолчанию 64 KiB) для оптимизации чтения

### Многострочные логи (Multiline)

Конфигурация для склеивания Stack Traces:

```yaml
parsers:
  - multiline:
      type: pattern
      pattern: '^\d{4}-\d{2}-\d{2}' # Начало нового события
      negate: true
      match: after
```

### Кодировки файлов

Filebeat поддерживает автоопределение кодировки (UTF-8, ISO-8859-1, CP437 и др.). Для нестандартных кодировок:

```yaml
parsers:
  - ndjson:
      encoding: GBK # Китайская кодировка
```

## Рекомендации по тюнингу производительности

1.  **Queue**: Используйте `queue.mem` для буферизации событий в памяти. Увеличение `events` и `flush.min_events` повышает пропускную способность за счет небольшого увеличения задержки.
2.  **Batch Size**: Настройка `bulk_max_size` в `output.elasticsearch` должна соответствовать возможностям кластера. Оптимальное значение — 1000–5000 событий.
3.  **Memory Limits**: В Kubernetes устанавливайте `resources.limits.memory` не менее 200–300 MiB, так как кеширование фингерпринтов и реестра потребляет RAM пропорционально количеству файлов.
4.  **Harvester Limit**: Параметр `harvester_limit` ограничивает количество одновременных harvester'ов (по умолчанию — без ограничений). Установите значение для контроля потребления CPU.
5.  **Scan Frequency**: Интервал сканирования новых файлов (по умолчанию 10с). Уменьшите для более быстрого обнаружения, увеличьте для снижения нагрузки на диск.

## Ссылки и взаимосвязи

*   **[Обзор Elastic Stack](./elk_stack_overview.md)** — архитектура и место Filebeat в системе.
*   **[Beats Family](./Elasticsearch/beats_family.md)** — Metricbeat, Heartbeat, Auditbeat, Packetbeat для метрик и аудита.
*   **[Elastic Agent и Fleet](./Elasticsearch/elastic_agent_and_fleet.md)** — замена Beats, централизованное управление через Fleet.
*   **[Логирование в Docker](../Docker/Docker_logs/docker_agent_based_logging.md)** — детально про сбор через сокет.
*   **[Logstash: Фильтрация и роутинг](./Logstash/logstash_pipelines.md)** — если возможностей Filebeat недостаточно.
*   **[Grok и Dissect Patterns](./grok_dissect_patterns.md)** — коллекция паттернов для парсинга логов.
*   **[Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md)** — обработка документов в Elasticsearch.
*   **[Официальная документация Filebeat](https://www.elastic.co/guide/en/beats/filebeat/current/index.html)**.
