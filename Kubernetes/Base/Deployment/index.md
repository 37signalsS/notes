# Kubernetes Deployment

Декларативное управление жизненным циклом подов в Kubernetes.

## Структура раздела

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

## Навигация по связанным темам

Базовые объекты: [`Pod`](../Pod/pod_overview.md), [`ReplicaSet`](../replicaset.md), [`ConfigMap`](../configmap.md), [`Secret`](../secrets/secrets_basics.md).

Stateful-приложения: [`StatefulSet`](../statefulset.md).

Отказоустойчивость: [`Высокая доступность`](../high_availability.md).
