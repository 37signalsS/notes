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

---

## Валидация и проверка

Для автоматизированной проверки подписи в CI:
1.  **Верификация Keychain:** `security show-keychain-info ci_build_keychain.keychain` — убедиться, что связка создана и доступна.
2.  **Проверка сертификатов:** `security find-identity -p codesigning ci_build_keychain.keychain` — должен вывести список импортированных сертификатов.
3.  **Xcode Build Logs:** Ищите строку `Check dependencies`, там должен быть указан путь к профилю, скачанному Match.
4.  **Match Verify:** Используйте `fastlane match verify --type appstore`, чтобы убедиться, что локальные сертификаты соответствуют хранилищу.

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

---

## Дополнительная информация

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
