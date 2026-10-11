# Container Registry Management в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

> **Примечание:** Полная теория Container Registry, image scanning и lifecycle policies описана в **[Container Registry в GitLab](../Advanced/container_registry.md)**. Это руководство фокусируется на практическом управлении registry в production среде.

## Определения

- **Container Registry** — встроенное в GitLab хранилище Docker-образов, тесно интегрированное с пайплайнами и проектами.
- **Package Registry** — универсальное хранилище пакетов (npm, Maven, PyPI, NuGet, Conan, Debian, Helm), альтернативное Container Registry для артефактов не-Docker-форматов.
- **Dependency Proxy** — кэширующий прокси для Docker Hub и других публичных реестров, ускоряющий сборки и снижающий внешний трафик.
- **Registry Cleanup Policy** — автоматическая политика удаления тегов и manifests по критериям (время, количество, регулярные выражения).
- **Immutable Tag** — тег, который нельзя перезаписать. Обеспечивает воспроизводимость сборок и безопасность цепочки поставок.
- **Image Promotion** — процесс переноса образа из одной среды в другую (staging → production) без пересборки, обычно через retagging.
- **SBOM (Software Bill of Materials)** — декларативный список зависимостей образа, генерируемый сканерами (Trivy, Syft) и сохраняемый как артефакт.
- **Image Scanning** — статический анализ Docker-образа на уязвимости (CVE), выполняется через `artifacts:reports:cyclonedx` или отдельные задачи.
- **Garbage Collection (GC)** — фоновая задача, удаляющая неиспользуемые manifests и слои из storage backend.
- **Protected Tag** — тег, защищённый от перезаписи и удаления через правила защиты GitLab.
- **Deploy Token / Project Access Token / CI_JOB_TOKEN** — механизмы аутентификации для доступа к Registry из CI/CD и внешних систем.

## Основные концепции

### Архитектура Container Registry

Container Registry встроен в GitLab и работает как отдельный сервис:

1. **Хранилище (Storage)**: Образы хранятся в объектном хранилище или на локальном диске. Для production рекомендуется отдельный bucket/prefix для Registry, не смешанный с Git data.
2. **Аутентификация (Auth)**: GitLab выставляет JWT-токены для доступа к Registry. `CI_JOB_TOKEN` автоматически авторизует задачи пайплайна в рамках проекта. Для внешних клиентов используются Deploy Tokens или Project Access Tokens.
3. **Версионирование (Tagging)**: Каждый тег — это immutable pointer на manifest образа. Registry поддерживает семантическое версионирование и SHA-подобные теги.
4. **Гарбеж-коллекция (Garbage Collection)**: Фоновая задача удаляет неиспользуемые manifests и слои. Настраивается через `registry[garbage_collection]` в `gitlab.rb`. GC требует lock и не должна выполняться во время активных пайплайнов.
5. **Доступность**: Registry может быть развернут как отдельный инстанс или внешний реестр (Harbor, Nexus) для heavy production workloads.

### Предопределённые переменные Registry

GitLab автоматически предоставляет переменные для доступа к Container Registry:

| Переменная | Описание |
| :--- | :--- |
| `CI_REGISTRY` | URL Registry (например, `registry.gitlab.com`) |
| `CI_REGISTRY_USER` | Имя пользователя для docker login (`gitlab-ci-token`) |
| `CI_REGISTRY_PASSWORD` | Пароль (`CI_JOB_TOKEN`) |
| `CI_REGISTRY_IMAGE` | Полный путь к образу проекта (`registry.example.com/group/project`) |
| `CI_REGISTRY_TAG` | Тег образа (если используется переменная `TAG`) |

### Интеграция с Dependency Proxy

Dependency Proxy кэширует слои из Docker Hub и других публичных реестров:

- **Преимущество**: Снижение времени сборки и трафика, особенно для популярных базовых образов (`python:3.12`, `node:20`).
- **Ограничение**: Кэширует только pulls, не pushes. Не подходит для частных образов.
- **Настройка**: Включить в Admin Area → Packages → Dependency Proxy.

### Registry Cleanup Policies

Автоматическая очистка предотвращает бесконтрольный рост Registry:

- **Критерии**: Время создания, количество тегов, регулярные выражения для имен тегов.
- **Политика**: `keep_n` (сохранить N последних), `older_than` (удалить старше X дней), `regex` (сохранить совпадающие с regex).
- **Режим**: `dry_run` для тестирования перед реальным удалением.

### RBAC и токены доступа

| Роль | Права в Registry |
| :--- | :--- |
| **Guest** | Pull из публичных проектов |
| **Reporter** | Pull |
| **Developer** | Push, pull, delete tags |
| **Maintainer** | Push, pull, delete tags, manage cleanup policies |
| **Owner** | Полный доступ, настройка Registry visibility |

Для внешних систем и automation используйте Deploy Tokens или Project Access Tokens с минимально необходимыми scopes (`read_registry`, `write_registry`, `delete_registry`).

## Предварительные требования

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Container Registry (базовый) | 8.0+ | Включен по умолчанию в Omnibus |
| `CI_REGISTRY` переменные | 8.0+ | Автоматически предоставляются |
| `CI_JOB_TOKEN` для Registry | 11.3+ | Авторизация без явного токена |
| Dependency Proxy | 13.8+ | Требует настройки в Admin Area |
| Registry Cleanup Policies | 13.9+ | Настраивается в UI проекта |
| Immutable Tags | 13.10+ | Защита от перезаписи тегов |
| `artifacts:reports:cyclonedx` | 12.7+ | SBOM-отчеты для сканирования |
| Package Registry (npm/Maven/PyPI) | 13.9+ | Универсальное хранилище пакетов |
| Helm Chart Registry | 13.12+ | Хранилище Helm-чартов |
| Bulk tag delete API | 16.4+ | Удаление тегов по regex и older_than |

### Необходимые знания

- Docker: образы, слои, теги, Dockerfile, multi-stage builds
- GitLab CI/CD Variables: предопределённые переменные (`CI_REGISTRY`, `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD`)
- GitLab RBAC: роли и права на запись в Registry
- Основы безопасности цепочки поставок (Supply Chain Security)
- Знание инструментов сканирования (Trivy, Grype) и подписи (Cosign)

### Роли и зоны ответственности

| Роль | Ответственность |
| :--- | :--- |
| **Dev** | Сборка образов, тегирование, базовый push, локальное тестирование |
| **DevOps / SRE** | Registry policies, cleanup, мониторинг, image promotion,灾备 восстановление |
| **Sysadmin** | `gitlab.rb` конфигурация, storage backend, garbage collection, сетевой контроль, backup |
| **Security** | Image scanning, SBOM, подпись образов, immutable tags, audit logging |

### Инструменты диагностики

- **Registry API**: `GET /projects/:id/registry/repositories` — список репозиториев
- **Registry API**: `GET /projects/:id/registry/repositories/:id/tags` — список тегов
- **Registry API**: `GET /projects/:id/registry/repositories/cleanup_policies` — статус cleanup policy
- **Registry API**: `GET /projects/:id/registry/garbage_collection` — статус GC
- **`gitlab-ctl`**: Управление встроенным Registry в Omnibus
- **`skopeo`**: Инспектирование и копирование образов между реестрами (локальный инструмент)
- **`trivy` / `grype`**: Сканирование образов на уязвимости
- **`cosign`**: Подпись и верификация образов
- **`glab`**: GitLab CLI для automation через API

## Практические сценарии

### Сценарий 1: Build и Push с многоархитектурной поддержкой

```yaml
stages:
  - build
  - deploy

build-multiarch:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2376
    DOCKER_TLS_CERTDIR: /certs
    IMAGE_TAG: $CI_COMMIT_SHORT_SHA
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker buildx create --name multiarch-builder --use || true
    - docker buildx inspect --bootstrap || true
  script:
    - |
      docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --file Dockerfile \
        --tag $CI_REGISTRY_IMAGE:$IMAGE_TAG \
        --tag $CI_REGISTRY_IMAGE:latest \
        --push \
        .
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$IMAGE_TAG \
        --set image.registry=$CI_REGISTRY \
        --set image.repository=$CI_REGISTRY_IMAGE
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 2: Lifecycle Policies через API

```bash
# Создание cleanup policy через GitLab API
# → Ожидается: JSON с полями name, enabled, rules
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories/cleanup_policies" \
  --data '{
    "name": "cleanup-old-images",
    "description": "Remove images older than 30 days",
    "enabled": true,
    "rules": [
      {
        "description": "Keep latest 10 tags",
        "keep_n": 10,
        "older_than": "30d",
        "regex": ".*"
      },
      {
        "description": "Keep production tags",
        "keep_n": 5,
        "older_than": "90d",
        "regex": "^v\\d+\\.\\d+\\.\\d+$"
      }
    ]
  }'
```

### Сценарий 3: Image Scanning в CI/CD

```yaml
stages:
  - build
  - security
  - deploy

build:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

container_scanning:
  stage: security
  image: aquasec/trivy:0.74.0
  script:
    - trivy image --format json --output report.json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  artifacts:
    reports:
      container_scanning: report.json
    expire_in: 30 days
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

> **Примечание:** В марте 2026 года в тегах `latest` и `0.69.4` образа `aquasec/trivy` была зафиксирована компрометация supply chain. Для production всегда фиксируйте версию сканера, проверяйте digest и используйте image signature verification.

### Сценарий 4: Image Signing и Verification (GitLab 18.3+)

```yaml
stages:
  - build
  - sign
  - deploy

build:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

sign:
  stage: sign
  image: gcr.io/projectsigstore/cosign:v2.4.0
  script:
    - echo "$COSIGN_KEY" > /tmp/cosign.key
    - cosign sign --key /tmp/cosign.key --yes $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false

verify-and-deploy:
  stage: deploy
  image: bitnami/kubectl:1.36
  script:
    - |
      cosign verify \
        --key /tmp/cosign.pub \
        $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA \
        --set image.signature.verify=true
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 5: Proxy Cache для Docker Hub (Instance-level)

Настройка Registry-level proxy cache выполняется в `gitlab.rb` на уровне инстанса:

```ruby
registry_nginx['proxy_cache_use_temp_path'] = 'off'
registry_nginx['proxy_cache_path'] = 'registry-cache levels=1:2 keys_zone=registry-cache:10m max_size=10g inactive=60m use_temp_path=off'
registry_nginx['proxy_cache'] = 'registry-cache'
```

После применения конфигурации (`gitlab-ctl reconfigure`) кэш работает на уровне Registry и не требует изменений в пайплайне. Pull из Docker Hub будет кэшироваться для всех проектов.

Для кэширования pulls на уровне Runner'ов используйте **Dependency Proxy** (Admin Area → Packages → Dependency Proxy).

## Валидация и проверка

1. **Registry UI:** Проверьте **Packages & Registries > Container Registry** — должны отображаться все образы
2. **Image pull:** Выполните `docker pull $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA` — должен работать
3. **Lifecycle Policy:** Проверьте статус cleanup policy через API
4. **Image Scanning:** Проверьте **Security & Compliance > Container Scanning** — должны отображаться уязвимости
5. **Signing:** Проверьте подпись образа через `cosign verify`

### Проверка Registry через API

```bash
# Список репозиториев
# → Ожидается: JSON-массив с объектами {id, name, path, ...}
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories" | \
  jq '.[] | {id, name, path}'

# Список тегов конкретного образа
# → Ожидается: JSON-массив с объектами {name, created_at, total_size, ...}
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories/$REPO_ID/tags" | \
  jq '.[] | {name, created_at, total_size}'
```

### Проверка cleanup policies и GC

```bash
# Проверка статуса GC
# → Ожидается: {"status":"finished"} или {"status":"running"}
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/garbage_collection" | jq

# Проверка cleanup policy
# → Ожидается: JSON-объект с keep_n, older_than, name_regex
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories/cleanup_policies" | jq
```

### Проверка доступности Registry из Runner

```bash
# Проверка доступности Registry API
# → Ожидается: HTTP 200 OK или 401/403 (если анонимный доступ закрыт)
curl -I https://registry.gitlab.example.com/v2/

# Проверка аутентификации через CI_JOB_TOKEN
# → Ожидается: HTTP 200 OK, login успешен
echo $CI_REGISTRY_PASSWORD | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin
```

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Push failed** | Неверные credentials или registry не доступен | Проверьте `CI_REGISTRY_USER` и `CI_REGISTRY_PASSWORD` |
| **Pull failed** | Образ не найден или нет прав | Проверьте тег и права доступа к registry |
| **Scan not running** | Container Scanning не включен | Включите Container Scanning в **Settings > Security & Compliance** |
| **Lifecycle policy not working** | Policy неактивна или неверные правила | Проверьте статус policy и синтаксис правил |
| **Image too large** | Неоптимизированный Dockerfile | Используйте multi-stage builds и `.dockerignore` |
| **Signing failed** | Неверный ключ или Cosign не установлен | Проверьте ключ и установите Cosign |
| **GC зависает** | Нет lock или нехватка диска | Остановите job, освободите диск, перезапустите GC |
| **`manifest unknown`** | Тег удален cleanup policy или не существует | Проверьте список тегов через API |
| **`toomanyrequests`** | Rate limit Registry API | Увеличьте `registry[rate_limiter]` в `gitlab.rb` (self-managed) |
| **Proxy cache не работает** | Неправильная конфигурация Nginx или Registry | Проверьте `registry_nginx['proxy_cache']` и логи Registry |
| **Immutable tag overwrite** | Попытка push уже защищённого тега | Используйте уникальные теги (SHA) или защищённые имена тегов |

## Best Practices

### Безопасность

- Используйте Image Scanning для всех образов перед деплоем
- Включите Image Signing для production образов
- Ограничьте доступ к registry (RBAC)
- Используйте lifecycle policies для минимизации surface attack
- Никогда не храните секреты в образах
- Фиксируйте версии сканеров и инструментов (Trivy, Cosign) вместо тега `latest`
- Проверяйте digest образов при использовании базовых образов

### Производительность

- Используйте multi-stage builds для уменьшения размера образа
- Используйте `.dockerignore` для исключения ненужных файлов
- Используйте layer caching для ускорения сборки
- Используйте Dependency Proxy для внешних образов
- Используйте digest вместо тега для production деплоев
- Ограничьте размер manifests и artifacts (SBOM > 5 MB сохраняйте как артефакт)

### Надёжность (SRE / Sysadmin)

- Настройте nightly Garbage Collection через `registry[garbage_collection]` в `gitlab.rb`
- Используйте semantic versioning для тегов
- Настройте Registry Cleanup Policy по умолчанию на уровне группы: `keep_n: 10`, `older_than: 30d`
- Настройте мониторинг Registry метрик: `registry_http_requests_total`, `registry_storage_operations_total`, `registry_garbage_collection_*`
- Мониторьте очередь Sidekiq `registry` на аномальную активность
- Используйте отдельный storage backend для Registry, не смешанный с Git data
- Настройте NetworkPolicy для runner'ов: разрешайте только egress к Registry API (порт 443)
- Для air-gapped сред используйте внутренний Registry Mirror
- Настройте backup для Registry storage и metadata отдельно от `gitlab-backup create`
- Тестируйте восстановление Registry из backup не реже квартала

### Управление инстансом (Sysadmin)

- **Конфигурация `gitlab.rb` для Registry:**
  ```ruby
  registry['enable'] = true
  registry['host'] = 'registry.example.com'
  registry['port'] = 5000
  registry['listen_address'] = '0.0.0.0:5000'
  registry['storage'] = {
    # Настройте объектное хранилище или локальный диск
    # Пример: { 'filesystem' => { 'rootdirectory' => '/var/opt/gitlab/registry/storage' } }
  }
  registry['garbage_collection'] = {
    'enabled' => true,
    'schedule' => '0 2 * * *' # nightly
  }
  ```
- **TLS:** Настройте валидированный TLS сертификат для Registry endpoint
- **Log rotation:** Настройте log rotation для Registry логов в Omnibus
- **Rate limiting:** Настройте `registry[rate_limiter]` в `gitlab.rb` для защиты от burst-атак
- **Registry isolation:** Для production используйте отдельный Registry инстанс или внешний (Harbor, Nexus)

## Ограничения и крайние случаи

### Технические лимиты

| Параметр | Лимит | Примечание |
| :--- | :--- | :--- |
| Размер одного manifest | 5 МБ | Для больших SBOM используйте отдельные артефакты |
| Максимум тегов на репозиторий | Нет жесткого лимита | Ограничен хранилищем и GC политикой |
| Garbage Collection | Требует lock | Не запускайте GC во время активных пайплайнов |
| Запросов к Registry API | Rate limit зависит от плана | Self-managed: настраивается администратором |
| Размер слоя | Максимум 10 ГБ | Для очень больших образов используйте multi-stage |
| Время жизни токена доступа | Зависит от типа токена | `CI_JOB_TOKEN` живёт в рамках job |

### Несовместимость и ограничения

| Ограничение | Описание | Решение |
| :--- | :--- | :--- |
| `CI_JOB_TOKEN` только для GitLab Registry | Токен не работает с внешними реестрами | Используйте Deploy Token или Project Access Token |
| GC во время пайплайна | Удаление слоев, используемых активными задачами | Настройте GC на ночное время |
| Immutable Tags + Cleanup | Политика cleanup не удаляет immutable теги | Используйте regex для исключения защищённых тегов |
| SBOM размер > 5 МБ | Manifest Registry не примет большой SBOM | Сохраняйте SBOM как артефакт, а не в Registry metadata |
| Dependency Proxy + Private Registry | Прокси работает только с публичными реестрами | Для приватных образов настройте Registry Mirror |
| Kaniko + DinD в одном job | Конфликт Docker daemon | Используйте отдельные стадии для DinD и Kaniko |
| Registry в air-gapped среде | Нет доступа к Docker Hub | Используйте внутренний Registry Mirror |

### Особые сценарии

**Registry в air-gapped среде:**
```yaml
variables:
  CI_REGISTRY: registry.corp.internal
  DOCKER_HOST: tcp://docker:2375
```

**Fallback при недоступности Registry:**
```yaml
script:
  - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY || echo "Registry unavailable, using local cache"
  - docker build -t $IMAGE_TAG .
  - docker push $IMAGE_TAG || echo "Push failed, keeping image locally"
```

**Cross-project Registry access:**
- `CI_JOB_TOKEN` работает только в рамках проекта.
- Для cross-project access используйте Deploy Token с scope `read_registry`/`write_registry`.
- Project Access Token можно ограничить конкретным проектом.

**Registry при fork-проектах:**
- Fork не наследует Container Registry upstream-проекта.
- Если upstream использует protected runners, fork не получит доступ к upstream Registry credentials.
- Настройте отдельный Registry namespace для fork-проектов.

**Registry при миграции инстанса:**
- Registry manifests не мигрируют через `gitlab-backup create`.
- Требуется отдельный backup Registry storage и metadata.
- Восстановление: настройте новый Registry на том же storage и импортируйте metadata.

## Очистка

### Удаление устаревших тегов через API

```bash
# Bulk delete тегов старше 30 дней через GitLab API
# → Ожидается: успешный HTTP 204 No Content или 202 Accepted
curl --request DELETE \
  --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/repositories/$REPO_ID/tags" \
  --data-urlencode "name_regex=.*" \
  --data-urlencode "older_than=30d"
```

### Проверка статуса Garbage Collection

```bash
# Статус фоновой GC
# → Ожидается: {"status":"finished"} или {"status":"running"}
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/registry/garbage_collection" | jq
```

## Дополнительная информация

### Смотрите также

- **[Container Registry — полное руководство](../Advanced/container_registry.md)** — теория, все features
- **[Container Scanning](../Concepts/gitlab_ci_security_scanning.md)** — анализ образов на уязвимости
- **[Package Registry Administration](../Advanced/gitlab_package_registry_administration.md)** — управление пакетами
- **[Self-hosted installation](../Tutorials/self_hosted_installation.md)** — настройка Registry в Omnibus
- **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — защита Registry, сканирование, подпись
- **[Kubernetes Review Apps](../Tutorials/kubernetes_review_apps.md)** — управление временными образами в K8s
- **[Официальная документация: Container Registry](https://docs.gitlab.com/ee/user/packages/container_registry/)** — полное руководство
- **[Официальная документация: Container registry API](https://docs.gitlab.com/api/container_registry)** — REST API reference
