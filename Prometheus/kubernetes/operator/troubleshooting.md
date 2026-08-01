# Prometheus Operator: Диагностика и устранение неисправностей

## Определения

**Troubleshooting Prometheus Operator** — систематический процесс выявления и устранения сбоев в работе контроллера, механизмов обнаружения целей (Service Discovery) и конвейера обработки метрик в Kubernetes.

**Цикл Reconciliation (Сверка)** — основной механизм работы Оператора (Watch → Generate → Apply → Reload). Сбой на любом этапе приводит к расхождению между декларативной конфигурацией (CRD) и реальным состоянием Prometheus.

**Config-Reloader** — sidecar-контейнер, отвечающий за мониторинг обновлений конфигурационных файлов в Secret и выполнение HTTP-запросов на перезагрузку основного процесса.

> **См. также:** [Концепции Prometheus Operator](./concepts.md), [Service Discovery в Kubernetes](./service_discovery.md).

## Базовые концепции

### Точки отказа в жизненном цикле конфигурации

| Этап | Механизм | Симптом сбоя | Инструмент диагностики |
| :--- | :--- | :--- | :--- |
| **Watch** | K8s API Watch | Оператор не реагирует на изменение CRD | `kubectl get events -A`, RBAC check |
| **Generate** | Operator Logic | Конфигурация в Secret не обновляется | Логи Оператора: `failed to generate config` |
| **Apply** | K8s API (Secret/STS) | Ошибка `Forbidden` или `Large resource` | `kubectl describe secret`, лимит 1MB |
| **Reload** | Sidecar Reloader | В `/config` (UI) старые данные | Логи `config-reloader`, статус пода |

---

## Алгоритм диагностики: «Цель не скрейпится»

Если вы добавили `ServiceMonitor`, но не видите целей в Prometheus, следуйте по шагам:

1.  **Проверка CRD:** Убедитесь, что `ServiceMonitor` создан и имеет нужные лейблы.
2.  **Селектор в Prometheus:** Соответствуют ли лейблы `ServiceMonitor` селектору `serviceMonitorSelector` в ресурсе `Prometheus`?
3.  **Endpoints:** Проверьте, что у целевого `Service` есть активные `Endpoints` (`kubectl get ep`). Если их нет — проблема в приложении или селекторе сервиса.
4.  **Сгенерированный конфиг:** Проверьте секрет Прометеуса (`kubectl get secret prometheus-<name>`). Содержит ли он вашу `job`?
5.  **Логи релоадера:** Видит ли sidecar изменения и прошел ли запрос `/-/reload` с кодом 200?
6.  **Сетевой уровень:** Доступен ли IP пода приложения с пода Прометеуса по указанному порту? (`kubectl exec ... curl <pod-ip>:<port>/metrics`).

---

## Практические сценарии

### 1. Проблемы Service Discovery и селекторов

**Симптом:** Цели не появляются в списке `/targets`.

*   **Label Matching:** Самая частая причина.
    ```bash
    # Проверка селектора в ресурсе Prometheus
    kubectl get prometheus main -o yaml | grep serviceMonitorSelector -A 3
    # Проверка лейблов на ServiceMonitor
    kubectl get servicemonitor my-app -o show-labels
    ```
*   **Namespace Selection:** Если `ServiceMonitor` в другом namespace, в `Prometheus` должен быть настроен `serviceMonitorNamespaceSelector` (по умолчанию ищет только в своем namespace).

### 2. Ошибки Admission Webhooks и TLS

**Симптом:** Ошибки при `kubectl apply -f prometheus-rule.yaml`.
`Error from server (InternalError): Internal error occurred: failed calling webhook...`

*   **Диагностика сертификатов:** Оператор требует TLS для вебхука. Если используется `cert-manager`:
    ```bash
    kubectl describe certificate prometheus-operator-webhook -n monitoring
    ```
*   **Проверка связности:** API-сервер должен «видеть» порт 9443 пода Оператора.
    ```bash
    # Проверьте, что сервис вебхука имеет Endpoints
    kubectl get ep prometheus-operator -n monitoring
    ```
*   **Таймауты:** Если Оператор не отвечает за 10с (дефолт), проверьте его CPU usage. При перегрузке reconciliation может блокировать обработку вебхуков.

### 3. Лимит 1MB на Kubernetes Secret

**Симптом:** Новые `ServiceMonitor` игнорируются, в логах Оператора ошибка:
`Secret "prometheus-main" is invalid: data: Too long: must have at most 1048576 bytes`

*   **Причина:** При тысячах целей сгенерированный `prometheus.yaml` превышает лимит Kubernetes для объектов Secret/ConfigMap.
*   **Решение:**
    1.  **Шардирование:** Используйте `spec.shards` в `Prometheus` для разделения нагрузки и конфига.
    2.  **Сжатие:** В новых версиях Оператора используйте аннотацию или настройку для сжатия конфига (gzip).
    3.  **Оптимизация:** Уменьшите количество `relabel_configs` в каждом мониторе.

### 4. Alertmanager: Ошибки отправки и конфигурации

**Симптом:** Алерты видны в Prometheus, но не приходят получателям.

*   **Проверка конфига:**
    ```bash
    # Извлечение актуальной конфигурации
    kubectl get secret alertmanager-main -n monitoring -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
    ```
*   **Проверка кластера (Gossip):** Alertmanager использует порт 9094 для синхронизации.
    ```bash
    kubectl exec -it alertmanager-main-0 -n monitoring -- amtool cluster show
    ```
*   **Логи Alertmanager:** Ищите ошибки аутентификации (SMTP/Webhook/Slack).
    ```bash
    kubectl logs -l app.kubernetes.io/name=alertmanager -n monitoring
    ```

### 5. Проблемы с хранилищем (PVC и Mount)

**Симптом:** Поды Prometheus в состоянии `Pending` или `CrashLoopBackOff`.

*   **Проверка PVC:**
    ```bash
    kubectl get pvc -n monitoring
    kubectl describe pvc prometheus-main-db-prometheus-main-0
    ```
*   **Corruption в TSDB:** Если диск был переполнен, Prometheus может не запуститься. Ищите в логах `WAL segment is corrupted`.
    *   *Решение:* Требуется ручное удаление поврежденных сегментов в директории `/prometheus/wal/`.

### 6. Thanos Sidecar: gRPC и S3

**Симптом:** Данные не уходят в Object Storage или Thanos Query выдает пустые ответы.

*   **Connectivity S3:** Проверьте логи sidecar.
    ```bash
    kubectl logs -c thanos-sidecar prometheus-main-0 -n monitoring
    # Ошибка: "failed to upload blocks" -> проверьте Secret с credentials
    ```
*   **gRPC Errors:** Thanos Query подключается к Sidecar по порту 10901. Проверьте сетевой доступ (NetworkPolicy).

### 7. Slow Reconciliation (Медленная сверка)

**Симптом:** Изменения в CRD применяются через минуты, а не секунды.

*   **Метрики:** `prometheus_operator_reconcile_duration_seconds_bucket`.
*   **Причины:**
    1.  **Throttling API:** Оператор уперся в лимиты запросов к K8s API.
    2.  **Большой кэш:** Слишком много объектов в кластере (десятки тысяч подов). Увеличьте RAM лимиты Оператора.
    3.  **Network Latency:** Задержки между Оператором и API-сервером.

---

## Распространённые проблемы скрейпинга (Сводка)

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **"no targets"** | Неверный Label Selector | Проверить `matchLabels` в ServiceMonitor. |
| **404 Not Found** | Неверный `path` в конфиге | Проверить `endpoints.path` (по дефолту `/metrics`). |
| **Connection Refused**| Приложение слушает другой порт | Проверить `endpoints.port` или `targetPort`. |
| **Context Deadline** | Медленный ответ приложения | Увеличить `scrapeTimeout` в мониторе. |
| **Authentication Error**| Нужен токен/сертификат | Настроить `tlsConfig` или `bearerTokenSecret`. |

---

## Инструментарий диагностики

### Доступ к UI для глубокой проверки
```bash
# Port-forward к сервису (operated-версия всегда ведет на активные поды)
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
```

### Полезные запросы PromQL для самодиагностики

| Запрос | Назначение |
| :--- | :--- |
| `up{job="prometheus-operator"} == 0` | Оператор упал или не скрейпится. |
| `rate(prometheus_operator_reconcile_errors_total[5m]) > 0` | Обнаружены ошибки в цикле сверки. |
| `prometheus_operator_config_size_bytes` | Проверка близости к лимиту 1MB. |
| `prometheus_target_scrapes_exceeded_sample_limit_total` | Цели отбрасываются из-за лимита метрик. |
| `alertmanager_notifications_failed_total` | Ошибки отправки уведомлений. |

---

## Дополнительная информация

### Рекомендации по алгоритму отладки (Runbook)

1.  **Проверьте логи Оператора:** Это SSoT для всех проблем с конфигурацией.
2.  **Проверьте статус в UI Prometheus:** Раздел `Status -> Targets` покажет, видит ли Прометеус цель вообще. Раздел `Status -> Configuration` покажет, дошли ли изменения до процесса.
3.  **Используйте `kubectl describe`:** Это основной способ увидеть ошибки планировщика, проблемы с монтированием томов и нехватку прав (Events).
4.  **Проверка в Air-gapped:** Если образы не скачиваются, проверьте `imagePullSecrets` в ресурсе `Prometheus` и доступность локального реестра.

### Связанные ресурсы

- **[Installation Guide](./installation.md)** — архитектура RBAC и Webhooks.
- **[High Availability](./high_availability.md)** — диагностика проблем HA и шардирования.
- **[ScrapeConfig CRD](./crd/servicemonitor.md)** — детали скрейпинга через мониторы.
