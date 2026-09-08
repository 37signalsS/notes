# Kustomize — Обзор и основные концепции

## 1. Определения

**Kustomize** — нативный инструмент Kubernetes для декларативного управления конфигурациями. В отличие от шаблонизаторов (Helm), он настраивает Kubernetes-объекты без изменения оригинальных манифестов через механизм наложения патчей (overlays), сохраняя «чистоту» базовых YAML-файлов.

**База (Base)** — директория с набором стандартных манифестов (Deployment, Service, ConfigMap) и файлом `kustomization.yaml`, который их объединяет. Представляет собой «шаблон по умолчанию» для приложения.

**Наложение (Overlay)** — директория, которая ссылается на `base` и применяет к ней специфические изменения (патчи) для конкретных окружений (Development, Staging, Production).

**kubectl kustomize** — встроенная в `kubectl` команда (начиная с v1.14). Позволяет собирать манифесты без установки отдельного бинарного файла.

**kustomization.yaml** — основной конфигурационный файл, описывающий ресурсы, трансформации, генераторы и патчи. Делает конфигурацию версионируемой, отслеживаемой и повторяемой.

## 2. Основные концепции

### Зачем нужны инструменты управления конфигурацией?

Редактирование манифестов YAML вручную для каждой среды (dev, staging, prod) является медленным процессом, подверженным ошибкам и плохо масштабируемым. Простое изменение, например обновление тега образа или увеличение количества реплик, может потребовать редактирования множества файлов, что создает риск несоответствий и сбоев приложения.

Kustomize решает эти проблемы, предоставляя систематический, повторяемый и контролируемый способ управления манифестами через декларативный подход без использования сложных шаблонизаторов.

### Основные преимущества

*   **Отсутствие шаблонов:** упрощает управление конфигурацией за счет отказа от сложных языков шаблонов (как в Helm).
*   **Декларативная настройка:** обеспечивает легкость чтения и понимания конфигураций, так как они остаются валидными YAML-файлами Kubernetes.
*   **Согласованность между средами:** повторное использование базовых конфигураций с применением специфических наложений (overlays) гарантирует единообразие инфраструктуры.
*   **Высокая повторяемость:** базовые конфигурации можно повторно использовать в нескольких проектах или средах с минимальными изменениями.
*   **Нативная поддержка GitOps:** инструменты вроде ArgoCD и Flux поддерживают Kustomize «из коробки», что делает его стандартом для автоматической синхронизации состояния репозитория с кластером. Подробнее об интеграции в конвейеры CD: [Интеграция Kustomize в конвейеры CD](./kustomize_cd_integration.md).

### Ключевые компоненты

*   **Базы (Bases):** директории, содержащие исходные файлы YAML без шаблонов, представляющие конфигурацию приложения по умолчанию.
*   **Наложения (Overlays):** каталоги, содержащие изменения, специфичные для конкретной среды. Каждое наложение имеет свой `kustomization.yaml`.
*   **Патчи (Patches):** механизмы внесения изменений в базовую конфигурацию (Strategic Merge Patch или JSON Patch).
*   **Ресурсы (Resources):** реальные объекты Kubernetes, определенные в файлах YAML и включенные в процесс сборки.
*   **Генераторы (Generators):** инструменты для динамического создания ConfigMaps и Secrets из файлов или литералов, что позволяет настраивать ресурсы в зависимости от окружения.

### Принципы работы и слои (Overlays)

Kustomize использует иерархическую структуру, где изменения накладываются слоями. Это позволяет избежать дублирования кода и упрощает поддержку множества окружений:

```text
                    ┌─────────────────┐
                    │      base/      │
                    │  (общая конф.)  │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
            v                v                v
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │  staging/  │  │ production/│  │   local/   │
     │  (overlay) │  │  (overlay) │  │  (overlay) │
     └────────────┘  └────────────┘  └────────────┘
```

### Ключевые возможности

| Возможность | Описание |
| :--- | :--- |
| **Генерация ресурсов** | Создание ConfigMap и Secret из файлов или литералов |
| **Name Hashing** | Автоматическое добавление хеша к именам ConfigMap/Secret для инициирования Rolling Update при изменении данных |
| **Манипуляция метаданными** | Массовое добавление префиксов, суффиксов к именам и общих аннотаций |
| **Общие метки (Labels)** | Добавление labels ко всем ресурсам в рамках одной сборки (namespace-wide) |
| **Патчи (Patches)** | Точечное изменение полей ресурсов (Strategic Merge Patch или JSON Patch/RFC 6902) |
| **Components (v4.0+)** | Переиспользуемые фрагменты логики (например, включение мониторинга), доступные для разных оверлеев |
| **Replacements (v5.0+)** | Типизированная и безопасная передача значений между любыми полями ресурсов (замена устаревшим `vars`) |
| **OpenAPI Integration** | Использование пользовательских схем для валидации и обработки Custom Resources |
| **Удаленные базы** | Возможность использовать ресурсы напрямую из Git-репозиториев или по HTTP (Kustomize 4.0+) |

Подробнее о генераторах, Components, Replacements и интеграции с Helm: [Продвинутые возможности](./kustomize_advanced_features.md).

### Концепция управления манифестами

Работа с «сырыми» YAML-файлами в реальных проектах сталкивается с проблемами разграничения окружений (Sandbox vs Prod) и управления секретами. Использование Kustomize или Helm привносит структуру и документированность, аналогично переходу от настройки серверов Shell-скриптами к использованию Ansible:

- **Shell-скрипты (Raw YAML)**: последовательность команд, отсутствие структуры, сложность поддержки, риск человеческой ошибки при ручном редактировании.
- **Ansible (Kustomize/Helm)**: декларативность, стандартные модули, разделение логики и данных, повторяемость. Kustomize позволяет описывать «что» должно быть изменено, а не «как».

### Сравнение с Helm и альтернативами

| Характеристика | Kustomize | Helm | Jsonnet / Tanka |
| :--- | :--- | :--- | :--- |
| **Принцип** | Наложение патчей (Overlays) | Шаблонизация (Go templates) | Программируемый JSON |
| **Тип** | Декларативный | Пакетный менеджер | Язык программирования |
| **Deployment** | Нет (нужен `kubectl apply`) | Да (отслеживает состояние/релизы) | Нет |
| **Условная логика** | Нет | Есть | Есть (полноценный код) |
| **Сложность** | Низкая (KISS) | Средняя / Высокая | Высокая |

**Helm** выделяется тем, что выполняет две функции: генерацию манифестов и их деплой (отслеживание ресурсов в кластере через механизм Release). Kustomize и Jsonnet — это только генераторы, требующие внешнего инструмента для деплоя (ArgoCD, Flux или `kubectl apply`).

Kustomize придерживается принципа **KISS (Keep It Simple, Stupid)** — манифесты остаются читаемыми Kubernetes-объектами, а не превращаются в сложные шаблоны с обилием фигурных скобок и управляющих конструкций.

### Ограничения

- **Нет условной логики** — в отличие от Helm templates. Нельзя создать ресурс на основе переменной (частично решается через Components).
- **Нет циклов** — нельзя генерировать множество одинаковых ресурсов по списку.
- **Простые трансформации** — сложные изменения могут потребовать множественных оверлеев или громоздких патчей.

Подробнее о типах патчей и overlays: [Наложения и патчи](./kustomize_overlays_and_patches.md).

## 3. Практические сценарии

### 3.0. Предварительные требования

Перед началом работы с Kustomize необходимо определить минимальный набор программного обеспечения, версии инструментов и начальное состояние окружения. Все примеры ниже используют структуру `base/ + overlays/`, которая является рекомендуемой для production-проектов.

**Программное обеспечение:**

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| kubectl | 1.14 | 1.29+ | Встроенная поддержка Kustomize начиная с v1.14 |
| kustomize CLI | 5.0 | 5.8.1 | Отдельная установка для advanced-фич (Components, Replacements, Validators) |

**Соответствие версий kubectl и встроенного Kustomize** (на основе [GitHub](https://github.com/kubernetes-sigs/kustomize)):

| kubectl | Kustomize (встроенный) |
| :--- | :--- |
| < v1.14 | n/a |
| v1.14–v1.20 | v2.0.3 |
| v1.21 | v4.0.5 |
| v1.22 | v4.2.0 |
| v1.23 | v4.4.1 |
| v1.24 | v4.5.4 |
| v1.25–v1.26 | v4.5.7 |
| v1.27 | v5.0.1 |
| v1.29+ | v5.x |

**Окружение:**
- Рабочий Kubernetes-кластер (minikube, kind или реальный кластер) для применения манифестов.
- Локальный Git-репозиторий для хранения конфигураций (GitOps подход).
- Базовые навыки работы с YAML и `kubectl`.

**Структура проекта:**
```text
my-app/
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── kustomization.yaml
└── overlays/
    ├── development/
    │   └── kustomization.yaml
    └── production/
        └── kustomization.yaml
```

### 3.1. Просмотр результата (Dry-run)

```bash
# Просмотр сгенерированных манифестов через встроенный kubectl
kubectl kustomize overlays/production/
# → Вывод: полный YAML манифест со всеми примененными патчами

# Просмотр через отдельный CLI (вывод в stdout)
kustomize build overlays/production/
# → Вывод: полный YAML манифест со всеми примененными патчами (тот же результат)

# Сохранение в файл для аудита
kustomize build overlays/production/ > manifests.yaml

# Предпросмотр изменений перед применением (kubectl diff)
kubectl diff -k overlays/production/
# → Вывод: список ресурсов, которые будут созданы, изменены или удалены (цветовым выделением)
# → Exit code 0 = нет изменений; 1 = есть различия (drift)
```

**Валидация результата сборки:** после `kustomize build` проверьте, что:
1. Хеш ConfigMap/Secret изменился (если менялись данные) — это гарантирует Rolling Update.
2. `namePrefix`/`nameSuffix` применились к именам ресурсов.
3. `commonLabels` добавлены ко всем ресурсам и селекторам Service.
4. Namespace подставлен во все ресурсы (если задан на уровне overlay).

### 3.2. Применение к кластеру

```bash
# Применение staging конфигурации (флаг -k указывает на директорию с kustomization.yaml)
kubectl apply -k overlays/staging/
# → configmap/app-config-f7h8z9 created
# → deployment.apps/web-server-staging configured

# Применение production конфигурации
kubectl apply -k overlays/production/

# Просмотр примененных ресурсов через kustomize (фильтр по типу)
kubectl get -k overlays/production/ --ignore-not-found
# → deployment.apps/web-server-prod
# → service/web-server-prod
# → configmap/app-config-x9k2m1
```

### 3.3. Удаление ресурсов

```bash
kubectl delete -k overlays/staging/
# → deployment.apps "web-server-staging" deleted
# → configmap "app-config-f7h8z9" deleted

# Удаление с подтверждением (dry-run перед delete)
kubectl delete -k overlays/staging/ --dry-run=client
# → Просмотр списка ресурсов, которые будут удалены
```

### 3.4. Установка Kustomize CLI

Хотя Kustomize встроен в `kubectl`, отдельный CLI обновляется чаще и предоставляет больше возможностей для отладки, включая `kustomize cfg fmt`, `kustomize fn` и `kustomize alpha`.

```bash
# Linux
curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
chmod +x kustomize
sudo mv kustomize /usr/local/bin/

# Linux (через GitHub Releases, фиксированная версия)
curl -L "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/v5.8.1/kustomize_v5.8.1_linux_amd64.tar.gz" | tar xz
sudo install kustomize /usr/local/bin/

# macOS (Homebrew)
brew install kustomize

# Проверка версии
kustomize version
# → {Version:v5.8.1 GitCommit:... BuildDate:... GoOs:linux GoArch:amd64}
```

### 3.5. Полный пример: создание конфигурации с нуля

Ниже демонстрируется создание минимального проекта `base + overlays` с нуля.

**Шаг 1. Создайте базовую конфигурацию:**
```bash
mkdir -p my-app/base my-app/overlays/{development,production}
```

**`base/deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-server
  template:
    metadata:
      labels:
        app: web-server
    spec:
      containers:
      - name: web-server
        image: nginx:1.25
        ports:
        - containerPort: 80
        envFrom:
        - configMapRef:
            name: app-config
```

**`base/service.yaml`:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-server
spec:
  type: ClusterIP
  selector:
    app: web-server
  ports:
  - port: 80
    targetPort: 80
```

**`base/kustomization.yaml`:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- deployment.yaml
- service.yaml

configMapGenerator:
- name: app-config
  literals:
  - LOG_LEVEL=info
  - DATABASE_HOST=postgres.example.com

commonLabels:
  app.kubernetes.io/name: web-server
  app.kubernetes.io/managed-by: kustomize
```

**Шаг 2. Создайте overlay для production:**

**`overlays/production/kustomization.yaml`:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../../base

namespace: production
namePrefix: prod-

patches:
- target:
    kind: Deployment
    name: web-server
  patch: |-
    - op: replace
      path: /spec/replicas
      value: 5
- target:
    kind: Deployment
    name: web-server
  patch: |-
    - op: replace
      path: /spec/template/spec/containers/0/resources
      value:
        limits:
          cpu: "1000m"
          memory: "512Mi"
        requests:
          cpu: "500m"
          memory: "256Mi"

configMapGenerator:
- name: app-config
  behavior: merge
  literals:
  - LOG_LEVEL=error
```

**Шаг 3. Проверьте результат сборки:**
```bash
kustomize build overlays/production/
# → Вывод: Deployment с 5 репликами, именем prod-web-server, ConfigMap с хешем
# → переменная LOG_LEVEL переопределена на "error" через behavior: merge
# → добавлены ресурсы limits/requests для контейнера
```

**Шаг 4. Примените к кластеру:**
```bash
kubectl apply -k overlays/production/
# → deployment.apps/prod-web-server created
# → service/prod-web-server created
# → configmap/prod-app-config-7d3k8f created
```

### 3.6. Валидация примененных изменений

После `kubectl apply -k` проверьте корректность применения:

```bash
# Проверить статус Deployment
kubectl get deployment prod-web-server -n production
# → READY: 5/5 (количество реплик совпадает с указанным в overlay)

# Проверить, что ConfigMap с хешем создан и смонтирован
kubectl get configmap -n production | grep app-config
# → prod-app-config-7d3k8f   1     5m

# Проверить переменные окружения пода
kubectl exec deploy/prod-web-server -n production -- env | grep LOG_LEVEL
# → LOG_LEVEL=error

# Проверить resource limits пода
kubectl describe pod -l app=web-server -n production
# → В секции "Limits" и "Requests" должны отображаться cpu и memory
```

## 4. Дополнительная информация

### Версии API Kustomize

| API Version | Kubernetes | Примечание |
| :--- | :--- | :--- |
| **kustomize.config.k8s.io/v1beta1** | 1.14+ | Текущая стабильная версия |
| **kustomize.config.k8s.io/v1alpha1** | 1.14–1.20 | Устаревшая (deprecated) |

### Требования к компонентам

Подробную таблицу соответствия версий см. в разделе [3.0. Предварительные требования](#30-предварительные-требования). Краткая сводка:

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| kubectl | 1.14+ | Встроенная поддержка начиная с v1.14; v1.27+ содержит Kustomize v5 |
| kustomize CLI | 5.0+ | Требуется для Components, Replacements, Validators и плагинов |

### Преодоление проблем

В ходе эксплуатации Kustomize могут возникнуть сложности при управлении большими конфигурациями. Рекомендуемые стратегии:

*   **Модуляризация конфигураций:** разбивайте крупные манифесты на мелкие части. Используйте поле `resources` для включения этих частей в итоговый `kustomization.yaml`.
*   **Использование генераторов:** автоматизируйте создание ConfigMaps и Secrets через генераторы для обеспечения согласованности и минимизации ручных правок.
*   **Тщательный обзор и тестирование:** проводите Code Review всех изменений. Используйте инструменты валидации (например, `kubeval` или [kubeconform](../kubeconform_overview.md)) для проверки манифестов перед их применением в кластере.

#### Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Error: may not be specified in a kustomization file of kind Kustomization` | Поле `namespace`, `namePrefix` или `nameSuffix` применено в `base` | Перенесите эти поля в `overlay`; base должна быть неймспейс-нейтральной. |
| `error: no such file or directory` при `kustomize build` | Опечатка в пути к ресурсу или отсутствие `kustomization.yaml` | Проверьте пути в блоке `resources` и наличие файла `kustomization.yaml` в указанной директории. |
| Патч не применяется (без ошибки) | `target.name` или `target.kind` не совпадают с ресурсом | Убедитесь, что имя и тип в `target` точно соответствуют манифесту. Используйте `kustomize build` для проверки. |
| `vars` is deprecated; use replacements instead | Использование удаленного в v5.0 поля `vars` | Замените `vars` на [replacements](./kustomize_advanced_features.md) (v4.0+, обязательны v5.0+). |
| Хеш ConfigMap не меняется при правке base | `disableNameSuffixHash: true` в `generatorOptions` | Проверьте `generatorOptions`; удалите флаг или установите в `false` для автоматического хеширования. |
| `helmCharts` не рендерится | Флаг `--enable-helm` не передан | Добавьте `--enable-helm` к `kustomize build` или `kubectl kustomize` (kubectl v1.27+ может поддерживать через `--enable-helm`). |
| Ссылки на сгенерированный Secret/ConfigMap сломаны после применения | Приложение ссылается на имя без хеша | Используйте `replacements` для автоматической подстановки хешированного имени, либо ссылку через `envFrom`/`configMapRef` с именем без суффикса (Kustomize перепишет автоматически). |

**Диагностика:**
```bash
# 1. Проверить, что kustomization.yaml валиден
kustomize build overlays/production/ --dry-run=client 2>&1 | head -20
# → Если ошибка парсинга, выводится сообщение с указанием строки

# 2. Отладить порядок применения патчей (verbose)
kustomize build overlays/production/ --enable-alpha-plugins --v=4
# → Подробный лог: какие ресурсы читаются, в каком порядке применяются трансформации

# 3. Проверить diff перед применением
kubectl diff -k overlays/production/
# → Показывает drift между текущим состоянием кластера и желаемым
```

### Переход к Helm

Kustomize отлично подходит для декларативного управления YAML, но при развертывании приложений на множестве кластеров в разных локациях может потребуется более масштабируемое решение. В таких случаях стандартом становится **Helm** — пакетный менеджер, обеспечивающий гибкую шаблонизацию и упрощенное управление жизненным циклом приложений.

Подробнее о сравнении: [Kustomize vs Helm](../../../CI-CD/Deployment_Strategies/comparison.md).

---

### Лучшие практики

1.  **Структура каталогов** — используйте единообразную структуру папок (например, `base/`, `overlays/`, `patches/`, `configs/`). Рекомендуемый шаблон структуры и правила оформления базового слоя описаны в [Структура проекта и синтаксис](./kustomize_structure_and_syntax.md).
2.  **Хранение ресурсов** — храните каждый ресурс в отдельном файле YAML (например, `deployment.yaml`, `service.yaml`), если только они не тесно связаны между собой.
3.  **Схема именования** — используйте единую схему именования файлов ресурсов для упрощения навигации (например, `<имя>.<вид>.yaml`).
4.  **Изоляция базовой конфигурации** — храните base в отдельной директории и никогда не редактируйте её для нужд конкретного окружения.
5.  **Генераторы** — всегда используйте `configMapGenerator` и `secretGenerator` для ConfigMap и Secret. Это гарантирует запуск Rolling Update подов при изменении данных за счет хеширования имен.
6.  **Именованные патчи** — используйте понятные имена файлов патчей (например, `patch-replica-count.yaml`).
7.  **Минимизация патчей** — старайтесь минимизировать использование сложных стратегических слияний и патчей JSON; предпочитайте встроенные механизмы трансформации (`namePrefix`, `commonLabels`), когда это возможно.
8.  **Версионирование образов** — фиксируйте `newTag` или digest образов (через `images` или `patches`) вместо `latest`.
9.  **Контроль версий и форматирование** — относитесь к конфигурациям как к коду. Используйте команду `kustomize cfg fmt` для форматирования и храните все файлы в Git (GitOps подход).
10. **Валидация результата** — используйте [kubeconform](../kubeconform_overview.md) перед применением манифестов в CI/CD.

### Очистка и откат изменений

После тестирования или при обнаружении проблем в production необходимо знать, как откатить изменения:

```bash
# 1. Откат Deployment к предыдущей ревизии (по умолчанию — на 1 шаг назад)
kubectl rollout undo deployment/prod-web-server -n production
# → deployment.apps/prod-web-server rolled back

# 2. Отключение и удаление ресурсов, созданных тестовым overlay
kubectl delete -k overlays/development/
# → Удаляет только ресурсы, помеченные этим оверлеем

# 3. Удаление с потерей — удаление по тех же меткам/именам
kubectl get -k overlays/production/ -o name | xargs kubectl delete
# → Удобно, когда kustomization.yaml уже изменён и -k недоступен

# 4. Просмотр истории rollout'ов (для диагностики)
kubectl rollout history deployment/prod-web-server -n production
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         <none>
```

### Граничные случаи и ограничения

*   **Удалённые базы (Remote bases):** при ссылке на Git URL Kustomize клонирует репозиторий во временную директорию. Убедитесь, что в CI-окружении есть доступ к сети и `git`. Кэширования между запусками нет — каждый `build` заново клонирует.
*   **Immutable Secrets и хеш:** если в базе явно задан `immutable: true` для Secret/ConfigMap, Kustomize добавит хеш к имени, но Kubernetes не позволит обновить существующий immutable-объект. Требуется удалить старый и создать новый.
*   **Порядок применения патчей:** патчи применяются строго в порядке перечисления в списке `patches`. Если один патч зависит от результата другого, расположите их последовательно.
*   **Namespace в base:** указание `namespace` в базовой конфигурации вызывает ошибку `may not be specified in a kustomization file of kind Kustomization`. Namespace задаётся только на уровне overlay.
*   **Генераторы vs ресурсы:** если в `base` есть статический `configmap.yaml`, а в `overlay` — `configMapGenerator` с тем же именем, Kustomize создаст два ConfigMap с разными именами (хешированным и статическим). Используйте `behavior: merge` или `behavior: replace` для слияния.
*   **JSON Patch и индексы массивов:** при работе с массивами (например, `containers[0]`) индекс может сместиться после применения другого патча. Используйте JSON Patch с `name`-селекторами или Strategic Merge для более надёжного адресования.
*   **Кэш ресурсов:** в некоторых версиях Kustomize (v4.x) наблюдалось кэширование удалённых ресурсов. При проблемах с актуальностью добавьте `--enable-git-inject` или очистите кэш вручную.

### См. также

- [Официальный сайт и документация Kustomize](https://kustomize.io/)
- [Наложения и патчи](./kustomize_overlays_and_patches.md) — механизмы модификации
- [Продвинутые возможности](./kustomize_advanced_features.md) — генераторы и Helm-интеграция
