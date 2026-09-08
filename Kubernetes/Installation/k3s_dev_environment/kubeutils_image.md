# Вспомогательный образ Kubeutils

Руководство по созданию универсального образа с утилитами для работы с Kubernetes в пайплайнах CI/CD. Образ используется для сборки, валидации и развертывания приложений в кластере K3s.

Контекст: Часть серии по созданию dev-окружения в K3s. Образ используется в пайплайнах GitLab CI для взаимодействия с Harbor и Kubernetes. См. [Архитектура K3s](./k3s_architecture.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Kubeutils** | Вспомогательный образ с набором утилит CLI: `kubectl`, `helm`, `regctl`, `kubeconform`. Используется в CI/CD для управления жизненным циклом приложений в Kubernetes. |
| **Kaniko** | Инструмент для сборки образов контейнеров внутри контейнера или Kubernetes без зависимости от Docker-демона. Стандарт безопасности для современных CI/CD систем. См. [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md). |
| **Build Args** | Переменные, передаваемые в Dockerfile во время сборки (`--build-arg`). Позволяют изменять версии утилит без правки кода Dockerfile. |
| **SBOM (Software Bill of Materials)** | Полный перечень всех программных компонентов и зависимостей в образе. Необходим для аудита безопасности. |
| **OCI (Open Container Initiative)** | Стандарт для форматов образов и сред выполнения, обеспечивающий совместимость между Docker, Podman и другими инструментами. |
| **Digest** | SHA256-хеш содержимого OCI-манифеста. Используется для точной идентификации образа, гарантируя неизменность артефакта (в отличие от тегов, которые могут перезаписываться). |
| **Multi-arch Build** | Сборка образа для нескольких архитектур (amd64, arm64) из одного Dockerfile с использованием `$TARGETARCH` и манифест-листа. Позволяет одним образом обслуживать разные платформы. |

Навигация: [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md) | [Docker Best Practices](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md) | [GitLab CI Basics](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)

---

## Основные концепции

### Назначение и преимущества образа

Образ `kubeutils` предоставляет единое, воспроизводимое окружение для выполнения задач в пайплайнах:

| Утилита | Назначение в пайплайне |
| :--- | :--- |
| **`kubectl`** | Взаимодействие с API Kubernetes (развертывание, диагностика, управление ресурсами). |
| **`helm`** | Управление Helm-чартами (установка, обновление, откат, шаблонизация). |
| **`regctl`** | Работа с OCI реестрами (тегирование, копирование образов, инспекция манифестов без Docker). |
| **`kubeconform`** | Валидация манифестов Kubernetes против схем API (OpenAPI), замена устаревшего `kubeval`. |

**Преимущества единого образа:**
- **Воспроизводимость:** Одинаковые версии инструментов во всех проектах исключают ошибки "разницы версий".
- **Скорость:** Исключается этап установки инструментов в каждом джобе пайплайна.
- **Безопасность:** Централизованное обновление версий и сканирование единого базового образа на CVE.
- **Масштабируемость:** Легкое расширение набора инструментов для всей компании через обновление одного репозитория.

### Почему Kaniko для сборки?

В средах Kubernetes и GitLab CI доступ к Docker-демону ограничен. Kaniko решает проблемы безопасности и архитектуры.

| Подход | Требования | Безопасность | Особенности |
| :--- | :--- | :--- | :--- |
| **Docker-in-Docker (dind)** | Привилегированный режим | Низкая | Требует `--privileged`, что опасно в мультитеннантных кластерах. |
| **Docker-outside-of-Docker (DooD)** | Монтирование `docker.sock` | Низкая | Контейнер получает полный контроль над хостовым Docker. |
| **Kaniko** | Стандартный контейнер | Высокая | Работает в userspace, не требует демон или привилегии ядра. |

**Особенности Kaniko:**
- Выполняет инструкции Dockerfile внутри файловой системы контейнера без демона.
- Идеально подходит для **Pod Security Standards: Restricted**.
- С июня 2025 года (после архивации проекта Google) стандартом является форк от сообщества — **`osscontainertools/kaniko`**.

### Выбор базового образа (Alpine Linux)

Alpine Linux остается оптимальным выбором для утилит благодаря:
- **Минимальному размеру:** Базовый слой ~5 МБ. Итоговый образ с утилитами остается компактным, что ускоряет `pull` в пайплайнах.
- **Безопасности:** Меньшее количество пакетов снижает поверхность атаки.
- **Совместимости:** Большинство облачных инструментов (Go-бинарники) работают в среде `musl` напрямую или через `gcompat`.

**Ограничение Alpine:** Некоторые Go-бинарники, скомпилированные с использованием `glibc`, могут не работать в Alpine без `gcompat`. В таких случаях:
1. Используйте статически скомпилированные бинарники (см. Dockerfile — все утилиты в примере являются статическими).
2. Установите `gcompat` как запасной вариант: `apk add --no-cache gcompat`.
3. Проверяйте совместимость перед добавлением новой утилиты: `ldd /usr/local/bin/tool` — если показывает `not found`, требуется `gcompat`.

### Стратегия фиксации версий (Version Pinning)

В enterprise CI/CD критично фиксировать конкретные версии зависимостей, а не использовать floating tags (`latest`, `stable`).

**Иерархия надежности (от наиболее к наименее надежной):**

| Метод | Пример | Надежность | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Digest** | `alpine:3.24.1@sha256:abc123...` | Максимальная | Продакшен-пайплайны, где критична воспроизводимость |
| **SemVer тег** | `alpine:3.24.1` | Высокая | Стандартный CI/CD (рекомендуется) |
| **Minor тег** | `alpine:3.24` | Средняя | Только dev/test окружения |
| **Floating tag** | `alpine:latest` | Низкая | Запрещено в пайплайнах |

**Почему Digest лучше тега:** Тег — это mutable-ссылка, которую владелец образа может перезаписать. Digest — это immutable SHA256-хеш содержимого. Использование Digest гарантирует, что между сборкой и деплоем не произойдет тайной подмены содержимого.

**Пример с Digest в Dockerfile:**
```dockerfile
# Фиксация по Digest (максимальная надежность)
FROM alpine:3.24.1@sha256:961a2e064f2c4c563e10cf5e2c3f2c4f8d4b2e1a3c5d6f7e8b9a0c1d2e3f4a5b

# Фиксация по SemVer тегу (рекомендуется)
FROM alpine:3.24.1
```

**Рекомендация для kubeutils:** Используйте SemVer теги для базовых образов и утилит. Digest-пиннинг применяйте только в критических продакшен-пайплайнах, где требуется полная воспроизводимость.

### Мультиархитектурная стратегия (Multi-arch)

Dockerfile поддерживает сборку для `amd64` и `arm64` через автоматическое определение архитектуры. Это позволяет использовать один образ как на x86-серверах, так и на ARM-устройствах (Apple Silicon, Raspberry Pi, ARM-серверы).

**Механизм работы:**
```dockerfile
# Автоопределение архитектуры (Alpine уже поддерживает multi-arch)
ARG TARGETARCH
# Или черезuname:
RUN ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
```

**Важные особенности:**
- Kaniko, kubectl, helm — все предоставляют мультиархитектурные бинарники.
- regctl и kubeconform доступны для обеих архитектур.
- При использовании Kaniko в multi-arch пайплайне укажите `--platform` явно.

### Жизненный цикл образа (Image Lifecycle)

Регулярное обновление образа необходимо для:
- Исправления CVE в утилитах и базовом образе.
- Обновления версий kubectl/helm для поддержки новых API.
- Соответствия политикам безопасности (non-root, read-only FS).

**Рекомендуемый процесс:**
1. **Ежемесячно:** Проверка новых версий утилит.
2. **Ежеквартально:** Полная пересборка образа с обновлёнными зависимостями.
3. **По событию:** Немедленное обновление при обнаружении критического CVE.
4. **Автоматизация:** Настройте Renovate/Dependabot для автоматических PR с обновлениями версий.

### Безопасность цепочки поставок (Supply Chain)

В 2026 году образ должен соответствовать стандартам безопасности:
1.  **Non-root:** Запуск процессов от пользователя с UID 1000.
2.  **SBOM Generation:** Генерация спецификации состава (например, через Syft в пайплайне) для загрузки в Harbor.
3.  **Image Signing:** Подпись образа через Cosign для гарантии того, что в кластер попадет именно тот артефакт, который прошел CI.
4.  **Minimal Base:** Использование максимально компактного базового образа для снижения поверхности атаки.

---

## Практические сценарии

### 1. Dockerfile для kubeutils (Версия Август 2026)

Dockerfile поддерживает многоплатформенность (`amd64`/`arm64`) и настройку безопасности.

```dockerfile
# Аргументы для управления версиями
ARG ALPINE_VERSION=3.24.1
ARG KUBE_VERSION=v1.36.3
ARG HELM_VERSION=v4.2.3
ARG REGCLIENT_VERSION=v0.11.5
ARG KUBECONFORM_VERSION=v0.8.0

FROM alpine:${ALPINE_VERSION}

# Установка системных зависимостей (только необходимые)
RUN apk add --no-cache ca-certificates curl git bash tar gzip

# Создание непривилегированного системного пользователя
RUN addgroup -S kube && adduser -S kube -G kube

# Установка бинарных файлов утилит
RUN set -x && \
    ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') && \
    # 1. Kubectl (August 2026 release)
    curl -LO "https://dl.k8s.io/release/${KUBE_VERSION}/bin/linux/${ARCH}/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    # 2. Helm v4
    curl -L "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH}.tar.gz" | tar -xzO linux-${ARCH}/helm > /usr/local/bin/helm && \
    chmod +x /usr/local/bin/helm && \
    # 3. regclient (regctl)
    curl -L "https://github.com/regclient/regclient/releases/download/${REGCLIENT_VERSION}/regctl-linux-${ARCH}" -o /usr/local/bin/regctl && \
    chmod +x /usr/local/bin/regctl && \
    # 4. kubeconform
    curl -L "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-${ARCH}.tar.gz" | tar -xzO kubeconform > /usr/local/bin/kubeconform && \
    chmod +x /usr/local/bin/kubeconform

# Настройка рабочего окружения
USER kube
WORKDIR /home/kube

# Валидация установки
RUN kubectl version --client && \
    helm version && \
    regctl version && \
    kubeconform -v
```

**Пояснение к ключевым параметрам:**
- `--no-cache` для `apk` — уменьшает размер образа, не кэшируя индекс пакетов.
- `addgroup -S kube && adduser -S kube -G kube` — минимальный непривилегированный пользователь (SYSTEM GROUP, SYSTEM USER).
- `set -x` — вывод каждой команды в лог для отладки при ошибке сборки.
- `tar -xzO` — распаковка в stdout без создания промежуточных файлов (эффективнее по диску).

### 2. Сборка через Kaniko (GitLab CI)

Пример сборки с использованием актуального форка Kaniko и поддержкой Registry Harbor.

```yaml
build-kubeutils:
  stage: build
  image:
    name: osscontainertools/kaniko:v1.28.2-debug
    entrypoint: [""]
  tags:
    - global
  variables:
    KUBE_VERSION: "v1.36.3"
    HELM_VERSION: "v4.2.3"
  script:
    # 1. Настройка аутентификации в Harbor
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$INTERNAL_REGISTRY\":{\"username\":\"$REGISTRY_USER\",\"password\":\"$REGISTRY_PASS\"}}}" > /kaniko/.docker/config.json
    
    # 2. Сборка и отправка
    - /kaniko/executor \
        --context "dir://$CI_PROJECT_DIR" \
        --dockerfile "$CI_PROJECT_DIR/Dockerfile" \
        --destination "$INTERNAL_REGISTRY/library/kubeutils:latest" \
        --destination "$INTERNAL_REGISTRY/library/kubeutils:$KUBE_VERSION" \
        --build-arg KUBE_VERSION=$KUBE_VERSION \
        --build-arg HELM_VERSION=$HELM_VERSION \
        --registry-mirror "proxy.registry.local" \
        --registry-certificate /path/to/internal-ca.crt # Если используется свой CA
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
```

**Пояснение к флагам Kaniko:**
- `--context "dir://..."` — контекст сборки (директория, git URL или tarball).
- `--destination` — можно указать несколько раз для создания нескольких тегов одного образа.
- `--registry-mirror` — зеркало реестра для ускорения pull базовых образов.
- `--registry-certificate` — путь к CA-сертификату для TLS (self-signed Harbor).

### 3. Сборка мультиархитектурного образа

Сборка образа для обеих архитектур (amd64 + arm64) через Kaniko с манифест-листом.

```yaml
build-multiarch:
  stage: build
  tags:
    - global
  script:
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$INTERNAL_REGISTRY\":{\"username\":\"$REGISTRY_USER\",\"password\":\"$REGISTRY_PASS\"}}}" > /kaniko/.docker/config.json
    
    # Сборка для amd64
    - /kaniko/executor \
        --context "dir://$CI_PROJECT_DIR" \
        --dockerfile "$CI_PROJECT_DIR/Dockerfile" \
        --destination "$INTERNAL_REGISTRY/library/kubeutils:latest-amd64" \
        --platform=linux/amd64
    
    # Сборка для arm64
    - /kaniko/executor \
        --context "dir://$CI_PROJECT_DIR" \
        --dockerfile "$CI_PROJECT_DIR/Dockerfile" \
        --destination "$INTERNAL_REGISTRY/library/kubeutils:latest-arm64" \
        --platform=linux/arm64
    
    # Объединение в манифест-лист (требует regctl)
    - regctl manifest create "$INTERNAL_REGISTRY/library/kubeutils:latest" \
        "$INTERNAL_REGISTRY/library/kubeutils:latest-amd64" \
        "$INTERNAL_REGISTRY/library/kubeutils:latest-arm64"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
```

**Примечание:** regctl использует OCI API для создания манифест-листа без использования Docker CLI. Это позволяет объединять образы разных архитектур в единый тег.

### 4. Использование в пайплайнах (Валидация и Деплой)

Пример использования образа для проверки манифестов и развертывания через Helm.

```yaml
deploy-app:
  stage: deploy
  image: $INTERNAL_REGISTRY/library/kubeutils:v1.36.3
  script:
    # Валидация манифестов (строгий режим)
    - kubeconform -strict -ignore-missing-schemas manifests/
    
    # Деплой с ожиданием готовности
    - helm upgrade --install my-app ./chart \
        --namespace production \
        --atomic \
        --wait \
        --timeout 300s
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### 5. Интеграция regctl в пайплайны

regctl позволяет работать с OCI-реестрами без Docker CLI. Типовые задачи:

```yaml
# Копирование образов между реестрами
regctl copy harbor.internal/library/app:v1.0 harbor-backup.internal/library/app:v1.0

# Инспекция манифеста (проверка размера, слоёв,.digest)
regctl manifest get harbor.internal/library/app:v1.0 --format json

# Тегирование существующего образа (без пересборки)
regctl tag set harbor.internal/library/app:latest --digest sha256:abc123...

# Удаление тега
regctl tag rm harbor.internal/library/app:old-tag

# Проверка доступности образа
regctl manifest digest harbor.internal/library/app:v1.0
```

**Использование в CI для проверки публикации:**
```yaml
verify-publish:
  stage: verify
  image: $INTERNAL_REGISTRY/library/kubeutils:v1.36.3
  script:
    # Проверяем, что образ доступен в реестре
    - regctl manifest digest $INTERNAL_REGISTRY/library/myapp:$CI_COMMIT_SHA
    # Проверяем размер образа
    - regctl manifest get $INTERNAL_REGISTRY/library/myapp:$CI_COMMIT_SHA --format json | jq '.config.size'
```

### 6. Настройка зеркала реестра для offline/air-gapped сред

В изолированных средах требуется настроить зеркало реестра для ускорения pull базовых образов.

```yaml
# В .gitlab-ci.yml
variables:
  DOCKER_CONFIG: /kaniko/.docker

build-with-mirror:
  stage: build
  image:
    name: osscontainertools/kaniko:v1.28.2-debug
    entrypoint: [""]
  script:
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$INTERNAL_REGISTRY\":{\"username\":\"$REGISTRY_USER\",\"password\":\"$REGISTRY_PASS\"}}}" > /kaniko/.docker/config.json
    
    # Настройка зеркала для Docker Hub
    - |
      cat > /kaniko/.docker/config.json <<EOF
      {
        "auths": {
          "$INTERNAL_REGISTRY": {
            "username": "$REGISTRY_USER",
            "password": "$REGISTRY_PASS"
          }
        },
        "mirrors": {
          "docker.io": {
            "mirrors": [{"host": "mirror.internal:5000"}]
          }
        }
      }
      EOF
    
    - /kaniko/executor \
        --context "dir://$CI_PROJECT_DIR" \
        --dockerfile "$CI_PROJECT_DIR/Dockerfile" \
        --destination "$INTERNAL_REGISTRY/library/kubeutils:latest" \
        --registry-mirror "mirror.internal:5000" \
        --registry-certificate "/path/to/mirror-ca.crt"
```

**Примечание:** Зеркало реестра должно быть доступно из сети GitLab Runner. В air-gapped средах зеркало является единственным источником базовых образов.

---

## Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `exec: "docker": executable file not found` | Использование `docker build` вместо Kaniko в CI | Замените image на `osscontainertools/kaniko:v1.28.2-debug` |
| `error building image: mkdir /kaniko/workspace/rootfs: read-only file system` | Kaniko запущен с read-only rootfs | Убедитесь, что volume `emptyDir` примонтирован в `/kaniko/workspace` |
| `x509: certificate signed by unknown authority` | CA-сертификат Harbor не доверен | Монтируйте CA: `--registry-certificate /path/to/ca.crt` |
| `Helm v4: "this is not a valid chart repository"` | Использование Helm v2/v3 команды с Helm v4 | Используйте `helm registry login` для OCI-чартов |
| `kubeconform: unable to find schema for ...` | Отсутствие схемы для CRD | Добавьте флаг `-ignore-missing-schemas` или укажите `-schema-location` |
| `no such host: harbor.internal` | DNS не резолвится в контейнере | Проверьте DNS в CI-runner или добавьте `/etc/hosts` в скрипт |
| `permission denied: /home/kube/.cache/helm` | Права доступа к кэшу Helm от другого пользователя | Убедитесь, что `USER kube` установлен перед запуском Helm |
| `Kaniko: signaled to cancel` | Timeout при сборке большого образа | Увеличьте `--timeout` или оптимизируйте слои Dockerfile |

---

## Дополнительная информация

### Актуальность компонентов (август 2026)

| Компонент | Версия | Статус | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Alpine Linux** | 3.24.1 | Stable | Релиз от июня 2026. Актуальная ветка 3.24. |
| **Kubernetes (kubectl)** | v1.36.3 | Stable | Выпуск от 6 августа 2026. Полная поддержка API 1.36. |
| **Helm** | v4.2.3 | Stable | Мажорная версия v4 (прекращена поддержка v2/v3 в новых инсталляциях). |
| **regclient (regctl)** | v0.11.5 | Stable | Легковесная альтернатива Docker CLI для CI. |
| **kubeconform** | v0.8.0 | Stable | Стандарт де-факто для валидации схем OpenAPI. |
| **Kaniko (fork)** | v1.28.2 | Active | Используйте `osscontainertools/kaniko`. |

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **Устаревшие версии** | Уязвимости (CVE) в утилитах. | Настройте ежемесячное обновление образа через CI Scheduler. |
| **glibc зависимость** | Несовместимость некоторых бинарников с Alpine. | Используйте только статические бинарники или устанавливайте `gcompat`. |
| **Права доступа** | Ошибки записи в CI (например, Helm cache). | Helm в образе настроен на работу от `kube`, убедитесь в наличии прав на `/home/kube`. |
| **TLS/SSL** | Ошибки сертификатов Harbor. | Всегда передавайте `--registry-certificate` или монтируйте CA в `/kaniko/ssl/certs/`. |
| **Лимиты ресурсов** | `OOMKilled` при валидации больших чартов. | Выделяйте не менее 512Mi RAM для джобов с `kubeconform`. |
| **Floating tags** | Невоспроизводимые сборки из-за перезаписи тегов `latest`. | Фиксируйте версии по SemVer или Digest. |
| **Multi-arch** | Несовместимость бинарников с целевой архитектурой. | Проверяйте `uname -m` в Dockerfile перед установкой. |
| **Kubernetes версия** | `kubectl` несовместим с API-сервером старше/младше на 2 минорных версии. | Обновляйте kubectl при обновлении кластера. |

### Очистка и откат

**Удаление kubeutils из Harbor:**
```bash
# Через regctl
regctl tag rm harbor.internal/library/kubeutils:latest
regctl tag rm harbor.internal/library/kubeutils:v1.36.3

# Удаление всех тегов образа
regctl tag ls harbor.internal/library/kubeutils | while read tag; do
  regctl tag rm "harbor.internal/library/kubeutils:$tag"
done
```

**Откат CI/CD на предыдущую версию:**
1. Верните `KUBE_VERSION` и `HELM_VERSION` в предыдущие значения.
2. Пересоберите образ через `build-kubeutils` пайплайн.
3. Обновите `image:` во всех конфигурациях пайплайнов на новую версию.

### См. также

- **Kaniko:** [Обзор Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md), [Оптимизация сборки](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md).
- **Безопасность:** [Безопасность Dockerfile](../../../Docker/Dockerfile/Docker_best_practices/security.md).
- **GitLab CI:** [Основы GitLab CI](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md), [Интеграция с Kubernetes](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md).
- **Dev-окружение:** [Архитектура K3s](./k3s_architecture.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md).
- **Валидация:** [Обзор kubeconform](../../../Kubernetes/ToolsUtilities/kubeconform_overview.md) — детальное руководство по валидации манифестов.
