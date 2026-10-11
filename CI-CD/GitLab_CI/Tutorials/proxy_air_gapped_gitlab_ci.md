# Proxy и Air-Gapped GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

* **Air-Gapped Environment** — изолированная среда без прямого доступа к публичному интернету. Весь трафик маршрутизируется через внутренние каналы.
* **Proxy** — промежуточный сервер для управления исходящими HTTP/HTTPS-запросами из Runner'ов и GitLab Server.
* **Dependency Proxy** — встроенный в GitLab кеширующий прокси для зависимостей пакетных менеджеров (npm, Maven, PyPI, Go и др.). Полная теория и конфигурация описаны в **[GitLab Dependency Proxy](../Advanced/dependency_proxy.md)**.
* **Internal Registry Mirror** — локальная реплика внешнего registry (Docker Hub, npm, PyPI), обеспечивающая доступ к образам и пакетам без выхода в интернет.
* **NO_PROXY** — список адресов и доменов, для которых прокси не используется; трафик идёт напрямую.
* **DinD (Docker-in-Docker)** — режим запуска Docker-демона внутри контейнера CI-задачи.
* **Runner Executor** — плагин GitLab Runner, определяющий, где и как выполняются задачи (Docker, Kubernetes, Shell, Fleet).
* **Offline Bundle** — архив с образами, пакетами и конфигурациями, переносимый в air-gapped среду через физические носители.

## Предварительные требования

| Роль | Требования |
|:---|:---|
| **Dev** | Понимание синтаксиса `.gitlab-ci.yml`, базовые знания пакетных менеджеров (npm, pip, Maven); роль Developer/Maintainer в проекте |
| **DevOps/SRE** | Доступ к GitLab Admin Area для настройки Dependency Proxy и registry mirror; доступ к логам Runner'ов и GitLab для диагностики сети |
| **Sysadmin** | Root-доступ к GitLab Server и Runner хостам; доступ к firewall, DNS, NTP; знание object store (S3/MinIO) для production |

**Инфраструктура:**
* GitLab CE/EE 17.x–19.x, зарегистрированный Runner 17.x–19.x
* Внутренний HTTP/HTTPS-proxy (Squid, Nginx, HAProxy) с доступом к внешним registry для начального заполнения кеша
* Внутренний registry mirror (Harbor, Nexus, Sonatype, GitLab Container Registry) для Docker-образов и пакетов
* DNS и NTP синхронизация между GitLab Server, Runner'ами и proxy
* Для Kubernetes Executor: NetworkPolicy, разрешающая egress к внутренним registry и GitLab API
* Хранилище для offline bundle: сетевой share (NFS, SMB) или физический переносимый носитель

## Основные концепции

### Архитектура доступа в air-gapped среде

Runner работает по pull-модели: инициирует исходящие соединения к GitLab API и внутренним registry. В air-gapped среде весь внешний трафик маршрутизируется через corporate proxy или полностью отсутствует.

```text
Pipeline Runner → [Internal Proxy / Direct] → GitLab Server
                                    → Internal Registry Mirror
                                    → Dependency Proxy cache
```

### Стратегии обеспечения доступа к зависимостям

| Стратегия | Когда использовать | Описание |
|:---|:---|:---|
| **Dependency Proxy** | GitLab-managed проекты с npm/PyPI/Maven | Кеширует артефакты на стороне GitLab; минимальная настройка |
| **Internal Registry Mirror** | Docker-образы и крупные бинарные артефакты | Полная или частичная реплика Docker Hub и внешних registry |
| **Offline Bundle** | Полностью изолированные сегменты (no proxy) | Физический перенос образов и пакетов |
| **Group-level Dependency Proxy** | Несколько проектов с overlapping зависимостями | Общий кеш для всей группы, снижающий дублирование |

### Жизненный цикл запроса зависимости

```text
Runner запрашивает пакет
    ├─ Dependency Proxy hit → отдать из кеша
    ├─ Internal Mirror hit → отдать из внутреннего registry
    ├─ External через Proxy → загрузить → вернуть Runner'у
    └─ Offline Bundle → загрузить из локального хранилища
```

## Практические сценарии

### Сценарий 1: Настройка GitLab Dependency Proxy

Dependency Proxy кеширует артефакты npm, Maven, PyPI и других пакетных менеджеров. Настройка выполняется на уровне проекта или группы.

```yaml
# .gitlab-ci.yml
variables:
  HTTP_PROXY: "http://proxy.internal:3128"
  HTTPS_PROXY: "http://proxy.internal:3128"
  NO_PROXY: "localhost,127.0.0.1,gitlab.example.com,registry.gitlab.example.com"

stages:
  - build

build:
  stage: build
  image: node:22-bookworm
  script:
    - npm config set registry https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/packages/npm/
    - npm ci
    - npm run build
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

**Валидация:**
```bash
# Проверка кешированных пакетов через API
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/dependency_proxy/cache" | jq 'length'
# → Число >= 0 (при первом запуске кеш пуст, после сборки заполняется)
```

### Сценарий 2: Air-Gapped установка зависимостей

Для полностью изолированных сред используются внутренние registry mirror вместо публичных.

```yaml
stages:
  - build

variables:
  NPM_CONFIG_REGISTRY: "http://internal-npm.example.com"
  PIP_INDEX_URL: "http://internal-pypi.example.com/simple"
  MAVEN_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"

build:
  stage: build
  image: python:3.13-slim
  script:
    - pip install -r requirements.txt --index-url http://internal-pypi.example.com/simple
    - python -m py_compile src/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
```bash
# Проверка доступности внутреннего registry
curl -I http://internal-pypi.example.com/simple/numpy/
# → HTTP/1.1 200 OK
```

### Сценарий 3: Proxy конфигурация для Docker DinD

При использовании Docker-in-Docker в air-gapped среде proxy должен быть настроен на уровне Docker daemon.

```yaml
variables:
  DOCKER_BUILDKIT: "1"
  DOCKER_CONFIG: $CI_PROJECT_DIR/.docker
  HTTP_PROXY: "http://proxy.internal:3128"
  HTTPS_PROXY: "http://proxy.internal:3128"
  NO_PROXY: "localhost,127.0.0.1,gitlab.example.com,registry.gitlab.example.com"

stages:
  - build

before_script:
  - mkdir -p $DOCKER_CONFIG
  - |
    cat > $DOCKER_CONFIG/config.json <<EOF
    {
      "proxies": {
        "default": {
          "httpProxy": "http://proxy.internal:3128",
          "httpsProxy": "http://proxy.internal:3128",
          "noProxy": "localhost,127.0.0.1,gitlab.example.com,registry.gitlab.example.com"
        }
      }
    }
    EOF

build:
  stage: build
  image: docker:27
  services:
    - docker:27-dind
  script:
    - docker info
    - docker build --build-arg HTTP_PROXY=http://proxy.internal:3128 \
        --build-arg HTTPS_PROXY=http://proxy.internal:3128 .
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Валидация:**
```bash
# Проверка proxy переменных в задаче
env | grep -i proxy
# → HTTP_PROXY=http://proxy.internal:3128
# → HTTPS_PROXY=http://proxy.internal:3128
# → NO_PROXY=localhost,127.0.0.1,gitlab.example.com,registry.gitlab.example.com
```

### Сценарий 4: Создание и использование Offline Bundle

Для сред без доступа к proxy создаётся offline bundle с образами и пакетами.

```bash
#!/bin/bash
# Создание offline bundle на машине с доступом к интернету

set -euo pipefail

BUNDLE_DIR="/tmp/gitlab-offline-bundle"
mkdir -p "$BUNDLE_DIR"/{images,python-packages,node-packages,maven-packages,gitlab-packages}

# 1. GitLab Runner образ
docker save gitlab/gitlab-runner:17.9.1 -o "$BUNDLE_DIR/images/gitlab-runner.tar"

# 2. Docker DinD образ
docker save docker:27-dind -o "$BUNDLE_DIR/images/docker-dind.tar"

# 3. Python пакеты
pip download -r requirements.txt -d "$BUNDLE_DIR/python-packages"

# 4. Node зависимости (lock-file анализ)
cd frontend && npm ci --package-lock-only && \
  tar czf "$BUNDLE_DIR/node-packages/node-modules.tar.gz" node_modules && \
  cd ..

# 5. Maven зависимости
cd backend && mvn dependency:go-offline -Dmaven.repo.local="$BUNDLE_DIR/maven-packages" && \
  cd ..

# 6. GitLab packages через API (если есть доступ)
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages" | \
  jq -r '.[]._links.web_path' | while read pkg; do
    curl -L "$pkg" -o "$BUNDLE_DIR/gitlab-packages/$(basename $pkg)"
  done

# 7. Упаковка bundle
tar czf gitlab-offline-bundle.tar.gz -C /tmp gitlab-offline-bundle

echo "Bundle created: $(du -sh gitlab-offline-bundle.tar.gz)"
```

```yaml
# .gitlab-ci.yml — использование offline bundle
stages:
  - setup
  - build

variables:
  OFFLINE_BUNDLE: "/tmp/gitlab-offline-bundle.tar.gz"

setup-offline:
  stage: setup
  image: alpine:3.20
  script:
    - tar xzf "$OFFLINE_BUNDLE" -C /tmp/
    - docker load -i /tmp/gitlab-offline-bundle/images/gitlab-runner.tar
    - docker load -i /tmp/gitlab-offline-bundle/images/docker-dind.tar
    - pip install --no-index --find-links=/tmp/gitlab-offline-bundle/python-packages -r requirements.txt
    - tar xzf /tmp/gitlab-offline-bundle/node-packages/node-modules.tar.gz -C frontend/
  rules:
    - if: $CI_PIPELINE_SOURCE == "manual"
```

**Валидация:**
```bash
# Проверка целостности bundle
tar tzf gitlab-offline-bundle.tar.gz | head
# → Список файлов внутри архива

# Проверка размера
du -sh gitlab-offline-bundle.tar.gz
# → Реальный размер с учётом всех зависимостей
```

### Сценарий 5: Internal Registry Mirror для Docker

Настройка registry mirror на уровне Docker daemon в Runner'е.

```yaml
variables:
  DOCKER_REGISTRY_MIRROR: "http://internal-registry.example.com:5000"

stages:
  - build

build:
  stage: build
  image: docker:27
  services:
    - docker:27-dind
  script:
    - |
      # Настройка mirroring через переменную окружения
      export DOCKER_OPTS="--registry-mirror=http://internal-registry.example.com:5000"
      dockerd --host=unix:///var/run/docker.sock --storage-driver=overlay2 &
      sleep 5
      docker info | grep -i mirror
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

Альтернативная конфигурация через `daemon.json` (для Shell executor):

```bash
# /etc/docker/daemon.json на Runner хосте
cat > /etc/docker/daemon.json <<EOF
{
  "registry-mirrors": [
    "http://internal-registry.example.com:5000"
  ],
  "insecure-registries": [
    "internal-registry.example.com:5000"
  ]
}
EOF

systemctl restart docker
```

**Валидация:**
```bash
# Проверка конфигурации mirror
docker info | grep -A 5 "Registry Mirrors"
# → Registry Mirrors:
#      http://internal-registry.example.com:5000

# Проверка pull через mirror
docker pull hello-world
# → Использует mirror, нет запросов к Docker Hub
```

### Сценарий 6: Network Isolation и проверка connectivity

Комплексная проверка сети в air-gapped среде.

```yaml
variables:
  HTTP_PROXY: "http://proxy.corp.example.com:8080"
  HTTPS_PROXY: "http://proxy.corp.example.com:8080"
  NO_PROXY: "localhost,127.0.0.1,.internal.example.com,gitlab.example.com,registry.gitlab.example.com"

stages:
  - build
  - deploy

build:
  stage: build
  image: alpine:3.20
  script:
    - |
      echo "=== Connectivity Tests ==="
      curl -sf https://gitlab.example.com/api/v4/version || echo "GitLab unreachable"
      curl -sf http://proxy.corp.example.com || echo "Proxy unreachable"
      echo "Build completed in air-gapped environment"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:
  stage: deploy
  image: registry.gitlab.com/gitlab-org/cluster-tools/helm-install-image:1.0.0
  script:
    - helm upgrade --install myapp ./charts/app \
        --namespace production \
        --set image.tag=$CI_COMMIT_SHORT_SHA
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Валидация:**
```bash
# Диагностический job
network_test:
  stage: test
  image: alpine:3.20
  script:
    - apk add --no-cache curl bind-tools nmap-ncat
    - nslookup gitlab.example.com
    - dig registry.gitlab.example.com
    - curl -I https://gitlab.example.com/api/v4/version
    - nc -zv -w5 gitlab.example.com 443
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

## Валидация и проверка

Выполните проверки после настройки air-gapped среды:

1. **Dependency Proxy:** Project → Packages & Registries → Dependency Proxy — отображаются кешированные пакеты
   - *Ожидаемый результат:* список пакетов с именем, версией и размером; hit rate >80% после нескольких сборок
2. **Package Registry:** Project → Packages & Registries → Package Registry — опубликованные пакеты видны
   - *Ожидаемый результат:* пакет отображается с версией и форматом
3. **Network connectivity:** `curl -I https://gitlab.example.com/api/v4/version`
   - *Ожидаемый результат:* `HTTP/2 200` или `HTTP/1.1 200`
4. **Proxy переменные:** `env | grep -i proxy` в задаче
   - *Ожидаемый результат:* `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` установлены корректно
5. **Registry mirror:** `docker info | grep -i mirror`
   - *Ожидаемый результат:* отображается configured mirror
6. **Offline mode:** `docker images` после загрузки bundle
   - *Ожидаемый результат:* все необходимые образы присутствуют локально
7. **DNS resolution:** `nslookup gitlab.example.com` и `dig registry.gitlab.example.com`
   - *Ожидаемый результат:* корректно разрешаются внутренние адреса

## Troubleshooting

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Cannot reach registry** | Нет доступа к внешнему registry | Используйте Internal Registry Mirror или Offline Bundle |
| **Dependency Proxy не возвращает кеш** | Кеш пуст или TTL истёк | Предзаполните кеш; проверьте TTL в Admin Area |
| **npm/pip install failed: 404** | Пакетный registry недоступен | Настройте Internal Package Registry или Dependency Proxy |
| **Docker pull failed** | Образ не в кеше и нет доступа к upstream | Загрузите образ заранее через `docker save/load` |
| **Proxy переменные игнорируются** | Неверный синтаксис или регистр переменных | Используйте `HTTP_PROXY`/`HTTPS_PROXY` без `http://` в DinD; для Docker daemon используйте `no_proxy` в нижнем регистре |
| **Network timeout** | Firewall блокирует запросы | Проверьте firewall rules, proxy настройки, MTU на интерфейсах |
| **SSL certificate error** | Самоподписанный сертификат | Добавьте CA-сертификат в `/usr/local/share/ca-certificates/` и обновите trust store |
| **DNS не разрешает имена** | DNS сервер недоступен или неправильный `/etc/resolv.conf` | Проверьте доступность DNS (UDP/TCP 53); настройьте внутренний DNS |
| **DinD: соединение с docker:dind падает** | TLS не настроен или порт 2375 открыт без ограничений | Используйте TLS (`DOCKER_TLS_CERTDIR`); ограничьте порт только Runner'ом |

## Лучшие практики (Best Practices)

### Безопасность

* Используйте Dependency Proxy для минимизации внешних запросов
* Настройте whitelist для `NO_PROXY` — только доверенные внутренние домены
* Используйте VPN или dedicated tunnel для доступа к GitLab instance из air-gapped среды при необходимости
* Включите audit logging для всех proxy запросов и обращений к registry
* Используйте RBAC для Internal Package Registry: только Maintainer может publish, Guest — только pull
* Не открывайте порт 2375 для DinD без TLS — это критическая уязвимость
* Храните offline bundle в зашифрованном хранилище; контролируйте доступ физически

### Производительность

* Кешируйте зависимости в Dependency Proxy с recommended TTL:
  * npm/PyPI/NuGet/RubyGems: 7 дней
  * Maven/Go/Conan: 14 дней (большие артефакты, редкие обновления)
* Используйте Internal Package Registry для частых внутренних зависимостей
* Предварительно загружайте Docker образы через `docker save/load` или registry mirror
* Используйте `--no-cache-dir` для pip в CI
* Настройте pre-build stage для загрузки зависимостей

### Надёжность (SRE)

* Регулярно экспортируйте пакеты и образы для air-gapped среды
* Документируйте процедуру обновления offline bundle
* Используйте version pinning для всех зависимостей
* Настройте алерты на недоступность Internal Registry и Dependency Proxy
* Тестируйте offline mode регулярно: симулируйте отключение proxy
* Мониторьте hit rate Dependency Proxy; порог алерта: <70%
* Используйте immutable tags для production образов; запретите overwrite `main`/`production`

### Эксплуатация

* Размещайте Runner'ы в том же дата-центре, что и GitLab Server, для снижения задержки
* Настраивайте `check_interval` с запасом при высокой задержки сети (>200 ms → 5–10 секунд)
* Используйте ephemeral Runner'ы для снижения риска утечки данных
* Документируйте firewall/NetworkPolicy правила для каждого Runner'а
* Проверяйте MTU после изменений сети (VPN, VLAN, оверлеи); единый MTU на всех участках пути

## Крайние случаи (Edge Cases)

* **Полная изоляция (no proxy):** Среда без любого proxy требует offline bundle и pre-loaded образов. Тестируйте восстановление из bundle регулярно.
* **Смена upstream registry:** При изменении URL upstream-реестра Dependency Proxy не переносит кеш автоматически. Очистите кеш через API.
* **Cross-project dependency proxy:** Project-level proxy видит только кеш своего проекта. Для overlapping зависимостей используйте group-level proxy.
* **Private upstream registries:** Если upstream требует аутентификацию, Dependency Proxy не сможет закешировать артефакты без явной настройки credentials в GitLab.
* **Large artifacts:** Артефакты >500 MB (по умолчанию `max_artifact_size`) не кешируются. Увеличьте лимит в `gitlab.rb` или используйте отдельный object store.
* **Network partitions:** При разрыве connectivity между Runner и GitLab job завершается с timeout. Настройте `retry` в `.gitlab-ci.yml` или увеличьте `job_timeout`.
* **MTU mismatch:** Разный MTU на сетевом пути приводит к фрагментации или тихому падению HTTPS. Используйте `ping -M do -s 1472` для диагностики.

## Очистка

```bash
# Очистка Dependency Proxy кеша через API
curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/dependency_proxy/cache" | \
  jq -r '.[].id' | xargs -I {} \
  curl --request DELETE --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$CI_API_V4_URL/projects/$CI_PROJECT_ID/dependency_proxy/cache/{}"

# Очистка Internal Package Registry
glab api groups/$GROUP_ID/packages | jq -r '.[] | select(.package_type == "npm") | .id' | \
  xargs -I {} glab api groups/$GROUP_ID/packages/{} -X DELETE

# Очистка Docker образов на Runner хосте
docker system prune -a --filter "until=720h"
```

## Дополнительная информация

### Смотрите также

* **[GitLab Dependency Proxy — полное руководство](../Advanced/dependency_proxy.md)** — кеширование зависимостей, TTL, group-level proxy, troubleshooting
* **[GitLab Package Registry Management](../Tutorials/package_registry_management.md)** — публикация и управление пакетами npm/Maven/PyPI/NuGet/Go
* **[Сетевые требования для GitLab Runner](../Advanced/runner_networking_requirements.md)** — firewall, NetworkPolicy, DinD сеть, proxy на уровне Runner'а
* **[Container Registry Management](../Tutorials/container_registry_management.md)** — управление Docker-образами, registry mirror, lifecycle policies
* **[GitLab Runner в Docker Compose](../Tutorials/gitlab_runner_docker_compose.md)** — развёртывание Runner'ов в air-gapped среде
* **[GitLab Administration](https://docs.gitlab.com/ee/administration/)** — официальная документация по администрированию

### Внешние ресурсы

* [GitLab: Dependency Proxy](https://docs.gitlab.com/ee/user/packages/dependency_proxy/)
* [GitLab: Group-level Dependency Proxy](https://docs.gitlab.com/ee/user/packages/group_level_dependency_proxy.html)
* [GitLab: Air-Gapped Installations](https://docs.gitlab.com/ee/install/airgap.html)
* [Docker: Registry Mirror](https://docs.docker.com/docker-hub/repos/mirror/)
