# Ошибки загрузки образов (Image Pull Errors): Распространённые ошибки

## Определения

Базовые термины и концепции загрузки образов описаны в разделе [Определения](./definitions.md).

---

## Основные концепции

### Классификация ошибок

| Код ошибки | Категория | Корневая причина |
| :--- | :--- | :--- |
| `manifest not found` | Образ или тег | Опечатка, удалённый тег, CI/CD не выполнил push |
| `unauthorized` | Аутентификация | Отсутствует или некорректный `imagePullSecrets` |
| `pull access denied` | Авторизация | Пользователь не имеет прав чтения в registry |
| `404 Not Found` | Путь к образу | Неверный path, образ никогда не загружался в этот репозиторий |

Подробный алгоритм поиска причин представлен в разделе [Пошаговая диагностика](./diagnostics.md).

---

## Практические сценарии

### Сценарий 1: Неверное имя или тег образа

**Сообщение:**

```text
manifest for my-app:1.1 not found
manifest unknown: manifest unknown
```

**Причина:** Опечатка в имени, тег не существует или был удалён из registry.

**Решение:**

```yaml
# Пример исправления в спецификации Pod
spec:
  containers:
  - name: app
    image: myregistry.io/my-app:1.2  # Указан существующий тег
```

**Проверка доступных тегов:**

```bash
# Для Docker Hub
curl -s https://hub.docker.com/v2/repositories/library/nginx/tags
# → {"count": ..., "next": ..., "results": [...]}

# Для Harbor
curl -k https://harbor.example.com/api/v2.0/projects/my-proj/repositories/my-app/artifacts
# → [{"tags": [{"name": "1.2"}, ...], ...}]
```

### Сценарий 2: Ошибки аутентификации в приватном репозитории

**Сообщение:**

```text
unauthorized: authentication required
pull access denied for my-app, repository does not exist or may require 'docker login'
```

**Причина:** Отсутствует или некорректно настроен `imagePullSecrets`.

**Создание секрета (идемпотентный способ):**

```bash
kubectl create secret docker-registry regcred \
  --docker-server=https://registry.example.com \
  --docker-username=robot-user \
  --docker-password=secret-pass \
  --namespace=my-namespace \
  --dry-run=client -o yaml | kubectl apply -f -
# → secret/regcred configured
```

**Привязка секрета к ServiceAccount:**
Это позволяет не указывать секрет в каждом манифесте Deployment.

```bash
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "regcred"}]}' \
  -n my-namespace
# → serviceaccount/default patched
```

### Сценарий 3: Образ отсутствует в реестре

**Сообщение:**

```text
manifest unknown: manifest unknown
404 Not Found
```

**Причина:** Образ никогда не загружался в репозиторий или был удалён.

**Проверка наличия образа локально:**

```bash
docker pull myregistry.io/my-app:1.0
# → Error response from daemon: manifest for myregistry.io/my-app:1.0 not found
```

**Рекомендация:** Используйте неизменяемые теги (SHA256 digest) для обеспечения стабильности:

```yaml
image: myregistry.io/my-app@sha256:45b23dee...
```

---

## Дополнительная информация

### Связанные темы

- [Определения и терминология](./definitions.md) — базовые понятия.
- [Пошаговая диагностика](./diagnostics.md) — пошаговый план устранения неисправностей.
- [Лучшие практики](./best_practices.md) — предотвращение ошибок загрузки.
