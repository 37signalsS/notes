# Управление Package Registry GitLab

**Актуально для:** GitLab 17.x–19.x

## Определения

* **Package Registry** — универсальное хранилище пакетов, встроенное в GitLab, поддерживающее форматы npm, Maven, PyPI, NuGet, Conan, Helm, Composer и Generic.
* **Container Registry** — хранилище Docker-образов, работающее как отдельный сервис; отличается от Package Registry архитектурой и конфигурацией.
* **Deploy Token** — токен для доступа к Registry из CI/CD или внешних систем; доступен на уровне проекта.
* **Project Access Token** — токен с настроенными правами на уровне проекта; используется для автоматизации.
* **Lifecycle Policy** — политика автоматического удаления пакетов по критериям: количество версий (`keep_n`), возраст (`older_than`), тип пакета (`package_type`).
* **Group Endpoint** — единая точка доступа к пакетам всех проектов внутри группы (NuGet с 17.4+, Maven с 17.5+).
* **Package Importer** — инструмент для импорта пакетов из внешних реестров (Nexus, Artifactory, JFrog) в GitLab Package Registry.
* **Rate Limiting** — ограничение количества запросов к Packages API для защиты инстанса от перегрузки.
* **Audit Events** — события аудита операций публикации и удаления пакетов (GA в GitLab 18.2, введено в 17.10).

## Основные концепции

### Архитектура Package Registry

Package Registry встроен в GitLab как часть основного Rails-приложения (в отличие от Container Registry, который работает как отдельный сервис на базе Docker Distribution):

1. **Хранилище (Storage)** — по умолчанию локальный диск GitLab (`/var/opt/gitlab/gitlab-rails/shared/packages`); поддерживаются объектные хранилища (S3, MinIO, GCS, Azure Blob) через `gitlab_rails['object_store']['objects']['packages']`.
2. **Аутентификация (Auth)** — доступ через Deploy Tokens, Project Access Tokens, CI_JOB_TOKEN, Personal Access Tokens; для group endpoints требуется токен с правами на группу.
3. **Версионирование (Versioning)** — SemVer или кастомные теги; пакеты неизменяемы (immutable): повторная публикация с тем же версией отклоняется.
4. **Очистка (Cleanup)** — Lifecycle Policies на уровне проекта или группы; поддерживается dry-run перед применением.
5. **Rate Limiting** — настраиваемые лимиты запросов к Packages API; действует на пользователей и IP.
6. **Аудит (Audit Events)** — логирование операций publish/delete с указанием пользователя, проекта и времени.
7. **Group Endpoints** — единые endpoints для NuGet и Maven, упрощающие конфигурацию зависимостей в монопое и multi-project окружениях.

### Поддерживаемые форматы

| Формат | Расширение | Версия GitLab | Примечание |
|:---|:---|:---|:---|
| **npm** | `.tgz` | 11.7+ | Node.js пакеты |
| **Maven** | `.jar`, `.pom` | 11.3+ | Java/Kotlin зависимости; group endpoint с 17.5+ |
| **PyPI** | `.whl`, `.tar.gz` | 12.10+ | Python пакеты |
| **NuGet** | `.nupkg` | 12.8+ | .NET пакеты; group endpoint с 17.4+ |
| **Conan** | `.conan` | 12.6+ (Conan 1), 18.1+ (Conan 2) | C/C++ зависимости |
| **Helm** | `.tgz` | 14.1+ | Helm-чарты |
| **Composer** | `.zip`, метаданные `.json` | 13.2+ | PHP пакеты |
| **Go** | `.mod`, `.zip` | 13.1+ | Go модули; прокси через GOPROXY |
| **Generic** | Любой | 13.5+ | Произвольные артефакты, включая бинарники и лицензии |

> **Примечание:** Формат Debian находится в статусе черновика (Draft) и не поддерживается в релизных версиях GitLab. Terraform Module Registry является отдельным компонентом GitLab и не относится к Package Registry.

### Права доступа

| Роль | Чтение | Загрузка | Управление lifecycle | Анонимный pull |
|:---|:---|:---|:---|:---|
| **Guest** | Да | Нет | Нет | По настройке проекта |
| **Reporter** | Да | Нет | Нет | По настройке проекта |
| **Developer** | Да | Да | Нет | Нет |
| **Maintainer** | Да | Да | Да | Нет |
| **Owner** | Да | Да | Да | Нет |

> **GitLab 17.x+:** Включение опции **Allow anyone to pull from package registry** в настройках проекта разрешает анонимный доступ на чтение к пакетам независимо от видимости проекта. Глобально опция управляется через Application Setting `package_registry_allow_anyone_to_pull_option`.

## Практические сценарии

### Сценарий 1: Настройка Package Registry

Package Registry включён по умолчанию в GitLab 17.x–19.x. При необходимости изменить хранилище, настроить rate limiting или отключить registry, используйте конфигурацию Omnibus:

```ruby
# /etc/gitlab/gitlab.rb

# Отключение Package Registry (не рекомендуется для production)
gitlab_rails['packages_enabled'] = false

# Локальное хранилище (если требуется отдельный путь)
gitlab_rails['packages_storage_path'] = "/mnt/packages"

# Объектное хранилище (S3 / MinIO / GCS / Azure)
gitlab_rails['object_store']['objects']['packages'] = {
  'enabled' => true,
  'bucket' => 'gitlab-packages',
  'region' => 'us-east-1',
  'access_key_id' => 'AKIAIOSFODNN7EXAMPLE',
  'secret_access_key' => 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
}

# Rate limiting для Packages API (GitLab 17.x+)
gitlab_rails['package_registry_rate_limits'] = {
  'enabled' => true,
  'requests_per_minute' => 300
}

# Применение конфигурации
sudo gitlab-ctl reconfigure
```

Для исходной сборки (source installation):

```yaml
# /home/git/gitlab/config/gitlab.yml
production: &base
  packages:
    enabled: true
    storage_path: /mnt/packages
```

```bash
# После изменения конфигурации перезапустите GitLab
sudo gitlab-ctl restart
```

### Сценарий 2: Публикация npm-пакетов

```yaml
# .gitlab-ci.yml
stages:
  - test
  - publish

variables:
  NPM_CONFIG_REGISTRY: "https://gitlab.example.com/api/v4/packages/npm/"
  NPM_CONFIG_LEGACY_PEER_DEPS: "true"

publish_npm:
  stage: publish
  image: node:20-bookworm
  script:
    - npm ci
    - npm run test
    - npm publish --access public
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
  only:
    - tags
```

### Сценарий 3: Публикация Maven-пакетов

```yaml
# .gitlab-ci.yml
stages:
  - build
  - publish

variables:
  MAVEN_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"
  MAVEN_CLI_OPTS: "--batch-mode --errors --fail-at-end --show-version"

build:
  stage: build
  image: maven:3.9-eclipse-temurin-21
  script:
    - mvn $MAVEN_CLI_OPTS compile
    - mvn $MAVEN_CLI_OPTS test
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

publish:
  stage: publish
  image: maven:3.9-eclipse-temurin-21
  script:
    - mvn $MAVEN_CLI_OPTS deploy -DskipTests
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
  only:
    - tags
```

Для использования **group endpoint** (GitLab 17.5+):

```xml
<!-- settings.xml -->
<settings>
  <servers>
    <server>
      <id>gitlab-maven</id>
      <configuration>
        <httpHeaders>
          <property>
            <name>Private-Token</name>
            <value>${CI_JOB_TOKEN}</value>
          </property>
        </httpHeaders>
      </configuration>
    </server>
  </servers>
</settings>
```

```bash
# Развёртывание в group endpoint
mvn deploy -DaltDeploymentRepository=gitlab::default::https://gitlab.example.com/api/v4/groups/GROUP_ID/packages/maven
```

### Сценарий 4: Публикация PyPI-пакетов

```yaml
# .gitlab-ci.yml
stages:
  - build
  - publish

variables:
  PIP_INDEX_URL: "https://gitlab.example.com/api/v4/packages/pypi/"
  PIP_EXTRA_INDEX_URL: "https://pypi.org/simple"

build:
  stage: build
  image: python:3.13-slim
  before_script:
    - pip install build twine
  script:
    - python -m build
    - twine check dist/*
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

publish:
  stage: publish
  image: python:3.13-slim
  before_script:
    - pip install twine
  script:
    - twine upload --repository-url https://gitlab.example.com/api/v4/packages/pypi/ dist/*
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
  only:
    - tags
```

### Сценарий 5: Публикация NuGet-пакетов

```yaml
# .gitlab-ci.yml
stages:
  - build
  - publish

variables:
  NUGET_PACKAGES: $CI_PROJECT_DIR/.nuget/packages

before_script:
  - |
    cat > NuGet.Config <<EOF
    <?xml version="1.0" encoding="utf-8"?>
    <configuration>
      <packageSources>
        <add key="gitlab" value="https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/nuget/index.json" />
      </packageSources>
    </configuration>
    EOF

build:
  stage: build
  image: mcr.microsoft.com/dotnet/sdk:8.0
  script:
    - dotnet restore --configfile NuGet.Config
    - dotnet build --configuration Release
    - dotnet test --configuration Release
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

publish:
  stage: publish
  image: mcr.microsoft.com/dotnet/sdk:8.0
  script:
    - dotnet nuget push bin/Release/*.nupkg \
        --source "gitlab" \
        --api-key "${CI_JOB_TOKEN}" \
        --skip-duplicate
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
  only:
    - tags
```

Для использования **group endpoint** (GitLab 17.4+):

```xml
<!-- NuGet.Config -->
<configuration>
  <packageSources>
    <add key="gitlab-group" value="https://gitlab.example.com/api/v4/groups/GROUP_ID/packages/nuget/index.json" />
  </packageSources>
</configuration>
```

### Сценарий 6: Использование Go-модулей через GOPROXY

```yaml
# .gitlab-ci.yml
variables:
  GOPROXY: "https://gitlab.example.com/api/v4/packages/go/"

test:
  stage: test
  image: golang:1.23-bookworm
  script:
    - go mod tidy
    - go build ./...
    - go test ./...
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

Для публикации Go-модулей используйте Packages API для загрузки `.mod` и `.zip` файлов. Документация: [Go Modules and Packages](https://docs.gitlab.com/ee/user/packages/go_registry/).

### Сценарий 7: Публикация Helm-чартов

```yaml
# .gitlab-ci.yml
publish_helm:
  stage: deploy
  image: alpine/helm:3.14
  script:
    - helm package charts/my-app --version $CI_PIPELINE_IID
    - curl --header "JOB-TOKEN: $CI_JOB_TOKEN" --upload-file my-app-$CI_PIPELINE_IID.tgz "$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages/helm/api/stable/charts"
  rules:
    - if: $CI_COMMIT_TAG
```

### Сценарий 8: Lifecycle Policies

```bash
# Создание lifecycle policy через GitLab API
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/packages/lifecycle_policies" \
  --data '{
    "name": "cleanup-old-packages",
    "description": "Remove packages older than 90 days",
    "enabled": true,
    "rules": [
      {
        "description": "Keep latest 10 npm packages",
        "keep_n": 10,
        "older_than": "90d",
        "package_type": "npm"
      },
      {
        "description": "Keep latest 5 Maven packages",
        "keep_n": 5,
        "older_than": "180d",
        "package_type": "maven"
      }
    ]
  }'
```

```bash
# Список lifecycle policies проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/packages/lifecycle_policies"

# Dry-run перед включением политики
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/packages/lifecycle_policies/$POLICY_ID/dry_run"
```

### Сценарий 9: Импорт пакетов из внешнего Registry

```bash
# 1. Экспорт пакетов из внешнего Registry
curl -u user:pass https://external-registry.com/v1/packages | jq -r '.[].name' | while read pkg; do
  curl -u user:pass -o "$pkg.tgz" "https://external-registry.com/v1/packages/$pkg/download"
done

# 2. Публикация в GitLab Package Registry
for pkg in *.tgz; do
  curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
    --upload-file "$pkg" \
    "$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages/generic/my-app/$CI_COMMIT_TAG/$(basename $pkg)"
done
```

Для автоматизированной миграции используйте **Package Importer** через UI: Project → Settings → General → Advanced settings → Import packages from another repository.

## Операции и команды

### Управление через API

```bash
# Список пакетов проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/packages"

# Список файлов пакета
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/packages/$PACKAGE_ID/package_files"

# Удаление пакета
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --request DELETE \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/packages/$PACKAGE_ID"

# Список lifecycle policies
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/packages/lifecycle_policies"

# Group endpoints (NuGet, GitLab 17.4+)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/groups/$GROUP_ID/packages/nuget/index.json"

# Group endpoints (Maven, GitLab 17.5+)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/groups/$GROUP_ID/packages/maven"
```

### Управление через UI

1. **Project Packages:** Project → Packages & Registries → Package Registry
2. **Group Packages:** Group → Packages & Registries → Package Registry
3. **Lifecycle Policies:** Project → Packages & Registries → Package Registry → Lifecycle policies
4. **Package Importer:** Project → Settings → General → Advanced settings → Import packages
5. **Admin Settings:** Admin Area → Packages & Registries → Package Registry

## Валидация и проверка

Перед внесением изменений в production выполните проверки:

1. **Хранилище:** Убедитесь, что выбранный бэкенд (локальный диск или объектное хранилище) доступен и имеет достаточную ёмкость; проверьте права на запись для пользователя `git`.
2. **Аутентификация:** Проверьте работу Deploy Token и CI_JOB_TOKEN с минимальными требуемыми правами (`read_package_registry`, `write_package_registry`).
3. **Публикация:** Запустите publish-задачу для каждого поддерживаемого формата — пакет должен появиться в UI с корректными метаданными.
4. **Установка:** Выполните `npm install`/`pip install`/`nuget restore` из registry — зависимости должны разрешаться без ошибок доступа.
5. **Lifecycle Policy:** Включите `dry_run` перед `enabled: true` и проверьте логику удаления в dry-run output.
6. **Group Endpoints:** Проверьте доступность group-level endpoints для NuGet/Maven из build-агентов.
7. **Rate Limits:** При нагрузочном тестировании убедитесь, что лимиты Packages API не блокируют легитимные запросы.

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `401 Unauthorized` | Неверный или просроченный токен | Проверьте Deploy Token, Project Access Token или CI_JOB_TOKEN; убедитесь в наличии scope `write_package_registry` |
| `403 Forbidden` | Токен без нужного scope или недостаточная роль | Используйте Project Access Token с scope `read_package_registry`/`write_package_registry`; проверьте роль Maintainer для загрузки |
| Пакет не найден | Неверный URL или права | Проверьте endpoint registry и права доступа к проекту |
| Ошибка публикации | Превышен лимит размера или неверный формат | Увеличьте `nginx['client_max_body_size']`; проверьте соответствие формата спецификации |
| Lifecycle policy не работает | Политика неактивна или неверные правила | Проверьте статус policy и правила; используйте `dry_run` перед включением |
| Повреждённый пакет | Ошибка при загрузке | Перезагрузите пакет; проверьте целостность хранилища |
| Rate limit exceeded | Превышен лимит запросов к Packages API | Увеличьте лимиты в конфигурации или включите Dependency Proxy для кэширования |
| `404` на group endpoint | Групповой endpoint не поддерживается версией | NuGet group endpoints доступны с 17.4+, Maven — с 17.5+; обновите GitLab |
| Анонимный pull не работает | Опция отключена глобально или на уровне проекта | Проверьте Application Setting `package_registry_allow_anyone_to_pull_option` и настройки проекта |

## Лучшие практики

### Организация

* **Версионирование:** используйте SemVer для всех пакетов; избегайте перезаписи версий (immutability).
* **Именование:** единое соглашение `<group>/<project>/<package-name>`; для group endpoints — namespace по группе.
* **Изоляция:** отдельные Project Registry для staging и production; используйте group endpoints для shared dependencies внутри организации.
* **Lifecycle Policies:** настройте `dry_run` перед `enabled: true`; применяйте разные правила для разных типов пакетов (например, `keep_n: 10` для npm, `keep_n: 5` для Maven).
* **Package Importer:** используйте для миграции из Nexus/Artifactory/JFrog вместо ручного скрипта; поддерживает большинство форматов.

### Безопасность

* **Токены:** используйте Project Access Tokens или Deploy Tokens с минимальными необходимыми правами; избегайте Personal Access Tokens в CI/CD.
* **RBAC:** ограничьте права на загрузку пакетов ролью Maintainer; включите `Allow anyone to pull` только для public пакетов.
* **Сканирование:** сканируйте пакеты на уязвимости перед публикацией; используйте Dependency Proxy для кэширования и контроля внешних зависимостей.
* **Аудит:** включите Audit Events (GA в 18.2) для отслеживания publish/delete операций; интегрируйте с SIEM или централизованным логированием.
* **Provenance:** проверяйте provenance и подписи пакетов перед установкой в production.

### Производительность

* **Хранилище:** для больших объёмов используйте объектное хранилище с CDN; для small deployments — локальный диск.
* **Кэширование:** настройте Dependency Proxy для внешних зависимостей; для часто используемых внутренних пакетов — group endpoints.
* **Очистка:** настройте автоматические lifecycle policies с `keep_n` и `older_than`; регулярно проверяйте квоты хранилища.
* **Мониторинг:** отслеживайте Packages API rate limits, объём хранилища, количество пакетов по типам.

### Надёжность

* **Резервное копирование:** включите бэкап packages в стратегию `gitlab-backup create`; убедитесь, что `SKIP` не исключает `packages`.
* **Миграция:** при изменении `packages_storage_path` используйте `gitlab-rake gitlab:packages:migrate` для переноса существующих пакетов.
* **Disaster Recovery:** используйте Package Importer для восстановления из бэкапа или внешнего registry; тестируйте восстановление регулярно.

## Очистка (Cleanup)

### Удаление устаревших пакетов через API

```bash
# Удаление пакетов проекта старше 90 дней через API
glab api projects/$PROJECT_ID/packages | jq -r '.[] | select(.created_at < "'$(date -d '90 days ago' -I)'") | .id' | \
  while read pkg_id; do
    echo "Deleting package $pkg_id"
    glab api projects/$PROJECT_ID/packages/$pkg_id -X DELETE
  done

# Пакетная очистка registry по типу пакета
glab api groups/$GROUP_ID/packages | jq -r '.[] | select(.package_type == "npm") | .id' | \
  xargs -I {} glab api groups/$GROUP_ID/packages/{} -X DELETE
```

### Миграция хранилища

```bash
# При изменении packages_storage_path или переключении на object store
sudo gitlab-rake gitlab:packages:migrate

# Проверка целостности миграции
sudo gitlab-rake gitlab:packages:check
```

### Проверка квот

```bash
# Объём пакетов по проектам (требуются права администратора)
sudo gitlab-rake gitlab:packages:list | head -20
```

## Дополнительная информация

### Связанные темы

* **[Container Registry в GitLab CI/CD](../container_registry.md)** — Docker Registry и CI/CD интеграция
* **[Dependency Proxy](../dependency_proxy.md)** — кеширование зависимостей и air-gapped окружения
* **[Управление инстансом GitLab](./gitlab_instance_administration.md)** — бэкап, восстановление, обновление
* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[SBOM и подпись артефактов](../sbom_and_artifact_signing.md)** — Supply Chain Security для пакетов

### API Reference

* [Packages API](https://docs.gitlab.com/ee/api/packages.html)
* [Lifecycle Policies API](https://docs.gitlab.com/ee/api/packages.html#lifecycle-policies)
* [Package Importer](https://docs.gitlab.com/ee/user/packages/package_importer.html)
* [Group Packages API](https://docs.gitlab.com/ee/api/packages.html#group-packages)
* [Официальная документация: Package Registry](https://docs.gitlab.com/ee/user/packages/)
* [Официальная документация: Администрирование Package Registry](https://docs.gitlab.com/administration/packages)
