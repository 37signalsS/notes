# Установка и настройка Kyverno

## Определения

**Установка Kyverno** — процесс развертывания компонентов управления политиками в кластер Kubernetes. В современной инфраструктуре (актуально на 2026 год, версия 1.18+) стандартом является установка через **Helm** в режиме высокой доступности (**High Availability, HA**) с преимущественным использованием нативного движка **CEL (Common Expression Language)**.

---

## Основные концепции

### Компоненты системы

| Компонент | Назначение | Режим (HA) |
| :--- | :--- | :--- |
| **Admission Controller** | Обработка мутаций, валидаций и верификаций образов в реальном времени. | 3 реплики |
| **Background Controller** | Применение политик к существующим ресурсам и управление генерацией. | 2 реплики |
| **Reports Controller** | Сбор и агрегация отчетов `PolicyReport`. Поддерживает внешние БД. | 2 реплики |
| **Cleanup Controller** | Автоматическое удаление ресурсов по расписанию (`CleanupPolicy`). | 2 реплики |

**Системные Namespace:**
- `kyverno` — контроллеры и admission webhook
- `kyverno-reports` — reports controller (при внешнем PostgreSQL)

### Системные требования (Production-ready)

| Параметр | Минимальные | Рекомендуемые (1000+ подов) |
| :--- | :--- | :--- |
| Kubernetes | 1.29+ | 1.31+ |
| CPU | 2 ядра | 4+ ядра (суммарно на компоненты) |
| RAM | 2 GB | 8+ GB |
| Хранилище | etcd (встроенное) | PostgreSQL (для внешних отчетов) |

### Стратегия API версий (v1 vs v2)

С версии Kyverno 1.18+ рекомендуется использовать **CEL-политики** (`policies.kyverno.io/v1`) вместо классических `ClusterPolicy` (`kyverno.io/v1`).

| Ресурс | API Group | Статус | Когда использовать |
| :--- | :--- | :--- | :--- |
| **ClusterPolicy** | `kyverno.io/v1` | **Устаревает** (удаление в v1.20) | Только legacy-сценарии без CEL. |
| **ValidatingPolicy** | `policies.kyverno.io/v1` | **Рекомендуется** | CEL-валидация,_CIDR-проверки, RBAC. |
| **MutatingPolicy** | `policies.kyverno.io/v1` | **Рекомендуется** | Инъекция sidecar, меток, env. |
| **GeneratingPolicy** | `policies.kyverno.io/v1` | **Рекомендуется** | Генерация NetworkPolicy, ResourceQuota. |
| **ImageValidatingPolicy** | `policies.kyverno.io/v1alpha1` | **Актуально** | Верификация образов (Sigstore/Cosign). |

**Важно:** v2-политики (CEL) не требуют отдельного admission webhook — они работают через нативный `ValidatingAdmissionPolicy` Kubernetes. Это снижает латентность на 40-60% по сравнению с JMESPath-политиками.

### Установка Kyverno CLI

Kyverno CLI используется для тестирования политик перед деплоем в кластер.

```bash
# macOS (Homebrew)
brew install kyverno

# Linux (amd64)
curl -sLO https://github.com/kyverno/kyverno/releases/latest/download/kyverno_linux_amd64.tar.gz
tar -xzf kyverno_linux_amd64.tar.gz
sudo mv kyverno /usr/local/bin/

# Проверка версии
kyverno version
# → Version: 1.18.0
```

**Полезные команды:**
```bash
# Валидация манифестов
kyverno apply policies/ --resource=deployment.yaml

# Юнит-тесты
kyverno test tests/

# Валидация с генерацией отчета
kyverno apply policies/ --resource=manifests/ --output-format json > report.json
```

---

## Практические сценарии

### 1. Промышленная установка через Helm (HA + CEL)

Для продуктивных сред рекомендуется использовать распределение подов по узлам и зонам (Anti-Affinity).

```bash
# Добавление репозитория
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update

# Установка (версия 2026 года)
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --version 3.8.0 \
  -f values.yaml
```

**Оптимальный `values.yaml` (v1.18+):**
```yaml
admissionController:
  replicas: 3
  priorityClassName: system-cluster-critical
  containerSecurityContext:
    allowPrivilegeEscalation: false
    capabilities: { drop: ["ALL"] }
    readOnlyRootFilesystem: true
    runAsNonRoot: true
  # Интеграция с Sigstore для верификации образов
  externalHttp:
    allowedHosts: ["sigstore.dev", "api.github.com", "ghcr.io"]

backgroundController:
  replicas: 2

reportsController:
  replicas: 2
  extraArgs:
    - --reportsChunkSize=1000

webhooks:
  # Защита системных Namespace от блокировки при сбоях Kyverno
  namespaceSelector:
    matchExpressions:
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values: ["kyverno", "kube-system", "monitoring"]
```

### 2. Управление сертификатами через cert-manager

По умолчанию Kyverno генерирует самоподписанные сертификаты. В 2026 году промышленным стандартом является использование **cert-manager**.

**Настройка в `values.yaml`**:
```yaml
admissionController:
  webhook:
    # Использование cert-manager для управления TLS-сертификатами
    certManager:
      enabled: true
      issuerRef:
        name: root-ca-issuer
        kind: ClusterIssuer
```

### 3. Настройка внешнего хранилища для отчетов (PostgreSQL)

В крупных кластерах хранение тысяч `PolicyReport` в etcd приводит к деградации API-сервера. Рекомендуется использовать внешний Reports Server.

**Настройка Reports Server**:
```yaml
reportsController:
  reportsServer:
    enabled: true
    database:
      type: postgres
      host: postgres-ha.db-namespace.svc
      name: kyverno_reports
      existingSecret: kyverno-db-creds
```

### 4. Особенности работы с Service Mesh (Istio / Linkerd)

При использовании Service Mesh необходимо исключить Kyverno из инъекции sidecar-контейнеров, чтобы избежать циклической зависимости при проверке подов самого Kyverno.

**Аннотации для Namespace**:
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: kyverno
  labels:
    # Исключение из Istio
    istio-injection: disabled
    # Исключение из Linkerd
    linkerd.io/is-control-plane: "true"
```

### 5. Развертывание через Argo CD (GitOps)

При использовании Argo CD необходимо включить **Server-Side Apply (SSA)** для корректной обработки CRD и мутаций.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kyverno-core
spec:
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true # Обязательно для больших CRD
  source:
    repoURL: https://kyverno.github.io/kyverno
    chart: kyverno
    targetRevision: 3.8.0
```
*Подробности см. в [Интеграция с Argo CD](./argo-cd.md).*

### 6. Локальная разработка (Dev/Testing)

Для локального тестирования политик рекомендуется использовать **kind** или **minikube**. В этих средах HA не требуется.

**kind (рекомендуется):**
```bash
# Установка kind
brew install kind

# Создание кластера
kind create cluster --name kyverno-dev

# Установка Kyverno без HA ( dev-режим)
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --set admissionController.replicas=1 \
  --set backgroundController.replicas=1 \
  --set reportsController.replicas=1 \
  --set cleanupController.replicas=1 \
  --set deletionPropagationPolicy=None
```

**minikube:**
```bash
# Запуск minikube с нужными ресурсами
minikube start --cpus=4 --memory=8g

# Установка Kyverno
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --set admissionController.replicas=1 \
  --set backgroundController.replicas=1
```

**k3s (легковесный):**
```bash
# Установка k3s без built-in Traefik
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable=traefik" sh -

# Установка Kyverno
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --kubeconfig=/etc/rancher/k3s/k3s.yaml
```

**Docker Desktop:**
```bash
# Включите Kubernetes в Docker Desktop → Settings → Kubernetes → Enable Kubernetes

# Установка Kyverno
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --set admissionController.replicas=1 \
  --set backgroundController.replicas=1
```

### 7. Настройка мониторинга (Prometheus + Grafana)

Kyverno экспортирует метрики через Prometheus. Для включения:

**Настройка в `values.yaml`**:
```yaml
# Включение метрик для всех контроллеров
admissionController:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
      namespace: monitoring
      interval: 30s

backgroundController:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
      namespace: monitoring

reportsController:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
      namespace: monitoring
```

**Полезные метрики Prometheus:**
```promql
# Количество PolicyReport с ошибками
kyverno_policy_results_total{result="fail"}

# Количество Admission Review запросов
kyverno_admission_requests_total{resource_state="changed"}

# Количество UpdateRequests в ошибке
kyverno_update_requests_total{status_type="error"}

# Латентность admission review
kyverno_admission_review_duration_seconds_bucket
```

**Grafana Dashboard:**
- Импортируйте dashboard ID `15673` из [Grafana.com](https://grafana.com/grafana/dashboards/) для мониторинга Kyverno.
- Или используйте [Policy Reporter UI](./reporter.md) для визуализации PolicyReport.

---

## Верификация после установки (Post-Install)

### 1. Проверка контроллеров

```bash
# Проверка что все поды в Running
kubectl get pods -n kyverno -o wide
# → NAME                                        READY   STATUS    RESTARTS
# → kyverno-admission-controller-xxxxx          3/3     Running   0
# → kyverno-background-controller-xxxxx         1/1     Running   0
# → kyverno-reports-controller-xxxxx            1/1     Running   0
# → kyverno-cleanup-controller-xxxxx            1/1     Running   0

# Проверка версии
kubectl get deployment -n kyverno kyverno-admission-controller \
  -o jsonpath='{.metadata.labels.app\.kubernetes\.io/version}'
# → 1.18.0
```

### 2. Проверка вебхуков

```bash
# Проверка что вебхуки зарегистрированы
kubectl get mutatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno
kubectl get validatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno

# Проверка что namespaceSelector работает (системные NS исключены)
kubectl get validatingwebhookconfigurations \
  -l app.kubernetes.io/instance=kyverno \
  -o jsonpath='{.items[0].webhooks[0].namespaceSelector}' | jq .
```

### 3. Тестовая политика (Smoke Test)

```bash
# Применение тестовой CEL-политики
cat <<EOF | kubectl apply -f -
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: smoke-test-require-labels
spec:
  validationActions: [Audit]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
  validations:
    - expression: |
        has(object.metadata.labels) &&
        has(object.metadata.labels['app'])
      message: "Label 'app' обязателен для всех Pod'ов."
EOF

# Проверка что политика применена
kubectl get validatingpolicy smoke-test-require-labels

# Создание Pod без label (должен сгенерировать предупреждение)
kubectl run test-pod --image=nginx --restart=Never

# Проверка PolicyReport
kubectl get polr -n default
```

### 4. Проверка RBAC контроллеров

```bash
# Проверка что background-controller может создавать ресурсы
kubectl auth can-i create networkpolicies \
  --namespace=default \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
# → yes

# Проверка что cleanup-controller может удалять Pod'ы
kubectl auth can-i delete pods \
  --namespace=default \
  --as=system:serviceaccount:kyverno:kyverno-cleanup-controller
# → yes

# Проверка что reports-controller может создавать ConfigMaps
kubectl auth can-i create configmaps \
  --namespace=default \
  --as=system:serviceaccount:kyverno:kyverno-reports-controller
# → yes
```

---

## Техническое обслуживание и обновление

### Стратегия обновления (Upgrading)

Обновление Kyverno требует осторожности из-за влияния на все операции в кластере.
1. **Бэкап политик**: Экспортируйте текущие `ClusterPolicy`.
2. **Обновление CRD**: В Kyverno CRD часто содержат ломающие изменения. Всегда используйте `kubectl apply --server-side` перед запуском `helm upgrade`.
3. **Audit Mode**: Перед переходом на новую мажорную версию переведите критические политики в режим `Audit`.
4. **Постепенный роллаут**: Обновляйте сначала контроллеры отчетов и очистки, затем admission-контроллер.

### Бэкап и восстановление политик

```bash
# Экспорт всех ClusterPolicy
kubectl get clusterpolicy -o yaml > kyverno-policies-backup.yaml

# Экспорт всех ValidatingPolicy (CEL)
kubectl get validatingpolicy -o yaml > kyverno-cel-policies-backup.yaml

# Экспорт PolicyReport (для отладки)
kubectl get polr -A -o yaml > kyverno-reports-backup.yaml

# Восстановление из бэкапа
kubectl apply -f kyverno-policies-backup.yaml
kubectl apply -f kyverno-cel-policies-backup.yaml
```

**Автоматизация бэкапа (CronJob):**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: kyverno-backup
  namespace: backup
spec:
  schedule: "0 2 * * *"  # Ежедневно в 02:00
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: kyverno-backup
          containers:
          - name: backup
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl get clusterpolicy -o yaml > /backup/policies-$(date +%Y%m%d).yaml
              kubectl get validatingpolicy -o yaml > /backup/cel-policies-$(date +%Y%m%d).yaml
              find /backup -name "*.yaml" -mtime +30 -delete
            volumeMounts:
            - name: backup-volume
              mountPath: /backup
          volumes:
          - name: backup-volume
            persistentVolumeClaim:
              claimName: kyverno-backup-pvc
          restartPolicy: OnFailure
```

### Удаление системы

1. Удалите все `ClusterPolicy` и `Policy` (иначе вебхуки могут заблокировать удаление Namespace).
2. Выполните `helm uninstall kyverno -n kyverno`.
3. Очистите оставшиеся вебхуки: `kubectl delete mutatingwebhookconfigurations,validatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno`.
4. Удалите CRD (опционально): `kubectl delete crd -l app.kubernetes.io/instance=kyverno`.

---

## Дополнительная информация

### Типичные ошибки и диагностика

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Deadlock при старте** | Вебхук блокирует поды CNI/CSI. | Используйте `namespaceSelector` для исключения системных пространств имен. |
| **Webhook timeout** | Задержка проверки образов (Sigstore). | Проверьте доступ к внешним хостам или увеличьте `timeoutSeconds`. |
| **CRD too large** | Лимит `last-applied-configuration`. | Используйте Server-Side Apply (`--server-side`). |
| **Memory Leak** | Большой объем PolicyReports. | Включите агрегацию отчетов или используйте внешнюю БД. |
| **Pod не проходит admission** | Политика в режиме `Enforce` блокирует поды. | Переведите политику в `Audit` или добавьте `PolicyException`. |
| **Generate не создает ресурсы** | Нет прав RBAC у `background-controller`. | Проверьте ClusterRole `kyverno-bg-controller` ([подробнее](../additional.md)). |
| **UpdateRequests в ошибке** | `generate`/`mutateExisting` не может применить изменения. | Проверьте права `background-controller` на целевой ресурс. |
| **CEL expression error** | Невалидный синтаксис CEL. | Проверьте выражение на [cel-playground.appspot.com](https://cel-playground.appspot.com). |
| **Reports Controller не запускается** | Неверные данные для подключения к PostgreSQL. | Проверьте Secret `kyverno-db-creds` и доступность PostgreSQL. |

### Диагностические команды

```bash
# Логи admission-controller
kubectl logs -n kyverno -l app.kubernetes.io/component=admission-controller --tail=100

# Логи background-controller
kubectl logs -n kyverno -l app.kubernetes.io/component=background-controller --tail=100

# Логи reports-controller
kubectl logs -n kyverno -l app.kubernetes.io/component=reports-controller --tail=100

# Логи cleanup-controller
kubectl logs -n kyverno -l app.kubernetes.io/component=cleanup-controller --tail=100

# Состояние всех политик
kubectl get clusterpolicy,validatingpolicy,mutatingpolicy -o wide

# Состояние UpdateRequests
kubectl get updaterequests -n kyverno -o wide

# Состояние PolicyReport
kubectl get polr -A
```

### См. также

- **[Политики: Типы правил (SSoT)](./rules.md)** — глубокий разбор match, validate, generate, clone, verifyImages, cleanup.
- **[Политики: Библиотека практических примеров](./policies/practical_scenarios.md)** — готовые YAML для копирования.
- **[Политики: Advanced Topics](./policies/advanced_topics.md)** — mutateExisting, CEL, autogen.
- **[Политики: Определения и концепции (SSoT)](./policies/definitions_and_concepts.md)** — лайфсайкл политики, v1 vs v2.
- **[Агрегированные роли и права доступа](./additional.md)** — права контроллеров на генерацию и мутацию.
- **[Отчеты и AdmissionReports](./reports.md)** — PolicyReport, ClusterPolicyReport, внешнее хранилище.
- **[Интеграция с Argo CD: Server-Side Diff и Health Checks](./argo-cd.md)** — SSA, managedFields, Health Checks.
- **[Сценарии: Automation & Compliance](./Scenarios/automation_compliance.md)** — CIS Benchmark, NIS2, PCI DSS, SOC 2.
- **[Reporter: Policy Reporter UI](./reporter.md)** — Prometheus/Grafana метрики, dashboard.
- **[kube-bench: CIS Benchmark аудит](../../kube-bench.md)** — проверка конфигурации кластера на CIS.
