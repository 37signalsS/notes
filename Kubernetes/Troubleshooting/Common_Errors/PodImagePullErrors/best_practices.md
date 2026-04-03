# Pod Image Pull Errors: Best Practices

## Определения

**Best Practices (Лучшие практики)** — проверенные рекомендации по предотвращению и минимизации image pull errors в Kubernetes, охватывающие управление образами, аутентификацию, сетевую конфигурацию и мониторинг.

**Immutable tag (SHA256 digest)** — криптографический хеш образа, гарантирующий неизменность и однозначную идентификацию версии (`my-app@sha256:abc123...`).

---

## Основные концепции

### Принципы предотвращения Image Pull Errors

| Категория | Практика | Обоснование |
| :--- | :--- | :--- |
| **Управление тегами** | Использовать конкретные теги (`:v1.2.3`) или SHA256 digest | Предотвращает ошибки `manifest not found`, обеспечивает воспроизводимость |
| **Аутентификация** | Привязка `imagePullSecrets` к `default` ServiceAccount | Автоматическая аутентификация для всех подов в namespace |
| **Реестры** | Использование private registry (Harbor, Nexus, ECR) | Контроль доступа, кэширование, отсутствие rate limits |
| **Кэширование** | Кэширование образов на узлах | Уменьшает время запуска и нагрузку на registry |
| **Мониторинг** | Алерты на rate limits и ошибки аутентификации | Раннее обнаружение проблем до массовых сбоев |

### Выбор imagePullPolicy

| Политика | Сценарий применения |
| :--- | :--- |
| `IfNotPresent` | **Рекомендуется** для production с конкретными тегами — использует локальный кэш |
| `Always` | Для `:latest` и nightly-сборок — гарантирует свежий образ |
| `Never` | Для offline-кластеров и отладки — только локальные образы |

> **Правило:** В production используйте конкретные теги с `IfNotPresent` или SHA256 digest с `Always`.

---

## Практические сценарии

### Сценарий 1: Глобальная настройка imagePullSecrets

Вместо указания `imagePullSecrets` в каждом манифесте, привяжите secret к ServiceAccount:

```bash
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "regcred"}]}' \
  -n <namespace>
```

Все поды, использующие `default` ServiceAccount, автоматически получат доступ к приватному registry. Подробнее о создании secret: [Common Errors](./common_errors.md#2-проблемы-с-доступом-к-приватному-репозиторию).

### Сценарий 2: Мониторинг ImagePullBackOff через Prometheus

```yaml
- alert: ImagePullBackOff
  expr: kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Pod {{ $labels.pod }} ImagePullBackOff"
    description: "Container {{ $labels.container }} не может скачать образ"
```

### Сценарий 3: Диагностика по таблице решений

| Симптом | Первая команда | Вероятное решение |
| :--- | :--- | :--- |
| `manifest not found` | `kubectl describe pod` | Исправить имя/тег образа |
| `unauthorized` | `kubectl get pod -o jsonpath='{.spec.imagePullSecrets}'` | Создать/исправить imagePullSecret |
| `connection timed out` | `ssh node curl -I registry` | Проверить сеть, firewall, proxy |
| `toomanyrequests` | `kubectl describe pod` | Аутентификация или mirror registry |
| `x509: unknown authority` | `kubectl describe pod` | Добавить CA cert на узлы |

Подробная диагностика: [Diagnostics](./diagnostics.md).

---

## Дополнительная информация

### Связанные темы

- Определения image pull errors: [Definitions](./definitions.md)
- Распространённые ошибки и решения: [Common Errors](./common_errors.md)
- Пошаговая диагностика: [Diagnostics](./diagnostics.md)
- Air-gapped кластеры: [Air-gapped](./airgapped.md)
- Проблемы сети: [Network Issues](./network_issues.md)
- Документация Kubernetes — образы: [Kubernetes Images](https://kubernetes.io/docs/concepts/containers/images/)
- Документация Kubernetes — приватные registry: [Pull Private Images](https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/)
