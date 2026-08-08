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

### Системные требования (Production-ready)

| Параметр | Минимальные | Рекомендуемые (1000+ подов) |
| :--- | :--- | :--- |
| Kubernetes | 1.29+ | 1.31+ |
| CPU | 2 ядра | 4+ ядра (суммарно на компоненты) |
| RAM | 2 GB | 8+ GB |
| Хранилище | etcd (встроенное) | PostgreSQL (для внешних отчетов) |

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

---

## Техническое обслуживание и обновление

### Стратегия обновления (Upgrading)

Обновление Kyverno требует осторожности из-за влияния на все операции в кластере.
1. **Бэкап политик**: Экспортируйте текущие `ClusterPolicy`.
2. **Обновление CRD**: В Kyverno CRD часто содержат ломающие изменения. Всегда используйте `kubectl apply --server-side` перед запуском `helm upgrade`.
3. **Audit Mode**: Перед переходом на новую мажорную версию переведите критические политики в режим `Audit`.
4. **Постепенный роллаут**: Обновляйте сначала контроллеры отчетов и очистки, затем admission-контроллер.

### Удаление системы

1. Удалите все `ClusterPolicy` и `Policy` (иначе вебхуки могут заблокировать удаление Namespace).
2. Выполните `helm uninstall kyverno -n kyverno`.
3. Очистите оставшиеся вебхуки: `kubectl delete mutatingwebhookconfigurations,validatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno`.
4. Удалите CRD (опционально): `kubectl delete crd -l app.kubernetes.io/instance=kyverno`.

---

## Дополнительная информация

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Deadlock при старте** | Вебхук блокирует поды CNI/CSI. | Используйте `namespaceSelector` для исключения системных пространств имен. |
| **Webhook timeout** | Задержка проверки образов (Sigstore). | Проверьте доступ к внешним хостам или увеличьте `timeoutSeconds`. |
| **CRD too large** | Лимит `last-applied-configuration`. | Используйте Server-Side Apply (`--server-side`). |
| **Memory Leak** | Большой объем PolicyReports. | Включите агрегацию отчетов или используйте внешнюю БД. |

### См. также
- [Интеграция с Argo CD: Server-Side Diff и Health Checks](./argo-cd.md)
- [Основные концепции: Механизм Admission и CEL](./concepts.md)
- [Типы правил: написание эффективных политик](./rules.md)
- [Агрегированные роли и права доступа](./additional.md)
