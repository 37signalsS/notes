# Container Registry в GitLab CI/CD

**Актуально для:** GitLab 18.0–19.4

## Определения

- **Container Registry** — встроенное в GitLab хранилище Docker-образов, тесно интегрированное с пайплайнами и проектами. Позволяет хранить, версионировать и доставлять образы без внешних реестров.
- **Package Registry** — универсальное хранилище пакетов (npm, Maven, PyPI, NuGet, Conan, Debian, Helm), альтернативное Container Registry для артефактов не-Docker-форматов.
- **Dependency Proxy** — кэширующий прокси для Docker Hub и других публичных реестров, ускоряющий сборки и снижающий внешний трафик.
- **Registry Cleanup Policy** — автоматическая политика удаления тегов и manifests по критериям (время, количество, регулярные выражения).
- **Immutable Tag** — тег, который нельзя перезаписать. Обеспечивает воспроизводимость сборок и безопасность цепочки поставок.
- **Image Promotion** — процесс переноса образа из одной среды в другую (staging → production) без пересборки, обычно через retagging.
- **SBOM (Software Bill of Materials)** — декларативный список зависимостей образа, генерируемый сканерами (Trivy, Syft) и сохраняемый как артефакт. Подробнее о стратегиях SBOM и Supply Chain Security см. в **[CI/CD Security Hardening](cicd_security_hardening.md)** и **[Управление релизами и SemVer](release_management_and_semver.md)**.
- **Image Scanning** — статический анализ Docker-образа на уязвимости (CVE), выполняется через `artifacts:reports:cyclonedx` или отдельные задачи.

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

### Необходимые знания

- Docker: образы, слои, теги, Dockerfile, multi-stage builds
- GitLab CI/CD Variables: предопределенные переменные (`CI_REGISTRY`, `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD`)
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

**Для кого:** DevOps-инженеры, проектирующие pipeline доставки контейнеров; SRE, настраивающие мониторинг и灾备 Registry; Sysadmin, управляющие self-managed инстансом и storage backend.

### Инструменты диагностики

- **Registry API**: `GET /projects/:id/registry/repositories` — список репозиториев
- **Registry API**: `GET /projects/:id/registry/repositories/:id/tags` — список тегов
- **`gitlab-ctl`**: Управление встроенным Registry в Omnibus
- **`skopeo`**: Инспектирование и копирование образов между реестрами
- **`trivy` / `grype`**: Сканирование образов на уязвимости
- **`cosign`**: Подпись и верификация образов

## Основные концепции

### Архитектура Container Registry

Container Registry встроен в GitLab и работает как отдельный сервис:

1. **Хранилище (Storage)**: Образы хранятся в объектном хранилище или на локальном диске. Рекомендуется отдельный bucket/prefix для каждого проекта.
2. **Аутентификация (Auth)**: GitLab выставляет JWT-токены для доступа к Registry. `CI_JOB_TOKEN` автоматически авторизует задачи пайплайна. Для внешних клиентов используются Deploy Tokens или Project Access Tokens.
3. **Версионирование (Tagging)**: Каждый тег — это immutable pointer на manifest образа. Registry поддерживает семантическое версионирование и SHA-подобные теги.
4. **Гарбеж-коллекция (Garbage Collection)**: Фоновая задача удаляет неиспользуемые manifests и слои. Настраивается через `registry[garbage_collection]` в `gitlab.rb`.

### Предопределенные переменные Registry

GitLab автоматически предоставляет переменные для доступа к Container Registry:

| Переменная | Описание |
| :--- | :--- |
| `CI_REGISTRY` | URL Registry (например, `registry.gitlab.com`) |
| `CI_REGISTRY_USER` | Имя пользователя для docker login (`gitlab-ci-token`) |
| `CI_REGISTRY_PASSWORD` | Пароль (`CI_JOB_TOKEN`) |
| `CI_REGISTRY_IMAGE` | Полный путь к образу проекта (`registry.example.com/group/project`) |
| `CI_REGISTRY_TAG` | Тег образа (если используется `TAG` переменная) |

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

## Практические сценарии

### Сценарий 1: Базовый сборка и push образа

Стандартный паттерн: сборка, тегирование, push в Registry с использованием встроенных переменных.

```yaml
build_image:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
    - docker tag $IMAGE_TAG $CI_REGISTRY_IMAGE:latest
    - docker push $CI_REGISTRY_IMAGE:latest
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 2: Сборка через Kaniko (без privileged)

Для сред с ограничениями безопасности (shared runners, restricted environments):

```yaml
build_image:
  stage: build
  image:
    name: kaniko-project/executor:latest
    # Используйте image из внутреннего реестра или Docker Hub вместо gcr.io
  variables:
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor --context $CI_PROJECT_DIR --dockerfile $CI_PROJECT_DIR/Dockerfile --destination $IMAGE_TAG --destination $CI_REGISTRY_IMAGE:latest
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 3: Multi-stage Dockerfile с кэшированием слоев

Использование `--cache-from` для ускорения повторных сборок:

```yaml
build_image:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker pull $CI_REGISTRY_IMAGE:latest || true
    - docker build --cache-from $CI_REGISTRY_IMAGE:latest -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
    - docker push $CI_REGISTRY_IMAGE:latest
  cache:
    key: docker-build
    paths:
      - .docker/
```

### Сценарий 5: Сканирование и SBOM для образов в Registry

Сканирование образов на уязвимости и генерация SBOM для хранения в Registry:

```yaml
scan_image:
  stage: test
  image: aquasec/trivy:latest
  variables:
    IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  script:
    - trivy image --format cyclonedx --output sbom.json $IMAGE_TAG
    - trivy image --severity HIGH,CRITICAL --exit-code 1 $IMAGE_TAG || true
  artifacts:
    reports:
      cyclonedx: sbom.json
    paths:
      - sbom.json
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

> **Примечание:** Подробную информацию о стратегиях SBOM, подписи образов через Cosign и интеграции с Supply Chain Security см. в **[CI/CD Security Hardening](cicd_security_hardening.md)** и **[Управление релизами и SemVer](release_management_and_semver.md)**.

### Сценарий 6: Image Promotion между окружениями

Перенос образа из staging в production без пересборки:

```yaml
promote_to_production:
  stage: deploy
  image: docker:24
  services:
    - docker:24-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    SOURCE_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    TARGET_IMAGE: $CI_REGISTRY_IMAGE:production
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker pull $SOURCE_IMAGE
    - docker tag $SOURCE_IMAGE $TARGET_IMAGE
    - docker push $TARGET_IMAGE
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 7: Настройка Registry Cleanup Policy

Удаление старых тегов для экономии места:

```yaml
# Настраивается в UI: Settings → Packages & Registries → Container Registry → Cleanup policy
# Пример конфигурации через API:
cleanup_registry:
  stage: .post
  image: curlimages/curl:latest
  script:
    - |
      curl --header "PRIVATE-TOKEN: $TOKEN" \
        --request POST \
        --data '{"keep_n": 10, "older_than": "30d", "name_regex": "^(main|latest|production)$"}' \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/registry/repositories/cleanup_policies"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 8: Helm Chart Registry

Публикация Helm-чартов в Package Registry:

```yaml
publish_chart:
  stage: deploy
  image: alpine/helm:latest
  script:
    - helm package charts/my-app --version $CI_PIPELINE_IID
    - curl --header "JOB-TOKEN: $CI_JOB_TOKEN" --upload-file my-app-$CI_PIPELINE_IID.tgz "$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages/helm/api/stable/charts"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

## Валидация и диагностика

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

### Проверка доступности Registry из Runner

```bash
# Проверка доступности Registry API
# → Ожидается: HTTP 200 OK или 401/403 (если анонимный доступ закрыт)
curl -I https://registry.gitlab.example.com/v2/

# Проверка аутентификации через CI_JOB_TOKEN
# → Ожидается: HTTP 200 OK, login успешен
echo $CI_REGISTRY_PASSWORD | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin

# Проверка работы Registry через docker info
# → Ожидается: Registry URL в секции Registry
docker info | grep -i registry
```

### Проверка SBOM и сканирования

```bash
# Просмотр SBOM
# → Ожидается: число компонентов > 0
cat sbom.json | jq '.components | length'

# Проверка уязвимостей
# → Ожидается: вывод уязвимостей или "No vulnerabilities found"
trivy image --format json $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA > trivy-report.json

# Верификация подписи образа
# → Ожидается: "Verified" или ошибка верификации
cosign verify $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
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

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` при push | Неверные `CI_REGISTRY_USER`/`CI_REGISTRY_PASSWORD` или токен отозван | Проверьте переменные, перезапустите job |
| `403 Forbidden` при push | Нет прав на запись в Registry (RBAC) | Проверьте роль в проекте: Maintainer или выше |
| `manifest unknown` при pull | Тег не существует или удален cleanup policy | Проверьте список тегов через API |
| `429 Too Many Requests` | Rate limit Registry API | Увеличьте `registry[rate_limiter]` в `gitlab.rb` (self-managed) |
| Registry недоступен | Сетевой фаервол или Registry упал | Проверьте `gitlab-ctl status registry`, сетевые правила |
| Garbage Collection зависает | Нет lock или нехватка диска | Остановите job, освободите диск, перезапустите GC |
| SBOM не генерируется | Trivy/Syft не установлен или образ пустой | Проверьте наличие образа, версию сканера |
| Push падает с `denied: requested access to the resource is denied` | Registry URL не совпадает с разрешенным | Проверьте `CI_REGISTRY` и внешний URL Registry |
| Cleanup policy не удаляет теги | Политика в `dry_run` или regex исключает теги | Переключите в `enabled` mode, проверьте regex |
| `toomanyrequests` от Dependency Proxy | Превышен лимит кэширования | Проверьте `dependency_proxy` настройки в Admin Area |

## Best Practices

### Разработка (Dev)

1. **Никогда не хардкодьте токены:** Используйте встроенные переменные `CI_REGISTRY_USER` и `CI_REGISTRY_PASSWORD`. Не передавайте `PRIVATE-TOKEN` в скриптах сборки.
2. **Тестируйте локально:** Используйте `docker login` с `CI_JOB_TOKEN` или Deploy Token для отладки push/pull до коммита.
3. **Используйте `.dockerignore`:** Исключайте кэш, node_modules, секреты из образа — уменьшает размер и снижает риск утечки.
4. **Версионируйте Dockerfile:** При изменении Dockerfile меняйте тег или используйте `docker build --cache-from` с учетом Dockerfile digest.
5. **Валидируйте образ до push:** Запускайте `trivy image` локально или в CI до загрузки в Registry.

### Эксплуатация и проектирование CI/CD (DevOps / SRE)

1. **Включите immutable tags для production:** Запретите overwrite тегов `main`, `production`, `latest`. Настройте через UI или API: `PUT /projects/:id/registry/repositories/:repo_id/tags/:tag/protect`.
2. **Registry Mirror для shared runners:** Настройте mirror на уровне Runner'ов для популярных базовых образов (`python:3.12`, `node:20`). Снижает зависимость от внешних сетей.
3. **Registry API мониторинг:** Настройте алерты на `registry/repositories` API — рост числа репозиториев или тегов без cleanup policy указывает на утечку.
4. **Cleanup policies по умолчанию:** Настройте group-level cleanup policy: `keep_n: 10` для веток, `older_than: 30d` для тегов без Git-тегов. Включайте `dry_run` перед `enabled`.
5. **Garbage Collection по расписанию:** Настройте nightly GC через `registry[garbage_collection]` в `gitlab.rb` или API. Не запускайте GC во время активных пайплайнов.
6. **Network Segmentation:** Registry должен быть доступен только из CI/CD подсети. Для self-managed настройте `registry['listen_address']` и firewall rules.
7. **Registry Isolation для production:** Для production используйте отдельный Registry инстанс или внешний (Harbor, Nexus). GitLab Registry встроен в GitLab и не предназначен для heavy production workloads.
8. **Dependency Proxy на уровне группы:** Включите для Docker Hub и публичных реестров. Кэширует pulls, снижает внешний трафик и время сборки.
9. **Аудит Registry API:** Логируйте вызовы Registry API через audit events. Отслеживайте массовый push/pull в нерабочее время.
10. **灾备 Registry:** Настройте replication в отдельный Registry инстанс или внешний реестр. Тестируйте восстановление из backup.

### Управление инстансом (Sysadmin)

1. **Конфигурация `gitlab.rb` для Registry:**
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
2. **Storage backend:** Выберите отдельный bucket/prefix для Registry. На self-managed используйте локальный диск или объектное хранилище. Не смешивайте Registry storage с Git data.
3. **Registry backup:** Регулярно экспортируйте manifests и metadata. Registry не покрыт `gitlab-backup create` по умолчанию — требуется отдельная стратегия.
4. **Registry API rate limiting:** Настройте `registry[rate_limiter]` в `gitlab.rb` для защиты от burst-атак.
5. **Monitoring Registry:** Настройте метрики Prometheus для Registry: `registry_http_requests_total`, `registry_storage_operations_total`, `registry_garbage_collection_*`.
6. **Sidekiq queue для Registry:** Мониторьте очередь `registry` на аномально высокую активность — признак массового GC или атаки.
7. **TLS для Registry:** Настройте валидированный TLS сертификат для Registry endpoint. Отключите `registry['tls_certificate']` только для внутренних тестов.
8. **Registry log rotation:** Настройте log rotation для Registry логов в Omnibus, чтобы предотвратить заполнение диска.
9. **Обновление Registry версии:** Следите за release notes GitLab — Registry версия привязана к версии GitLab. Обновляйте GitLab для получения исправлений безопасности Registry.
10. **Registry disaster recovery:** Настройте replication в отдельный инстанс или внешний реестр. Тестируйте восстановление из backup не реже квартала.

## Граничные случаи и ограничения

### Технические лимиты

| Параметр | Лимит | Примечание |
| :--- | :--- | :--- |
| Размер одного manifest | 5 МБ | Для больших SBOM используйте отдельные артефакты |
| Максимум тегов на репозиторий | Нет жесткого лимита | Ограничен хранилищем и GC политикой |
| Garbage Collection | Требует lock | Не запускайте GC во время активных пайплайнов |
| Запросов к Registry API | Rate limit зависит от плана | Self-managed: настраивается администратором |
| Размер слоя | Максимум 10 ГБ | Для очень больших образов используйте multi-stage |
| Количество manifests в registry | Зависит от storage | Мониторьте quota, настройте cleanup |
| Время жизни токена доступа | Зависит от типа токена | `CI_JOB_TOKEN` живёт в рамках job |

### Несовместимость и ограничения

| Ограничение | Описание | Решение |
| :--- | :--- | :--- |
| `CI_JOB_TOKEN` только для GitLab Registry | Токен не работает с внешними реестрами | Используйте Deploy Token или Project Access Token |
| GC во время пайплайна | Удаление слоев, используемых активными задачами | Настройте GC на ночное время |
| Immutable Tags + Cleanup | Политика cleanup не удаляет immutable теги | Используйте regex для исключения защищенных тегов |
| SBOM размер > 5 МБ | Manifest Registry не примет большой SBOM | Сохраняйте SBOM как артефакт, а не в Registry metadata |
| Dependency Proxy + Private Registry | Прокси работает только с публичными реестрами | Для приватных образов настройте Registry Mirror |
| Kaniko + DinD в одном job | Конфликт Docker daemon | Используйте отдельные стадии для DinD и Kaniko |
| Registry в air-gapped среде | Нет доступа к Docker Hub | Используйте внутренний Registry Mirror |

### Особые сценарии

**Registry в air-gapped среде:**
```yaml
# Использование внутреннего Registry
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

**Registry и GitLab Pages:**
- Pages и Container Registry могут использовать один domain с разными поддоменами.
- Настройте `registry['registry_http_addr']` и `pages['external_http']` для разделения.

**Registry при миграции инстанса:**
- Registry manifests не мигрируют через `gitlab-backup create`.
- Требуется отдельный backup Registry storage и metadata.
- Восстановление: настройте новый Registry на том же storage и импортируйте metadata.

## Дополнительная информация

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые принципы, Registry в архитектуре GitLab.
- **[Артефакты и кэширование](gitlab_ci_caching/gitlab_ci_artifacts.md)** — передача данных между стадиями.
- **[Безопасность CI/CD](cicd_security_hardening.md)** — защита Registry, сканирование, подпись.
- **[Управление релизами](release_management_and_semver.md)** — публикация артефактов и тегирование.
- **[Обзор Runner и Executor](gitlab_ci_runners_executors.md)** — изоляция при сборке образов.
- **[Официальная документация: Container Registry](https://docs.gitlab.com/ee/user/packages/container_registry/)** — полное руководство.
