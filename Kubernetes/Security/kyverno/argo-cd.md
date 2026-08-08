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

### Современный стек (2026)

Стандартом 2026 года для Argo CD v3.x является **полный переход на Server-Side Apply (SSA)** и **Server-Side Diff**. Это переносит логику объединения (merge) и сравнения манифестов на сторону Kubernetes API. При такой архитектуре мутации, внесенные Kyverno, сохраняются в `managedFields` ресурса, что позволяет Argo CD игнорировать их автоматически, если настроены соответствующие менеджеры полей.

---

## Практические сценарии

### 1. Глобальная настройка Server-Side Diff

Чтобы Argo CD корректно учитывал изменения, внесенные мутирующими вебхуками Kyverno, необходимо включить сравнение на стороне сервера. Это критично для ресурсов, где Kyverno добавляет sidecar-контейнеры или инжектирует переменные окружения.

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
      - ServerSideApply=true # Использование SSA при синхронизации (стандарт v3.x)
```

### 2. Игнорирование системных различий (ignoreDifferences)

В Argo CD v3.x существует два способа исключения дрифта: классический (через пути) и современный (через менеджеров полей).

#### Способ А: Managed Fields (Рекомендуемый в 2026)
Этот метод позволяет Argo CD полностью доверять Kyverno в управлении определенными полями, не описывая каждое поле вручную.

**В Application или argocd-cm**:
```yaml
spec:
  ignoreDifferences:
    - group: "*"
      kind: "*"
      managedFieldsManagers:
        - kyverno # Игнорировать все изменения, внесенные менеджером kyverno
```

#### Способ Б: JQ и JSON Pointers
Используется для специфических полей Kyverno, которые не всегда попадают под управление менеджера (например, автогенерируемые правила).

**Настройка в Application**:
```yaml
spec:
  ignoreDifferences:
    - group: kyverno.io
      kind: ClusterPolicy
      jqPathExpressions:
        - .spec.rules[] | select(.name|test("autogen-.")) # Игнорировать автогенерируемые правила
        - .spec.rules[].skipBackgroundRequests            # Техническое поле Kyverno
    - group: kyverno.io
      kind: Policy
      jsonPointers:
        - /status # Игнорировать блок статуса
```

### 3. Конфликты при генерации ресурсов (Generate Rules)

Kyverno может генерировать новые ресурсы (например, `NetworkPolicy` или `ConfigMap`) при создании Namespace. Если этот Namespace управляется Argo CD, он увидит «лишние» ресурсы и попытается их удалить (Prune).

**Решение**:
Для ресурсов, генерируемых Kyverno, необходимо добавить аннотацию, запрещающую Argo CD их удалять, или исключить их из процесса прунинга.

**В шаблоне политики Kyverno (generate)**:
```yaml
generate:
  apiVersion: v1
  kind: ConfigMap
  name: global-config
  data:
    metadata:
      annotations:
        # Указывает Argo CD игнорировать этот ресурс при очистке
        argocd.argoproj.io/sync-options: Prune=false
```

### 4. Визуализация отчетов (PolicyReport) в UI Argo CD

Чтобы видеть нарушения политик безопасности непосредственно в дашборде Argo CD, необходимо настроить **Health Checks** для ресурсов отчетов Kyverno. Это позволяет приложению переходить в статус `Degraded`, если обнаружены критические нарушения.

**В конфигурации Argo CD (argocd-cm)**:
```yaml
data:
  # Настройка для обычных отчетов (в Namespace)
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

  # Настройка для кластерных отчетов
  resource.customizations.health.wgpolicyk8s.io_ClusterPolicyReport: |
    hs = {}
    if obj.summary.fail > 0 then
      hs.status = "Degraded"
      hs.message = "Кластерные нарушения: " .. obj.summary.fail
    else
      hs.status = "Healthy"
    end
    return hs
```

### 5. Порядок установки (Sync Waves)

Для корректной работы системы при первичной установке необходимо соблюдать очередность:

| Волна (Wave) | Компоненты | Зачем |
| :--- | :--- | :--- |
| **0** | Namespace, Secrets, ConfigMaps. | Базовая инфраструктура. |
| **1** | Контроллер Kyverno (Helm). | Контроллер должен быть готов до появления политик. |
| **2** | ClusterPolicies / Policies. | Политики должны быть загружены до появления нагрузки. |
| **3+** | Application Workloads. | Поды будут проверены или мутированы сразу при создании. |

---

## Дополнительная информация

### Сводная таблица параметров Argo CD для Kyverno (v3.x)

| Параметр | Уровень | Значение | Назначение |
| :--- | :--- | :--- | :--- |
| `ServerSideApply=true` | Sync Option | Да | Рекомендуемый метод для всех ресурсов в 2026 году. |
| `ServerSideDiff=true` | Annotation | Да | Точное сравнение с учетом мутаций на стороне API. |
| `managedFieldsManagers` | ignoreDiff | `['kyverno']` | Автоматическое игнорирование всех мутаций от Kyverno. |
| `IncludeMutationWebhook`| Annotation | `true` | Обязательно для корректного Diff при использовании мутаций. |

### Особенности Kyverno 1.13+: AdmissionReport

В новых версиях Kyverno отчеты о проверках в момент допуска (Admission) могут сохраняться в ресурсах `AdmissionReport`. В отличие от `PolicyReport`, они эфемерны и могут не требовать постоянного мониторинга в Argo CD, однако для критических приложений рекомендуется также настраивать для них Health Checks по аналогии с `PolicyReport`.

### Особенности работы с Helm

Если Kyverno устанавливается как Helm-чарт через Argo CD, важно обратить внимание на параметр `config.preserve`. 
- **Рекомендация**: Установите `config.preserve=false`. В противном случае Helm создаст `post-delete` хуки для сохранения конфигурации, которые могут блокировать автоматическое удаление ресурсов контроллером Argo CD.

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| Бесконечный `OutOfSync` | `argocd app diff <name> --server-side` | Убедитесь, что `managedFieldsManagers` содержит `kyverno`. |
| Ресурс не мутируется | Проверьте аннотации в объекте | Если используется SSA, проверьте `managedFields` — там должен быть указан менеджер `kyverno`. |
| Приложение `Healthy`, но поды не создаются | `kubectl get events -n <ns>` | Kyverno заблокировал создание (Admission Control). Проверьте `PolicyReport` в UI. |
| Ошибка `Too large resource` | Логи `argocd-application-controller` | Включите `ServerSideApply=true` для этого приложения. |

### См. также
- [Установка Kyverno с помощью Argo CD](./install.md)
- [Типы правил и механизмы мутации](./rules.md)
- [Официальный Policy Reporter UI (визуализация)](./reporter.md)
