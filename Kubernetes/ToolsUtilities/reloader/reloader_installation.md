# Reloader — Установка и настройка

## Определения

**Установка Reloader** — процесс развёртывания контроллера Reloader в Kubernetes-кластере для автоматического отслеживания изменений в ConfigMap/Secret и инициирования плавного обновления (Rolling Upgrade) рабочих нагрузок (workloads).

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Предварительные требования

### Версии и зависимости

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Kubernetes** | 1.26 | 1.28+ | User Namespaces требует 1.25+ |
| **Helm** (для установки через чарт) | 3.10 | 3.12+ | Для управления версиями и HA |
| **Go** (для сборки из исходников) | 1.26.2 | 1.26.2 | Версия, использованная в официальном билде |

### Сетевые требования

- Доступ к API Server Kubernetes (стандартный порт 443).
- Доступ к реестрам образов: `ghcr.io/stakater/reloader` (OSS) или `quay.io/stakater/reloader` (Enterprise).
- Если используется CSI-интеграция: доступ к эндпоинту Secrets Store CSI Driver.

### Требования к кластеру

- **RBAC:** Возможность создания ServiceAccount, ClusterRole и ClusterRoleBinding.
- **StorageClass:** Не требуется (контроллер не использует PersistentVolume).
- **Сеть:** Нет специфических требований к сетевым политикам (NetworkPolicy).

---

## Основные концепции

### Способы установки

| Способ | Когда использовать | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Helm** | Production, GitOps (ArgoCD/Flux) | Управление версиями, поддержка HA, простая параметризация через `values.yaml`. | Зависимость от Helm, "магия" шаблонов. |
| **Манифесты (YAML)** | Быстрое развёртывание, Air-gapped | Не требует сторонних инструментов, полный контроль над каждым ресурсом. | Сложность обновления, ручное управление версиями. |
| **Kustomize** | GitOps без шаблонизации | Нативный подход Kubernetes, отсутствие "магии" шаблонов. | Требует понимания Kustomize, ограниченная параметризация. |

### Требования к RBAC

Reloader требует Role-Based Access Control (RBAC) для мониторинга ресурсов и внесения изменений.

**Минимальные права (ClusterRole):**

| Ресурс | API Group | Методы | Описание |
| :--- | :--- | :--- | :--- |
| `secrets`, `configmaps` | `""` | `list`, `get`, `watch` | Чтение конфигураций |
| `deployments`, `daemonsets`, `statefulsets` | `apps` | `list`, `get`, `watch`, `update`, `patch` | Управление рабочими нагрузками |
| `rollouts` | `argoproj.io` | `list`, `get`, `watch`, `update`, `patch` | Интеграция с Argo Rollouts |
| `secretproviderclasspodstatuses` | `secrets-store.csi.x-k8s.io` | `list`, `get`, `watch` | CSI-интеграция (опционально) |
| `cronjobs` | `batch` | `list`, `get`, `watch` | Мониторинг CronJob |

**Scoped RBAC (рекомендуется для больших кластеров):**

Вместо ClusterRole используйте Role в каждом namespace для минимизации прав:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: reloader-role
  namespace: target-namespace
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    verbs: ["list", "get", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "daemonsets", "statefulsets"]
    verbs: ["list", "get", "watch", "update", "patch"]
```

### Ресурсы и масштабирование

Контроллер потребляет ресурсы пропорционально количеству отслеживаемых объектов и частоте обновлений в кластере.

| Параметр | S/M кластер (<100 ns) | L кластер (100-500 ns) | XL кластер (>5000 ns) | Описание |
| :--- | :--- | :--- | :--- | :--- |
| **CPU Request** | 100m | 200m | 500m | Минимальное резервирование. |
| **CPU Limit** | 300m | 500m | 1000m | Для обработки всплесков при массовом обновлении. |
| **Memory Request** | 128Mi | 256Mi | 512Mi | Базовое потребление. |
| **Memory Limit** | 512Mi | 1Gi | 2Gi | Лимит для предотвращения OOM-kill при кешировании API. |
| **Реплики (HA)** | 1-2 | 2-3 | 3+ | Для отказоустойчивости. |

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
  replicas: 2  # Режим High Availability (HA)
  watchGlobally: true

  # Безопасность: Включение User Namespaces (v1.4+)
  # Требует Kubernetes 1.25+ и поддержки в CRI (containerd/CRI-O)
  podContext:
    hostUsers: false

  deployment:
    image:
      tag: v1.4.19  # Go 1.26.2, UBI 9 base image
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 300m
        memory: 512Mi

  # Планирование (опционально)
  # nodeSelector:
  #   node-role: control-plane
  # tolerations:
  #   - key: "node-role.kubernetes.io/master"
  #     operator: "Exists"
  #     effect: "NoSchedule"

  args:
    - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
    - --log-level=info
    - --enable-csi-integration=true
    - --reload-strategy=annotations
    - --ignore-annotation=false  # Установите true для глобального форсирования релоадов
    - --sync-after-restart=true  # Полная сверка после перевыборов лидера

  # Pod Disruption Budget (для HA)
  podDisruptionBudget:
    enabled: true
    minAvailable: 1

  # Service Monitor для Prometheus (если установлен Prometheus Operator)
  serviceMonitor:
    enabled: true
    namespace: monitoring
    interval: 30s
```

**3. Выполнение установки:**

```bash
helm install reloader stakater/reloader \
  --namespace reloader-system \
  --create-namespace \
  --values values.yaml
# → result: NAME: reloader, STATUS: deployed, NAMESPACE: reloader-system
```

**4. Проверка статуса:**

```bash
helm status reloader -n reloader-system
# → result: STATUS: deployed, REVISION: 1
```

### Сценарий 2: Обновление Reloader

**Обновление через Helm:**

```bash
# Обновление чарта
helm repo update
helm upgrade reloader stakater/reloader \
  --namespace reloader-system \
  --values values.yaml \
  --reuse-values  # Сохранение текущих значений
# → result: Release "reloader" has been upgraded.
```

**Обновление версии образа:**

```bash
helm upgrade reloader stakater/reloader \
  --namespace reloader-system \
  --set reloader.deployment.image.tag=v1.4.19 \
  --reuse-values
```

**Откат обновления:**

```bash
helm rollback reloader 1 -n reloader-system
# → result: Release "reloader" has been rolled back.
```

### Сценарий 3: Установка через полные манифесты (Air-gapped / Manual)

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
  replicas: 2  # HA режим
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
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: reloader
          image: ghcr.io/stakater/reloader:v1.4.19
          args:
            - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
            - --log-level=info
            - --reload-strategy=annotations
            - --enable-csi-integration=true
            - --sync-after-restart=true
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
          livenessProbe:
            httpGet:
              path: /healthz
              port: 9090
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /readyz
              port: 9090
            initialDelaySeconds: 5
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: reloader
  namespace: reloader-system
  labels:
    app: reloader
spec:
  ports:
    - port: 9090
      name: http
      targetPort: 9090
  selector:
    app: reloader
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: reloader-pdb
  namespace: reloader-system
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: reloader
```

**Применение манифестов:**

```bash
kubectl apply -f reloader-setup.yaml
# → result: namespace/reloader-system created
# → result: serviceaccount/reloader created
# → result: clusterrole.rbac.authorization.k8s.io/reloader-role created
# → result: clusterrolebinding.rbac.authorization.k8s.io/reloader-role-binding created
# → result: deployment.apps/reloader created
# → result: service/reloader created
# → result: poddisruptionbudget.policy/reloader-pdb created
```

### Сценарий 4: Установка через Kustomize

Для GitOps без шаблонизации Helm.

**Структура каталогов:**

```
reloader-kustomize/
├── base/
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── serviceaccount.yaml
│   ├── clusterrole.yaml
│   ├── clusterrolebinding.yaml
│   └── deployment.yaml
└── overlays/
    └── production/
        ├── kustomization.yaml
        ├── replicas-patch.yaml
        └── args-patch.yaml
```

**base/kustomization.yaml:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - namespace.yaml
  - serviceaccount.yaml
  - clusterrole.yaml
  - clusterrolebinding.yaml
  - deployment.yaml
```

**overlays/production/kustomization.yaml:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

patchesStrategicMerge:
  - replicas-patch.yaml
  - args-patch.yaml
```

**Применение:**

```bash
kubectl apply -k overlays/production/
# → result: All resources applied from overlays/production/
```

### Сценарий 5: Настройка для GitOps (ArgoCD / Flux)

Для стабильной работы в GitOps необходимо исключить "петли синхронизации" (sync loops).

1. **Стратегия `annotations`:** Позволяет ArgoCD видеть только изменение аннотации, а не переменных окружения, что чище.
2. **Ignore Differences:** Исключите аннотацию из сверки состояния.

```yaml
# ArgoCD Application snippet
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
  name: reloader
  namespace: flux-system
spec:
  interval: 10m
  path: ./kubernetes/reloader/overlays/production
  sourceRef:
    kind: GitRepository
    name: flux-system
  postBuild:
    substituteFrom:
      - kind: ConfigMap
        name: cluster-config
```

### Сценарий 6: Air-gapped установка (закрытые кластеры)

Для кластеров без доступа к интернету.

**1. Скачивание образов:**

```bash
# На машине с интернетом
docker pull ghcr.io/stakater/reloader:v1.4.19
docker tag ghcr.io/stakater/reloader:v1.4.19 harbor.local/stakater/reloader:v1.4.19
docker push harbor.local/stakater/reloader:v1.4.19
```

**2. Скачивание Helm чарта:**

```bash
helm pull stakater/reloader --version 2.2.14
tar -xzf reloader-2.2.14.tgz
# Загрузить в artifact repository (Nexus, Artifactory)
```

**3. Установка из локального реестра:**

```bash
helm install reloader ./reloader \
  --namespace reloader-system \
  --create-namespace \
  --set reloader.deployment.image.repository=harbor.local/stakater/reloader \
  --set reloader.deployment.image.tag=v1.4.19 \
  --values values.yaml
```

### Сценарий 7: Использование приватного реестра образов

Для кластеров с auth-protected реестрами.

**1. Создание Secret:**

```bash
kubectl create secret docker-registry regcred \
  --docker-server=harbor.local \
  --docker-username=admin \
  --docker-password=Harbor12345 \
  -n reloader-system
```

**2. Использование в Helm:**

```yaml
# values.yaml
reloader:
  deployment:
    imagePullSecrets:
      - name: regcred
```

**3. Использование в манифестах:**

```yaml
spec:
  template:
    spec:
      imagePullSecrets:
        - name: regcred
```

---

## Проверка установки

### Базовая проверка

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

# Проверка возможности читать secrets
kubectl auth can-i list secrets --as=system:serviceaccount:reloader-system:reloader
# → result: yes

# Проверка в конкретном namespace
kubectl auth can-i patch deployments -n production --as=system:serviceaccount:reloader-system:reloader
# → result: yes
```

**3. Логи инициализации:**

```bash
kubectl logs -f deployment/reloader -n reloader-system
# → result: level=info msg="Reloader started"
# → result: level=info msg="Watching for changes in all namespaces"
```

### Продвинутая проверка

**4. Проверка метрик:**

```bash
kubectl port-forward deployment/reloader 9090:9090 -n reloader-system &
curl -s http://localhost:9090/metrics | head -20
# → result: # HELP reloader_resource_watch_total Total number of resources watched
# → result: # TYPE reloader_resource_watch_total counter
```

**5. Проверка Health Checks:**

```bash
kubectl port-forward deployment/reloader 9090:9090 -n reloader-system &
curl -s http://localhost:9090/healthz
# → result: ok

curl -s http://localhost:9090/readyz
# → result: ok
```

**6. Тестовое отслеживание:**

```bash
# Создание тестового ConfigMap
kubectl create configmap test-config --from-literal=key=value -n default

# Добавление аннотации к Deployment
kubectl annotate deployment test-app reloader.stakater.com/auto=true -n default

# Изменение ConfigMap
kubectl patch configmap test-config -p '{"data":{"key":"new-value"}}' -n default

# Проверка логов Reloader
kubectl logs deployment/reloader -n reloader-system --tail=10 | grep test-config
# → result: level=info msg="Triggered rolling upgrade for deployment/default/test-app"
```

---

## Устранение неполадок установки

### Типичные ошибки

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Pod не стартует (CrashLoopBackOff)** | Неверный образ или проблемы с RBAC | Проверьте логи: `kubectl logs -n reloader-system -l app=reloader` |
| **`forbidden: "patch" not allowed`** | Недостаточно прав ClusterRole | Расширьте права на `update`, `patch` для deployments |
| **`error: unable to recognize`** | Несовместимая версия Kubernetes | Проверьте таблицу совместимости ниже |
| **Helm install timeout** | Медленный кластер или проблемы с сетью | Увеличьте `--timeout 5m` |
| **ImagePullBackOff** | Нет доступа к реестру образов | Создайте imagePullSecret или настройте mirror registry |
| **Reloader не отслеживает namespace** | `--namespaces-to-ignore` включает этот ns | Проверьте аргументы контроллера |
| **Высокое потребление CPU** | Слишком много отслеживаемых ресурсов | Ограничьте namespace через `--namespaces-to-select` |
| **Leader Election не работает** | Нет доступа к endpointsleases | Добавьте права на `endpointsleases` в `coordination.k8s.io` |

### Диагностические команды

```bash
# Проверка статуса пода
kubectl get pod -n reloader-system -l app=reloader -o wide

# Детальная информация о поде
kubectl describe pod -n reloader-system -l app=reloader

# Проверка событий
kubectl get events -n reloader-system --sort-by='.lastTimestamp'

# Проверка RBAC
kubectl get clusterrole reloader-role -o yaml
kubectl get clusterrolebinding reloader-role-binding -o yaml

# Проверка деплоя
kubectl get deployment reloader -n reloader-system -o yaml
```

---

## Удаление Reloader

### Через Helm

```bash
helm uninstall reloader -n reloader-system
# → result: release "reloader" uninstalled

# Удаление namespace (опционально)
kubectl delete namespace reloader-system
```

### Через манифесты

```bash
kubectl delete -f reloader-setup.yaml
# Или вручную:
kubectl delete deployment reloader -n reloader-system
kubectl delete service reloader -n reloader-system
kubectl delete clusterrolebinding reloader-role-binding
kubectl delete clusterrole reloader-role
kubectl delete serviceaccount reloader -n reloader-system
kubectl delete namespace reloader-system
```

### Очистка аннотаций

После удаления контроллера аннотации на Deployment остаются, но не влияют на работу:

```bash
# Удаление аннотаций (опционально)
kubectl annotate deployment <name> reloader.stakater.com/auto- -n <namespace>
kubectl annotate deployment <name> configmap.reloader.stakater.com/reload- -n <namespace>
kubectl annotate deployment <name> secret.reloader.stakater.com/reload- -n <namespace>
```

---

## Дополнительная информация

### Совместимость версий

| Версия Reloader | Kubernetes | Helm | Go | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **v1.4.19** | 1.26 - 1.30+ | 3.12+ | 1.26.2 | Текущая стабильная версия |
| **v1.3.x** | 1.24 - 1.28 | 3.10+ | 1.21.x | Предыдущий стабильный релиз |

### Параметры безопасности

Reloader спроектирован с учётом принципов **Zero Trust** и **Supply Chain Security**:

- **Signed Images:** Образы подписаны через Cosign (Enterprise).
- **Non-root:** Запуск от UID 65534.
- **Minimal RBAC:** Возможность ограничения контроллера конкретными неймспейсами через `--namespaces-to-select`.
- **User Namespaces:** Изоляция пользователей на уровне ядра Linux для предотвращения container breakout.
- **Seccomp Profile:** Использование RuntimeDefault для ограничения системных вызовов.
- **Read-only Root FS:** Возможность включения через SecurityContext.

### Ресурсы

- [Stakater GitHub: Reloader](https://github.com/stakater/Reloader)
- [ArtifactHub: Chart Reloader](https://artifacthub.io/packages/helm/stakater/reloader)
- [Мониторинг и лучшие практики](./reloader_monitoring_and_best_practices.md)
- [Практические сценарии использования](./reloader_usage_scenarios.md)
- [Обзор Reloader](./reloader_overview.md)
