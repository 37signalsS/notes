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

### 3. Управление секретами в GitLab

Для работы iOS CI/CD необходимо добавить следующие переменные в **Settings > CI/CD > Variables**:

| Переменная | Тип | Описание |
| :--- | :--- | :--- |
| `MATCH_PASSWORD` | Variable (Masked) | Пароль для расшифровки репозитория с сертификатами. |
| `ASC_API_KEY` | **File** | Содержимое файла `.p8` (App Store Connect API Key). |
| `KEYCHAIN_PASSWORD` | Variable | Пароль для создания временного Keychain на раннере. |
| `MATCH_GIT_URL` | Variable | URL приватного репозитория с сертификатами. |

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

---

## Валидация и проверка

1.  **Проверка доступности Xcode:** В начале пайплайна добавьте `xcodebuild -version`, чтобы убедиться, что выбрана верная версия через `xcode-select`.
2.  **Health Check раннера:**
    ```bash
    gitlab-runner verify
    security find-identity -v -p codesigning # Проверка доступных сертификатов
    ```

---

## Устранение проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **"Could not find a valid identity"** | Сертификат не импортирован или Keychain заблокирован. | Проверьте использование `setup_ci_keychain` в Fastfile. |
| **"Operation not permitted"** | TCC (Transparency, Consent, and Control) в macOS блокирует доступ терминала к папкам. | Добавьте `gitlab-runner` в **Full Disk Access** в системных настройках Mac. |
| **Runner застрял в Pending** | Нет раннеров с соответствующими тегами. | Проверьте теги в `.gitlab-ci.yml` и в настройках зарегистрированного раннера. |
| **Slow Builds (IO bound)** | Использование HDD или медленного сетевого хранилища. | Используйте Mac на базе Apple Silicon с NVMe SSD. |

---

## Дополнительная информация

### Безопасность
*   **Protected Tags:** Используйте теги только для защищенных веток, если на раннере хранятся долгоживущие сессии или специфические лицензии.
*   **Automatic Cleanup:** Убедитесь, что скрипты очистки срабатывают даже при падении джобы (`after_script`).

### См. также:
*   **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)**
*   **[Автоматизация через Fastlane](./fastlane-guide.md)**
*   **[Регистрация GitLab Runner](../GitLab_CI/Tutorials/runner_registration.md)**
*   **[Обзор GitLab Runner и Executor](../GitLab_CI/Advanced/gitlab_ci_runners_executors.md)**
