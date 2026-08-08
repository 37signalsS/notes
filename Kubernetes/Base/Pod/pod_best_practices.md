# Лучшие практики написания манифестов Pod в Kubernetes

## Определения

**YAML** — человекочитаемый язык сериализации данных, являющийся стандартом де-факто для описания конфигураций в Kubernetes.

**Манифест** — декларативное описание желаемого состояния объекта. Манифесты позволяют реализовать подход **Infrastructure as Code (IaC)**, обеспечивая версионность и воспроизводимость инфраструктуры.

**Immutable tag** — фиксированная версия образа (например, `1.31.0` или SHA-хеш), которая гарантирует идентичность содержимого при каждом скачивании.

**Graceful Shutdown** — процесс корректного завершения работы приложения, при котором оно успевает обработать текущие запросы и закрыть соединения до принудительной остановки.

---

## Базовые концепции

### Декларативный подход и IaC

Всегда используйте YAML-манифесты вместо императивных команд (`kubectl run`, `kubectl expose`).

*   **Контроль версий:** Храните манифесты в Git для отслеживания изменений и возможности отката.
*   **Автоматизация:** Используйте CI/CD для применения изменений (`kubectl apply`).
*   **Валидация:** Проверяйте манифесты инструментами линтинга (например, `kube-linter` или `datree`) перед деплоем.

### Управление образами

1.  **Избегайте `:latest`:** Этот тег непредсказуем. Используйте конкретные версии (SemVer) или SHA-хеш образа.
2.  **ImagePullPolicy:** 
    *   Используйте `IfNotPresent` для фиксированных тегов в Production (ускоряет запуск и экономит трафик).
    *   Используйте `Always` для тега `:latest` (только в Dev/Stage).
3.  **Приватные реестры:** Всегда настраивайте `imagePullSecrets` для доступа к защищенным хранилищам образов.

### Управление ресурсами и QoS

Явное указание ресурсов критично для стабильности кластера:

*   **Requests:** Минимальный гарантированный объем ресурсов. Используется планировщиком (Scheduler).
*   **Limits:** Максимальный порог потребления. Превышение лимита памяти ведет к `OOMKilled`.
*   **Sidecars:** Всегда указывайте ресурсы для вспомогательных контейнеров (логирование, прокси), чтобы они не вытеснили основное приложение.

Подробнее о классах обслуживания см. в [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md).

### Проверки состояния (Probes)

1.  **livenessProbe:** Перезапускает контейнер при зависании процесса.
2.  **readinessProbe:** Управляет включением Pod в Service (маршрутизация трафика).
3.  **startupProbe:** Защищает медленно запускающиеся приложения от преждевременного убийства liveness-пробой.
4.  **Best Practice:** Используйте разные эндпоинты для разных проб (например, `/healthz` для liveness и `/ready` для readiness).

Детальная настройка в [Пробы в Kubernetes](../probes.md).

### Безопасность (Security Context)

Применяйте принцип наименьших привилегий (Least Privilege) через `securityContext`:

*   **runAsNonRoot: true:** Запрещает запуск от суперпользователя.
*   **allowPrivilegeEscalation: false:** Блокирует повышение прав процессами.
*   **readOnlyRootFilesystem: true:** Делает ФС контейнера неизменяемой (используйте `emptyDir` для `/tmp`).
*   **capabilities: drop: ["ALL"]:** Отключает все потенциально опасные системные вызовы Linux.

Параметры и профили PSA описаны в [Security Context в Kubernetes](../../Security/pod_security_context.md).

### Метаданные (Labels и Annotations)

*   **Labels (Метки):** Используйте для поиска и выбора объектов (Selectors). Применяйте стандартные метки (`app.kubernetes.io/name`, `app.kubernetes.io/version`).
*   **Annotations (Аннотации):** Используйте для хранения метаданных, не участвующих в выборе объектов (контакты, ссылки, конфигурации для Ingress).
*   **Best Practice:** Используйте аннотации для хранения хеша конфигурации — это позволяет автоматически перезапускать Pod при изменении ConfigMap.

См. подробнее: [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md).

### Жизненный цикл и доступность

1.  **terminationGracePeriodSeconds:** Настраивайте под время завершения вашего приложения (по умолчанию 30с). Для БД может потребоваться 60-120с.
2.  **preStop Hook:** Используйте для подготовки к выключению (например, `sleep 5` для завершения обработки сетевых пакетов перед остановкой).
3.  **Pod Disruption Budget (PDB):** Всегда создавайте PDB для Production-нагрузок, чтобы гарантировать доступность при обслуживании узлов. Подробнее: [PDB в Kubernetes](../../Autoscaling/pod_disruption_budget.md).
4.  **Native Sidecars (v1.29+):** Оформляйте вспомогательные сервисы (прокси, агенты) как `initContainers` с `restartPolicy: Always`. Это гарантирует их готовность до старта приложения.

---

## Практические сценарии

### Пример 1: Манифест Pod уровня Production

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: production-ready-pod
  labels:
    app.kubernetes.io/name: web-api
    app.kubernetes.io/version: "1.31.0"
spec:
  # Native Sidecar (v1.29+)
  initContainers:
  - name: cloud-sql-proxy
    image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.12.0
    restartPolicy: Always
    resources:
      requests: { cpu: "50m", memory: "64Mi" }
  containers:
  - name: app
    image: my-company.com/web-api:1.31.0
    imagePullPolicy: IfNotPresent
    resources:
      requests:
        cpu: "250m"
        memory: "512Mi"
      limits:
        cpu: "500m"
        memory: "1Gi"
    ports:
    - containerPort: 8080
    livenessProbe:
      httpGet: { path: /healthz, port: 8080 }
      initialDelaySeconds: 15
    readinessProbe:
      httpGet: { path: /ready, port: 8080 }
    securityContext:
      runAsNonRoot: true
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 10"]
  terminationGracePeriodSeconds: 45
```

### Пример 2: Использование Projected Volumes для конфигураций

Лучшая практика объединения секретов и конфигов без захламления манифеста:

```yaml
volumes:
- name: all-configs
  projected:
    sources:
    - configMap:
        name: app-config
    - secret:
        name: app-credentials
    - downwardAPI:
        items:
          - path: "pod-info"
            fieldRef:
              fieldPath: metadata.name
```
Подробнее: [Projected Volumes](./volume_types/projected_volumes.md).

---

## Дополнительная информация

**Связанные темы:**

* [Пробы в Kubernetes](../probes.md) — детальный разбор Liveness/Readiness/Startup.
* [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md) — как лимиты влияют на приоритет Pod.
* [Security Context в Kubernetes](../../Security/pod_security_context.md) — настройки PSA и изоляции.
* [Бюджет прерывания подов (PDB)](../../Autoscaling/pod_disruption_budget.md) — управление доступностью.
* [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md) — стандарты именования.
* [Жизненный цикл Pod](./pod_lifecycle_and_state.md) — подробности фаз и Graceful Shutdown.
