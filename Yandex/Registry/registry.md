# Yandex Container Registry: Управление образами

## 1. Определения

**Container Registry (Реестр контейнеров)** — сервис Yandex Cloud для хранения, управления и доставки контейнерных образов (Docker/OCI). Интегрирован с Kubernetes и поддерживает S3-совместимый доступ к артефактам.

**Репозиторий (Repository)** — именованная группа образов внутри реестра. Содержит теги и манифесты образов.

**Авторизация** — `yc container registry configure-docker` регистрирует `cr.yandex` в `~/.docker/config.json` как trusted registry, используя IAM-токен вместо `docker login`.

---

## 2. Базовые концепции

### Архитектура

```
yc CLI → IAM-токен → Container Registry API → Docker daemon
                                                    ↓
                                          cr.yandex/<registry_id>/<name>:<tag>
```

- **registry_id** — уникальный ID реестра (не имя).
- **cr.yandex** — endpoint реестра (без `:443` — использует TLS по умолчанию).
- **`configure-docker`** — пишет credential helper в `~/.docker/config.json`, токен обновляется автоматически (TTL ~12 ч).

### Лимиты (2026)

- Максимальный размер образа: 10 ГБ.
- Максимальное количество тегов на репозиторий: 1000.
- Холодное храниение (Infrequent Access) — для редко используемых образов.

---

## 3. Практические сценарии

### Создание реестра и авторизация Docker

```bash
# Создать реестр
yc container registry create --name my-registry

# Получить ID реестра
REGISTRY_ID=$(yc container registry get --name my-registry --format json | jq -r '.id')

# Настроить Docker для аутентификации через IAM (без docker login)
yc container registry configure-docker
# → Запись в ~/.docker/config.json для cr.yandex
```

### Сборка, тегирование и загрузка образа

```bash
# Тег с подставленным ID реестра (не хардкодим cr.yandex/<reg-id>)
docker tag myapp:latest \
  cr.yandex/$(yc container registry get --name my-registry --format json | jq -r '.id')/myapp:latest

# Push
docker push cr.yandex/$REGISTRY_ID/myapp:latest
```

### Управление образами и GC

```bash
# Список репозиториев
yc container repository list --format json | jq -r '.[].name'

# Список всех образов по репозиториям (имя:тег, incl <none>)
yc container repository list --format json | \
  jq -r '.[].name' | while read r; do \
    yc container image list --repository-name "$r" --format json | \
    jq -r '.[] | "\(.name):\(.tags[]? // "<none>")"'; \
  done
# → полезно перед чисткой реестра (garbage collection)
```

### Очистка устаревших образов

```bash
# Удалить образ по digest
yc container image delete \
  --repository-name my-repo \
  --digest sha256:<image_digest>
```

---

## 4. Дополнительная информация

- **Интеграция с Kubernetes:** образы из YC Container Registry доступны в кластерах Managed Service for Kubernetes без дополнительной конфигурации.
- **Сканирование уязвимостей:** интеграция с [Trivy](../../Docker/Docker_security/vulnerability_scanning.md).
- **Политики доступа:** RBAC через IAM-роли на уровне реестра и репозитория.
