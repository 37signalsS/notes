# ArgoCD — игнорирование различий и принудительная синхронизация

## Определения

**Игнорирование различий (Ignore Differences)** — механизм ArgoCD, позволяющий исключать конкретные поля ресурсов из процесса сравнения (diffing). Это предотвращает ложные срабатывания статуса `OutOfSync` для полей, которые изменяются внешними контроллерами или мутирующими вебхуками.

**Принудительная синхронизация (Force Sync)** — режим, при котором ArgoCD использует `kubectl apply --force`. Это приводит к удалению и повторному созданию ресурса, если обычное обновление невозможно из-за конфликтов или неизменяемых (immutable) полей.

**managedFieldsManagers** — современный метод игнорирования различий, основанный на Kubernetes Server-Side Apply. Позволяет игнорировать все поля, которыми управляет конкретный контроллер (например, HPA или cert-manager), без перечисления каждого поля вручную.

## Базовые концепции

### Методы настройки игнорирования

ArgoCD предлагает три основных способа указать поля для игнорирования:

1.  **jsonPointers**: Классический метод, использующий RFC6901 (например, `/spec/replicas`).
2.  **jqPathExpressions**: Более гибкий метод, позволяющий использовать логику JQ (например, для фильтрации элементов в списках по имени).
3.  **managedFieldsManagers**: Самый надежный метод для 2024-2025 гг. Он опирается на метаданные `managedFields` и автоматически игнорирует любые изменения, внесенные указанным менеджером.

### Уровни конфигурации

- **Локальный (Application level)**: Настраивается непосредственно в манифесте `Application`. Удобно для специфичных для приложения правок.
- **Глобальный (System level)**: Настраивается в ConfigMap `argocd-cm`. Позволяет задать общие правила для всего кластера (например, игнорирование системных аннотаций облачных провайдеров).

### Параметр RespectIgnoreDifferences

По умолчанию `ignoreDifferences` влияет только на визуальный статус в UI. При запуске синхронизации (особенно автоматической) ArgoCD может попытаться "исправить" эти поля.
Для того чтобы ArgoCD **не перезаписывал** игнорируемые поля во время синхронизации, необходимо установить `RespectIgnoreDifferences=true` в `syncOptions`.

### Server-Side Diffing

В новых версиях ArgoCD поддерживает перенос процесса сравнения на сторону API-сервера Kubernetes. Это значительно снижает количество "шума" от мутирующих вебхуков (например, при инъекции sidecar-контейнеров Istio), так как Kubernetes учитывает результат работы всех вебхуков перед сравнением.

## Практические сценарии

### Сценарий 1: Интеграция с HPA через managedFieldsManagers

Это рекомендуемый способ решения конфликтов между ArgoCD и Horizontal Pod Autoscaler. Вместо перечисления полей `/spec/replicas`, мы доверяем контроллеру Kubernetes.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    managedFieldsManagers:
    - kube-controller-manager # Игнорировать всё, чем управляет HPA
  syncPolicy:
    syncOptions:
    - RespectIgnoreDifferences=true
```

### Сценарий 2: Глобальное игнорирование системных полей

Настройка в `argocd-cm` для автоматического игнорирования полей статуса и меток облачных провайдеров для всех приложений.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
data:
  # Глобальное игнорирование полей статуса
  resource.compareoptions: |
    ignoreResourceStatusField: all

  # Игнорирование меток, добавляемых внешними системами
  resource.customizations.ignoreDifferences.all: |
    jqPathExpressions:
    - .metadata.labels["cloud.google.com/gke-installed-by"]
    - .metadata.annotations["control-plane.alpha.kubernetes.io/leader"]
```

### Сценарий 3: Использование jqPathExpressions для списков

Если нужно проигнорировать изменения в конкретном контейнере (например, sidecar), но отслеживать остальные.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jqPathExpressions:
    - .spec.template.spec.containers[] | select(.name == "istio-proxy")
```

### Сценарий 4: Принудительное обновление застрявших ресурсов

Если ресурс содержит неизменяемое поле, которое изменилось в Git, синхронизация завершится ошибкой. В этом случае используется `Force Sync`.

**Через CLI:**
```bash
argocd app sync my-app --force
```

**В манифесте Application:**
```yaml
spec:
  syncPolicy:
    retry:
      limit: 2
    syncOptions:
    - Force=true # Опасно: приводит к пересозданию ресурса
```

## Дополнительная информация

- **[Синхронизация ArgoCD](../synchronization.md)** — общий обзор политик и механизмов.
- **[Автоматическая синхронизация](./scenarios/auto_sync.md)** — детальная настройка `selfHeal` и `RespectIgnoreDifferences`.
- [ArgoCD Documentation: Diff Customization](https://argo-cd.readthedocs.io/en/stable/user-guide/diff-customization/) — официальное руководство по настройке сравнения.
