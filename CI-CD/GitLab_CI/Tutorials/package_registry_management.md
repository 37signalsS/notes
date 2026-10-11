# Package Registry Management в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

> **Примечание:** Полная теория Package Registry, npm/Maven/PyPI registry и lifecycle policies описана в **[GitLab Package Registry Administration](../Advanced/gitlab_package_registry_administration.md)**. Это руководство фокусируется на практическом управлении registry в production среде.

## Определения

* **Package Registry** — универсальное хранилище пакетов, встроенное в GitLab; в CI используется для публикации и установки артефактов (npm, Maven, PyPI, NuGet, Go, Helm, Generic).
* **CI_JOB_TOKEN** — временный токен, автоматически создаваемый для каждого pipeline job; имеет права `write_package_registry` в рамках проекта.
* **Deploy Token** — долгоживущий токен уровня проекта с правами `read_package_registry`/`write_package_registry`; используется для внешних систем и cross-project install.
* **Lifecycle Policy** — политика автоматического удаления пакетов по критериям `keep_n`, `older_than`, `package_type`; поддерживает dry-run.
* **Immutable Package** — пакет, который нельзя перезаписать после публикации; повторная публикация с тем же именем и версией отклоняется с 409.
* **Group Endpoint** — единая точка доступа к пакетам всех проектов внутри группы (NuGet с 17.4+, Maven с 17.5+).
* **Dependency Proxy** — кэширующий прокси для внешних registry, снижающий трафик и время сборок.
* **Project Access Token** — токен с настроенными scopes на уровне проекта; альтернатива Deploy Token для автоматизации.

## Основные концепции

### Аутентификация и токены

Доступ к Package Registry из CI/CD обеспечивается через `CI_JOB_TOKEN`, который автоматически инжектируется в каждый job. Токен живёт только в рамках выполнения задачи и имеет минимально необходимые права внутри проекта.

Для внешних систем, cross-project install или долгоживущих интеграций используются Deploy Tokens или Project Access Tokens с явно заданными scopes (`read_package_registry`, `write_package_registry`). Personal Access Tokens в CI/CD не рекомендуются из-за более широких прав и риска утечки.

### Неизменяемость пакетов

Package Registry обеспечивает immutability: пакет с заданным именем и версией не может быть перезаписан. Это гарантирует воспроизводимость сборок и целостность артефактов. При необходимости обновления публикуется новая версия.

### Lifecycle Policies и очистка

Фоновые воркеры выполняют lifecycle policies каждые 12 часов. По умолчанию `package_registry_cleanup_package_file_worker_capacity` равен 2. Перед включением политики рекомендуется запустить dry-run через API для проверки логики удаления.

### Хранилище и бэкенды

По умолчанию пакеты хранятся на локальном диске GitLab (`/var/opt/gitlab/gitlab-rails/shared/packages`). Для production workloads рекомендуется объектное хранилище (S3, MinIO) через `gitlab_rails['object_store']['objects']['packages']`. Миграция между бэкендами выполняется через `gitlab-rake gitlab:packages:migrate` без downtime.

### Rate Limiting

Packages API защищён настраиваемыми лимитами запросов (`throttle_authenticated_packages_api_requests_per_period`, `throttle_unauthenticated_packages_api_requests_per_period`). При превышении лимитов возвращается 429; для снижения нагрузки используется Dependency Proxy.

## Предварительные требования

1. **GitLab Runner**: Runner должен иметь исходящий доступ к GitLab API (TCP 443) и DNS. Для group endpoints требуется доступ к групповому namespace.
2. **Права доступа**: роль Maintainer или Owner для publish; для install — Guest (read) при наличии доступа к проекту.
3. **Package Registry**: включён в настройках проекта (`Settings → Packages and registries`). По умолчанию активен в GitLab 17.x–19.x.
4. **Токены**: для CI/CD используется `CI_JOB_TOKEN`; для внешних систем — Deploy Token с scope `read_package_registry`/`write_package_registry`.
5. **Сеть**: исходящий NAT/ firewall, разрешающий TCP 443 к GitLab instance; при использовании Dependency Proxy — доступ к внешним registry.

## Практические сценарии

### Сценарий 1: npm Package Publish

```yaml
stages:
  - build
  - publish

variables:
  NPM_CONFIG_REGISTRY: "https://${CI_SERVER_HOST}/api/v4/projects/${CI_PROJECT_ID}/packages/npm/"

before_script:
  - echo "@${CI_PROJECT_NAMESPACE}:registry=https://${CI_SERVER_HOST}/api/v4/projects/${CI_PROJECT_ID}/packages/npm/" > .npmrc
  - echo "//${CI_SERVER_HOST}/api/v4/projects/${CI_PROJECT_ID}/packages/npm/:_authToken=${CI_JOB_TOKEN}" >> .npmrc

build:
  stage: build
  image: node:22-bookworm
  script:
    - npm ci
    - npm run build
    - npm run test
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

publish:
  stage: publish
  image: node:22-bookworm
  script:
    - npm publish
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
```

> **Примечание:** Для scoped пакетов (`@scope/package`) добавьте в `package.json`:
> ```json
> "publishConfig": {
>   "registry": "https://${CI_SERVER_HOST}/api/v4/projects/${CI_PROJECT_ID}/packages/npm/"
> }
> ```

### Сценарий 2: Maven Package Publish

```yaml
stages:
  - build
  - publish

variables:
  MAVEN_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"
  MAVEN_CLI_OPTS: "--batch-mode --errors --fail-at-end --show-version"

before_script:
  - |
    cat > $CI_PROJECT_DIR/.m2/settings.xml <<EOF
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
    EOF

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
```

Для **group endpoint** (GitLab 17.5+):

```xml
<!-- settings.xml -->
<settings>
  <servers>
    <server>
      <id>gitlab-maven-group</id>
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
mvn deploy -DaltDeploymentRepository=gitlab::default::https://${CI_SERVER_HOST}/api/v4/groups/${GROUP_ID}/packages/maven
```

### Сценарий 3: PyPI Package Publish

```yaml
stages:
  - build
  - publish

variables:
  PIP_INDEX_URL: "https://${CI_SERVER_HOST}/api/v4/projects/${CI_PROJECT_ID}/packages/pypi/"
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
    - twine upload --repository-url https://${CI_SERVER_HOST}/api/v4/projects/${CI_PROJECT_ID}/packages/pypi/ dist/*
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
```

### Сценарий 4: NuGet Package Publish

```yaml
stages:
  - build
  - publish

variables:
  NUGET_PACKAGES: $CI_PROJECT_DIR/.nuget/packages

before_script:
  - |
    cat > $CI_PROJECT_DIR/NuGet.Config <<EOF
    <?xml version="1.0" encoding="utf-8"?>
    <configuration>
      <packageSources>
        <add key="gitlab" value="https://${CI_SERVER_HOST}/api/v4/projects/${CI_PROJECT_ID}/packages/nuget/index.json" />
      </packageSources>
    </configuration>
    EOF

build:
  stage: build
  image: mcr.microsoft.com/dotnet/sdk:8.0
  script:
    - dotnet restore --configfile $CI_PROJECT_DIR/NuGet.Config
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
```

Для **group endpoint** (GitLab 17.4+):

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <add key="gitlab-group" value="https://${CI_SERVER_HOST}/api/v4/groups/${GROUP_ID}/packages/nuget/index.json" />
  </packageSources>
</configuration>
```

### Сценарий 5: Go Modules через GOPROXY

```yaml
stages:
  - build
  - test

variables:
  GOPROXY: "https://${CI_SERVER_HOST}/api/v4/packages/go/"

build:
  stage: build
  image: golang:1.26-bookworm
  script:
    - go mod tidy
    - go build ./...
    - go test ./...
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

Для публикации Go-модулей используйте Packages API для загрузки `.mod` и `.zip` файлов. Документация: [Go Modules and Packages](https://docs.gitlab.com/ee/user/packages/go_registry/).

### Сценарий 6: Lifecycle Policies для Package Registry

```bash
# Создание lifecycle policy через GitLab API
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/packages/lifecycle_policies" \
  --data '{
    "name": "cleanup-old-packages",
    "description": "Удаление устаревших пакетов",
    "enabled": true,
    "rules": [
      {
        "description": "Хранить 10 последних npm-пакетов",
        "keep_n": 10,
        "older_than": "90d",
        "package_type": "npm"
      },
      {
        "description": "Хранить 5 последних Maven-пакетов",
        "keep_n": 5,
        "older_than": "180d",
        "package_type": "maven"
      }
    ]
  }'
```

```bash
# Dry-run перед включением политики
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  "https://${CI_SERVER_HOST}/api/v4/projects/$PROJECT_ID/packages/lifecycle_policies/$POLICY_ID/dry_run"
```

## Валидация и проверка

Выполните проверки после публикации пакета:

1. **Package Registry UI:** Project → Packages & Registries → Package Registry — пакет отображается с версией и форматом.
   - *Ожидаемый результат:* список пакетов содержит запись с именем и тегом версии.
2. **Package Install:** Выполните установку из registry в изолированном окружении:
   ```bash
   # npm
   NPM_TOKEN=<deploy_token> npm install @scope/package
   # pip
   pip install --index-url https://<token>:<deploy_token>@gitlab.example.com/api/v4/projects/<id>/packages/pypi/simple/ my-package
   ```
   - *Ожидаемый результат:* пакет устанавливается без ошибок доступа.
3. **Package Publish:** Запустите publish-задачу по тегу.
   - *Ожидаемый результат в логах:* `npm notice` / `+package@version` / `Uploading to GitLab`.
4. **Lifecycle Policy:** Запустите dry-run и проверьте вывод.
   - *Ожидаемый результат:* dry-run output перечисляет пакеты, подлежащие удалению.
5. **Dependencies:** Для NuGet/Maven проверьте разрешение зависимостей из group endpoint.
   - *Ожидаемый результат:* сборка проходит без 404.

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| **401 Unauthorized** | Неверный или просроченный токен | Проверьте Deploy Token, Project Access Token или `CI_JOB_TOKEN`; убедитесь в наличии scope `write_package_registry` |
| **403 Forbidden** | Токен без нужного scope или недостаточная роль | Используйте Project Access Token с scope `read_package_registry`/`write_package_registry`; для publish — роль Maintainer |
| **409 Conflict** | Пакет с таким именем и версией уже существует | Package Registry обеспечивает immutability; увеличьте версию пакета |
| **404 Not Found** | Неверный URL registry или права доступа | Проверьте endpoint registry и видимость проекта; для cross-project install используйте Deploy Token |
| **413 Payload Too Large** | Превышен лимит размера файла | Увеличьте `nginx['client_max_body_size']` или проверьте `*_max_file_size` в plan limits |
| **422 Unprocessable Entity** | Ошибка в метаданных пакета | Проверьте `package.json`, `pom.xml` или `setup.py` на корректность имени и версии |
| **429 Too Many Requests** | Превышен лимит Packages API | Включите Dependency Proxy для кэширования или увеличьте лимиты в конфигурации |
| **Lifecycle policy не работает** | Политика неактивна или неверные правила | Проверьте статус policy и правила; используйте `dry_run` перед `enabled: true`; убедитесь, что `package_registry_cleanup_package_file_worker_capacity > 0` |
| **npm install 404** | Неверный scope или URL registry | Проверьте `.npmrc` на наличие строки `@scope:registry=...` и trailing slash в URL |
| **Cross-project install 404** | `CI_JOB_TOKEN` не имеет доступа к другому проекту | Используйте Deploy Token из проекта-получателя с scope `read_package_registry` |
| **Registry unavailable (502/503)** | Storage backend недоступен или перегружен | Проверьте connectivity к storage (локальный диск или S3); проверьте статус GitLab |
| **Rate limit exceeded** | Превышен глобальный лимит запросов | Увеличьте `package_registry_rate_limits` в `gitlab.rb` или включите Dependency Proxy |

## Крайние случаи (Edge Cases)

* **Повреждённый пакет:** При частичной загрузке файл может быть невалидным. Удалите пакет через API и повторно опубликуйте; проверьте целостность storage backend.
* **Scoped vs unscoped (npm):** Без scope в `.npmrc` npm публикует в `registry.npmjs.org`. Убедитесь, что scope совпадает с namespace проекта GitLab.
* **Immutable version collision:** Попытка перезаписать существующую версию возвращает 409. Для hotfix-сценариев используйте новый patch-версию или восстановите пакет из бэкапа.
* **Group endpoint не найден (404):** NuGet group endpoints доступны с 17.4+, Maven — с 17.5+. На старых инстансах используйте project-level endpoint.
* **Storage quota:** Container Registry, Package Registry и artifacts учитываются в namespace storage usage. При превышении purchased storage проект переходит в read-only; для решения — докупите storage или очистите старые пакеты.
* **Network partitions:** При разрыве connectivity между Runner и GitLab publish-job завершается с ошибкой timeout. Настройте `retry` в `.gitlab-ci.yml` или увеличьте `job_timeout`.
* **Token expiry:** Deploy Token имеет дату истечения; `CI_JOB_TOKEN` живёт только в рамках job. Для долгоживущих pipeline используйте Project Access Token с длительным сроком действия.
* **Large file uploads:** Generic packages ограничены `generic_packages_max_file_size` (по умолчанию 5 GB). Для файлов >1 GB используйте фрагментированную загрузку или внешнее хранилище с ссылкой в Generic package.

## Лучшие практики (Best Practices)

### Организация

* **Версионирование:** используйте SemVer для всех пакетов; избегайте перезаписи версий (immutability).
* **Именование:** единое соглашение `<namespace>/<package-name>`; для group endpoints — namespace по группе.
* **Изоляция:** отдельные namespace для staging и production; используйте group endpoints для shared dependencies внутри организации.
* **Lifecycle Policies:** настройте `dry_run` перед `enabled: true`; применяйте разные правила для разных типов пакетов (`keep_n: 10` для npm, `keep_n: 5` для Maven).
* **Package Importer:** используйте для миграции из Nexus/Artifactory/JFrog вместо ручных скриптов.

### Безопасность

* **Токены:** используйте Project Access Tokens или Deploy Tokens с минимальными необходимыми правами; избегайте Personal Access Tokens в CI/CD.
* **RBAC:** ограничьте права на загрузку пакетов ролью Maintainer; включите `Allow anyone to pull` только для public пакетов.
* **Сканирование:** сканируйте пакеты на уязвимости перед публикацией; используйте Dependency Proxy для контроля внешних зависимостей.
* **Аудит:** включите Audit Events (GA в 18.2) для отслеживания publish/delete операций; интегрируйте с централизованным логированием.
* **Provenance:** проверяйте provenance и подписи пакетов перед установкой в production.

### Производительность

* **Хранилище:** для больших объёмов используйте объектное хранилище; для small deployments — локальный диск с мониторингом дискового пространства.
* **Кэширование:** настройте Dependency Proxy для внешних зависимостей; для часто используемых внутренних пакетов — group endpoints.
* **Очистка:** настройте автоматические lifecycle policies с `keep_n` и `older_than`; мониторьте `Usage quotas → Packages` для отслеживания роста.
* **Rate Limits:** при нагрузочном тестировании убедитесь, что лимиты Packages API не блокируют легитимные запросы; включите Dependency Proxy для popular базовых пакетов.

### Надёжность (SRE)

* **Мониторинг:** отслеживайте Packages API rate limits, объём хранилища, количество пакетов по типам; настройте алерты на `Usage quotas` nearing limit.
* **Резервное копирование:** включите бэкап packages в стратегию `gitlab-backup create`; убедитесь, что `SKIP` не исключает `packages`.
* **Disaster Recovery:** используйте Package Importer для восстановления из бэкапа или внешнего registry; тестируйте восстановление регулярно.
* **Capacity Planning:** при росте количества пакетов плавно увеличивайте `package_registry_cleanup_package_file_worker_capacity` и storage backend capacity.

## Очистка

### Удаление устаревших пакетов через API

```bash
# Удаление пакетов проекта старше 90 дней через API (требуется GNU date)
glab api projects/$PROJECT_ID/packages | jq -r '.[] | select(.created_at < "'$(date -d "90 days ago" -I)'") | .id' | \
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
```

## Дополнительная информация

### Смотрите также

- **[Package Registry Administration — полное руководство](../Advanced/gitlab_package_registry_administration.md)** — теория, архитектура, все типы пакетов, API reference
- **[Container Registry](../Advanced/container_registry.md)** — управление Docker-образами
- **[Dependency Proxy — полное руководство](../Advanced/dependency_proxy.md)** — кеширование зависимостей, air-gapped окружения
- **[Container Registry Management в GitLab CI/CD](../Tutorials/container_registry_management.md)** — практическое управление контейнерным registry
- **[npm Documentation](https://docs.npmjs.com/)** — официальная документация
- **[Maven Documentation](https://maven.apache.org/)** — официальная документация
- **[PyPI Documentation](https://packaging.python.org/)** — официальная документация
- **[NuGet Documentation](https://learn.microsoft.com/en-us/nuget/)** — официальная документация
- **[Go Modules](https://go.dev/doc/modules)** — официальная документация
