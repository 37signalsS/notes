# Установка Promtail в Kubernetes (Legacy)

## Определения

**Promtail** — специализированный агент для сбора логов и их отправки в систему Loki. В архитектуре Kubernetes он развертывается как DaemonSet, обеспечивая сбор логов со всех узлов кластера. Promtail отвечает только за логи; для метрик и трейсов в стеке Grafana используются отдельные агенты.

**Важное примечание (весна 2026):** Поддержка Promtail официально прекращена. Для всех новых инсталляций и при плановом обновлении инфраструктуры необходимо использовать **Grafana Alloy**. Данный документ сохраняется исключительно для обслуживания и эксплуатации существующих legacy-систем.

**Статус:** Helm-чарт `grafana/promtail` переведен в архивный режим. Обновления безопасности и функционала не выпускаются.

**Promtail EOL в контексте стека Loki 3.x:** Начиная с Loki 3.0, появились структурированные метаданные (Structured Metadata) и Bloom-фильтры. Promtail не поддерживает `allow_structured_metadata = true` в том же виде, что Alloy, поэтому при сохранении Promtail новые возможности Loki 3.x используются не полностью.

**Подробнее:** [Статус агентов сбора](../loki_overview.md)

## Основные концепции

### Архитектура Promtail

Агент читает файлы логов из директории `/var/log/pods` на хосте, обогащает их метаданными из API Kubernetes и отправляет пакеты (batches) в Loki через балансировщик (Gateway).

```
┌─────────────┐     ┌──────────────┐     ┌─────────┐
│ Файлы логов │────→│   Promtail   │────→│  Loki   │
│ /var/log/*  │     │  (DaemonSet) │     │ Gateway │
└─────────────┘     └──────────────┘     └─────────┘
      │                     │
      │              positions.yaml
      │            (отслеживание чтения)
```

**Принцип работы:**
1. **Scrape loop:** Promtail опрашивает файловую систему на наличие новых лог-файлов и изменений в существующих.
2. **Tail:** Для каждого файла отслеживается текущая позиция чтения через `positions.yaml`. При перезапуске агент продолжает чтение с последней сохраненной позиции, избегая дублирования.
3. **Kubernetes SD:** Использует Kubernetes API для получения метаданных подов (namespace, pod name, labels) и их добавления к лог-записям.
4. **Pipeline stages:** Логи проходят через конвейер обработки: multiline-сборка, парсинг JSON, маскировка, фильтрация, извлечение лейблов.
5. **Batch и retry:** Собранные логи группируются в батчи и отправляются в Loki. При недоступности Loki работает механизм backoff с экспоненциальной задержкой.

### Ключевые компоненты конфигурации

| Компонент | Назначение |
| :--- | :--- |
| **`clients`** | Настройка адресов Loki и параметров аутентификации, backoff и лимитов батчей |
| **`scrape_configs`** | Правила обнаружения источников (Service Discovery) и парсинга |
| **`pipeline_stages`** | Этапы обработки строки: парсинг JSON, обработка многострочных логов (multiline), фильтрация |
| **`positions`** | Файл/хранилище для хранения смещения (offset) в каждом читаемом файле |

### Жизненный цикл лог-записи в Promtail

1. **Discovery:** Promtail обнаруживает целевые файлы логов через `kubernetes_sd_configs` или статические пути.
2. **Read:** Читает новые байты с последней известной позиции из `positions.yaml`.
3. **Parse:** Применяет pipeline stages: multiline-сборка, JSON-парсинг, extraction, labels.
4. **Enrich:** Добавляет метаданные Kubernetes (namespace, pod, node) и кастомные лейблы.
5. **Buffer:** Накопление в памяти до достижения порогов `batchsize` или `batchwait`.
6. **Send:** Отправка батча в Loki через HTTP POST `/loki/api/v1/push`.
7. **Ack/Retry:** При успехе — обновление позиции в `positions.yaml`. При ошибке — повтор через backoff.

### Важность positions.yaml

`positions.yaml` — критически важный файл состояния. Он хранит:
- Имя файла лога
- Текущее смещение (offset) в байтах
- Последнюю modification time

При потере или повреждении этого файла Promtail начнет чтение логов сначала, что приведет к дублированию данных в Loki. Для production обязательно используетcя персистентное хранилище (HostPath или PVC) для этого файла.

### Выбор агента сбора логов в legacy-средах

| Критерий | Promtail | Fluent Bit | Vector |
| :--- | :--- | :--- | :--- |
| **Интеграция с Loki** | Нативная | Через output plugin | Через sink |
| **Производительность** | Средняя | Высокая | Высокая |
| **Потребление памяти** | ~50-100MB | ~20-50MB | ~30-80MB |
| **Язык конфигурации** | YAML | YAML/JSON | TOML/JSON |
| **Статус в стеке Loki** | Deprecated | Активный (требует настройки) | Активный (требует настройки) |
| **Поддержка structured metadata** | Ограниченная | Ограниченная | Ограниченная |

**Рекомендация:** В существующих кластерах с Promtail продолжайте использовать его до плановой миграции на Alloy. Для новых сервисов в рамках того же кластера рассмотрите Fluent Bit или Vector как временное решение, если миграция на Alloy запланирована на более поздний срок.

### Сравнение с Grafana Alloy

| Характеристика | Promtail | Grafana Alloy |
| :--- | :--- | :--- |
| **Тип данных** | Только логи | Универсальный: логи, метрики, трассировки, профили |
| **Язык конфигурации** | YAML (статический) | River (динамический, HCL-подобный) |
| **Производительность** | Средняя | Высокая (оптимизировано под Go и OTel) |
| **Жизненный цикл** | Устарело (Deprecated) | Стандарт индустрии (Current) |
| **Structured Metadata (Loki 3.x)** | Ограниченная поддержка | Полная поддержка через `allow_structured_metadata` |
| **eBPF** | Нет | Да (авто-инструментирование) |
| **Multi-tenancy** | На уровне Loki | На уровне агента и Loki |
| **Обнаружение изменений** | Перезагрузка процесса | Hot reload (динамическое обновление) |

## Практические сценарии

### Сценарий 1: Эксплуатация Promtail в существующем кластере

Для поддержки работоспособности агента в старых окружениях необходимо использовать фиксированные версии чарта и учитывать особенности EOL-состояния.

**Подготовка:**

```bash
# Использование legacy-репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Получение текущих значений
helm show values grafana/promtail > promtail_values.yaml
```

**Важное замечание по безопасности:** Поскольку Promtail больше не получает обновлений, крайне важно:
1. Использовать фиксированную версию чарта, а не тег `latest`
2. Ограничить доступ к API Kubernetes через минимально необходимые RBAC-права
3. Изолировать Promtail в отдельном namespace
4. Регулярно проверять наличие критических уязвимостей в образе контейнера

**Пример production-ready values.yaml:**

```yaml
# Фиксированная версия для стабильности
image:
  tag: 3.1.1
  pullPolicy: IfNotPresent

# RBAC
serviceAccount:
  create: true
  name: promtail-agent

rbac:
  create: true
  # Минимальные права: только pods, nodes, namespaces
  # ClusterRole создается чартом автоматически

# DaemonSet-конфигурация
daemonset:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1

# Tolerations для master/control-plane нод (опционально)
tolerations:
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule

# Pod Anti-Affinity для распределения по разным нодам
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: promtail
          topologyKey: kubernetes.io/hostname

# Ресурсы
resources:
  limits:
    cpu: 200m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 256Mi

# Хранилище для positions.yaml (обязательно для production)
positions:
  directory: /var/lib/promtail
  syncPeriod: 5s

# Конфигурация Promtail
config:
  clients:
    - url: http://loki-gateway.logging.svc.cluster.local:80/loki/api/v1/push
      batchwait: 1s
      batchsize: 1048576 # 1MB
      backoff_config:
        min_period: 100ms
        max_period: 10s
        max_retries: 10
```

**Пример конфигурации для многострочных логов (Java Stacktrace):**

```yaml
config:
  snippets:
    pipelineStages:
      - multiline:
          firstline: '^\[\d{4}-\d{2}-\d{2}' # Начало строки с датой
          max_wait_time: 3s
      - json:
          expressions:
            level: level
            msg: message

    scrape_configs:
      - job_name: kubernetes-pods
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_namespace]
            target_label: namespace
          - source_labels: [__meta_kubernetes_pod_name]
            target_label: pod
```

### Сценарий 2: Безопасность и права доступа (RBAC)

Promtail требует доступа к API Kubernetes для получения метаданных подов и узлов. В EOL-состоянии особенно важно соблюдать принцип минимальных привилегий.

**Настройка ServiceAccount и RBAC в `values.yaml`:**
```yaml
serviceAccount:
  create: true
  name: promtail-agent

rbac:
  create: true
  # ClusterRole создается чартом, но можно переопределить:
  # rules:
  #   - apiGroups: [""]
  #     resources: ["pods", "namespaces", "nodes"]
  #     verbs: ["get", "list", "watch"]
```

**Проверка созданных прав:**

```bash
# Проверка ClusterRole
kubectl get clusterrole promtail-agent -o yaml

# Проверка ServiceAccount
kubectl get sa -n logging promtail-agent

# Проверка прав (dry-run)
kubectl auth can-i get pods --as=system:serviceaccount:logging:promtail-agent
kubectl auth can-i list nodes --as=system:serviceaccount:logging:promtail-agent
```

Если в кластере включены жесткие политики безопасности (PodSecurityPolicy или Admission Controllers), убедитесь, что Promtail имеет доступ к `/var/log/pods` и `/var/lib/docker/containers` через `hostPath` тома.

### Сценарий 3: Оптимизация и управление ресурсами

В высоконагруженных кластерах Promtail может потреблять значительный объем памяти при буферизации и обработке большого количества логов.

```yaml
resources:
  limits:
    cpu: 200m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 256Mi

# Настройка backoff при недоступности Loki
config:
  clients:
    - url: http://loki:3100/loki/api/v1/push
      backoff_config:
        min_period: 100ms
        max_period: 10s
        max_retries: 10
      # Ограничение размера батча для снижения memory pressure
      batchsize: 524288 # 512KB вместо 1MB для слабых нод
```

**Рекомендации по ресурсам:**
- Для сред с < 100 pods/ноду: 100m CPU, 256Mi Memory
- Для сред с > 500 pods/ноду или интенсивным логированием: 200m CPU, 512Mi Memory
- Мониторьте `process_resident_memory_bytes` метрику Promtail для корректировки лимитов

### Сценарий 4: Локальная установка (Binary) на Linux

Ручной запуск агента для сбора логов с физических или виртуальных серверов без Kubernetes.

**1. Загрузка и подготовка:**

```bash
# Загрузка бинарного файла (выберите архитектуру)
curl -O -L "https://github.com/grafana/loki/releases/download/v3.1.1/promtail-linux-amd64.zip"
unzip promtail-linux-amd64.zip
chmod +x promtail-linux-amd64
```

**2. Конфигурация (`promtail-local-config.yaml`):**

Пример настройки для сбора системных логов и логов конкретного приложения:

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

clients:
  - url: http://<LOKI_SERVER_IP>:3100/loki/api/v1/push

scrape_configs:
  # Задача 1: Системные логи
  - job_name: system
    static_configs:
      - targets:
          - localhost
        labels:
          job: varlogs
          __path__: /var/log/*.log # Сбор всех .log файлов в директории

  # Задача 2: Логи приложения
  - job_name: custom_app
    static_configs:
      - targets:
          - localhost
        labels:
          job: api_logs
          env: production
          __path__: /home/user/app/logs/app.log
```

**3. Запуск агента:**

Для чтения логов из `/var/log` обычно требуются права суперпользователя.

```bash
sudo ./promtail-linux-amd64 -config.file=promtail-local-config.yaml
```

**4. Особенности конфигурации:**
*   **`__path__`**: Поддерживает wildcard (например, `*.log`).
*   **Labels**: Это метаданные, по которым будет происходить индексация в Loki. Старайтесь не создавать слишком много уникальных лейблов (High Cardinality).
*   **Positions**: По умолчанию Promtail создает файл `positions.yaml`, чтобы помнить, на каком месте он закончил чтение при перезапуске.

**5. Запуск как systemd service (рекомендуется для production):**

```ini
# /etc/systemd/system/promtail.service
[Unit]
Description=Promtail log collector
After=network.target

[Service]
Type=simple
User=promtail
Group=promtail
ExecStart=/usr/local/bin/promtail-linux-amd64 -config.file=/etc/promtail/config.yml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Сценарий 5: Переход на Grafana Alloy

Миграция рекомендуется как единственный путь обеспечения безопасности и масштабируемости. Детальное пошаговое руководство см. в [alloy_installation.md](alloy_installation.md#сценарий-8-миграция-с-promtail-на-alloy).

**Краткий план миграции:**

1.  **Экспорт конфигурации:**
    ```bash
    kubectl get configmap -n logging promtail -o jsonpath='{.data["promtail\.yaml"]}' > legacy_promtail.yaml
    ```
2.  **Конвертация:**
    Используйте встроенную утилиту Alloy:
    ```bash
    alloy convert --source-format=promtail --output=config.alloy legacy_promtail.yaml
    alloy lint config.alloy
    ```
3.  **Валидация и проверка лейблов:**
    Проверьте полученный файл `config.alloy`. Убедитесь, что логика `relabel_configs` сохранилась, так как изменение лейблов приведет к разрыву исторических данных (созданию новых потоков в Loki).
4.  **Развертывание:**
    Инструкции по установке нового агента доступны в [Руководстве по Alloy](alloy_installation.md).

**Важно:** Проверьте, что `external_labels` и `__meta_*` лейблы совпадают, чтобы избежать разрыва исторических данных в Loki.

### Сценарий 6: Динамическое извлечение лейблов из JSON-логов (Kubernetes)

Используется для превращения полей внутри лог-сообщения (например, HTTP-кода или метода) в индексируемые лейблы Loki.

**1. Проверка структуры лога:**
Если приложение пишет логи в формате `{"log": {"code": 200, "method": "GET", "msg": "success"}}`, мы можем извлечь `code` и `method`.

**2. Извлечение текущей конфигурации из Secret:**
```bash
kubectl get secret loki-stack-promtail -o jsonpath="{.data['promtail\.yaml']}" | base64 --decode > promtail.yaml
```

**3. Редактирование пайплайна в `promtail.yaml`:**
Добавьте стадию `match` для конкретного приложения:
```yaml
pipeline_stages:
  - match:
      selector: '{app="api"}' # Фильтр подов
      stages:
        - json:
            expressions:
              extracted_log: log # Извлекаем вложенный объект
        - json:
            source: extracted_log
            expressions:
              code: code
              method: method
        - labels:
            code:
            method:
```

**4. Обновление секрета и перезапуск:**
```bash
# Удаление старого секрета
kubectl delete secret loki-stack-promtail
# Создание нового из файла
kubectl create secret generic loki-stack-promtail --from-file=promtail.yaml
# Перезапуск подов Promtail (удаление текущих)
kubectl delete pod -l app=promtail
```

**5. Верификация:**
В Grafana Explore выберите `{app="api"}`. В списке лейблов должны появиться `code` и `method`, позволяя фильтровать логи: `{app="api", code="200"}`.

### Сценарий 7: Production DaemonSet — планирование capacity и обновление

**Capacity planning:**

| Метрика | Формула | Пример |
| :--- | :--- | :--- |
| **Потребление RAM** | 50-100MB на ноду + 10-20MB на 100 pods | 500 pods → ~100-150MB |
| **Потребление CPU** | 10-50m на ноду при средней нагрузке | 1000 pods → ~100-200m |
| **Диск positions.yaml** | < 1MB на 1000 pods | 5000 pods → ~5MB |
| **Сеть** | ~1-10KB/с на ноду в среднем | Зависит от объема логов |

**Update Strategy для DaemonSet:**

```yaml
daemonset:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1 # Постепенный rollout, минимизируя риск
```

**Приоритет scheduling:**

```yaml
# PriorityClass для Promtail, чтобы он стартовал до приложений
priorityClassName: system-node-critical

# Или через values.yaml:
priorityClassName: ""
```

### Сценарий 8: Мониторинг и самомониторинг Promtail

Хотя Promtail устарел, в существующих кластерах важно отслеживать его работоспособность.

**Включение метрик:**

```yaml
config:
  server:
    http_listen_port: 9080
    grpc_listen_port: 0

# Включение endpoint для метрик (по умолчанию на 9080)
```

**Ключевые метрики для мониторинга:**

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `promtail_request_duration_seconds` | Длительность отправки батчей в Loki | P99 > 5s |
| `promtail_sent_bytes_total` | Объем отправленных данных | Резкое падение → проблема с сетью/Loki |
| `promtail_failed_entries_total` | Количество неотправленных записей | > 0 длительное время |
| `promtail_entries_sent_total` | Успешно отправленные записи | Должен расти |
| `promtail_wal_lines` | Количество строк в WAL (positions) | Взрывной рост → проблема с чтением |

**Пример ServiceMonitor для Prometheus Operator:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: promtail
  namespace: logging
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: promtail
  endpoints:
    - port: http-metrics
      interval: 30s
      path: /metrics
```

### Сценарий 9: Бэкап и восстановление состояния Promtail

**Бэкап конфигурации:**

```bash
# Helm-значения
helm get values promtail -n logging > promtail-backup-$(date +%Y%m%d).yaml

# ConfigMap с конфигурацией
kubectl get configmap -n logging promtail -o yaml > promtail-config-backup.yaml

# Secret (если используется)
kubectl get secret -n logging loki-stack-promtail -o yaml > promtail-secret-backup.yaml
```

**Бэкап positions.yaml:**

```bash
# Для DaemonSet с HostPath
HOST_PATH="/var/lib/promtail"
NODE_NAME=$(hostname)
kubectl debug node/$NODE_NAME -it --image=busybox -- cp $HOST_PATH/positions.yaml ./positions-backup.yaml

# Или через архив с ноды
tar -czf promtail-positions-backup.tar.gz /var/lib/promtail/
```

**Восстановление:**

```bash
# Восстановление ConfigMap
kubectl apply -f promtail-config-backup.yaml

# Восстановление positions.yaml на всех нодах
# (требует доступа к нодам или перезапуска DaemonSet)
kubectl rollout restart daemonset/promtail -n logging
```

### Сценарий 10: Параллельная работа Promtail и Alloy (Canary)

Пошаговая миграция без риска потери логов.

1.  **Установка Alloy в отдельном namespace или с другим префиксом:**
    ```bash
    helm install alloy-canary grafana/alloy \
      --namespace logging \
      --set deployment.mode=DaemonSet \
      --set config.mapContent='...'
    ```

2.  **Валидация сбора:** убедиться, что логи поступают в Loki от обоих агентов.

3.  **Конвертация конфигурации:**
    ```bash
    alloy convert --source-format=promtail --output=config.alloy promtail-config.yaml
    alloy lint config.alloy
    ```

4.  **Переключение нагрузки:** удаление Promtail после подтверждения работы Alloy.

## Диагностика и устранение неисправностей

### Типичные проблемы

| Проблема | Причина | Способ решения |
| :--- | :--- | :--- |
| **"Entry out of order"** | Логи с одинаковыми метками приходят не в хронологическом порядке | Добавьте уникальную метку (например, `pod`) или используйте стадию `timestamp` для парсинга времени из тела лога. |
| **Поды в Pending** | Taints на мастер-нодах или отсутствие ресурсов | Добавьте `tolerations: - operator: "Exists"` в values.yaml. Проверьте ResourceQuotas в namespace. |
| **Пропуски данных** | Сбой файла `positions.yaml` | Проверьте монтирование HostPath для персистентности файла позиций. Убедитесь, что у Promtail есть права на запись в этот файл. |
| **Ошибка 429** | Превышение лимитов в Loki | Увеличьте `ingestion_rate_mb` в конфигурации Loki или уменьшите `batchsize` в Promtail. |
| **Высокое потребление RAM** | Большой размер батчей или много pipeline stages | Уменьшите `batchsize`, добавьте `limit` на pipeline stages, увеличьте лимиты ресурсов. |
| **Логи не появляются в Loki** | Проблемы с сетью, неверные labels, отброс старых сэмплов | Проверьте endpoint, метрики агента, `reject_old_samples_max_age`. Убедитесь, что timestamp в логах корректен. |
| **Повреждение positions.yaml** | Аварийное завершение Promtail или переполнение диска | Восстановите из бэкапа или удалите файл (лог будет прочитан сначала). |

### Диагностические команды

```bash
# Проверка статуса подов
kubectl get pods -n logging -l app.kubernetes.io/name=promtail

# Проверка DaemonSet
kubectl get daemonset -n logging promtail

# Проверка логов
kubectl logs -n logging -l app.kubernetes.io/name=promtail --tail=100

# Проверка метрик
kubectl port-forward svc/promtail 9080:9080 -n logging
curl -s http://localhost:9080/metrics | grep -E "promtail_entries|promtail_sent|promtail_failed"

# Проверка positions.yaml
kubectl exec -n logging <pod-name> -- cat /var/lib/promtail/positions.yaml | head

# Проверка связности с Loki
kubectl exec -n logging <pod-name> -- curl -s http://loki-gateway.logging.svc.cluster.local:80/ready
```

## Ограничения и особые случаи

### Ограничения Promtail в 2026 году

1.  **EOL-статус:** Никаких новых функций, исправлений уязвимостей или обновлений совместимости с Loki 3.x.
2.  **Structured Metadata:** Promtail не имеет нативной поддержки `allow_structured_metadata = true` в том же виде, что Alloy. Для использования structured metadata в Loki 3.x требуется миграция.
3.  **Язык конфигурации:** Только статический YAML. Любое изменение требует перезапуска процесса.
4.  **Производительность:** В высоконагруженных кластерах (> 1000 pods/нода) может потреблять больше ресурсов, чем Alloy или Fluent Bit.
5.  **eBPF:** Отсутствует поддержка авто-инструментирования приложений.

### Рекомендации по эксплуатации legacy-систем

1.  **Планируйте миграцию:** Даже если текущая конфигурация работает, разработайте план перехода на Alloy в течение 3-6 месяцев.
2.  **Фиксируйте версии:** Используйте конкретные теги образов и чартов, а не `latest`.
3.  **Мониторьте уязвимости:** Регулярно проверяйте образ Promtail в реестре на наличие критических CVE.
4.  **Изолируйте:** Размещайте Promtail в отдельном namespace с минимальными RBAC-правами.
5.  **Документируйте:** Ведите журнал конфигурационных изменений для упрощения будущей миграции.

## Полезные команды

```bash
# Получение логов Promtail
kubectl logs -n logging -l app.kubernetes.io/name=promtail --tail=100 -f

# Проверка DaemonSet rollout
kubectl rollout status daemonset/promtail -n logging

# Проверка RBAC
kubectl auth can-i get pods --as=system:serviceaccount:logging:promtail-agent

# Проверка positions.yaml на ноде
kubectl debug node/<node-name> -it --image=busybox -- cat /var/lib/promtail/positions.yaml

# Валидация Helm-шаблона
helm template promtail grafana/promtail -f values.yaml | kubectl apply --dry-run=client -f -

# Проверка метрик
kubectl port-forward svc/promtail 9080:9080 -n logging
curl -s http://localhost:9080/metrics | grep promtail

# Экспорт текущей конфигурации
kubectl get configmap -n logging promtail -o jsonpath='{.data["promtail\.yaml"]}'
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Установка Grafana Alloy](alloy_installation.md) | Рекомендуемый современный агент для сбора телеметрии |
| [Миграция с Promtail на Alloy](alloy_installation.md#сценарий-8-%D0%BC%D0%B8%D0%B3%D1%80%D0%B0%D1%86%D0%B8%D1%8F-%D1%81-promtail-%D0%BD%D0%B0-alloy) | Пошаговое руководство по переходу |
| [Обзор Loki](../loki_overview.md) | Общая архитектура системы логирования |
| [Установка Loki](loki_installation.md) | Развертывание бэкенда в Kubernetes |
| [Grafana Alloy — обзор](../../Grafana/grafana_alloy_overview.md) | Детальное описание преимуществ и языка River |
