# Устранение неполадок стека EFK в Kubernetes

> **Примечание:** Данный файл является специализированным руководством по диагностике в среде Kubernetes. Общие концепции и базовое решение проблем поиска описаны в документе [Elasticsearch: Обзор](../../../ELK_Stack/Elasticsearch/elasticsearch_overview.md).

## Определения

**[CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md)** — статус циклической перезагрузки контейнера. Частая причина для Fluent Bit — ошибки конфигурации или недоступность Elasticsearch. Подробный алгоритм диагностики доступен в [Диагностика CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md).

**OOMKilled (Out Of Memory)** — прерывание процесса (например, Fluent Bit или Elasticsearch) ядром Linux (OOM Killer) из-за превышения установленных лимитов памяти (`limits.memory`). Подробный разбор механизмов и решений — в [Диагностика OOMKilled](../../Troubleshooting/Common_Errors/oomkilled_pods.md).

**`mapper_parsing_exception`** — ошибка в Elasticsearch, возникающая при несоответствии типа данных поля (например, число вместо строки) в новом документе ранее определенному маппингу индекса или Data Stream.

**`security_exception`** — (характерно для 8.x) ошибка аутентификации. Возникает при использовании неверных учетных данных или отсутствии прав у пользователя `elastic`/`fluent-bit`.

**`es_rejected_execution_exception`** — ошибка переполнения очереди запросов в Elasticsearch. Возникает при превышении лимита одновременных запросов (typically >200 запросов/сек на узел). Требует масштабирования кластера или оптимизации запросов.

**`circuit_breaking_exception`** — ошибка срабатывания circuit breaker'а в Elasticsearch. Защита от OOM: когда запрос потребляет слишком много памяти (> по умолчанию 60% от JVM heap), Elasticsearch прерывает его.

**Backpressure** — состояние, при котором Fluent Bit не успевает отправлять логи в Elasticsearch из-за перегрузки приемной стороны. Проявляется в росте `fluentbit_output_retries_total` и замедлении обработки.

**Статусы здоровья кластера (Cluster Health)**:
*   **Green**: все шарды (основные и реплики) распределены и доступны.
*   **Yellow**: все основные шарды доступны, но некоторые реплики не распределены (кластер уязвим к сбоям узлов).
*   **Red**: часть основных шардов недоступна (потеря данных или частичная неработоспособность).

## Основные концепции диагностики

Процесс поиска неисправностей в Kubernetes должен быть последовательным и основываться на системном подходе:

### Пошаговый алгоритм диагностики

1.  **Инспекция ресурсов**: проверка статуса подов и событий.
    ```bash
    # Просмотр всех подов в namespace
    kubectl get pods -n logging -o wide
    # → NAME                        READY   STATUS    RESTARTS   AGE   IP           NODE
    # → elasticsearch-master-0      1/1     Running   0          10m   10.0.1.100   node-1

    # Детальная информация о поде (события, условия, контейнеры)
    kubectl describe pod <pod-name> -n logging
    # → Events: Normal Pulled Successfully pulled image "..."
    # → Warning BackOff Back-off restarting failed container

    # Проверка событий в namespace (последние 50)
    kubectl get events -n logging --sort-by='.lastTimestamp' | tail -50
    ```

2.  **Анализ логов**: изучение вывода компонентов.
    ```bash
    # Для Fluent Bit (поиск ошибок OUTPUT)
    kubectl logs -l app.kubernetes.io/name=fluent-bit -n logging --tail=100
    # → [2026/08/27 10:00:00] [error] [output:es:es.0] HTTP status=401

    # Для Elasticsearch (поиск причин Red status)
    kubectl logs elasticsearch-master-0 -n logging | grep -i "error"
    # → [ERROR] [o.e.c.m.MetadataIndexTemplateService] [master-0] ... timeout

    # Просмотр логов с предыдущего краша (если под перезапустился)
    kubectl logs <pod-name> -n logging --previous --tail=50
    ```

3.  **Сетевая связность и TLS**: проверка доступности API и сертификатов.
    ```bash
    # Проверка DNS-резолва сервиса Elasticsearch
    kubectl exec <fluent-bit-pod> -n logging -- nslookup elasticsearch-master.logging.svc
    # → Name:      elasticsearch-master.logging.svc
    # → Address:   10.0.1.50

    # Проверка порта Elasticsearch (должен отвечать)
    kubectl exec <fluent-bit-pod> -n logging -- nc -zv elasticsearch-master 9200
    # → Connection to elasticsearch-master 9200 port [tcp/*] succeeded!

    # Проверка доступности с игнорированием проверки сертификата (для 8.x)
    kubectl exec <fluent-bit-pod> -n logging -- curl -k -u elastic:$PASS https://elasticsearch-master:9200
    # → {
    # →   "name" : "elasticsearch-master-0",
    # →   "cluster_name" : "elasticsearch",
    # →   "cluster_uuid" : "...",
    # →   "version" : { "number" : "8.19.0" }
    # → }

    # Проверка сертификата TLS
    kubectl exec <fluent-bit-pod> -n logging -- openssl s_client -connect elasticsearch-master:9200 -servername elasticsearch-master.logging.svc 2>/dev/null | openssl x509 -noout -dates
    # → notBefore=Aug 27 00:00:00 2026 GMT
    # → notAfter=Nov 25 00:00:00 2026 GMT
    ```

4.  **Инструментальная отладка**: использование эфемерных контейнеров (для K8s 1.25+).
    ```bash
    # Запуск отладочного контейнера с инструментами
    kubectl debug <pod-name> -it --image=nicolaka/netshoot -n logging

    # Внутри эфемерного контейнера:
    curl -k -u elastic:$PASS https://elasticsearch-master:9200/_cluster/health?pretty
    dig elasticsearch-master.logging.svc
    tcpdump -i eth0 port 9200
    ```

5.  **Проверка ресурсов**: мониторинг потребления CPU и памяти.
    ```bash
    # Потребление ресурсов подами
    kubectl top pods -n logging
    # → NAME                        CPU(cores)   MEMORY(bytes)
    # → elasticsearch-master-0      1500m        12Gi
    # → fluent-bit-xxxxx            50m          45Mi

    # Потребление узлами
    kubectl top nodes
    # → NAME    CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
    # → node-1  3500m        87%    14Gi            87%
    ```

### Инструменты диагностики

| Инструмент | Назначение | Пример использования |
| :--- | :--- | :--- |
| `kubectl get events` | Просмотр событий кластера | `kubectl get events -n logging --sort-by='.lastTimestamp'` |
| `kubectl describe pod` | Детальная информация о поде | `kubectl describe pod elasticsearch-master-0 -n logging` |
| `kubectl logs` | Просмотр логов контейнера | `kubectl logs -l app=fluent-bit -n logging --tail=100` |
| `kubectl top` | Мониторинг ресурсов | `kubectl top pods -n logging` |
| `kubectl debug` | Отладка с эфемерными контейнерами | `kubectl debug <pod> -it --image=nicolaka/netshoot -n logging` |
| `_cluster/health` | Состояние кластера Elasticsearch | `curl -k -u elastic:$PASS https://localhost:9200/_cluster/health?pretty` |
| `_cat/allocation` | Распределение шардов и дисков | `curl -k -u elastic:$PASS https://localhost:9200/_cat/allocation?v` |
| `_cat/indices` | Список индексов | `curl -k -u elastic:$PASS https://localhost:9200/_cat/indices?v&s=index` |
| `_cluster/allocation/explain` | Объяснение распределения шардов | `curl -k -u elastic:$PASS https://localhost:9200/_cluster/allocation/explain?pretty` |
| `_ilm/explain` | Статус ILM политик | `curl -k -u elastic:$PASS https://localhost:9200/_ilm/explain/kube-logs-*?pretty` |

## Практические сценарии

### Сценарий 1: Проблемы безопасности и TLS (Elasticsearch 8.x)

**Симптом: Fluent Bit выдает ошибки "SSL handshake failed" или "401 Unauthorized".**

*   **SSL Certificate Unknown**: Если используется self-signed сертификат (по умолчанию в ECK и Helm 8.x), Fluent Bit должен либо доверять CA, либо иметь настройку `TLS.Verify Off` (не рекомендуется для prod).
    *   *Решение (ECK)*: Смонтируйте секрет `<cluster-name>-es-http-certs-public`, созданный оператором, в под Fluent Bit и укажите `TLS.CA_File`.
    *   *Решение (Helm)*: Извлеките CA из секрета `elasticsearch-master-certs` и передайте его во Fluent Bit.
*   **Authentication Error**: Пароль пользователя `elastic` был изменен или неверно передан в секрет.
    *   *Решение (ECK)*: Пароль автоматически генерируется в секрете `<cluster-name>-es-elastic-user`. Извлеките его: `kubectl get secret <cluster-name>-es-elastic-user -o jsonpath='{.data.elastic}' | base64 -d`.
    *   *Решение (Helm)*: Проверьте значение в секрете `elasticsearch-master-credentials`: `kubectl get secret elasticsearch-master-credentials -o jsonpath='{.data.password}' | base64 -d`.

**Диагностика:**
```bash
# Проверка сертификата в поде Fluent Bit
kubectl exec <fluent-bit-pod> -n logging -- openssl s_client -connect elasticsearch-master:9200 2>/dev/null | openssl x509 -noout -issuer -subject
# → issuer=CN = elasticsearch-http-certs-public
# → subject=CN = elasticsearch-master.logging.svc

# Проверка учетных данных
kubectl get secret elasticsearch-es-elastic-user -n logging -o jsonpath="{.data.elastic}" | base64 -d
# → YourSecurePass123!
```

### Сценарий 2: Проблемы сбора логов (Fluent Bit)

**Симптом: логи не появляются в Kibana, ошибок в Elasticsearch нет.**

*   **Неверные пути (Input)**: Агент ищет логи там, где их нет (например, `/var/lib/docker/containers` в кластерах с `containerd`).
    *   *Решение*: Проверьте `Path` в `[INPUT]`. Для современных кластеров K8s (где CRI — containerd или CRI-O) это обычно `/var/log/containers/*.log`.
*   **Backpressure (Mem_Buf_Limit) и OOMKilled**: Fluent Bit не успевает отправлять логи (из-за медленной сети или перегруженного ES), потребляет слишком много памяти и убивается OOM Killer-ом (статус пода `OOMKilled`).
    *   *Решение*: Установите жесткий лимит `Mem_Buf_Limit 50MB` в секции `[INPUT]`. Если буфер полон, агент приостановит чтение до освобождения места. Также рассмотрите включение дисковой буферизации (filesystem buffering).

**Диагностика:**
```bash
# Проверка метрик Fluent Bit (если включен Prometheus endpoint)
kubectl port-forward -n logging svc/fluent-bit 2020:2020
curl -s http://localhost:2020/api/v1/metrics | grep fluentbit_output
# → fluentbit_output_errors_total{...} 0
# → fluentbit_output_retries_total{...} 5

# Проверка наличия логов в Pod
kubectl exec <fluent-bit-pod> -n logging -- ls -la /var/log/containers/
# → total 0
# → drwxr-xr-x 7 root root  224 Aug 27 10:00 .

# Проверка чтения логов (внутри контейнера)
kubectl exec <fluent-bit-pod> -n logging -- cat /var/log/containers/*.log | head -5
# → {"log":"...","stream":"stdout","time":"2026-08-27T10:00:00.000000000Z"}
```

### Сценарий 3: Деградация кластера Elasticsearch (Red/Yellow)

**Симптом: медленный поиск, ошибки записи, статус Red.**

*   **Low Disk Watermark**: Диск заполнен на 85-90%. ES переводит индексы в `read-only`.
    *   *Решение*: Расширьте PVC или удалите старые индексы. Сбросьте блокировку через API кластера (выполняется изнутри кластера или через проброс портов):
        ```bash
        kubectl exec -it elasticsearch-master-0 -n logging -- curl -k -XPUT -u elastic:$PASS "https://localhost:9200/_all/_settings" -H 'Content-Type: application/json' -d'{"index.blocks.read_only_allow_delete": null}'
        ```
*   **Unassigned Shards**: Шарды не могут быть размещены (например, из-за нехватки узлов для реплик).
    *   *Решение*: Проверьте причину неразмещения через Allocation Explain API:
        ```bash
        kubectl exec -it elasticsearch-master-0 -n logging -- curl -k -u elastic:$PASS "https://localhost:9200/_cluster/allocation/explain?pretty"
        ```

**Диагностика:**
```bash
# Проверка состояния кластера
kubectl exec elasticsearch-master-0 -n logging -- curl -k -u elastic:$PASS "https://localhost:9200/_cluster/health?pretty"
# → {
# →   "status" : "yellow",
# →   "number_of_nodes" : 3,
# →   "number_of_data_nodes" : 3,
# →   "active_primary_shards" : 10,
# →   "active_shards" : 15,
# →   "relocating_shards" : 0,
# →   "initializing_shards" : 0,
# →   "unassigned_shards" : 5
# → }

# Просмотр распределения дискового пространства
kubectl exec elasticsearch-master-0 -n logging -- curl -k -u elastic:$PASS "https://localhost:9200/_cat/allocation?v"
# → shards disk.indices disk.used disk.avail disk.total disk.percent host      node
# →     5          123    45.2gb     54.8gb    100.0gb           45   10.0.1.100 elasticsearch-master-0
```

### Сценарий 4: Конфликты маппинга (Mapping Conflicts)

**Симптом: Ошибка `mapper_parsing_exception` в логах Fluent Bit.**

*   **Причина**: В одном индексе поле `request_time` — это `float`, а в новом логе пришла строка `"0.05"`.
*   **Решение**:
    1.  Используйте `Replace_Dots On` во Fluent Bit, чтобы избежать конфликтов с вложенными объектами.
    2.  Настройте Ingest Pipeline в Elasticsearch для принудительного приведения типов.
    3.  При использовании **Data Streams** — обновите Index Template и дождитесь ротации (`rollover`).

### Сценарий 5: Проблемы с Circuit Breaker

**Симптом: Ошибка `circuit_breaking_exception` в логах Elasticsearch.**

*   **Причина**: Запрос потребляет слишком много памяти (>60% от JVM heap по умолчанию).
*   **Решение**:
    1.  Увеличьте лимиты памяти для контейнера Elasticsearch.
    2.  Оптимизируйте запросы (уменьшите `size`, используйте `source filtering`).
    3.  Настройте circuit breaker'ы в `elasticsearch.yml`:
        ```yaml
        indices.breaker.request.limit: 60%
        indices.breaker.total.limit: 70%
        ```

**Диагностика:**
```bash
# Проверка статуса circuit breaker'ов
kubectl exec elasticsearch-master-0 -n logging -- curl -k -u elastic:$PASS "https://localhost:9200/_nodes/stats/breaker?pretty"
# → "breakers" : {
# →   "request" : {
# →     "limit_size_in_bytes" : 6442450944,
# →     "limit_size" : "6gb",
# →     "estimated_size_in_bytes" : 3221225472,
# →     "estimated_size" : "3gb",
# →     "overhead" : 1.0,
# →     "tripped" : 0
# →   }
# → }
```

### Сценарий 6: Проблемы с производительностью поиска

**Симптом: Медленные запросы в Kibana, тайм-ауты при поиске.**

*   **Причина**: Большие индексы, неоптимизированные запросы, нехватка ресурсов.
*   **Решение**:
    1.  Настройте ILM для автоматической ротации индексов.
    2.  Используйте `source filtering` для возврата только нужных полей.
    3.  Ограничивайте временной диапазон в запросах.
    4.  Добавьте данные узлов Elasticsearch или увеличьте ресурсы.

**Диагностика:**
```bash
# Проверка медленных запросов
kubectl exec elasticsearch-master-0 -n logging -- curl -k -u elastic:$PASS "https://localhost:9200/_nodes/hot_threads?threads=5&interval=500ms"
# → :::
# →   CPU usage (this node):
# →     0% (0ms out of 500ms) flushes
# →     0% (0ms out of 500ms) syncing
# →     0% (0ms out of 500ms) writing

# Проверка индексов с наибольшим количеством документов
kubectl exec elasticsearch-master-0 -n logging -- curl -k -u elastic:$PASS "https://localhost:9200/_cat/indices?v&s=docs.count:desc&h=index,docs.count,store.size"
# → index                              docs.count store.size
# → kube-logs-2026.08.27               1234567    2.3gb
# → kube-logs-2026.08.26               987654     1.8gb
```

### Сценарий 7: Проблемы с сетевой связностью

**Симптом: Fluent Bit не может подключиться к Elasticsearch, ошибки "Connection refused" или "Timeout".**

*   **Причина**: Неверный DNS, NetworkPolicy блокирует трафик, Elasticsearch не доступен.
*   **Решение**:
    1.  Проверьте DNS-резолв сервиса Elasticsearch.
    2.  Проверьте NetworkPolicy в namespace `logging`.
    3.  Убедитесь, что Elasticsearch запущен и слушает порт 9200.

**Диагностика:**
```bash
# Проверка DNS из пода Fluent Bit
kubectl exec <fluent-bit-pod> -n logging -- nslookup elasticsearch-master.logging.svc
# → Name:      elasticsearch-master.logging.svc
# → Address:   10.0.1.50

# Проверка сетевого трафика (с использованием tcpdump)
kubectl exec <fluent-bit-pod> -n logging -- tcpdump -i eth0 port 9200 -c 5
# → 10:00:00.000000 IP 10.0.1.100.45678 > 10.0.1.50.9200: Flags [S], seq 1234567890, win 65535, options [mss 1460,sackOK,TS val 123456 ecr 0,nop,wscale 7], length 0

# Проверка доступности сервиса
kubectl exec <fluent-bit-pod> -n logging -- curl -s -o /dev/null -w "%{http_code}" https://elasticsearch-master:9200
# → 200
```

### Сценарий 8: Проблемы с PersistentVolume (Elasticsearch)

**Симптом: Под Elasticsearch в состоянии `Pending` или `CrashLoopBackOff` из-за проблем с диском.**

*   **Причина**: PersistentVolume не может быть provisioned, диск заполнен, или PVC не привязан.
*   **Решение**:
    1.  Проверьте статус PVC.
    2.  Убедитесь, что StorageClass существует и поддерживает dynamic provisioning.
    3.  Расширьте PV или освободите место.

**Диагностика:**
```bash
# Проверка PVC
kubectl get pvc -n logging
# → NAME                                      STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → elasticsearch-data-elasticsearch-master-0  Bound    pvc-abc123                                 100Gi      RWO            fast-ssd       10m

# Проверка PV
kubectl get pv
# → NAME                                       CAPACITY   RECLAIM POLICY   STATUS   CLAIM                                         STORAGECLASS
# → pvc-abc123                                 100Gi      Delete           Bound    logging/elasticsearch-data-elasticsearch-master-0   fast-ssd

# Проверка использования диска в поде Elasticsearch
kubectl exec elasticsearch-master-0 -n logging -- df -h
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1       100G   45G   55G  45% /usr/share/elasticsearch/data
```

### Сценарий 9: Проблемы с ресурсами (CPU Throttling)

**Симптом: Медленная работа Elasticsearch, высокий latency при нормальном CPU usage.**

*   **Причина**: CFS Throttling — контейнер ограничивается в CPU из-за превышения лимитов.
*   **Решение**:
    1.  Увеличьте `limits.cpu` для контейнера Elasticsearch.
    2.  Используйте Guaranteed QoS (requests = limits).
    3.  Настройте `cpuManagerPolicy` в kubelet.

**Диагностика:**
```bash
# Проверка CPU throttling через cgroup
kubectl exec elasticsearch-master-0 -n logging -- cat /sys/fs/cgroup/cpu/cpu.stat
# → nr_periods 123456
# → nr_throttled 789
# → throttled_time 12345678900

# Проверка лимитов CPU
kubectl exec elasticsearch-master-0 -n logging -- cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us
# → 200000

# Проверка потребления CPU
kubectl exec elasticsearch-master-0 -n logging -- top -bn1 | head -5
# → PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
# →   1 elastic   20   0  12.3g   8.5g  123m S  150.0  53.1   10:23.45 java
```

## Дополнительная информация

*   [Настройка стека EFK](./efk_stack_setup_guide.md) — развертывание и базовые параметры.
*   [Практическое руководство по Kibana](./kibana_guide.md) — поиск логов и решение проблем с неразобранными JSON.
*   [Конфигурация Fluent Bit](./fluentbit/fluentbit_configuration.md) — настройка фильтров, парсеров и оптимизация производительности.
*   [Управление индексами (ILM)](../../../ELK_Stack/Elasticsearch/elasticsearch_ilm_and_retention.md) — настройка автоматической очистки старых данных для предотвращения ошибки заполнения диска.
*   [Elastic Cloud on Kubernetes (ECK)](../../../ELK_Stack/elastic_cloud_on_k8s.md) — подробное руководство по архитектуре ECK и управлению кластерами Elasticsearch.
*   [Диагностика CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md) — пошаговый алгоритм поиска причин перезагрузки контейнеров.
*   [Диагностика OOMKilled](../../Troubleshooting/Common_Errors/oomkilled_pods.md) — решение проблем с нехваткой памяти в контейнерах.
