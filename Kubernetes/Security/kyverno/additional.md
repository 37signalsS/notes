# Дополнительная информация Kyverno: Агрегированные роли

## Определения

**Aggregated Cluster Roles (Агрегированные роли кластера)** — механизм Kubernetes, позволяющий динамически расширять права существующих ролей через использование специальных лейблов (меток). В контексте Kyverno этот механизм критически важен для предоставления контроллерам прав на создание, изменение или удаление ресурсов, которыми они управляют в рамках политик.

---

## Основные концепции

### Механизм агрегации в Kyverno

По умолчанию контроллеры Kyverno обладают ограниченным набором прав для обеспечения безопасности кластера. Например, они не могут создавать ресурсы типа `Secret` без явного разрешения.

**Как это работает**:

1. Вы создаете новую `ClusterRole`, описывающую необходимые права (например, `create` для секретов).
2. Вы добавляете к этой роли лейбл Kyverno: `kyverno.io/aggregate-to-<controller>-controller: "true"`.
3. Kubernetes автоматически объединяет эти права с основной ролью соответствующего контроллера.
4. Контроллер получает новые возможности без необходимости перезагрузки или изменения его основной конфигурации.

Общую теорию работы агрегированных ролей можно найти в разделе **[Агрегация ролей RBAC](../rbac/aggregation_scenarios.md)**.

### Контроллеры Kyverno и их лейблы

| Контроллер | Лейбл для агрегации прав | Основная задача |
|------------|--------------------------|-----------------|
| **admission-controller** | `kyverno.io/aggregate-to-admission-controller: "true"` | Обработка мутирующих и валидирующих вебхуков. |
| **background-controller** | `kyverno.io/aggregate-to-background-controller: "true"` | Фоновое сканирование ресурсов и генерация объектов (`generate`). |
| **reports-controller** | `kyverno.io/aggregate-to-reports-controller: "true"` | Создание и обновление отчетов по политикам. |
| **cleanup-controller** | `kyverno.io/aggregate-to-cleanup-controller: "true"` | Удаление ресурсов согласно политикам очистки. |

---

## Практические сценарии

### 1. Права для генерации секретов (Secret)

Для работы политики `generate`, создающей секреты, необходимо предоставить права `background-controller`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno-generate-secret
  labels:
    # Привязка прав к фоновому контроллеру
    kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["create", "update", "delete", "get", "list", "watch"]
```

### 2. Права для генерации сетевых политик (NetworkPolicy)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno-generate-network-policy
  labels:
    kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["create", "update", "delete", "get", "list", "watch"]
```

### 3. Права для чтения конфигураций (ConfigMap)

Если политика валидации должна считывать данные из `ConfigMap`, права нужны `admission-controller`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno-read-configmap
  labels:
    kyverno.io/aggregate-to-admission-controller: "true"
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
```

### Проверка примененных прав

Для подтверждения того, что права были успешно агрегированы, используйте следующие команды:

```bash
# Поиск всех ClusterRole, агрегируемых в Kyverno
kubectl get clusterrole -l 'kyverno.io/aggregate-to-background-controller=true'

# Просмотр итоговых прав фонового контроллера
kubectl get clusterrole kyverno:background -o yaml

# Проверка возможности выполнения действия от имени сервис-аккаунта
kubectl auth can-i create secrets --as=system:serviceaccount:kyverno:kyverno-background-controller
# → yes
```

---

## Дополнительная информация

### Связанные темы

- **[RBAC Overview](../rbac/rbac_overview.md)** — основы управления доступом (Role-Based Access Control).
- **[Pod Security Context](../pod_security_context.md)** — миграция с устаревших PSP (Pod Security Policies) на современные PSS (Pod Security Standards) и PSA (Pod Security Admission).
- **[Установка Kyverno](./install.md)** — базовая настройка компонентов.
- **[Основные концепции Kyverno](./concepts.md)** — архитектура admission-контроллеров.
- **[Типы правил](./rules.md)** — подробнее о механизме `generate` и мутациях.
