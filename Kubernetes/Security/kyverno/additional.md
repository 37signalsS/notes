# Агрегированные роли Kyverno и продвинутые возможности

## Определения

**Агрегированные ClusterRoles** — механизм Kubernetes, позволяющий динамически расширять права существующих ролей через использование селекторов по меткам (labels). В контексте Kyverno это основной способ предоставления контроллерам прав на манипуляцию ресурсами (создание, изменение, удаление) без прямого редактирования системных ролей.

**Global Context (v1.15+)** — механизм кэширования данных из внешних источников (API, ConfigMaps) для использования в политиках без нагрузки на внешние системы при каждом Admission-запросе.

**Update Request (UR)** — внутренний ресурс Kyverno, используемый для отслеживания и выполнения асинхронных операций мутации и генерации существующих ресурсов.

---

## Основные концепции

### Механизм агрегации прав

По умолчанию контроллеры Kyverno работают в режиме минимальных привилегий. Для выполнения активных действий (генерация сетевых политик, мутация лейблов) необходимо делегировать соответствующие права.

**Алгоритм настройки**:
1. Определение целевого контроллера (например, `background-controller` для генерации).
2. Создание `ClusterRole` с необходимыми `verbs` (get, list, watch, create, update, patch).
3. Добавление метки агрегации с префиксом `rbac.kyverno.io/`.

### Контроллеры и метки агрегации (v3.x)

| Контроллер | Метка агрегации | Назначение прав |
| :--- | :--- | :--- |
| **admission-controller** | `rbac.kyverno.io/aggregate-to-admission-controller: "true"` | Права на чтение данных для сложных CEL-валидаций. |
| **background-controller** | `rbac.kyverno.io/aggregate-to-background-controller: "true"` | Права на `generate` и `mutateExisting`. |
| **reports-controller** | `rbac.kyverno.io/aggregate-to-reports-controller: "true"` | Управление жизненным циклом `PolicyReports`. |
| **cleanup-controller** | `rbac.kyverno.io/aggregate-to-cleanup-controller: "true"` | Удаление ресурсов по расписанию. |

### Продвинутые механизмы 2026 года

*   **Global Context**: Позволяет политике обращаться к кэшированным данным (например, списку разрешенных пользователей из внешней системы) за `O(1)`, что критично для производительности Admission-контроля.
*   **Автоматическое управление UR**: В версиях 1.14+ Kyverno автоматически очищает успешно выполненные `UpdateRequests`, предотвращая засорение хранилища `etcd`.
*   **CEL-First Admission**: Использование нативных `ValidatingAdmissionPolicies` Kubernetes для базовых проверок снижает задержку (latency) API-запросов на 30–50%.

---

## Практические сценарии

### 1. Делегирование прав на генерацию (Generate)

Необходимо для политик, создающих инфраструктурные объекты (NetworkPolicy, ResourceQuota) при появлении нового Namespace.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno:generate-network-policies
  labels:
    rbac.kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["create", "update", "delete", "get", "list", "watch"]
```

### 2. Настройка Global Context для внешних данных

Используется для кэширования данных из внешнего API или тяжелого ConfigMap.

**Определение GlobalContext**:
```yaml
apiVersion: kyverno.io/v1alpha2
kind: GlobalContextEntry
metadata:
  name: allowed-teams-cache
spec:
  kubernetesResource:
    group: ""
    version: "v1"
    kind: ConfigMap
    name: teams-metadata
    namespace: kyverno
```

**Использование в политике**:
```yaml
spec:
  rules:
    - name: check-team-exists
      context:
        - name: teams
          globalContextEntry: allowed-teams-cache
      validate:
        cel:
          expressions:
            - "variables.teams.data.allowed.contains(object.metadata.labels['team'])"
```

### 3. Управление жизненным циклом (Cleanup TTL)

Kyverno позволяет реализовать концепцию "временных сред" без написания сложных политик, используя стандартные метки.

```yaml
# Пример временного Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: feature-branch-qa
  labels:
    cleanup.kyverno.io/ttl: "12h" # Удаление через 12 часов
```

---

## Техническое обслуживание и диагностика

### Мониторинг UpdateRequests

Если фоновые операции (мутация существующих ресурсов) не выполняются, проверьте состояние ресурсов UR:

```bash
# Просмотр зависших или ошибочных запросов на обновление
kubectl get updaterequests -n kyverno

# Диагностика прав через auth can-i
kubectl auth can-i patch deployments \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
```

### Оптимизация Reports Server

При использовании внешнего сервера отчетов ([см. reports.md](./reports.md)) убедитесь, что `reports-controller` имеет права на запись в агрегированный API.

---

## Дополнительная информация

### Связанные темы

- **[Обзор RBAC](../rbac/rbac_overview.md)** — основы управления доступом.
- **[Сценарии агрегации ролей](../rbac/aggregation_scenarios.md)** — общие примеры расширения прав в Kubernetes.
- **[Основные концепции Kyverno](./concepts.md)** — архитектура и движок CEL.
- **[Типы правил (rules)](./rules.md)** — подробности работы mutate и generate.

### Ссылки и ресурсы

- [Kyverno Reports Server](https://github.com/kyverno/reports-server) — внешнее хранилище для масштабируемых отчетов.
- [Официальная документация по Global Context](https://kyverno.io/docs/writing-policies/context/global-context/)
