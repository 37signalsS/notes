# Android CI/CD: Подпись и публикация

## Определения

**Keystore (.jks / .keystore)** — бинарный файл-хранилище, содержащий закрытые ключи и сертификаты. В Android используется для цифровой подписи приложений, гарантируя, что обновления приходят от того же автора.

*   **Upload Key:** Ключ, которым разработчик (или CI) подписывает артефакт перед загрузкой в Play Console. При использовании Google Play App Signing этот ключ хранится у разработчика и может быть сброшен через поддержку, если утерян.
*   **App Signing Key:** Финальный ключ подписи, которым Google подписывает приложение перед доставкой пользователям. Хранится в защищенной инфраструктуре Google. Сбросить его невозможно без удаления приложения из каталога.
*   **Android App Bundle (AAB):** Современный формат публикации (обязателен с 2021 года для новых приложений). Позволяет Google Play генерировать оптимизированные APK под конкретную архитектуру и разрешение экрана, уменьшая размер загрузки.
*   **APK (Android Package):** Устаревший формат, используемый для прямой установки или внутреннего распространения. В отличие от AAB, содержит код для всех архитектур.
*   **bundletool:** Официальная утилита от Google для работы с AAB: валидация, генерация APK, получение списка поддерживаемых устройств.
*   **apksigner:** Утилита из Android SDK для проверки и подписи APK-файлов.
*   **Fastlane Supply:** Fastlane-экшен для загрузки AAB/APK и метаданных в Play Console.

---

## Базовые концепции

### Архитектура подписи в Android CI/CD

Процесс подписи Android-приложения состоит из трех этапов:
1.  **Keystore Injection:** В CI-джобе keystore декодируется из секрета (Base64) и записывается в рабочий каталог раннера.
2.  **Gradle Build & Sign:** `gradlew bundleRelease` или `bundle` автоматически находит keystore и параметры подписи, переданные через `-P` свойства или `signingConfigs`.
3.  **Upload:** Готовый AAB/APK подписывается Upload Key и загружается в Play Console через Fastlane Supply или Google API.

### Google Play App Signing

Современный стандарт (2025–2026) — разделение ответственности за подпись:
*   **CI/CD** отвечает за Upload Key. Его потеря не критична: поддержка Google позволяет сбросить ключ без удаления приложения.
*   **Google** хранит App Signing Key. Он недоступен для модификации разработчиком, что повышает безопасность конечных пользователей.

### Self-hosted Linux-раннеры для Android

В отличие от iOS, Android-сборки могут выполняться на **Linux** без проприетарных ограничений. Это открывает возможности для гибкой инфраструктуры:

| Тип раннера | Технические особенности | Сфера применения |
| :--- | :--- | :--- |
| **Linux Bare Metal** | Физические серверы с Ubuntu/Debian, JDK, Android SDK. Предсказуемая производительность, полный контроль над окружением. | Основные рабочие лошадки для release-сборок и длительных UI-тестов. |
| **Linux Container (Docker/Podman)** | Контейнеризированное окружение с зафиксированным набором зависимостей. Быстрый старт, изоляция между джобами, легкая ротация. | PR-валидация, параллельные сборки, эфемерные окружения. |
| **Linux VM ( ephemeral )** | Виртуальные машины, создаваемые под конкретную джобу и уничтожаемые после выполнения. Обеспечивает максимальную чистоту окружения. | Изоляция между проектами, тестирование на разных версиях SDK. |

### Golden Image для Android-раннеров

**Golden Image** — предварительно настроенный шаблон окружения, содержащий стандартный набор инструментов:
*   **JDK 17/21** (с фиксированной версией)
*   **Android SDK** (cmdline-tools, platform-tools, build-tools, нужные SDK-платформы)
*   **Gradle** (wrapper или системный, фиксированная версия)
*   **Fastlane** (через Bundler с зафиксированным Gemfile.lock)
*   **Инструменты тестирования:** Firebase Test Lab, Spoon, Spoon Server
*   **Мониторинг:** `node_exporter` для сбора метрик CPU, RAM, disk

Golden Image гарантирует **идемпотентность** развертывания: новый раннер поднимается за минуты, без ручной настройки.

### SRE-подход к Android CI/CD

**Принципы применения SRE:**

*   **Error Budget для пайплайна:** Договоритесь с командой о допустимом проценте проваленных сборок (например, 5% в месяц). При исчерпании бюджета фокус смещается на стабилизацию пайплайна, а не на новые фичи.
*   **MTTR (Mean Time To Repair):** Среднее время восстановления после инцидента пайплайна. Целевое значение: < 30 минут для blocking-инцидентов.
*   **Toil Reduction:** Автоматизируйте рутинные операции (обновление SDK, очистка кэша, ротацию эмуляторов). Измеряйте долю toil в работе команды.
*   **Flaky Test Management:** Ведите реестр «мигающих» тестов. Устанавливайте SLA на починку (например, 5 рабочих дней).
*   **Runbook'и:** Для каждого типичного сбоя (исчерпание лимитов Play Console, падение Gradle Daemon, зависание эмулятора) должно быть пошаговое руководство по восстановлению.

### Sysadmin: управление парком Linux-раннеров

**Provisioning и конфигурация:**

Linux-раннеры для Android требуют специализированного подхода:
*   **Установка пакет:** Используется `apt` (Debian/Ubuntu) или `dnf` (RHEL). Homebrew на Linux (`linuxbrew`) может использоваться для определенных инструментов.
*   **Системные сервисы:** GitLab Runner регистрируется как systemd-сервис с автозапуском и автоматическим восстановлением.
*   **Управление дисками:** Gradle кэш (`~/.gradle/caches`), Android SDK и артефакты могут занимать десятки гигабайт. Настройте log rotation и регулярную очистку через `systemd-tmpfiles` или `cron`.
*   **SELinux/AppArmor:** На production-раннерах включите Mandatory Access Control. Убедитесь, что процессы CI имеют минимально необходимые права.
*   **Мониторинг:** Установите `prometheus_node_exporter` на каждый раннер для сбора метрик CPU, RAM, disk I/O, температуры.

---

## Практическая реализация

### 0. Предварительные требования (Prerequisites)

*   **Linux** (Ubuntu 22.04+, Debian 12+, RHEL 9+).
*   **JDK 17 или 21** (полностью совместим с AGP 8.x).
*   **Android SDK** (cmdline-tools, platform-tools, необходимые build-tools и SDK-платформы).
*   **Ruby + Bundler:** Для управления версией Fastlane.
*   **Gradle:** Через wrapper или системный менеджер версий (`sdkman`, `mise`).
*   **GitLab Runner** (self-hosted).

**Проверка готовности окружения:**
```bash
# Проверка Java
java -version
# → openjdk version "21.0.2" 2024-01-16

# Проверка Android SDK
adb version
# → Android Debug Bridge version 1.0.41
sdkmanager --list | grep "installed"
# → build-tools;34.0.0 | platforms;android-34 | ...

# Проверка Gradle
./gradlew --version
# → Gradle 8.7
# → Kotlin: 1.9.22

# Проверка Ruby и Bundler
ruby --version && bundle --version
# → ruby 3.2.2 (2024-04-23 revision c31463cd45) [x86_64-linux]
# → Bundler version 2.5.6
```

### 1. Создание и резервное копирование Keystore

**Создание нового Keystore:**
```bash
# Генерация keystore с ключом RSA 2048
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

# Экспорт сертификата (не закрытого ключа) для shared-верификации
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

### 2. Подпись через Gradle

Gradle поддерживает два способа передачи параметров подписи: через `signingConfigs` в `build.gradle` (не рекомендуется для CI) и через injected properties (рекомендуется для CI).

**Рекомендуемый способ для CI — injected properties:**

```yaml
# .gitlab-ci.yml
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

### 3. Автоматизация версионирования

Для предотвращения ошибок "Version code already exists", используйте автоматический инкремент.

**Вариант А: Через Gradle (`build.gradle.kts`)**
```kotlin
android {
    defaultConfig {
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

### 4. Публикация через Fastlane Supply

**Supply** управляет не только бинарными файлами, но и метаданными (changelogs, описания, скриншоты).

**Настройка доступа:**
1.  Создайте Service Account в Play Console с правами "Release Manager".
2.  Скачайте JSON-ключ и сохраните его в CI как `PLAY_STORE_SERVICE_ACCOUNT_JSON`.

**Fastfile:**
```ruby
lane :deploy_to_play_store do
  gradle(task: "bundle", build_type: "Release")
  
  supply(
    track: "internal",
    aab: "app/build/outputs/bundle/release/app-release.aab",
    json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"],
    skip_upload_metadata: false,
    skip_upload_changelogs: false
  )
end
```

### 5. Тестирование в CI/CD

**Unit-тесты:**
```ruby
lane :run_unit_tests do
  gradle(task: "test", build_type: "Debug")
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

**Скриншот-тесты:**
```ruby
lane :capture_screenshots do
  gradle(
    task: "executeScreenshotTests",
    build_type: "Debug"
  )
  
  supply(
    track: "internal",
    screenshots_path: "./fastlane/metadata/android/en-US/images",
    json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"],
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

### 6. Rollback и восстановление

**Rollback через Play Console:**
*   Используйте `supply` с `track: "internal"` для быстрого отката на предыдущую версию.
*   Автоматический rollback при падении crash-free rate ниже порога.

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
  --json_key "$PLAY_STORE_SERVICE_ACCOUNT_JSON" \
  --skip_upload_metadata \
  --skip_upload_changelogs
```

---

## Валидация и проверка

Перед отправкой AAB в Play Console рекомендуется проверить его локально или на раннере:

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

## Операции и команды

| Команда / Операция | Пример / Параметры | Результат |
| :--- | :--- | :--- |
| **Генерация Keystore** | `keytool -genkeypair -v -keystore my-upload-key.jks -keyalg RSA -keysize 2048 -validity 10000 -alias my-upload-key -storepass PASS -keypass PASS -dname "CN=Name, OU=Org, O=Org, L=City, ST=State, C=US"` | Созданный `.jks` файл с закрытым ключом. |
| **Экспорт сертификата** | `keytool -export -alias my-upload-key -file my-upload-key.cer -keystore my-upload-key.jks -storepass PASS` | Публичный сертификат `.cer` для верификации. |
| **Просмотр Keystore** | `keytool -list -v -keystore my-upload-key.jks -storepass PASS` | Список alias'ов и отпечатков сертификатов. |
| **Сборка AAB** | `./gradlew bundleRelease` | `app-release.aab` в `app/build/outputs/bundle/release/`. |
| **Сборка APK (debug)** | `./gradlew assembleDebug` | `app-debug.apk` в `app/build/outputs/apk/debug/`. |
| **Unit-тесты** | `./gradlew test` | Отчет о прохождении тестов в `app/build/test-results/`. |
| **Тесты с покрытием** | `./gradlew test jacocoTestReport` | HTML-отчет о покрытии в `app/build/reports/jacoco/jacocoTestReport/`. |
| **Instrumented-тесты** | `./gradlew connectedAndroidTest` | Результаты тестов на эмуляторе/устройстве. |
| **Lint-проверка** | `./gradlew lint` | Отчет об ошибках в `app/build/reports/lint-results-release.html`. |
| **Проверка подписи APK** | `apksigner verify --verbose app/build/outputs/apk/release/app-release-unsigned.apk` | `Verifies successfully` или детальный вывод ошибки. |
| **Валидация AAB** | `bundletool validate --bundle app-release.aab` | `Bundle validated successfully`. |
| **Генерация APK из AAB** | `bundletool build-apks --bundle=app.aab --output=app.apks --mode=universal` | Универсальный APK для тестирования. |
| **Проверка versionCode** | `aapt dump badging app.aab \| grep versionCode` | `versionCode:'42'`. |
| **Проверка размера AAB** | `stat -f%z app-release.aab` | Размер в байтах. |
| **Очистка Gradle** | `./gradlew clean` | Удаление `build/` директорий. |
| **Очистка кэша Gradle** | `rm -rf ~/.gradle/caches/*` | Полная очистка кэша зависимостей. |
| **Очистка кэша Android SDK** | `rm -rf ~/.cache/android-build-cache/*` | Очистка инкрементального кэша сборки. |

---

## Устранение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Play Console API 403** | Service Account не имеет необходимых прав. | Добавьте аккаунт с ролью "Release Manager" в Play Console. Проверьте, что JSON-ключ действителен и не истек. |
| **VersionCode already used** | Попытка загрузить билд с тем же или меньшим номером версии. | Используйте `CI_PIPELINE_IID` или плагины версионирования для уникальности кода. |
| **Invalid Keystore Format** | Ошибка при декодировании Base64 или неверный формат (.jks vs .p12). | Убедитесь, что Base64 строка не содержит лишних символов и что Gradle ожидает правильный тип хранилища. |
| **Signing key not found** | Keystore не декодирован или путь неверен. | Проверьте, что файл существует после декодирования: `ls -la $KEYSTORE_FILE`. |
| **Keystore password incorrect** | Неверный пароль keystore или key. | Убедитесь, что переменные `UPLOAD_KEYSTORE_PASSWORD` и `UPLOAD_KEY_PASSWORD` переданы корректно. |
| **Bundletool version mismatch** | Версия bundletool несовместима с Gradle Plugin. | Используйте совместимые версии: проверьте `bundletool.version` в `gradle.properties`. |
| **Lint errors in CI** | Lint-ошибки блокируют сборку. | Добавьте `lintOptions { abortOnError false }` или исправьте ошибки перед коммитом. |
| **Out of memory during build** | Недостаточно памяти для Gradle Daemon. | Увеличьте `org.gradle.jvmargs=-Xmx4g` в `gradle.properties`. |
| **APK not compatible** | AAB не подходит для целевого устройства (неправильные `splits.abi` или `splits.density`). | Проверьте конфигурацию модулей в Gradle. |
| **Service Account JSON invalid** | Неверный формат JSON или истекший ключ. | Пересоздайте Service Account JSON и обновите переменные CI. |
| **Gradle Daemon not responding** | Gradle Daemon завис или устарел. | Выполните `./gradlew --stop` и перезапустите сборку. |
| **Emulator boot timeout** | Эмулятор не запускается за отведенное время. | Увеличьте таймаут в конфигурации эмулятора или используйте pre-warmed образы. |
| **Dependency resolution failed** | Сбой загрузки зависимостей из Maven репозитория. | Проверьте сетевую доступность репозитория, увеличьте таймаут в `gradle.properties` (`systemProp.org.gradle.internal.http.connectionTimeout=60000`). |
| **Insufficient disk space** | На раннере закончилось место на диске. | Выполните очистку Gradle кэша, Android SDK кэша и старых артефактов. |

---

## Best Practices

### Безопасность

*   **Секреты в CI:** Никогда не храните секреты в коде. Используйте защищенные переменные CI или локальные менеджеры секретов (HashiCorp Vault, SOPS).
*   **Keystore hygiene:** Храните keystore в зашифрованном хранилище. Никогда не коммитьте `.jks` или `.keystore` в Git. Используйте разные keystore для `dev`, `staging`, `production`.
*   **Ротация ключей:** Ротируйте Upload Key ежегодно или при утечке. App Signing Key ротируется через Play Console (Google handles this).
*   **Минимальные права Service Account:** Выдавайте только роль "Release Manager". Не используйте аккаунты с правами Owner/Admin.

### Производительность

*   **Build Cache:** Настройте Gradle Build Cache (`local` или `remote`) для переиспользования outputs между джобами. Экономия до 60% времени сборки.
*   **Параллелизм:** Включайте `org.gradle.parallel=true` и `org.gradle.daemon=true` (на persistent-раннерах).
*   **Инкрементальные сборки:** Избегайте `clean` на каждый запуск. Используйте `assembleRelease` вместо полной пересборки.
*   **Очистка:** Настраивайте автоматическую очистку `~/.gradle/caches` через `systemd-tmpfiles` или `cron` (старше 7 дней).
*   **Docker слои:** При использовании контейнеров помещайте зависимости (Gradle wrapper, SDK) в отдельные слои для переиспользования.

### Стабильность

*   **Фиксация версий:** Всегда фиксируйте версии JDK, Gradle, Android Gradle Plugin, build-tools. Используйте `gradle-wrapper.properties` и `sdkmanager` с pinned-версиями.
*   **Gradle Daemon:** На persistent-раннерах используйте daemon. На ephemeral-раннерах отключайте (`org.gradle.daemon=false`) для чистоты.
*   **Таймауты:** Устанавливайте разумные таймауты для джобов (особенно для UI-тестов: 15–20 минут).
*   **Retry:** Настройте автоматические повторные попытки для сетевых операций (загрузка зависимостей, публикация в Play Console).
*   **Rollback plan:** Имейте скрипт быстрого отката и проверьте его работоспособность на staging.

### SRE: наблюдаемость и метрики

**Ключевые SLI для Android CI/CD:**

| SLI | Описание | Целевое значение |
|:---|:---|:---|
| **Build Success Rate** | Процент успешных сборок | > 95% |
| **Build Duration** | Среднее время сборки | < 10 минут для PR, < 20 минут для release |
| **PR Validation Time** | Время проверки PR | < 10 минут |
| **Flaky Test Rate** | Процент "мигающих" тестов | < 2% |
| **Time to Internal** | Время от merge до Internal Track | < 1 час |
| **AAB Size** | Размер артефакта | < 150 МБ |
| **Lint Errors** | Ошибки линтинга | 0 (блокирующий порог) |

**Error Budget для пайплайна:** Договоритесь с командой о допустимом проценте проваленных сборок (например, 5% в месяц). При исчерпании бюджета фокус смещается на стабилизацию пайплайна.

**MTTR (Mean Time To Repair):** Среднее время восстановления после инцидента пайплайна. Целевое значение: < 30 минут для blocking-инцидентов.

**Toil Reduction:** Автоматизируйте рутинные операции (обновление SDK, очистка кэша, ротацию эмуляторов). Измеряйте долю toil в работе команды.

**Мониторинг:**
*   **Prometheus + Grafana:** Сбор метрик с раннеров (CPU, RAM, disk, network) через `node_exporter`.
*   **CI-специфичные метрики:** Длительность сборок, доля успешных джоб, время в очереди, размер артефактов.
*   **Алерты:** Настройте оповещения при падении успешности сборок ниже порога (например, < 95% за 1 час) или превышении времени сборки (например, > 20 минут).

### Provisioning Android-раннера (Sysadmin Guide)

Для reproducible-окружения используйте Infrastructure as Code. Ниже — пример базового provisioning Linux-сервера для роли Android CI-раннера.

**Шаг 1: Базовая конфигурация системы (Ubuntu/Debian)**
```bash
# Установка базовых пакетов
apt update && apt install -y openjdk-21-jdk git ruby ruby-dev build-essential curl unzip

# Установка Android SDK cmdline-tools
mkdir -p /opt/android-sdk/cmdline-tools
cd /opt/android-sdk/cmdline-tools
curl -o commandlinetools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip commandlinetools.zip && rm commandlinetools.zip
mv cmdline-tools latest

# Установка необходимых SDK-компонентов
yes | /opt/android-sdk/cmdline-tools/latest/bin/sdkmanager --licenses
/opt/android-sdk/cmdline-tools/latest/bin/sdkmanager \
  "platform-tools" \
  "platforms;android-34" \
  "build-tools;34.0.0"

# Установка Fastlane
gem install fastlane

# Настройка переменных окружения
cat <<'EOF' >> /etc/environment
ANDROID_HOME=/opt/android-sdk
PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools
EOF
```

**Шаг 2: Регистрация как CI-раннер (GitLab Runner example)**
```bash
# Установка GitLab Runner
apt install -y gitlab-runner

# Регистрация с тегами для маршрутизации
sudo gitlab-runner register \
  --url https://gitlab.company.com/ \
  --token $RUNNER_TOKEN \
  --tag-list android,linux,gradle \
  --run-untagged=false \
  --locked=false \
  --executor shell

# Запуск как системный сервис (systemd)
sudo gitlab-runner start
```

**Шаг 3: Автоматическая очистка**
```bash
# Создание скрипта очистки
cat <<'EOF' | sudo tee /usr/local/bin/android-ci-cleanup.sh
#!/bin/bash
# Очистка Gradle кэша старше 7 дней
find ~/.gradle/caches -type f -mtime +7 -delete 2>/dev/null

# Очистка Android SDK кэша
find ~/.cache/android-build-cache -type f -mtime +7 -delete 2>/dev/null

# Очистка логов Gradle
find ~/.gradle -name "*.log" -mtime +7 -delete 2>/dev/null
EOF

sudo chmod +x /usr/local/bin/android-ci-cleanup.sh

# Добавление в systemd timer для ежедневного запуска
cat <<'EOF' | sudo tee /etc/systemd/system/android-ci-cleanup.service
[Unit]
Description=Android CI cleanup

[Service]
Type=oneshot
ExecStart=/usr/local/bin/android-ci-cleanup.sh
EOF

cat <<'EOF' | sudo tee /etc/systemd/system/android-ci-cleanup.timer
[Unit]
Description=Run Android CI cleanup daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now android-ci-cleanup.timer
```

---

## Дополнительная информация

### Ограничения и edge cases

1.  **Лимит Play Console:** Play Console устанавливает лимит на количество APK/AAB загрузок (до 15 в день на каждый track). При превышении используйте `rollout` для постепенного обновления.
2.  **Ротация Upload Key:** Поддержка Google позволяет сбросить Upload Key через тикет. App Signing Key сбросить невозможно без удаления приложения.
3.  **Мульти-модульные проекты:** В проектах с несколькими модулями каждый модуль может иметь свой `build.gradle`. Убедитесь, что keystore передается во все модули через `signingConfigs`.
4.  **Разные Build Types:** Для `debug` и `release` сборок используйте разные keystore. Не используйте release keystore для debug сборок.
5.  **Версия Gradle Plugin:** Убедитесь, что версия `com.android.tools.build:gradle` совместима с вашей версией Gradle. Проверьте `AGP Release Notes`.
6.  **Совместимость с Android Versions:** Проверяйте `minSdkVersion` и `targetSdkVersion` перед публикацией. Play Console требует `targetSdkVersion >= 34` (Android 14) для новых приложений.
7.  **Размер AAB:** Play Console ограничивает размер AAB (до 200 МБ для базового модуля). Используйте Play Asset Delivery для больших файлов.
8.  **CI-окружение и SDK:** Убедитесь, что на раннере установлены нужные SDK и приняты все licenses: `yes | sdkmanager --licenses`.

### См. также

*   **[Обзор Mobile CI/CD и инфраструктуры](./index.md)** — архитектура macOS/linux-раннеров, кэширование, пайплайны.
*   **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)** — детали Provisioning Profiles, Fastlane Match и Keychain management (для сравнения подходов).
*   **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins, обработка ошибок, интеграция с Supply.
