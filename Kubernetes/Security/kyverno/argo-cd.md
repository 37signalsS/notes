# Интеграция Kyverno с Argo CD

## Определения

**Интеграция Kyverno с Argo CD** — настройка совместного использования policy-движка Kyverno и GitOps-платформы Argo CD для корректной работы мутации и валидации ресурсов.

> **Проблема**: Argo CD и Kyverno могут конфликтовать из-за разных подходов к отслеживанию ресурсов и сравнению состояний.

---

## Basic Concepts

### Источники конфликтов

| Конфликт | Причина | Последствия |
|----------|---------|-------------|
| **Resource Tracking** | Оба используют labels для отслеживания ресурсов | Argo CD теряет контроль над ресурсами |
| **Server-side Diff** | Kyverno мутирует манифесты после применения | Бесконечный цикл синхронизации |
| **Mutation Webhooks** | Argo CD не учитывает изменения от webhook | Ложные различия в состоянии |
| **Aggregated Roles** | Kyverno динамически изменяет роли | Argo CD показывает изменения |

---

## Practical Scenarios

### 1. Конфликт меток (Resource Tracking)

**Проблема**: Argo CD и Kyverno используют одинаковый механизм отслеживания ресурсов через метки (`labels`).

**Решение**: Перевести Argo CD на использование **annotations** вместо labels.

```yaml
# values.yaml Argo CD
resourceTrackingMethod: annotation
```

**Альтернативно для конкретного приложения**:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/tracking-method: annotation
```

### 2. Server-side Diff

**Проблема**: Argo CD по умолчанию сравнивает манифесты из Git с состоянием в кластере. При использовании Kyverno (который может мутировать манифесты) возникает бесконечный цикл синхронизации.

**Решение**: Включить `server-side diff` в Argo CD.

**Глобально** (в `values.yaml` Argo CD):

```yaml
controller:
  diff:
    serverSide: true
```

**Для конкретного приложения** (аннотация):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/compare-options: ServerSideDiff=true
```

### 3. Mutation Webhooks

**Проблема**: Kyverno может изменять (мутировать) манифесты в процессе admission. Argo CD необходимо учитывать эти изменения при сравнении.

**Решение**: Добавить аннотацию к приложению в Argo CD.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-options: IncludeMutationWebhook=true
```

> **Важно**: Работает только при включенном `server-side diff`.

### 4. Aggregated Roles

**Проблема**: Kyverno использует Aggregated Cluster Roles, что приводит к динамическому изменению ролей. Argo CD может некорректно обрабатывать эти изменения.

**Решение**: В `values.yaml` Argo CD указать:

```yaml
resource:
  compare:
    ignoreAggregatedRoles: true
```

### 5. Установка Kyverno через Argo CD

Подробная инструкция — в [Установка Kyverno](./install.md).

---

## Additional Information

### Сводная таблица настроек Argo CD

| Настройка | Файл | Значение | Назначение |
|-----------|------|----------|------------|
| `resourceTrackingMethod` | `values.yaml` | `annotation` | Избежание конфликта меток |
| `controller.diff.serverSide` | `values.yaml` | `true` | Учет мутаций Kyverno |
| `resource.compare.ignoreAggregatedRoles` | `values.yaml` | `true` | Игнорирование динамических ролей |
| `argocd.argoproj.io/compare-options` | Annotation | `ServerSideDiff=true` | Server-side diff для приложения |
| `argocd.argoproj.io/sync-options` | Annotation | `IncludeMutationWebhook=true` | Учет мутаций webhook |
| `applyServerSide` | Application | `true` | Server-side apply для установки |

### Проверка конфигурации

```bash
# Проверка текущего состояния приложения
argocd app get my-app

# Принудительная синхронизация с server-side apply
argocd app sync my-app --server-side

# Проверка различий с учетом мутаций
argocd app diff my-app --server-side
```

### Troubleshooting

| Проблема | Решение |
|----------|---------|
| Бесконечный цикл синхронизации | Включить `server-side diff` |
| Argo CD теряет ресурсы | Переключить на `annotation` tracking |
| Ошибки webhook при установке | Использовать `applyServerSide: true` |
| Ложные изменения в ролях | Включить `ignoreAggregatedRoles: true` |

### Связанные темы

- [Установка Kyverno](./install.md) — установка через Helm и Argo CD
- [Aggregated Cluster Roles](./additional.md) — механизм расширения прав
- [Мутация ресурсов](./rules.md) — как Kyverno изменяет манифесты
