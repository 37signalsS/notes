# Стек EFK в Kubernetes

> **Примечание:** Данный файл является основным руководством по развертыванию стека EFK в среде Kubernetes. Для решения возникающих проблем используйте [Устранение неполадок EFK](./efk_stack_troubleshooting.md).

> **Актуальные версии (август 2026):** Elasticsearch **8.19 LTS** (поддержка до июля 2027) или **9.x** (текущая стабильная линия 9.5.x). Рекомендуется использовать 8.19 LTS для production-сред с длительным циклом поддержки.

## Определения

**Стек EFK (Elasticsearch, Fluent Bit, Kibana)** — интегрированное решение для централизованного сбора, долговременного хранения и анализа логов в кластере Kubernetes. Стек реализует паттерн «сбор → хранение → визуализация».

**Elasticsearch** — ядро стека; распределенная база данных, оптимизированная для полнотекстового поиска и аналитики. Начиная с версии 8.x, функции безопасности (TLS и аутентификация) включены по умолчанию. Поддерживает архитектуру Hot-Warm-Cold-Frozen для оптимизации хранения данных разной давности.

**Fluent Bit** — высокопроизводительный агент (Log Shipper), написанный на C с минимальным потреблением памяти (~45 MB RAM). В стеке EFK отвечает за сбор логов с узлов, их парсинг, обогащение метаданными и отправку в хранилище. Поддерживает плагины для фильтрации, маршрутизации и балансировки нагрузки.

**Kibana** — платформа визуализации и аналитики. Используется для поиска по логам (инструмент **Discover**), создания дашбордов, настройки алертинга и управления жизненным циклом данных. В версиях 9.x добавлена поддержка Workflows и Agent Builder.

**ECK (Elastic Cloud on Kubernetes)** — (рекомендуемый в 2026 г.) оператор для управления стеком Elastic в K8s, обеспечивающий автоматизацию обновлений, ротацию сертификатов и масштабирование. В современной архитектуре ECK управляет ядром (Elasticsearch + Kibana), а агенты (Fluent Bit) развертываются отдельно. Подробное описание архитектуры и CRD доступно в [Elastic Cloud on Kubernetes (ECK)](../../../ELK_Stack/elastic_cloud_on_k8s.md).

**Data Stream** — современный способ организации временных данных (логов) в Elasticsearch (7.9+), автоматизирующий создание, ротацию и управление индексами. В отличие от traditional index patterns, Data Stream обеспечивает единый интерфейс для записи и поиска по данным разной давности.

**Index Lifecycle Management (ILM)** — механизм управления жизненным циклом индексов: автоматическое перемещение между tier'ами (Hot → Warm → Cold → Frozen), удаление устаревших данных и оптимизация производительности.

## Предварительные требования

### Hardware Requirements

Для production-кластера с 3 нодами (минимальная отказоустойчивая конфигурация):

| Компонент | CPU | RAM | Диск | Количество подов |
| :--- | :--- | :--- | :--- | :--- |
| **Elasticsearch** | 4+ ядра | 16+ GB | 100+ GB SSD | 3 (min. для кворума) |
| **Kibana** | 2+ ядра | 4+ GB | 10 GB | 1-2 (для HA) |
| **Fluent Bit** | 0.5 ядра | 512 MB | - | 1 на узел (DaemonSet) |

**Для development/test:** Достаточно 1 ноды Elasticsearch с 2 ядрами и 4 GB RAM.

### Software Requirements

- **Kubernetes:** 1.25+ (рекомендуется 1.28+ для ECK 3.x)
- **Helm:** 3.10+ (для управления чартами)
- **kubectl:** версия, совместимая с кластером
- **StorageClass:** С поддержкой dynamic provisioning (для PV)
- **Сеть:** Доступность API-сервера Kubernetes для Fluent Bit (фильтр Kubernetes)

### Network Requirements

| Компонент | Порт | Протокол | Назначение |
| :--- | :--- | :--- | :--- |
| **Elasticsearch** | 9200 | HTTPS | REST API |
| **Elasticsearch** | 9300 | TCP | Transport (внутренний кластер) |
| **Kibana** | 5601 | HTTPS | Web UI |
| **Fluent Bit** | - | HTTPS | Отправка логов в Elasticsearch |

## Основные концепции

### Архитектура сбора данных

Fluent Bit развертывается как **DaemonSet**. Это гарантирует запуск одного агента на каждом рабочем узле кластера.
*   **Input**: Чтение файлов `/var/log/containers/*.log`.
*   **Filter (Kubernetes)**: Обращение к API-серверу K8s для сопоставления лога с конкретным подом, контейнером и его метками.
*   **Filter (Parser)**: Парсинг JSON-логов, извлечение полей, обогащение данными.
*   **Output**: Пересылка структурированного JSON в Elasticsearch.

**Поток данных:**
```
Pod → /var/log/containers/*.log → Fluent Bit → (Filter) → Elasticsearch → Kibana
```

### Управление жизненным циклом (ILM)

В промышленной эксплуатации логи не могут храниться вечно. Используются следующие механизмы:
*   **Hot-Warm-Cold-Frozen архитектура**: Перемещение старых логов с быстрых SSD на дешевые HDD и object storage.
*   **Data Streams**: (введено в ES 7.9+) современный способ работы с временными рядами (логами), упрощающий автоматическую ротацию и управление индексами. Для использования Data Streams во Fluent Bit отключается `Logstash_Format` и задается конкретное имя потока через параметр `Index`.

**Пример ILM-политики для логов:**
- **Hot:** 7 дней (SSD, высокая производительность)
- **Warm:** 30 дней (HDD, средняя производительность)
- **Cold:** 90 дней (compressed, низкая производительность)
- **Frozen:** >90 дней (S3/GCS, поиск через searchable snapshots)
- **Delete:** >365 дней

### Безопасность по умолчанию

В Elasticsearch 8.x передача данных без TLS и без пароля заблокирована на уровне ядра. Необходимо:
1. Использовать автоматически сгенерированный (ECK) или заданный вручную (Helm) пароль для пользователя `elastic`.
2. Настроить Fluent Bit на использование HTTPS и проверку CA-сертификата (или временное игнорирование проверки `TLS.Verify Off` для self-signed сертификатов).
3. Рекомендуется использовать Service Accounts или API Keys вместо статических паролей для автоматизации.

## Практические сценарии

### 0. Проверка готовности кластера

Перед развертыванием EFK убедитесь, что кластер готов:

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Server Version: v1.28.x+

# Проверка доступных узлов
kubectl get nodes -o wide
# → все узлы в состоянии Ready

# Проверка StorageClass
kubectl get sc
# → есть StorageClass с dynamic provisioning

# Проверка доступности ресурсов
kubectl top nodes
# → достаточно CPU/RAM для Elasticsearch (минимум 4 ядра, 16 GB RAM на узел)
```

### 1. Развертывание ES и Kibana через ECK (Стандарт 2026)

В 2026 году развертывание базовых компонентов Elastic (Elasticsearch и Kibana) с помощью сырых Helm-чартов считается устаревшим (Legacy). SSoT-подходом является использование оператора ECK.

> **Важно:** Полное руководство по архитектуре ECK, включая настройку Hot-Warm-Cold, управление ресурсами и безопасность, доступно в документе **[Elastic Cloud on Kubernetes (ECK)](../../../ELK_Stack/elastic_cloud_on_k8s.md)**.

В рамках стека EFK оператор ECK берет на себя запуск базы данных и UI, после чего Fluent Bit настраивается на отправку логов в созданный оператором кластер.

**Быстрый старт с ECK:**

```bash
# 1. Установка оператора ECK
helm repo add elastic https://helm.elastic.co
helm repo update
helm install elastic-operator elastic/eck-operator -n elastic-system --create-namespace

# 2. Ожидание готовности оператора
kubectl wait --for=condition=ready pod -l control-plane=elastic-operator -n elastic-system --timeout=120s

# 3. Создание namespace для логов
kubectl create ns logging

# 4. Создание Elasticsearch кластера (3 ноды)
cat <<EOF | kubectl apply -f -
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: elasticsearch
  namespace: logging
spec:
  version: 8.19.0
  nodeSets:
  - name: default
    count: 3
    config:
      node.store.allow_mmap: false
    podTemplate:
      spec:
        containers:
        - name: elasticsearch
          resources:
            requests:
              memory: 16Gi
              cpu: 2
            limits:
              memory: 16Gi
              cpu: 2
    volumeClaimTemplates:
    - metadata:
        name: elasticsearch-data
      spec:
        accessModes:
        - ReadWriteOnce
        resources:
          requests:
            storage: 100Gi
        storageClassName: fast-ssd
EOF

# 5. Ожидание готовности Elasticsearch
kubectl get pods -n logging -w
# → все поды в состоянии Running и Ready

# 6. Создание Kibana
cat <<EOF | kubectl apply -f -
apiVersion: kibana.k8s.elastic.co/v1
kind: Kibana
metadata:
  name: kibana
  namespace: logging
spec:
  version: 8.19.0
  count: 1
  elasticsearchRef:
    name: elasticsearch
EOF

# 7. Получение пароля для пользователя elastic
kubectl get secret elasticsearch-es-elastic-user -n logging -o jsonpath="{.data.elastic}" | base64 -d
# → сохраните этот пароль!

# 8. Доступ к Kibana (port-forward)
kubectl port-forward -n logging svc/kibana-kb-http 5601:5601
# → откройте http://localhost:5601 в браузере
```

### 2. Развертывание через Helm (Классический подход)

Данный сценарий описывает установку всего стека с помощью официальных Helm-чартов. Подходит для development/test сред или когда ECK не доступен.

> **Важно:** Для production-сред рекомендуется использовать ECK (см. сценарий 1).

#### 2.1. Подготовка окружения

```bash
# Создание namespace
kubectl create ns logging

# Добавление репозиториев
helm repo add elastic https://helm.elastic.co
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update

# Проверка доступных чартов
helm search repo elastic/elasticsearch
# → VERSION 8.19.0, APP VERSION 8.19.0
```

#### 2.2. Установка Elasticsearch (с безопасностью)

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

**Параметры конфигурации:**
- `replicas`: Количество узлов Elasticsearch (минимум 3 для отказоустойчивости)
- `secret.password`: Пароль для пользователя `elastic`
- `esJavaOpts`: JVM heap size (рекомендуется 50% от available RAM, максимум 32 GB)
- `resources.requests.memory`: Объем памяти для контейнера
- `volumeClaimTemplate.resources.requests.storage`: Размер PersistentVolume

> **Важно:** Если пароль не задан, извлеките его командой:
> `kubectl get secret elasticsearch-master-credentials -n logging -o jsonpath="{.data.password}" | base64 -d`

**Проверка установки:**
```bash
kubectl get pods -n logging -l app=elasticsearch
# → elasticsearch-master-0   1/1     Running   0          5m
# → elasticsearch-master-1   1/1     Running   0          5m
# → elasticsearch-master-2   1/1     Running   0          5m

kubectl exec -it elasticsearch-master-0 -n logging -- curl -s localhost:9200/_cluster/health?pretty
# → "status": "green" (или "yellow" если replica shards не назначены)
```

#### 2.3. Установка Fluent Bit

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
        Logstash_DateFormat %Y.%m.%d
```

**Параметры конфигурации:**
- `Name`: Тип аутпута (elasticsearch)
- `Match`: Маска для фильтрации логов (все логи)
- `Host`: Имя сервиса Elasticsearch в кластере
- `Port`: Порт Elasticsearch (9200)
- `HTTP_User` / `HTTP_Passwd`: Учетные данные для аутентификации
- `TLS`: Включение шифрования (обязательно для 8.x)
- `TLS.Verify`: Проверка CA-сертификата (отключить для self-signed)
- `Suppress_Type_Name`: Отключение поля _type (удалено в 8.x)
- `Logstash_Format`: Использование формата имён индексов Logstash
- `Logstash_Prefix`: Префикс имени индекса (kube-logs-YYYY.MM.DD)
- `Logstash_DateFormat`: Формат даты в имени индекса

Применение конфигурации и запуск агента:

```bash
helm upgrade --install fluent-bit fluent/fluent-bit \
  --namespace logging \
  -f fluent-bit-values.yaml
```

**Проверка установки:**
```bash
kubectl get pods -n logging -l app.kubernetes.io/name=fluent-bit
# → fluent-bit-xxxxx   1/1     Running   0          2m

kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=10
# → [2026/08/27 10:00:00] [ info] [engine] flush length defaults to 1440
# → [2026/08/27 10:00:00] [ info] [output:es:es.0] host=elasticsearch-master.logging.svc port=9200
```

#### 2.4. Установка Kibana

```bash
helm upgrade --install kibana elastic/kibana \
  --namespace logging \
  --set elasticsearchHosts="https://elasticsearch-master:9200" \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host="kibana.example.com"
```

**Проверка установки:**
```bash
kubectl get pods -n logging -l app=kibana
# → kibana-kibana-xxxxx   1/1     Running   0          3m

kubectl port-forward -n logging svc/kibana-kb-http 5601:5601
# → откройте http://localhost:5601 в браузере
# → войдите с логином elastic и паролем из шага 2.2
```

### 3. Настройка Index Lifecycle Management (ILM)

ILM автоматизирует управление жизненным циклом индексов (перемещение между tier'ами, удаление устаревших данных).

```bash
# Создание ILM-политики для логов
curl -X PUT "https://localhost:9200/_ilm/policy/logs-lifecycle" \
  -u elastic:YourSecurePass123! \
  -H 'Content-Type: application/json' \
  -d '{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_primary_shard_size": "30gb",
            "max_age": "7d"
          },
          "set_priority": {
            "priority": 100
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "shrink": {
            "number_of_shards": 1
          },
          "forcemerge": {
            "max_num_segments": 1
          },
          "set_priority": {
            "priority": 50
          }
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "set_priority": {
            "priority": 0
          }
        }
      },
      "delete": {
        "min_age": "365d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'
```

**Применение политики к индексу:**
```bash
# Создание шаблона индекса с ILM
curl -X PUT "https://localhost:9200/_index_template/logs-template" \
  -u elastic:YourSecurePass123! \
  -H 'Content-Type: application/json' \
  -d '{
  "index_patterns": ["kube-logs-*"],
  "template": {
    "settings": {
      "index.lifecycle.name": "logs-lifecycle",
      "index.lifecycle.rollover_alias": "kube-logs"
    }
  }
}'
```

### 4. Настройка Network Policies

Для ограничения трафика между компонентами EFK:

```yaml
# elasticsearch-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: elasticsearch-allow-only-authorized
  namespace: logging
spec:
  podSelector:
    matchLabels:
      elasticsearch.k8s.elastic.co/cluster-name: elasticsearch
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: logging
    - podSelector:
        matchLabels:
          app: kibana
    - podSelector:
        matchLabels:
          app: fluent-bit
    ports:
    - port: 9200
      protocol: TCP
    - port: 9300
      protocol: TCP
```

**Применение:**
```bash
kubectl apply -f elasticsearch-network-policy.yaml
```

### 5. Настройка мониторинга стека EFK

Для мониторинга состояния Elasticsearch и Kibana:

```bash
# Проверка состояния кластера
curl -s -u elastic:YourSecurePass123! "https://localhost:9200/_cluster/health?pretty"
# → status: green/yellow/red

# Проверка использования диска
curl -s -u elastic:YourSecurePass123! "https://localhost:9200/_cat/allocation?v"
# → shards disk.indices disk.used disk.avail disk.total disk.percent host node

# Проверка индексов
curl -s -u elastic:YourSecurePass123! "https://localhost:9200/_cat/indices?v&s=index"
# → health status index                                    uuid                   pri rep docs.count docs.deleted store.size pri.store.size

# Проверка ILM статуса
curl -s -u elastic:YourSecurePass123! "https://localhost:9200/_ilm/explain/kube-logs-*?pretty"
```

### Оптимизация производительности

*   **Resources**: Всегда устанавливайте `requests` равными `limits` для памяти в Elasticsearch, чтобы избежать OOM Killer при всплесках нагрузки.
*   **Buffers**: Если Fluent Bit не успевает отправлять логи (Backpressure), настройте `Mem_Buf_Limit` в секции Input, чтобы предотвратить переполнение памяти агента.
*   **Disk**: Используйте `StorageClass` с быстрым SSD (например, `gp3` в AWS или `ssd-persistent-disk` в GCP).
*   **Shards**: Оптимальный размер shard - 20-40 GB. Избегайте большого количества мелких shard'ов.
*   **Replicas**: Для production устанавливайте минимум 1 replica. Для development/test можно использовать 0.

## Best Practices

### Production Recommendations

1. **Отказоустойчивость:**
   - Минимум 3 узла Elasticsearch (для кворума)
   - Kibana с replicas >= 2 (для HA)
   - Fluent Bit на каждом узле (DaemonSet)

2. **Безопасность:**
   - Включите TLS для всех компонентов
   - Используйте Service Accounts вместо статических паролей
   - Настройте RBAC для ограничения доступа
   - Включите Audit Logs

3. **Производительность:**
   - Настройте JVM heap size (50% от RAM, макс. 32 GB)
   - Используйте SSD для Hot tier
   - Настройте ILM для автоматической ротации
   - Ограничивайте количество shard'ов

4. **Мониторинг:**
   - Настройте алертинг на основе метрик Elasticsearch
   - Мониторьте использование диска и памяти
   - Отслеживайте логи Fluent Bit

### Cleanup

Для полного удаления стека EFK:

```bash
# Удаление через Helm
helm uninstall kibana -n logging
helm uninstall fluent-bit -n logging
helm uninstall elasticsearch -n logging

# Удаление PVC (если нужно)
kubectl delete pvc -n logging -l app=elasticsearch

# Удаление namespace
kubectl delete ns logging
```

## Дополнительная информация

*   [Конфигурация Fluent Bit](./fluentbit/fluentbit_configuration.md) — детальная настройка фильтров и парсеров в агенте.
*   [Практическое руководство по Kibana](./kibana_guide.md) — как искать логи и строить дашборды.
*   [Устранение неполадок EFK](./efk_stack_troubleshooting.md) — типичные ошибки при подключении и запуске стека.
*   [Elastic Cloud on Kubernetes (ECK)](../../../ELK_Stack/elastic_cloud_on_k8s.md) — подробное руководство по архитектуре ECK.

### Мониторинг и безопасность

*   [Интеграция с Prometheus/Grafana](./efk_monitoring_integration.md) — настройка мониторинга компонентов EFK.
*   [RBAC и безопасность](./efk_rbac_security.md) — настройка Role-Based Access Control и security policies.
*   [Бэкап и восстановление](./efk_backup_restore.md) — стратегии бэкапа Elasticsearch и procedures восстановления.

### Высокая доступность и масштабирование

*   [Высокая доступность](./efk_high_availability.md) — настройка HA для всех компонентов EFK.
*   [Масштабирование Fluent Bit](./efk_fluentbit_scaling.md) — оптимизация производительности и масштабирование агента.
*   [Multi-cluster логирование](./efk_multi_cluster.md) — архитектура и настройка multi-cluster сценариев.

### Управление конфигурацией

*   [GitOps для EFK](./efk_gitops.md) — управление конфигурацией через Git с ArgoCD/Flux.