# Android CI/CD: Подпись и публикация

## Определения

**Keystore (.jks / .keystore)** — бинарный файл-хранилище, содержащий закрытые ключи и сертификаты. В Android используется для цифровой подписи приложений, гарантируя, что обновления приходят от того же автора.

*   **Upload Key:** Ключ, которым разработчик (или CI) подписывает артефакт перед загрузкой в Google Play Console.
*   **App Signing Key:** Финальный ключ подписи, которым Google подписывает приложение перед раздачей пользователям. При использовании **Google Play App Signing** этот ключ хранится в защищенной инфраструктуре Google.
*   **Android App Bundle (AAB):** Современный формат публикации (обязателен с 2021 года). Позволяет Google Play генерировать оптимизированные APK под конкретную архитектуру и разрешение экрана устройства пользователя, уменьшая размер загрузки.

---

## Базовые концепции

### Google Play App Signing (SSoT для подписи)

Современный стандарт (2025-2026) — разделение ответственности за подпись.
1.  **CI/CD** использует **Upload Key**. Если он будет утерян, его можно сбросить через поддержку Google.
2.  **Google** использует **App Signing Key**. Его невозможно изменить или сбросить без удаления приложения, поэтому хранение его в Google повышает безопасность.

### Управление секретами

Главный риск — утечка Keystore или паролей. 
- **Keystore Injection:** Хранение файла в секретах CI в формате Base64.
- **Gradle Properties:** Передача паролей через аргументы командной строки или переменные окружения, исключая их попадание в `build.gradle` или логи.

---

## Практическая реализация

### 1. Инъекция Keystore и подпись через Gradle

**Шаг 1: Подготовка Base64**
```bash
# Кодирование ключа для вставки в Secret переменную
base64 -i my-upload-key.jks | pbcopy 
```

**Шаг 2: Конфигурация пайплайна (`.gitlab-ci.yml`)**
```yaml
build_android:
  stage: build
  variables:
    KEYSTORE_FILE: "app/upload-key.jks"
  script:
    # 1. Декодирование ключа из переменной окружения
    - echo "$ANDROID_KEYSTORE_BASE64" | base64 -d > $KEYSTORE_FILE
    # 2. Сборка с инъекцией параметров подписи
    - ./gradlew bundleRelease \
        -Pandroid.injected.signing.store.file=$(pwd)/$KEYSTORE_FILE \
        -Pandroid.injected.signing.store.password=$UPLOAD_KEYSTORE_PASSWORD \
        -Pandroid.injected.signing.key.alias=$UPLOAD_KEY_ALIAS \
        -Pandroid.injected.signing.key.password=$UPLOAD_KEY_PASSWORD
    # 3. Удаление ключа после сборки (безопасность)
    - rm $KEYSTORE_FILE
```

### 2. Автоматизация версионирования

Для предотвращения ошибок "Version code already exists", используйте автоматический инкремент.

**Вариант А: Через Gradle (`build.gradle.kts`)**
```kotlin
android {
    defaultConfig {
        // Берем номер сборки из CI (например, GitLab CI)
        versionCode = System.getenv("CI_PIPELINE_IID")?.toInt() ?: 1
        versionName = "1.0.${System.getenv("CI_PIPELINE_IID") ?: "0"}"
    }
}
```

**Вариант Б: Через Fastlane (плагин `versioning_android`)**
```ruby
lane :increment_version do
  increment_version_code(
    gradle_file_path: "./app/build.gradle",
    version_code: ENV["CI_PIPELINE_IID"].to_i
  )
end
```

### 3. Публикация через Fastlane Supply

**Supply** управляет не только бинарными файлами, но и метаданными (changelogs, описания).

**Настройка доступа:**
1.  Создайте Service Account в Google Cloud Console.
2.  Добавьте его в Google Play Console с правами "Release Manager".
3.  Сохраните JSON-ключ в CI как `GCP_SERVICE_ACCOUNT_JSON`.

**Fastfile:**
```ruby
lane :deploy_to_play_store do
  # Сборка
  gradle(task: "bundle", build_type: "Release")
  
  # Загрузка во внутреннее тестирование (Internal Test)
  supply(
    track: "internal",
    aab: "app/build/outputs/bundle/release/app-release.aab",
    json_key_data: ENV["GCP_SERVICE_ACCOUNT_JSON"],
    skip_upload_metadata: false, # Загрузить скриншоты и описания из fastlane/metadata
    skip_upload_changelogs: false
  )
end
```

---

## Валидация и проверка

Перед отправкой AAB в Google Play рекомендуется проверить его локально или на раннере:
1.  **Проверка структуры AAB:** `bundletool validate --bundle path/to/app.aab`.
2.  **Генерация APK из AAB (для тестов):**
    ```bash
    bundletool build-apks --bundle=app.aab --output=app.apks --mode=universal
    ```
3.  **Проверка подписи:** `apksigner verify --verbose path/to/generated_app.apk`.

---

## Устранение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Google API Error: 403 Forbidden** | Service Account не имеет прав в Play Console. | Проверьте права доступа и убедитесь, что API Google Play Android Developer включен в GCP проекте. |
| **VersionCode already used** | Попытка загрузить билд с тем же или меньшим номером версии. | Используйте `CI_PIPELINE_IID` или плагины версионирования для уникальности кода. |
| **Invalid Keystore Format** | Ошибка при декодировании Base64 или неверный формат (.jks vs .p12). | Убедитесь, что Base64 строка не содержит лишних символов и что Gradle ожидает правильный тип хранилища. |

---

## Дополнительная информация

### Play Asset Delivery (PAD)
Для игр и тяжелых приложений (> 200 МБ) используйте PAD. Пайплайн должен корректно упаковывать `asset-packs` в финальный AAB. Google Play автоматически распределит ресурсы по запросу приложения.

### См. также:
*   **[Обзор Mobile CI/CD и инфраструктуры](./index.md)**
*   **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)**
*   **[Автоматизация через Fastlane](./fastlane-guide.md)**
