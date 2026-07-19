# Skopeo: Манипуляции образами без демона

## Определения

**Skopeo** — инструмент командной строки для выполнения различных операций с образами контейнеров и их репозиториями. Работает напрямую с реестрами через HTTP API, не требуя локального запуска Docker-демона или Podman.

Официальный репозиторий: **[github.com/containers/skopeo](https://github.com/containers/skopeo)**.

## Базовые концепции

Skopeo является частью "тройки" инструментов Red Hat для работы с контейнерами:
1. **Buildah** — сборка (Build).
2. **Podman** — запуск (Run).
3. **Skopeo** — передача и инспекция (Transport & Inspect).

### Ключевые возможности

- **Копирование образов:** Перемещение образов между различными типами хранилищ (например, из одного реестра в другой, из реестра в локальный каталог OCI или в локальный кэш Docker).
- **Инспекция без скачивания:** Получение метаданных образа (манифест, слои, переменные окружения) из удаленного реестра без предварительного `pull`.
- **Синхронизация реестров:** Зеркалирование целых репозиториев.
- **Управление подписями:** Проверка и создание подписей для образов (Simple Signing).
- **Удаление образов:** Удаление образов из удаленных реестров (если поддерживается API реестра).

### Транспорты (Transport Types)

Skopeo использует префиксы для определения источника и назначения:
- `docker://` — удаленный реестр Docker (например, Docker Hub, Harbor).
- `docker-daemon:` — локальный кэш Docker-демона.
- `containers-storage:` — локальное хранилище Podman/Buildah.
- `oci:` — локальная директория в формате OCI.
- `dir:` — локальная директория с несжатыми слоями (удобно для отладки).

## Практические сценарии

### 1. Инспекция удаленного образа

Позволяет узнать размер слоев, архитектуру иLabels без скачивания гигабайтов данных.

```bash
skopeo inspect docker://registry.access.redhat.com/ubi8/ubi-minimal
```

### 2. Копирование между реестрами (Direct Copy)

Наиболее эффективный способ синхронизации образов в CI/CD пайплайнах. Образ передается напрямую из реестра в реестр, минуя локальный диск.

```bash
skopeo copy \
    --src-creds user:pass1 \
    --dest-creds user:pass2 \
    docker://registry-source.com/app:v1 \
    docker://registry-dest.com/app:v1
```

### 3. Копирование в локальный OCI-каталог

Полезно для архивации образов или их передачи на "изолированные" (air-gapped) системы.

```bash
skopeo copy docker://nginx:latest oci:nginx-latest-dir:latest
```

### 4. Синхронизация репозиториев

Автоматическое зеркалирование всех тегов из одного проекта в другой.

```bash
skopeo sync --src docker --dest docker \
    --src-creds $SRC_USER:$SRC_PASS \
    --dest-creds $DEST_USER:$DEST_PASS \
    my-registry.com/my-project \
    internal-registry.com/my-project
```

### 5. Удаление образа из реестра

```bash
skopeo delete docker://my-registry.com/my-app:old-tag
```

## Интеграция в CI/CD

Skopeo идеально подходит для пайплайнов, так как он:
1. **Безопасен:** Не требует `root` или доступа к `docker.sock`.
2. **Легковесен:** Бинарный файл занимает мало места, есть официальные образы.
3. **Эффективен:** Минимизирует сетевой трафик и дисковые операции.

**Пример в GitLab CI:**

```yaml
push-to-prod:
  stage: deploy
  image: quay.io/skopeo/stable:latest
  script:
    - skopeo copy 
        --src-creds $CI_REGISTRY_USER:$CI_REGISTRY_PASSWORD
        --dest-creds $PROD_REGISTRY_USER:$PROD_REGISTRY_PASSWORD
        docker://$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
        docker://$PROD_REGISTRY_IMAGE:latest
```

## Дополнительная информация

- **[Buildah: Сборка образов](./buildah_overview.md)**
- **[Podman: Запуск контейнеров](./podman_vs_docker.md)**
- **[Безопасность цепочки поставок: Подписи](../Security/Supply_Chain_Security/build_integrity.md)**
- **[Политики подписи образов (Simple Signing)](../Docker/Docker_security/image_signature_and_verification.md)**
