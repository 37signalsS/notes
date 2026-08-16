# iOS CI/CD: Подпись кода и управление профилями

## Определения

**Code Signing (Подпись кода)** — криптографический процесс в экосистеме Apple, обеспечивающий целостность приложения и подтверждающий личность разработчика. Без корректной подписи iOS-устройство откажется запускать исполняемый файл.

*   **Сертификат (.cer / .p12):** Пара из открытого и закрытого ключей, выданная Apple. Закрытый ключ хранится в **Keychain** (Связке ключей) и является критически важным для процесса сборки.
*   **Provisioning Profile (.mobileprovision):** Конфигурационный файл («разрешение»), который объединяет:
    *   **App ID:** Уникальный идентификатор приложения.
    *   **Certificates:** Список сертификатов, которыми можно подписывать это приложение.
    *   **Entitlements:** Список разрешенных возможностей (Push Notifications, iCloud, Sign In with Apple).
    *   **Device IDs (UDID):** Список разрешенных устройств (только для Development и Ad Hoc профилей).

---

## Базовые концепции

### Иерархия сертификатов (2025-2026)

Apple перешла к унифицированной модели **Apple Distribution** и **Apple Development**, которые заменяют старые специфичные сертификаты для iOS/macOS.
- **Apple Development:** Используется для отладки на устройствах.
- **Apple Distribution:** Используется для отправки в TestFlight и App Store.
- **In-House (Enterprise):** Позволяет устанавливать приложения на любые устройства внутри организации без App Store.

### Fastlane Match: Single Source of Truth

Использование Xcode Auto-Signing в CI/CD ведет к «Certificate Hell» — бесконечной генерации новых ключей разными разработчиками и конфликтам на раннерах. **Fastlane Match** реализует подход **Certificates as Code**.

**Механизм работы:**
1.  **Хранилище:** Сертификаты и профили шифруются и загружаются в Git, S3 или Google Cloud Storage.
2.  **Общий доступ:** Вся команда использует один и тот же набор ключей, что исключает ошибки «Missing private key».
3.  **Автоматизация:** Match сам обновляет профили, если в App ID были добавлены новые Entitlements или устройства.

---

## Практическая реализация

### 1. Подготовка инфраструктуры (Keychain в CI)

Главная проблема iOS CI/CD — доступ к закрытым ключам. В интерактивной среде macOS Keychain разблокируется пользователем. В CI необходимо создавать **временную связку ключей**.

**Скрипт подготовки (Fastlane):**
```ruby
lane :setup_ci_keychain do
  create_keychain(
    name: "ci_build_keychain",
    password: ENV["KEYCHAIN_PASSWORD"],
    default_keychain: true,
    unlock: true,
    timeout: 3600,
    add_to_search_list: true
  )
end
```

### 2. Настройка Fastlane Match

**Шаг 1: Инициализация**
```bash
fastlane match init
# Выберите тип хранилища: git, google_cloud, s3
```

**Шаг 2: Генерация/Импорт**
```bash
# Создаст сертификаты и загрузит в хранилище
fastlane match appstore
fastlane match development
```

**Шаг 3: Использование в пайплайне**
```ruby
lane :release do
  setup_ci_keychain # Создаем временный Keychain
  
  # Аутентификация через API Key (рекомендуется)
  app_store_connect_api_key(
    key_id: "D383SF73OK",
    issuer_id: "60536ceb-2f39-4172-ba1e-92475661771d",
    key_content: ENV["ASC_API_KEY"] # Содержимое .p8 файла
  )
  
  # Синхронизация в режиме Read-Only
  match(type: "appstore", readonly: true, keychain_name: "ci_build_keychain")
  
  # Сборка
  build_app(scheme: "MyApp")
end
```

### 3. Выбор хранилища для Match

| Хранилище | Безопасность | Масштабируемость |
| :--- | :--- | :--- |
| **Private Git Repo** | Средняя (требуется `MATCH_PASSWORD`). | Высокая для небольших команд. |
| **AWS S3 / GCS** | Высокая (IAM роли, отсутствие долгоживущих токенов). | Идеально для крупных Enterprise проектов. |

---

## Валидация и проверка

Для проверки корректности подписи на раннере используйте:
1.  **Проверка сертификатов в Keychain:** `security find-identity -p codesigning ci_build_keychain.keychain`.
2.  **Проверка Provisioning Profile:** `grep -a "ExpirationDate" path/to/profile.mobileprovision` — убедитесь, что профиль не протух.
3.  **Xcode Build Settings:** Убедитесь, что в проекте для Release-конфигурации выбрано `Manual Signing` и указан соответствующий профиль, созданный Match.

---

## Устранение проблем (Troubleshooting)

*   **Ошибка: "Code Signing Error: No profile found":**
    *   Проверьте, совпадает ли Bundle ID в Xcode и в хранилище Match.
    *   Убедитесь, что Match запущен с правильным `type` (например, `adhoc` вместо `appstore`).
*   **Ошибка: "User interaction is not allowed":**
    *   Связка ключей (Keychain) не разблокирована или заблокировалась по таймауту.
    *   Используйте `unlock_keychain` перед сборкой.
*   **Лимит сертификатов (Certificate Limit Reached):**
    *   Кто-то из команды вручную создал сертификаты в Apple Portal.
    *   Решение: `fastlane match nuke distribution` (удалит ВСЕ сертификаты и профили в портале и хранилище) и повторный `fastlane match appstore`. **Внимание:** Это действие затронет всех разработчиков.

---

## Дополнительная информация

### App Store Connect API Key
С 2024 года использование Apple ID с 2FA в автоматизации официально не поддерживается (сессии живут недолго). Переход на **API Key** (.p8) является обязательным для стабильного CI.

### См. также:
*   **[Обзор Mobile CI/CD и инфраструктуры](./index.md)**
*   **[Автоматизация через Fastlane](./fastlane-guide.md)**
*   **[Android CI/CD: Подпись и публикация](./android-ci-cd.md)**
