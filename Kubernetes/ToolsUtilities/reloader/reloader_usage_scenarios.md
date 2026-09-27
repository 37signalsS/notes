# Reloader — Практические сценарии использования

## Определения

**Сценарии использования Reloader** — типовые конфигурации и примеры применения контроллера Reloader для автоматического обновления рабочих нагрузок (Deployments, StatefulSets, DaemonSets, Argo Rollouts, DeploymentConfig) при изменении связанных с ними ресурсов `ConfigMap` и `Secret`.

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Предварительные требования

### Установка Reloader

```bash
# Быстрая установка через Helm
helm repo add stakater https://stakater.github.io/stakater-charts
helm install reloader stakater/reloader \
  --namespace reloader-system \
  --create-namespace
```

### Проверка доступности

```bash
kubectl get pods -n reloader-system -l app=reloader
# → result: reloader-xxxxxxxxxx-xxxxx  1/1  Running  0  5m
```

---

## Основные концепции

### Механизмы активации

Reloader управляется через аннотации в метаданных объектов. Основные способы отслеживания:

-   **Явное указание (Explicit):** Аннотации `configmap.reloader.stakater.com/reload: "name"` или `secret.reloader.stakater.com/reload: "name"`. Позволяет точечно управлять перезапусками.
-   **Автоматическое обнаружение (Auto):** Аннотация `reloader.stakater.com/auto: "true"`. Рекомендуется для большинства stateless-приложений.
-   **Стратегия обновления:** В 2026 году стандартом является использование `--reload-strategy=annotations` для совместимости с GitOps (ArgoCD/Flux), чтобы избежать конфликтов состояния (OutOfSync).
-   **Глобальное переопределение (v1.4.19):** Флаг `--ignore-annotation` на уровне контроллера позволяет игнорировать аннотации запрета на уровне отдельных приложений, что полезно для соблюдения политик безопасности платформы.

### Полный справочник аннотаций

| Аннотация | Значение | Описание |
| :--- | :--- | :--- |
| `reloader.stakater.com/auto` | `"true"` / `"false"` | Автоматическое обнаруживание всех ConfigMap/Secret |
| `configmap.reloader.stakater.com/reload` | `"name1,name2"` | Список ConfigMap через запятую |
| `secret.reloader.stakater.com/reload` | `"name1,name2"` | Список Secret через запятую |
| `reloader.stakater.com/ignore` | `"true"` / `"false"` | Игнорирование данного ресурса |
| `deployment.reloader.stakater.com/pause-period` | `"1m"`, `"5m"`, `"1h"` | Debounce-задержка перед перезапуском |
| `reloader.stakater.com/pod-placeholder` | `"true"` | Заглушка для отладки без реальных изменений |

### Приоритет и правила разрешения

1. **Глобальный флаг `--ignore-annotation=true`:** Переопределяет все аннотации `ignore` на уровне ресурсов.
2. **Аннотация `ignore` на ресурсе:** Приоритетнее `auto` — если установлен `ignore: "true"`, Reloader не будет отслеживать.
3. **Явные аннотации (`configmap/reload`):** Приоритетнее `auto` — если указаны конкретные имена, отслеживаются только они.
4. **Debounce (`pause-period`):** Применяется к конкретному ресурсу, не глобально.

---

## Практические сценарии

### Сценарий 1: Веб-сервер с динамическим контентом (subPath)

**Задача:** Перезапуск Nginx/OpenResty при обновлении HTML-файла или конфигурации, смонтированной через `subPath`.
**Проблема:** Механизмы Kubernetes не обновляют файлы, смонтированные через `subPath`, без перезапуска пода.

```yaml
# nginx-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-web
  annotations:
    configmap.reloader.stakater.com/reload: "web-config"
spec:
  template:
    spec:
      containers:
        - name: nginx
          image: nginx:alpine
          volumeMounts:
            - name: config
              mountPath: /etc/nginx/nginx.conf
              subPath: nginx.conf
      volumes:
        - name: config
          configMap:
            name: web-config
```

**Проверка:**
1.  Измените данные в ConfigMap `web-config`.
2.  Reloader обнаружит изменение и обновит Deployment.
3.  # → result: Выполнится Rolling Update, новые поды подхватят обновлённый файл.

---

### Сценарий 2: Ротация секретов через Secrets Store CSI Driver

**Задача:** Автоматический перезапуск приложения при обновлении секрета во внешнем хранилище (HashiCorp Vault, AWS Secrets Manager).
**Требование:** Reloader запущен с флагом `--enable-csi-integration=true`.

```yaml
# app-with-csi.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: security-app
  annotations:
    secret.reloader.stakater.com/reload: "app-db-creds"
spec:
  template:
    spec:
      containers:
        - name: app
          image: internal-app:v2
          volumeMounts:
            - name: secrets-store-inline
              mountPath: "/mnt/secrets"
              readOnly: true
      volumes:
        - name: secrets-store-inline
          csi:
            driver: secrets-store.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: "vault-db-creds"
```

**Принцип работы:** Когда CSI-драйвер обновляет локальный Kubernetes Secret (синхронизированный из Vault), Reloader реагирует на изменение этого секрета и инициирует перезапуск.

---

### Сценарий 3: Интеграция с Argo Rollouts (Canary)

**Задача:** Использование Canary-стратегии развёртывания при обновлении конфигурации.
**Требование:** Флаг `--is-argo-rollouts=true` (включен по умолчанию в v1.4+).

```yaml
# argo-rollout-canary.yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: canary-deployment
  annotations:
    reloader.stakater.com/auto: "true"
spec:
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: { duration: 5m }
        - setWeight: 50
        - pause: { duration: 10m }
  template:
    spec:
      containers:
        - name: app
          image: business-logic:latest
          envFrom:
            - configMapRef:
                name: app-params
```

**Результат:** При изменении `app-params` Reloader инициирует не мгновенный Rolling Update, а запуск Canary-процесса, определённого в Rollout.

---

### Сценарий 4: Оптимизация для GitOps (ArgoCD)

**Задача:** Предотвращение состояния OutOfSync в ArgoCD при работе Reloader.

**Решение:**
1.  Установить `--reload-strategy=annotations`.
2.  Настроить ArgoCD на игнорирование аннотации хеша.

```yaml
# ArgoCD Application
apiVersion: argoproj.io/v1alpha1
kind: Application
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

**Flux Kustomization:**

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
  namespace: flux-system
spec:
  interval: 10m
  path: ./kubernetes/apps/production
  sourceRef:
    kind: GitRepository
    name: flux-system
  postBuild:
    substituteFrom:
      - kind: ConfigMap
        name: cluster-config
```

---

### Сценарий 5: Глобальное принудительное обновление (Platform Policy)

**Задача:** Игнорирование аннотации `reloader.stakater.com/ignore: "true"` для обеспечения безопасности (например, принудительная ротация TLS-сертификатов).

**Контекст:** Разработчик пометил приложение аннотацией `ignore`, но администратор платформы запустил Reloader с флагом `--ignore-annotation=true`.

**Манифест приложения:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: legacy-app
  annotations:
    reloader.stakater.com/ignore: "true"  # Будет проигнорировано контроллером
    reloader.stakater.com/auto: "true"
spec:
  # ...
```

**Результат:** Несмотря на наличие аннотации `ignore`, Reloader выполнит перезапуск при обновлении связанных ресурсов.

---

### Сценарий 6: DaemonSet — мониторинг инфраструктурных нод

**Задача:** Автоматическое обновление Node Exporter при изменении конфигурации.

```yaml
# node-exporter-daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
  annotations:
    configmap.reloader.stakater.com/reload: "node-exporter-config"
spec:
  selector:
    matchLabels:
      app: node-exporter
  template:
    metadata:
      labels:
        app: node-exporter
    spec:
      containers:
        - name: node-exporter
          image: prom/node-exporter:v1.7.0
          args:
            - --config.file=/etc/node-exporter/config.yml
          volumeMounts:
            - name: config
              mountPath: /etc/node-exporter
      volumes:
        - name: config
          configMap:
            name: node-exporter-config
```

**Проверка:**
```bash
kubectl annotate daemonset node-exporter configmap.reloader.stakater.com/reload=node-exporter-config -n monitoring
kubectl get events -n monitoring --field-selector reason=ReloaderTriggered
```

---

### Сценарий 7: StatefulSet — база данных с Persistent Volume

**Задача:** Перезапуск PostgreSQL при изменении конфигурации `postgresql.conf`.

```yaml
# postgres-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: databases
  annotations:
    configmap.reloader.stakater.com/reload: "postgres-config"
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:16
          env:
            - name: POSTGRES_DB
              value: mydb
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
            - name: config
              mountPath: /etc/postgresql/postgresql.conf
              subPath: postgresql.conf
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
  volumeClaimTemplates:
    - metadata:
        name: config
      spec:
        accessModes: ["ReadOnlyMany"]
        resources:
          requests:
            storage: 100Mi
```

**Важно:** StatefulSet обновляется медленнее Deployment — Reloader учитывает `updateStrategy` и `minReadySeconds`.

---

### Сценарий 8: Множественные ConfigMap/Secret в одном поде

**Задача:** Приложение использует несколько конфигурационных файлов из разных ConfigMap.

```yaml
# multi-config-app.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: multi-config-app
  annotations:
    # Автоматический режим — отслеживает все зависимые ресурсы
    reloader.stakater.com/auto: "true"
    # ИЛИ явный режим (более безопасно)
    # configmap.reloader.stakater.com/reload: "app-config,nginx-config,logging-config"
    # secret.reloader.stakater.com/reload: "app-secrets,tls-certs"
spec:
  template:
    spec:
      containers:
        - name: app
          image: my-app:v1.0
          envFrom:
            - configMapRef:
                name: app-config
            - configMapRef:
                name: logging-config
            - secretRef:
                name: app-secrets
          volumeMounts:
            - name: nginx-config
              mountPath: /etc/nginx
            - name: tls-certs
              mountPath: /etc/tls
              readOnly: true
      volumes:
        - name: nginx-config
          configMap:
            name: nginx-config
        - name: tls-certs
          secret:
            secretName: tls-certs
```

**Поведение:** При изменении любого из 4 ресурсов (2 ConfigMap + 2 Secret) Reloader выполнит один Rolling Update.

---

### Сценарий 9: Multi-Container Pod

**Задача:** Основной контейнер зависит от конфигурации, а sidecar — от другого ConfigMap.

```yaml
# multi-container-pod.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-with-sidecar
  annotations:
    configmap.reloader.stakater.com/reload: "app-config,sidecar-config"
spec:
  template:
    spec:
      containers:
        - name: app
          image: my-app:v1.0
          envFrom:
            - configMapRef:
                name: app-config
        - name: sidecar
          image: fluent/fluent-bit:latest
          envFrom:
            - configMapRef:
                name: sidecar-config
```

**Поведение:** Reloader отслеживает оба ConfigMap и перезапускает под при изменении любого из них. Оба контейнера перезапускаются одновременно.

---

### Сценарий 10: CronJob с обновлением конфигурации

**Задача:** Перезапуск CronJob при изменении скрипта в ConfigMap.

```yaml
# cronjob-with-config.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: backup-job
  annotations:
    configmap.reloader.stakater.com/reload: "backup-script"
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: alpine:latest
              command: ["/bin/sh", "/scripts/backup.sh"]
              volumeMounts:
                - name: script
                  mountPath: /scripts
          volumes:
            - name: script
              configMap:
                name: backup-script
                defaultMode: 0755
```

**Проверка:**
```bash
kubectl annotate cronjob backup-job configmap.reloader.stakater.com/reload=backup-script
```

---

### Сценарий 11: Debounce — группировка массовых обновлений

**Задача:** Предотвратить "шторм" перезапусков при обновлении десятков ConfigMap одновременно.

```yaml
# debounce-example.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: microservice
  annotations:
    reloader.stakater.com/auto: "true"
    deployment.reloader.stakater.com/pause-period: "5m"
spec:
  template:
    spec:
      containers:
        - name: app
          image: my-app:v1.0
```

**Поведение:**
1. При изменении первого ConfigMap Reloader начинает отсчёт 5 минут.
2. Если за это время изменяются другие ConfigMap/Secret — они добавляются в очередь.
3. По истечении 5 минут выполняется один Rolling Update со всеми изменениями.

**Рекомендации по задержкам:**

| Задержка | Когда использовать |
| :--- | :--- |
| `1m` | Небольшие кластеры, Dev/Stage среды |
| `5m` | Production, критические сервисы |
| `15m` | Крупные кластеры с частыми изменениями |
| `1h` | Ручное управление, исключительные случаи |

---

### Сценарий 12: Namespace-scoped Reloader

**Задача:** Ограничить Reloader конкретными namespace для безопасности.

```bash
# Установка с ограничением namespace
helm install reloader stakater/reloader \
  --namespace reloader-system \
  --create-namespace \
  --set reloader.watchGlobally=false \
  --set reloader.namespaces='{production,staging}'
```

**Альтернатива — несколько экземпляров Reloader:**

```bash
# Production Reloader
helm install reloader-prod stakater/reloader \
  --namespace reloader-prod \
  --set reloader.watchGlobally=false \
  --set reloader.namespaces='{production}'

# Staging Reloader
helm install reloader-staging stakater/reloader \
  --namespace reloader-staging \
  --set reloader.watchGlobally=false \
  --set reloader.namespaces='{staging}'
```

---

### Сценарий 13: Интеграция с Cert-Manager

**Задача:** Перезапуск Ingress Controller при обновлении TLS-сертификата.

```yaml
# ingress-with-cert.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-ingress
  annotations:
    secret.reloader.stakater.com/reload: "web-ingress-tls"
spec:
  template:
    spec:
      containers:
        - name: nginx
          image: nginx:alpine
          volumeMounts:
            - name: tls-certs
              mountPath: /etc/tls
              readOnly: true
      volumes:
        - name: tls-certs
          secret:
            secretName: web-ingress-tls
```

---

### Сценарий 14: Reloader с Prometheus и Alertmanager

**Задача:** Автоматическое обновление Prometheus при изменении правил или конфигурации.

```yaml
# prometheus-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: prometheus
  namespace: monitoring
  annotations:
    configmap.reloader.stakater.com/reload: "prometheus-rules,prometheus-config"
spec:
  serviceName: prometheus
  replicas: 2
  selector:
    matchLabels:
      app: prometheus
  template:
    metadata:
      labels:
        app: prometheus
    spec:
      containers:
        - name: prometheus
          image: prom/prometheus:v2.51.0
          args:
            - --config.file=/etc/prometheus/prometheus.yml
            - --storage.tsdb.retention.time=15d
          volumeMounts:
            - name: config
              mountPath: /etc/prometheus
            - name: rules
              mountPath: /etc/prometheus/rules
      volumes:
        - name: config
          configMap:
            name: prometheus-config
        - name: rules
          configMap:
            name: prometheus-rules
```

**Преимущество:** Обновление правил Prometheus не требует перезапуска пода (hot reload), но Reloader полезен для обновления конфигурации (`prometheus.yml`).

---

### Сценарий 15: Blue/Green стратегия с Reloader

**Задача:** Обновление конфигурации для Blue/Green развёртывания.

```yaml
# blue-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-blue
  annotations:
    configmap.reloader.stakater.com/reload: "app-config"
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
      version: blue
  template:
    metadata:
      labels:
        app: my-app
        version: blue
    spec:
      containers:
        - name: app
          image: my-app:v1.0
          envFrom:
            - configMapRef:
                name: app-config
---
# green-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-green
  annotations:
    configmap.reloader.stakater.com/reload: "app-config"
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
      version: green
  template:
    metadata:
      labels:
        app: my-app
        version: green
    spec:
      containers:
        - name: app
          image: my-app:v2.0
          envFrom:
            - configMapRef:
                name: app-config
```

**Поведение:** При изменении `app-config` оба Deployment (Blue и Green) получат обновление одновременно.

---

### Сценарий 16: Reloader с OPA/Gatekeeper

**Задача:** Ограничение использования Reloader через политики.

```yaml
# constraint-template.yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8sreloaderallowed
spec:
  crd:
    spec:
      names:
        kind: K8sReloaderAllowed
      validation:
        openAPIV3Schema:
          type: object
          properties:
            allowedNamespaces:
              type: array
              items:
                type: string
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8sreloaderallowed
        violation[{"msg": msg}] {
          input.review.object.metadata.annotations["reloader.stakater.com/auto"] == "true"
          not input.review.object.metadata.namespace in input.parameters.allowedNamespaces
          msg := sprintf("Reloader auto mode is not allowed in namespace %v", [input.review.object.metadata.namespace])
        }
---
# constraint.yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sReloaderAllowed
metadata:
  name: restrict-reloader-auto
spec:
  match:
    kinds:
      - apiGroups: ["apps"]
        kinds: ["Deployment", "StatefulSet", "DaemonSet"]
  parameters:
    allowedNamespaces:
      - production
      - staging
```

---

### Сценарий 17: Reloader с ResourceQuota

**Задача:** Ограничение количества одновременных перезапусков в namespace.

```yaml
# resourcequota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: reloader-quota
  namespace: production
spec:
  hard:
    pods: "100"
    deployments: "50"
    # Ограничение на количество обновлений в час
    count/deployments.apps: "50"
---
# networkpolicy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: reloader-allow
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: reloader
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: kube-system
      ports:
        - protocol: TCP
          port: 443
```

---

### Сценарий 18: Тестирование Reloader (Debug Mode)

**Задача:** Отладка поведения без реальных изменений.

```bash
# Включение debug-логирования
helm upgrade reloader stakater/reloader \
  --namespace reloader-system \
  --set reloader.args[0]="--log-level=debug" \
  --reuse-values

# Создание тестового ConfigMap
kubectl create configmap test-config --from-literal=key=value -n default

# Создание тестового Deployment
kubectl create deployment test-app --image=nginx:alpine -n default

# Добавление аннотации
kubectl annotate deployment test-app reloader.stakater.com/auto=true -n default

# Проверка логов
kubectl logs -f deployment/reloader -n reloader-system | grep test-config

# Очистка
kubectl delete deployment test-app -n default
kubectl delete configmap test-config -n default
```

---

### Сценарий 19: Миграция на Reloader

**Задача:** Переход с checksum-аннотаций Helm на Reloader.

**Этап1: Установка Reloader:**

```bash
helm install reloader stakater/reloader --namespace reloader-system --create-namespace
```

**Этап2: Добавление аннотаций:**

```yaml
# Было (checksum)
annotations:
  checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}

# Стало (Reloader)
annotations:
  configmap.reloader.stakater.com/reload: "{{ .Release.Name }}-config"
```

**Этап3: Удаление checksum:**

```yaml
# Удалить строку checksum/config из template.metadata.annotations
```

**Этап4: Проверка:**

```bash
kubectl get events --field-selector reason=ReloaderTriggered -n <namespace>
```

---

## Дополнительная информация

### Взаимодействие с Rolling Update стратегиями

Reloader инициирует Rolling Update через patch PodTemplate, но **не управляет параметрами обновления**. Это означает, что `maxSurge` и `maxUnavailable` Deployment определяют скорость и безопасность обновления.

**Как Reloader взаимодействует с разными стратегиями:**

| Стратегия Deployment | Поведение Reloader | Рекомендации |
| :--- | :--- | :--- |
| `maxSurge: 1, maxUnavailable: 0` | Сначала +1 новый под, затем -1 старый | **Стандарт.** Безопасно для production |
| `maxSurge: 25%, maxUnavailable: 25%` | Параллельный обмен по 25% | Быстрее, но требует запас ресурсов |
| `maxUnavailable: 0` | Старые поды не удаляются до готовности новых | Гарантия доступности, но требует ресурсов для `maxSurge` |
| `Recreate` | Все старые поды удаляются, затем все новые | **Опасно** — полный простой. Избегать для критичных сервисов |

**Практический пример:**

```yaml
# Deployment с безопасными параметрами для Reloader
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    reloader.stakater.com/auto: "true"
    # Debounce: группировать изменения в окне 2 минуты
    deployment.reloader.stakater.com/pause-period: "2m"
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # +1 дополнительный под
      maxUnavailable: 0   # Старые поды не удаляются до готовности новых
  template:
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: app
          image: my-app:v1.0
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
          lifecycle:
            preStop:
              exec:
                command: ["sh", "-c", "sleep 10"]  # Дренаж трафика перед SIGTERM
```

**Критические параметры для Reloader:**

1. **`maxUnavailable: 0`** — гарантирует, что Reloader не вызовет downtime
2. **`readinessProbe`** — обязательна; без неё Reloader может удалить здоровый под до готовности нового
3. **`terminationGracePeriodSeconds`** — должен покрывать `preStop sleep` + время дренажа
4. **`preStop sleep`** — компенсирует задержку обновления Endpoints (5-15 сек)

**Edge cases:**

- **Reloader + HPA:** HPA масштабирует Deployment, а Reloader обновляет. При `maxUnavailable: 0` и нехватке ресурсов rollout застрянет — убедитесь в запасе мощности кластера.
- **Reloader + PDB:** PodDisruptionBudget **не блокирует** Rolling Update от контроллера Deployment, но блокирует `kubectl drain`. Согласуйте `maxUnavailable` в Deployment и `minAvailable` в PDB.
- **Reloader + StatefulSet:** StatefulSet обновляется медленнее — Reloader учитывает `updateStrategy` и `minReadySeconds`. Используйте `partition` для ступенчатого обновления.

### Configuration Drift: Reloader и GitOps

**Configuration drift** — расхождение между состоянием в Git и фактическим состоянием кластера. Reloader может как создавать drift, так и способствовать его обнаружению.

**Как Reloader создаёт drift:**

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Git (SSoT) │ ──> │   ArgoCD     │ ──> │  K8s Cluster │
│  ConfigMap   │     │  Sync        │     │  ConfigMap   │
└──────────────┘     └──────────────┘     └──────────────┘
                            │                     │
                            │                     ▼
                            │              ┌──────────────┐
                            │              │   Reloader   │
                            │              │  patch Deploy│
                            │              └──────────────┘
                            │                     │
                            ▼                     ▼
                     ┌──────────────┐     ┌──────────────┐
                     │  OutOfSync   │     │  Pod с новым │
                     │  (drift)     │     │  аннотацией  │
                     └──────────────┘     └──────────────┘
```

**Стратегии предотвращения drift:**

| Стратегия | Механизм | Когда использовать |
| :--- | :--- | :--- |
| **Annotation Strategy** | `--reload-strategy=annotations` | **Рекомендуется.** Minimizes diff — только аннотация, не переменные окружения |
| **Ignore Differences** | ArgoCD `ignoreDifferences` | Обязательно при использовании Reloader + ArgoCD |
| **Immutable ConfigMap** | `immutable: true` + Kustomize Hash | Для критичных конфигураций — полная замена вместо update |
| **External Secret Operators** | ESO + Reloader CSI | Секреты управляются вне Git, Reloader реагирует на CSI sync |

**Практический пример: предотвращение drift с ArgoCD:**

```yaml
# 1. Reloader с annotation strategy
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: reloader-system
spec:
  template:
    spec:
      containers:
        - name: reloader
          args:
            - --reload-strategy=annotations  # Ключевой параметр

---
# 2. ArgoCD Application с ignoreDifferences
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        # Игнорировать аннотацию Reloader
        - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

**Детекция drift через Reloader metrics:**

```promql
# Reloader обновил под, но ArgoCD откатил — цикл обновлений
increase(reloader_success_reload_total[5m]) > 3

# ConfigMap изменился, но Reloader не отреагировал (潜在ный drift)
changes(kube_configmap_info{namespace="production"}[5m]) > 0
  and on()
  (rate(reloader_success_reload_total[5m]) == 0)
```

### Рекомендации по выбору режима отслеживания

| Режим | Когда применять | Особенности |
| :--- | :--- | :--- |
| **Явный (Explicit)** | Критические системы, БД, StatefulSets | Исключает случайные перезапуски при изменении соседних ресурсов. |
| **Автоматический (`auto`)** | Stateless микросервисы, Dev/Stage среды | Максимальное удобство, автоматический охват всех ENV и Volumes. |
| **Гибридный** | Смешанные среды | `auto` для Dev, `explicit` для Production. |

### Типичные ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Приложение не перезапускается | Отсутствуют аннотации | Добавьте `reloader.stakater.com/auto: "true"` |
| Массовые перезапуски | Отсутствует debounce | Добавьте `deployment.reloader.stakater.com/pause-period: "5m"` |
| Reloader не видит namespace | `--namespaces-to-ignore` | Проверьте аргументы контроллера |
| ArgoCD показывает OutOfSync | Нет ignoreDifferences | Добавьте аннотацию в ignoreDifferences |
| Конфликт с Helm checksum | Два механизма одновременно | Выберите один: checksum ИЛИ Reloader |

### Производительность

- **Задержка обнаружения:** <5 секунд для изменений ConfigMap/Secret.
- **Задержка перезапуска:** Зависит от debounce-настроек (по умолчанию 0).
- **Потребление ресурсов:** ~100m CPU, ~128Mi RAM на контроллер.
- **Лимиты:** Один контроллер может отслеживать до 10 000 ресурсов.

---

## См. также

- [Установка и настройка Reloader](./reloader_installation.md)
- [Мониторинг и лучшие практики](./reloader_monitoring_and_best_practices.md)
- [Безопасность Reloader](./reloader_security.md)
- [Runbooks и реагирование на инциденты](./reloader_runbooks.md)
- [Helm templating: Restart on Change](../Helm/templating/scenarios/restart_on_change.md)
- [ArgoCD: Ignore Differences](../../GitOps/ArgoCD/synchronization/ignore_differences.md)
