# Pod Image Pull Errors: Best Practices

## Best Practices

| Практика | Описание |
|----------|----------|
| **Используйте конкретные теги** | Избегайте `:latest`, используйте `:v1.2.3` или SHA256 |
| **Настройте imagePullSecrets глобально** | Привяжите secret к `default` ServiceAccount |
| **Используйте private registry** | Harbor, Nexus, ECR для контроля доступа |
| **Кэшируйте образы на узлах** | Уменьшает время запуска и нагрузку на registry |
| **Мониторьте rate limits** | Алерты на ошибки аутентификации |

## Мониторинг и алерты

```yaml
# Prometheus alert для ImagePullBackOff
- alert: ImagePullBackOff
  expr: kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Pod {{ $labels.pod }} ImagePullBackOff"
    description: "Container {{ $labels.container }} не может скачать образ"
```

## Таблица решений

| Симптом | Первая команда | Вероятное решение |
|---------|----------------|-------------------|
| `manifest not found` | `kubectl describe pod` | Исправить имя/тег образа |
| `unauthorized` | `kubectl get pod -o jsonpath='{.spec.imagePullSecrets}'` | Создать/исправить imagePullSecret |
| `connection timed out` | `ssh node curl -I registry` | Проверить сеть, firewall, proxy |
| `toomanyrequests` | `kubectl describe pod` | Аутентификация или mirror registry |
| `x509: unknown authority` | `kubectl describe pod` | Добавить CA cert на узлы |

## Ссылки

- [Kubernetes Images](https://kubernetes.io/docs/concepts/containers/images/)
- [Docker Hub Rate Limiting](https://docs.docker.com/docker-hub/download-rate-limit/)
- [Pull Private Container Images](https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/)
