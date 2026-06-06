# CreateContainerConfigError: Профилактика

## Definitions

**Профилактика CreateContainerConfigError** — набор практик и инструментов, направленных на предотвращение ошибок конфигурации контейнеров до их попадания в кластер: валидация манифестов, управление зависимостями, CI/CD-проверки.

## Basic Concepts

### Стратегии предотвращения

| Стратегия | Описание | Эффект |
|-----------|----------|--------|
| **Валидация манифестов** | Проверка синтаксиса и схем до apply | Исключает опечатки, неверные поля |
| **Генерация ConfigMap/Secret** | Kustomize `configMapGenerator`, Helm | Ресурсы создаются вместе с Pod |
| **Namespace consistency** | Все ресурсы деплоя в одном namespace | Исключает namespace mismatch |
| **CI/CD gate** | Блокировка деплоя при ошибках валидации | Предотвращает попадание ошибок в кластер |
| **Monitoring** | Алерты на CreateContainerConfigError | Раннее обнаружение |

### Валидация манифестов

```bash
# Встроенная проверка Kubernetes
kubectl apply -f deployment.yaml --dry-run=client

# Валидация схем через kubeconform
kubeconform -strict deployment.yaml
```

kubeconform проверяет манифесты против JSON Schema API Kubernetes. Подробности: [kubeconform overview](../../../ToolsUtilities/kubeconform/kubeconform_overview.md).

> **Примечание:** `kubeval` — deprecated. Рекомендуется [kubeconform](../../../ToolsUtilities/kubeconform/kubeconform_overview.md) (выше производительность, поддержка CRD, активная разработка).

## Practical Scenarios

### Сценарий 1: Kustomize для управления зависимостями

`configMapGenerator` и `secretGenerator` гарантируют, что ConfigMap/Secret создаются до Pod.

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- deployment.yaml

configMapGenerator:
- name: app-config
  literals:
  - DATABASE_URL=postgres://db:5432/mydb
  - LOG_LEVEL=info

secretGenerator:
- name: db-credentials
  literals:
  - username=admin
  - password=SuperSecret
```

Применение:

```bash
kubectl apply -k .
```

Kustomize автоматически добавляет хеш в имя ConfigMap — при изменении содержимого создаётся новый ресурс, и Pod получает обновлённую конфигурацию через restart.

### Сценарий 2: Helm values validation

Валидация values.yaml предотвращает ошибки конфигурации до рендеринга шаблонов.

```yaml
# values.yaml
configMap:
  enabled: true
  data:
    LOG_LEVEL: info

secret:
  enabled: true
  data:
    password: changeme
```

Проверка рендеринга без применения в кластер:

```bash
helm template release ./chart --values values.yaml | kubeconform -strict
```

### Сценарий 3: CI/CD pipeline с валидацией

Пример GitLab CI step, блокирующий деплой при ошибках манифестов:

```yaml
validate-manifests:
  stage: validate
  image: ghcr.io/yannh/kubeconform:latest
  script:
    - kubeconform -strict -summary -output tap manifests/**/*.yaml
```

При обнаружении ошибок пайплайн останавливается — ресурсы не попадают в кластер.

### Сценарий 4: Monitoring и алерты

Настройка алертов на CreateContainerConfigError для раннего обнаружения:

```yaml
# Пример PrometheusRule
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: create-container-config-error
spec:
  groups:
  - name: kubernetes.rules
    rules:
    - alert: CreateContainerConfigError
      expr: kube_pod_container_status_waiting_reason{reason="CreateContainerConfigError"} > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.pod }} в CreateContainerConfigError"
        description: "Container не может запуститься: {{ $labels.reason }}"
```

### Сценарий 5: Best Practices checklist

| Практика | Реализация |
|----------|------------|
| **Единый namespace** | ConfigMap/Secret/PVC в том же namespace, что и Pod |
| **Валидация перед apply** | `kubectl apply --dry-run=client` + `kubeconform` |
| **Kustomize/Helm** | Автоматическое управление зависимостями |
| **RBAC** | Права `get/list` на ConfigMap/Secret для ServiceAccount пода |
| **Мониторинг** | Алерты на `kube_pod_container_status_waiting_reason{reason="CreateContainerConfigError"}` |

## Additional Information

### Связь с другими практиками

- Валидация Helm-чартов: [Helm security best practices](../../../ToolsUtilities/Helm/Advanced/security_best_practices.md)
- Валидация Kustomize: [Наложения и патчи](../../../ToolsUtilities/kustomize/kustomize_overlays_and_patches.md)

### Связанные ресурсы

- Определения: [definitions.md](./definitions.md)
- Диагностика: [diagnostics.md](./diagnostics.md)
- ConfigMap: [configmap_issues.md](./configmap_issues.md)
- Secrets: [secret_issues.md](./secret_issues.md)
- Обзор ошибки: [create_container_config_error.md](../create_container_config_error.md)
