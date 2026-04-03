# Pod Image Pull Errors: Распространённые ошибки

## Определения

**Manifest unknown** — ошибка реестра, означающая, что указанный образ с данным именем или тегом не найден в registry.

**Unauthorized** — ошибка аутентификации, означающая, что kubelet не имеет корректных учётных данных для доступа к приватному реестру.

**ImagePullSecret** — Kubernetes Secret типа `kubernetes.io/dockerconfigjson`, содержащий учётные данные для аутентификации в приватном registry.

---

## Основные концепции

### Классификация ошибок

| Код ошибки | Категория | Корневая причина |
| :--- | :--- | :--- |
| `manifest not found` | Образ/тег не существует | Опечатка, удалённый тег, CI/CD не выполнил push |
| `unauthorized: authentication required` | Аутентификация | Отсутствует/некорректный imagePullSecret |
| `pull access denied` | Аутентификация/авторизация | Пользователь не имеет прав чтения в registry |
| `404 Not Found` | Образ не существует | Неверный path, образ никогда не загружался |

### Жизненный цикл диагностики

```
kubectl describe pod
    ↓
Анализ Events → определение типа ошибки
    ↓
manifest not found? → Проверить имя/тег образа
unauthorized? → Проверить imagePullSecret
    ↓
Исправление → kubectl apply / kubectl patch
    ↓
Подтверждение: pod запущен
```

---

## Практические сценарии

### Сценарий 1: Неверное имя или тег образа

**Сообщение:**

```
manifest for my-app:1.1 not found
manifest unknown: manifest unknown
```

**Причина:** Опечатка в имени, тег не существует, образ удалён из registry.

**Решение:**

```yaml
# ❌ Ошибка
spec:
  containers:
  - name: app
    image: myregistry.io/my-app:1.1  # Опечатка или несуществующий тег

# ✅ Решение
spec:
  containers:
  - name: app
    image: myregistry.io/my-app:1.2  # Исправленный тег
```

**Проверка доступных тегов:**

```bash
# Docker Hub
curl -s https://hub.docker.com/v2/repositories/<user>/<repo>/tags?page_size=100

# Harbor
curl -k https://harbor.example.com/api/v2.0/projects/<project>/repositories/<repo>/artifacts
```

### Сценарий 2: Проблемы с доступом к приватному репозиторию

**Сообщение:**

```
unauthorized: authentication required
pull access denied for my-app, repository does not exist or may require 'docker login'
```

**Причина:** Отсутствует или некорректно настроен `imagePullSecrets`.

**Решение — создание imagePullSecret:**

```bash
# Способ 1: kubectl create secret (рекомендуется)
kubectl create secret docker-registry regcred \
  --docker-server=https://registry.example.com \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email> \
  -n <namespace>

# Способ 2: из существующего docker config
kubectl create secret generic regcred \
  --from-file=.dockerconfigjson=$HOME/.docker/config.json \
  --type=kubernetes.io/dockerconfigjson \
  -n <namespace>
```

**Привязка secret к Pod:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  containers:
  - name: app
    image: registry.example.com/my-app:1.0
  imagePullSecrets:
  - name: regcred
```

**Привязка secret к ServiceAccount (автоматически для всех подов):**

```bash
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "regcred"}]}' \
  -n <namespace>
```

### Сценарий 3: Образ не существует

**Сообщение:**

```
manifest unknown: manifest unknown
404 Not Found
```

**Причина:** Образ никогда не загружался в репозиторий, был удалён, или неверно указан path.

**Решение:**

```bash
# Проверка наличия образа
docker pull <image-name>

# Для CI/CD: убедиться, что шаг build/push выполнен успешно
# Проверить pipeline в GitLab CI / GitHub Actions
```

**Рекомендация:** Используйте immutable tags (SHA256 digest) в production:

```yaml
image: myregistry.io/my-app@sha256:abc123...
```

---

## Дополнительная информация

### Связанные темы

- Определения и базовые концепции: [Definitions](./definitions.md)
- Пошаговая диагностика: [Diagnostics](./diagnostics.md)
- Глобальная настройка imagePullSecrets: [Best Practices](./best_practices.md#сценарий-1-глобальная-настройка-imagepullsecrets)
- Автоматическое создание secret в CI/CD: [CI/CD Integration](./ci_cd_integration.md#сценарий-1-gitlab-ci--автоматическое-создание-secret)
- Документация Kubernetes — приватные registry: [Pull Private Images](https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/)
