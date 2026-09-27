# GitLab CI/CD для iOS и macOS: Настройка и масштабирование

## Определения

**GitLab iOS CI/CD** — реализация процессов сборки, тестирования и доставки iOS/macOS-приложений на инфраструктуре GitLab. Отличается необходимостью проприетарного оборудования (macOS), жестких правил подписи кода и управления эфемерными связками ключей.

**Shell Executor** — тип исполнителя GitLab Runner, предоставляющий прямой доступ к Xcode, симуляторам и системной связке ключей (Keychain). Рекомендуется для macOS-раннеров, поскольку Docker-Executor не поддерживает доступ к графическим инструментам Xcode и аппаратному ускорению симуляторов.

**Ephemeral Keychain** — временная связка ключей, создаваемая внутри джобы CI для безопасного хранения сертификатов. Автоматически удаляется после завершения сборки, исключая утечку секретов между джобами.

**GitLab Runner Token (`glrt-`)** — регистрационный токен, создаваемый в UI GitLab для привязки раннера к инстансу. Существует два типа: `glrt-` для проектных раннеров и групповых токенов.

**Golden Image** — предварительно настроенный шаблон macOS, содержащий Xcode, Fastlane, Ruby, симуляторы и политики безопасности. Гарантирует идемпотентность развертывания и исключает «дрейф» конфигурации.

**Error Budget (бюджет ошибок)** — допустимый процент проваленных сборок, связывающий надёжность пайплайна и скорость поставки. При исчерпании бюджета фокус смещается на стабилизацию, а не на новые фичи.

---

## Базовые концепции

### Архитектура macOS-раннеров в GitLab CI/CD

Для iOS-команд рекомендуется гибридная схема, сочетающая predictable latency и изоляцию:

| Тип раннера | Технические особенности | Сфера применения |
| :--- | :--- | :--- |
| **Dedicated Mac mini / Mac Studio** | Физические машины на Apple Silicon (M2/M3/M4), NVMe SSD, `launchd`-сервис для `gitlab-runner`. Предсказуемая производительность. | Release-сборки, UI-тесты на реальных устройствах, тяжелые задачи. |
| **Virtualized Pool (Tart/Orka)** | Эфемерные виртуальные машины на базе гипервизора Apple. Каждая джоба получает чистую среду. | Параллельные сборки, изоляция Keychain между джобами, тестирование на разных версиях Xcode. |
| **Shared Runners** | Общий пул раннеров, управляемых через GitLab UI. Подходит для мелких команд с нестабильной нагрузкой. | PR-валидация, lint, unit-тесты. Не рекомендуется для релизных сборок из-за риска утечки сертификатов. |

**Важно для Sysadmin:** macOS не имеет `systemd`; вместо него используется `launchd`. Раннер регистрируется как системный сервис с автозапуском и автоматическим восстановлением (`KeepAlive`). SIP (System Integrity Protection) ограничивает изменения защищённых разделов; для установки инструментов на dedicated-раннерах может потребоваться `csrutil disable` (не рекомендуется для shared-пулов).

### Принципы SRE для GitLab iOS CI/CD

- **Error Budget для пайплайна:** Договоритесь с командой о допустимом проценте проваленных сборок (например, 5% в месяц). При исчерпании бюджета фокус смещается на стабилизацию пайплайна.
- **MTTR (Mean Time To Repair):** Среднее время восстановления после инцидента. Целевое значение: < 30 минут для blocking-инцидентов (например, истечение сертификатов).
- **Toil Reduction:** Автоматизируйте обновление SDK, очистку DerivedData, ротацию симуляторов. Измеряйте долю toil в работе команды.
- **Flaky Test Management:** Ведите реестр «мигающих» тестов. Устанавливайте SLA на починку (например, 5 рабочих дней).
- **Runbook'и:** Для каждого типичного сбоя (падение Keychain, зависание симулятора, исчерпание лимитов Apple) должно быть пошаговое руководство.

### Управление секретами в GitLab

GitLab предоставляет два уровня хранения секретов:
- **Project Variables:** Доступны только в рамках проекта. Подходит для `MATCH_PASSWORD`, `KEYCHAIN_PASSWORD`.
- **Group/Instance Variables:** Наследуются дочерними проектами. Подходит для общих ключей (например, `ASC_API_KEY_ID` + `ASC_API_KEY_ISSUER_ID`).

Типы переменных:
- **Variable (Masked):** Обычные переменные, маскируются в логах.
- **File:** Переменная-файл, доступная как временный файл на раннере. Используется для `.p8` ключей и сертификатов `.p12`.

---

## Практические сценарии

### 1. Установка и регистрация раннера на macOS

#### Предварительные требования

- macOS 14+ (Sonoma) или macOS 15+ (Sequoia) на Apple Silicon.
- Xcode Command Line Tools: `xcode-select --install`.
- Homebrew: `/bin/bash -c "$(curl -fsSL https://brew.sh/install)"`.
- Ruby >= 3.2 (через `mise`, `asdf` или системный).
- Fastlane: `gem install fastlane` или `mise use ruby@3.3 && gem install fastlane`.

#### Регистрация Shell Executor

```bash
brew install gitlab-runner
brew services start gitlab-runner
```

```bash
gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "glrt-YOUR_MAC_TOKEN" \
  --executor "shell" \
  --tag-list "ios,macos,xcode-16" \
  --description "Mac Mini M2 - $(hostname)"
```

#### Конфигурация `config.toml`

```toml
concurrent = 4
check_interval = 3

[[runners]]
  name = "Mac Mini M2 - iOS"
  url = "https://gitlab.example.com/"
  token = "glrt-XXX"
  executor = "shell"
  shell = "zsh"
  environment = ["IOS_BUILD_ENV=true", "LC_ALL=en_US.UTF-8"]
  limit = 2
  [runners.cache]
    Type = "local"
    Shared = true
    Path = "/Users/runner/gitlab-runner/cache"
```

**Важно:** Используйте локальный кэш (`Type = "local"`). Удалённые хранилища добавляют сетевую задержку, что критично для macOS-раннеров из-за большого объёма зависимостей.

#### Множественные раннеры на одном Mac

```bash
gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "glrt-SECOND_TOKEN" \
  --executor "shell" \
  --tag-list "ios,macos,xcode-15" \
  --description "Mac Mini M1 - Legacy Support" \
  --working-directory "/Users/developer/builds" \
  --config "/etc/gitlab-runner/config-second.toml"
```

#### Управление раннерами через CLI

```bash
gitlab-runner list
gitlab-runner verify
gitlab-runner stop && gitlab-runner start
gitlab-runner unregister --name "Mac Mini M1 - Legacy Support"
```

### 2. Управление Keychain в CI/CD

**Создание ephemeral keychain:**

```bash
#!/bin/bash
# ci_create_keychain.sh

KEYCHAIN_NAME="ci_build_keychain"
KEYCHAIN_PASSWORD=$(openssl rand -base64 32)

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_NAME.keychain"
security set-keychain-settings -lut 21600 "$KEYCHAIN_NAME.keychain"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_NAME.keychain"
security list-keychains -d user -s "$KEYCHAIN_NAME.keychain" login.keychain

echo "Keychain создан: $KEYCHAIN_NAME.keychain"
```

**Импорт сертификатов:**

```bash
#!/bin/bash
# ci_import_certificates.sh

KEYCHAIN_NAME="ci_build_keychain"
CERTIFICATE_PATH="$1"
CERTIFICATE_PASSWORD="$2"

security import "$CERTIFICATE_PATH" \
  -k "$KEYCHAIN_NAME.keychain" \
  -P "$CERTIFICATE_PASSWORD" \
  -T /usr/bin/codesign \
  -T /usr/bin/security

security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "" "$KEYCHAIN_NAME.keychain"
```

**Очистка после сборки:**

```bash
#!/bin/bash
# ci_cleanup_keychain.sh

KEYCHAIN_NAME="ci_build_keychain"
security delete-keychain "$KEYCHAIN_NAME.keychain"
```

### 3. Конфигурация `.gitlab-ci.yml`

#### Базовый пайплайн

```yaml
variables:
  LC_ALL: "en_US.UTF-8"
  LANG: "en_US.UTF-8"

stages:
  - setup
  - test
  - build
  - deploy

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

#### Расширенный пайплайн с параллельными тестами и кэшированием

```yaml
variables:
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

#### Multi-project pipeline

```yaml
# config.gitlab-ci.yml
build_ipa:
  extends: .ios_base
  stage: build
  script:
    - bundle exec fastlane release
  artifacts:
    paths:
      - ./build/*.ipa
    expire_in: 1 week

# В другом проекте
trigger_qa:
  stage: deploy
  trigger:
    project: mobile/qa-pipeline
    branch: main
    strategy: depend
  needs:
    - build_ipa
```

### 4. Управление секретами

| Переменная | Тип | Описание |
| :--- | :--- | :--- |
| `MATCH_PASSWORD` | Variable (Masked) | Пароль для шифрования репозитория с сертификатами (AES-256). |
| `ASC_API_KEY` | **File** | Содержимое `.p8` (App Store Connect API Key). |
| `KEYCHAIN_PASSWORD` | Variable | Пароль для создания временного Keychain. |
| `MATCH_GIT_URL` | Variable | URL приватного Git-репозитория с сертификатами. |
| `ASC_API_KEY_ID` | Variable | `Key ID` из App Store Connect. |
| `ASC_API_KEY_ISSUER_ID` | Variable | `Issuer ID` из App Store Connect. |

---

## Операции и команды

### Жизненный цикл раннера

```bash
# Просмотр зарегистрированных раннеров
gitlab-runner list

# Проверка работоспособности
gitlab-runner verify

# Перезапуск сервиса
sudo launchctl unload /Library/LaunchDaemons/com.gitlab.runner.plist
sudo launchctl load /Library/LaunchDaemons/com.gitlab.runner.plist

# Очистка кэша
rm -rf /Users/runner/gitlab-runner/cache/*
```

### Проверка окружения

```bash
# Проверка Xcode
xcodebuild -version
xcode-select -p

# Проверка доступных симуляторов
xcrun simctl list devices available

# Проверка сертификатов в Keychain
security find-identity -v -p codesigning

# Проверка DerivedData
du -sh ~/Library/Developer/Xcode/DerivedData
```

### Управление Keychain

```bash
# Создание ephemeral keychain
security create-keychain -p "$PASSWORD" ci_build.keychain
security set-keychain-settings -lut 21600 ci_build.keychain
security unlock-keychain -p "$PASSWORD" ci_build.keychain
security list-keychains -d user -s ci_build.keychain login.keychain

# Импорт сертификата
security import cert.p12 -k ci_build.keychain -P "$CERT_PASS" \
  -T /usr/bin/codesign -T /usr/bin/security

# Настройка ACL
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "$PASSWORD" ci_build.keychain

# Удаление keychain
security delete-keychain ci_build.keychain
```

### Автоматический скрипт проверки окружения

```bash
#!/bin/bash
# ci_env_check.sh

set -e

echo "=== Проверка окружения iOS CI/CD ==="

if xcodebuild -version &> /dev/null; then
  echo "✓ Xcode: $(xcodebuild -version | head -1)"
else
  echo "✗ Xcode не найден"
  exit 1
fi

if bundle exec fastlane --version &> /dev/null; then
  echo "✓ Fastlane: $(bundle exec fastlane --version | head -1)"
else
  echo "✗ Fastlane не найден"
  exit 1
fi

CERTS=$(security find-identity -v -p codesigning | grep -c "iPhone")
if [ "$CERTS" -gt 0 ]; then
  echo "✓ Найдено $CERTS сертификат(ов) для подписи"
else
  echo "✗ Сертификаты для подписи не найдены"
  exit 1
fi

if [ -d "$HOME/Library/Developer/Xcode/DerivedData" ]; then
  echo "✓ DerivedData: $(du -sh ~/Library/Developer/Xcode/DerivedData | cut -f1)"
else
  echo "✓ DerivedData не существует (чистое окружение)"
fi

echo "=== Все проверки пройдены ==="
```

---

## Устранение проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **"Could not find a valid identity"** | Сертификат не импортирован или Keychain заблокирован. | Проверьте `setup_ci_keychain` в Fastfile. |
| **"Operation not permitted"** | TCC блокирует доступ терминала к папкам. | Добавьте `gitlab-runner` в **Full Disk Access**. |
| **Runner застрял в Pending** | Нет раннеров с соответствующими тегами. | Проверьте теги в `.gitlab-ci.yml` и регистрации. |
| **Slow Builds (IO bound)** | HDD или медленного сетевого хранилища. | Используйте Apple Silicon с NVMe SSD. |
| **"No signing certificate found"** | Сертификат не найден в Keychain. | Убедитесь, что сертификат импортирован в ephemeral keychain. |
| **"Invalid entitlements"** | Entitlements не соответствуют App ID. | Проверьте `Signing & Capabilities` в Xcode и Apple Developer Portal. |
| **"Provisioning profile doesn't match"** | Сертификат в профиле не совпадает с Keychain. | Выполните `security find-identity -p codesigning`. |
| **"Unable to find destination"** | Указанный симулятор/устройство не найден. | Проверьте: `xcrun simctl list devices`. |
| **"File is corrupted"** | IPA поврежден при архивации. | Повторите сборку с `clean: true`. |
| **"No space left on device"** | Недостаточно места на диске. | Очистите DerivedData: `rm -rf ~/Library/Developer/Xcode/DerivedData`. |
| **"Bundle identifier is not unique"** | Занят bundle ID в App Store Connect. | Проверьте уникальность bundle ID. |
| **"fastlane: command not found"** | Fastlane не установлен или не в PATH. | Используйте `bundle exec fastlane` или `gem install fastlane`. |
| **"Runner is not healthy"** | Раннер не отвечает на ping. | Перезапустите: `gitlab-runner restart`. |
| **"Could not resolve host"** | Проблемы с DNS или сетью. | Проверьте DNS и прокси на раннере. |
| **"Certificate has expired"** | Сертификат или Provisioning Profile истек. | Обновите через Match: `fastlane match appstore --force_for_new_devices`. |

---

## Рекомендации

### Best Practices

- **Error Budget:** Установите допустимый процент проваленных сборок (например, 5% в месяц). При исчерпании бюджета фокусируйтесь на стабилизации.
- **MTTR:** Целевое время восстановления — < 30 минут для blocking-инцидентов. Автоматизируйте процедуры восстановления.
- **Toil Reduction:** Автоматизируйте обновление SDK, очистку кэша, ротацию симуляторов. Измеряйте долю toil.
- **Golden Image:** Используйте шаблон окружения для быстрого развертывания новых раннеров. Храните образ в управляемом репозитории.
- **Ephemeral Keychain:** Всегда создавайте временный Keychain внутри джобы и удаляйте в `after_script`, даже при падении джобы.
- **Local Cache:** На macOS-раннерах используйте локальный кэш (`Type = "local"`). Удалённые хранилища замедляют сборки из-за объёма зависимостей.
- **DerivedData:** Не кэшируйте DerivedData между ветками. Используйте уникальные ключи кэша или `fastlane clear_derived_data`.
- **Backup Certificates:** Регулярно создавайте бэкап репозитория Match. Храните `MATCH_PASSWORD` в защищённых системах (HashiCorp Vault, GitLab CI Variables).

### Edge Cases и ограничения

1. **Один джоб на раннер:** Shell Executor обрабатывает одну задачу одновременно. Используйте `concurrent` в `config.toml` или несколько раннеров на одном Mac.
2. **Лимиты Apple:** Ограничение на количество сертификатов и Provisioning Profiles. Используйте Match для автоматического управления.
3. **SIP:** System Integrity Protection ограничивает изменения в системных разделах. Для некоторых инструментов может потребоваться отключение на dedicated-раннерах.
4. **Обновление Xcode:** При обновлении Xcode обновите все Provisioning Profiles через Match.
5. **Параллельные тесты:** Убедитесь, что симуляторы не конфликтуют. Используйте `xcodebuild -parallel-testing`.
6. **Лимиты артефактов:** GitLab ограничивает размер артефактов (по умолчанию 100 МБ). Настройте `expire_in`.
7. **Сетевая задержка:** На удалённых раннерах используйте локальные зеркала для зависимостей (CocoaPods, SPM).
8. **TCC/Full Disk Access:** `gitlab-runner` должен иметь доступ к папкам проекта и DerivedData. Добавьте в системные настройки.

### Мониторинг и Observability

**Метрики:**
- **Build Success Rate:** > 95%.
- **Build Duration:** < 10 минут для PR, < 20 минут для release.
- **Test Pass Rate:** процент пройденных тестов.
- **Flaky Test Rate:** < 2%.
- **Runner Utilization:** < 80%.

**Интеграция с Prometheus Pushgateway:**

```yaml
report_metrics:
  stage: .post
  script:
    - |
      echo "gitlab_ci_build_duration_seconds{project=\"$CI_PROJECT_NAME\",branch=\"$CI_COMMIT_BRANCH\"} $CI_JOB_DURATION" | \
      curl -X POST --data-binary @- http://localhost:9091/metrics/job/gitlab_ci
  when: always
```

### Безопасность

- **Protected Tags:** Используйте теги только для защищённых веток.
- **Automatic Cleanup:** Обеспечьте удаление Keychain и секретов в `after_script`, даже при падении джобы.
- **Token Rotation:** Ротируйте `glrt-` токены периодически. Удаляйте неиспользуемые раннеры.
- **Least Privilege:** Runner-аккаунт должен иметь минимальные права. Не запускайте `gitlab-runner` под `root`.

---

## Дополнительная информация

- **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)** — детали Provisioning Profiles, Fastlane Match и Keychain management.
- **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins, обработка ошибок, интеграция с GitLab CI.
- **[Обзор Mobile CI/CD и инфраструктуры](./index.md)** — архитектура macOS-раннеров, Tart/Orka, golden image.
