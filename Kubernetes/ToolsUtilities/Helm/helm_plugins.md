# Плагины Helm

Расширение функциональности Helm CLI через сторонние скрипты, исполняемые файлы и модули WebAssembly (WASM). В Helm v4 (стандарт 2026 года) система плагинов обеспечивает изоляцию через WASM-песочницу, обязательную типизацию и нативную поддержку OCI-реестров.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Плагин (Plugin)** | Автономный инструмент, интегрируемый в `helm` CLI для расширения его возможностей. |
| **WASM-плагин** | (Helm v4+) Плагин, скомпилированный в WebAssembly, работающий в изолированной среде (Extism runtime). |
| **Классический плагин (Legacy/Binary)** | Плагин v3-совместимого типа, запускаемый как дочерний процесс (Bash, Go, Python). В v4 поддерживается для обратной совместимости, но не имеет изоляции. |
| **Метаданные (`plugin.yaml`)** | Файл манифеста плагина, определяющий его имя, версию, тип, конфигурацию среды выполнения и разрешения безопасности. |
| **Тип плагина (Plugin Type)** | (v4) Обязательная типизация: `cli/v1` (дополнительные команды), `getter/v1` (протоколы загрузки), `postrenderer/v1` (модификация манифестов). |
| **WASM-песочница (Sandbox)** | Изолированная среда выполнения с декларативно заданным доступом к сети, ФС и переменным окружения. |
| **Хуки плагина (Plugin Hooks)** | Жизненные циклы плагина: `pre-install`, `post-install`, `pre-upgrade`, `post-upgrade`, `pre-uninstall`, `post-uninstall`. Позволяют выполнять инициализацию и очистку. |
| **Discovery** | Механизм Helm, сканирующий `$HELM_PLUGINS` и зарегистрированные WASM-модули для построения дерева доступных команд. |

---

## Базовые концепции

### Управление плагинами

Плагины устанавливаются в директорию `$HELM_PLUGINS` (по умолчанию `~/.local/share/helm/plugins`). В версии v4 основным методом дистрибуции стал OCI (Open Container Initiative).

| Команда | Описание |
|---------|----------|
| `helm plugin install <url\|path>` | Установка плагина (GitHub-URL, локальная папка или OCI-артефакт). |
| `helm plugin list` | Вывод списка всех установленных плагинов, их версий и типов. |
| `helm plugin update <name>` | Обновление плагина до последней доступной версии. |
| `helm plugin uninstall <name>` | Удаление плагина из системы. |
| `helm plugin package <dir>` | (v4) Упаковка плагина в OCI-совместимый артефакт `.tgz`. |

### Типы плагинов и архитектура

В Helm v4 плагинная система перестроена согласно [HIP-0026](https://github.com/helm/community/blob/main/hips/hip-0026.md). Существует два типа исполнения:

1.  **Классические плагины (Subprocess):** Запускаются как дочерние процессы (Binary/Bash). Наследуют переменные окружения и имеют полный доступ к ФС пользователя. В v4 считаются "легаси" из-за отсутствия изоляции. Поддерживаются для обратной совместимости с v3.
2.  **WASM-плагины (Extism runtime):** Современный стандарт. Модуль `.wasm` исполняется в песочнице. Все разрешения (сеть, переменные, пути ФС) должны быть декларативно описаны в `plugin.yaml`.

**Стандартные переменные окружения (доступны всем типам плагинов):**
*   `HELM_BIN` — путь к исполняемому файлу `helm`.
*   `HELM_PLUGIN_DIR` — путь к директории с файлами самого плагина.
*   `HELM_NAMESPACE` — текущий неймспейс из контекста Kubernetes.
*   `HELM_KUBECONTEXT` — имя текущего контекста кластера.

### Жизненный цикл плагина

1.  **Discovery:** Helm сканирует `$HELM_PLUGINS` (или встроенные WASM-модули) и загружает `plugin.yaml`.
2.  **Validation:** Проверяется `apiVersion`, `type`, наличие исполняемого файла или WASM-модуля.
3.  **Registration:** Плагин регистрируется в CLI под указанным именем.
4.  **Execution:** При вызове `helm <plugin-name> ...` происходит запуск с передачей аргументов и окружения.
5.  **Teardown:** При `helm plugin uninstall` удаляется директория и запись из реестра.

### Хуки плагинов

Плагины могут определять хуки для автоматизации задач при установке/обновлении/удалении:

| Хук | Выполняется |
|-----|-------------|
| `pre-install` | Перед установкой плагина |
| `post-install` | После успешной установки |
| `pre-upgrade` | Перед обновлением |
| `post-upgrade` | После успешного обновления |
| `pre-uninstall` | Перед удалением |
| `post-uninstall` | После удаления |

Хуки полезны для: проверки зависимостей (curl, jq), настройки конфигурации по умолчанию, регистрации completion-скриптов, проверки подписей GPG.

### Discovery и приоритет

Если в `$HELM_PLUGINS` обнаружено несколько плагинов с одинаковым именем:
1.  Приоритет отдаётся WASM-плагину (если есть совпадение по имени).
2.  Затем классическому плагину.
3.  При конфликте Helm выводит предупреждение и использует первый найденный в алфавитном порядке директории.

Для предсказуемого поведения в CI pin'ьте плагины по пути или OCI-дигесту.

---

## Разработка плагина

### Структура манифеста `plugin.yaml`

Файл `plugin.yaml` является входной точкой и определяет поведение плагина в системе. Полная спецификация полей:

```yaml
apiVersion: helm.sh/v1
name: "my-advanced-plugin"
version: "1.2.0"
type: "cli/v1"
runtime: "extism/v1"  # Обязательно для WASM-плагинов; для классических — "binary" или "bash"

# Метаданные (используются в artifact hub и helm help)
description: "Плагин для проверки политик безопасности Helm-релизов"
home: "https://github.com/example/helm-security-checker"
sources:
  - "https://github.com/example/helm-security-checker"
maintainers:
  - name: "sysadmin"
    email: "ops@example.com"
keywords:
  - "security"
  - "policy"
  - "helm"
deprecated: false

# Инструкции для CLI
config:
  usage: "my-advanced-plugin [args]"
  shortHelp: "Краткое описание для helm help"
  longHelp: |
    Подробное описание плагина, отображаемое при helm my-advanced-plugin --help.
    Поддерживается многострочный текст.
  # Дополнительные параметры конфигурации (только для WASM)
  - name: policyFile
    type: string
    description: Путь к файлу политик YAML
    required: false
    default: "/etc/helm/policies/default.yaml"

# Настройки безопасности и изоляции (только для WASM)
runtimeConfig:
  module: "plugin.wasm"       # Имя WASM-модуля внутри плагина
  allowedHosts:               # Белый список доменов для сетевых вызовов
    - "api.github.com"
    - "registry.internal:5000"
  allowedEnv:                 # Список переменных окружения, доступных плагину
    - "KUBECONFIG"
    - "HOME"
  allowedPaths:               # (v4.1+) Разрешённые пути в ФС хоста
    - "/etc/helm/policies"
  timeout: 30000              # Ограничение времени выполнения в миллисекундах
```

> **Примечание:** В Helm v4 для плагинов типа `postrenderer/v1` также требуется `apiVersion: helm.sh/v1`. Поле `runtime` для классических плагинов может быть опущено или установлено в `binary`.

### Классический плагин (CLI)

Минимальный пример bash-плагина, добавляющего команду `helm env-check`:

**Структура:**
```text
helm-env-check/
├── plugin.yaml
└── env-check
```

**`plugin.yaml`:**
```yaml
apiVersion: helm.sh/v1
name: "env-check"
version: "0.1.0"
type: "cli/v1"
description: "Проверка окружения Helm и доступа к кластеру"
config:
  usage: "env-check"
  shortHelp: "Проверка окружения и RBAC"
```

**`env-check` (исполняемый файл):**
```bash
#!/usr/bin/env bash
set -euo pipefail

echo "Helm binary: ${HELM_BIN}"
echo "Namespace: ${HELM_NAMESPACE:-<not set>}"
echo "Kubecontext: ${HELM_KUBECONTEXT:-<not set>}"

# Проверка доступности кластера
if kubectl get nodes >/dev/null 2>&1; then
  echo "Cluster reachable: OK"
else
  echo "Cluster unreachable: FAIL"
  exit 1
fi
```

**Установка:**
```bash
chmod +x ./helm-env-check/env-check
helm plugin install ./helm-env-check
helm env-check
```

### WASM-плагин (Extism)

WASM-плагин компилируется из исходников на Go/Rust/C++ в бинарный модуль `.wasm`. Основные требования:
- Модуль должен экспортировать функцию с соглашением о вызовах Extism PDK.
- Всё состояние хранится в параметрах вызова; глобальная память не сохраняется между вызовами.
- Зависимости статически линкуются (нет доступа к динамическим библиотекам хоста).

**Структура:**
```text
policy-checker/
├── plugin.yaml
└── policy.wasm        # Скомпилированный WASM-модуль
```

**Минимальный `plugin.yaml` для WASM:**
```yaml
apiVersion: helm.sh/v1
name: "policy-checker"
version: "0.1.0"
type: "cli/v1"
runtime: "extism/v1"
config:
  usage: "policy-checker <chart-path>"
  shortHelp: "Проверка политик безопасности чарта"
runtimeConfig:
  module: "policy.wasm"
  timeout: 15000
```

### Публикация в OCI-реестры

Helm v4 позволяет хранить плагины в тех же реестрах, что и чарты (Harbor, ECR, GHCR, CNCF Distribution).

```bash
# 1. Упаковка (создаёт плагин с OCI-манифестом)
helm plugin package ./my-plugin

# 2. Авторизация и пуш
helm registry login registry.example.com -u svc-deployer
helm push my-advanced-plugin-1.2.0.tgz oci://registry.example.com/plugins

# 3. Установка конечным пользователем по версии
helm plugin install oci://registry.example.com/plugins/my-advanced-plugin --version 1.2.0

# 4. Установка по дигесту (иммутабельно, рекомендуется для CI)
DIGEST="sha256:$(helm show plugin oci://registry.example.com/plugins/my-advanced-plugin --version 1.2.0 \
  | awk '/^digest:/{print $2}')"
helm plugin install oci://registry.example.com/plugins/my-advanced-plugin@${DIGEST}
```

> **Примечание по тегам:** Helm при пуше преобразует `+` в `_` (например, `1.2.3+build.5` → `1.2.3_build.5`) из-за ограничений OCI.

### Отладка плагинов

Поскольку WASM-плагины работают в изоляции, их отладка требует использования логов среды выполнения:

1.  **Уровень логирования:** Используйте флаг `--debug` при запуске команд Helm для вывода системных сооб WASM-хоста.
2.  **Stdout/Stderr:** Весь вывод плагина в стандартные потоки пробрасывается в консоль пользователя.
3.  **WASM-инспекция:** Используйте инструменты типа `wasm-objdump` или `wasm-interp` для проверки структуры модуля перед упаковкой.
4.  **Трассировка Extism:** Для глубокой отладки используйте переменную окружения `EXTISM_DEBUG=1` для получения логов хоста WASM.

Для классических плагинов:
```bash
# Запуск с отладкой внешнего плагина
helm my-plugin --debug subcommand
# Или直接 запуск бинарника с переменными окружения
HELM_NAMESPACE=default HELM_KUBECONTEXT=prod ./env-check
```

---

## Практические сценарии

### helm-diff: Визуализация изменений

Самый востребованный плагин для GitOps. Показывает разницу между текущим состоянием ресурсов в кластере и тем, что определено в чарте. В v4 доступен как WASM-плагин и плотно интегрирован с **Server-Side Apply**.

```bash
# Просмотр изменений перед апгрейдом
helm diff upgrade my-app ./charts/my-app --values values.yaml
# → Output: показывает diff между текущим SSA-состоянием и новым чартом

# Сравнение двух ревизий релиза
helm diff revision my-app 10 11
```

### helm-secrets: Управление секретами

Интеграция с **Mozilla SOPS** для шифрования данных. Позволяет использовать зашифрованные файлы значений напрямую в командах Helm.

```bash
# Установка плагина
helm plugin install https://github.com/jkroepke/helm-secrets

# Деплой с расшифровкой на лету
helm secrets upgrade --install my-app ./chart -f values.yaml -f secrets.yaml
```

> Подробное руководство по интеграции helm-secrets с SOPS, паттерну `existingSecret` и лучшим практикам см. в [Helm + секреты](../../Base/secrets/helm_secrets.md).

### helm-unittest: Юнит-тестирование чартов

Позволяет писать BDD-тесты на YAML для проверки корректности рендеринга шаблонов без Kubernetes. Подробнее: [Юнит-тестирование Helm-чартов](../Advanced/unit_testing.md).

```bash
# Запуск тестов
helm unittest ./my-chart
# → Output: PASSED: 15, FAILED: 0
```

### helm-mapkubeapis: Исправление устаревших API

Помогает при миграции между версиями Kubernetes, обновляя аннотации ресурсов в метаданных релиза, чтобы они соответствовали новым версиям API.

```bash
# Обновление метаданных релиза
helm mapkubeapis my-release
```

### Создание кастомного CLI-плагина

Сценарий: организация требует обязательной проверки соответствия чарта корпоративным политикам перед каждым деплоем.

**Шаг 1: Создание структуры**
```bash
mkdir -p helm-policy-checker && cd helm-policy-checker
```

**Шаг 2: `plugin.yaml`**
```yaml
apiVersion: helm.sh/v1
name: "policy-checker"
version: "0.1.0"
type: "cli/v1"
description: "Валидация чартов по корпоративным политикам"
config:
  usage: "policy-checker <chart-path>"
  shortHelp: "Проверка соответствия политикам"
```

**Шаг 3: Исполняемый скрипт `policy-checker`**
```bash
#!/usr/bin/env bash
set -euo pipefail

CHART_PATH="${1:-.}"

# Проверка наличия values.schema.json
if [[ ! -f "${CHART_PATH}/values.schema.json" ]]; then
  echo "ERROR: values.schema.json отсутствует"
  exit 1
fi

# Проверка безопасности контекстов запуска
if grep -r 'privileged: true' "${CHART_PATH}/templates/" 2>/dev/null; then
  echo "ERROR: Обнаружен privileged: true"
  exit 1
fi

echo "OK: Политики пройдены"
```

**Шаг 4: Установка и интеграция в CI**
```bash
chmod +x policy-checker
helm plugin install .

# Использование в пайплайне
helm policy-checker ./my-chart && helm upgrade --install ...
```

### Создание пост-рендерера (Post-renderer plugin)

В Helm v4 пост-рендереры обязаны быть плагинами типа `postrenderer/v1`. Сценарий: инъекция стандартных меток и securityContext во все чарты без их форка.

**Структура:**
```text
kustomize-postrenderer/
├── plugin.yaml
└── kustomize-postrenderer.sh
```

**`plugin.yaml`:**
```yaml
apiVersion: helm.sh/v1
type: postrenderer/v1
name: kustomize
runtime: binary
version: 0.1.0
description: |
  Post-renderer, применяющий организационные патчи к отрендеренным Helm манифестам.
config:
  - name: kustomizationDir
    type: string
    description: Путь к директории с kustomization.yaml
    required: true
commands:
  - name: run
    description: Применить Kustomize и вернуть модифицированные манифесты
```

**`kustomize-postrenderer.sh`:**
```bash
#!/usr/bin/env bash
set -euo pipefail

KUZM_DIR="${HELM_PLUGIN_CONFIG_KUSTOMIZATIONDIR:-./kustomize}"

cat > "${KUZM_DIR}/all.yaml"
kustomize build "${KUZM_DIR}"
rm -f "${KUZM_DIR}/all.yaml"
```

**Запуск:**
```bash
helm plugin install ./kustomize-postrenderer
helm upgrade --install web oci://registry.example.com/charts/web-chart \
  --version 2.4.1 \
  --post-renderer kustomize
```

### Создание геттера (Getter plugin)

Геттеры расширяют протоколы загрузки чартов. Сценарий: загрузка чартов из внутреннего артефакт-стора по кастомному протоколу.

**`plugin.yaml`:**
```yaml
apiVersion: helm.sh/v1
name: "internal-getter"
version: "0.1.0"
type: "getter/v1"
config:
  - name: baseURL
    type: string
    description: Базовый URL внутреннего репозитория
    required: true
commands:
  - name: get
    description: Загрузка чарта по внутреннему протоколу
```

### Установка и обновление плагинов

**Из публичного GitHub:**
```bash
helm plugin install https://github.com/databus23/helm-diff
```

**Из локального каталога:**
```bash
helm plugin install ./my-plugin
```

**Из OCI-реестра:**
```bash
helm plugin install oci://registry.example.com/plugins/my-plugin --version 1.2.0
```

**Обновление:**
```bash
helm plugin update helm-diff
```

**Удаление:**
```bash
helm plugin uninstall helm-diff
```

### Плагины в CI/CD пайплайнах

Для воспроизводимости CI используйте один из подходов:

1.  **Pre-baked раннер:** Образ Docker с предустановленными плагинами.
2.  **OCI-установка:** Плагины загружаются из корпоративного реестра с версионированием.
3.  **Docker-оборудка (helm-unittest):** Для тестирования используйте готовые образы.

```yaml
# Пример GitLab CI stage
test-helm:
  image: registry.example.com/ci/helm-runner:4.2.0
  script:
    - helm plugin install oci://registry.example.com/plugins/unittest:0.7.0
    - helm plugin install oci://registry.example.com/plugins/diff:4.2.0
    - helm unittest ./my-chart
    - helm diff upgrade my-app ./chart -f values.yaml
```

## Безопасность плагинов

### GPG-верификация при установке

Начиная с Helm 4, при `helm plugin install` из git проверяется GPG-подпись тега репозитория плагина. Если ключ не импортирован, установка завершается ошибкой `plugin signature verification failed`.

```bash
# Импорт публичного ключа плагина (один раз)
gpg --no-default-keyring --keyring ~/.config/helm/keyring.gpg \
    --import plugin-signing-key.asc

# Установка плагина
helm plugin install https://github.com/helm-unittest/helm-unittest.git
```

При установке из OCI/http-архива GPG-проверка работает штатно при наличии ключа в keyring.

### Установка по дигесту (SHA-пиннинг)

Для защиты от подмены артефакта устанавливайте плагины по дигесту:

```bash
# Установка по дигесту из доверенного реестра
helm plugin install oci://registry.company.com/plugins/security-checker@sha256:7f3a9c...
```

### WASM-песочница и воздушный зазор (Air-gapped)

- **WASM-плагины** имеют декларативный доступ: `allowedHosts`, `allowedEnv`, `allowedPaths`. Не указывайте `allowedHosts: ["*"]` в production.
- В **air-gapped средах** WASM-плагины не требуют Python/Bash на целевом хосте — только Extism runtime (входит в состав Helm 4).
- **Классические плагины** в air-gapped окружениях требуют предустановленных интерпретаторов (bash, python, jq) на всех раннерах.
- Для корпоративных реестров распространяйте WASM-модули через OCI вместе с подписью Cosign.

## Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| `plugin signature verification failed` | GPG-ключ плагина не импортирован в keyring | Импортируйте ключ через `gpg --import` или используйте `--verify=false` (только для доверенных источников). |
| `no plugin named ...` | Плагин не установлен или имя указано неверно | Проверьте `helm plugin list`. Для post-renderer используйте точное имя из `plugin.yaml`. |
| `plugin not registered` | Ошибка в `plugin.yaml` (неверный apiVersion/type) | Проверьте синтаксис манифеста; для post-renderer обязательно `apiVersion: helm.sh/v1`. |
| `permission denied` при установке | Файл плагина не исполняемый | `chmod +x <plugin-binary>` перед `helm plugin install`. |
| `connection refused` (WASM) | `allowedHosts` не включает целевой хост | Добавьте хост в `runtimeConfig.allowedHosts` в `plugin.yaml`. |
| `unknown flag: --post-renderer` | Используется Helm v3, а не v4 | В v3 используется прямой путь к файлу; в v4 требуется плагин `postrenderer/v1`. |
| `plugin panicked` | Паника внутри WASM-модуля или неверные входные данные | Проверьте входные аргументы; используйте `EXTISM_DEBUG=1` для трассировки. |
| `lookup` возвращает пустой объект | Режим отладки или неверные права RBAC | Для плагинов, запрашивающих кластер, проверьте ServiceAccount и KUBECONFIG. |

## Лучшие практики

- **WASM вместо классических:** Для новых плагинов используйте WASM — это обеспечивает изоляцию и кроссплатформенность.
- **GPG-верификация:** Никогда не используйте `--verify=false` в production, только в CI с изолированным доступом.
- **Пининг версий:** В CI указывайте точную версию плагина или OCI-дигест, чтобы избежать неожиданных изменений.
- **Минимальные разрешения:** Для WASM-плагинов указывайте только необходимые `allowedHosts`, `allowedEnv` и `allowedPaths`.
- **Completion-скрипты:** Если плагин добавляет CLI-команды, поставляйте shell-completion (`_completions` в `plugin.yaml` или хуки).
- **Тестирование:** Плагины должны проходить статический анализ (`helm lint`, `kubeconform`) и unit-тесты.
- **Документация:** Каждый плагин должен иметь README с примерами и описанием ошибок.

## Дополнительная информация

### Сравнение: классические vs WASM-плагины

| Характеристика | Классический (v3 legacy) | WASM (v4) |
|-----------------|--------------------------|-----------|
| Изоляция | Нет (полный доступ к ФС/сети) | Да (песочница Extism) |
| Зависимости | Требует bash/python/go на хосте | Требует только Extism runtime |
| Кроссплатформенность | Нет (скрипты под конкретную ОС) | Да (один `.wasm` для всех ОС) |
| Безопасность | Риск выполнения произвольного кода | Ограничено манифестом `plugin.yaml` |
| Производительность | Нет overhead | Небольшой overhead на вызовы хоста |
| Дистрибуция | Git/HTTP | OCI (рекомендуется) |

### Полезные ссылки

*   [Artifact Hub (поиск плагинов)](https://artifacthub.io/)
*   [HIP-0026: Helm v4 Plugin System](https://github.com/helm/community/blob/main/hips/hip-0026.md)
*   [Официальная документация по WASM SDK](https://helm.sh/docs/wasm-sdk/)
*   [Extism Runtime](https://extism.io/)

См. также:
*   [Обзор Helm](./helm_overview.md) — архитектура v4 и SSA
*   [Безопасность Helm](../Advanced/security_best_practices.md) — GPG, WASM-песочница, air-gapped
*   [Продвинутые сценарии Helm](../Advanced/scenarios.md) — пост-рендеринг и адаптивные чарты
*   [Helmfile](./helmfile_overview.md) — декларативное управление
*   [Argo CD: Custom Tooling](../../../GitOps/ArgoCD/argocd_custom_tooling.md) — интеграция плагинов в GitOps-пайплайны
