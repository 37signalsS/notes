# Pod Image Pull Errors: Определения

## Определения

**`ErrImagePull`** — начальная ошибка, означающая, что `kubelet` не может скачать образ контейнера из репозитория.

**`ImagePullBackOff`** — состояние, в которое переходит под после нескольких неудачных попыток скачивания образа. `kubelet` увеличивает задержку между попытками (exponential backoff).

> - Docker Registry: [`../../../Docker/Docker_registries/docker_registries.md`](../../../Docker/Docker_registries/docker_registries.md)
> - GitLab CI/CD: [`../../../CI-CD/GitLab_CI/Tutorials/ci_cd_pipeline_overview.md`](../../../CI-CD/GitLab_CI/Tutorials/ci_cd_pipeline_overview.md)
> - ArgoCD: [`../../../GitOps/ArgoCD/argocd_troubleshooting_and_monitoring.md`](../../../GitOps/ArgoCD/argocd_troubleshooting_and_monitoring.md)
> - Secrets: [`../../../Base/secrets/external_managers.md`](../../../Base/secrets/external_managers.md)

**Backoff задержки:** 10s → 20s → 40s → 80s → 160s → 300s (максимум)

## Основные концепции

### Workflow загрузки образа

```
Pod создан
    ↓
kubelet на узле получает задачу
    ↓
Проверка локального кэша
    ↓
Образ не найден → Запрос в registry
    ↓
Аутентификация (если приватный)
    ↓
Скачивание слоев
    ↓
Распаковка и запуск
```

### ImagePullPolicy

| Политика | Поведение | Когда использовать |
|----------|-----------|-------------------|
| **`IfNotPresent`** | Использовать кэш, если есть; иначе скачать | Production (по умолчанию для `:tag`) |
| **`Always`** | Всегда скачивать свежий образ | Production (по умолчанию для `:latest`) |
| **`Never`** | Использовать только локальный образ | Offline-кластеры, тестирование |

> **Best Practice:** Избегайте тега `:latest` в production. Используйте конкретные версии или SHA256 digest.

### Типы репозиториев

| Тип | Примеры | Аутентификация |
|-----|---------|----------------|
| **Публичные** | Docker Hub, GHCR | Не требуется (для публичных образов) |
| **Приватные** | Docker Hub, GCR, ECR, Harbor | `imagePullSecrets` |
| **Локальные** | Internal registry, air-gapped | Self-signed cert, offline tokens |
