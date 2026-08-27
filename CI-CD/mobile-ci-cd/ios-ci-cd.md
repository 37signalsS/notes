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

---

## Базовые концепции

### Иерархия сертификатов (2025–2026)

Apple окончательно перешла к унифицированной модели сертификатов, которая упрощает управление:
- **Apple Development:** Универсальный сертификат для разработки и отладки на устройствах (iOS, macOS, tvOS, watchOS, visionOS).
- **Apple Distribution:** Используется для всех видов распространения: TestFlight, App Store, Ad Hoc.
- **Developer ID Application:** Специфично для распространения macOS-приложений вне Mac App Store (Notarization).

### Fastlane Match: Certificates as Code

Ручное управление подписью в CI/CD приводит к «Certificate Hell» — ситуации, когда каждый новый разработчик или раннер генерирует свои ключи, достигая лимита Apple и ломая сборки коллегам. 

**Fastlane Match** решает это через подход SSoT (Single Source of Truth):
1.  **Централизованное хранилище:** Все сертификаты и профили шифруются и хранятся в одном месте (Git, S3, GCS).
2.  **Общий доступ:** Вся команда и CI используют один и тот же набор ключей.
3.  **Автоматизация:** Match сам создает App ID, обновляет профили при добавлении устройств и следит за сроками действия.

---

## Практическая реализация

### 0. Предварительные требования (Prerequisites)

- **macOS** (локально для инициализации или как CI-раннер).
- **Ruby >= 3.2** и установленный **fastlane** (`gem install fastlane`).
- **Apple Developer Program** аккаунт с ролью **Account Holder** или **Admin**.
- Приватный Git-репозиторий или S3/GCS бакет для хранения ключей.

### 1. Настройка App Store Connect API

Это обязательный шаг для CI в 2026 году.

1.  Перейдите в [App Store Connect > Users and Access > Integrations](https://appstoreconnect.apple.com/access/api).
2.  Создайте новый ключ с доступом **Admin** (необходим для управления сертификатами через Match).
3.  Скачайте файл `.p8`. **Внимание:** файл можно скачать только один раз.
4.  Сохраните `Issuer ID` и `Key ID`.

### 2. Подготовка инфраструктуры (Keychain в CI)

На эфемерных раннерах (GitHub Actions, GitLab Shared Runners) необходимо создавать временную связку ключей, чтобы Match мог безопасно импортировать туда закрытые ключи.

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
# Выберите метод хранения. Для Enterprise рекомендуется 's3' или 'google_cloud'
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

### 4. Выбор хранилища для Match

| Хранилище | Безопасность | Особенности 2026 |
| :--- | :--- | :--- |
| **Git (Private)** | Высокая | Требует `MATCH_PASSWORD` и SSH-ключ доступа к репо. Стандарт для малых команд. |
| **Amazon S3** | Максимальная | Поддержка OIDC. CI-раннер может получать доступ через IAM Role без статических секретов. |
| **Google Cloud (GCS)** | Максимальная | Лучший выбор при использовании GCP Workload Identity. |
| **Cloudflare R2** | Высокая | S3-совместимый вариант без платы за исходящий трафик (Egress). |

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

**UI-тесты (на реальных устройствах через Firebase Test Lab):**
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
  stapp(
    app_path: "./build/MacApp.app",
    staple: true
  )
end
```

### 8. Мониторинг и Observability в iOS CI/CD

**Метрики для отслеживания:**
- **Build Success Rate:** Процент успешных сборок (целевое значение: > 95%).
- **Build Duration:** Среднее время сборки (целевое значение: < 15 минут для PR, < 30 минут для release).
- **Test Pass Rate:** Процент пройденных тестов.
- **Flaky Test Rate:** Процент "мигающих" тестов (целевое значение: < 2%).
- **Time to First Install (TTFI):** Время от коммита до установки на устройство.

**Интеграция с мониторингом:**
```ruby
# Отправка метрик в Datadog/Prometheus
lane :report_metrics do |options|
  # Метрики сборки
  Datadog.measure("ci.build.duration", options[:duration], tags: ["project:ios", "lane:#{options[:lane]}"])
  Datadog.increment("ci.build.count", tags: ["project:ios", "status:#{options[:status]}"])
  
  # Метрики тестов
  Datadog.measure("ci.test.duration", options[:test_duration], tags: ["project:ios", "suite:#{options[:suite]}"])
  Datadog.increment("ci.test.count", tags: ["project:ios", "status:#{options[:test_status]}"])
end
```

---

## Валидация и проверка

Для автоматизированной проверки подписи в CI:
1.  **Верификация Keychain:** `security show-keychain-info ci_build_keychain.keychain` — убедиться, что связка создана и доступна.
2.  **Проверка сертификатов:** `security find-identity -p codesigning ci_build_keychain.keychain` — должен вывести список импортированных сертификатов.
3.  **Xcode Build Logs:** Ищите строку `Check dependencies`, там должен быть указан путь к профилю, скачанному Match.
4.  **Match Verify:** Используйте `fastlane match verify --type appstore`, чтобы убедиться, что локальные сертификаты соответствуют хранилищу.
5.  **Проверка подписи IPA:** `codesign -vvvv -d ./build/*.ipa` — должна возвращать `valid on disk` и `Identifier=com.company.app`.
6.  **Проверка Provisioning Profile:** `security cms -D -i ./build/*.mobileprovision` — выводит содержимое профиля в plist формате.

**Скрипт автоматической проверки:**
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

---

## Устранение проблем (Troubleshooting)

*   **Ошибка: "Missing private key in keychain":**
    *   Match успешно скачал профиль, но не нашел закрытого ключа в Keychain. 
    *   Решение: Проверьте, что `MATCH_PASSWORD` верен и Keychain был создан/разблокирован перед вызовом `match`.
*   **Ошибка: "Certificate Limit Reached":**
    *   Кто-то создал сертификаты вручную в Apple Portal.
    *   Решение: `fastlane match nuke distribution` (удалит все сертификаты и профили) и заново `fastlane match appstore`. **Осторожно:** это потребует пересборки всех активных версий у коллег.
*   **Ошибка: "User interaction is not allowed":**
    *   macOS пытается показать UI-диалог для доступа к Keychain. 
    *   Решение: Убедитесь, что используется `setup_ci` и `unlock_keychain` с флагом `--add-to-search-list`.
*   **Срок действия Apple WWDR:**
    *   Иногда Apple обновляет промежуточный сертификат (Worldwide Developer Relations). 
    *   Решение: Match обычно обновляет его автоматически, но в редких случаях его нужно скачать и импортировать в Keychain вручную через скрипт.
*   **Ошибка: "No signing certificate "iOS Distribution" found":**
    *   Профиль содержит сертификат, которого нет в Keychain.
    *   Решение: Убедитесь, что `match` запускается с `readonly: false` для обновления сертификатов, или выполните `fastlane match nuke` и пересоздайте.
*   **Ошибка: "The executable was signed with invalid entitlements":**
    *   Entitlements в проекте не соответствуют App ID в App Store Connect.
    *   Решение: Проверьте `TARGET` > `Signing & Capabilities` в Xcode и сверьте с App ID в Apple Developer Portal.
*   **Ошибка: "Provisioning profile doesn't match signing identity":**
    *   Сертификат в профиле не совпадает с установленным в Keychain.
    *   Решение: Выполните `security find-identity -p codesigning` и сверьте с `match` --force для пересоздания.
*   **Ошибка: "IPHONEOS_DEPLOYMENT_TARGET is higher than SDK":**
    *   Версия iOS в проекте выше, чем в установленном Xcode.
    *   Решение: Обновите Xcode или понизьте `IPHONEOS_DEPLOYMENT_TARGET` в настройках проекта.
*   **Ошибка: "Unable to install application" на реальном устройстве:**
    *   Устройство не добавлено в Provisioning Profile или_UDID не зарегистрирован.
    *   Решение: Добавьте устройство в Apple Developer Portal и выполните `fastlane match adhoc` для обновления профиля.
*   **Ошибка: "The file is corrupted or cannot be read":**
    *   IPA поврежден при загрузке или архивирован неверно.
    *   Решение: Проверьте целостность артефакта и повторите сборку с `clean: true`.

---

## Edge Cases и ограничения

1.  **Лимиты Apple:** Apple устанавливает лимиты на количество сертификатов (100 Development, 100 Distribution на команду). Match автоматически управляет этим, но при ручном добавлении сертификатов лимит может быть исчерпан.
2.  **Ротация ключей App Store Connect:** API Keys (.p8) не имеют срока действия, но могут быть отозваны. Рекомендуется ротация каждые 6-12 месяцев.
3.  **Смена Apple ID:** При смене Apple ID Account Holder необходимо обновить все API Keys и повторно настроить Match.
4.  **Обновление WWDR:** Apple периодически обновляет промежуточный сертификат (Worldwide Developer Relations). Match обычно обновляет его автоматически, но в редких случаях требуется ручное обновление.
5.  **Управление командой:** При добавлении нового разработчика необходимо добавить его UDID в Provisioning Profile (для Ad Hoc) или предоставить ему доступ к Match.
6.  **Мульти-таргетинг:** Если проект имеет несколько таргетов (extension, widget), каждый требует отдельного App ID и Provisioning Profile.
7.  **Конфликт версий Xcode:** Разные проекты могут требовать разные версии Xcode. Используйте `xcversion` или `xcode-select` для переключения.
8.  **Проблемы с Keychain на M-сериях:** На Apple Silicon Macs могут возникать проблемы с доступом к Keychain. Используйте `security set-key-partition-list` для разрешения доступа.

### Безопасность секрета MATCH_PASSWORD
Этот пароль используется для шифрования всех сертификатов в репозитории (AES-256). 
- Не используйте простые пароли.
- Ротируйте пароль ежегодно: `fastlane match change_password`.
- Храните его только в защищенных Vault-системах (Vault, AWS Secrets Manager).

### См. также:
*   **[GitLab CI/CD для iOS и macOS: Настройка](./gitlab-ios-ci.md)**
*   **[Обзор Mobile CI/CD и инфраструктуры](./index.md)**
*   **[Автоматизация через Fastlane](./fastlane-guide.md)**
*   **[Android CI/CD: Подпись и публикация](./android-ci-cd.md)**
