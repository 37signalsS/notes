# Обзор Helm

Helm — промышленный стандарт пакетного менеджера для Kubernetes, обеспечивающий полный жизненный цикл приложений через механизмы шаблонизации, версионирования и декларативного управления. В актуальной версии v4.2.0 (состояние на 2026 год) Helm интегрирует нативную поддержку Server-Side Apply (SSA) и расширяемую архитектуру на базе WebAssembly (WASM).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Chart (Чарт)** | Пакет манифестов и шаблонов, описывающих набор ресурсов Kubernetes. См. [Структура Helm-чарта](./helm_chart_structure.md). |
| **Release (Релиз)** | Экземпляр чарта, развёрнутый в кластере под конкретным именем. Управляется через SSA в v4. |
| **OCI Registry** | Реестр артефактов (Open Container Initiative), ставший в v4 основным способом хранения и дистрибуции чартов. |
| **Values (Значения)** | Внешние параметры конфигурации (`values.yaml`), позволяющие динамически изменять параметры рендеринга шаблонов. |
| **WASM Plugin** | Кроссплатформенное расширение Helm CLI, исполняемое в изолированной песочнице (Extism runtime). |
| **Server-Side Apply (SSA)** | Стратегия применения манифестов, при которой логика слияния и владения полями (field ownership) делегируется Kubernetes API. |
| **kstatus** | Библиотека, используемая в v4 для унифицированного определения состояния готовности (Readiness) ресурсов. |
| **Ревизия (Revision)** | Порядковый номер версии релиза, увеличивающийся при каждом `upgrade` или `rollback`. |
| **Полевая принадлежность (Field Ownership)** | Механизм SSA, при котором Kubernetes отслеживает, какой менеджер (Helm, HPA, оператор) управляет каждым полем ресурса. |
| **helmignore** | Файл `.helmignore` со списком паттернов для исключения файлов из пакета чарта (аналог `.gitignore`). |
| **Chart version vs App version** | `version` — версия самого чарта (SemVer), `appVersion` — версия приложения, разворачиваемого внутри чарта. |

---

## Проблемы, которые решает Helm

Kubernetes не имеет понятия «приложение». Кластер видит только отдельные объекты (Deployment, Service, ConfigMap, Secret и т. д.), между которыми нет никакой связи. Это порождает три ключевые проблемы:

1.  **Дрейф окружений.** При нескольких окружениях (dev, stage, prod) один и тот же набор манифестов размножается копированием. Даже минимальные отличия (тег образа, количество реплик, домен, лимиты ресурсов) со временем приводят к тому, что окружения расходятся, и воспроизвести ошибку вне конкретного окружения становится невозможно.
2.  **Отсутствие операций уровня приложения.** В Kubernetes нет команд «обновить приложение» или «удалить приложение» — есть только применение конкретных манифестов и удаление отдельных объектов. Если при удалении забыть про ConfigMap, он остаётся висеть в кластере до случайного обнаружения.
3.  **Проблема «Чужой софт».** Для установки инфраструктурных компонентов (операторы, контроллеры) приходится копировать из документации десятки манифестов, которые вы видите впервые, и надеяться, что автор ничего не забыл.

Helm решает эти проблемы, добавляя слой абстракции «приложение»: чарт группирует объекты, релиз даёт им имя и историю, а команды `install`, `upgrade`, `rollback`, `uninstall` работают с приложением целиком. При этом сам чарт по себе ничего делать не будет — это просто набор шаблонов и значений, который становится рабочим приложением только после установки в кластер.

---

## Базовые концепции

### Архитектура Helm v4

Helm v4 сохраняет модель "Client-only" (без серверных компонентов внутри кластера), но переходит на современные примитивы Kubernetes для управления состоянием.

1.  **Декларативное управление через SSA**: В отличие от Three-way merge (v3), где слияние происходило на стороне клиента, v4 передаёт манифесты напрямую в API-сервер с флагом `--server-side`. Это позволяет точно отслеживать, какие поля контролируются Helm, а какие — сторонними контроллерами (например, HPA или Mesh-инъекторами).
2.  **Мониторинг состояния (Readiness)**: Helm v4 интегрирует стандарт `kstatus`, что позволяет ему понимать состояние готовности кастомных ресурсов (CRD) и стандартных объектов без написания специфических хуков.
3.  **Изоляция и портативность**: Переход на WASM-плагины устраняет зависимости от ОС хоста и Python/Bash интерпретаторов, делая расширения (например, `helm-diff`) стабильными в любых средах.

### Жизненный цикл релиза

Helm управляет состоянием приложений через релизы. Каждый релиз проходит через несколько этапов:

1.  **Install**: Создание нового релиза. Helm рендерит шаблоны, применяет манифесты в кластер и сохраняет снимок значений в Secret.
2.  **Upgrade**: Обновление существующего релиза. В v4 по умолчанию используется SSA, что позволяет безопасно обновлять ресурсы, изменённые внешними контроллерами.
3.  **Rollback**: Откат к предыдущей ревизии. Важно понимать, что откат возвращает только манифесты: он не откатывает состояние базы данных, не отменяет применённые миграции и не восстанавливает удалённые при обновлении тома (PVC). Каждая ревизия хранится как отдельный Secret; откат не пересчитывает чарт и не смотрит, каким приложение было «раньше» — он просто применяет готовый снапшот манифеста заново. При этом откат создаёт новую ревизию, а не уменьшает счётчик: если у вас было три ревизии и вы откатились ко второй, их станет четыре (четвёртая повторяет вторую). История Helm только растёт.
4.  **Uninstall**: Удаление релиза и всех управляемых ресурсов. При флаге `--keep-history` только ресурсы удаляются, а история сохраняется для возможного отката.

### Иерархия значений (Values Hierarchy)

Helm v4 использует Server-Side Apply (SSA), что позволяет внешним контроллерам (HPA, cert-manager) изменять ресурсы без конфликтов. Порядок применения значений (от высшего к низшему приоритету):

1.  `--set` / `--set-string` флаги CLI
2.  Файлы `-f values.yaml` (последний файл перезаписывает предыдущие)
3.  Значения по умолчанию из `values.yaml` чарта
4.  Встроенные значения системных объектов (например, `.Release.Name`, `.Release.Namespace`)

### Переменные окружения

| Переменная | Описание |
|------------|----------|
| `HELM_PLUGINS` | Путь к директории с плагинами (по умолчанию `~/.local/share/helm/plugins`). |
| `HELM_CONFIG_HOME` | Директория для конфигурационных файлов (реестры, кеш аутентификации). |
| `HELM_CACHE_HOME` | Директория кеша (загруженные чарты, OCI-манифесты). |
| `HELM_DATA_HOME` | Директория для данных (история, ревизии). |
| `HELM_NAMESPACE` | Namespace по умолчанию (если не указан в команде). |
| `HELM_KUBECONTEXT` | Контекст kubectl по умолчанию. |
| `HELM_DEBUG` | Включает детальное логирование для отладки. |
| `HELM_NO_PLUGINS` | Отключает загрузку плагинов (полезно в CI с ограниченными правами). |

### Почему Helm? (Пакетный подход)

Helm решает проблему "YAML-ада" и фрагментированного управления инфраструктурой:

*   **Абстракция и повторное использование**: Создание универсальных шаблонов для сложных приложений (например, база данных с PVC, Service, ConfigMap и StatefulSet) исключает дублирование кода.
*   **Управление жизненным циклом**: Команды `install`, `upgrade` и `rollback` обеспечивают атомарность изменений и возможность быстрого возврата к стабильной версии при сбоях.
*   **Стандартизация в GitOps**: Helm-чарты являются базовым кирпичом для Argo CD и Flux, обеспечивая единый интерфейс между разработкой и эксплуатацией.
*   **Безопасность**: Нативная поддержка шифрования секретов (`helm-secrets` + SOPS) и проверка подписей чартов (Cosign/Sigstore).

---

## Установка CLI

> **Актуальная версия:** Helm v4.2.0. Версия v3 находится в статусе EOL (End of Life) с ноября 2026.

### Предварительные требования

*   **Kubernetes cluster**: v1.24+ (рекомендуется v1.29+ для полной поддержки SSA и Gateway API).
*   **kubectl**: версия должна совпадать с версией Kubernetes-кластера.
*   **kubeconfig**: файл конфигурации с правами на создание ресурсов в целевом namespace.

### Установка в Linux/macOS:

```bash
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-4
chmod 700 get_helm.sh
./get_helm.sh
```

### Установка в Windows (PowerShell):

```powershell
Invoke-WebRequest -Uri "https://get.helm.sh/helm-v4.2.0-windows-amd64.zip" -OutFile "helm.zip"
Expand-Archive -Path "helm.zip" -DestinationPath "C:\helm"
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\helm", "User")
```

### Установка через пакетный менеджер

**Homebrew (macOS/Linux):**
```bash
brew install helm
```

**APT (Debian/Ubuntu):**
```bash
curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
sudo apt-get install apt-transport-https --yes
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
sudo apt-get update
sudo apt-get install helm
```

### Проверка конфигурации:

```bash
helm version
# → version.BuildInfo{Version:"v4.2.0", GitCommit:"...", ...}

# Проверка подключения к кластеру
helm list --all-namespaces
# → (пустой вывод или список релизов)

# Проверка kubeconfig
kubectl config current-context
# → prod-cluster
```

---

## Практические сценарии

### Управление репозиториями чартов

Добавление, обновление и поиск чартов в репозиториях:

```bash
# Добавление официального репозитория
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Поиск доступных чартов
helm search repo nginx
# → NAME                                    CHART VERSION   APP VERSION   DESCRIPTION
# → bitnami/nginx                           ...              ...           Chart for the nginx web server

# Просмотр доступных версий чарта
helm search repo bitnami/nginx --versions
```

### Инспектирование чартов перед установкой

Всегда проверяйте содержимое чарта перед деплоем:

```bash
# Просмотр метаданных (Chart.yaml)
helm show chart bitnami/nginx

# Просмотр всех значений по умолчанию
helm show values bitnami/nginx > nginx-values.yaml

# Просмотр сгенерированных манифестов без применения
helm template my-nginx bitnami/nginx -f values.yaml

# Валидация синтаксиса чарта
helm lint bitnami/nginx -f values.yaml
# → 1 chart(s) linted, 0 chart(s) failed
```

### Использование Server-Side Apply (SSA)

В v4 SSA включен по умолчанию. Это критично для избежания конфликтов с внешними операторами.

```bash
# Установка с явным подтверждением владения полями
helm upgrade --install my-app oci://registry.example.com/charts/my-app \
  --values values.yaml \
  --server-side \
  --force-conflicts  # Перехват владения полями, если они были изменены вручную
```

**Разрешение конфликтов владения полями:**

Если поле управляется другим контроллером, Helm v4 не затирает его, если не указан флаг `--force-conflicts`. Для анализа конфликтов используйте:

```bash
# Просмотр управляемых полей
kubectl get deployment my-app -o jsonpath='{.metadata.managedFields}'
```

### Отслеживание готовности через kstatus

В шаблонах чарта теперь можно использовать стандартные аннотации для управления поведением `helm install --wait`.

```yaml
# templates/deployment.yaml
metadata:
  annotations:
    helm.sh/readiness-success: "Condition=Ready" # Ожидание конкретного условия через kstatus
```

```bash
# Установка с ожиданием готовности (включая CRD)
helm install my-app ./chart \
  --namespace prod \
  --create-namespace \
  --wait \
  --timeout 10m \
  --atomic  # Автоматический откат при таймауте
```

### Работа с OCI-реестрами

В версии v4 поддержка OCI является основной. Работа с классическими HTTP-репозиториями (ChartMuseum) считается легаси.

```bash
# Авторизация (требуется только домен)
helm registry login registry.example.com

# Установка по точному дигесту (Immutable Infrastructure)
helm install my-release oci://registry.example.com/charts/my-app@sha256:7f...

# Просмотр значений из OCI-репозитория
helm show values oci://registry.example.com/charts/my-app --version 1.2.3

# Пакет и публикация чарта
helm package ./my-chart
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts
```

### Управление релизами

Интроспекция и управление установленными релизами:

```bash
# Список всех релизов
helm list --all-namespaces

# История ревизий релиза
helm history my-app -n prod

# Просмотр значений релиза
helm get values my-app -n prod
helm get values my-app -n prod --all  # Включая дефолты

# Просмотр манифестов релиза
helm get manifest my-app -n prod

# Откат к предыдущей ревизии
helm rollback my-app 1 -n prod

# Полное удаление с сохранением истории
helm uninstall my-app -n prod --keep-history
```

### Управление зависимостями

Helm v4 управляет зависимостями через секцию `dependencies` в `Chart.yaml`:

```bash
# Загрузка зависимостей
helm dependency update ./my-chart

# Создание lock-файла
helm dependency build ./my-chart

# Просмотр графа зависимостей
helm dependency list ./my-chart
```

**Пример `Chart.yaml` с зависимостями:**
```yaml
apiVersion: v2
name: my-app
version: 1.0.0
dependencies:
  - name: postgresql
    version: "12.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    condition: postgresql.enabled
    alias: db
```

### .helmignore

Файл `.helmignore` исключает временные файлы и документацию из пакета:

```text
.git/
.idea/
*.md
!README.md
*.tgz
*.swp
*.bak
```

### Air-gapped развёртывание

В изолированных сетях без доступа в интернет используются локальные OCI-реестры:

```bash
# На машине с интернетом: пакет и загрузка
helm package ./my-chart
helm push my-chart-1.0.0.tgz oci://harbor.internal/library/charts

# На целевом кластере: установка из внутреннего реестра
helm registry login harbor.internal -u admin -p password
helm install my-app oci://harbor.internal/library/charts/my-app@sha256:abc123...
```

### Интеграция в CI/CD пайплайны

Типичный паттерн для GitLab CI / GitHub Actions:

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - deploy

helm-lint:
  stage: lint
  image: alpine/helm:4.2.0
  script:
    - helm lint ./chart
    - helm template test-release ./chart --dry-run

helm-deploy:
  stage: deploy
  image: alpine/helm:4.2.0
  script:
    - helm upgrade --install my-app ./chart \
        --namespace prod \
        --values values-prod.yaml \
        --atomic \
        --timeout 10m
  environment:
    name: production
```

---

## Устранение неисправностей

| Симптом | Возможная причина | Решение |
|---------|------------------|---------|
| `Error: rendered manifests contain a resource that already exists` | Релиз с таким именем уже существует | `helm list --all-namespaces`; используйте `helm upgrade` или `helm install --generate-name` |
| `Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is in progress` | Предыдущая операция не завершилась | `helm history <release>`; проверьте `kubectl get secrets -n <ns>`; используйте `helm rollback` или `helm uninstall --keep-history` |
| `Error: INSTALLATION FAILED: failed post-renderer` | Ошибка в пост-рендерере | Проверьте вывод `--debug`; убедитесь, что плагин типа `postrenderer/v1` установлен |
| `Error: chart "xxx" matching ... not found` | Репозиторий не добавлен или не обновлён | `helm repo add`, `helm repo update`; проверьте `helm repo list` |
| `Error: incompatible versions` | Конфликт версий Chart.yaml и зависимостей | Проверьте `Chart.lock`; выполните `helm dependency update` |
| `Error: release: "xxx" already exists` | Релиз существует, но Helm не может его обновить | Проверьте namespace; используйте `helm list --all-namespaces` |
| `Error: field is immutable` | Попытка изменить неизменяемое поле (например, `spec.clusterIP`) | Используйте `helm upgrade` с изменённым values.yaml; или удалите и создайте заново с `helm uninstall` |
| `Error: Apply failed due to conflicts` | Конфликт SSA с другим контроллером | Определите владельца поля через `kubectl get <resource> -o yaml`; используйте `--force-conflicts` если Helm должен управлять полем |

---

## Лучшие практики

1.  **Атомарные деплои**: Всегда используйте `--atomic` и `--timeout` для автоматического отката при сбоях.
2.  **Фиксация версий**: Указывайте `--version` для чартов и фиксируйте версии образов в `values.yaml`. Используйте OCI-дигесты (`@sha256:...`) для полной воспроизводимости.
3.  **Values в Git**: Храните `values.yaml` в Git, но секреты шифруйте через `sops` или `helm-secrets`. Никогда не коммитьте открытые секреты.
4.  **SSA без конфликтов**: По умолчанию Helm v4 кооперируется с HPA и другими контроллерами. Используйте `--force-conflicts` только при миграции или если поле должно принадлежать Helm.
5.  **Валидация**: Интегрируйте `helm lint` и `helm template` в CI. Для production добавляйте `helm unittest` и `kubeconform`.
6.  **Минимальные разрешения**: Создавайте отдельные ServiceAccount и Namespace для каждого релиза. Не используйте `cluster-admin`.
7.  **Очистка**: Регулярно удаляйте неиспользуемые релизы: `helm uninstall --keep-history` для сохранения истории, или полностью для освобождения ресурсов.
8.  **Лимит истории ревизий:** Устанавливайте `--history-max` в диапазоне 10–20. Журнал ревизий хранится в Secrets и не бесконечен: при частых неудачных деплоях с последующими откатами он может заполниться неработающими версиями. Заранее узнайте лимит у вашего кластера.

---

## Ограничения и особенности

*   **SSA и устаревшие Kubernetes**: Кластеры Kubernetes <1.18 не поддерживают полный функционал SSA и Field Ownership. При миграции на Helm v4 требуется предварительное обновление Kubernetes.
*   **WASM-плагины**: Не все плагины v3 имеют портированные версии для WASM. Плагины, требующие длительных операций или интенсивного доступа к файловой системе, могут иметь ограничения производительности в песочнице Extism.
*   **OCI-репозитории за прокси**: При работе через корпоративные прокси требуется предварительная настройка доверенных корневых сертификатов для OCI-реестров. Дигесты артефактов должны проверяться на этапе сборки.
*   **Пост-рендеринг**: Сложные мутации, требующие доступа к состоянию кластера, не могут быть реализованы через пост-рендерер. Для динамических мутаций требуются операторы или admission webhooks (Kyverno, OPA Gatekeeper).
*   **Значения по умолчанию**: Helm не валидирует `values.yaml` пользователя на соответствие `values.schema.json` при `helm install` — только `helm lint` проверяет схему. Всегда запускайте `helm lint` перед деплоем.
*   **CRD и обновления**: Helm не обновляет и не удаляет CRD из директории `crds/` при обновлении или удалении релиза. Это защищает данные, но требует ручного обновления CRD при необходимости.
*   **Откат не откатывает внешнее состояние:** `helm rollback` возвращает только манифесты. Данные в базе, применённые миграции, тома (PVC) и любые изменения, сделанные outside манифестов, остаются как есть. Helm не является машиной времени для состояния приложения.

---

## Дополнительная информация

### Расширенный функционал

*   **[Зависимости и библиотеки](./helm_dependencies_and_library_charts.md)** — модульное построение чартов.
*   **[Хуки и тестирование](./helm_hooks_and_tests.md)** — автоматизация проверок и миграций.
*   **[Плагины Helm](./helm_plugins.md)** — расширение CLI через WASM.

### Связанные инструменты

*   **[Helmfile](./helmfile_overview.md)** — декларативный оркестратор для управления группами релизов.
*   **[Helmwave](./helmwave_overview.md)** — современная альтернатива на Go с поддержкой сложных графов зависимостей.
*   **[Argo CD: Интеграция с Helm](../../../GitOps/ArgoCD/helm_integration.md)** — использование Helm в GitOps-пайплайнах.

### См. также

*   [Сравнение версий Helm](./helm_v2_vs_v3.md) — детали миграции и стратегий слияния.
*   [Команды и рабочий процесс](./helm_commands_and_workflow.md) — интроспекция, управление релизами и отладка.
*   [Продвинутые возможности](./Advanced/index.md) — OCI, Post-rendering, WASM-плагины и Policy-as-Code.

### Полезные ресурсы

*   [Artifact Hub](https://artifacthub.io) — глобальный поиск публичных чартов.
*   [Документация Helm v4](https://helm.sh/docs/v4/) — официальное руководство (англ.).
*   [Сравнение стратегий слияния](./helm_v2_vs_v3.md) — детали работы SSA и Three-way merge.
