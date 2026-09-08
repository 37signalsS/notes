# Абстрагирование деталей реализации с Kaniko

## Определения

**Абстрагирование деталей реализации** — стратегический этап развития CI/CD, при котором внутренняя логика выполнения задач (выбор инструментов, команды, конфигурация среды) инкапсулируется внутри общего шаблона. Потребитель шаблона взаимодействует только с интерфейсом (переменными), не зная о том, какой именно инструмент (Docker, Kaniko, Buildah) выполняет работу.

**Kaniko** — утилита для сборки контейнерных образов из Dockerfile внутри контейнера или Kubernetes-кластера. Ключевая особенность заключается в работе в пространстве пользователя (userspace) без необходимости доступа к Docker-демону или использования привилегированного режима (`privileged`). Kaniko использует механизм `chroot` для эмуляции файловой системы, что исключает необходимость в namespaces и cgroups, доступных только процессам с `CAP_SYS_ADMIN`.

> [!WARNING]
> **Статус проекта (2025):** Официальный репозиторий Google (`GoogleContainerTools/kaniko`) был **архивирован 3 июня 2025 года**. Новые функции и патчи безопасности от Google более не выпускаются. В актуальных инфраструктурах рекомендуется использовать форк от сообщества — **[osscontainertools/kaniko](https://github.com/osscontainertools/kaniko)** или мигрировать на **[BuildKit (Standalone)](../../../../Docker/Dockerfile/dockerfile_buildkit.md)**.

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
│  │  │ (интерфейс)  │  │ (аутентификация,     │   │  │
│  │  │ DOCKERFILE   │  │  CA-сертификаты,     │   │  │
│  │  │ CONTEXT      │  │  кэширование)       │   │  │
│  │  │ DESTINATION  │  │                      │   │  │
│  │  └─────────────┘  └──────────────────────┘   │  │
│  └───────────────────────────────────────────────┘  │
│                        │                            │
│                        ▼                            │
│  ┌───────────────────────────────────────────────┐  │
│  │  script: /kaniko/executor (скрытая логика)    │  │
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
| **Аутентификация** | Каждый проект управляет секретами | Централизованно (ID Tokens, JWT) |
| **Аудит** | Распределенный, трудоемкий | Точки сбора в одном месте |

**Ключевой переход:** от «гибких, но хрупких» шаблонов к «безопасным по умолчанию» конфигурациям, где неправильная настройка технически невозможна без модификации центрального шаблона.

## Базовые концепции

### Проблемы прямой зависимости от Docker

На этапах [ include:project](./evolution_include.md) и [extends](./evolution_extends.md) часто используется Docker-in-Docker (DinD). Это создает ряд рисков:
1.  **Безопасность:** Режим `privileged: true` позволяет контейнеру получить доступ к устройствам хоста, что делает инфраструктуру уязвимой для атак типа «Container Escape».
2.  **Архитектурная связанность:** Если компания решает перейти на Podman или другой инструмент, придется вручную обновлять тысячи файлов `.gitlab-ci.yml`.
3.  **Сложность обслуживания:** Каждый проект должен самостоятельно управлять `config.json` для авторизации, что ведет к дублированию секретов и ошибок.

### Преимущества абстракции

1.  **Инфраструктурная мобильность:** Возможность заменить Kaniko на Buildah или BuildKit, обновив только один файл шаблона.
2.  **Централизованный аудит:** В шаблон легко добавить принудительное сканирование уязвимостей (Trivy) или подпись образов (Cosign) для всей компании сразу.
3.  **Безопасность по умолчанию:** Разработчики не могут случайно запустить привилегированный контейнер, так как не имеют прямого контроля над секцией `image` и `script` в задачах сборки.

### Безопасность: почему Kaniko, а не DinD

Абстрагирование на базе Kaniko решает критическую проблему безопасности CI/CD-инфраструктуры. Ключевые векторы защиты:

1.  **Отсутствие `--privileged`:** Kaniko не требует привилегированного режима. В отличие от DinD, процесс сборки не получает доступ к cgroups, namespaces и устройствам хоста. Это исключает вектор атаки «Container Escape» через компрометацию CI-контейнера.
2.  **Соответствие Pod Security Standards (Restricted):** Контейнер Kaniko работает от non-root пользователя (UID 1000) и не требует специальных capabilities. Это позволяет запускать сборку в неймспейсах с профилем безопасности `restricted` в Kubernetes — самом строгом профиле, где запрещены привилегированные контейнеры, hostPath-тома и доступ к сети хоста.
3.  **Изоляция через chroot:** Kaniko использует `chroot` вместо namespaces для изоляции файловой системы процесса сборки. Это означает, что даже при компрометации скрипта сборки злоумышленник остаётся в пределах изолированной файловой системы и не имеет доступа к файлам хоста.
4.  **NetworkPolicy-совместимость:** В Kubernetes строгие `NetworkPolicy` могут ограничить сетевую активность пода Kaniko, не позволяя процессу сборки сканировать внутреннюю сеть или подключаться к неавторизованным реестрам.

> **Сравнение векторов атаки:** Подробный анализ рисков DinD, Socket Mount и Kaniko приведён в разделе [Docker-in-Docker: Запуск в контейнере](../../../../Docker/docker-in-docker.md#выбор-метода-сборки-dind-vs-kaniko).

### Кэширование слоёв в абстрагированном шаблоне

Kaniko поддерживает удалённое кэширование слоёв через реестр образов, что является принципиальным отличием от Docker BuildKit с локальным кэшем:

-   **Удалённый кэш (Remote-only):** Кэшированные слои хранятся в Registry (`--cache-repo`). Локального постоянного кэша не существует — контейнер удаляется после каждой сборки.
-   **Логика инвалидации:** Параметр `--cache-ttl` определяет время жизни кэша (по умолчанию 24 часа). По истечении TTL слои пересобираются, даже если исходный код не изменился.
-   **Рекомендация по настройке:** Используйте отдельный реестр или namespace для кэша (`$CI_REGISTRY_IMAGE/cache`), чтобы он не конфликтовал с основными образами и не увеличивал стоимость хранения в основном реестре.

**Пример кэширования в шаблоне:**

```yaml
script:
  - /kaniko/executor \
      --cache=true \
      --cache-repo="$CI_REGISTRY_IMAGE/cache" \
      --cache-ttl="$CACHE_TTL" \
      --context "$CONTEXT" \
      --dockerfile "$DOCKERFILE" \
      --destination "$DESTINATION"
```

### Влияние на архитектуру Container Registry

Централизованная сборка через Kaniko создаёт специфические требования к реестру образов:

1.  **Хранение кэша:** Репозиторий кэша (`cache-repo`) должен поддерживать OCI Distribution API. Суммарный объём кэшированных слоёв может превышать размер основных образов в 3–5 раз.
2.  **Очистка:** Настройте политики удаления неиспользуемых тегов и кэшированных слоёв. В Harbor это делается через `Garbage Collection`, в GitLab — через `Package Registry cleanup` в настройках проекта.
3.  **Сетевая доступность:** Runner и поды Kaniko должны иметь сетевой доступ к реестру. В Kubernetes это обеспечивается через `NetworkPolicy` и DNS-конфигурацию.

## Предварительные условия

Для успешного внедрения абстрагированного шаблона необходимо:
- **GitLab Runner:** настроенный с Docker или Kubernetes исполнителем. Для Kubernetes-исполнителя рекомендуется выделить отдельный node pool для задач сборки, чтобы изолировать их от production-нагрузки.
- **Права доступа:** проект должен иметь права на запись в `Container Registry` (роль `Developer` или выше). При использовании внешних реестров (Harbor, Nexus) потребуются дополнительные credentials.
- **Версии:** рекомендуется использовать GitLab 16.0+ для поддержки `id_tokens` (OIDC). Для полной поддержки `spec:inputs` и CI/CD Catalog — GitLab 16.11+.
- **Сетевой доступ:** Runner должен иметь доступ к реестру образов. В Kubernetes это обеспечивается через `NetworkPolicy`. Если Dockerfile содержит `FROM` с внешних реестров (Docker Hub), необходим доступ и к ним.
- **Образ Kaniko:** Используйте актуальный форк `osscontainertools/kaniko:v1.28.0-debug`. Официальный образ Google (`gcr.io/kaniko-project`) архивирован и не получает обновлений безопасности.

### Рекомендуемый стек версий

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| GitLab | 16.0 | 17.x+ |
| GitLab Runner | 15.0 | 17.x+ |
| Kaniko (форк) | v1.25.0 | v1.28.0+ |
| Kubernetes (если используется) | 1.25 | 1.28+ |
| Pod Security Standards | `baseline` | `restricted` |

## Практические сценарии

### Сценарий 1: Эталонный абстрагированный шаблон

В данном примере логика Kaniko полностью скрыта. Мы используем `ID Tokens` для беспарольной аутентификации в GitLab Registry, что избавляет от передачи паролей в `before_script`.

```yaml
# ci-templates/templates/docker-build.yml
.docker-build-base:
  stage: build
  image:
    # Использование актуального форка сообщества (SSoT для версий Kaniko)
    name: osscontainertools/kaniko:v1.28.0-debug
    entrypoint: [""]
  variables:
    DOCKERFILE: "Dockerfile"
    CONTEXT: "$CI_PROJECT_DIR"
    DESTINATION: "$CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG"
    CACHE_TTL: "24h"
  id_tokens:
    # Современный метод аутентификации без использования паролей
    GITLAB_JWT:
      aud: https://gitlab.com
  before_script:
    # Скрытая логика подготовки окружения
    - mkdir -p /kaniko/.docker
    # Настройка авторизации через JWT (автоматически для GitLab Registry)
    - |
      echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"gitlab-ci-token\",\"password\":\"$CI_JOB_TOKEN\"}}}" > /kaniko/.docker/config.json
    # Добавление корпоративного CA, если необходимо
    - |
      if [ -f "$INTERNAL_CA_PEM" ]; then
        cp "$INTERNAL_CA_PEM" /kaniko/ssl/certs/ca-certificates.crt
      fi
  script:
    - /kaniko/executor \
        --context "$CONTEXT" \
        --dockerfile "$DOCKERFILE" \
        --destination "$DESTINATION" \
        --cache=true \
        --cache-repo="$CI_REGISTRY_IMAGE/cache" \
        --cache-ttl="$CACHE_TTL" \
        $EXTRA_ARGS
```

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
    # Передача дополнительных флагов для многостадийной сборки
    EXTRA_ARGS: "--target production --build-arg VERSION=$CI_COMMIT_TAG"
  rules:
    - if: $CI_COMMIT_TAG
```

### Сценарий 3: Сборка с внешними зависимостями (Edge Case)

Если Kaniko нужно авторизоваться во внешнем реестре (например, Docker Hub для базовых образов), шаблон расширяется через дополнительные переменные, не раскрывая их формат в `config.json`.

```yaml
# В шаблоне добавляется обработка внешних секретов
before_script:
  - |
    if [ -n "$DOCKER_HUB_AUTH" ]; then
      # Добавление записи в существующий config.json
      sed -i "s/\"auths\":{/\"auths\":{\"https:\/\/index.docker.io\/v1\/\":{\"auth\":\"$DOCKER_HUB_AUTH\"},/" /kaniko/.docker/config.json
    fi
```

### Сценарий 4: Многостадийная сборка с кастомизацией стадий

Абстрагированный шаблон поддерживает multi-stage Dockerfile. Разработчик указывает целевую стадию через `EXTRA_ARGS`, а шаблон обеспечивает корректную работу кэша для каждой стадии.

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

### Сценарий 5: Сборка с интеграцией сканирования безопасности (Trivy)

Централизованный шаблон позволяет добавить принудительное сканирование уязвимостей после сборки. Сканирование выполняется в `after_script`, что не блокирует сборку при обнаружении уязвимостей низкой критичности, но фиксирует результат для аудита.

```yaml
# ci-templates/templates/docker-build.yml
.docker-build-base:
  stage: build
  image:
    name: osscontainertools/kaniko:v1.28.0-debug
    entrypoint: [""]
  variables:
    DOCKERFILE: "Dockerfile"
    CONTEXT: "$CI_PROJECT_DIR"
    DESTINATION: "$CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG"
    CACHE_TTL: "24h"
    TRIVY_SEVERITY: "HIGH,CRITICAL"
    SCAN_EXIT_CODE: "1"
  before_script:
    - mkdir -p /kaniko/.docker
    - |
      echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"gitlab-ci-token\",\"password\":\"$CI_JOB_TOKEN\"}}}" > /kaniko/.docker/config.json
  script:
    - /kaniko/executor \
        --context "$CONTEXT" \
        --dockerfile "$DOCKERFILE" \
        --destination "$DESTINATION" \
        --cache=true \
        --cache-repo="$CI_REGISTRY_IMAGE/cache" \
        --cache-ttl="$CACHE_TTL" \
        $EXTRA_ARGS
  after_script:
    # Сканирование после сборки (не блокирует пайплайн по умолчанию)
    - |
      if command -v trivy &> /dev/null; then
        trivy image --exit-code "$SCAN_EXIT_CODE" \
          --severity "$TRIVY_SEVERITY" \
          "$DESTINATION"
      fi
  artifacts:
    paths:
      - trivy-report.json
    when: always
```

### Сценарий 6: Debug-образ для отладки проблемной сборки

При возникновении ошибок в Dockerfile или проблем с сетевым доступом переключение на debug-образ (с поддержкой shell) позволяет интерактивно исследовать среду сборки.

```yaml
# Временное отладочное задание (добавить в .gitlab-ci.yml проекта)
build-debug:
  extends: .docker-build-base
  image:
    name: osscontainertools/kaniko:v1.28.0-debug
    entrypoint: [""]
  variables:
    DOCKERFILE: "Dockerfile"
    DESTINATION: "$CI_REGISTRY_IMAGE:debug-$CI_COMMIT_SHORT_SHA"
    # Отладка: включить подробное логирование
    EXTRA_ARGS: "--verbosity=trace --log-timestamp"
  before_script:
    - mkdir -p /kaniko/.docker
    - |
      echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"gitlab-ci-token\",\"password\":\"$CI_JOB_TOKEN\"}}}" > /kaniko/.docker/config.json
    # Диагностика окружения
    - echo "=== DEBUG: Проверка сети ==="
    - wget -qO- --timeout=5 https://$CI_REGISTRY/v2/ || echo "WARN: Registry недоступен"
    - echo "=== DEBUG: Содержимое workspace ==="
    - ls -la /workspace/
    - cat /workspace/Dockerfile
  script:
    - /kaniko/executor \
        --context "$CONTEXT" \
        --dockerfile "$DOCKERFILE" \
        --destination "$DESTINATION" \
        --no-push \
        $EXTRA_ARGS
  allow_failure: true
```

## Преимущества и недостатки подхода

| Характеристика | Описание |
| :--- | :--- |
| **Безопасность** | Сборка без `--privileged`, совместимость с Pod Security Standards (restricted). |
| **Инфраструктурная мобильность** | Замена инструмента сборки (Kaniko → Buildah → BuildKit) без правок в проектах. |
| **Централизация** | Единая точка управления аутентификацией, кэшированием, сканированием. |
| **Снижение TCO** | Устранение дублирования конфигурации, автоматизация обновлений. |
| **Скрытая сложность (Минус)** | «Чёрный ящик»: разработчик не видит, как именно собирается образ, что затрудняет отладку. |
| **Ограниченная совместимость (Минус)** | Kaniko поддерживает ~95% инструкций Dockerfile. BuildKit-расширения (`--mount`, `--network`, `--security`) игнорируются. |
| **Зависимость от реестра (Минус)** | Кэширование требует доступа к Registry. При его недоступности кэш не работает, время сборки увеличивается. |
| **Стоимость хранения (Минус)** | Кэшированные слои хранятся в Registry и увеличивают потребление диска. Требуется настройка политик очистки. |

## Валидация

Для проверки корректности работы абстрагированного пайплайна:
1.  **Логи Kaniko:** Убедитесь, что в выводе задачи присутствует строка `INFO[0000] Retrieving image manifest...` и нет ошибок `401 Unauthorized`.
2.  **Кэширование:** Проверьте, что после первого запуска в логах появляется `INFO[xxxx] Using files from context: ...` и слои подгружаются из `cache-repo`.
3.  **Артефакты:** Проверьте наличие образа в Container Registry с ожидаемым тегом.
4.  **Безопасность:** Выполните команду `id` внутри задачи (если используется debug-образ). Она должна возвращать `uid=0`, но при этом задача не должна требовать `privileged: true` в настройках раннера.

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `error checking push permissions` | Неверный `config.json` или отсутствие прав у `CI_JOB_TOKEN`. | Проверьте права доступа в `Settings -> Repository -> Deploy Tokens` или роли проекта. Убедитесь, что переменные `$CI_REGISTRY_USER` и `$CI_JOB_TOKEN` доступны. |
| `Out of memory (OOM)` | Слишком большие слои или много стадий сборки. | Увеличьте `resources:limits` в настройках Kubernetes раннера. Для базовых образов Alpine рекомендуется минимум 1Gi памяти. |
| `error building image: error resolving ...` | Проблема с DNS или доступом к внешнему реестру. | Проверьте настройки `dnsConfig` в подах раннера или наличие прокси. Для корпоративных реестров добавьте кастомный CA через `$INTERNAL_CA_PEM`. |
| `failed to extract layer: ... file exists` | Конфликт системных путей Kaniko с файлами образа. | Избегайте манипуляций с каталогом `/kaniko` в Dockerfile. Не используйте `COPY` или `ADD` для записи в `/kaniko/*`. |
| `TLS handshake timeout` | Проблемы с сертификатом или сетевой задержкой до реестра. | Добавьте сертификат через `--registry-certificate` илимонтируйте CA в `/kaniko/ssl/certs/ca-certificates.crt`. Проверьте `MTU` сетевого интерфейса. |
| `error building image: reference not found` | Неверный путь к Dockerfile или отсутствие файла в контексте. | Проверьте переменную `$DOCKERFILE` и `$CONTEXT`. Убедитесь, что Dockerfile находится в корне указанного контекста. |
| `UNAUTHORIZED` при пуше | Истёк срок действия токена или неверный registry. | При использовании `CI_JOB_TOKEN` токен действителен только в рамках текущего пайплайна. Проверьте, что `$CI_REGISTRY` указывает на правильный реестр. |
| Кэш не используется (`--cache=true`) | TTL кэша истёк или `cache-repo` недоступен. | Увеличьте `--cache-ttl` (например, до `168h` для недельного кэша). Проверьте доступность `cache-repo` из пода Kaniko. |
| `no space left on device` | Переполнение writable layer контейнера Kaniko. | Оптимизируйте Dockerfile: объединяйте `RUN`-команды, используйте multi-stage сборку, очищайте кэш пакетного менеджера в каждом `RUN`. |

## Дополнительная информация

- **Предыдущий этап:** [Гибкость с extends](./evolution_extends.md) — наследование и кастомизация конфигурации.
- **Следующий этап:** [CI/CD Components](./evolution_components.md) — переход к типизированным интерфейсам и каталогу компонентов.
- **Технический SSoT по Kaniko:** [Руководство по Kaniko](../../../../Docker/Dockerfile/dockerfile_kaniko.md) — глубокое погружение в параметры исполнителя, архитектуру и сравнение с альтернативами.
- **Безопасность:** [Docker-in-Docker: Запуск в контейнере](../../../../Docker/docker-in-docker.md) — анализ рисков DinD, DooD и Kaniko, сравнение векторов атаки.
- **Обзор эволюции:** [Эволюция переиспользуемого пайплайна](../evolution_example.md) — контекст всех этапов зрелости CI/CD.
- **Практические примеры:** [Обзор механизмов переиспользования](../overview.md) — сравнение `extends`, `include`, `components`.
- **Безопасность образов:** [Обзор DevSecOps](../../../DevSecOps/devsecops_overview.md) — интеграция сканирования уязвимостей в пайплайн.
