# Управление политиками безопасности через GitOps (GitOps-мозг)

Этот документ описывает архитектурный подход к централизованому управлению политиками безопасности в множестве Kubernetes-кластеров с использованием ArgoCD, Teleport и движков политик (Gatekeeper, Kyverno).

## Определения

**GitOps-мозг (Policy Brain)** — концепция централизованного управляющего кластера (Management Cluster), который выступает единственным источником правды для политик безопасности всей организации. Он доставляет конфигурации во все подключенные кластеры, обеспечивая единообразие и наблюдаемость.

**Teleport Access Plane** — инфраструктурное решение для управления доступом, используемое в данной архитектуре как защищенный прокси-слой. Оно позволяет ArgoCD подключаться к API-серверам удаленных кластеров без прямого сетевого доступа и VPN.

**Gatekeeper (OPA)** — агент безопасности в целевых кластерах, выполняющий проверку ресурсов на соответствие политикам, написанным на языке **Rego**.

**Kyverno** — K8s-native движок политик, использующий YAML для описания правил валидации, мутации и генерации ресурсов.

**tbot (Teleport Bot)** — компонент Teleport для машинной аутентификации, который генерирует кратковременные сертификаты и обновляет их автоматически для работы ArgoCD.

**opus-scorecard** — специализированный экспортер для Gatekeeper, позволяющий преобразовывать детальную информацию о нарушениях (violations) из статусов CRD в метрики формата Prometheus.

**execProviderConfig** — механизм в ArgoCD (с v1.8.0), позволяющий использовать внешние скрипты для получения учетных данных (kubeconfig/tokens) при подключении к удаленным кластерам.

---

## Архитектура решения

Центральным компонентом является **ArgoCD**, развернутый в Hub-кластере, который:
1. Забирает политики (Rego/YAML) и манифесты из Git.
2. Подключается к удаленным кластерам (Spokes) через **Teleport Proxy**.
3. Доставляет объекты `ConstraintTemplate`, `Constraint` (Gatekeeper) или `ClusterPolicy` (Kyverno).
4. Отслеживает состояние синхронизации и наличие нарушений.

### Схема взаимодействия
`Git (Policies) → ArgoCD (Hub) → Teleport Proxy → Remote Clusters (Gatekeeper/Kyverno)`

---

## Интеграция ArgoCD и Teleport

Для подключения ArgoCD к кластерам через Teleport используется скрипт аутентификации, запускаемый через `execProviderConfig`.

### 1. Настройка секрета кластера в ArgoCD

В секрете, описывающем удаленный кластер, настраивается секция `execProviderConfig`.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: remote-cluster-secret
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
type: Opaque
stringData:
  config: |
    {
      "execProviderConfig": {
        "command": "/usr/local/bin/teleport-auth.sh",
        "args": ["--cluster-name", "prod-cluster-01"],
        "apiVersion": "client.authentication.k8s.io/v1beta1"
      }
    }
  name: prod-cluster-01
  # Использование локального сервиса-прокси для обхода ограничений ArgoCD на уникальность URL
  server: https://cluster-prod-01-proxy.argocd.svc.cluster.local:3026
```

### 2. Скрипт аутентификации (teleport-auth.sh)

Скрипт использует утилиту `tbot` (Teleport Bot) для получения временных учетных данных. В 2026 году рекомендуется использовать режим фонового обновления сертификатов `tbot`.

```bash
#!/bin/bash
# Аргументы передаются из execProviderConfig
CLUSTER_NAME=$2

# Получение актуального kubeconfig через tbot
# Предполагается, что tbot запущен как sidecar или daemonset с доступом к /var/lib/tbot
tbot proxy kube --cluster-name="${CLUSTER_NAME}" --out-file="/tmp/kubeconfig-${CLUSTER_NAME}" > /dev/null 2>&1

# Возврат JSON для Kubernetes exec credential plugin
cat "/tmp/kubeconfig-${CLUSTER_NAME}" | jq -c '.auth_info' # Пример упрощенной логики
```

### 3. Решение проблемы уникальности эндпоинтов (ExternalName)

ArgoCD может некорректно обрабатывать несколько кластеров, если у них один и тот же URL прокси (Teleport).
**Решение:** Создание объектов `Service` типа `ExternalName` для каждого кластера в namespace ArgoCD.

```yaml
kind: Service
apiVersion: v1
metadata:
  name: cluster-prod-01-proxy
  namespace: argocd
spec:
  type: ExternalName
  externalName: teleport.example.com # Реальный адрес Teleport Proxy
```

---

## Управление политиками (Git-структура)

Для гибкого управления политиками репозиторий разделяется на логические уровни:

1.  **`white/`** — глобальные политики для всех кластеров (например, запрет privileged-контейнеров, обязательные лейблы).
2.  **`zones/`** — группировка по зонам ответственности (production, test, pci-dss).
3.  **`clusters/`** — специфические исключения или настройки для конкретного кластера.

**Механизм доставки:**
ArgoCD использует **ApplicationSet** с генераторами (`Git` или `Cluster`), которые считывают метаданные кластеров и автоматически подключают соответствующие папки из Git.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: policy-deployment
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            security-tier: high
  template:
    spec:
      source:
        path: policies/zones/high-security
        repoURL: https://git.example.com/sec/policies.git
      destination:
        server: "{{server}}"
        namespace: gatekeeper-system
```

---

## Наблюдаемость и мониторинг нарушений

Стандартный Gatekeeper не экспортирует детали нарушений (какой именно объект нарушил политику) в стандартные метрики.

### Использование opus-scorecard
Решение `opus-scorecard` собирает информацию о `violations` из статуса объектов `Constraint` и предоставляет их по эндпоинту `/metrics`.

**Ключевые метрики для Grafana:**
- `gatekeeper_violations` — общее количество нарушений.
- `gatekeeper_constraint_status` — состояние синхронизации политик.

### Policy Reporter
Для Kyverno и Gatekeeper рекомендуется использовать **Policy Reporter UI**, который агрегирует `PolicyReports` и предоставляет удобный интерфейс для ИБ-специалистов, включая отправку уведомлений в Slack/Teams при появлении новых нарушений.

---

## Производительность и масштабирование

При управлении большим количеством кластеров (100+) необходимо:

- **Шардирование контроллера (Controller Sharding):** ArgoCD требует масштабирования `argocd-application-controller` (примерно 1 реплика на 20-30 кластеров в зависимости от количества ресурсов).
- **Оптимизация tbot:** Использование кэширования для токенов Teleport в памяти (tmpfs), чтобы снизить нагрузку на диск и ускорить время отклика `execProviderConfig`.
- **Лимиты ресурсов:** Увеличьте `memory` для `repo-server`, так как рендеринг множества ApplicationSets требует значительного объема RAM.
- **Tuning ArgoCD:** Установка `ARGOCD_EXEC_TIMEOUT` (по умолчанию 90с) может потребоваться увеличить при медленных ответах через прокси.

---

## Исключения и гибкость политик

Исключения могут быть реализованы на трех уровнях:

### 1. На уровне Git
Удаление/добавление манифестов `Constraint` в папках конкретных кластеров через ApplicationSet.

### 2. Параметры Constraint (Gatekeeper)
Использование поля `match.excludedNamespaces` или `match.labelSelector` в манифесте политики.

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequiredLabels
metadata:
  name: ns-must-have-owner
spec:
  match:
    excludedNamespaces:
      - kube-system
      - istio-system
    labelSelector:
      matchExpressions:
        - {key: security, operator: NotIn, values: [ignored]}
```

### 3. Внутри Rego-кода (OPA)
Проверка специфических меток (labels) на ресурсах через инвентаризацию данных (`data.inventory`).

```rego
# Пример исключения в Rego
package kubernetes.admission

deny[msg] {
    # Проверка метки исключения на namespace
    not is_excluded_namespace(input.request.namespace)
    # Логика: запрет образов без хэша (sha256)
    [image, tag] := split(input.request.object.spec.containers[_].image, ":")
    not contains(image, "@sha256")
    msg := "Образы должны содержать digest (sha256)."
}

is_excluded_namespace(ns) {
    data.inventory.cluster["v1"]["Namespace"][ns].metadata.labels["security.policy/ignore"] == "true"
}
```

### 4. Исключения в Kyverno
Использование блока `exclude` в правилах политики, что позволяет гибко отсекать ресурсы по именам, ролям или меткам.

---

## Жизненный цикл и тестирование (Policy as Code)

Политики безопасности напрямую влияют на доступность API-сервера. Ошибка в Rego-коде или YAML-манифесте Kyverno может привести к блокировке критических процессов в кластере.

### Тестирование (Validation)
1.  **OPA / Gatekeeper:** Использование `conftest` или `opa test` для проверки логики Rego-правил на синтетических манифестах перед их фиксацией в Git.
2.  **Kyverno:** Использование `kyverno CLI` (команда `test`) для проверки политик на соответствие ожидаемым результатам (режим `pass/fail`).
3.  **Dry-run (Audit):** Первичное внедрение новых политик всегда выполняется в режиме `Audit` (Gatekeeper) или `Audit` (Kyverno), чтобы оценить влияние на существующие ресурсы без их блокировки.

### Пайплайн продвижения
Рекомендуемый процесс доставки политик:
`Linting & Unit Tests → Validation in Sandbox → Audit Mode in Staging → Enforce Mode in Production`

---

## Дополнительная информация

### См. также
- **[OPA Gatekeeper: детали и Rego](../../Kubernetes/Security/rbac/limitations_opa.md)** — глубокий разбор движка OPA.
- **[Интеграция Kyverno с ArgoCD](../../Kubernetes/Security/kyverno/argo-cd.md)** — нюансы Server-Side Diff и мутаций.
- **[ArgoCD: обзор архитектуры](../ArgoCD/argocd_overview.md)** — базовые принципы GitOps.
- **[Управление секретами в GitOps](../secrets_encryption.md)** — шифрование креденшилов для доступа к кластерам.
