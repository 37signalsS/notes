# Pod Image Pull Errors: Распространённые ошибки

## 1. Неверное имя или тег образа

**Сообщение:**

```
manifest for my-app:1.1 not found
manifest unknown: manifest unknown
```

**Причина:** Опечатка в имени, тег не существует, образ удален.

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

**Проверка:**

```bash
# Список тегов в registry (для Docker Hub)
curl -s https://hub.docker.com/v2/repositories/<user>/<repo>/tags?page_size=100

# Для Harbor
curl -k https://harbor.example.com/api/v2.0/projects/<project>/repositories/<repo>/artifacts
```

## 2. Проблемы с доступом к приватному репозиторию

**Сообщение:**

```
unauthorized: authentication required
pull access denied for my-app, repository does not exist or may require 'docker login'
```

**Причина:** Отсутствует или неверно настроен `imagePullSecrets`.

**Решение:**

### Создание imagePullSecret

```bash
# Способ 1: kubectl create secret
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

### Привязка secret к Pod

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

### Привязка secret к ServiceAccount (автоматически для всех подов)

```bash
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "regcred"}]}' \
  -n <namespace>
```

## 3. Образ не существует

**Сообщение:**

```
manifest unknown: manifest unknown
404 Not Found
```

**Причина:** Образ никогда не был загружен в репозиторий, удален, или неверно указан path.

**Решение:**

```bash
# Проверка наличия образа
docker pull <image-name>

# Для CI/CD: убедиться, что image build шаг выполнен успешно
# Проверить pipeline в GitLab CI / GitHub Actions
```

**Best Practice:** Используйте immutable tags (SHA256 digest) в production:

```yaml
image: myregistry.io/my-app@sha256:abc123...
```
