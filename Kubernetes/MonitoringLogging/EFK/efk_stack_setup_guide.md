# Стек EFK в Kubernetes

> **Примечание:** Данный файл является основным руководством по развертыванию стека EFK в среде Kubernetes. Для решения возникающих проблем используйте [Устранение неполадок EFK](./efk_stack_troubleshooting.md).

## Определения

**Стек EFK (Elasticsearch, Fluent Bit, Kibana)** — интегрированное решение для централизованного сбора, долговременного хранения и анализа логов в кластере Kubernetes.

**Elasticsearch** — ядро стека; распределенная база данных, оптимизированная для полнотекстового поиска и аналитики. Начиная с версии 8.x, функции безопасности (TLS и аутентификация) включены по умолчанию.

**Fluent Bit** — высокопроизводительный агент (Log Shipper). В стеке EFK отвечает за сбор логов с узлов, их парсинг, обогащение метаданными и отправку в хранилище.

**Kibana** — платформа визуализации. Используется для поиска по логам (инструмент **Discover**), создания дашбордов и управления жизненным циклом данных.

**ECK (Elastic Cloud on Kubernetes)** — (рекомендуемый в 2026 г.) оператор для управления стеком Elastic в K8s, обеспечивающий автоматизацию обновлений, ротацию сертификатов и масштабирование. В современной архитектуре ECK управляет ядром (Elasticsearch + Kibana), а агенты (Fluent Bit) развертываются отдельно.

## Основные концепции

### Архитектура сбора данных

Fluent Bit развертывается как **DaemonSet**. Это гарантирует запуск одного агента на каждом рабочем узле кластера.
*   **Input**: Чтение файлов `/var/log/containers/*.log`.
*   **Filter (Kubernetes)**: Обращение к API-серверу K8s для сопоставления лога с конкретным подом, контейнером и его метками.
*   **Output**: Пересылка структурированного JSON в Elasticsearch.

### Управление жизненным циклом (ILM)

В промышленной эксплуатации логи не могут храниться вечно. Используются следующие механизмы:
*   **Hot-Warm-Cold архитектура**: Перемещение старых логов с быстрых SSD на дешевые HDD.
*   **Data Streams**: (введено в ES 7.9+) современный способ работы с временными рядами (логами), упрощающий автоматическую ротацию и управление индексами. Для использования Data Streams во Fluent Bit отключается `Logstash_Format` и задается конкретное имя потока через параметр `Index`.

### Безопасность по умолчанию

В Elasticsearch 8.x передача данных без TLS и без пароля заблокирована на уровне ядра. Необходимо:
1. Использовать автоматически сгенерированный (ECK) или заданный вручную (Helm) пароль для пользователя `elastic`.
2. Настроить Fluent Bit на использование HTTPS и проверку CA-сертификата (или временное игнорирование проверки `TLS.Verify Off` для self-signed сертификатов).

## Практические сценарии

### Развертывание ES и Kibana через ECK (Стандарт 2026)

В 2026 году развертывание базовых компонентов Elastic (Elasticsearch и Kibana) с помощью сырых Helm-чартов считается устаревшим (Legacy). SSoT-подходом является использование оператора ECK.

> **Важно:** Полное руководство по архитектуре ECK, включая настройку Hot-Warm-Cold, управление ресурсами и безопасность, доступно в документе **[Elastic Cloud on Kubernetes (ECK)](../../../ELK_Stack/elastic_cloud_on_k8s.md)**.

В рамках стека EFK оператор ECK берет на себя запуск базы данных и UI, после чего Fluent Bit настраивается на отправку логов в созданный оператором кластер.

### Развертывание через Helm (Классический подход)

Данный сценарий описывает установку всего стека с помощью официальных Helm-чартов.

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

Для работы с Elasticsearch 8.x необходимо добавить параметр `Suppress_Type_Name On` (так как типы индексов удалены). Для конфигурации используется файл `fluent-bit-values.yaml`.

```yaml
# fluent-bit-values.yaml
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

Применение конфигурации и запуск агента:

```bash
helm upgrade --install fluent-bit fluent/fluent-bit \
  --namespace logging \
  -f fluent-bit-values.yaml
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

*   [Конфигурация Fluent Bit](./fluentbit/fluentbit_configuration.md) — детальная настройка фильтров и парсеров в агенте.
*   [Практическое руководство по Kibana](./kibana_guide.md) — как искать логи и строить дашборды.
*   [Устранение неполадок EFK](./efk_stack_troubleshooting.md) — типичные ошибки при подключении и запуске стека.