# Агрегированные роли Kyverno и дополнительные возможности

## Определения

**Агрегированные ClusterRoles** — механизм Kubernetes, позволяющий динамически расширять права существующих ролей через использование селекторов по меткам (labels). В контексте Kyverno этот механизм является основным способом предоставления контроллерам прав на манипуляцию ресурсами (создание, изменение, удаление) без прямого редактирования стандартных ролей приложения.

В современных версиях Kyverno (2024–2025) рекомендуется использовать метки с префиксом `rbac.kyverno.io/` для обеспечения безопасности и модульности.

---

## Основные концепции

### Механизм расширения прав

По умолчанию контроллеры Kyverno работают по принципу минимальных привилегий. Например, `background-controller` не имеет прав на создание секретов, пока они не будут явно предоставлены через агрегацию.

**Алгоритм работы**:
1. Создается `ClusterRole` с необходимыми правилами (`rules`).
2. В метаданные роли добавляется метка, соответствующая конкретному контроллеру.
3. Kubernetes автоматически объединяет эти правила с системной ролью контроллера.

### Контроллеры и метки агрегации

| Контроллер | Метка для агрегации прав | Основная задача |
|------------|--------------------------|-----------------|
| **admission-controller** | `rbac.kyverno.io/aggregate-to-admission-controller: "true"` | Валидация и мутация ресурсов в момент поступления запроса в API-сервер. |
| **background-controller** | `rbac.kyverno.io/aggregate-to-background-controller: "true"` | Выполнение операций `generate`, фоновое сканирование и мутация существующих ресурсов. |
| **reports-controller** | `rbac.kyverno.io/aggregate-to-reports-controller: "true"` | Управление жизненным циклом отчетов `PolicyReport`. |
| **cleanup-controller** | `rbac.kyverno.io/aggregate-to-cleanup-controller: "true"` | Удаление ресурсов по расписанию или согласно TTL-меткам. |

### Продвинутые механизмы (2025)

*   **CEL-политики**: Использование `ValidatingAdmissionPolicies` позволяет выполнять проверки на стороне Kubernetes без вызова внешнего вебхука, что повышает производительность и надежность.
*   **Reports Server**: Для крупных инсталляций (более 1000 узлов) рекомендуется использовать внешний сервер отчетов для разгрузки `etcd`.
*   **Least Privilege**: В версии 1.16+ поддерживаются Namespaced-политики (например, `NamespacedDeletingPolicy`), позволяющие ограничить область действия прав конкретными пространствами имен.

---

## Практические сценарии

### 1. Права на генерацию секретов

Необходимы для работы политик `generate`, создающих `Secret` (например, при инициализации нового Namespace).

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno:generate-secrets
  labels:
    rbac.kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["create", "update", "delete", "get", "list", "watch"]
```

### 2. Права на очистку старых ресурсов (Cleanup)

Для автоматического удаления завершенных подов или временных ресурсов.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno:cleanup-pods
  labels:
    rbac.kyverno.io/aggregate-to-cleanup-controller: "true"
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch", "delete"]
```

### 3. TTL-управление через метки

Kyverno поддерживает автоматическую очистку через добавление меток к самим ресурсам, что избавляет от необходимости создавать отдельные политики для простых сценариев.

```yaml
# Пример добавления TTL к временному пространству имен
apiVersion: v1
kind: Namespace
metadata:
  name: temp-dev-env
  labels:
    cleanup.kyverno.io/ttl: "24h" # Будет удалено через 24 часа после создания
```

### Проверка агрегации прав

```bash
# Проверка, какие роли агрегируются в фоновый контроллер
kubectl get clusterrole -l 'rbac.kyverno.io/aggregate-to-background-controller=true'

# Валидация итоговых прав сервис-аккаунта
kubectl auth can-i create secrets \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
# → yes
```

---

## Дополнительная информация

### Связанные темы

- **[Обзор RBAC](../rbac/rbac_overview.md)** — теоретические основы управления доступом.
- **[Сценарии агрегации ролей](../rbac/aggregation_scenarios.md)** — подробные примеры использования `aggregationRule` в Kubernetes.
- **[Pod Security Context](../pod_security_context.md)** — переход с PSP на PSS/PSA.
- **[Установка Kyverno](./install.md)** — развертывание компонентов admission-контроллера.
- **[Основные концепции](./concepts.md)** — архитектура и жизненный цикл политики.

### Ссылки и ресурсы

- [Kyverno Reports Server](https://github.com/kyverno/reports-server) — внешнее хранилище для отчетов.
- [OpenReports API](https://openreports.io) — стандарт отчетности по безопасности в Kubernetes.
