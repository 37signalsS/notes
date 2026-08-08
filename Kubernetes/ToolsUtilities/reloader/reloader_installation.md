# Reloader — Установка и настройка

## Определения

**Установка Reloader** — процесс развёртывания контроллера Reloader в Kubernetes-кластере для автоматического отслеживания изменений в ConfigMap/Secret и инициирования плавного обновления (Rolling Upgrade) рабочих нагрузок (workloads).

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Основные концепции

### Способы установки

| Способ | Когда использовать | Преимущества |
| :--- | :--- | :--- |
| **Helm** | Production, GitOps (ArgoCD/Flux) | Управление версиями, поддержка HA, простая параметризация через `values.yaml`. |
| **Манифесты (YAML)** | Быстрое развёртывание, Air-gapped | Не требует сторонних инструментов, полный контроль над каждым ресурсом. |
| **Kustomize** | GitOps без шаблонизации | Нативный подход Kubernetes, отсутствие "магии" шаблонов. |

### Требования к RBAC

Reloader требует Role-Based Access Control (RBAC) для мониторинга ресурсов и внесения изменений.

- **Ресурсы конфигурации:** `secrets`, `configmaps` — методы `list`, `get`, `watch`.
- **Рабочие нагрузки:** `deployments`, `daemonsets`, `statefulsets`, `deployments.extensions` — методы `list`, `get`, `watch`, `update`, `patch`.
- **Интеграции:**
  - **Argo Rollouts:** `rollouts.argoproj.io` — `list`, `get`, `watch`, `update`, `patch`.
  - **Secrets Store CSI:** `secretproviderclasspodstatuses.secrets-store.csi.x-k8s.io` — `list`, `get`, `watch` (требуется при включении `--enable-csi-integration`).
- **Дополнительно:** `cronjobs` — методы `list`, `get`, `watch`.

### Ресурсы и масштабирование

Контроллер потребляет ресурсы пропорционально количеству отслеживаемых объектов и частоте обновлений в кластере.

| Параметр | Рекомендация (S/M кластер) | Описание |
| :--- | :--- | :--- |
| **CPU Request** | 100m | Минимальное резервирование. |
| **CPU Limit** | 300m | Для обработки всплесков при массовом обновлении. |
| **Memory Request** | 128Mi | Базовое потребление. |
| **Memory Limit** | 512Mi | Лимит для предотвращения OOM-kill при кешировании API. |

---

## Практические сценарии

### Сценарий 1: Установка через Helm (Рекомендуется для Production)

Метод обеспечивает гибкое управление конфигурацией и нативную интеграцию с GitOps.

**1. Добавление репозитория:**

```bash
helm repo add stakater https://stakater.github.io/stakater-charts
helm repo update
# → result: "stakater" has been added to your repositories
```

**2. Создание расширенного `values.yaml` (v1.4.19):**

```yaml
# values.yaml
reloader:
  replicas: 2 # Режим High Availability (HA)
  watchGlobally: true
  
  # Безопасность: Включение User Namespaces (v1.4+)
  # Требует Kubernetes 1.25+ и поддержки в CRI (containerd/CRIO)
  podContext:
    hostUsers: false

  deployment:
    image:
      tag: v1.4.19 # Go 1.26.2, UBI 9 base image
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 300m
        memory: 512Mi

  args:
    - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
    - --log-level=info
    - --enable-csi-integration=true
    - --reload-strategy=annotations
    - --ignore-annotation=false # Установите true для глобального форсирования релоадов
```

**3. Выполнение установки:**

```bash
helm install reloader stakater/reloader \
  --namespace reloader-system \
  --create-namespace \
  --values values.yaml
# → result: NAME: reloader, STATUS: deployed, NAMESPACE: reloader-system
```

---

### Сценарий 2: Установка через полные манифесты (Air-gapped / Manual)

Подходит для систем с ограниченным доступом или когда требуется детальный аудит манифестов.

**Манифест `reloader-setup.yaml`:**

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: reloader-system
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: reloader
  namespace: reloader-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: reloader-role
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    verbs: ["list", "get", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "daemonsets", "statefulsets"]
    verbs: ["list", "get", "watch", "update", "patch"]
  - apiGroups: ["secrets-store.csi.x-k8s.io"]
    resources: ["secretproviderclasspodstatuses"]
    verbs: ["list", "get", "watch"]
  - apiGroups: ["argoproj.io"]
    resources: ["rollouts"]
    verbs: ["list", "get", "watch", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: reloader-role-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: reloader-role
subjects:
  - kind: ServiceAccount
    name: reloader
    namespace: reloader-system
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: reloader-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: reloader
  template:
    metadata:
      labels:
        app: reloader
    spec:
      serviceAccountName: reloader
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        fsGroup: 65534
        # seccompProfile:
        #   type: RuntimeDefault
      containers:
        - name: reloader
          image: ghcr.io/stakater/reloader:v1.4.19
          args:
            - --namespaces-to-ignore=kube-system,kube-public
            - --log-level=info
            - --reload-strategy=annotations
            - --enable-csi-integration=true
          ports:
            - containerPort: 9090
              name: http
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 300m
              memory: 512Mi
```

---

### Сценарий 3: Настройка для GitOps (ArgoCD / Flux)

Для стабильной работы в GitOps необходимо исключить "петли синхронизации" (sync loops).

1.  **Стратегия `annotations`:** Позволяет ArgoCD видеть только изменение аннотации, а не переменных окружения, что чище.
2.  **Ignore Differences:** Исключите аннотацию из сверки состояния.

```yaml
# ArgoCD Application snippet
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

---

## Проверка установки

**1. Статус контроллера:**

```bash
kubectl get pods -n reloader-system -l app=reloader
# → result: reloader-xxxxxxxxxx-xxxxx  1/1  Running  0  10m
```

**2. Валидация прав (Self-test):**

```bash
# Проверка возможности патчить Deployment
kubectl auth can-i patch deployments --as=system:serviceaccount:reloader-system:reloader
# → result: yes
```

**3. Логи инициализации:**

```bash
kubectl logs -f deployment/reloader -n reloader-system
# → result: level=info msg="Reloader started"
# → result: level=info msg="Watching for changes in all namespaces"
```

---

## Дополнительная информация

### Совместимость версий

| Версия Reloader | Kubernetes | Helm | Go |
| :--- | :--- | :--- | :--- |
| **v1.4.19** | 1.26 - 1.30+ | 3.12+ | 1.26.2 |
| **v1.3.x** | 1.24 - 1.28 | 3.10+ | 1.21.x |

### Параметры безопасности

Reloader спроектирован с учётом принципов **Zero Trust** и **Supply Chain Security**:

- **Signed Images:** Образы подписаны через Cosign (Enterprise).
- **Non-root:** Запуск от UID 65534.
- **Minimal RBAC:** Возможность ограничения контроллера конкретными неймспейсами через `--namespaces-to-select`.
- **User Namespaces:** Изоляция пользователей на уровне ядра Linux для предотвращения container breakout.

### Ресурсы

- [Stakater GitHub: Reloader](https://github.com/stakater/Reloader)
- [ArtifactHub: Chart Reloader](https://artifacthub.io/packages/helm/stakater/reloader)
- [Мониторинг и лучшие практики](./reloader_monitoring_and_best_practices.md)
- [Практические сценарии использования](./reloader_usage_scenarios.md)

