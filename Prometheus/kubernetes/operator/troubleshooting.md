# Prometheus Operator: Диагностика и устранение неисправностей

## Определения

**Troubleshooting Prometheus Operator** — системный процесс выявления и устранения сбоев в работе контроллера, механизмов генерации конфигурации, обнаружения целей (Service Discovery) и конвейера обработки метрик в Kubernetes.

**Цикл Reconciliation (Сверка)** — механизм работы Оператора (Watch → Generate → Apply → Reload), при котором он приводит текущее состояние объектов (Pod, Secret, StatefulSet) в соответствие с декларативным описанием в CRD.

**CEL-валидация (Common Expression Language)** — механизм проверки корректности CRD на стороне API-сервера Kubernetes, предотвращающий создание некорректных ресурсов (например, отрицательных интервалов скрейпинга) до того, как они попадут в Оператор.

**Config-Reloader** — sidecar-контейнер, выполняющий мониторинг обновлений конфигурации в Secret и инициализирующий перезагрузку основного процесса Prometheus/Alertmanager через HTTP API.

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

---

## Инструментарий диагностики

### Доступ к интерфейсам
```bash
# Доступ к Prometheus UI
kubectl port-forward svc/prometheus-operated -n monitoring 9090

# Доступ к Alertmanager UI
kubectl port-forward svc/alertmanager-operated -n monitoring 9093
```

### Полезные запросы для самодиагностики

| Запрос | Назначение |
| :--- | :--- |
| `prometheus_operator_reconcile_errors_total` | Ошибки генерации конфигов или прав доступа. |
| `prometheus_tsdb_wal_corruptions_total` | Повреждения файлов WAL (требуется очистка `/wal`). |
| `prometheus_target_sync_length_seconds` | Время обработки Service Discovery (задержки в API K8s). |
| `prometheus_sd_kubernetes_cache_list_duration_seconds` | Задержки кеширования объектов Kubernetes. |

---

## Дополнительная информация

### Рекомендации по алгоритму отладки (Runbook)

1.  **Логи Оператора:** Всегда начинайте с них. Если Оператор не "видит" объект, проблема в лейблах или RBAC.
2.  **Секрет конфигурации:** Проверьте, попали ли ваши настройки в итоговый YAML.
3.  **UI Prometheus:** Проверьте `Status -> Targets`. Это финальная точка истины для скрейпинга.
4.  **Проверка сетевой связности:** Используйте временный под с `curl`, чтобы проверить доступность порта приложения из сети мониторинга.

### Связанные ресурсы

- **[Концепции Prometheus Operator](./concepts.md)** — архитектура и жизненный цикл.
- **[Service Discovery в Kubernetes](../service_discovery.md)** — механизмы обнаружения целей.
- **[ServiceMonitor CRD](./crd/servicemonitor.md)** — детальная настройка сбора метрик.
- **[Высокая доступность](./high_availability.md)** — диагностика проблем шардирования.
