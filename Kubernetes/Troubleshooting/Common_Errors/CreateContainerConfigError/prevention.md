# Профилактика CreateContainerConfigError

## Определения

**Профилактика CreateContainerConfigError** — стратегия упреждающего контроля конфигураций, направленная на минимизацию риска возникновения ошибок при формировании спецификации контейнера в рантайме. В отличие от реактивной диагностики, профилактика фокусируется на «сдвиге влево» (Shift-Left) — проверке зависимостей (ConfigMap, Secret, PVC, RBAC) на этапах разработки, CI/CD и Admission Control.

Основная цель — гарантировать, что к моменту, когда `kubelet` начнет создание контейнера, все внешние ссылки в `PodSpec` будут валидными и доступными.

## Основные концепции

### Эшелонированная защита (Prevention Layers)

Предотвращение ошибок конфигурации строится на четырех уровнях:

1.  **Клиентский уровень (Pre-commit/IDE):** Использование линтеров и расширений (например, vscode-kubernetes), которые подсвечивают отсутствие ресурсов.
2.  **Уровень CI (Pipeline Validation):** Статический анализ манифестов (`kubeconform`, `datree`, `trivy`) и проверка существования зависимостей в целевом окружении.
3.  **Уровень Admission Control (Cluster Guardrails):** Использование Policy Engines (Kyverno, OPA/Gatekeeper) для блокировки подов, ссылающихся на несуществующие или недопустимые ресурсы.
4.  **Уровень приложения (Graceful Degradation):** Использование флага `optional: true` для второстепенных настроек, позволяющее приложению запуститься даже при отсутствии конфига.

### Стратегии предотвращения

| Стратегия | Механизм | Результат |
|-----------|----------|-----------|
| **Статическая валидация** | Проверка схем API и Best Practices до деплоя | Исключение синтаксических ошибок и использования deprecated полей |
| **Генерация с хешированием** | `configMapGenerator` в Kustomize / Helm | Гарантированная консистентность: под всегда ссылается на конкретную версию ресурса |
| **Семантическая проверка** | Кастомные скрипты в CI или Policy Engines | Проверка логических связей (например, наличие секрета для `imagePullSecrets`) |
| **Admission Enforcement** | Блокировка запроса на создание Pod через Webhooks | Предотвращение попадания некорректных спецификаций в `etcd` |

### Инструменты валидации и анализа

Помимо стандартных средств, рекомендуется использовать специализированные утилиты:

```bash
# 1. Kubeconform (валидация схем)
kubeconform -strict -summary -output json deployment.yaml

# 2. Datree (проверка на соответствие Best Practices и кастомным политикам)
datree test deployment.yaml

# 3. Trivy (сканирование конфигураций на безопасность и ошибки)
trivy config .

# 4. Kubectl dry-run (проверка на стороне сервера - самый надежный метод)
kubectl apply -f deployment.yaml --dry-run=server
```

> **Важно:** `kubectl apply --dry-run=server` проверяет не только синтаксис, но и права доступа (RBAC), а также наличие ссылок на существующие объекты, если это поддерживается Admission контроллерами.

## Практические сценарии

### Сценарий 1: Управление зависимостями через Kustomize (Immutable-подход)

Использование генераторов ресурсов решает проблему «зависших» подов при обновлении конфигурации.

```yaml
# kustomization.yaml
configMapGenerator:
- name: app-config
  files:
  - config.properties
generatorOptions:
  disableNameSuffixHash: false # По умолчанию false, добавляет хеш к имени
```

**Почему это предотвращает ошибку:**
1. К имени ConfigMap добавляется хеш (например, `app-config-847h79777f`).
2. При изменении файла создается НОВЫЙ объект с новым хешем.
3. Kustomize автоматически обновляет ссылку в Deployment.
4. Kubernetes запускает Rolling Update. Старый под продолжает работать со старым конфигом, пока новый не перейдет в `Ready`.

### Сценарий 2: Использование опциональных зависимостей (Optional Flags)

Для параметров, которые не являются критическими для старта приложения, всегда используйте флаг `optional`.

```yaml
env:
- name: DEBUG_TOOLS_CONFIG
  valueFrom:
    configMapKeyRef:
      name: non-critical-config
      key: debug-level
      optional: true # Под запустится, даже если ConfigMap отсутствует
```

### Сценарий 3: Проверка RBAC и ServiceAccount в CI

Частая причина `CreateContainerConfigError` — отсутствие прав у `ServiceAccount` на чтение секретов. Это можно проверить в CI пайплайне перед деплоем.

```bash
# Имитация прав ServiceAccount для проверки доступа
kubectl auth can-i get secret --as=system:serviceaccount:my-namespace:my-app-sa
# → yes (или no)

# Проверка в скрипте CI
if ! kubectl auth can-i get secret/my-secret --as=system:serviceaccount:prod:app-sa; then
  echo "CRITICAL: ServiceAccount lacks permissions to read secrets!"
  exit 1
fi
```

### Сценарий 4: Блокировка через Kyverno (Admission Control)

Политика Kyverno может предотвратить создание пода, если он ссылается на секрет, который помечен как «чувствительный», но не имеет необходимых меток.

```yaml
# Пример концепции: запрет использования секретов без определенных лейблов
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-secret-labels
spec:
  validationFailureAction: Enforce
  rules:
  - name: validate-secret-reference
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "Используемый секрет должен иметь метку app.kubernetes.io/managed-by"
      # ... логика проверки связей ...
```

### Сценарий 5: Мониторинг и проактивный алертинг

Настройка Prometheus для раннего обнаружения аномалий в статусах контейнеров.

```yaml
groups:
- name: kubernetes.config.alerts
  rules:
  - alert: KubernetesContainerConfigErrorRate
    # Оповещение при появлении ошибки в пространстве имен
    expr: sum by (namespace) (kube_pod_container_status_waiting_reason{reason="CreateContainerConfigError"}) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Обнаружена ошибка CreateContainerConfigError в namespace {{ $labels.namespace }}"
      description: "Один или несколько подов не могут сформировать конфигурацию контейнера. Проверьте соответствие ConfigMap/Secret."
```

## Список лучших практик (Checklist)

| Категория | Рекомендация |
|-----------|--------------|
| **Версионность** | Используйте `configMapGenerator` или Helm-чарты с управлением релизами. |
| **Валидация** | Интегрируйте `kubeconform` и `dry-run=server` в CI/CD пайплайны. |
| **Доступ (RBAC)** | Проверяйте права `ServiceAccount` перед выкаткой новых зависимостей. |
| **Отказоустойчивость** | Используйте `optional: true` для всех некритичных переменных окружения и томов. |
| **Чистота** | Удаляйте старые ConfigMap/Secret только после того, как убедитесь, что на них нет ссылок (используйте `kubectl get pods -A -o json | jq ...`). |

## Дополнительная информация

### Связь с другими практическими руководствами

- Управление секретами: [Безопасность Secret в Kubernetes](../../../Security/application_secrets_management.md)
- Оптимизация Helm: [Helm security best practices](../../../ToolsUtilities/Helm/Advanced/security_best_practices.md)
- Инструментарий: [Обзор kubeconform](../../../ToolsUtilities/kubeconform_overview.md)

### Связанные ресурсы

- [Определения CreateContainerConfigError](./definitions.md)
- [Диагностика ошибки](./diagnostics.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Проблемы с Secret](./secret_issues.md)
- [Проблемы с RBAC и ServiceAccount](./rbac_issues.md)

