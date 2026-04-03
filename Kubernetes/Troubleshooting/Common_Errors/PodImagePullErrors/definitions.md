# Pod Image Pull Errors: Определения

## Определения

**`ErrImagePull`** — начальная ошибка, означающая, что `kubelet` не может скачать образ контейнера из реестра. Возникает при первой попытке pull.

**`ImagePullBackOff`** — состояние, в которое переходит под после нескольких неудачных попыток скачивания образа. `kubelet` увеличивает задержку между попытками (exponential backoff).

**Backoff задержки:** 10s → 20s → 40s → 80s → 160s → 300s (максимум)

**`kubelet`** — агент Kubernetes на каждом узле, отвечающий за запуск и управление контейнерами, включая загрузку образов.

**Container Registry** — сервис хранения и доставки контейнерных образов (Docker Hub, Harbor, ECR, GCR).

**Image Pull** — процесс скачивания слоёв контейнерного образа из registry в локальное хранилище узла.

---

## Основные концепции

### Workflow загрузки образа

```
Pod создан
    ↓
kubelet на узле получает задачу
    ↓
Проверка локального кэша docker/containerd
    ↓
Образ не найден → Запрос в registry
    ↓
Аутентификация (если приватный registry)
    ↓
Скачивание слоёв (layers)
    ↓
Распаковка и запуск контейнера
```

### Переход ErrImagePull → ImagePullBackOff

```
ErrImagePull (первая ошибка)
    ↓
Повторная попытка через 10s
    ↓
Повторная ошибка → backoff увеличивается
    ↓
ImagePullBackOff (после нескольких неудач)
    ↓
Задержка растёт экспоненциально до 5 минут
```

### ImagePullPolicy

| Политика | Поведение | Когда использовать |
| :--- | :--- | :--- |
| **`IfNotPresent`** | Использовать кэш, если есть; иначе скачать | Production (по умолчанию для `:tag`) |
| **`Always`** | Всегда скачивать свежий образ | Production (по умолчанию для `:latest`) |
| **`Never`** | Использовать только локальный образ | Offline-кластеры, тестирование |

**Правило по умолчанию:**

| Тег образа | Default imagePullPolicy |
| :--- | :--- |
| `:latest` | `Always` |
| Конкретный тег (`:v1.2.3`) | `IfNotPresent` |

> **Рекомендация:** Избегайте тега `:latest` в production. Используйте конкретные версии или SHA256 digest.

### Типы репозиториев

| Тип | Примеры | Аутентификация |
| :--- | :--- | :--- |
| **Публичные** | Docker Hub, GHCR | Не требуется (для публичных образов) |
| **Приватные** | Docker Hub, GCR, ECR, Harbor | `imagePullSecrets` |
| **Локальные** | Internal registry, air-gapped | Self-signed cert, offline tokens |

### Rate limiting Docker Hub

Docker Hub ограничивает количество pull-запросов для анонимных пользователей:
- **Anonymous:** 100 pull / 6 часов
- **Authenticated (free):** 200 pull / 6 часов
- **Pro/Team:** без ограничений

При превышении лимита возникает ошибка `toomanyrequests`. Решение — аутентификация через `imagePullSecrets` или использование mirror registry.

---

## Практические сценарии

### Сценарий 1: Диагностика по статусу пода

```bash
# Проверка статуса pod
kubectl get pod <pod-name>

# Возможные статусы:
# ImagePullBackOff — pod не может скачать образ
# ErrImagePull     — начальная ошибка pull
# Running          — pod успешно запущен
```

### Сценарий 2: Быстрая проверка типа ошибки

```bash
# Извлечение причины ожидания
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}'

# Возможные значения:
# ErrImagePull
# ImagePullBackOff
# RegistryUnavailable
# ErrImageNeverPull
```

---

## Дополнительная информация

### Связанные темы

- Распространённые ошибки и решения: [Common Errors](./common_errors.md)
- Пошаговая диагностика: [Diagnostics](./diagnostics.md)
- Рекомендации по предотвращению: [Best Practices](./best_practices.md)
- Air-gapped кластеры: [Air-gapped](./airgapped.md)
- Интеграция с CI/CD: [CI/CD Integration](./ci_cd_integration.md)
- Сетевые проблемы: [Network Issues](./network_issues.md)
- Документация Kubernetes — образы: [Kubernetes Images](https://kubernetes.io/docs/concepts/containers/images/)
