# CreateContainerConfigError: Профилактика

## Определения

**Профилактика CreateContainerConfigError** — комплекс мер, инструментов и практик, направленных на исключение ошибок конфигурации контейнеров до момента их деплоя в кластер. Включает в себя статическую валидацию манифестов, автоматизацию управления зависимостями (ConfigMap/Secret) и использование политик безопасности.

Подробные определения ошибки: [definitions.md](./definitions.md).

## Основные концепции

### Стратегии предотвращения

| Стратегия | Описание | Эффект |
|-----------|----------|--------|
| **Статическая валидация** | Проверка синтаксиса YAML и схем Kubernetes API до `apply` | Исключает опечатки и использование недопустимых полей |
| **Генераторы ресурсов** | Использование `configMapGenerator` в Kustomize или шаблонизации в Helm | Гарантирует наличие ресурсов и автоматический рестарт при изменениях |
| **Admission Control** | Использование Policy Engines (Kyverno, OPA) | Блокирует создание подов, ссылающихся на несуществующие ресурсы |
| **GitOps-валидация** | Предварительная проверка в CI и механизмы dry-run в Argo CD/Flux | Предотвращает попадание некорректных манифестов в Git-репозиторий |
| **Проактивный мониторинг** | Алертинг на ранних стадиях возникновения ошибки | Позволяет исправить конфигурацию до того, как она повлияет на доступность сервиса |

### Инструменты валидации

```bash
# Проверка манифеста встроенными средствами kubectl
kubectl apply -f deployment.yaml --dry-run=client
# → deployment.apps/my-app configured (dry run)

# Валидация схем через kubeconform (замена устаревшему kubeval)
kubeconform -strict deployment.yaml
# → deployment.yaml - Deployment my-app is valid
```

`kubeconform` проверяет манифесты на соответствие JSON-схемам Kubernetes API. Подробности: [Обзор kubeconform](../../../ToolsUtilities/kubeconform_overview.md).

> **Примечание:** `kubeval` больше не поддерживается (deprecated). Рекомендуется использовать `kubeconform` из-за поддержки CRD и высокой производительности.

## Практические сценарии

### Сценарий 1: Управление зависимостями через Kustomize

Использование `configMapGenerator` и `secretGenerator` гарантирует, что зависимые ресурсы будут созданы и обновлены вместе с подом.

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- deployment.yaml

configMapGenerator:
- name: app-config
  literals:
  - LOG_LEVEL=debug
  - APP_PORT=8080
```

При изменении контента в `configMapGenerator`, Kustomize меняет хеш в имени ресурса (например, `app-config-f78687h`), что заставляет Kubernetes выполнить Rolling Update пода. Это предотвращает ситуацию, когда старый под ссылается на удаленный или некорректно обновленный ConfigMap.

### Сценарий 2: Валидация Helm-значений

Использование `values.schema.json` в Helm-чарте позволяет проверять входные параметры до рендеринга шаблонов.

```bash
# Проверка рендеринга и валидация схемы
helm lint ./my-chart
# → 0 chart(s) linted, 0 chart(s) failed

helm template release ./my-chart --values values.yaml | kubeconform -strict
# → Summary: 1 file passed, 0 errors, 0 warnings
```

### Сценарий 3: Блокировка деплоя через Kyverno

Kyverno может проверять наличие ConfigMap или Secret в кластере перед тем, как разрешить создание пода. Это позволяет поймать ошибку на этапе Admission Control.

Подробнее о концепциях Kyverno: [Концепции Kyverno](../../../Security/kyverno/concepts.md).

### Сценарий 4: GitOps и Argo CD Sync Options

Argo CD предоставляет механизмы для предотвращения применения некорректных манифестов.

*   **`Validate=true`**: Выполняет проверку манифеста перед применением.
*   **`ServerSideApply=true`**: Позволяет Kubernetes проверить манифест на стороне API-сервера, что эффективнее для больших ресурсов и CRD.

```yaml
# Пример настройки в Application
spec:
  syncPolicy:
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
```

### Сценарий 5: Мониторинг и алертинг

Настройка Prometheus для обнаружения подов, застрявших в статусе `CreateContainerConfigError`.

```yaml
# PrometheusRule
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: container-config-alerts
spec:
  groups:
  - name: kubernetes.errors
    rules:
    - alert: CreateContainerConfigErrorPersistent
      expr: kube_pod_container_status_waiting_reason{reason="CreateContainerConfigError"} > 0
      for: 10m
      labels:
        severity: critical
      annotations:
        summary: "Ошибка конфигурации контейнера в поде {{ $labels.pod }}"
        description: "Под {{ $labels.namespace }}/{{ $labels.pod }} находится в состоянии CreateContainerConfigError более 10 минут. Проверьте наличие ConfigMap/Secret."
```

## Список лучших практик (Checklist)

| Практика | Реализация |
|----------|------------|
| **Локальность ресурсов** | Размещайте ConfigMap/Secret в том же Namespace, что и Pod |
| **Использование генераторов** | Применяйте `configMapGenerator` для управления версионностью конфигов |
| **CI-валидация** | Интегрируйте `kubeconform` в каждый пайплайн |
| **Проверка прав (RBAC)** | Убедитесь, что ServiceAccount пода имеет доступ к Secret/ConfigMap |
| **Обязательный dry-run** | Всегда проверяйте манифесты командой `kubectl apply --dry-run=server` перед деплоем |

## Дополнительная информация

### Связь с другими практическими руководствами

- Безопасность Helm: [Helm security best practices](../../../ToolsUtilities/Helm/Advanced/security_best_practices.md)
- Kustomize-патчи: [Наложения и патчи](../../../ToolsUtilities/kustomize/kustomize_overlays_and_patches.md)
- Политики Kyverno: [Концепции Kyverno](../../../Security/kyverno/concepts.md)

### Связанные ресурсы

- [Определения CreateContainerConfigError](./definitions.md)
- [Диагностика ошибки](./diagnostics.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Проблемы с Secret](./secret_issues.md)
