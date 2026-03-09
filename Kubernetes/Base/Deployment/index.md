# Kubernetes Deployment

Декларативное управление жизненным циклом подов в Kubernetes.

## Структура

- **[deployment_concepts.md](./deployment_concepts.md)** — Определения, анатомия манифеста, стратегии обновления
- **[deployment_manifest.md](./deployment_manifest.md)** — Пример манифеста, лучшие практики
- **[lifecycle_management.md](./lifecycle_management.md)** — Создание, обновление, откат, управление ревизиями

## Быстрый старт

```bash
# Создать Deployment
kubectl apply -f deployment.yaml

# Обновить образ
kubectl set image deployment/my-app my-container=my-image:v2

# Отследить статус
kubectl rollout status deployment/my-app

# Откатить
kubectl rollout undo deployment/my-app
```

## Связанные темы

- [ConfigMap](../configmap.md)
- [Secret](../secrets/secrets_basics.md)
- [StatefulSet](../statefulset.md)
- [ReplicaSet](../replicaset.md)
- [Pod](../Pod/pod_overview.md)
- [Высокая доступность](../high_availability.md)
