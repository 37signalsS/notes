# Абстрагирование деталей реализации сборки образов с Kaniko

> [!WARNING]
> **Статус проекта:** Официальный репозиторий Google (`GoogleContainerTools/kaniko`) был **архивирован 3 июня 2025 года**, патчи безопасности от Google более не выпускаются. Развивает проект сообщество — **[osscontainertools/kaniko](https://github.com/osscontainertools/kaniko)**. Образы публикуются в `ghcr.io/osscontainertools/kaniko` и зеркалируются в Docker Hub. Технические детали инструмента — в [Руководстве по Kaniko](../../../../Docker/Dockerfile/dockerfile_kaniko.md).

**Актуально для:** osscontainertools/kaniko 1.28.x (форк сообщества); GitLab CI 17.x–19.x; Kubernetes 1.28+.

## Определения

**Абстрагирование деталей реализации** — стратегический этап развития CI/CD, при котором внутренняя логика выполнения задач (выбор инструментов, команды, конфигурация среды) инкапсулируется внутри общего шаблона. Потребитель шаблона взаимодействует только с интерфейсом (переменными), не зная о том, какой именно инструмент (Docker, Kaniko, Buildah) выполняет работу.

**Kaniko** — утилита для сборки контейнерных образов из Dockerfile внутри контейнера или Kubernetes-кластера без Docker-демона. Она не запускает контейнеры и не использует привилегированные механизмы ядра: распаковывает файловую систему базового образа в корень собственного контейнера, выполняет инструкции Dockerfile и после каждой из них делает снапшот файловой системы в пространстве пользователя (userspace), упаковывая изменения в слой.

**Интерфейс «Черного ящика»** — концепция проектирования шаблонов, где проект передает только бизнес-параметры (путь к коду, имя образа), а технические детали (аутентификация, кэширование, сетевые настройки) управляются централизованно.

**Контекст этапа:** Четвертый уровень зрелости CI/CD, фокусирующийся на безопасности инфраструктуры и возможности бесшовной замены технологического стека без изменения кода в сотнях репозиториев.

### Архитектура абстрагирования

```
┌─────────────────────────────────────────────────────┐
│         Центральный шаблон (shared/ci-templates)     │
│  ┌───────────────────────────────────────────────┐  │
│  │  .docker-build-base                           │  │
│  │  ┌─────────────┐  ┌──────────────────────┐   │  │
│  │  │ Переменные   │  │ before_script        │   │  │
│  │  │ (интерфейс)  │  │ (сейчас — пустой:    │   │  │
│  │  │ DOCKERFILE   │  │  аутентификация      │   │  │
│  │  │ CONTEXT      │  │  встроена в Kaniko)  │   │  │
│  │  │ DESTINATION  │  │                      │   │  │
│  │  └─────────────┘  └──────────────────────┘   │  │
│  └───────────────────────────────────────────────┘  │
│                        │                            │
│                        ▼                            │
│  ┌───────────────────────────────────────────────┐  │
│  │  script: /kaniko/executor (скрытая логика)    │  │
│  │   + credential helper gitlab, кэш, digest     │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Проект A    │ │  Проект B    │ │  Проект N    │
│  extends:    │ │  extends:    │ │  extends:    │
│  .docker-    │ │  .docker-    │ │  .docker-    │
│  build-base  │ │  build-base  │ │  build-base  │
└──────────────┘ └──────────────┘ └──────────────┘
```

## Эволюционное преимущество перед предыдущим этапом

На этапе [extends](./evolution_extends.md) проекты получили возможность наследовать и кастомизировать шаблоны. Однако детали реализации (какой инструмент собирает образ, как хранятся секреты, какой используется режим привилегий) оставались «прозрачными» — разработчик мог случайно ввести небезопасную конфигурацию или жестко привязаться к Docker.

| Характеристика | Этап 3 (Extends) | Этап 4 (Абстракция + Kaniko) |
| :--- | :--- | :--- |
| **Инструмент сборки** | Виден и доступен для изменений | Скрыт внутри шаблона |
| **Безопасность** | Зависит от дисциплины разработчика | Гарантируется шаблоном (нет `--privileged`) |
| **Смена стека** | Требует правок в каждом проекте | Одна правка в центральном шаблоне |
| **Аутентификация** | Каждый проект управляет секретами | Централизованно (credential helpers, JWT) |
| **Аудит** | Распределенный, трудоемкий | Точки сбора в одном месте |

**Ключевой переход:** от «гибких, но хрупких» шаблонов к «безопасным по умолчанию» конфигурациям, где неправильная настройка технически невозможна без модификации центрального шаблона.

## Базовые концепции

### Проблемы прямой зависимости от Docker

На этапах [include:project](./evolution_include.md) и [extends](./evolution_extends.md) часто используется Docker-in-Docker (DinD). Это создает ряд рисков:
1.  **Безопасность:** Режим `privileged: true` и доступ к docker socket позволяют контейнеру получить доступ к устройствам хоста, что делает инфраструктуру уязвимой для атак типа «Container Escape».
2.  **Архитектурная связанность:** Если компания решает перейти на Podman или другой инструмент, придется вручную обновлять тысячи файлов `.gitlab-ci.yml`.
3.  **Сложность обслуживания:** Каждый проект должен самостоятельно управлять `config.json` или переменными для авторизации, что ведет к дублированию секретов и ошибок.

### Преимущества абстракции

1.  **Инфраструктурная мобильность:** Возможность заменить Kaniko на Buildah или BuildKit, обновив только один файл шаблона.
2.  **Централизованный аудит:** В шаблон легко добавить принудительное сканирование уязвимостей (Trivy) или подпись образов (Cosign) для всей компании сразу.
3.  **Безопасность по умолчанию:** Разработчики не могут случайно запустить привилегированный контейнер, так как не имеют прямого контроля над секцией `image` и `script` в задачах сборки.

### Как Kaniko выполняет сборку (механизм изоляции)

Понимание реального механизма важно для оценки угроз. Kaniko работает **не через `chroot`**: `chroot` и bind-mount требуют привилегий (`CAP_SYS_ADMIN`), которых у контейнера нет, поэтому (цитата из README форка) *«оно распаковывает файлы прямо в корень собственного контейнера»*.

1.  **Распаковка базового образа:** образ из `FROM` скачивается и его файловая система извлекается в корень (`/`) контейнера Kaniko.
2.  **Выполнение инструкций:** каждая команда `RUN` исполняется как обычный процесс внутри того же контейнера, без изоляции через namespaces.
3.  **Снапшотинг (diff слоёв):** после каждой инструкции Kaniko сравнивает контрольные суммы файлов с предыдущим состоянием; измененные файлы упаковываются в слой (`tar.gz`), который затем отправляется в реестр.
4.  **Multi-stage:** стадии выполняются последовательно в одном контейнере; артефакты `COPY --from=` между стадиями сохраняются во временном хранилище, перед новой стадией файловая система очищается.

Практические следствия для безопасности:

- Побег из контейнера через техники `chroot`-escape (montage, pivot) неприменим — изоляция обеспечивается самим контейнерным рантаймом (cgroups/namespaces), а не эмуляцией внутри.
- Kaniko исполняется с **UID 0 внутри своего контейнера** (в образе нет директивы `USER`). Это нормально: он распаковывает ФС в `/` и должен уметь создавать файлы. Привилегированным он при этом не становится — у него нет доступа к демону, устройствам хоста и не выдаются дополнительные capabilities.

### Безопасность: почему Kaniko, а не DinD

Ключевые векторы защиты:

1.  **Отсутствие `--privileged` и docker socket:** Kaniko не требует привилегированного режима и не монтирует `/var/run/docker.sock`. Процесс сборки не получает доступ к cgroups, namespaces, устройствам и демону хоста. Это исключает главный вектор «Container Escape» при компрометации CI-контейнера.
2.  **Без дополнительных capabilities:** стоковый образ не требует добавления capabilities сверх того, что есть у обычного контейнера. Реальная совместимость с Pod Security Standards — детально ниже.
3.  **Ограничения оркестратора:** в Kubernetes `NetworkPolicy` жестко ограничивает сетевую активность пода сборки — нельзя сканировать внутреннюю сеть и подключаться к неавторизованным реестрам; `ResourceQuota`/LimitRange ограничивают потребление ресурсов.
4.  **Аутентификация без паролей в хранилище:** встроенные credential helpers и OIDC позволяют не хранить долгоживущие пароли ни в шаблоне, ни в проектах.

#### Реальное соответствие Pod Security Standards

Утверждение «работает в профиле `restricted`» требует уточнения. Pod Security Standards (`restricted`) **требуют** `runAsNonRoot: true`, `runAsUser ≠ 0` и `allowPrivilegeEscalation: false`. Стоковый образ Kaniko исполняется с UID 0 и не содержит не-root пользователя, поэтому **под `restricted` он не проходит без пересборки образа**.

Точная картина по профилям:

| Профиль | Требования (релевантные) | Kaniko (стоковый образ) |
| :--- | :--- | :--- |
| `privileged` | нет ограничений | проходит (но бессмысленно) |
| `baseline` | без `privileged`, hostPath, host-сетей; capabilities только из разрешенного списка | **проходит без изменений** |
| `restricted` | + `runAsNonRoot: true`, `runAsUser ≠ 0`, `allowPrivilegeEscalation: false`, `drop: [ALL]`, seccomp `RuntimeDefault` | **не проходит** (UID 0) |

Рекомендуемая архитектура для Kubernetes: выделенный неймспейс сборки образов с профилем `baseline` (или exemption от `restricted`), сетевые `NetworkPolicy` из белого списка (реестр, Git, менеджеры пакетов), `ResourceQuota` на namespace. Production-неймспейсы с `restricted` остаются недоступными для задач сборки.

> **Сравнение векторов атаки:** Подробный анализ рисков DinD, Socket Mount и Kaniko приведён в разделе [Docker-in-Docker: Запуск в контейнере](../../../../Docker/docker-in-docker.md#выбор-метода-сборки-dind-vs-kaniko).

### Аутентификация в реестре — скрытая логика шаблона

В форке 1.28.x аутентификацию можно полностью спрятать внутрь Kaniko через встроенные **credential helpers**. По умолчанию активны `[env, google, ecr, acr, gitlab]`; список переопределяется флагом `--credential-helpers` (пустое значение отключает все). До выбора helpers работает базовый keychain (`authn.DefaultKeychain`), который читает `DOCKER_AUTH_CONFIG` (переменная окружения) и `/kaniko/.docker/config.json` в этом порядке приоритета.

- **Базовый keychain (config.json / `DOCKER_AUTH_CONFIG`):** обрабатывает `DOCKER_AUTH_CONFIG` и файл `/kaniko/.docker/config.json`, при этом **`DOCKER_AUTH_CONFIG` всегда имеет приоритет над файлом** и может его «затенять». Это штатный способ авторизации во внешних реестрах (Harbor, Nexus, Docker Hub): администратор кладет закодированный `auths` в защищенную CI-переменную, и проекты не видят секрет.
- **`gitlab`** — читает предопределенные переменные `CI_REGISTRY`, `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD` (= `CI_JOB_TOKEN`) и автоматически авторизуется в GitLab Container Registry (и только в него). Для шаблона GitLab **больше не нужен `before_script`** с ручной генерацией `config.json`.
- **`env`** — `KANIKO_<HOST_WITH_UNDERSCORES>_USER` / `KANIKO_<HOST_WITH_UNDERSCORES>_PASSWORD`, например для `registry.example.com` — `KANIKO_REGISTRY_EXAMPLE_COM_USER`.
- **namespace-aware (path-scoped) учетные данные (1.28.4+):** запись `auths` может покрывать часть пути реестра, а не только хост. Для `registry.example.com/org-a/project/image` подбор идет по цепочке `…/project/image → …/org-a/project → …/org-a → …/host`, первое найденное значение побеждает. Это позволяет держать одну запись на организацию (например, robot-аккаунт Quay) вместо записи на каждое репозиторий. Доступно за флагом `FF_KANIKO_PATH_SCOPED_REGISTRY_AUTH` (по умолчанию `false`) — включается через переменную окружения сборки.

Важное ограничение: **Kaniko не делает сетевой фолбэк между credentials**. Он выбирает один локально и не повторяет запрос с другим постапись после `401`. Поэтому рассинхронизация `DOCKER_AUTH_CONFIG` и `config.json` приводит не к «попробовал второе», а к падению сборки.

### Кэширование слоёв в абстрагированном шаблоне

Kaniko хранит кэш слоёв в реестре (remote-only) — контейнер удаляется после каждой сборки, локального персистентного кэша по умолчанию нет. Ключевые детали, которые нужно знать при проектировании шаблона:

-   **`--cache-repo`:** репозиторий хранения кэша. Если не задан — выводится из `--destination` автоматически. Рекомендуется отдельный namespace (`$CI_REGISTRY_IMAGE/cache`), чтобы кэш не смешивался с основными образами.
-   **`--cache-copy-layers` (по умолчанию `false`):** слои инструкций `COPY` **не кэшируются**, пока флаг не включен. Типичная причина «кэш не работает» при неизменно-меняющихся `COPY`.
-   **Логика «все или ничего» в рамках стадии:** после **промаха** (cache miss) оставшиеся команды стадии **не обращаются к кэшу** — все последующие слои строятся локально (`FF_KANIKO_CACHE_PROBE_AFTER_MISS` предлагает иное поведение). Стабильная часть Dockerfile должна стоять выше изменяемой.
-   **TTL:** `--cache-ttl` по умолчанию **336h (две недели)**, а не 24 часа. По истечении TTL слои пересобираются, даже если исходный код не изменился.
-   **Локальный кэш (для отладки и Kubernetes):** поддерживается `--cache-dir` (по умолчанию `/cache`), предзаполнение базовых образов через образ `warmer`, а также формат `--cache-repo=oci:` (OCI-layout в локальной папке). На Kubernetes локальный кэш монтируется как PVC, но при конвейерных сборках к нему нужно сериализовать доступ.
-   **Параллелизм:** одновременные сборки могут писать кэш слоя в одно время и конфликтовать. В GitLab задачу следует ограничить `resource_group`, чтобы сборки в пределах одной группы не пересекались по `cache-repo`.

### Влияние на архитектуру Container Registry

Централизованная сборка через Kaniko создаёт специфические требования к реестру образов:

1.  **Хранение кэша:** репозиторий кэша использует OCI Distribution API. Суммарный объём кэшированных слоёв может превышать размер основных образов в 3–5 раз.
2.  **Очистка:** настройте политики удаления неиспользуемых тегов и кэшированных слоёв. В Harbor это делается через `Garbage Collection`, в GitLab — через `Package Registry cleanup` в настройках проекта.
3.  **Корпоративные зеркала (air-gapped):** для ограниченных сред Kaniko умеет направлять `FROM docker.io/...` в корпоративное зеркало: `--registry-mirror harbor.internal.example.com/dockerhub` (и `--skip-default-registry-fallback` чтобы не уходить в публичный реестр при промахе), а полное перенаправление хостов делает `--registry-map original.registry=new.registry`. Это снимает необходимость править каждый Dockerfile.
4.  **Сетевая доступность:** runner и поды Kaniko должны иметь сетевой доступ к реестру. В Kubernetes это обеспечивается через `NetworkPolicy` и DNS-конфигурацию.

### Совместимость с Dockerfile

Kaniko поддерживает ~95% инструкций Dockerfile. По состоянию на 1.28.x уточнения:

-   `RUN --mount=type=bind|cache|secret` — **поддерживается** (флаг `FF_KANIKO_RUN_MOUNT_BIND`, по умолчанию `true`; будет объявлен устаревшим в 1.29, но остаётся как основной путь). Cross-stage `type=bind,from=<stage>` пока не поддерживается.
-   `RUN --network=host` и `--security=insecure` — **не поддерживаются**.
-   Секреты передаются флагом `--secret id=NAME,env=VAR` / `--secret id=NAME,src=/path` (в Dockerfile — `RUN --mount=type=secret,id=NAME,required=true`). ⚠️ Важно: **секрет не хранится изолированно в течение сборки** — сторонние `RUN`-команды могут его прочитать, секрет лишь не попадает в финальный образ. На недоверенные Dockerfile реальные секреты так передавать нельзя.
-   Multi-arch: `--custom-platform` собирает для иной платформы **последовательно** и без эмуляции (не удастся собрать arm64 на amd64-хосте, если нет нативной поддержки); билд не такой плоский, как у BuildKit, но без `--privileged`.

### Наблюдаемость сборки

Из-за «чёрного ящика» диагностика ложится на центральный шаблон — добавьте в него:

-   `--log-format=json` — структурированные логи, пригодные для автопарсинга и централизованного сбора (переменная `KANIKO_LOG_FORMAT` в шаблоне).
-   `--digest-file /kaniko/digest.txt` + `artifacts` — после сборки в артефактах лежит SHA256 digest образа; его используют сканирование, подпись и деплой по digest (`kubectl set image ... image@<digest>`), а не по тегу.
-   `--dryrun` — «план» сборки без выполнения: быстрая проверка, что шаблон корректен.
-   Телеметрия OTel (`KANIKO_TELEMETRY_ENDPOINT`) — **отключена по умолчанию** и направляет трейсы сборки во внешний коллектор; включать только осознанно и с заголовками аутентификации. Для корпоративного шаблона стоит запретить её включение, если трейсы уходят за периметр.

## Предварительные условия

Для успешного внедрения абстрагированного шаблона необходимо:

- **GitLab Runner:** настроенный с Docker или Kubernetes исполнителем, **без** `privileged: true`. Для Kubernetes-исполнителя рекомендуется выделить отдельный node pool для задач сборки, чтобы изолировать их от production-нагрузки, и отдельный неймспейс с PSS `baseline`.
- **Права доступа:** проект должен иметь права на запись в `Container Registry` (роль `Developer` или выше). При использовании внешних реестров (Harbor, Nexus) — protected-переменная `DOCKER_AUTH_CONFIG` или env-содержащие переменные для credential helper `env`.
- **Версии GitLab:** `id_tokens` (OIDC) доступны с 15.7 (глобально через `default:` — с 16.4); полная поддержка `spec:inputs` и CI/CD Catalog — с 16.11 (текущая ветка — 19.x). Для шаблона на базе `extends` достаточно 15.7+.
- **Сетевой доступ:** runner должен иметь доступ к реестру образов. В Kubernetes это обеспечивается через `NetworkPolicy`. Если Dockerfile содержит `FROM` с внешних реестров (Docker Hub), необходим доступ и к ним, либо корпоративный `--registry-mirror`.
- **Образ Kaniko:** актуальный форк `ghcr.io/osscontainertools/kaniko:v1.28.5` (либо `-debug` для отладки). Образы Google (`gcr.io/kaniko-project/*`) и Docker Hub-теги архивированной ветки не получают обновлений безопасности.
- **Сериализация сборок:** если кэш общий, добавьте в задачу `resource_group` для исключения гонки на запись в `cache-repo`.

### Рекомендуемый стек версий

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| GitLab | 16.0 | 19.x |
| GitLab Runner | 15.0 | 17.x+ |
| Kaniko (форк) | v1.28.0 | v1.28.5+ |
| Kubernetes (если используется) | 1.28 | 1.35+ |
| Pod Security Standards | `baseline` | `baseline` + NetworkPolicy |

## Практические сценарии

### Сценарий 1: Эталонный абстрагированный шаблон

Логика Kaniko полностью скрыта. Аутентификация в GitLab Registry выполняется встроенным credential helper `gitlab` — в `before_script` не утекают ни пароли, ни `config.json`. `CONTEXT` и путь к Dockerfile в шаблоне нормализуются (префикс `dir://` обязателен).

```yaml
# ci-templates/templates/docker-build.yml
.docker-build-base:
  stage: build
  image:
    # Актуальный форк сообщества; ghcr.io — основной реестр публикации
    name: ghcr.io/osscontainertools/kaniko:v1.28.5-debug
    entrypoint: [""]
  variables:
    DOCKERFILE: "Dockerfile"
    CONTEXT: "$CI_PROJECT_DIR"
    DESTINATION: "$CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG"
    CACHE_TTL: "336h"                 # дефолт Kaniko — две недели
    KANIKO_LOG_FORMAT: "text"         # "json" для централизованного сбора логов
  before_script:
    # Аутентификация скрыта: credential helper 'gitlab' в Kaniko
    # читает CI_REGISTRY / CI_REGISTRY_USER / CI_REGISTRY_PASSWORD.
    - |
      # Добавление корпоративного CA для приватных реестров (если задан)
      if [ -f "$INTERNAL_CA_PEM" ]; then
        cp "$INTERNAL_CA_PEM" /kaniko/ssl/certs/ca-certificates.crt
      fi
  script:
    - /kaniko/executor \
        --context "dir://$CONTEXT" \
        --dockerfile "$CONTEXT/$DOCKERFILE" \
        --destination "$DESTINATION" \
        --credential-helpers gitlab \
        --cache=true \
        --cache-repo="$CI_REGISTRY_IMAGE/cache" \
        --cache-copy-layers=true \
        --cache-ttl="$CACHE_TTL" \
        --digest-file=/kaniko/digest.txt \
        --push-retry=3 \
        --log-format="$KANIKO_LOG_FORMAT" \
        $EXTRA_ARGS
  artifacts:
    paths:
      - /kaniko/digest.txt
  # Сериализация записи в общий кэш
  resource_group: docker-build
```

> **Почему так:** `--context "dir://$CONTEXT"` обязателен — без префикса `dir://` Kaniko завершится с `unknown build context prefix provided`. `CONTEXT` остается интерфейсной переменной (проект может указать поддиректорию), а нормализация пути скрыта в шаблоне.

### Сценарий 2: Использование в микросервисе

Разработчик подключает шаблон и передает только те параметры, которые специфичны для его приложения.

```yaml
# my-app/.gitlab-ci.yml
include:
  - project: 'shared/ci-templates'
    file: 'templates/docker-build.yml'
    ref: 'v2.1.0'

build-backend:
  extends: .docker-build-base
  variables:
    DOCKERFILE: "deploy/backend.Dockerfile"
    DESTINATION: "$CI_REGISTRY_IMAGE/backend:$CI_COMMIT_TAG"
    EXTRA_ARGS: "--target production --build-arg VERSION=$CI_COMMIT_TAG"
  rules:
    - if: $CI_COMMIT_TAG
```

Потребитель не видит флагов аутентификации, кэширования и `dir://` — это интерфейс абстракции.

### Сценарий 3: Внешние реестры (Harbor, Nexus, Docker Hub)

Для авторизации во внешнем реестре администратор кладет base64-конфигурацию в **защищенную** переменную проекта/группы `DOCKER_AUTH_CONFIG`. Kaniko даёт ей приоритет над `config.json`, проекты не видят и не умеют её менять.

```yaml
# Групповая переменная (Settings -> CI/CD -> Variables):
# DOCKER_AUTH_CONFIG (Protected, Masked):
# {"auths":{"harbor.internal.example.com":{"auth":"<base64 user:password>",
#           "harbor.internal.example.com/team-a":{"auth":"<base64 robot:token>"}}}}
```

Сборка использует тот же шаблон без изменений — реестр внешний, но логика скрыта:

```yaml
# my-app/.gitlab-ci.yml
build-external:
  extends: .docker-build-base
  variables:
    DESTINATION: "harbor.internal.example.com/team-b/my-app:$CI_COMMIT_SHA"
```

Для случаев, когда `DOCKER_AUTH_CONFIG` неудобен (например, разные роботы на общем хосте), допустим встроенный helper `env` — переменные вида `KANIKO_HARBOR_INTERNAL_EXAMPLE_COM_USER` / `KANIKO_HARBOR_INTERNAL_EXAMPLE_COM_PASSWORD`. С 1.28.4 записи `auths` можно задавать path-scoped (по подпути), покрывая целую организацию одной записью.

Если доступ к GitLab Registry нужен одновременно с внешним — перечислите helpers подряд: `--credential-helpers gitlab,env`.

### Сценарий 4: Многостадийная сборка с кастомизацией стадий

Абстрагированный шаблон поддерживает multi-stage Dockerfile. Разработчик указывает целевую стадию через `EXTRA_ARGS`; с 1.28.x флаг `--target` принимает несколько стадий (первая в списке будет запушена).

```yaml
# my-app/.gitlab-ci.yml
build-frontend:
  extends: .docker-build-base
  variables:
    DOCKERFILE: "Dockerfile"
    DESTINATION: "$CI_REGISTRY_IMAGE/frontend:$CI_COMMIT_TAG"
    EXTRA_ARGS: "--target frontend --build-arg NODE_ENV=production"
  rules:
    - if: $CI_COMMIT_TAG

build-backend:
  extends: .docker-build-base
  variables:
    DOCKERFILE: "Dockerfile"
    DESTINATION: "$CI_REGISTRY_IMAGE/backend:$CI_COMMIT_TAG"
    EXTRA_ARGS: "--target backend --build-arg VERSION=$CI_COMMIT_TAG"
  rules:
    - if: $CI_COMMIT_TAG
```

### Сценарий 5: Сканирование безопасности (Trivy) по digest

Сканировать собранный образ **внутри образа Kaniko нельзя** — его там нет. Правильная схема: задание сборки отдает артефакт `digest.txt`, а отдельная задача в `test` сканирует образ из реестра по digest. Так «чёрный ящик» не мешает аудиту, а проверка не зависит от инструментов внутри образа сборки.

```yaml
# ci-templates/templates/docker-scan.yml
scan-image:
  stage: test
  image:
    name: ghcr.io/aquasecurity/trivy:0.74.0
    entrypoint: [""]
  variables:
    TRIVY_SEVERITY: "HIGH,CRITICAL"
    TRIVY_EXIT_CODE: "1"
  script:
    - |
      DIGEST=$(cat /kaniko/digest.txt 2>/dev/null || echo "$CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG")
      trivy image --no-progress \
        --severity "$TRIVY_SEVERITY" \
        --exit-code "$TRIVY_EXIT_CODE" \
        --username gitlab-ci-token --password "$CI_JOB_TOKEN" \
        "$DIGEST"
  artifacts:
    when: always
    expire_in: 7 days
```

Digest забирается из артефактов предыдущего задания (`needs: build-image`). При переходе на Cosign (подпись) тот же `digest.txt` используется как вход для подписи.

### Сценарий 6: Ограниченная среда / зеркала реестров (Edge Case)

В изолированных средах (без прямого доступа к Docker Hub) шаблон направляет базовые образы в корпоративное зеркало, не меняя Dockerfile проектов:

```yaml
# Переопределение в шаблоне для air-gapped группы
.docker-build-base:
  variables:
    HUB_MIRROR: "mirror.monitoring.internal:5000/dockerhub"
  script:
    - /kaniko/executor \
        --context "dir://$CONTEXT" \
        --dockerfile "$CONTEXT/$DOCKERFILE" \
        --destination "$DESTINATION" \
        --registry-mirror "$HUB_MIRROR" \
        --skip-default-registry-fallback \
        --cache=true --cache-repo="$CI_REGISTRY_IMAGE/cache" \
        --cache-ttl="$CACHE_TTL" \
        $EXTRA_ARGS
```

`--skip-default-registry-fallback` запрещает утечку трафика в публичный `docker.io` при промахе зеркала. Для полного переопределения отдельных хостов используется `--registry-map original.example.com=mirror.example.com` (repeatable).

### Сценарий 7: Debug-образ для отладки проблемной сборки

При ошибках в Dockerfile переключение на debug-образ (с развитым shell) позволяет исследовать среду сборки. Используйте `$CI_PROJECT_DIR` — в GitLab Runner это не `/workspace`.

```yaml
# Временное отладочное задание (добавить в .gitlab-ci.yml проекта)
build-debug:
  extends: .docker-build-base
  variables:
    EXTRA_ARGS: "--verbosity=debug --log-timestamp=true --no-push"
  before_script:
    - echo "=== DEBUG: workspace ==="
    - ls -la "$CI_PROJECT_DIR/"
    - cat "$CI_PROJECT_DIR/$DOCKERFILE"
    - echo "=== DEBUG: registry reachability ==="
    - |
      CODE=$(wget -qO- --timeout=5 "https://$CI_REGISTRY/v2/" >/dev/null 2>&1; echo $?)
      echo "registry probe exit=$CODE (401 считается нормой: требуется токен)"
  allow_failure: true
```

## Валидация

Для проверки корректности работы абстрагированного пайплайна:

1.  **Логи Kaniko:** убедитесь, что в выводе задачи есть `Pushing image to <dest>` и `Pushed <digest>`, нет `401 Unauthorized` и `unknown build context prefix provided`.
2.  **Аутентификация:** без ручной генерации `config.json` сборка в GitLab Registry не должна требовать паролей. Проверьте, что лог содержит `credential providers by priority: [..., gitlab]`.
3.  **Кэширование:** при повторной сборке без изменений в логах ожидается `Using caching version of cmd:` для `RUN`-команд (для `COPY` — только при `--cache-copy-layers=true`), а не `No cached layer found for cmd`.
4.  **Артефакт digest:** убедитесь, что после сборки в артефактах есть `/kaniko/digest.txt` с корректным `sha256:...`.
5.  **Привилегии:** задача не должна требовать `privileged: true` в настройках раннера. Для debug-образа команда `id` вернёт `uid=0` — это ожидаемо: Kaniko распаковывает образ в корень своего контейнера; важно отсутствие `privileged`, а не не-root пользователя.
6.  **Синтаксис без сборки:** для быстрой проверки шаблона можно выполнить `--dryrun` (план сборки) — он не запускает команды и не пушит образ.

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unknown build context prefix provided … use gs://, dir://, tar://, s3://, git://, https://` | `--context` без обязательного префикса. | Используйте `dir://` в шаблоне: `--context "dir://$CI_PROJECT_DIR"`. |
| `error checking push permissions` / `401 Unauthorized` | Неверные credentials; `DOCKER_AUTH_CONFIG` «затеняет» `config.json`; истёк `CI_JOB_TOKEN` (живёт только в рамках пайплайна). | Проверьте роль проекта (`Developer`+ на Registry), используйте `--credential-helpers gitlab`, при гонке источников — удалите лишний. **Сетевого фолбэка между credentials нет.** |
| `Out of memory (OOM)` | Слишком большие слои или много стадий сборки. | Увеличьте `resources:limits` в настройках Kubernetes-раннера; для базовых образов Alpine рекомендуется минимум 1Gi памяти. |
| `error resolving …` / `TLS handshake timeout` | Проблема с DNS, прокси или сертификатом реестра. | Проверьте `dnsConfig` подов раннера; корпоративный CA добавьте через `--registry-certificate <host>=/path/ca.crt` или `$INTERNAL_CA_PEM`; проверьте MTU. |
| `failed to extract layer: … file exists` | Конфликт системных путей Kaniko с файлами образа. | Не выполняйте `COPY`/`ADD` в `/kaniko` и `/busybox*`; для переноса рабочего каталога используйте `KANIKO_DIR`. |
| `UNAUTHORIZED` при пуше | Истёк токен или неверный registry. | `CI_JOB_TOKEN` действует только в текущем пайплайне; проверьте, что `$CI_REGISTRY` указывает на нужный реестр. |
| Кэш не используется | `--cache-copy-layers=false` (слои `COPY` не кэшируются); TTL истёк; `cache-repo` недоступен; промах в начале стадии. | Включите `--cache-copy-layers=true`; TTL по умолчанию 336h; поместите изменяемые `COPY` ниже стабильных команд; убедитесь в доступности `cache-repo`. |
| `no space left on device` | Переполнение writable layer контейнера Kaniko. | Добавьте `--cleanup` (или `KANIKO_CLEANUP=true`) в конце; объединяйте `RUN`, используйте multi-stage; чистите кэш пакетного менеджера в каждом `RUN`. |
| `main.img … read-only file system` | Writable слой смонтирован read-only (например, герметичный раннер). | Проверьте, что контейнер имеет записываемый корневой слой; task не должна исполняться в read-only pod. |
| Медленные push/pull при работе с GitLab Registry | Производительность HTTP/2 при работе с GitLab Registry заметно ниже HTTP/1.1. | Установите переменную `FF_KANIKO_DISABLE_HTTP2=true` (эффект тот же, что у `GODEBUG="http2client=0"`), чтобы принудительно перейти на HTTP/1.1. |
| Сборка «зависает» / не завершается | Kaniko работает как PID 1 и не собирает зомби-процессы: короткоживущие child-процессы из `RUN` могут подвесить сборку. | Включите `FF_KANIKO_RUN_VIA_TINI=true` — `RUN` будет исполняться через `tini` (subreaper), но только при наличии `/kaniko/tini` в образе; в v1.29.0 станет значением по умолчанию. |

## Преимущества и недостатки подхода

| Характеристика | Описание |
| :--- | :--- |
| **Безопасность** | Сборка без `--privileged` и docker socket; на Kubernetes — PSS `baseline` + `NetworkPolicy`. |
| **Инфраструктурная мобильность** | Замена инструмента сборки (Kaniko → Buildah → BuildKit) без правок в проектах. |
| **Централизация** | Единая точка управления аутентификацией, кэшированием, зеркалами, сканированием. |
| **Снижение TCO** | Устранение дублирования конфигурации, автоматизация обновлений. |
| **Скрытая сложность (Минус)** | «Чёрный ящик»: разработчик не видит, как именно собирается образ, что затрудняет отладку без центральной площадки. |
| **Ограниченная совместимость (Минус)** | Kaniko поддерживает ~95% инструкций Dockerfile; `--network host` и `--security insecure` не работают; multi-arch собирается последовательно. |
| **Модель прав (Минус)** | Стоковый образ исполняется с UID 0 — профиль `restricted` PSS недостижим без пересборки образа; требуется отдельный неймспейс сборки. |
| **Зависимость от реестра (Минус)** | Кэширование требует доступа к Registry; при его недоступности кэш не работает, время сборки увеличивается. |
| **Стоимость хранения (Минус)** | Кэшированные слои хранятся в Registry и увеличивают потребление диска. Требуется настройка политик очистки. |

## Лучшие практики и очистка

**Эксплуатация:**

1.  **Пиньте версии образов** (`ghcr.io/osscontainertools/kaniko:v1.28.5`, `ghcr.io/aquasecurity/trivy:0.74.0`), а не `latest`; версию обновляет только владелец шаблона.
2.  **Кэш:** `--cache-copy-layers=true`, отдельный `cache-repo`, `resource_group` для сериализации, TTL исходя из частоты сборок.
3.  **Деплой по digest:** используйте артефакт `digest.txt` (`kubectl set image deploy/app app=<image>@<digest>`), а не перезапись тега — воспроизводимость и быстрый откат.
4.  **Секреты сборки:** `--secret id=NAME,env=VAR` вместо `ARG`; помните, что секрет не изолирован внутри сборки — не доверяйте его непроверенным Dockerfile.
5.  **Не отключайте проверки TLS** (`--skip-tls-verify`) в production-шаблоне; реестры с self-signed сертификатами обслуживайте через `--registry-certificate` и корпоративный CA.
6.  **Логи:** по умолчанию `--log-format=json` для аудита; `--verbosity` повышать только при отладке.
7.  **Телеметрия:** `KANIKO_TELEMETRY_*` выключена по умолчанию; включайте только в свой OTLP-коллектор и с аутентификацией.

**Откат (rollback) шаблона:**
- Шаблон в репозитории шаблонов версионируется тегом/`ref`; откат = переключение `ref` с `v2.1.0` на `v2.0.9` в файле `include` (или обновление одной строки в проектах). Ролл-аут новых ревизий выполняйте частями (пилотный проект → группа → весь инстанс), отслеживая статус пайплайнов.
- Для дистрибуции без правки проектов применяйте pipeline-wide defaults / `variables` уровня группы, чтобы сменить дефолтную ревизию централизованно.

**Очистка:**
- В Kaniko: `--cleanup` (или `KANIKO_CLEANUP=true`) убирает рабочую ФС в конце сборки; `--pre-cleanup` — перед началом.
- В реестре: политики удаления неиспользуемых тегов; для `cache-repo` — отдельный namespace и регулярная GC (Harbor `Garbage Collection`, GitLab `Package Registry cleanup`).

## Дополнительная информация

- **Предыдущий этап:** [Гибкость с extends](./evolution_extends.md) — наследование и кастомизация конфигурации.
- **Следующий этап:** [CI/CD Components](./evolution_components.md) — переход к типизированным интерфейсам и каталогу компонентов.
- **Техническая справка по Kanniko:** [Руководство по Kaniko](../../../../Docker/Dockerfile/dockerfile_kaniko.md) — глубокое погружение в параметры исполнителя, архитектуру и сравнение с альтернативами.
- **Альтернатива сборки:** [BuildKit: современная замена Kaniko](../../../../Docker/Dockerfile/dockerfile_buildkit.md) — флаги `--mount`, аттестации (SBOM), параллельный multi-arch.
- **Безопасность:** [Docker-in-Docker: Запуск в контейнере](../../../../Docker/docker-in-docker.md) — анализ рисков DinD, DooD и Kaniko, сравнение векторов атаки.
- **Обзор эволюции:** [Эволюция переиспользуемого пайплайна](../evolution_example.md) — контекст всех этапов зрелости CI/CD.
- **Практические примеры:** [Обзор механизмов переиспользования](../overview.md) — сравнение `extends`, `include`, `components`.
- **Безопасность образов:** [Обзор DevSecOps](../../../DevSecOps/devsecops_overview.md) и [Цепочка поставок контейнерных образов](../../../../Security/Supply_Chain_Security/container_image_supply_chain.md) — сканирование, подпись (Cosign), digest-pinning.
- **Container Registry:** [Container Registry administration](../../Advanced/container_registry.md) — cleanup policies, garbage collection, vulnerability scanning.
- **Сканирование безопасности:** [Сканирование безопасности в GitLab CI](../../Concepts/gitlab_ci_security_scanning.md) — SAST, DAST, Secret Detection, Dependency Scanning.
- **Compliance:** [Compliance и Audit в GitLab CI](../../Advanced/compliance_and_audit.md) — Pipeline Execution Policies, protected environments.
- **Окружения и деплой:** [Окружения и развертывания](../../Concepts/environments_and_deployments.md) — protected environments, approvals, deployments tracking.
- **Release management:** [Управление релизами и SemVer](../../Advanced/release_management_and_semver.md) — GitLab Releases, SBOM, changelogs.