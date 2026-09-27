# Prometheus Operator: Диагностика и устранение неисправностей

## Определения

**Troubleshooting Prometheus Operator** — системный процесс выявления и устранения сбоев в работе контроллера, механизмов генерации конфигурации, обнаружения целей (Service Discovery) и конвейера обработки метрик в Kubernetes.

**Цикл Reconciliation (Сверка)** — механизм работы Оператора (Watch → Generate → Apply → Reload), при котором он приводит текущее состояние объектов (Pod, Secret, StatefulSet) в соответствие с декларативным описанием в CRD.

**CEL-валидация (Common Expression Language)** — механизм проверки корректности CRD на стороне API-сервера Kubernetes, предотвращающий создание некорректных ресурсов (например, отрицательных интервалов скрейпинга) до того, как они попадут в Оператор.

**Config-Reloader** — sidecar-контейнер, выполняющий мониторинг обновлений конфигурации в Secret и инициализирующий перезагрузку основного процесса Prometheus/Alertmanager через HTTP API.

**EndpointSlice** — объект Kubernetes API, содержащий IP-адреса и порты эндпоинтов Service. С версии v0.80+ Prometheus Operator использует EndpointSlice вместо устаревшего Endpoints для Service Discovery.

**Stale Marker** — специальный маркер (`stale NaN`), который Prometheus отправляет для всех метрик пода при его остановке или перезапуске. Используется下游 системами для определения исчезновения источника данных.

**Churn Rate** — скорость появления и исчезновения временных рядов в TSDB. Высокий churn (например, из-за короткоживущих подов) приводит к фрагментации индекса и росту потребления RAM.

---

## Базовые концепции

### Точки отказа в жизненном цикле конфигурации

| Этап | Механизм | Симптом сбоя | Инструмент диагностики |
| :--- | :--- | :--- | :--- |
| **Validation** | Admission Webhook / CEL | `kubectl apply` завершается с ошибкой | Текст ошибки в CLI, логи вебхука |
| **Watch** | K8s API Watch | Оператор игнорирует изменения в CRD | `kubectl get events`, RBAC (get/watch/list) |
| **Generate** | Operator Controller Logic | Конфигурация в Secret не обновляется | Логи Оператора: `failed to generate config` |
| **Apply** | K8s API (Secret/STS) | Ошибка `Too long` для Secret (1MB) | `kubectl describe secret`, статус Оператора |
| **Reload** | Sidecar Reloader | В UI Prometheus старые данные | Логи `config-reloader`, статус пода |

### Уровни изоляции проблем

1.  **Инфраструктурный:** Проблемы с RBAC, NetworkPolicy, DNS или доступностью API-сервера.
2.  **Логический:** Ошибки в селекторах (labels), неправильные порты или пути в ServiceMonitor.
3.  **Ресурсный:** OOMKilled, троттлинг процессора, переполнение диска (TSDB corruption).

### Таксономия состояний целей (Target States)

Prometheus классифицирует цель по состоянию здоровья:

| Состояние | Значение `health` | Типичные причины |
| :--- | :--- | :--- |
| **up** | `1` | Цель доступна, скрейпинг проходит успешно. |
| **down** | `0` | Цель недоступна: Connection Refused, Context Deadline Exceeded, timeout. |
| **stale** | — | Пода цели перезапущен, метки исчезли или scrapе прерван. |
| **absent** | — | Метрика полностью отсутствует в течение всего окна `--query.lookback-delta` (по умолчанию 5 минут). |

### Режимы сбоев скрейпинга

При скрейпинге Prometheus сталкивается с несколькими категориями ошибок:

*   **Connection Refused:** Целевой порт не открыт (пода не готова, Service неправильно настроен).
*   **Connection Timed Out:** Сетевой пакет не дошел до цели (NetworkPolicy, firewall, DNS не разрешает имя).
*   **Context Deadline Exceeded:** Цель доступна, но время ответа превышает `scrape_timeout`. Причина: перегрузка приложения или слишком агрессивный `timeout` в конфигурации.
*   **TLS Handshake Error:** Проблема с сертификатами, несовместимые версии TLS, `insecureSkipVerify: false` при самоподписанном сертификате.
*   **HTTP 4xx/5xx:** Приложение возвращает ошибку. `401/403` — проблема авторизации, `404` — неверный `metrics_path`, `500` — падение приложения.
*   **Invalid Metric Type:** Экспортер возвращает метрику с типом, несовместимым с ожидаемым (например, Summary вместо Histogram при включенных нативных гистограммах).

### Типичные причины ошибок reconciliation

| Категория | Причина | Влияние |
| :--- | :--- | :--- |
| **RBAC** | Operator не имеет прав `get/list/watch` на CRD или `update/create` на STS/Secret | Оператор игнорирует изменения, в логах `forbidden` |
| **CRD Mismatch** | Версия CRD старше версии Operator (или наоборот) | Поля игнорируются, ошибки `unknown field` в логах |
| **Etcd Latency** | Высокая загрузка API-сервера или etcd | Reconciliation занимает >30 секунд, цель не обновляется |
| **Resource Quota** | Превышен лимит pods/ Secrets в namespace | Operator не может создать/обновить объект |
| **Webhook Timeout** | Admission Webhook не отвечает за 10 секунд | `kubectl apply` зависает или падает с timeout |

---

## Алгоритм диагностики: «Цель не появилась или не скрейпится»

Если ресурс (ServiceMonitor/PodMonitor/ScrapeConfig) создан, но цели отсутствуют в Prometheus:

1.  **Проверка селекторов лейблов:**
    - Проверьте `serviceMonitorSelector` в ресурсе `Prometheus`. По умолчанию он может быть пустым (не выбирает ничего) или иметь жесткий фильтр (например, `release: kube-prometheus-stack`).
    - Проверьте лейблы на самом `ServiceMonitor`. Они должны строго соответствовать селектору Оператора.
2.  **Проверка селекторов пространств имен (Namespaces):**
    - Если монитор находится в другом namespace, в `Prometheus` должен быть настроен `serviceMonitorNamespaceSelector`. Чтобы искать во всех namespace, используйте `{}`.
3.  **Валидация Service и Endpoints:**
    - Проверьте наличие активных IP в `kubectl get ep <service-name>`. Если список пуст, Prometheus не найдет целей.
    - Убедитесь, что `port` в ServiceMonitor соответствует **имени порта** (name) или **номеру** в Service.
4.  **Анализ сгенерированного секрета:**
    - Изучите итоговый конфиг: `kubectl get secret prometheus-<name> -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip`.
    - Найдите `job_name`, соответствующую вашему монитору. Если её нет — Оператор не смог обработать ресурс.
5.  **Проверка статуса в UI:**
    - Перейдите в `Status -> Targets`. Если цель в `Down`, проверьте столбец `Error` (Connection Refused, Context Deadline, etc.).

---

## Практические сценарии

### 1. Превышение лимита Secret (1MB)

**Симптом:** Оператор выдает ошибку `Secret "..." is invalid: data: Too long`, новые мониторы не применяются.

*   **Причина:** Большое количество мониторов или сложные правила релейблинга раздувают `prometheus.yaml`.
*   **Решение:**
    1.  **Шардирование:** Настройте `spec.shards` в ресурсе Prometheus. Оператор разделит цели между репликами, уменьшив размер конфига каждой.
    2.  **Сжатие:** Убедитесь, что используется автоматическое сжатие конфига (включено по умолчанию в новых версиях).
    3.  **Оптимизация:** Удалите избыточные `relabel_configs` или используйте `ScrapeConfig` для более компактного описания.

### 2. Prometheus Agent и проблемы Remote Write

**Симптом:** Агент работает, но данные не поступают в центральное хранилище.

*   **Диагностика очереди (Shards):** Проверьте метрики `prometheus_remote_storage_shards`. Если количество шардов растет, алертинг может запаздывать.
*   **Ошибки авторизации:** Проверьте логи на наличие 401/403 ошибок от Remote Write endpoint.
    ```bash
    kubectl logs -l app.kubernetes.io/name=prometheus-agent -c prometheus
    ```
*   **NetworkPolicy:** Убедитесь, что поды Агента имеют доступ к внешнему IP/DNS хранилища.

### 3. Проблемы с CEL и Admission Webhooks

**Симптом:** Ошибки при создании ресурсов: `Internal error occurred: failed calling webhook`.

*   **Проверка вебхука:** Оператор использует порт 9443 для валидации ресурсов.
    ```bash
    kubectl get svc -n monitoring # Ищите сервис с портом 443 -> 9443
    kubectl get ep -n monitoring <operator-service-name> # Проверьте наличие IP
    ```
*   **TLS сертификаты:** Если сертификаты истекли или не созданы (cert-manager), API-сервер заблокирует создание CRD. Проверьте статус сертификата и аннотации в CRD.

### 4. Отладка правил релейблинга (Relabeling)

**Симптом:** Метки на метриках не соответствуют ожиданиям или цели отфильтровываются.

*   **Инструмент:** Используйте `prometheus-config-reloader` в режиме отладки или UI Prometheus (раздел `Service Discovery`), где показаны `Before Relabeling` и `After Relabeling` метки для каждой цели.
*   **Типичная ошибка:** Использование `action: keep` с неправильным `source_labels`, что приводит к удалению всех целей.

### 5. Ресурсные ограничения (OOMKilled)

**Симптом:** Prometheus постоянно перезагружается.

*   **Причина:** Объем данных в памяти (Head Block) превышает лимиты RAM.
*   **Диагностика:**
    ```bash
    kubectl describe pod prometheus-main-0 | grep -A 5 Last\ State
    # Ищите Reason: OOMKilled
    ```
*   **Решение:**
    1.  Увеличьте `resources.limits.memory`.
    2.  Уменьшите `retention` или используйте `retentionSize`.
    3.  Проверьте `scrape_interval` — слишком частый сбор увеличивает нагрузку.

### 6. NetworkPolicy блокирует скрейпинг

**Симптом:** Цели в статусе `down` с ошибкой `Connection Refused` или `context deadline exceeded`, хотя приложение работает.

*   **Диагностика:**
    ```bash
    # Проверка NetworkPolicy в namespace целевого приложения
    kubectl get networkpolicy -n <app-namespace>

    # Проверка, разрешен ли трафик от Prometheus
    kubectl describe networkpolicy -n <app-namespace> | grep -A5 prometheus
    ```
*   **Решение:**
    1.  Создайте NetworkPolicy, разрешающую трафик от ServiceAccount Prometheus на порт метрик целевых подов.
    2.  Для Alertmanager Gossip откройте порт `9094` (TCP и UDP) между репликами.
    3.  Если используется Cilium, проверьте L7-политики (FQDN-политики могут блокировать DNS-запросы).

### 7. DNS-проблемы и `NXDOMAIN`

**Симптом:** Цели не разрешаются, в логах Prometheus `lookup <service>.<namespace>.svc.cluster.local: NXDOMAIN`.

*   **Причина:** Кастомный `dnsPolicy` без корректных `nameservers`, отключенный CoreDNS или перегрузка DNS-кэша.
*   **Диагностика:**
    ```bash
    # Проверка DNS внутри пода Prometheus
    kubectl exec -n monitoring prometheus-main-0 -- nslookup kubernetes.default
    kubectl exec -n monitoring prometheus-main-0 -- cat /etc/resolv.conf
    ```
*   **Решение:**
    1.  Если используется `dnsPolicy: Custom`, убедитесь в наличии корректных `nameservers` в `dnsConfig`.
    2.  Проверьте статус CoreDNS: `kubectl get pods -n kube-system -l k8s-app=kube-dns`.
    3.  Увеличьте `dnsCacheSize` в ConfigMap CoreDNS при большом количестве сервисов.

### 8. Stale-метрики и ложные алерты при перезапуске

**Симптом:** Алерты на `absent()` срабатывают при rolling update Prometheus или перезапуске приложения.

*   **Причина:** При остановке пода Prometheus отправляет `stale NaN` для всех его метрик. Downstream-системы (Grafana, Alertmanager) интерпретируют отсутствие метрики как сбой.
*   **Решение:**
    1.  Используйте `ignoreStaleMarkers: true` в правилах, где это применимо.
    2.  Установите `for: 5m` (или больше) в алертах, чтобы пропустить кратковременные пропуски.
    3.  При rolling update StatefulSet Prometheus используйте `partition` для канарейчного обновления.

### 9. PodMonitor: цели не собираются без Service

**Симптом:** PodMonitor создан, но в `Status -> Targets` нет соответствующих целей.

*   **Причина:** Поды не имеют открытого порта метрик, не соответствуют селектору или находятся не в фазе `Running`.
*   **Диагностика:**
    ```bash
    # Проверка, что поды соответствуют селектору
    kubectl get pods -n <namespace> -l app=my-app -o wide

    # Проверка портов контейнера
    kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].ports[*].name}'
    ```
*   **Решение:**
    1.  Убедитесь, что `podMonitorSelector` в ресурсе `Prometheus` соответствует лейблам PodMonitor.
    2.  Имя порта в `podMetricsEndpoints.port` должно совпадать с именем порта в контейнере (case-sensitive).
    3.  Поды в `Pending` или `CrashLoopBackOff` не обнаруживаются PodMonitor по умолчанию.

### 10. StatefulSet не обновляется при изменении версии

**Симптом:** Изменение `spec.version` в ресурсе `Prometheus` не вызывает обновления пода.

*   **Причина:** `updateStrategy.rollingUpdate.partition` установлен в значение больше 0, или ресурс `PodDisruptionBudget` блокирует прерывание.
*   **Диагностика:**
    ```bash
    kubectl get statefulset prometheus-main -n monitoring -o yaml | grep -A5 partition
    kubectl get pdb -n monitoring
    ```
*   **Решение:**
    1.  Установите `partition: 0` для обновления всех подов одновременно.
    2.  Проверьте PDB: `kubectl describe pdb -n monitoring` — убедитесь, что `DisruptionsAllowed` > 0.

### 11. Alertmanager: Gossip-кластеризация не работает

**Сиymptom:** Алерты не дедуплицируются, в UI Alertmanager отображается только одна реплика.

*   **Причина:** Порт `9094` (TCP/UDP) заблокирован NetworkPolicy, или `clusterAdvertiseAddress` не настроен.
*   **Диагностика:**
    ```bash
    # Проверка порта Gossip между репликами
    kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- netstat -tulpn | grep 9094

    # Проверка логов кластеризации
    kubectl logs -n monitoring alertmanager-main-0 -c alertmanager | grep -i gossip
    ```
*   **Решение:**
    1.  Откройте порт `9094` (TCP и UDP) в NetworkPolicy между репликами Alertmanager.
    2.  При использовании Headless Service проверьте, что `clusterAdvertiseAddress` совпадает с IP пода.

### 12. CRD mismatch: Operator и CRD несовместимых версий

**Симптом:** В логах Operator ошибки `unknown field`, `no kind "Prometheus" is registered` или селекторы игнорируются.

*   **Причина:** CRD установлены версии v0.85, а Operator v0.92 (или наоборот). CEL-валидация в новых CRD использует поля, не доступные в старых версиях.
*   **Диагностика:**
    ```bash
    kubectl get crd | grep monitoring.coreos.com
    kubectl describe crd prometheuses.monitoring.coreos.com | grep -A3 "Versions:"
    ```
*   **Решение:**
    1.  Обновите CRD до версии, соответствующей Operator: `kubectl apply -f https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.92.0/stripped-down-crds.yaml`.
    2.  Никогда не используйте `kubectl apply` с CRD старой версии после обновления Operator.

### 13. Проблемы с хранилищем (PVC) и производительностью диска

**Симптом:** Высокая латентность скрейпинга, ошибки `write timeout`, slow compaction.

*   **Причина:** PVC на медленном диске (HDD), недостаточно IOPS или разделение WAL/Blocks на одном физическом носителе.
*   **Диагностика:**
    ```bash
    # Проверка IOPS и латентности диска внутри пода
    kubectl exec -n monitoring prometheus-main-0 -- iostat -x 1 5

    # Проверка типа StorageClass
    kubectl get storageclass
    ```
*   **Решение:**
    1.  Используйте отдельный PVC для WAL на NVMe SSD.
    2.  Для `storage.tsdb.retention.size` убедитесь, что StorageClass поддерживает `allowVolumeExpansion: true`.
    3.  Проверьте `mountOptions` в StorageClass: должны быть `noatime,nodiratime`.

### 14. Resource Quota и лимиты namespace

**Симптом:** Operator не создает StatefulSet, в событиях `exceeded quota`.

*   **Причина:** В namespace `monitoring` установлен ResourceQuota, ограничивающий количество pods, Secrets или объем запрашиваемых ресурсов.
*   **Диагностика:**
    ```bash
    kubectl get resourcequota -n monitoring
    kubectl get limitrange -n monitoring
    ```
*   **Решение:**
    1.  Увеличьте лимиты в ResourceQuota или добавьте исключения для `prometheus-operator`.
    2.  Проверьте LimitRange: если установлен `default`, Prometheus может получать меньше памяти, чем требуется.

### 15. Scrape timeout и `target_sync_length_seconds`

**Симптом:** Цели постоянно в `Down` с `Context Deadline Exceeded`, хотя приложение отвечает на `curl`.

*   **Причина:** `scrape_timeout` превышает `scrape_interval`, или метрики приложения слишком большие для парсинга за отведенное время.
*   **Диагностика:**
    ```bash
    # Проверка метрики задержки синхронизации
    kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
      | grep prometheus_target_sync_length_seconds

    # Проверка времени скрейпинга конкретной цели
    kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/api/v1/targets \
      | jq '.data.activeTargets[] | select(.health=="down") | {job, instance, error, lastScrape}'
    ```
*   **Решение:**
    1.  Увеличьте `scrape_timeout` в ServiceMonitor (должен быть меньше `scrape_interval`).
    2.  Для больших объемов метрик увеличьте `sample_limit` или используйте `metric_relabel_configs` для удаления не нужных рядов.
    3.  Проверьте, нет ли блокирующих I/O операций в приложении во время скрейпинга.

---

## Инструментарий диагностики

### Доступ к интерфейсам
```bash
# Доступ к Prometheus UI
kubectl port-forward svc/prometheus-operated -n monitoring 9090

# Доступ к Alertmanager UI
kubectl port-forward svc/alertmanager-operated -n monitoring 9093
```

### Временный под для диагностики сети

```bash
# Запуск подов с networking-инструментами для проверки связности
kubectl run -n monitoring --rm -it --image=nicolaka/netshoot debug-pod -- \
  curl -s -o /dev/null -w "%{http_code}" http://prometheus-main:9090/-/healthy

# Проверка DNS из пода
kubectl run -n monitoring --rm -it --image=nicolaka/netshoot debug-pod -- \
  nslookup <target-service>.<namespace>.svc.cluster.local
```

### Полезные запросы для самодиагностики

| Запрос | Назначение |
| :--- | :--- |
| `prometheus_operator_reconcile_errors_total` | Ошибки генерации конфигов или прав доступа. |
| `prometheus_tsdb_wal_corruptions_total` | Повреждения файлов WAL (требуется очистка `/wal`). |
| `prometheus_target_sync_length_seconds` | Время обработки Service Discovery (задержки в API K8s). |
| `prometheus_sd_kubernetes_cache_list_duration_seconds` | Задержки кеширования объектов Kubernetes. |
| `prometheus_tsdb_head_series` | Количество активных серий в Head Block (мониторинг кардинальности). |
| `prometheus_tsdb_compaction_chunks_range` | Диапазон чанков, подлежащих compaction (зависание при большом объеме). |
| `prometheus_config_last_reload_success_timestamp_seconds` | Время последней успешной перезагрузки конфигурации. |
| `prometheus_remote_storage_shards` | Количество шардов Remote Write (рост = задержка алертинга). |
| `prometheus_engine_queries_active` | Количество активных PromQL-запросов (troттлинг). |
| `prometheus_notifications_alertmanagers_discovered` | Количество обнаруженных Alertmanager (проверка кластеризации). |

### Команды для быстрой диагностики состояния

```bash
# 1. Статус pods Operator и Prometheus
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus
kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager

# 2. Проверка событий (Events) на предмет ошибок
kubectl get events -n monitoring --sort-by='.lastTimestamp' | tail -20

# 3. Проверка статуса StatefulSet
kubectl rollout status statefulset/prometheus-main -n monitoring --timeout=5m

# 4. Проверка сгенерированного конфига
kubectl get secret prometheus-main -n monitoring -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | wc -c

# 5. Проверка размера WAL и блоков TSDB
kubectl exec -n monitoring prometheus-main-0 -- du -sh /prometheus/wal /prometheus/chunks_head

# 6. Проверка метрик Operator
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
  | grep -E "prometheus_operator_reconcile|prometheus_config_last_reload"

# 7. Проверка Service Discovery
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/api/v1/targets \
  | jq '.data.activeTargets[] | {job, instance, health, lastError}'
```

---

## Дополнительная информация

### Рекомендации по алгоритму отладки (Runbook)

1.  **Логи Оператора:** Всегда начинайте с них. Если Оператор не "видит" объект, проблема в лейблах или RBAC.
2.  **Секрет конфигурации:** Проверьте, попали ли ваши настройки в итоговый YAML.
3.  **UI Prometheus:** Проверьте `Status -> Targets`. Это финальная точка истины для скрейпинга.
4.  **Проверка сетевой связности:** Используйте временный под с `curl`, чтобы проверить доступность порта приложения из сети мониторинга.
5.  **Проверка ResourceQuota и LimitRange:** Если Operator не создает объекты, проверьте квоты namespace.
6.  **Проверка версий CRD:** При ошибках `unknown field` убедитесь, что CRD и Operator совместимых версий.

### Связанные ресурсы

- **[Концепции Prometheus Operator](./concepts.md)** — архитектура и жизненный цикл.
- **[ServiceMonitor CRD](./crd/servicemonitor.md)** — детальная настройка сбора метрик.
- **[Безопасность (Security)](./Security/index.md)** — Admission Webhooks, CEL-валидация, RBAC.
- **[Network Policies](./network_policies.md)** — сетевая изоляция для компонентов мониторинга.
- **[PromQL для Kubernetes](./promql_kubernetes_patterns.md)** — паттерны алертинга и диагностики.
- **[Расчет ресурсов](./resource_sizing.md)** — sizing, формулы RAM/CPU/Disk.
