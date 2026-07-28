# Skopeo: Манипуляции образами без демона

## Определения

**Skopeo** — это гибкий инструмент командной строки для работы с образами контейнеров и их репозиториями. Главной особенностью Skopeo является его способность взаимодействовать с реестрами (Registry) напрямую через HTTP API, не требуя локального запуска Docker-демона, Podman или наличия прав root.

Skopeo входит в состав набора инструментов Red Hat для управления контейнерами:
- **Buildah** — сборка (Build).
- **Podman** — запуск (Run).
- **Skopeo** — передача и инспекция (Transport & Inspect).

---

## Основные концепции

### Ключевые возможности

- **Копирование без посредников:** Перемещение образов напрямую между двумя реестрами без промежуточного скачивания на диск.
- **Инспекция метаданных:** Получение информации об образе (манифест, архитектура, переменные окружения, метки) без скачивания слоев.
- **Поддержка Multi-arch:** Возможность копирования всех архитектурных вариантов образа одной командой.
- **Шифрование образов:** Поддержка шифрования и дешифрования слоев образа при передаче.
- **Синхронизация реестров:** Зеркалирование репозиториев с поддержкой фильтрации по тегам.
- **Манипуляция манифестами:** Получение дайджестов манифестов без скачивания данных.

### Типы транспортов (Transports)

Skopeo использует префиксы для определения источника и назначения данных:

| Транспорт | Описание |
| :--- | :--- |
| `docker://` | Удаленный реестр Docker (Hub, Quay, Harbor). |
| `containers-storage:` | Локальное хранилище Podman/Buildah. |
| `docker-daemon:` | Локальный кэш Docker-демона (через сокет). |
| `docker-archive:` | Файл архива, созданный через `docker save`. |
| `oci:` | Директория в формате OCI Layout. |
| `oci-archive:` | Архив (tar) в формате OCI Layout. |
| `dir:` | Локальная директория с несжатыми слоями (для отладки). |

---

## Практические сценарии

### 1. Инспекция удаленного образа

Позволяет проверить наличие нужной архитектуры или тега перед скачиванием.

```bash
# Просмотр общей информации
skopeo inspect docker://docker.io/library/nginx:latest

# Получение только дайджеста образа
skopeo inspect --format "{{.Digest}}" docker://docker.io/library/nginx:latest
```

### 2. Копирование образов

#### Между реестрами (Direct Copy)
```bash
skopeo copy \
    --src-creds user:pass1 \
    --dest-creds user:pass2 \
    docker://registry-1.com/app:v1 \
    docker://registry-2.com/app:v1
```

#### Копирование всех архитектур (Multi-arch)
Флаг `--all` гарантирует, что будут скопированы все варианты образа (x86_64, arm64 и т.д.).
```bash
skopeo copy --all docker://quay.io/libpod/alpine:latest oci:alpine-multi:latest
```

### 3. Синхронизация репозиториев (Mirroring)

Для зеркалирования используется команда `sync`. Она полезна для наполнения внутренних реестров.

```bash
# Синхронизация всех тегов из одного проекта в другой
skopeo sync --src docker --dest docker \
    my-registry.com/my-project \
    internal-registry.com/my-project
```

### 4. Авторизация (Login)

Вместо передачи учетных данных в каждой команде можно авторизоваться один раз.

```bash
skopeo login registry.example.com -u username -p password
# Учетные данные сохраняются в $XDG_RUNTIME_DIR/containers/auth.json
```

---

## Безопасность и политики

### Шифрование образов
Skopeo может шифровать образы при копировании, используя открытый ключ.

```bash
# Шифрование образа при копировании в локальный каталог
skopeo copy \
    --encryption-key jwe:/path/to/public_key.pem \
    docker://nginx:latest oci:encrypted-nginx:latest
```

### Политики подписи (Signature Verification)
Skopeo поддерживает проверку подписей образов через файл конфигурации `/etc/containers/policy.json`. Это позволяет блокировать запуск или копирование образов из недоверенных источников.

Подробнее: **[Политики подписи образов](../Docker/Docker_security/image_signature_and_verification.md)**.

---

## Интеграция в CI/CD

Skopeo является стандартом для современных CI/CD пайплайнов благодаря своей легковесности и безопасности.

**Пример в GitLab CI (Promote image):**

```yaml
promote-to-production:
  stage: release
  image: quay.io/skopeo/stable:v1.14
  script:
    - skopeo copy --all
        --src-creds $CI_REGISTRY_USER:$CI_REGISTRY_PASSWORD
        --dest-creds $PROD_REGISTRY_USER:$PROD_REGISTRY_PASSWORD
        docker://$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
        docker://$PROD_REGISTRY_IMAGE:stable
```

---

## Дополнительная информация

### Связанные разделы
- **[Buildah: Сборка образов](./buildah_overview.md)** — подготовка артефактов для передачи.
- **[Podman vs Docker](./podman_vs_docker.md)** — общая экосистема инструментов.
- **[Реестры образов](../Docker/docker_registries.md)** — виды и особенности хранилищ.
- **[Продвижение образов в CI/CD](../Docker/Docker_fs/images/promotion_cicd.md)** — стратегии перемещения между окружениями.

### Ссылки
- **[Официальный репозиторий Skopeo](https://github.com/containers/skopeo)**
- **[Руководство по синхронизации (Sync)](https://github.com/containers/skopeo/blob/main/docs/skopeo-sync.1.md)**
