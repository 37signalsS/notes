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

### 1. Создание и резервное копирование Keystore

**Создание нового Keystore:**
```bash
# Генерация keystore с ключом
keytool -genkeypair \
  -v \
  -keystore my-upload-key.jks \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -alias my-upload-key \
  -storepass YOUR_STORE_PASSWORD \
  -keypass YOUR_KEY_PASSWORD \
  -dname "CN=Your Name, OU=Your Company, O=Your Company, L=Your City, ST=Your State, C=US"
```

**Резервное копирование Keystore:**
```bash
# Копирование keystore в безопасное место
cp my-upload-key.jks /secure/backup/my-upload-key-$(date +%Y%m%d).jks

# Экспорт сертификата (не закрытого ключа) для shared验证
keytool -export -alias my-upload-key \
  -file my-upload-key.cer \
  -keystore my-upload-key.jks \
  -storepass YOUR_STORE_PASSWORD
```

**Верификация Keystore:**
```bash
# Просмотр информации о keystore
keytool -list -v -keystore my-upload-key.jks -storepass YOUR_STORE_PASSWORD

# Проверка конкретного ключа
keytool -list -v -alias my-upload-key -keystore my-upload-key.jks -storepass YOUR_STORE_PASSWORD
```

### 2. Инъекция Keystore и подпись через Gradle

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

**Конфигурация GitHub Actions:**
```yaml
name: Android Build & Publish

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up JDK 17
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
      
      - name: Setup Gradle
        uses: gradle/actions/setup-gradle@v3
      
      - name: Decode keystore
        env:
          ANDROID_KEYSTORE_BASE64: ${{ secrets.ANDROID_KEYSTORE_BASE64 }}
        run: echo "$ANDROID_KEYSTORE_BASE64" | base64 -d > app/upload-key.jks
      
      - name: Build with Gradle
        env:
          UPLOAD_KEYSTORE_PASSWORD: ${{ secrets.UPLOAD_KEYSTORE_PASSWORD }}
          UPLOAD_KEY_ALIAS: ${{ secrets.UPLOAD_KEY_ALIAS }}
          UPLOAD_KEY_PASSWORD: ${{ secrets.UPLOAD_KEY_PASSWORD }}
        run: |
          ./gradlew bundleRelease \
            -Pandroid.injected.signing.store.file=$(pwd)/app/upload-key.jks \
            -Pandroid.injected.signing.store.password=$UPLOAD_KEYSTORE_PASSWORD \
            -Pandroid.injected.signing.key.alias=$UPLOAD_KEY_ALIAS \
            -Pandroid.injected.signing.key.password=$UPLOAD_KEY_PASSWORD
      
      - name: Cleanup keystore
        if: always()
        run: rm -f app/upload-key.jks
      
      - name: Upload AAB
        uses: actions/upload-artifact@v4
        with:
          name: app-release.aab
          path: app/build/outputs/bundle/release/app-release.aab
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
    skip_upload_metadata: false,
    skip_upload_changelogs: false
  )
end
```

### 4. Тестирование в CI/CD

**Unit-тесты:**
```ruby
lane :run_unit_tests do
  gradle(task: "test", build_type: "Debug")
  
  # Публикация отчётов
  gradle(task: "jacocoTestReport", build_type: "Debug")
end
```

**Instrumented-тесты (на эмуляторе/устройстве):**
```ruby
lane :run_instrumented_tests do
  gradle(
    task: "connectedAndroidTest",
    build_type: "Debug"
  )
end
```

**Скриншот-тесты (для Google Play):**
```ruby
lane :capture_screenshots do
  gradle(
    task: "executeScreenshotTests",
    build_type: "Debug"
  )
  
  # Загрузка скриншотов в Google Play Console
  supply(
    track: "internal",
    screenshots_path: "./fastlane/metadata/android/en-US/images",
    json_key_data: ENV["GCP_SERVICE_ACCOUNT_JSON"],
    skip_upload_binary: true,
    skip_upload_changelogs: true
  )
end
```

**Gradle-команды для тестирования:**
```bash
# Все unit-тесты
./gradlew test

# Тесты с покрытием (JaCoCo)
./gradlew test jacocoTestReport

# Instrumented-тесты (требуется эмулятор или устройство)
./gradlew connectedAndroidTest

# Lint-проверка
./gradlew lint

# Проверка безопасности (dependency scanning)
./gradlew dependencyCheckAnalyze
```

### 5. Мониторинг и Observability в Android CI/CD

**Метрики для отслеживания:**
- **Build Success Rate:** Процент успешных сборок (целевое значение: > 95%).
- **Build Duration:** Среднее время сборки (целевое значение: < 10 минут для PR, < 20 минут для release).
- **Test Pass Rate:** Процент пройденных тестов.
- **Flaky Test Rate:** Процент "мигающих" тестов (целевое значение: < 2%).
- **APK/AAB Size:** Размер артефактов (целевое значение: < 150 МБ для AAB).
- **Lint Errors:** Количество ошибок Lint (целевое значение: 0 errors).

**Интеграция с метриками (Prometheus/InfluxDB):**
```ruby
# Отправка метрик в CI/CD pipeline
lane :report_metrics do |options|
  # Метрики сборки
  metrics = {
    "build_duration" => options[:duration],
    "build_status" => options[:status],
    "project" => "android",
    "lane" => options[:lane]
  }
  
  # Запись в InfluxDB или Prometheus pushgateway
  system("echo 'android_build,project=android,#{options[:lane]} duration=#{options[:duration]},status=#{options[:status]}' | curl -X POST --data-binary @- http://localhost:8086/write?db=ci_metrics")
end
```

**Мониторинг размера APK/AAB:**
```bash
# Проверка размера артефакта
AAB_SIZE=$(stat -f%z app/build/outputs/bundle/release/app-release.aab)
MAX_SIZE=$((150 * 1024 * 1024))  # 150 МБ

if [ "$AAB_SIZE" -gt "$MAX_SIZE" ]; then
  echo "ERROR: AAB size ($AAB_SIZE bytes) exceeds limit ($MAX_SIZE bytes)"
  exit 1
fi
```

### 6. Rollback и восстановление

**Rollback через Google Play Console:**
- Используйте `supply` с `track: "internal"` для быстрой откаты на предыдущую версию.
- Автоматический rollback при падении crash-free rate ниже порога.

**Скрипт отката:**
```bash
#!/bin/bash
# android_rollback.sh

set -e

PREVIOUS_VERSION=$1
TRACK=$2

if [ -z "$PREVIOUS_VERSION" ] || [ -z "$TRACK" ]; then
  echo "Usage: $0 <previous_version> <track>"
  echo "Example: $0 1.0.123 internal"
  exit 1
fi

echo "Rolling back to version $PREVIOUS_VERSION on track $TRACK..."

fastlane supply \
  --track "$TRACK" \
  --version_code "$PREVIOUS_VERSION" \
  --json_key "$GCP_SERVICE_ACCOUNT_JSON" \
  --skip_upload_metadata \
  --skip_upload_changelogs
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
4.  **Проверка размера AAB:**
    ```bash
    AAB_SIZE=$(stat -f%z app.aab)
    echo "AAB size: $(($AAB_SIZE / 1024 / 1024)) MB"
    ```
5.  **Проверка versionCode:**
    ```bash
    VERSION_CODE=$(aapt dump badging app.aab 2>/dev/null | grep "versionCode" | cut -d"'" -f2)
    echo "Version Code: $VERSION_CODE"
    ```

**Автоматический скрипт проверки:**
```bash
#!/bin/bash
# android_build_verify.sh

set -e

AAB_PATH="./app/build/outputs/bundle/release/app-release.aab"

echo "=== Проверка AAB ==="

# Проверка существования файла
if [ ! -f "$AAB_PATH" ]; then
  echo "✗ AAB файл не найден: $AAB_PATH"
  exit 1
fi

# Проверка размера
AAB_SIZE=$(stat -f%z "$AAB_PATH")
MAX_SIZE=$((150 * 1024 * 1024))
if [ "$AAB_SIZE" -gt "$MAX_SIZE" ]; then
  echo "✗ Размер AAB ($(($AAB_SIZE / 1024 / 1024)) MB) превышает лимит (150 MB)"
  exit 1
fi

# Валидация структуры
if bundletool validate --bundle "$AAB_PATH" 2>&1 | grep -q "valid"; then
  echo "✓ Структура AAB валидна"
else
  echo "✗ Ошибка валидации AAB"
  exit 1
fi

echo "=== Все проверки пройдены ==="
```

---

## Устранение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Google API Error: 403 Forbidden** | Service Account не имеет прав в Play Console. | Проверьте права доступа и убедитесь, что API Google Play Android Developer включен в GCP проекте. |
| **VersionCode already used** | Попытка загрузить билд с тем же или меньшим номером версии. | Используйте `CI_PIPELINE_IID` или плагины версионирования для уникальности кода. |
| **Invalid Keystore Format** | Ошибка при декодировании Base64 или неверный формат (.jks vs .p12). | Убедитесь, что Base64 строка не содержит лишних символов и что Gradle ожидает правильный тип хранилища. |
| **Signing key not found** | Keystore не декодирован или путь неверен. | Проверьте, что файл существует после декодирования: `ls -la $KEYSTORE_FILE`. |
| **Keystore password incorrect** | Неверный пароль keystore или key. | Убедитесь, что переменные `UPLOAD_KEYSTORE_PASSWORD` и `UPLOAD_KEY_PASSWORD` переданы корректно. |
| **Bundletool version mismatch** | Версия bundletool несовместима с Gradle Plugin. | Используйте совместимые версии: проверьте `bundletool.version` в `gradle.properties`. |
| **Lint errors in CI** | Lint-ошибки блокируют сборку. | Добавьте `lintOptions { abortOnError false }` или исправьте ошибки перед коммитом. |
| **Out of memory during build** | Недостаточно памяти для Gradle. | Увеличьте `org.gradle.jvmargs=-Xmx4g` в `gradle.properties`. |
| **Play Console: APK not compatible** | AAB не подходит для целевого устройства. | Проверьте `splits.abi` и `splits.density` в конфигурации Gradle. |
| **Service Account JSON invalid** | Неверный формат JSON или истекший ключ. | Пересоздайте Service Account JSON и обновите переменные CI. |

---

## Edge Cases и ограничения

1.  **Лимит Google Play:** Google Play устанавливает лимит на количество APK/AAB (до 15 в день на каждый track). При превышении — использование `rollout` для постепенного обновления.
2.  **Ротация Upload Key:** Google разрешает сброс Upload Key через поддержку. App Signing Key сбросить невозможно без удаления приложения.
3.  **Мульти-модульные проекты:** В проектах с несколькими модулями каждый модуль может иметь свой `build.gradle` и keystore. Убедитесь, что keystore передается во все модули.
4.  **Разные Build Types:** Для `debug` и `release` сборок используйте разные keystore. Не пытайся использовать release keystore для debug сборок.
5.  **Версия Gradle Plugin:** Убедитесь, что версия `com.android.tools.build:gradle` совместима с вашей версией Gradle. Проверьте `AGP Release Notes`.
6.  **Совместимость с Android Versions:** Проверяйте `minSdkVersion` и `targetSdkVersion` перед публикацией. Google Play требует `targetSdkVersion >= 33` (Android 13) для новых приложений.
7.  **Размер AAB:** Google Play ограничивает размер AAB (до 200 МБ для базового модуля). Используйте Play Asset Delivery для больших файлов.
8.  **CI-окружение и SDK:** Убедитесь, что на раннере установлены нужные SDK и接受 licenses: `yes | sdkmanager --licenses`.

### Безопасность Keystore

- Храните Keystore в защищенном хранилище (Vault, encrypted CI secrets).
- Never коммитьте Keystore в Git.
- Ротируйте Keystore ежегодно или при утечке.
- Используйте разные Keystore для разных окружений (dev, staging, production).

### См. также:
*   **[Обзор Mobile CI/CD и инфраструктуры](./index.md)**
*   **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)**
*   **[Автоматизация через Fastlane](./fastlane-guide.md)**
