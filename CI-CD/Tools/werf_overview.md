# Werf: Автоматизация сборки и развёртывания в Kubernetes

## Определения

**Werf** — это Open Source инструмент (CNCF Sandbox) для автоматизации сборки Docker-образов и развёртывания приложений в Kubernetes. Реализует концепцию Giterminism, объединяя процессы сборки, публикации и деплоя в единый, воспроизводимый конвейер.

**Nelm** — современный движок развёртывания werf, пришедший на смену форку Helm. Обеспечивает нативную поддержку Kubernetes Server-Side Apply и улучшенное отслеживание ресурсов. Nelm позволяет обрабатывать сложные сценарии слияния манифестов и предоставляет глубокую диагностику состояния ресурсов в реальном времени.

**Stapel** — продвинутый сборочный движок и формат описания образов в werf (альтернатива Dockerfile), предоставляющий декларативный синтаксис на YAML и оптимизированное кэширование на основе стадий.

**Server-Side Apply (SSA)** — механизм Kubernetes, используемый werf для применения манифестов. SSA переносит логику слияния (merge) на сторону API-сервера, решая проблемы владения полями и конфликтов между разными участниками (человек, CI, контроллер).

**Giterminism** (Git + Determinism) — фундаментальный принцип werf: состояние развёрнутого приложения должно полностью определяться состоянием Git-репозитория. Werf работает только с закоммиченными данными, что исключает влияние локальных «грязных» файлов на результат сборки.

**Werf Converge** — основная команда развёртывания, выполняющая полный цикл: сборка, публикация в registry и синхронизация состояния кластера с Git.

## Основные концепции

### Ключевые принципы

- **Infrastructure as Code (IaC)** — вся конфигурация сборки и деплоя описывается в файлах, хранящихся в Git вместе с кодом.
- **Гитерминизм (Giterminism):**
    - Изоляция сборки от локального окружения.
    - Игнорирование файлов, не добавленных в Git (кроме режима `--dev`).
    - Использование `werf-giterminism.yaml` для явного разрешения чтения внешних файлов или переменных окружения.
- **Воспроизводимость:** гарантируется идентичность образа для одного и того же коммита.

### Архитектура werf

1. **Сборка образов:**
   - Поддержка Dockerfile и нативного формата Stapel.
   - Инкрементальная сборка с кэшированием слоёв.
   - Мультиступенчатая сборка (multi-stage).
   - **Stapel** — продвинутый сборочный движок werf, который анализирует инструкции сборки и кэширует результаты каждой стадии. При повторных сборках пересобираются только те слои, которые изменились.
   - **Стадии сборки Stapel:**
     - `beforeInstall` — подготовка окружения до установки зависимостей (например, установка системных пакетов).
     - `install` — установка зависимостей приложения (кэшируется отдельно, что ускоряет сборку при изменении только кода).
     - `beforeSetup` — подготовка перед финальной настройкой приложения.
     - `setup` — финальная настройка и компиляция образа (кэшируется отдельно).

2. **Публикация в registry:**
   - Автоматическая публикация собранных образов.
   - Поддержка OCI-совместимых registry (GitHub Container Registry, Harbor, Docker Hub, GitLab Registry).
   - **Тег на основе хэша содержимого (Content-based tagging):** werf присваивает образу тег, рассчитанный на основе содержимого образа и инструкций сборки, а не просто версию или ветку. Это гарантирует уникальность и консистентность каждой сборки.

3. **Развёртывание в Kubernetes:**
   - Встроенный Helm-совместимый движок для управления манифестами.
   - Go template для динамической подстановки имён образов и других параметров.
   - Отслеживание статуса rollout до полной готовности ресурсов.

### Основные команды werf

| Команда | Описание |
| :--- | :--- |
| `werf converge` | Объединяет build, push и deploy в одну операцию. |
| `werf plan` | Показывает планируемые изменения (аналог `terraform plan`). |
| `werf render` | Генерирует итоговые манифесты Kubernetes для проверки без деплоя. |
| `werf cleanup` | Очистка Container Registry от старых образов по настраиваемым политикам. |
| `werf run` | Запуск контейнера на основе образа проекта для локальной отладки. |
| `werf bundle` | Создание пакета (bundle) для развертывания в изолированных сетях (Air-gap). |

### Преимущества werf

| Критерий | Описание |
| :--- | :--- |
| **Единая команда** | `werf converge` объединяет build, push и deploy |
| **Кэширование** | Уникальная система кэширования стадий Stapel и переиспользование кэша в CI |
| **Безопасность** | Сборка через Buildah без root-прав и поддержка SSA |
| **Giterminism** | Гарантия соответствия состояния кластера коду в Git |
| **Nelm** | Глубокая интеграция с Kubernetes и корректная обработка состояния ресурсов |

## Практические сценарии

### Сценарий 0: Установка werf

**Установка (macOS/Linux):**

```bash
curl -sL https://werf.io/install.sh | bash
```

**Проверка установки:**

```bash
werf version
# Вывод: 2.x.x (Stable/Rock-Solid)
```

**Настройка для локальной разработки:**
Для полноценной работы рекомендуется иметь установленный Docker или альтернативный движок (например, Buildah).

### Сценарий 1: Настройка доступа к GitHub Container Registry (GHCR)

**Проблема:** Werf требует доступ для публикации образов в приватный registry.

**Решение:**

1. **Создание Personal Access Token (PAT) в GitHub:**
   Необходимо разрешение `write:packages` (или `read:packages` для pull).

2. **Аутентификация в registry:**

   ```bash
   docker login ghcr.io -u <username> -p <token>
   ```

3. **Создание Kubernetes Secret для imagePullSecrets:**

   ```bash
   kubectl create secret docker-registry registry-secret \
     --docker-server=ghcr.io \
     --docker-username=<username> \
     --docker-password=<token> \
     -n <namespace>
   ```

### Сценарий 2: Переписывание Dockerfile на Stapel

**Исходный Dockerfile (multi-stage):**

```dockerfile
# Build stage
FROM golang:1.21 AS builder
WORKDIR /app
COPY . .
RUN go build -o myapp

# Runtime stage
FROM alpine:3.18
COPY --from=builder /app/myapp /myapp
CMD ["/myapp"]
```

**Эквивалент на Stapel (werf.yaml):**

```yaml
project: myapp
configVersion: "1"

build:
  - image: app
    from: alpine:3.18
    import:
      - image: builder
        add: /app/myapp
        to: /myapp
    command: ["/myapp"]

  - image: builder
    from: golang:1.21
    git:
      - add: /
        to: /app
    shell:
      - cd /app && go build -o myapp
```
*Примечание: Stapel позволяет более гибко управлять импортом артефактов и кэшированием каждой инструкции.*

### Сценарий 3: Шаблонизация манифеста Kubernetes

**Проблема:** Имя образа меняется с каждой сборкой из-за content-based tagging.

**Решение:** Использовать Go template в манифесте Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      containers:
        - name: app
          image: "{{ .Values.werf.image.app }}"
      imagePullSecrets:
        - name: registry-secret
      command: ["/myapp"]
```

**Пояснение:** `{{ .Values.werf.image.app }}` — это плейсхолдер, который werf автоматически заменяет на полный путь к образу (включая Registry URL и уникальный тег) во время выполнения `werf converge`.

### Сценарий 4: Развёртывание командой werf converge

**Подготовка:**
Убедитесь, что вы авторизованы в Registry и имеете доступ к кластеру Kubernetes.

**Запуск деплоя:**

```bash
werf converge \
  --repo ghcr.io/<username>/<repo> \
  --env production \
  --namespace <namespace>
```

**Что происходит:**
1. **Анализ:** werf проверяет текущий коммит в Git и конфигурацию `werf.yaml`.
2. **Сборка:** собираются только те стадии образов, которые изменились.
3. **Публикация:** новые образы пушатся в Registry.
4. **Рендеринг:** Helm-шаблоны рендерятся с актуальными тегами образов.
5. **Применение:** Nelm применяет изменения в кластер через SSA и ждет готовности подов.

### Сценарий 5: Оптимизация размера образа

**Проблема:** Использование тяжелых базовых образов (например, `golang:1.21` весит ~800 МБ) в runtime.

**Решение:** Отделение сборочного окружения от runtime через Stapel или Multi-stage Dockerfile. В runtime используется минималистичный образ (`alpine` или `distroless`).

**Результат:** Итоговый образ уменьшается до 10-50 МБ, что ускоряет pull образов и повышает безопасность.

### Сценарий 6: Кросс-платформенная сборка

**Проблема:** Разработка ведется на Apple Silicon (ARM64), а серверы используют AMD64.

**Решение:** Использование флага `--platform` (требуется настроенный эмулятор QEMU или удаленный сборочный узел):

```bash
werf build --platform linux/amd64
```

### Сценарий 7: Режим разработки (--dev)

**Проблема:** Нужно быстро проверить код в кластере без создания коммита.

**Решение:**
```bash
werf converge --dev
```
Werf включит в сборку все незакоммиченные изменения. Теги для таких образов будут содержать префикс `dev-`.

### Сценарий 8: Предварительный просмотр изменений (werf plan)

**Решение:**
```bash
werf plan --env production
```
Выводит текстовый diff манифестов, позволяя избежать случайных деструктивных изменений в инфраструктуре.

### Сценарий 9: Валидация и откат (lint, rollback)

**Проблема:** Ошибки в шаблонах Helm или необходимость вернуться к предыдущей версии.

```bash
# Проверка синтаксиса шаблонов
werf lint --env staging

# Откат релиза
werf rollback --env production
```

### Сценарий 10: Управление жизненным циклом через аннотации

**Решение:** Использование аннотаций для управления поведением Nelm.

```yaml
metadata:
  annotations:
    werf.io/delete-policy: "delete" # Удаление ресурса вместе с релизом
    werf.io/weight: "10" # Очередность деплоя (аналог Helm hooks)
```

### Сценарий 11: Интеграция с GitLab CI/CD (Новый)

Для автоматизации в GitLab создается файл `.gitlab-ci.yml`:

```yaml
stages:
  - build_and_deploy

deploy:
  stage: build_and_deploy
  script:
    - werf converge --repo $CI_REGISTRY_IMAGE --env $CI_ENVIRONMENT_SLUG
  tags:
    - werf-runner
  only:
    - main
```
*Werf автоматически использует `CI_JOB_TOKEN` для авторизации в GitLab Registry.*

### Сценарий 12: Очистка Container Registry (Новый)

Настройка политик в `werf.yaml` для предотвращения переполнения диска:

```yaml
cleanup:
  keepPolicies:
    - references:
        tag: /.*/
        limit:
          last: 10
    - imagesPerReference:
        last: 2
```
Запуск очистки (рекомендуется запускать по расписанию в CI):
```bash
werf cleanup --repo <registry_url>
```

## Дополнительная информация

### Структура проекта werf

```text
project/
├── .werf/
│   └── werf.yaml          # Главный конфиг сборки
├── .helm/
│   ├── templates/         # Манифесты K8s
│   ├── values.yaml        # Значения по умолчанию
│   └── _helpers.tpl       # Хелперы шаблонизатора
├── werf-giterminism.yaml  # Конфиг Гитерминизма (опционально)
├── src/                   # Исходный код
└── Dockerfile             # Опционально
```

### Сравнение с альтернативами

| Инструмент | Сборщик | Движок деплоя | Server-Side Apply | Giterminism |
| :--- | :--- | :--- | :--- | :--- |
| **Werf** | Stapel/Dockerfile | **Nelm** | Да | Да |
| **Skaffold** | Docker/Jib/Buildpacks | Helm/Kubectl | Частично | Нет |
| **Helm** | Нет | Helm (3-way merge) | Нет | Нет |
| **Argo CD** | Нет | GitOps (Pull) | Да | Да |

### Ограничения и нюансы

- **Зависимость от Git:** Werf теряет свои преимущества вне Git-репозитория.
- **Хранилище стадий:** Для работы кэша требуется внешний Registry, поддерживающий хранение слоев.
- **Порог вхождения:** Понимание разницы между Dockerfile и Stapel, а также механизмов Nelm требует времени.

### Связанные темы

- [Работа с Container Registry](../../Docker/docker_registries.md)
- [Шаблонизация в Helm](../../Kubernetes/ToolsUtilities/Helm/helm_templating.md)
- [Kubernetes Server-Side Apply](../../Kubernetes/Concepts/api_interaction.md)

### Ресурсы

- [Официальный сайт werf.io](https://werf.io/)
- [Документация по Nelm](https://werf.io/documentation/advanced/nelm.html)
- [Giterminism Deep Dive](https://werf.io/documentation/advanced/giterminism.html)
- [CNCF Sandbox: werf](https://www.cncf.io/projects/werf/)
