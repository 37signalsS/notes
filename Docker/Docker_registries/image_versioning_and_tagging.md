# Версионирование и тегирование Docker-образов

**Актуально для:** Docker Engine 29.x, Buildx, OCI Image Spec 1.1, Kubernetes 1.29+, Docker Hub (Tag mutability settings)

## Определения

*   **Тэг (Tag)**: Изменяемая (mutable) текстовая метка, указывающая на конкретный манифест образа. Позволяет обращаться к образу по понятному имени (например, `:1.2.5`). Формат: `[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}` — до 128 символов, допустимы буквы, цифры, `_`, `.` и `-`; не может начинаться с `.` или `-`. Если тег не указан, по умолчанию используется `latest`.
*   **Дайджест (Digest)**: Уникальный, неизменяемый (immutable) идентификатор контента образа (`sha256:` + 64 шестнадцатеричных символа). Гарантирует идентичность артефакта вне зависимости от состояния тегов.
*   **Иммутабельный тег (Immutable Tag)**: Настройка реестра, запрещающая перезапись (overwrite) существующего тега. Гарантирует стабильность сред.
*   **Плавающий тег (Floating Tag / Alias)**: Тег, который перемещается и всегда указывает на последнюю версию в рамках мажора или минора (например, `:1`, `:1.2`, `:latest`).
*   **Манифест (Manifest)**: JSON-файл, описывающий состав образа: слои, конфигурацию и метаданные согласно спецификациям **OCI (Open Container Initiative)**.
*   **Манифест-лист (Manifest List / Image Index)**: Индекс, объединяющий манифесты для разных архитектур (`amd64`, `arm64`) под одним тегом. При pull клиент получает индекс и автоматически выбирает вариант под платформу хоста.
*   **OCI-аннотации (Annotations)**: Стандартизированные метаданные образа в пространстве имён `org.opencontainers.image.*` (версия, ревизия, источник и т.д.), задаваемые через `LABEL` в Dockerfile или `--annotation` в Buildx.

## Основные концепции

### Стратегии версионирования

Выбор стратегии зависит от типа проекта и модели выпуска:

1.  **Семантическое версионирование (SemVer 2.0.0)**:
    *   Формат: `MAJOR.MINOR.PATCH` (например, `2.3.1`).
    *   MAJOR — несовместимые изменения API, MINOR — обратно-совместимый новый функционал, PATCH — обратно-совместимые исправления.
    *   Pre-release: `1.0.0-alpha`, `1.0.0-alpha.1`, `1.0.0-rc.2`; build-метаданные: `1.0.0+build.5` (не влияют на приоритет версий).
    *   Применение: Публичные библиотеки, микросервисы со строгим API.
2.  **Календарное версионирование (CalVer)**:
    *   Форматы: `YYYY.MM[.MICRO]` (например, `2026.08`), `YY.MM`, `YYYY.MM.DD` (например, `2026.08.04`).
    *   Применение: Проекты с непрерывным циклом обновлений (rolling releases), например Ubuntu или базы данных.
3.  **Хеширование (Hash-based)**:
    *   Формат: короткий SHA коммита (например, `sha-a1b2c3d`).
    *   Применение: Внутренние сборки в CI/CD для обеспечения прослеживаемости (traceability) кода.

Общие принципы выбора версий описаны в **[Управлении артефактами](../../CI-CD/artifact_management.md)**.

### Формат ссылки на образ

Полная ссылка (reference) состоит из компонентов:

```text
[HOST[:PORT]/]NAMESPACE/REPOSITORY[:TAG][@sha256:DIGEST]
```

*   **HOST**: расположение реестра; по умолчанию — Docker Hub (`docker.io`).
*   **NAMESPACE**: пользователь или организация; по умолчанию — `library` (пространство Docker Official Images).
*   **REPOSITORY**: имя репозитория (до 255 символов, строчные буквы, цифры и разделители `_`, `__`, `-`, `.`).
*   **TAG**: версия или вариант; по умолчанию — `latest`.
*   **DIGEST**: неизменяемый идентификатор контента.

Пример: `registry.example.com:5000/team/my-app:2.4.1` — хост `registry.example.com:5000`, namespace `team`, репозиторий `my-app`, тег `2.4.1`.

### Фиксация по дайджесту (Digest Pinning)

В производственных средах использование тегов (даже SemVer) несет риски, так как теги мутабельны. Использование дайджеста — единственный способ гарантировать 100% воспроизводимость.

*   **Проблема**: Владелец репозитория может обновить образ под тегом `node:20-slim`, изменив версию базовой ОС или патч-версию рантайма.
*   **Решение**: Указание дайджеста в `Dockerfile` или K8s манифесте.

```dockerfile
# Использование дайджеста вместо тега
FROM node@sha256:723c347...
```

### Иммутабельность на уровне реестра

Реестры поддерживают политики **Immutable Tags**. При их включении попытка загрузить (push) образ с уже существующим тегом вернет ошибку. Это предотвращает "тихую" подмену кода в Production.

| Реестр | Поддержка | Настройка |
| :--- | :--- | :--- |
| **Docker Hub** | Три режима: все теги mutable (по умолчанию), все immutable, или по regex | Settings → General → Tag mutability settings (regex — движок Go RE2) |
| **Harbor** | Паттерны тегов (`v*`, `release-*`) | Project → Configuration → Immutable Tags |
| **AWS ECR** | Политики immutable tags на репозиторий | `put-repository-policy` / консоль |
| **GitLab Registry** | Защита тегов (`protected`) | Settings → General → Visibility, project features |

> Подробные шаги для Harbor — в **[Работе с Harbor](./Harbor/usage.md)** (сценарий 8), для Docker Hub — в документации по ссылке в «См. также».

### Плавающий тег `:latest` и его ловушки

*   `:latest` — это **не** «самая новая версия», а просто тег по умолчанию, когда тег не указан. Он может указывать на старый образ, если владелец давно не обновлял тег.
*   В Kubernetes при опущенном `imagePullPolicy` тег `:latest` (или отсутствие тега) автоматически задаёт `imagePullPolicy: Always`, а конкретный тег — `IfNotPresent`. Значение `imagePullPolicy` фиксируется при создании объекта и **не** обновляется при смене тега.
*   В Production избегайте `:latest`: сложнее отследить запущенную версию и выполнить откат. Используйте осмысленный тег (`v1.42.0`) и/или дайджест.

### Метаданные версии через OCI-аннотации

Теги — это ссылки, а не метаданные. Для машиночитаемой информации об образе используйте стандартные аннотации OCI (задаются как `LABEL` в Dockerfile):

| Аннотация | Назначение |
| :--- | :--- |
| `org.opencontainers.image.version` | Версия упакованного ПО (может быть SemVer-совместимой) |
| `org.opencontainers.image.revision` | Идентификатор ревизии в системе контроля версий |
| `org.opencontainers.image.source` | URL исходного кода для сборки образа |
| `org.opencontainers.image.created` | Дата сборки (RFC 3339) |
| `org.opencontainers.image.vendor` | Имя организации-распространителя |
| `org.opencontainers.image.licenses` | SPDX-выражение лицензии |
| `org.opencontainers.image.base.name` / `.base.digest` | Ссылка и дайджест базового образа |

## Практические сценарии

### Сценарий 1: Многоуровневое тегирование в CI/CD

При выпуске релиза рекомендуется создавать цепочку тегов для удобства пользователей.

```bash
IMAGE="registry.example.com/app"
VERSION="2.4.1"

# 1. Основной тег (SemVer)
docker tag app:latest $IMAGE:$VERSION

# 2. Создание плавающих тегов
docker tag $IMAGE:$VERSION $IMAGE:2.4
docker tag $IMAGE:$VERSION $IMAGE:2
docker tag $IMAGE:$VERSION $IMAGE:latest

# 3. Отправка всех тегов одной командой
docker push $IMAGE --all-tags
```

```text
# → 2.4.1: digest: sha256:abcd... size: 1024
# → 2.4: digest: sha256:abcd... size: 1024
# → 2: digest: sha256:abcd... size: 1024
# → latest: digest: sha256:abcd... size: 1024
```

> `docker push --all-tags` (`-a`) отправляет все теги репозитория и поддерживается в Docker CLI 29.x. Альтернатива — явный push каждого тега: `docker push $IMAGE:$VERSION && docker push $IMAGE:2.4 ...`

### Сценарий 2: Логика автоматического тегирования в пайплайне

Типовой алгоритм для GitLab CI или GitHub Actions:

*   **Ветка `main`**: тегируется как `:edge` или `:latest`.
*   **Git Tag (v*)**: тегируется как `:1.2.3` (SemVer).
*   **Каждый коммит**: тегируется как `:sha-abcdef`.

```bash
# Пример формирования тега в CI
if [ -n "$CI_COMMIT_TAG" ]; then
  DOCKER_TAG="$CI_COMMIT_TAG"
else
  DOCKER_TAG="sha-${CI_COMMIT_SHORT_SHA}"
fi

docker build -t $IMAGE:$DOCKER_TAG .
```

### Сценарий 3: Сборка многоархитектурных образов

Использование **Buildx** позволяет создать единый тег для разных платформ.

```bash
# Создание строителя с поддержкой мультиплатформенности
docker buildx create --name mybuilder --use

# Сборка и отправка манифест-листа
docker buildx build --platform linux/amd64,linux/arm64 \
  -t registry.example.com/service:1.0.0 --push .
```

```text
# → [+] Building 120.0s (23/23) FINISHED
# → registry.example.com/service:1.0.0
```

**Ограничения и проверка:**

*   `--load` (shorthand для `--output=type=docker`) работает **только для одной платформы**: стандартный образ Docker Engine не поддерживает загрузку мультиплатформенных образов (`ERROR: docker exporter does not currently support exporting manifest lists`). Для нескольких платформ используйте `--push`. Локальное хранение мультиплатформенных образов возможно при включённом containerd image store.
*   Проверьте манифест-лист в реестре после push:

```bash
docker buildx imagetools inspect registry.example.com/service:1.0.0
```

```text
# → Name:      registry.example.com/service:1.0.0
# → MediaType: application/vnd.docker.distribution.manifest.list.v2+json
# → Digest:    sha256:21a3deaa0d32...
# → Manifests:
# →   Name:      registry.example.com/service:1.0.0@sha256:e7d88de73db3...
# →   Platform:  linux/amd64
# →   Name:      registry.example.com/service:1.0.0@sha256:c4ba6347b0e4...
# →   Platform:  linux/arm64
```

*   Для добавления тега к уже существующему манифест-листу (без пересборки) — `docker buildx imagetools create`:

```bash
# Создать тег 1.0.1 как копию манифест-листа 1.0.0
docker buildx imagetools create --tag registry.example.com/service:1.0.1 \
  registry.example.com/service:1.0.0
```

> Команда `docker manifest` (create/inspect/push) является экспериментальной — Docker рекомендует использовать её только для тестирования, не в Production; для продакшена — `docker buildx imagetools`.

### Сценарий 4: Фиксация версии в Kubernetes

Пример деплоя с использованием дайджеста для максимальной безопасности.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-service
spec:
  template:
    spec:
      containers:
      - name: main
        image: registry.example.com/api@sha256:abcd1234...
```

**Взаимодействие тега и `imagePullPolicy`** (по умолчанию, при опущенном `imagePullPolicy`):

| Ссылка в манифесте | Автоматический `imagePullPolicy` | Поведение |
| :--- | :--- | :--- |
| `image@sha256:...` (дайджест) | `IfNotPresent` | Дайджест неизменяем — повторный pull не нужен, содержимое гарантированно то же |
| `image:1.2.3` (конкретный тег) | `IfNotPresent` | Тег может быть перезаписан в реестре, но kubelet не проверит это повторно |
| `image:latest` или без тега | `Always` | Kubelet каждый раз резолвит тег в дайджест и тянет обновление |

> Значение `imagePullPolicy` фиксируется при создании объекта и не меняется при последующей смене тега в манифесте — при переходе на `:latest` его нужно задавать явно.

### Сценарий 5: Проверка дайджеста и манифеста

Стандартные операции идентификации образа:

```bash
# 1. Дайджесты образов в локальном хранилище
docker images --digests nginx

# 2. RepoDigest образа (ссылка по дайджесту в реестре)
docker inspect --format='{{index .RepoDigests 0}}' registry.example.com/my-app:1.2.0

# 3. Манифест образа в реестре (одноплатформенный или список)
docker manifest inspect registry.example.com/my-app:1.2.0

# 4. Pull конкретной платформы из мультиплатформенного образа
docker pull --platform linux/arm64 registry.example.com/service:1.0.0
```

```text
# → docker images --digests:
# →   nginx   1.31   sha256:<manifest-digest>   sha256:<config-digest>   ...
# → docker inspect RepoDigests:
# →   registry.example.com/my-app@sha256:abc123...
```

> `docker manifest inspect` — экспериментальная команда (тестирование); для Production-проверки мультиплатформенных образов используйте `docker buildx imagetools inspect` (сценарий 3).

### Сценарий 6: Метаданные версии через OCI LABEL

```dockerfile
# LABEL в Dockerfile — метаданные доступны через docker inspect
LABEL org.opencontainers.image.version="2.4.1" \
      org.opencontainers.image.revision="a1b2c3d4e5f6" \
      org.opencontainers.image.source="https://git.example.com/team/app" \
      org.opencontainers.image.vendor="Team"
```

```bash
# Аннотации на уровне индекса/манифеста при сборке Buildx
docker buildx build --push \
  --annotation "index:org.opencontainers.image.authors=team@example.com" \
  --annotation "manifest[linux/amd64]:foo=bar" \
  -t registry.example.com/service:1.0.0 .
```

```bash
# Проверка метаданных
docker inspect registry.example.com/service:1.0.0 --format='{{index .Config.Labels "org.opencontainers.image.version"}}'
```

```text
# → 2.4.1
```

## Валидация

```bash
# 1. Формат тега корректен (не начинается с . или -, <=128 символов)
docker tag app:latest registry.example.com/app:2.4.1
# → OK; ошибка формата: "invalid reference format"

# 2. Все теги релиза указывают на один дайджест
docker buildx imagetools inspect registry.example.com/app:2.4.1 --format '{{json .Manifest.Digest}}'
docker buildx imagetools inspect registry.example.com/app:2 --format '{{json .Manifest.Digest}}'
# → одинаковый sha256:... для обоих тегов

# 3. Дайджест в манифесте Kubernetes совпадает с реестром
kubectl get deployment api-service -o jsonpath='{.spec.template.spec.containers[0].image}'
docker buildx imagetools inspect registry.example.com/api@sha256:abcd1234...
# → Manifest.Digest совпадает с указанным в манифесте

# 4. Иммутабельность включена: повторный push того же тега отклонён
docker push registry.example.com/app:2.4.1
# → denied: immutable tag 2.4.1 already exists (Harbor/Docker Hub с включённой политикой)
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `invalid reference format` при tag/push | Тег начинается с `.` или `-`, содержит недопустимые символы или длиннее 128 символов | Привести тег к формату `[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}` |
| `ERROR: docker exporter does not currently support exporting manifest lists` | `--load` при сборке для нескольких `--platform` | Использовать `--push` или включить containerd image store для локального хранения |
| В Kubernetes под не обновляется после перезаливки тега | `imagePullPolicy: IfNotPresent` + конкретный тег: kubelet использует локальный кэш | Фиксировать образ дайджестом; при необходимости `imagePullPolicy: Always` или `kubectl rollout restart` |
| `imagePullPolicy` не стал `Always` после смены тега на `:latest` | Политика фиксируется при создании объекта и не пересчитывается | Задавать `imagePullPolicy` явно в манифесте |
| `docker manifest inspect` не показывает мультиплатформенность | Образ одноплатформенный или команда экспериментальна | Проверить через `docker buildx imagetools inspect` |
| Push отклонён с ошибкой immutable tag | В реестре включена политика Immutable Tags | Создать новый тег версии; изменить политику в настройках реестра |
| `docker tag` перезаписал существующий тег локально | Локальный тег — mutable по умолчанию (флаг `-f` не нужен с Docker 1.12+) | Использовать уникальные теги или дайджесты для отслеживания версий |

## Граничные случаи

*   **Один тег — разные дайджесты во времени**: мутабельный тег (`:1.2`, `:latest`) может указывать на разный контент после перезаливки; только дайджест гарантирует идентичность.
*   **Multi-arch дайджесты**: у мультиплатформенного образа дайджест манифест-листа (index) отличается от дайджестов отдельных платформенных манифестов; при фиксации в K8s используйте дайджест индекса.
*   **`latest` не означает «новое»**: тег `:latest` может указывать на старый образ; он лишь тег по умолчанию.
*   **Локальный vs реестровый тег**: `docker tag` создаёт ссылку в локальном хранилище и не затрагивает реестр; перезапись локального тега не влияет на уже запушенный образ.
*   **Pre-release SemVer в тегах**: символы `+` (build-метаданные) недопустимы в теге Docker — `1.0.0+build.5` нужно преобразовывать (например, `1.0.0-build.5`).
*   **Реестр без поддержки immutable tags**: при отсутствии политики (например, простой `registry:3` без настроек) теги всегда перезаписываемы — компенсируйте фиксацией по дайджесту.
*   **`docker pull` по дайджесту игнорирует тег**: ссылка `image@sha256:...` всегда возвращает один и тот же контент, даже если тег в реестре перемещён.

## Лучшие практики

*   **Чистка (Retention)**: Настраивайте политики удаления в реестре (например, "удалять образы веток старше 30 дней", но "хранить все релизные теги").
*   **Метаданные**: Используйте `LABEL` с OCI-аннотациями (`org.opencontainers.image.version`, `.revision`, `.source`) для хранения версии и ссылки на коммит, помимо тегов.
*   **Автоматизация**: Используйте инструменты вроде `semantic-release` для исключения ручного управления версиями.
*   **Production-деплой**: Фиксируйте образ дайджестом в манифестах Kubernetes поверх любой стратегии тегирования; включайте Immutable Tags в реестре для релизных тегов.
*   **Многоуровневые теги**: При релизе создавайте цепочку `:MAJOR.MINOR.PATCH` → `:MAJOR.MINOR` → `:MAJOR` → `:latest`, все указывающие на один дайджест.
*   **Откат**: Храните дайджесты предыдущих релизов (например, в Git) для быстрого отката без пересборки — `kubectl rollout undo` или возврат к предыдущему дайджесту.

## См. также

*   **[Безопасность публичных реестров](./public_registry_security.md)** — риски мутабельных тегов и фиксация по дайджесту.
*   **[Продвижение образов в CI/CD](../Docker_fs/images/promotion_cicd.md)** — перемещение артефактов по контурам, модели продвижения.
*   **[Продвижение артефактов между средами](../../CI-CD/Deployment_Strategies/artifact_promotion.md)** — команды работы с digest при promotion.
*   **[Работа с Harbor](./Harbor/usage.md)** — настройка Immutable Tags и политик очистки.
*   **[Управление артефактами](../../CI-CD/artifact_management.md)** — концепции SemVer и CalVer.
*   **[Подпись и верификация образов](../Docker_security/image_signature_and_verification.md)** — Cosign/Notation, подписи по дайджесту.
*   **[SBOM образов](../Docker_security/docker_sbom.md)** — генерация SBOM при сборке.
*   **[Immutable tags на Docker Hub](https://docs.docker.com/docker-hub/repos/manage/hub-images/immutable-tags/)** — настройка Tag mutability settings.
*   **[OCI Image Spec — Annotations](https://github.com/opencontainers/image-spec/blob/main/annotations.md)** — стандартные ключи аннотаций.
*   **[Kubernetes: Images](https://kubernetes.io/docs/concepts/containers/images/)** — imagePullPolicy и дайджесты.
