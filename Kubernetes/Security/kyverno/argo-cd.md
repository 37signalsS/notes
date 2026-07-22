# Интеграция Kyverno с Argo CD

## Определения

**Интеграция Kyverno с Argo CD** — комплекс мер по настройке совместной работы GitOps-платформы и движка политик, исключающий конфликты при мутации ресурсов и обеспечивающий прозрачность нарушений безопасности (Policy Violations) непосредственно в интерфейсе управления.

---

## Основные концепции

### Проблематика совместного использования

При стандартной настройке Argo CD и Kyverno возникают три критические проблемы:

1.  **Бесконечный цикл синхронизации (Sync Drift)**: Kyverno мутирует ресурс при создании (например, добавляет Sidecar или лейблы). Argo CD видит разницу между Git и кластером и пытается "откатить" изменения.
2.  **Конфликты Resource Tracking**: Если оба инструмента используют одинаковые механизмы отслеживания (метки `app.kubernetes.io/instance`), это приводит к потере контроля над ресурсами.
3.  **Невидимость нарушений**: Без специальной настройки Argo CD считает приложение "Healthy", даже если Kyverno заблокировал создание части его ресурсов или зафиксировал критические ошибки безопасности в отчетах.

### Современный стек (2025–2026)

Стандартом является использование **Server-Side Apply (SSA)** и **Server-Side Diff**. Это переносит логику объединения (merge) и сравнения манифестов на сторону Kubernetes API, где мутирующие вебхуки Kyverno учитываются автоматически.

---

## Практические сценарии

### 1. Глобальная настройка Server-Side Diff

Чтобы Argo CD корректно учитывал изменения, внесенные мутирующими вебхуками Kyverno, необходимо включить сравнение на стороне сервера.

**В аннотациях Application**:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  annotations:
    # Включает сравнение на стороне сервера и учет мутирующих вебхуков
    argocd.argoproj.io/compare-options: ServerSideDiff=true,IncludeMutationWebhook=true
spec:
  syncPolicy:
    syncOptions:
      - ServerSideApply=true # Использование SSA при синхронизации
```

### 2. Игнорирование системных различий (ignoreDifferences)

Kyverno автоматически добавляет некоторые технические поля в свои ресурсы (например, `skipBackgroundRequests`), которые вызывают дрифт в Argo CD.

**Настройка в Application или ConfigMap (argocd-cm)**:
```yaml
spec:
  ignoreDifferences:
    - group: kyverno.io
      kind: ClusterPolicy
      jqPathExpressions:
        - .spec.rules[] | select(.name|test("autogen-.")) # Игнорировать автогенерируемые правила
        - .spec.rules[].skipBackgroundRequests            # Игнорировать техническое поле
    - group: kyverno.io
      kind: Policy
      jsonPointers:
        - /status # Игнорировать блок статуса
```

### 3. Визуализация PolicyReport в UI Argo CD

Чтобы видеть нарушения политик безопасности непосредственно в дашборде Argo CD, необходимо настроить **Health Checks** для ресурсов отчетов Kyverno.

**В конфигурации Argo CD (argocd-cm)**:
```yaml
data:
  resource.customizations.health.wgpolicyk8s.io_PolicyReport: |
    hs = {}
    if obj.summary.fail > 0 then
      hs.status = "Degraded"
      hs.message = "Нарушения политик: " .. obj.summary.fail
    else
      hs.status = "Healthy"
      hs.message = "Проверки безопасности пройдены"
    end
    return hs
```
*После этой настройки приложение перейдет в состояние `Degraded`, если Kyverno обнаружит ошибки безопасности в ресурсах этого приложения.*

### 4. Порядок установки (Sync Waves)

Для корректной работы системы при первичной установке или обновлении необходимо соблюдать очередность:

| Волна (Wave) | Компоненты | Зачем |
| :--- | :--- | :--- |
| **0** | Пространство имен (Namespace), секреты, конфигурация. | База. |
| **1** | Контроллер Kyverno (Helm chart). | Движок должен быть активен до появления политик. |
| **2** | Политики (ClusterPolicy / Policy). | Правила должны быть загружены до появления нагрузки. |
| **3+** | Рабочая нагрузка (Workloads: Deployments, Services). | Поды будут мутированы и проверены сразу при создании. |

---

## Дополнительная информация

### Сводная таблица параметров Argo CD для Kyverno

| Параметр | Уровень | Рекомендуемое значение | Назначение |
| :--- | :--- | :--- | :--- |
| `ServerSideApply=true` | Sync Option | Да | Решение проблем с большими манифестами и конфликтами полей. |
| `ServerSideDiff=true` | Annotation | Да | Учет динамических изменений от вебхуков. |
| `resourceTrackingMethod` | ConfigMap | `annotation` | Предотвращение конфликта меток (актуально для старых версий). |
| `ApplyOutOfSyncOnly=true` | Sync Option | Да | Оптимизация: обновлять только изменившиеся ресурсы. |

### Особенности работы с Helm

Если Kyverno устанавливается как Helm-чарт через Argo CD, важно обратить внимание на параметр `config.preserve`. 
- **Рекомендация**: Установите `config.preserve=false`. В противном случае Helm создаст `post-delete` хуки для сохранения конфигурации, которые могут блокировать автоматическое удаление ресурсов контроллером Argo CD.

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| Бесконечный `OutOfSync` | `argocd app diff <name> --server-side` | Проверьте `ignoreDifferences` для мутированных полей. |
| Ресурс не мутируется | Проверьте логи `kyverno-admission-controller` | Убедитесь, что вебхуки Kyverno успевают обрабатывать запросы. |
| Приложение `Healthy`, но поды не создаются | `kubectl get events -n <ns>` | Kyverno может блокировать создание подов в режиме `Enforce`, но Argo CD не видит этого без Health Checks. |

### См. также
- [Установка Kyverno с помощью Argo CD](./install.md)
- [Типы правил и механизмы мутации](./rules.md)
- [Официальный Policy Reporter UI (визуализация)](./reporter.md)
