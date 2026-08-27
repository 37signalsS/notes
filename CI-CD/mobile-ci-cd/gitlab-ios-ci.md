# GitLab CI/CD для iOS и macOS: Настройка и масштабирование

## Определения

**GitLab iOS CI/CD** — это реализация процессов сборки, тестирования и доставки приложений для экосистемы Apple с использованием инфраструктуры GitLab. Основная сложность заключается в необходимости использования проприетарного оборудования (macOS) и жестких правил подписи кода (Code Signing).

**Shell Executor** — рекомендуемый тип исполнителя для macOS-раннеров. В отличие от Docker, он предоставляет прямой доступ к Xcode, симуляторам и системной связке ключей (Keychain), что критично для сборки iOS.

**Ephemeral Keychain** — временная связка ключей, создаваемая внутри джобы GitLab CI для безопасного хранения сертификатов и их автоматического удаления после завершения сборки.

---

## Базовые концепции

### Архитектура macOS-раннеров

Для эффективной работы iOS-команд рекомендуется гибридная схема:
1.  **Dedicated Runners:** Физические Mac mini или Mac Studio для тяжелых сборок и UI-тестов.
2.  **Virtualization (Tart/Orka):** Использование эфемерных виртуальных машин для обеспечения чистоты окружения и параллелизма.
3.  **Tags:** Обязательное использование тегов (например, `ios`, `macos`, `xcode-16.1`) для точного подбора раннера с нужной версией SDK.

---

## Практическая реализация

### 1. Установка и регистрация раннера на macOS

**Шаг 1: Установка через Homebrew**
```bash
brew install gitlab-runner
brew services start gitlab-runner
```

**Шаг 2: Регистрация (Shell Executor)**
При регистрации обязательно используйте `glrt-` токен, созданный в UI GitLab.
```bash
gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.com/" \
  --token "glrt-YOUR_MAC_TOKEN" \
  --executor "shell" \
  --tag-list "ios,macos,xcode-16" \
  --description "Mac Mini M2 - Office Infrastructure"
```

**Шаг 3: Настройка multiple runners на одном Mac**
```bash
# Регистрация второго раннера для другой версии Xcode
gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.com/" \
  --token "glrt-SECOND_TOKEN" \
  --executor "shell" \
  --tag-list "ios,macos,xcode-15" \
  --description "Mac Mini M1 - Legacy Support" \
  --working-directory "/Users/developer/builds" \
  --config "/etc/gitlab-runner/config-second.toml"
```

**Шаг 4: Настройка concurrent jobs в `config.toml`**
```toml
concurrent = 4
check_interval = 3

[[runners]]
  name = "Mac Mini M2 - iOS"
  url = "https://gitlab.com/"
  token = "glrt-XXX"
  executor = "shell"
  shell = "zsh"
  environment = ["IOS_BUILD_ENV=true"]
  limit = 2  # Лимит параллельных задач на этом раннере
  [runners.cache]
    Type = "s3"
    Shared = true
```

**Шаг 5: Управление раннерами через CLI**
```bash
# Просмотр всех зарегистрированных раннеров
gitlab-runner list

# Проверка статуса раннера
gitlab-runner verify

# Остановка/перезапуск раннера
gitlab-runner stop
gitlab-runner start

# Удаление старого раннера
gitlab-runner unregister --name "Mac Mini M1 - Legacy Support"
```

### 2. Управление Keychain в CI/CD

**Создание ephemeral keychain:**
```bash
#!/bin/bash
# ci_create_keychain.sh

KEYCHAIN_NAME="ci_build_keychain"
KEYCHAIN_PASSWORD=$(openssl rand -base64 32)

# Создание keychain
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_NAME.keychain"

# Отключение auto-lock
security set-keychain-settings -lut 21600 "$KEYCHAIN_NAME.keychain"

# Разблокировка keychain
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_NAME.keychain"

# Добавление в search list
security list-keychains -d user -s "$KEYCHAIN_NAME.keychain" login.keychain

echo "Keychain создан: $KEYCHAIN_NAME.keychain"
```

**Импорт сертификатов в ephemeral keychain:**
```bash
#!/bin/bash
# ci_import_certificates.sh

KEYCHAIN_NAME="ci_build_keychain"
CERTIFICATE_PATH="$1"
CERTIFICATE_PASSWORD="$2"

if [ -z "$CERTIFICATE_PATH" ] || [ -z "$CERTIFICATE_PASSWORD" ]; then
  echo "Usage: $0 <certificate.p12> <password>"
  exit 1
fi

# Импорт сертификата
security import "$CERTIFICATE_PATH" \
  -k "$KEYCHAIN_NAME.keychain" \
  -P "$CERTIFICATE_PASSWORD" \
  -T /usr/bin/codesign \
  -T /usr/bin/security

# Настройка ACL для codesign
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "" "$KEYCHAIN_NAME.keychain"

echo "Сертификат импортирован"
```

**Очистка keychain после сборки:**
```bash
#!/bin/bash
# ci_cleanup_keychain.sh

KEYCHAIN_NAME="ci_build_keychain"

# Удаление keychain
security delete-keychain "$KEYCHAIN_NAME.keychain"

echo "Keychain удален"
```

### 2. Конфигурация .gitlab-ci.yml

Пример базового пайплайна для iOS с использованием Fastlane:

```yaml
variables:
  LC_ALL: "en_US.UTF-8"
  LANG: "en_US.UTF-8"

stages:
  - setup
  - test
  - build
  - deploy

# Шаблон для всех джоб iOS
.ios_base:
  tags:
    - ios
  before_script:
    - bundle install --path vendor/bundle

setup_dependencies:
  extends: .ios_base
  stage: setup
  script:
    - bundle exec fastlane install_plugins
  cache:
    key:
      files:
        - Gemfile.lock
    paths:
      - vendor/bundle

unit_tests:
  extends: .ios_base
  stage: test
  script:
    - bundle exec fastlane test
  artifacts:
    reports:
      junit: fastlane/test_output/report.xml

build_ipa:
  extends: .ios_base
  stage: build
  script:
    - bundle exec fastlane release
  artifacts:
    paths:
      - ./build/*.ipa
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_TAG
```

**Расширенный пайплайн с параллельными тестами и кэшированием:**
```yaml
variables:
  LC_ALL: "en_US.UTF-8"
  LANG: "en_US.UTF-8"
  DERIVED_DATA_PATH: "$CI_PROJECT_DIR/.derived_data"
  MAX_PARALLEL_TESTS: 4

stages:
  - setup
  - lint
  - test
  - build
  - distribute

.ios_base:
  tags:
    - ios
  before_script:
    - bundle install --path vendor/bundle
    - xcodebuild -version

setup_dependencies:
  extends: .ios_base
  stage: setup
  script:
    - bundle exec fastlane install_plugins
    - bundle exec fastlane run cocoapods_install
  cache:
    key:
      files:
        - Gemfile.lock
        - Podfile.lock
    paths:
      - vendor/bundle
      - Pods/
      - .build/

lint_code:
  extends: .ios_base
  stage: lint
  script:
    - bundle exec fastlane run swiftlint
  allow_failure: true

unit_tests_parallel:
  extends: .ios_base
  stage: test
  parallel: 4
  script:
    - |
      bundle exec fastlane test \
        --derived_data_path "$DERIVED_DATA_PATH" \
        --parallel_testing \
        --parallel_count $MAX_PARALLEL_TESTS
  artifacts:
    reports:
      junit:
        - fastlane/test_output/report-*.xml
    paths:
      - fastlane/test_output/
    expire_in: 3 days
  cache:
    key:
      files:
        - Podfile.lock
    paths:
      - Pods/

ui_tests:
  extends: .ios_base
  stage: test
  script:
    - bundle exec fastlane snapshot
  artifacts:
    paths:
      - fastlane/screenshots/
    expire_in: 1 week
  allow_failure: true

build_release:
  extends: .ios_base
  stage: build
  script:
    - bundle exec fastlane release
  artifacts:
    paths:
      - ./build/*.ipa
      - ./build/*.dSYM.zip
    expire_in: 30 days
  rules:
    - if: $CI_COMMIT_TAG
    - if: $CI_COMMIT_BRANCH == "main"

distribute_testflight:
  extends: .ios_base
  stage: distribute
  script:
    - bundle exec fastlane upload_to_testflight
  rules:
    - if: $CI_COMMIT_TAG
  dependencies:
    - build_release
  when: on_success
```

**Сценарий: Multi-project pipeline с общими артефактами:**
```yaml
# В основном проекте (config.gitlab-ci.yml)
build_ipa:
  extends: .ios_base
  stage: build
  script:
    - bundle exec fastlane release
  artifacts:
    paths:
      - ./build/*.ipa
    expire_in: 1 week

# В другом проекте, ссылающемся на артефакты
trigger_qa:
  stage: deploy
  trigger:
    project: mobile/qa-pipeline
    branch: main
    strategy: depend
  needs:
    - build_ipa
```

### 3. Управление секретами в GitLab

Для работы iOS CI/CD необходимо добавить следующие переменные в **Settings > CI/CD > Variables**:

| Переменная | Тип | Описание |
| :--- | :--- | :--- |
| `MATCH_PASSWORD` | Variable (Masked) | Пароль для расшифровки репозитория с сертификатами. |
| `ASC_API_KEY` | **File** | Содержимое файла `.p8` (App Store Connect API Key). |
| `KEYCHAIN_PASSWORD` | Variable | Пароль для создания временного Keychain на раннере. |
| `MATCH_GIT_URL` | Variable | URL приватного репозитория с сертификатами. |

---

## Тестирование в CI/CD

### Unit-тесты
```ruby
lane :test do
  run_tests(
    project: "MyApp.xcodeproj",
    scheme: "MyAppTests",
    devices: ["iPhone 15 Pro"],
    code_coverage: true,
    output_types: "junit",
    output_directory: "fastlane/test_output"
  )
end
```

### UI-тесты и скриншоты
```ruby
lane :snapshot do
  capture_screenshots(
    project: "MyApp.xcodeproj",
    scheme: "MyAppUITests",
    devices: ["iPhone 15 Pro", "iPhone 15 Pro Max"],
    languages: ["en-US", "ru-RU"],
    clear_previous_screenshots: true
  )
end
```

### Lint и анализ кода
```ruby
lane :lint do
  swiftlint(
    mode: :lint,
    raise_if_swiftlint_error: true,
    ignore_exit_status: false
  )
end
```

### Быстрые команды для проверки:
```bash
# Проверка сборки без подписи
xcodebuild -project MyApp.xcodeproj \
  -scheme MyApp \
  -destination 'platform=iOS Simulator,name=iPhone 15 Pro' \
  build

# Запуск тестов
xcodebuild test \
  -project MyApp.xcodeproj \
  -scheme MyAppTests \
  -destination 'platform=iOS Simulator,name=iPhone 15 Pro'

# Очистка DerivedData
rm -rf ~/Library/Developer/Xcode/DerivedData
```

---

## Оптимизация и кэширование

На macOS-раннерах кэширование через GitLab Runner (S3/GCS) может быть медленнее, чем использование локального кэша, из-за размера зависимостей.

**Рекомендуемые пути для кэширования:**
```yaml
cache:
  paths:
    - vendor/bundle
    - Pods/
    - .build/ # Swift Package Manager
```

**Важно:** Для Xcode DerivedData лучше использовать локальный механизм очистки (например, `fastlane clear_derived_data`) или выделенные папки для каждой ветки, чтобы избежать конфликтов при параллельных сборках.

### Продвинутое кэширование для macOS
```yaml
# Использование тегов для кэширования по версиям Xcode
cache:
  key:
    files:
      - Gemfile.lock
      - Podfile.lock
      - .xcode-version
  paths:
    - vendor/bundle
    - Pods/
    - DerivedData/
  policy: pull-push

# Раздельное кэширование для build и test
.unit_tests_cache:
  cache:
    key: test-$CI_COMMIT_REF_SLUG
    paths:
      - DerivedData/Build/Products/
    policy: pull

.build_cache:
  cache:
    key: build-$CI_COMMIT_REF_SLUG
    paths:
      - DerivedData/
    policy: pull
```

### Оптимизация времени сборки
```yaml
# Параллельная сборка модулей
build_ipa:
  script:
    - |
      xcodebuild build \
        -project MyApp.xcodeproj \
        -scheme MyApp \
        -destination 'generic/platform=iOS' \
        -parallelizeTargets \
        -maximumParallelizationTargets 4 \
        CODE_SIGN_IDENTITY="" \
        CODE_SIGNING_REQUIRED=NO
```

---

## Валидация и проверка

1.  **Проверка доступности Xcode:** В начале пайплайна добавьте `xcodebuild -version`, чтобы убедиться, что выбрана верная версия через `xcode-select`.
2.  **Health Check раннера:**
    ```bash
    gitlab-runner verify
    security find-identity -v -p codesigning # Проверка доступных сертификатов
    ```
3.  **Проверка Keychain:**
    ```bash
    # Просмотр всех keychains
    security list-keychains
    
    # Проверка доступа к конкретному keychain
    security unlock-keychain -p "$KEYCHAIN_PASSWORD" ci_build_keychain.keychain
    
    # Просмотр сертификатов в keychain
    security find-identity -v -p codesigning ci_build_keychain.keychain
    ```

**Автоматический скрипт проверки окружения:**
```bash
#!/bin/bash
# ci_env_check.sh

set -e

echo "=== Проверка окружения iOS CI/CD ==="

# Проверка Xcode
if xcodebuild -version &> /dev/null; then
  XCODE_VERSION=$(xcodebuild -version | head -1)
  echo "✓ Xcode: $XCODE_VERSION"
else
  echo "✗ Xcode не найден"
  exit 1
fi

# Проверка fastlane
if bundle exec fastlane --version &> /dev/null; then
  FASTLANE_VERSION=$(bundle exec fastlane --version | head -1)
  echo "✓ Fastlane: $FASTLANE_VERSION"
else
  echo "✗ Fastlane не найден"
  exit 1
fi

# Проверка сертификатов
CERTS=$(security find-identity -v -p codesigning | grep -c "iPhone")
if [ "$CERTS" -gt 0 ]; then
  echo "✓ Найдено $CERTS сертификат(ов) для подписи"
else
  echo "✗ Сертификаты для подписи не найдены"
  exit 1
fi

# Проверка DerivedData
if [ -d "$HOME/Library/Developer/Xcode/DerivedData" ]; then
  DERIVED_SIZE=$(du -sh "$HOME/Library/Developer/Xcode/DerivedData" | cut -f1)
  echo "✓ DerivedData: $DERIVED_SIZE"
else
  echo "✓ DerivedData не существует (чистое окружение)"
fi

echo "=== Все проверки пройдены ==="
```

---

## Устранение проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **"Could not find a valid identity"** | Сертификат не импортирован или Keychain заблокирован. | Проверьте использование `setup_ci_keychain` в Fastfile. |
| **"Operation not permitted"** | TCC (Transparency, Consent, and Control) в macOS блокирует доступ терминала к папкам. | Добавьте `gitlab-runner` в **Full Disk Access** в системных настройках Mac. |
| **Runner застрял в Pending** | Нет раннеров с соответствующими тегами. | Проверьте теги в `.gitlab-ci.yml` и в настройках зарегистрированного раннера. |
| **Slow Builds (IO bound)** | Использование HDD или медленного сетевого хранилища. | Используйте Mac на базе Apple Silicon с NVMe SSD. |
| **"No signing certificate "iOS Distribution" found"** | Сертификат не найден в Keychain. | Убедитесь, что сертификат импортирован в ephemeral keychain перед сборкой. |
| **"The executable was signed with invalid entitlements"** | Entitlements в проекте не соответствуют App ID. | Проверьте `TARGET` > `Signing & Capabilities` в Xcode и сверьте с Apple Developer Portal. |
| **"Provisioning profile doesn't match signing identity"** | Сертификат в профиле не совпадает с Keychain. | Выполните `security find-identity -p codesigning` и сверьте с Match. |
| **"xcodebuild: error: Unable to find a destination matching the provided destination specifier"** | Указанное устройство/симулятор не найдено. | Проверьте список доступных устройств: `xcrun simctl list devices`. |
| **"The file is corrupted or cannot be read"** | IPA поврежден при загрузке или архивирован неверно. | Проверьте целостность артефакта и повторите сборку с `clean: true`. |
| **"No space left on device"** | Недостаточно места на диске для сборки. | Очистите DerivedData: `rm -rf ~/Library/Developer/Xcode/DerivedData`. |
| **"Bundle identifier is not unique"** | Попытка загрузить приложение с занятым bundle identifier. | Проверьте уникальность bundle ID в App Store Connect и проекте. |
| **"fastlane: command not found"** | Fastlane не установлен или не добавлен в PATH. | Добавьте `bundle exec` перед fastlane или установите `gem install fastlane`. |
| **"Runner is not healthy"** | Раннер не отвечает на ping. | Перезапустите раннер: `gitlab-runner restart`. |
| **"Could not resolve host: gitlab.com"** | Проблемы с DNS или сетью. | Проверьте DNS и прокси-настройки на раннере. |
| **"Certificate has expired"** | Сертификат или Provisioning Profile истек. | Обновите сертификаты через Match: `fastlane match appstore --force_for_new_devices`. |

---

## Edge Cases и ограничения

1.  **Лимиты GitLab Runner:** Один раннер может обрабатывать только одно задание одновременно с Shell Executor. Используйте `concurrent` в `config.toml` для параллелизма.
2.  **Лимиты Xcode:** Apple устанавливает лимиты на количество сертификатов и Provisioning Profiles. Используйте Match для автоматического управления.
3.  **Кэширование DerivedData:** Не кэшируйте DerivedData между разными ветками — это может привести к конфликтам. Используйте уникальные ключи кэша.
4.  **Очистка Keychain:** Всегда удаляйте ephemeral keychain после сборки (`after_script`), даже при падении джобы.
5.  **Обновление Xcode:** При обновлении Xcode на раннере необходимо обновить все Provisioning Profiles через Match.
6.  **Параллельные тесты:** Убедитесь, что симуляторы не конфликтуют при параллельном запуске. Используйте `xcodebuild -parallel-testing`.
7.  **Лимиты артефактов:** GitLab ограничивает размер артефактов (по умолчанию 100 МБ). Настройте `expire_in` для старых сборок.
8.  **Сетевая задержка:** На удаленных раннерах может быть высокая задержка при загрузке зависимостей. Используйте локальные зеркала.

### Мониторинг и Observability

**Метрики для отслеживания:**
- **Build Success Rate:** Процент успешных сборок (целевое значение: > 95%).
- **Build Duration:** Среднее время сборки (целевое значение: < 10 минут для PR, < 20 минут для release).
- **Test Pass Rate:** Процент пройденных тестов.
- **Flaky Test Rate:** Процент "мигающих" тестов (целевое значение: < 2%).
- **Runner Utilization:** Процент использования раннеров (целевое значение: < 80%).

**Интеграция с метриками (Prometheus):**
```yaml
# В .gitlab-ci.yml
report_metrics:
  stage: .post
  script:
    - |
      # Отправка метрик в Prometheus pushgateway
      echo "gitlab_ci_build_duration_seconds{project=\"$CI_PROJECT_NAME\",branch=\"$CI_COMMIT_BRANCH\"} $CI_JOB_DURATION" | \
      curl -X POST --data-binary @- http://localhost:9091/metrics/job/gitlab_ci
  when: always
```

### См. также:

### Безопасность
*   **Protected Tags:** Используйте теги только для защищенных веток, если на раннере хранятся долгоживущие сессии или специфические лицензии.
*   **Automatic Cleanup:** Убедитесь, что скрипты очистки срабатывают даже при падении джобы (`after_script`).

### См. также:
*   **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)**
*   **[Автоматизация через Fastlane](./fastlane-guide.md)**
*   **[Регистрация GitLab Runner](../GitLab_CI/Tutorials/runner_registration.md)**
*   **[Обзор GitLab Runner и Executor](../GitLab_CI/Advanced/gitlab_ci_runners_executors.md)**
