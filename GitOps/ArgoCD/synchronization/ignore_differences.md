# Argo CD — игнорирование различий и принудительная синхронизация

> **Актуальность (2026):** В версии Argo CD v3.x механизмы сравнения ресурсов (diffing) стали более интеллектуальными благодаря глубокой интеграции с **Server-Side Apply (SSA)**. Основным методом игнорирования динамических изменений стал `managedFieldsManagers`, который заменяет ручное перечисление полей через JSON Pointers в 90% случаев.

## Определения

**Игнорирование различий (Ignore Differences)** — механизм Argo CD, позволяющий исключать конкретные поля или целые группы полей ресурсов из процесса сравнения (diffing). Это предотвращает ложные срабатывания статуса `OutOfSync` для полей, которые изменяются внешними контроллерами, мутирующими вебхуками или автоматикой облачных провайдеров.

**Принудительная синхронизация (Force Sync)** — режим, при котором Argo CD использует команду `kubectl apply --force`. Это приводит к удалению и повторному созданию ресурса, если обычное обновление (patch/update) невозможно из-за конфликтов или наличия неизменяемых (immutable) полей.

**managedFieldsManagers** — метод игнорирования, основанный на метаданных `managedFields` в Kubernetes. Позволяет Argo CD автоматически игнорировать любые изменения, внесенные указанным контроллером (менеджером), не требуя ручного указания путей к полям.

**Server-Side Diffing** — режим, при котором вычисление разницы между Git и кластером делегируется API-серверу Kubernetes. Это позволяет учитывать работу всех мутирующих вебхуков (например, инъекцию sidecar-контейнеров) до проведения сравнения.

## Базовые концепции

### Методы настройки игнорирования

Argo CD предлагает три способа идентификации полей для исключения:

1.  **managedFieldsManagers (Рекомендуемый):** Опирается на то, *кто* изменил поле. Самый надежный метод для систем типа HPA, cert-manager или облачных контроллеров.
2.  **jqPathExpressions:** Опирается на логику JQ. Позволяет выбирать элементы в списках по условию (например, контейнер с конкретным именем в массиве `containers`).
3.  **jsonPointers:** Опирается на RFC6901. Классический метод указания жесткого пути к полю (например, `/spec/replicas`).

### Уровни конфигурации

- **Локальный (Application level):** Правила описываются внутри манифеста `Application` в секции `spec.ignoreDifferences`. Применяются только к конкретному приложению.
- **Глобальный (System level):** Настраивается в ConfigMap `argocd-cm`. Позволяет задать общие правила (Customizations) для всех приложений в кластере на основе Group/Kind ресурсов.

### Параметр RespectIgnoreDifferences

По умолчанию `ignoreDifferences` влияет только на визуальный статус (превращает `OutOfSync` в `Synced`). Однако при запуске синхронизации Argo CD по умолчанию попытается привести поле в соответствие с Git.
Чтобы Argo CD **не перезаписывал** игнорируемые поля во время автоматической или ручной синхронизации, необходимо установить параметр `RespectIgnoreDifferences=true` в `syncOptions`.

## Практические сценарии

### Сценарий 1: Совместная работа с HPA (v3.x Way)

Вместо перечисления поля `replicas`, мы доверяем контроллеру, управляющему масштабированием.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    managedFieldsManagers:
    - kube-controller-manager # HPA управляется этим менеджером
  syncPolicy:
    syncOptions:
    - RespectIgnoreDifferences=true
```

### Сценарий 2: Игнорирование мутаций Service Mesh (Istio/Linkerd)

Системы Service Mesh внедряют sidecar-контейнеры и аннотации, которые отсутствуют в Git.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jqPathExpressions:
    - .spec.template.spec.containers[] | select(.name == "istio-proxy")
    - .spec.template.metadata.annotations["sidecar.istio.io/status"]
```

### Сценарий 3: Глобальное игнорирование системных аннотаций

Настройка в `argocd-cm` для исключения "шума" от облачных провайдеров (например, GKE/AWS/Yandex Cloud).

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
data:
  resource.customizations.ignoreDifferences.all: |
    jqPathExpressions:
      - .metadata.annotations["cloud.google.com/gke-installed-by"]
      - .metadata.labels["managed-by-external-system"]
```

### Сценарий 4: Принудительное обновление неизменяемых полей

Если в Git изменилось поле, которое Kubernetes запрещает обновлять (например, `spec.selector` в `Service` или `spec.clusterIP`), синхронизация завершится ошибкой.

**Решение через CLI:**
```bash
argocd app sync <app-name> --force
```

**Решение в коде (использовать с осторожностью):**
```yaml
spec:
  syncPolicy:
    syncOptions:
    - Force=true # Приведет к удалению и пересозданию ресурса
```

## Технический справочник

### Типичные менеджеры полей (Managers)

| Система | Имя менеджера (`managedFieldsManagers`) |
| :--- | :--- |
| **Horizontal Pod Autoscaler** | `kube-controller-manager` |
| **cert-manager** | `cert-manager-certificates-issuer` |
| **Kyverno / Gatekeeper** | `kyverno`, `gatekeeper` |
| **Argo CD (SSA)** | `argocd-controller` |
| **Cloud Controllers** | `cloud-controller-manager` |

### Server-Side Diffing (Оптимизация)

Для ресурсов с огромным количеством динамических правок (например, `CustomResourceDefinitions`) рекомендуется включить Server-Side Diffing в `argocd-cm`:

```yaml
data:
  # Включение SSA для всех ресурсов по умолчанию
  server.side.apply.enabled: "true"
```
Это позволит Argo CD видеть "финальное" состояние ресурса после работы всех вебхуков, что радикально сокращает список необходимых `ignoreDifferences`.

## Дополнительная информация

### См. также
- [Синхронизация Argo CD: Обзор](../synchronization.md)
- [Автоматическая синхронизация и Self-Heal](./scenarios/auto_sync.md)
- [Диагностика и Troubleshooting](../argocd_troubleshooting_and_monitoring.md)
- [Интеграция Kyverno и Argo CD](../../../Kubernetes/Security/kyverno/argo-cd.md)

### Ссылки
- [Argo CD Documentation: Diff Customization](https://argo-cd.readthedocs.io/en/stable/user-guide/diff-customization/)
- [Kubernetes: Server-Side Apply Managed Fields](https://kubernetes.io/docs/reference/using-api/server-side-apply/#field-management)
