# Стек EFK в Kubernetes

> **Примечание:** Данный файл является основным руководством по развертыванию стека EFK в среде Kubernetes. Для решения возникающих проблем используйте [Устранение неполадок EFK](./efk_stack_troubleshooting.md).

## Определения

**Стек EFK (Elasticsearch, Fluent Bit, Kibana)** — интегрированное решение для централизованного сбора, долговременного хранения и анализа логов в кластере Kubernetes.

**Elasticsearch** — ядро стека; распределенная база данных, оптимизированная для полнотекстового поиска и аналитики. Начиная с версии 8.x, функции безопасности (TLS и аутентификация) включены по умолчанию.

**Fluent Bit** — высокопроизводительный агент (Log Shipper). В стеке EFK отвечает за сбор логов с узлов, их парсинг, обогащение метаданными и отправку в хранилище.

**Kibana** — платформа визуализации. Используется для поиска по логам (инструмент **Discover**), создания дашбордов и управления жизненным циклом данных.

**ECK (Elastic Cloud on Kubernetes)** — (рекомендуемый в 2026 г.) оператор для управления стеком Elastic в K8s, обеспечивающий автоматизацию обновлений, ротацию сертификатов и масштабирование.

## Основные концепции

### Архитектура сбора данных

Fluent Bit развертывается как **DaemonSet**. Это гарантирует запуск одного агента на каждом рабочем узле кластера.
*   **Input**: Чтение файлов `/var/log/containers/*.log`.
*   **Filter (Kubernetes)**: Обращение к API-серверу K8s для сопоставления лога с конкретным подом, контейнером и его метками.
*   **Output**: Пересылка структурированного JSON в Elasticsearch.

### Управление жизненным циклом (ILM)

В промышленной эксплуатации логи не могут храниться вечно. Используются следующие механизмы:
*   **Hot-Warm-Cold архитектура**: Перемещение старых логов с быстрых SSD на дешевые HDD.
*   **Data Streams**: (введено в ES 7.9+) современный способ работы с временными рядами (логами), упрощающий автоматическую ротацию и управление индексами.

### Безопасность по умолчанию

В Elasticsearch 8.x передача данных без TLS и без пароля заблокирована на уровне ядра. При развертывании через Helm необходимо:
1. Сгенерировать или задать пароль для пользователя `elastic`.
2. Настроить Fluent Bit на использование HTTPS и проверку CA-сертификата (или временное игнорирование проверки для self-signed сертификатов).

## Практические сценарии

### Развертывание через Helm

#### 1. Подготовка окружения

```bash
kubectl create ns logging
helm repo add elastic https://helm.elastic.co
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
```

#### 2. Установка Elasticsearch (с безопасностью)

Для 8.x важно явно задать пароль или знать, как его извлечь после установки.

```bash
# Пример установки с фиксированным паролем (для демонстрации)
helm upgrade --install elasticsearch elastic/elasticsearch \
  --namespace logging \
  --set replicas=3 \
  --set secret.password="YourSecurePass123!" \
  --set esJavaOpts="-Xmx2g -Xms2g" \
  --set resources.requests.memory="4Gi" \
  --set volumeClaimTemplate.resources.requests.storage="20Gi"
```
> **Важно:** Если пароль не задан, извлеките его командой:
> `kubectl get secret elasticsearch-master-credentials -n logging -o jsonpath="{.data.password}" | base64 -d`

#### 3. Установка Fluent Bit

Для работы с Elasticsearch 8.x необходимо добавить параметр `Suppress_Type_Name On` (так как типы индексов удалены).

```bash
# values.yaml для Fluent Bit
config:
  outputs: |
    [OUTPUT]
        Name            es
        Match           *
        Host            elasticsearch-master.logging.svc
        Port            9200
        HTTP_User       elastic
        HTTP_Passwd     YourSecurePass123!
        TLS             On
        TLS.Verify      Off
        Suppress_Type_Name On
        Logstash_Format On
        Logstash_Prefix kube-logs
```

#### 4. Установка Kibana

```bash
helm upgrade --install kibana elastic/kibana \
  --namespace logging \
  --set elasticsearchHosts="https://elasticsearch-master:9200" \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host="kibana.example.com"
```

### Оптимизация производительности

*   **Resources**: Всегда устанавливайте `requests` равными `limits` для памяти в Elasticsearch, чтобы избежать OOM Killer при всплесках нагрузки.
*   **Buffers**: Если Fluent Bit не успевает отправлять логи (Backpressure), настройте `Mem_Buf_Limit` в секции Input, чтобы предотвратить переполнение памяти агента.
*   **Disk**: Используйте `StorageClass` с быстрым SSD (например, `gp3` в AWS или `ssd-persistent-disk` в GCP).

## Дополнительная информация

*   [Конфигурация Fluent Bit](./fluentbit/fluentbit_configuration.md) — детальная настройка фильтров и парсеров.
*   [Парсинг логов во Fluent Bit](./fluentbit/parsing.md) — разбор JSON и многострочных записей (Java/Python).
*   [Практическое руководство по Kibana](./kibana_guide.md) — как искать логи и строить дашборды.
*   [Устранение неполадок EFK](./efk_stack_troubleshooting.md) — типичные ошибки при подключении и запуске.
*   [Сравнение Fluentd и Fluent Bit](./fluentbit/fluent_comparison.md) — почему Fluent Bit предпочтительнее для K8s.
