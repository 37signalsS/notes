# iOS CI/CD: Подпись кода и управление профилями

## Определения

**Code Signing (Подпись кода)** — криптографический механизм в экосистеме Apple, подтверждающий целостность исполняемого файла и идентичность автора. Для iOS-устройств подпись является обязательным условием запуска приложения (за исключением симуляторов).

*   **Сертификат (Certificate, .cer / .p12):** Цифровая подпись, выданная Apple (CA). Состоит из открытого ключа (хранится в профиле) и закрытого ключа (хранится в Keychain). В CI/CD отсутствие закрытого ключа в связке ключей раннера — самая частая причина сбоев (`Missing private key`).
*   **Provisioning Profile (.mobileprovision):** Связующее звено («разрешение»), которое Apple проверяет при запуске. Объединяет:
    *   **App ID:** Уникальный Bundle Identifier приложения.
    *   **Certificates:** Список сертификатов, имеющих право подписывать этот App ID.
    *   **Entitlements:** Список разрешенных API и возможностей (Push, iCloud, CarPlay).
    *   **Device IDs (UDID):** Список разрешенных устройств для тестирования (только для Development и Ad Hoc).
*   **App Store Connect API Key (.p8):** Современный метод аутентификации в сервисах Apple для автоматизации. В отличие от Apple ID, не требует 2FA и имеет неограниченный срок жизни сессии, что критично для стабильного CI.
*   **Ephemeral Keychain:** Временная связка ключей, создаваемая внутри джобы CI для безопасного хранения сертификатов и их автоматического удаления после завершения сборки. Является стандартом для изоляции подписи на shared runner'ах.
*   **Fastlane Match:** Инструмент для управления сертификатами и профилями как кодом (Certificates as Code), решающий проблему «Certificate Hell».

---

## Базовые концепции

### Иерархия сертификатов (2025–2026)

Apple окончательно перешла к унифицированной модели сертификатов, которая упрощает управление:
*   **Apple Development:** Универсальный сертификат для разработки и отладки на устройствах (iOS, macOS, tvOS, watchOS, visionOS).
*   **Apple Distribution:** Используется для всех видов распространения: TestFlight, App Store, Ad Hoc.
*   **Developer ID Application:** Специфично для распространения macOS-приложений вне Mac App Store (Notarization).

### Архитектура подписи в CI/CD

Процесс подписи iOS-приложения состоит из трех этапов:
1.  **Fetch Certificates:** Загрузка сертификатов и закрытых ключей из хранилища (Fastlane Match).
2.  **Import to Keychain:** Импорт в эфемерную или системную связку ключей раннера с корректными ACL для `codesign`.
3.  **Xcode Build & Sign:** `xcodebuild` или `xcbuild` автоматически находит профиль и сертификат в Keychain и подписывает бинарник.

### Self-hosted macOS-раннеры и подпись

В 2026 году стандартом для мобильного CI является полный переход на **Apple Silicon** (M-серия) и архитектуру **self-hosted** раннеров:
*   **Dedicated Runners:** Физические Mac mini / Mac Studio для тяжелых сборок и UI-тестов. Обеспечивают стабильность и минимальную задержку.
*   **Virtualization (Tart/Orka):** Эфемерные виртуальные машины для обеспечения чистоты окружения и параллелизма. Особенно важны для изоляции Keychain между джобами.
*   **Golden Image:** Базовый образ macOS с предустановленным Xcode, Fastlane, Ruby, зависимостями и настройками безопасности. Гарантирует идемпотентность развертывания нового раннера.

### Fastlane Match: Certificates as Code

Ручное управление подписью в CI/CD приводит к «Certificate Hell» — ситуации, когда каждый новый разработчик или раннер генерирует свои ключи, достигая лимита Apple и ломая сборки коллегам. 

**Fastlane Match** решает это через подход SSoT (Single Source of Truth):
1.  **Централизованное хранилище:** Все сертификаты и профили шифруются и хранятся в одном месте.
2.  **Общий доступ:** Вся команда и CI используют один и тот же набор ключей.
3.  **Автоматизация:** Match сам создает App ID, обновляет профили при добавлении устройств и следит за сроками действия.

---

## Практическая реализация

### 0. Предварительные требования (Prerequisites)

*   **macOS** (локально для инициализации или как CI-раннер).
*   **Ruby >= 3.2** и установленный **fastlane** (`gem install fastlane`).
*   **Apple Developer Program** аккаунт с ролью **Account Holder** или **Admin**.
*   Приватное хранилище для ключей: локальный Git-репозиторий, self-hosted S3-совместимое хранилище (MinIO), или сетевой ресурс.

### 1. Настройка App Store Connect API

Это обязательный шаг для CI в 2026 году.

1.  Перейдите в [App Store Connect > Users and Access > Integrations](https://appstoreconnect.apple.com/access/api).
2.  Создайте новый ключ с доступом **Admin** (необходим для управления сертификатами через Match).
3.  Скачайте файл `.p8`. **Внимание:** файл можно скачать только один раз.
4.  Сохраните `Issuer ID` и `Key ID`.

### 2. Инфраструктура: подготовка macOS-раннера

#### Golden Image provisioning

Для нового физического Mac mini / Mac Studio или Tart/Orka виртуальной машины выполните baseline-настройку:

```bash
# Установка Xcode Command Line Tools
xcode-select --install

# Установка менеджера версий Ruby (mise/asdf/rbenv)
brew install mise

# Установка Fastlane
mise use ruby@3.3
gem install fastlane

# Предварительная настройка git (если хранилище ключей в Git)
git config --global user.email "ci@company.com"
git config --global user.name "CI Runner"
```

#### Создание ephemeral keychain в CI

На эфемерных раннерах необходимо создавать временную связку ключей, чтобы Match мог безопасно импортировать туда закрытые ключи.

**Скрипт создания keychain:**
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
echo "KEYCHAIN_PASSWORD=$KEYCHAIN_PASSWORD" > keychain.env
```

**Пример в Fastfile:**
```ruby
lane :setup_ephemeral_keychain do
  setup_ci # Стандартный экшен для подготовки CI-окружения
  
  # Создание временного Keychain
  create_keychain(
    name: "ci_build_keychain",
    password: ENV["KEYCHAIN_PASSWORD"], # Любая сложная строка
    default_keychain: true,
    unlock: true,
    timeout: 3600,
    add_to_search_list: true
  )
end
```

### 3. Настройка и запуск Fastlane Match

**Инициализация:**
```bash
fastlane match init
# Выберите метод хранения. Для self-hosted инфраструктуры рекомендуется 'git' или 's3' (MinIO)
```

**Генерация сертификатов (выполняется один раз локально):**
```bash
# Импортирует или создаст новые сертификаты и профили
fastlane match development
fastlane match appstore
```

**Использование в пайплайне:**
```ruby
lane :build_release do
  setup_ephemeral_keychain
  
  # Загрузка API Key из секретов CI
  api_key = app_store_connect_api_key(
    key_id: ENV["ASC_KEY_ID"],
    issuer_id: ENV["ASC_ISSUER_ID"],
    key_content: ENV["ASC_KEY_CONTENT"], # Base64 от содержимого .p8
    is_key_content_base64: true
  )
  
  # Синхронизация (readonly гарантирует, что CI не изменит репозиторий ключей)
  match(
    type: "appstore",
    readonly: true,
    api_key: api_key,
    keychain_name: "ci_build_keychain",
    keychain_password: ENV["KEYCHAIN_PASSWORD"]
  )
  
  # Сборка с использованием подтянутых профилей
  build_app(
    scheme: "Production",
    export_method: "app-store",
    workspace: "MyApp.xcworkspace"
  )
end
```

### 4. Выбор хранилища для Match (self-hosted)

| Хранилище | Безопасность | Особенности 2026 |
| :--- | :--- | :--- |
| **Git (Private)** | Высокая | Требует `MATCH_PASSWORD` и SSH-ключ доступа к репо. Стандарт для малых команд. |
| **MinIO / S3-совместимое** | Максимальная | Self-hosted вариант. Поддержка IAM-подобных политик через MinIO. |
| **Сетевой ресурс (NFS/SMB)** | Средняя | Локальное хранилище в корпоративной сети. Простота настройки, но требует контроля доступа. |
| **Зашифрованный DMG** | Высокая | Файл-образ с шифрованием AES-256. Подходит для air-gapped окружений. |

### 5. Дистрибуция приложений

**TestFlight (Internal & External Testing):**
```ruby
lane :distribute_testflight do
  setup_ephemeral_keychain
  
  api_key = app_store_connect_api_key(
    key_id: ENV["ASC_KEY_ID"],
    issuer_id: ENV["ASC_ISSUER_ID"],
    key_content: ENV["ASC_KEY_CONTENT"],
    is_key_content_base64: true
  )
  
  match(
    type: "appstore",
    readonly: true,
    api_key: api_key,
    keychain_name: "ci_build_keychain",
    keychain_password: ENV["KEYCHAIN_PASSWORD"]
  )
  
  build_app(
    scheme: "Production",
    export_method: "app-store",
    workspace: "MyApp.xcworkspace"
  )
  
  upload_to_testflight(
    api_key: api_key,
    skip_waiting_for_build_processing: true,
    distribute_external: true,
    notify_external_testers: true,
    changelog: ENV["CHANGELOG"] || "Bug fixes and improvements"
  )
end
```

**App Store (Production Release):**
```ruby
lane :release_appstore do
  setup_ephemeral_keychain
  
  api_key = app_store_connect_api_key(
    key_id: ENV["ASC_KEY_ID"],
    issuer_id: ENV["ASC_ISSUER_ID"],
    key_content: ENV["ASC_KEY_CONTENT"],
    is_key_content_base64: true
  )
  
  match(
    type: "appstore",
    readonly: true,
    api_key: api_key,
    keychain_name: "ci_build_keychain",
    keychain_password: ENV["KEYCHAIN_PASSWORD"]
  )
  
  build_app(
    scheme: "Production",
    export_method: "app-store",
    workspace: "MyApp.xcworkspace"
  )
  
  upload_to_app_store(
    api_key: api_key,
    force: true,
    skip_screenshots: true,
    skip_metadata: false,
    precheck_include_in_app_purchases: false,
    submission_information: {
      add_id_info_limits_tracking: true,
      add_id_info_serves_ads: false,
      add_id_info_tracks_action: true,
      add_id_info_tracks_install: true,
      add_id_info_tracks_wifi: true,
      content_rating: "4+",
      copyright_year: Time.now.year.to_s
    }
  )
end
```

**Ad Hoc (Для тестирования на реальных устройствах):**
```ruby
lane :build_adhoc do
  setup_ephemeral_keychain
  
  api_key = app_store_connect_api_key(
    key_id: ENV["ASC_KEY_ID"],
    issuer_id: ENV["ASC_ISSUER_ID"],
    key_content: ENV["ASC_KEY_CONTENT"],
    is_key_content_base64: true
  )
  
  match(
    type: "adhoc",
    readonly: true,
    api_key: api_key,
    keychain_name: "ci_build_keychain",
    keychain_password: ENV["KEYCHAIN_PASSWORD"]
  )
  
  build_app(
    scheme: "Staging",
    export_method: "ad-hoc",
    workspace: "MyApp.xcworkspace"
  )
  
  # Дистрибуция через Firebase App Distribution или Crashlytics
  firebase_app_distribution(
    app: ENV["FIREBASE_APP_ID"],
    groups: "qa-team, developers",
    release_notes: "Build #{ENV['CI_BUILD_NUMBER']} - Ad Hoc testing"
  )
end
```

### 6. Тестирование в CI/CD

**Unit-тесты:**
```ruby
lane :run_unit_tests do
  run_tests(
    scheme: "UnitTests",
    devices: ["iPhone 16", "iPhone 15 Pro"],
    clean: true,
    code_coverage: true,
    output_types: "html,junit",
    output_directory: "./test_output"
  )
end
```

**UI-тесты (на реальных устройствах):**
```ruby
lane :run_ui_tests do
  run_tests(
    scheme: "UITests",
    devices: ["iPhone 16"],
    testplan: "UITests",
    clean: true,
    output_types: "html,junit",
    output_directory: "./test_output"
  )
end
```

**Snapshot-тесты (для скриншотов App Store):**
```ruby
lane :capture_screenshots do
  capture_screenshots(
    scheme: "Production",
    devices: ["iPhone 16 Pro Max", "iPad Pro 12.9-inch (6th generation)"],
    languages: ["en-US", "ru-RU"],
    output_directory: "./fastlane/screenshots"
  )
  
  # Загрузка скриншотов в App Store Connect
  upload_screenshots(
    api_key: api_key,
    skip_screenshots: false
  )
end
```

### 7. Notarization (для macOS-приложений)

Для распространения macOS-приложений вне Mac App Store требуется нотаризация:

```ruby
lane :notarize_macos do
  # Сборка
  build_app(
    scheme: "MacApp",
    export_method: "developer-id",
    workspace: "MyApp.xcworkspace"
  )
  
  # Нотаризация
  notarize(
    app_path: "./build/MacApp.app",
    apple_id: ENV["APPLE_ID"],
    team_id: ENV["TEAM_ID"],
    password: ENV["APP_SPECIFIC_PASSWORD"],
    skip_waiting_for_notarization: false
  )
  
  # Стэппинг (после успешной нотаризации)
  staple(
    app_path: "./build/MacApp.app",
    staple: true
  )
end
```

---

## Операции и команды

### Проверка окружения и диагностика подписи

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `security show-keychain-info ci_build_keychain.keychain` | Проверка, что временная связка создана и доступна. | Вывод информации о keychain без ошибок. |
| `security find-identity -p codesigning ci_build_keychain.keychain` | Список сертификатов, имеющих право подписи. | Строки вида `1) XXXXXXXX "Apple Distribution: ..."`. |
| `security find-identity -v -p codesigning` | Проверка доступных сертификатов во всех keychain. | Должен отображаться импортированный сертификат. |
| `fastlane match verify --type appstore` | Верификация, что локальные сертификаты соответствуют хранилищу. | `Valid certificate found` или ошибка несоответствия. |
| `codesign -vvvv -d ./build/*.ipa` | Проверка подписи IPA. | `valid on disk` и `Identifier=com.company.app`. |
| `security cms -D -i ./build/*.mobileprovision` | Декодирование содержимого профиля в plist. | Вывод XML с App ID, expiration date, entitlements. |
| `xcodebuild -version` | Проверка установленной версии Xcode. | `Xcode X.Y.Z` и версия компилятора. |
| `xcrun simctl list devices` | Список доступных симуляторов. | Перечень устройств с статусом `Booted`/`Shutdown`. |

### Скрипт автоматической проверки подписи

```bash
#!/bin/bash
# ios_signing_verify.sh

set -e

KEYCHAIN="ci_build_keychain.keychain"
IPA_PATH="./build/*.ipa"

echo "=== Проверка Keychain ==="
if security show-keychain-info "$KEYCHAIN" 2>&1 | grep -q "keychain"; then
  echo "✓ Keychain создан"
else
  echo "✗ Keychain не найден"
  exit 1
fi

echo "=== Проверка сертификатов ==="
CERTS=$(security find-identity -p codesigning "$KEYCHAIN" | grep -c "iPhone")
if [ "$CERTS" -gt 0 ]; then
  echo "✓ Найдено $CERTS сертификат(ов)"
else
  echo "✗ Сертификаты не найдены"
  exit 1
fi

echo "=== Проверка подписи IPA ==="
if codesign -vvvv "$IPA_PATH" 2>&1 | grep -q "valid on disk"; then
  echo "✓ Подпись валидна"
else
  echo "✗ Подпись невалидна"
  exit 1
fi

echo "=== Все проверки пройдены ==="
```

### Очистка окружения

```bash
# Удаление временного keychain после сборки
security delete-keychain "ci_build_keychain.keychain"

# Очистка DerivedData
rm -rf ~/Library/Developer/Xcode/DerivedData

# Очистка кэша симуляторов
xcrun simctl shutdown all
xcrun simctl erase all
```

---

## Устранение проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **"Missing private key in keychain"** | Match скачал профиль, но не нашел закрытого ключа в Keychain. | Проверьте, что `MATCH_PASSWORD` верен и Keychain был создан/разблокирован перед вызовом `match`. |
| **"Certificate Limit Reached"** | Лимит сертификатов Apple исчерпан ручным добавлением. | `fastlane match nuke distribution` и заново `fastlane match appstore`. **Осторожно:** потребует пересборки. |
| **"User interaction is not allowed"** | macOS пытается показать UI-диалог для доступа к Keychain. | Убедитесь, что используется `setup_ci` и `unlock_keychain` с флагом `--add-to-search-list`. |
| **Срок действия Apple WWDR** | Apple обновил промежуточный сертификат. | Match обычно обновляет его автоматически; в редких случаях импортируйте вручную. |
| **"No signing certificate "iOS Distribution" found"** | Профиль содержит сертификат, которого нет в Keychain. | Запустите `match` с `readonly: false` для обновления, или `fastlane match nuke`. |
| **"The executable was signed with invalid entitlements"** | Entitlements не соответствуют App ID. | Проверьте `Signing & Capabilities` в Xcode и App ID в Apple Developer Portal. |
| **"Provisioning profile doesn't match signing identity"** | Сертификат в профиле не совпадает с установленным в Keychain. | `security find-identity -p codesigning` и `match --force`. |
| **"IPHONEOS_DEPLOYMENT_TARGET is higher than SDK"** | Версия iOS в проекте выше, чем в Xcode. | Обновите Xcode или понизьте `IPHONEOS_DEPLOYMENT_TARGET`. |
| **"Unable to install application" на реальном устройстве** | Устройство не добавлено в Provisioning Profile. | Добавьте UDID в Apple Developer Portal и `fastlane match adhoc`. |
| **"The file is corrupted or cannot be read"** | IPA поврежден при архивации. | Проверьте целостность артефакта и повторите сборку с `clean: true`. |
| **"Operation not permitted"** | TCC в macOS блокирует доступ терминала. | Добавьте `gitlab-runner`/терминал в **Full Disk Access**. |
| **Runner застрял в Pending** | Нет раннеров с нужными тегами. | Проверьте теги в CI-конфигурации и настройках раннера. |
| **"No space left on device"** | Недостаточно места на диске. | Очистите DerivedData и артефакты. |

---

## Best Practices

### Гигиена сертификатов и управление лимитами

Apple устанавливает лимиты на количество сертификатов (100 Development, 100 Distribution на команду). Match автоматически управляет этим, но при ручном добавлении лимит может быть исчерпан. Используйте `readonly: true` в CI, чтобы исключить случайное создание новых сертификатов.

### Ротация секретов и MATCH_PASSWORD

Этот пароль используется для шифрования всех сертификатов в репозитории (AES-256):
*   Не используйте простые пароли.
*   Ротируйте пароль ежегодно: `fastlane match change_password`.
*   Храните его в защищенных системах (HashiCorp Vault, GitLab CI Variables, macOS Keychain сервиса).

### SRE: наблюдаемость и метрики

**Ключевые SLI для iOS signing:**

| SLI | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Signing Success Rate** | Процент успешных сборок без signing-ошибок | > 98% |
| **Certificate Rotation Time** | Время обновления сертификатов при приближении срока | < 1 часа до истечения |
| **PR Validation Time** | Время проверки PR | < 10 минут |
| **Flaky Test Rate** | Процент "мигающих" тестов | < 2% |
| **Time to First Install (TTFI)** | Время от merge до TestFlight | < 2 часа |
| **MTTR (Signing Incident)** | Среднее время восстановления после сбоя подписи | < 30 минут |

**Error Budget для signing:** Договоритесь с командой о допустимом проценте проваленных сборок из-за signing-проблем (например, 2% в месяц). При исчерпании бюджета фокус смещается на стабилизацию, а не на новые фичи.

**Toil Reduction:** Автоматизируйте ротацию сертификатов, очистку Keychain и DerivedData. Измеряйте долю ручной работы по администрированию signing в команде.

**Мониторинг инфраструктуры:**
*   **Prometheus + Grafana:** Сбор метрик с раннеров (CPU, RAM, disk, network) через `node_exporter`.
*   **CI-специфичные метрики:** Длительность сборок, доля успешных джоб, время в очереди.
*   **Алерты:** Настройте оповещения при падении успешности сборок ниже порога или превышении времени сборки.

**Runbook'и:** Для каждого типичного сбоя (Certificate Limit Reached, падение Keychain, зависание симулятора) должно быть пошаговое руководство по восстановлению.

### Идемпотентность и безопасность

*   Используйте `readonly: true` для `match` во всех CI-джобах. Запись в репозиторий ключей должна выполняться только с защищенных контуров.
*   Никогда не коммитьте `.p12`, `.p8` или `MATCH_PASSWORD` в репозиторий.
*   Очищайте ephemeral keychain после каждой сборки в `after_script`/`ensure`-блоке.
*   Используйте `security set-key-partition-list` для корректной работы `codesign` без UI-подтверждения на Apple Silicon.

---

## Edge Cases и ограничения

1.  **Лимиты Apple:** Apple устанавливает лимиты на количество сертификатов (100 Development, 100 Distribution на команду). Match автоматически управляет этим, но при ручном добавлении сертификатов лимит может быть исчерпан.
2.  **Ротация ключей App Store Connect:** API Keys (.p8) не имеют срока действия, но могут быть отозваны. Рекомендуется ротация каждые 6–12 месяцев.
3.  **Смена Apple ID:** При смене Apple ID Account Holder необходимо обновить все API Keys и повторно настроить Match.
4.  **Обновление WWDR:** Apple периодически обновляет промежуточный сертификат (Worldwide Developer Relations). Match обычно обновляет его автоматически, но в редких случаях требуется ручное обновление.
5.  **Управление командой:** При добавлении нового разработчика необходимо добавить его UDID в Provisioning Profile (для Ad Hoc) или предоставить доступ к Match.
6.  **Мульти-таргетинг:** Если проект имеет несколько таргетов (extension, widget), каждый требует отдельного App ID и Provisioning Profile.
7.  **Конфликт версий Xcode:** Разные проекты могут требовать разные версии Xcode. Используйте `xcversion` или `xcode-select` для переключения.
8.  **Проблемы с Keychain на M-сериях:** На Apple Silicon Macs могут возникать проблемы с доступом к Keychain. Используйте `security set-key-partition-list` для разрешения доступа.

---

## См. также

*   **[GitLab CI/CD для iOS и macOS: Настройка](./gitlab-ios-ci.md)** — регистрация раннеров, shell executor, ephemeral keychain скрипты.
*   **[Обзор Mobile CI/CD и инфраструктуры](./index.md)** — архитектура macOS-раннеров, Tart/Orka, golden image.
*   **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins, обработка ошибок, интеграция с Match.
