# Манифест Kubernetes Deployment и лучшие практики

Руководство по созданию отказоустойчивых, безопасных и масштабируемых манифестов для stateless-приложений.

## 1. Определения

**Манифест Deployment** — декларативное описание желаемого состояния приложения, включающее параметры запуска контейнеров, стратегии обновления, требования к ресурсам и правила размещения в кластере.

Общее описание и концепции см. в основном разделе: **[Kubernetes Deployment](./index.md)**.

## 2. Базовые концепции

### Эталонный Production-манифест

Пример манифеста, учитывающего требования безопасности, надежности и наблюдаемости:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-frontend
  namespace: production
  labels:
    app.kubernetes.io/name: frontend
    app.kubernetes.io/component: web
    app.kubernetes.io/part-of: my-project
spec:
  replicas: 3
  revisionHistoryLimit: 5
  progressDeadlineSeconds: 600
  selector:
    matchLabels:
      app.kubernetes.io/name: frontend
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app.kubernetes.io/name: frontend
    spec:
      # Безопасность и управление доступом
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 2000
      automountServiceAccountToken: false
      
      # Планирование и приоритеты
      priorityClassName: production-high
      terminationGracePeriodSeconds: 60
      
      containers:
      - name: web-container
        image: my-registry.com/frontend:1.4.2 # Senior practice: конкретный тег
        imagePullPolicy: IfNotPresent
        
        ports:
        - name: http
          containerPort: 8080
          
        # Переменные окружения и секреты
        envFrom:
        - configMapRef:
            name: app-config
        
        # Ресурсы (обязательно requests == limits для памяти в критических сервисах)
        resources:
          requests:
            cpu: "250m"
            memory: "512Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
            
        # Триада проб (Health Checks)
        startupProbe:
          httpGet:
            path: /healthz
            port: http
          failureThreshold: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: http
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /live
            port: http
          initialDelaySeconds: 15
          periodSeconds: 20
```

### Ключевые поля спецификации (Pod Spec)

| Поле | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `priorityClassName` | Определяет важность пода при нехватке ресурсов. | Используйте для критических сервисов, чтобы предотвратить их вытеснение. |
| `imagePullPolicy` | Правило скачивания образа. | `IfNotPresent` для экономии трафика. `Always` — только если вы используете мутабельные теги (антипаттерн). |
| `automountServiceAccountToken` | Автомонтирование токена доступа к API. | Устанавливайте в `false`, если приложению не нужен доступ к Kubernetes API (защита от атак). |
| `terminationGracePeriodSeconds` | Время на завершение работы (SIGTERM). | По умолчанию 30с. Увеличивайте для тяжелых приложений (DB, Java) для чистого закрытия соединений. |
| `revisionHistoryLimit` | Глубина истории ReplicaSets. | 3–5 достаточно для отката. Большие значения создают лишнюю нагрузку на `etcd`. |

### Метаданные и аннотации

Использование стандартных меток (`app.kubernetes.io/*`) позволяет инструментам мониторинга (Prometheus) и визуализации (Lens, Dashboard) корректно группировать ресурсы.

**Полезные аннотации:**
- `prometheus.io/scrape: "true"` — автоматический сбор метрик.
- `kubernetes.io/change-cause` — краткое описание причины изменения (отображается в `rollout history`).

## 3. Практические сценарии

### Равномерное распределение (Topology Spread Constraints)

Для обеспечения высокой доступности (HA) на уровне дата-центров используйте распределение по зонам:

```yaml
spec:
  topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: "topology.kubernetes.io/zone"
    whenUnsatisfiable: DoNotSchedule # Жесткое ограничение
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: frontend
```

### Тонкая настройка RollingUpdate

| Конфигурация | Результат | Кейс использования |
| :--- | :--- | :--- |
| `maxUnavailable: 0`, `maxSurge: 1` | Сначала +1 новый, потом -1 старый. | **Стандарт.** Гарантирует 100% доступность во время обновления. |
| `maxUnavailable: 25%`, `maxSurge: 0` | Сначала -25% старых, потом +25% новых. | Экономия ресурсов в кластере за счет временной деградации мощности. |

## 4. Дополнительная информация

### Лучшие практики (Best Practices 2026)

1.  **Принцип неизменяемости (Immutability):**
    - Запрещено использовать `:latest`. Это делает деплой невоспроизводимым и ломает механизм отката.
    - Используйте хеши образов (`sha256:...`) для максимальной безопасности в критических средах.
2.  **Resources (QoS):**
    - Всегда указывайте `requests` и `limits`.
    - Для памяти рекомендуется устанавливать `requests == limits` (класс **Guaranteed**), чтобы защитить приложение от OOMKiller при фрагментации памяти на узле. См. [Управление ресурсами](../../Scheduling/qos_limit_and_requests.md).
3.  **Безопасность (Security by Design):**
    - `readOnlyRootFilesystem: true` — защищает от изменения кода в контейнере.
    - `runAsNonRoot: true` — обязательное требование для всех production-нагрузок. См. [Pod Security Context](../../Security/pod_security_context.md).
4.  **Graceful Termination:**
    - Приложение должно корректно обрабатывать сигнал `SIGTERM`.
    - Используйте `preStop` хуки, если приложение не умеет завершаться само (например, для плавного вывода из Nginx upstream).
5.  **Аффинити и распределение:**
    - Используйте `podAntiAffinity` или `topologySpreadConstraints`, чтобы поды одного сервиса не оказывались на одном узле (избегание Single Point of Failure). См. [Affinity и Anti-Affinity](../../Scheduling/affinity.md).

### См. также

- [Управление жизненным циклом Deployment](./lifecycle_management.md)
- [Диагностика и Troubleshooting](./troubleshooting.md)
- [Проверки состояния (Probes) в Kubernetes](../probes.md)
- [HPA — автоматическое масштабирование](../../Autoscaling/HPA/index.md)
