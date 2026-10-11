# GitLab Dependency Proxy: конфигурации пакетных менеджеров

**Актуально для:** GitLab 18.0–19.4

## Определения

**Dependency Proxy** — кеширующий proxy для зависимостей пакетных менеджеров (npm, Maven, PyPI, Go, NuGet, RubyGems, Conan). Уменьшает время сборки, снижает нагрузку на внешние реестры и обеспечивает работу в air-gapped средах.

**Pull-through cache** — режим работы, при котором Dependency Proxy кеширует артефакты при первом запросе и отдаёт их из кеша при последующих запросах.

**Group-level Dependency Proxy** — общий кеш для всех проектов группы, снижающий общий объём скачиваемых зависимостей.

**TTL (Time To Live)** — срок жизни кешированных артефактов. По истечении TTL артефакт загружается заново из upstream-реестра.

**Upstream registry** — внешний реестр, из которого Dependency Proxy загружает артефакты при отсутствии кешированной копии.

**Hit rate** — доля запросов, обслуженных из кеша. Высокий hit rate (>80–90%) указывает на эффективную работу кеша.

## Предварительные требования

| Роль | Требования |
| :--- | :--- |
| **Dev** | GitLab Runner с доступом к интернету или air-gapped окружению; базовое понимание пакетных менеджеров; права Maintainer в проекте |
| **DevOps/SRE** | Доступ к Admin Area для глобальных настроек TTL и лимитов; доступ к логам GitLab для диагностики hit rate; права Group Owner для group-level proxy |
| **Sysadmin** | Доступ к `gitlab.rb` для настройки object store и лимитов; root-доступ к серверу GitLab; мониторинг дискового пространства |

**Требования к окружению:**
- GitLab 18.0 или новее (рекомендуется 19.x)
- Доступ к upstream-реестрам для первоначального заполнения кеша
- При air-gapped развёртывании: заранее подготовленный кеш или mirror upstream-реестра

## Архитектура и принцип работы

### Компоненты

Dependency Proxy состоит из следующих компонентов:

1. **GitLab Rails приложение** — основной сервис, обрабатывающий HTTP-запросы к Dependency Proxy, аутентификацию через `CI_JOB_TOKEN` или Personal/Project Access Token, и управление кешем в базе данных PostgreSQL.
2. **Nginx** — обратный прокси, принимающий внешние запросы и маршрутизирующий их к Rails.
3. **Object Store / локальный диск** — физическое хранилище кешированных артефактов. Может быть:
   - Локальный диск сервера GitLab
    - Объектное хранилище
4. **Workhorse** — промежуточный прокси между Nginx и Rails для обработки больших файлов.

### Lifecycle запроса

```text
Pipeline Runner → GitLab Nginx → Rails → [Кеш hit?]
    ├─ Да → Object Store → отдать артефакт
    └─ Нет → Upstream Registry → скачать → Object Store → отдать артефакт
```

### Кеширование и TTL

- При первом запросе артефакт скачивается из upstream-реестра и сохраняется в кеш.
- При последующих запросах артефакт отдаётся из кеша до истечения TTL.
- После истечения TTL артефакт удаляется из кеша при следующем запросе (lazy expiration) или по расписанию.
- Group-level proxy объединяет кеши всех проектов группы, уменьшая duplicate downloads.

## Конфигурация

### Включение Dependency Proxy (Sysadmin)

Включите Dependency Proxy в Admin Area → Packages → Dependency Proxy или через `gitlab.rb`:

```ruby
# /etc/gitlab/gitlab.rb
gitlab_rails['dependency_proxy_enabled'] = true

# Настройка object store для кеша
gitlab_rails['object_store']['enabled'] = true
gitlab_rails['object_store']['remote_directory'] = 'dependency_proxy'
gitlab_rails['object_store']['connection'] = {
  'provider' => 'OBJECT_STORE_PROVIDER',
  'region' => 'REGION',
  'access_key_id' => 'ACCESS_KEY',
  'secret_access_key' => 'SECRET_KEY'
}

# Лимиты
gitlab_rails['dependency_proxy']['max_artifact_size'] = 500.megabytes
```

Примените конфигурацию:

```bash
gitlab-ctl reconfigure
```

### Настройка в пакетных менеджерах

#### npm

```yaml
# .gitlab-ci.yml
variables:
  NPM_CONFIG_REGISTRY: "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/npm/"

install_dependencies:
  stage: build
  image: node:20
  script:
    - echo "//gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/npm/:_authToken=${CI_JOB_TOKEN}" > .npmrc
    - npm ci
```

**Локальная разработка:**
```bash
# .npmrc для локальной разработки
@my-company:registry=https://gitlab.example.com/api/v4/projects/123/packages/npm/
//gitlab.example.com/api/v4/projects/123/packages/npm/:_authToken=glpat-xxxxxxxxxxxx
```

#### Maven

```yaml
variables:
  MAVEN_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"
  MAVEN_CLI_OPTS: "-s .m2/settings.xml"

install_dependencies:
  stage: build
  image: maven:3.9-eclipse-temurin-21
  script:
    - mkdir -p .m2
    - cat > .m2/settings.xml <<EOF
      <settings>
        <mirrors>
          <mirror>
            <id>gitlab-dependency-proxy</id>
            <mirrorOf>*</mirrorOf>
            <url>https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/maven/</url>
          </mirror>
        </mirrors>
        <servers>
          <server>
            <id>gitlab-dependency-proxy</id>
            <username>$CI_JOB_TOKEN</username>
            <password>$CI_JOB_TOKEN</password>
          </server>
        </servers>
      </settings>
      EOF
    - mvn $MAVEN_CLI_OPTS dependency:go-offline
```

#### PyPI

```yaml
variables:
  PIP_INDEX_URL: "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/pypi/"
  PIP_EXTRA_INDEX_URL: "https://pypi.org/simple"

install_dependencies:
  stage: build
  image: python:3.11
  script:
    - pip install --index-url $PIP_INDEX_URL --extra-index-url $PIP_EXTRA_INDEX_URL -r requirements.txt
```

#### Go modules

```yaml
variables:
  GOPROXY: "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/go/"
  GONOSUMDB: "gitlab.example.com"

install_dependencies:
  stage: build
  image: golang:1.23
  script:
    - go mod download
```

#### NuGet

```yaml
variables:
  NUGET_PACKAGES: "$CI_PROJECT_DIR/.nuget/packages"

install_dependencies:
  stage: build
  image: dotnet/sdk:8.0
  script:
    - dotnet restore --configfile ./nuget.config
```

`nuget.config`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="GitLab Dependency Proxy" value="https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/nuget/index.json" />
  </packageSources>
</configuration>
```

#### RubyGems

```yaml
variables:
  BUNDLE_GEMS__GITLAB__COM: "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/rubygems/"

install_dependencies:
  stage: build
  image: ruby:3.3
  script:
    - bundle config set --local deployment true
    - bundle config set --local without "development test"
    - bundle install
```

#### Conan

```yaml
variables:
  CONAN_USER_HOME: "$CI_PROJECT_DIR/.conan"

install_dependencies:
  stage: build
  image: conanio/gcc13-ubuntu22.04:latest
  script:
    - conan remote add gitlab-dependency-proxy https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/conan/ || true
    - conan install . --remote=gitlab-dependency-proxy --build=missing
```

#### Group-level Dependency Proxy

```yaml
# Использование group-level proxy для всех проектов группы
variables:
  NPM_CONFIG_REGISTRY: "https://gitlab.example.com/api/v4/groups/<group_id>/packages/npm/"

install_dependencies:
  stage: build
  image: node:20
  script:
    - echo "//gitlab.example.com/api/v4/groups/<group_id>/packages/npm/:_authToken=${CI_JOB_TOKEN}" > .npmrc
    - npm ci
```

## Валидация и диагностика

### Проверка через API

```bash
# Список кешированных пакетов
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/dependency_proxy/cache" | jq

# Удаление конкретного пакета
curl --request DELETE \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/dependency_proxy/cache/<cache_id>"

# Очистка всего кеша
curl --request DELETE \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/dependency_proxy/cache"
```

### Ожидаемые результаты

| Команда | Успешный результат |
| :--- | :--- |
| `GET /dependency_proxy/cache` | JSON-массив с кешированными пакетами, каждый элемент содержит `id`, `package_name`, `size`, `created_at` |
| `DELETE /dependency_proxy/cache/<id>` | HTTP 204 No Content — пакет удалён из кеша |
| `DELETE /dependency_proxy/cache` | HTTP 204 No Content — весь кеш очищен |

### Проверка hit rate

```bash
# Проверка размера кеша
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/dependency_proxy/cache" | jq 'length'

# Проверка hit rate (логи GitLab)
grep "dependency_proxy" /var/log/gitlab/nginx/gitlab_access.log | \
  awk '{print $NF}' | sort | uniq -c | sort -nr
```

**Ожидаемый результат:** `200` или `304` для cache hit, `502`/`504` для upstream error.

### Проверка через GitLab UI

1. Перейдите в **Project → Packages & Registries → Dependency Proxy**
2. Убедитесь, что отображаются кешированные пакеты с размерами и датами
3. Проверьте, что TTL настроен в Admin Area → Packages → Dependency Proxy

## Граничные случаи и ограничения

### Air-gapped окружения

- **Первоначальное заполнение кеша:** При полностью air-gapped развёртывании Dependency Proxy не может загрузить артефакты из внешних реестров. Решения:
  - Предзаполнение кеша через промежуточный host с доступом к интернету
  - Использование внутреннего mirror/replica upstream-реестра
  - Ручная загрузка артефактов через API

### Cross-project и Group-level доступ

- Project-level proxy видит только кеш своего проекта
- Group-level proxy видит объединённый кеш всех проектов группы
- При переносе проекта между группами кеш не переносится автоматически

### Fallback при недоступности upstream

- При недоступности upstream-реестра Dependency Proxy отдаёт закешированные артефакты, если TTL не истёк
- Если артефакт не закеширован — сборка завершается ошибкой
- Настройте retry-логику в CI/CD pipeline для устойчивости

### Ограничения

- **Размер артефактов:** Зависит от настроек `max_artifact_size` в `gitlab.rb` (по умолчанию 500 MB)
- **Количество пакетов:** Ограничено дисковым пространством object store
- **Аутентификация upstream:** Если upstream-реестр требует аутентификацию, Dependency Proxy не сможет закешировать такие артефакты без дополнительной настройки credentials
- **Private upstream registries:** Поддерживаются только при явной настройке credentials в GitLab

### Migration и очистка

- При изменении настроек TTL старые артефакты остаются в кеше до следующего запроса или ручной очистки
- При удалении проекта кеш Dependency Proxy удаляется вместе с проектом
- Group-level proxy не наследует кеш при создании новой группы

## Performance tuning

### TTL кеша

Настройте TTL в Admin Area → Packages → Dependency Proxy:

| Пакетный менеджер | Рекомендуемый TTL | Обоснование |
| :--- | :--- | :--- |
| **npm** | 7 дней | Стабильные версии, редко меняются |
| **Maven** | 14 дней | Большие артефакты, дорогая загрузка |
| **PyPI** | 7 дней | Частые обновления, но stable версии стабильны |
| **Go** | 14 дней | Модули rarely меняются после релиза |
| **NuGet** | 7 дней | Стабильные пакеты |
| **RubyGems** | 7 дней | Стабильные версии |
| **Conan** | 14 дней | Большие бинарные пакеты |

### Мониторинг использования

```bash
# Проверка размера кеша
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/dependency_proxy/cache" | jq 'length'

# Проверка hit rate (логи GitLab)
grep "dependency_proxy" /var/log/gitlab/nginx/gitlab_access.log | \
  awk '{print $NF}' | sort | uniq -c | sort -nr
```

**Ожидаемый результат:** hit rate >80% для здорового кеша.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` при загрузке | CI_JOB_TOKEN не имеет scope `read_package_registry` | Используйте Project Access Token с нужным scope |
| `404 Not Found` для пакета | Пакет не кеширован или удалён из upstream | Проверьте upstream реестр, кеш может быть очищен |
| Slow first build | Кеш пуст, первый download из upstream | Ожидаемо, последующие builds будут быстрее |
| Air-gapped не работает | Нет доступа к upstream при первом запросе | Предзаполните кеш вручную или используйте mirror |
| Hit rate <50% | Слишком короткий TTL или частые обновления зависимостей | Увеличьте TTL, проверьте lock-файлы |
| Кеш заполняет диск | Нет лимитов или TTL слишком длинный | Настройте `max_artifact_size` и TTL |
| Group-level proxy не работает | Нет прав Group Owner или proxy не включён на уровне группы | Проверьте права и настройки в Group → Packages |
| Conan/NuGet/RubyGems не кешируются | Неверная конфигурация пакетного менеджера | Проверьте URL registry и auth в конфигурации |
| `502 Bad Gateway` при доступе к proxy | Rails или Nginx не работает | Проверьте `gitlab-ctl status`, логи `/var/log/gitlab/nginx/gitlab_error.log` |

## Best Practices

### Разработка (Dev)

1. **Используйте Dependency Proxy для всех внешних зависимостей:** Ускоряет сборку и обеспечивает reproducibility.
2. **Настройте group-level proxy:** Для команд с несколькими проектами — общий кеш снижает duplicate downloads.
3. **Версионируйте lock-файлы:** `package-lock.json`, `go.sum`, `requirements.txt` — должны быть в репозитории.
4. **Используйте `CI_JOB_TOKEN` вместо Personal Access Token:** Для CI/CD pipeline `CI_JOB_TOKEN` имеет минимальные необходимые права.

### Эксплуатация (DevOps/SRE)

1. **Мониторьте место, занятое кешем Dependency Proxy:** Кеш хранится на объектном хранилище или локальном диске. Мониторйте utilisation.
2. **Ограничьте доступ к Dependency Proxy:** Только authorised projects/groups должны иметь доступ.
3. **Используйте отдельный bucket/путь:** Для Dependency Proxy выделите отдельный bucket или путь на объектном хранилище.
4. **Резервное копирование конфигурации:** Регулярно бэкапируйте конфигурацию Dependency Proxy (не сам кеш — он восстанавливается из upstream).
5. **Настройте оповещения по hit rate:** Установите пороговое значение 70% и алерт при падении ниже.

### Sysadmin

1. **Настройте TTL:** По умолчанию TTL может быть слишком длинным. Настройте в зависимости от частоты обновлений пакетов.
2. **Ограничьте размер кеша:** Установите лимит на размер кеша для предотвращения заполнения диска через `max_artifact_size` в `gitlab.rb`.
3. **Мониторьте hit rate:** Низкий hit rate (>80% misses) указывает на проблемы с кешированием или TTL.
4. **Настройте отдельный object store:** Для Dependency Proxy выделите отдельный bucket/контейнер, чтобы избежать влияния на другие сервисы GitLab.
5. **Регулярно обновляйте GitLab:** Каждый релиз содержит исправления для Package Registry и Dependency Proxy.

## Дополнительная информация

### См. также

- **[Container Registry в GitLab CI/CD](./container_registry.md)** — работа с Container Registry
- **[Air-gapped GitLab CI](../Tutorials/proxy_air_gapped_gitlab_ci.md)** — настройка air-gapped окружения
- **[Управление Package Registry](../Tutorials/package_registry_management.md)** — полное руководство по Package Registry
- **[CI/CD Security Hardening](./cicd_security_hardening.md)** — защита CI/CD

### Внешние ресурсы

- [GitLab: Dependency Proxy](https://docs.gitlab.com/ee/user/packages/dependency_proxy/)
- [GitLab: Group-level Dependency Proxy](https://docs.gitlab.com/ee/user/packages/group_level_dependency_proxy.html)
