# Xcode Build System в Mobile CI/CD

**Актуально для:** Xcode 16–26, iOS 17–26, macOS 14–16

---

## Определения

- **xcodebuild** — командная утилита Apple для сборки, тестирования и архивации Xcode-проектов. Основной инструмент в CI-пайплайнах.
- **xcconfig** — текстовые конфигурационные файлы для управления Build Settings вне Xcode GUI. Позволяют версионировать настройки и разделять окружения.
- **Scheme** — конфигурация сборки, определяющая targets, тесты и действия (build, test, run, archive, profile). Может быть shared или unshared.
- **Target** — цель сборки: приложение, фреймворк, расширение или тест-бандл.
- **Build Phase** — этап сборки: компиляция источников, копирование ресурсов, linking, execution of script phases.
- **Build Settings** — параметры сборки (`CODE_SIGN_IDENTITY`, `PRODUCT_NAME`, `SDKROOT`, `ENABLE_BITCODE` и др.). Могут быть inherited или explicit.
- **Workspace** — контейнер для нескольких проектов и их зависимостей (например, основной проект + CocoaPods/Swift Package Manager).
- **Project** — корневой объект Xcode-проекта (`.xcodeproj`).
- **xcrun** — утилита для поиска и запуска инструментов Xcode по имени.
- **xcbeautify** — форматирование вывода `xcodebuild` в читаемый вид. Стандарт для CI-логов.
- **xcbuild** — альтернативная система сборки от Apple (не рекомендуется, deprecated).
- **Build Cache** — кэширование промежуточных артефактов (`DerivedData`) для ускорения повторных сборок. Target hit rate: > 80%.
- **Incremental Build** — инкрементальная сборка, пересобирающая только измененные файлы и их зависимости.
- **DerivedData** — директория с промежуточными артефактами сборки (`~/Library/Developer/Xcode/DerivedData`). Требует регулярной очистки.
- **Build Slice** — подмножество зависимостей, пересобираемое при изменении конкретного файла. Определяется графами зависимостей Xcode.
- **Build Duration SLO** — целевое время полной сборки. Target: < 10 минут для инкрементальной, < 15 минут для полной.
- **Build Success Rate** — процент успешных сборок без вмешательства. SLO: > 95%.
- **Build Infrastructure MTTR** — среднее время восстановления сборки после сбоя инфраструктуры. Target: < 15 минут.
- **Build Flake Rate** — процент нестабильных сборок, вызванных внешними факторами (сеть, ресурсы). Target: < 2%.
- **Ephemeral Keychain** — временная связка ключей macOS, создаваемая для каждой сборки и удаляемая после завершения. Предотвращает утечку секретов между запусками.
- **Artifact Retention Policy** — политика хранения артефактов сборки (IPA, dSYM, logs). Рекомендуется: 30–90 дней для release, 7 дней для CI.
- **dSYM** — файл символов для дебага и crash reporting. Должен храниться вместе с IPA для символьication crash logs.
- **BITCODE** — deprecated технология компиляции Apple. Отключена по умолчанию в Xcode 14+. Не используйте в новых проектах.

---

## Базовые концепции

### Архитектура Xcode build system

```
Workspace (опционально)
    └── Project (.xcodeproj)
            └── Target
                    └── Build Phases
                            └── Build Settings
```

### Build Settings: inherited vs explicit

- **Inherited:** Настройки наследуются от проекта, конфигурации (Debug/Release) или xcconfig-файла.
- **Explicit:** Переопределены на уровне target или build configuration.

### Управление конфигурациями

Стандартные конфигурации: `Debug`, `Release`. Кастомные (`Beta`, `Staging`) создаются в Project Editor или через xcconfig.

### Schemes: shared vs unshared

- **Shared:** Хранятся в репозитории, доступны всем членам команды. Обязательны для CI.
- **Unshared:** Локальные, не коммитятся. Не подходят для CI/CD.

### Multi-target проекты

Один проект может содержать несколько targets: основное приложение, extension, framework. В CI требуется указать правильный scheme, который покрывает нужные targets.

### Build phases

1. **Sources:** Компиляция исходников (Swift/Obj-C).
2. **Frameworks:** Копирование фреймворков.
3. **Resources:** Копирование ресурсов (assets, storyboards).
4. **Scripts:** Кастомные shell-скрипты (SwiftLint, генерация кода, Fastlane).
5. **Link Binary With Libraries:** Линковка.

### Артефакты

- **xcarchive:** Архив проекта (`.xcarchive`) — содержит бинарник, dSYM, Info.plist.
- **IPA:** Готовый пакет для установки (App Store, Ad Hoc, Enterprise).
- **dSYM:** Файл символов для дебага и crash reporting.

### Code signing integration

`xcodebuild` использует `CODE_SIGN_IDENTITY`, `PROVISIONING_PROFILE_SPECIFIER`, `DEVELOPMENT_TEAM`. В CI требуется эфемерный Keychain или Fastlane Match.

### SRE/SysAdmin: управление инфраструктурой сборок

**Build Cache Strategies:**
- **Local DerivedData:** Быстрый доступ на раннере, но не сохраняется между джобами. Используйте для инкрементальных сборок внутри одной джобы.
- **Remote Cache (self-hosted):** Используйте `sccache` или `xcache` для распределенного кэширования артефактов между раннерами. Target hit rate: > 80%.
- **Cache Invalidation:** При изменении зависимостей (Podfile.lock, Package.resolved) инвалидируйте кэш. Используйте hash зависимостей как cache key.
- **Cache Warm-up:** Прогревайте кэш на типовых раннерах перед пиковыми нагрузками.

**Resource Management:**
- **CPU/RAM:** Мониторьте утилизацию ресурсов во время сборки. Xcode может потреблять до 8GB RAM на крупных проектах.
- **Disk I/O:** DerivedData и кэши требуют быстрого диска. Используйте NVMe SSD для раннеров.
- **Parallel Jobs:** Ограничьте параллельные джобы на одном раннере, чтобы избежать OOM. Используйте `-jobs N` в xcodebuild.
- **Cleanup Automation:** Настройте автоматическую очистку DerivedData старше 7 дней и логов старше 30 дней.

**Secrets Management:**
- **Ephemeral Keychain:** Создавайте временный Keychain для каждой сборки. Удаляйте после завершения.
- **CI Variables:** Храните `CODE_SIGN_IDENTITY`, `PROVISIONING_PROFILE_SPECIFIER`, `DEVELOPMENT_TEAM` в masked CI variables.
- **Fastlane Match:** Self-hosted сервер для хранения сертификатов и профилей. Не требует облака.
- **Rotation:** Ротация сертификатов раз в год. Автоматизируйте через pipeline alerts.

**Artifact Management:**
- **Retention Policy:** IPA и dSYM храните 30–90 дней. Логи CI — 7–14 дней.
- **Checksum Verification:** Верифицируйте integrity IPA через `codesign -vvvv`.
- **Storage:** Используйте self-hosted artifact storage (GitLab Registry, Nexus, MinIO) вместо облачных сервисов.

---

## Практические сценарии

### 1. xcconfig для CI/CD

Создание конфигурационных файлов для управления Build Settings:

```bash
# CI/Build.xcconfig
CODE_SIGN_STYLE = Manual
DEVELOPMENT_TEAM = ABC123DEF4
CODE_SIGN_IDENTITY = Apple Distribution
PROVISIONING_PROFILE_SPECIFIER = match AppStore com.example.app
ENABLE_BITCODE = NO
SWIFT_VERSION = 5.9
```

```bash
# Debug.xcconfig
#include "CI/Build.xcconfig"
CODE_SIGNING_ALLOWED = NO
ONLY_ACTIVE_ARCH = YES
```

```bash
# Release.xcconfig
#include "CI/Build.xcconfig"
CODE_SIGNING_ALLOWED = YES
ONLY_ACTIVE_ARCH = NO
```

Использование в CI:

```bash
xcodebuild \
  -project MyApp.xcodeproj \
  -scheme MyApp \
  -configuration Release \
  -xcconfig CI/Build.xcconfig \
  build
```

### 2. Управление schemes

**Shared schemes:** Убедитесь, что scheme отмечен как Shared в Xcode (или через `xcodegen`).

**fastlane gym/snapshot:**

```ruby
# Fastfile
gym(
  scheme: "MyApp",
  configuration: "Release",
  export_method: "app-store",
  export_options: {
    provisioningProfiles: {
      "com.example.app" => "match AppStore com.example.app"
    }
  }
)
```

**xcodescheme CLI:**

```bash
# Создание shared scheme
xcodescheme list --project MyApp.xcodeproj
xcodescheme set-shared MyApp --project MyApp.xcodeproj
```

### 3. Multi-target сборка

Пример: основное приложение + Notification Service Extension в одной джобе:

```bash
# 1. Сборка основного таргета
xcodebuild \
  -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -configuration Release \
  -derivedDataPath build/MyApp \
  build

# 2. Сборка extension
xcodebuild \
  -workspace MyApp.xcworkspace \
  -scheme MyAppNotificationService \
  -configuration Release \
  -derivedDataPath build/Extension \
  build

# 3. Архивация основного приложения
xcodebuild \
  -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -archivePath build/MyApp.xcarchive \
  archive
```

### 4. Build phases: кастомные скрипты

```bash
# В Xcode Build Phases добавить скрипт:
# ${SRCROOT}/Scripts/run-lint.sh

#!/bin/bash
set -euo pipefail

echo "Running SwiftLint..."
if which swiftlint > /dev/null; then
  swiftlint --strict --reporter junit > swiftlint-report.xml || {
    echo "SwiftLint failed"
    exit 1
  }
else
  echo "SwiftLint not installed"
  exit 1
fi

echo "Lint completed successfully"
```

Логирование в CI:

```bash
xcodebuild build ... | xcbeautify
```

### 5. Архивация и экспорт

```bash
# Шаг 1: Архивация
xcodebuild \
  -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -configuration Release \
  -archivePath build/MyApp.xcarchive \
  archive \
  | xcbeautify

# Шаг 2: Экспорт IPA
xcodebuild \
  -exportArchive \
  -archivePath build/MyApp.xcarchive \
  -exportPath build/Export \
  -exportOptionsPlist CI/ExportOptions.plist \
  | xcbeautify
```

`ExportOptions.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>app-store</string>
    <key>teamID</key>
    <string>ABC123DEF4</string>
    <key>uploadBitcode</key>
    <false/>
    <key>uploadSymbols</key>
    <true/>
    <key>compileBitcode</key>
    <false/>
</dict>
</plist>
```

### 6. Диагностика сборки

```bash
# Детальный лог сборки
xcodebuild \
  -project MyApp.xcodeproj \
  -scheme MyApp \
  -configuration Release \
  build \
  | xcbeautify \
  | tee build.log

# Анализ времени сборки
xcodebuild \
  -project MyApp.xcodeproj \
  -scheme MyApp \
  -configuration Release \
  build \
  -showBuildTimingSummary

# Очистка DerivedData
rm -rf ~/Library/Developer/Xcode/DerivedData/*
```

### 7. Эфемерная конфигурация

Передача параметров в CI без коммита в репозиторий:

```bash
# Через переменные окружения
export CODE_SIGN_IDENTITY="Apple Distribution"
export PROVISIONING_PROFILE_SPECIFIER="match AppStore com.example.app"

xcodebuild \
  -project MyApp.xcodeproj \
  -scheme MyApp \
  -configuration Release \
  build
```

```yaml
# .gitlab-ci.yml
variables:
  XCODE_CONFIG: "Release"
  CODE_SIGN_IDENTITY: "Apple Distribution"
  PROVISIONING_PROFILE_SPECIFIER: "match AppStore com.example.app"

build_ios:
  stage: build
  script:
    - xcodebuild -project MyApp.xcodeproj -scheme MyApp -configuration $XCODE_CONFIG build
```

```bash
# Через xcconfig override (предпочтительно)
xcodebuild \
  -project MyApp.xcodeproj \
  -scheme MyApp \
  -configuration Release \
  CODE_SIGN_IDENTITY="Apple Distribution" \
  PROVISIONING_PROFILE_SPECIFIER="match AppStore com.example.app" \
  build
```

### Edge Cases и ограничения

1. **Bitcode deprecated:** Начиная с Xcode 14, `ENABLE_BITCODE` deprecated. Удалите из xcconfig для новых проектов.
2. **Xcode license:** На чистых раннерах требуется `sudo xcodebuild -license accept` перед первой сборкой.
3. **Символические ссылки в DerivedData:** Могут вызывать cache misses. Используйте полные пути.
4. **Параллельные джобы на одном раннере:** Xcode не поддерживает параллельные сборки в одной DerivedData. Используйте отдельные `-derivedDataPath` или раздельные раннеры.
5. **Provisioning profile mismatch:** Изменение Bundle Identifier требует обновления профиля. Автоматизируйте через Fastlane Match.
6. **Xcode-beta:** Сборки на beta-версиях Xcode нестабильны. Используйте только GM/релизные версии в CI.
7. **Кэш инвалидация:** Изменение `SWIFT_VERSION` или `IPHONEOS_DEPLOYMENT_TARGET` требует полной очистки DerivedData.

---

## Операции и команды

### Проверка окружения

```bash
# Версия Xcode и build
xcodebuild -version
# → Xcode 16.2
# → Build version 16C5032a

# Доступные симуляторы
xcrun simctl list devices available | grep -i iphone
# → iPhone 16, iPhone 16 Pro, iPhone 15 и т.д.

# Установленные runtime
xcrun simctl list runtimes available
# → iOS 18.0 (18.0.0) - com.apple.CoreSimulator.SimRuntime.iOS-18-0
```

### Диагностика сборки

```bash
# Проверка Build Settings
xcodebuild -project MyApp.xcodeproj \
  -scheme MyApp \
  -showBuildSettings
# → Выводит все inherited и explicit settings

# Детальный лог сборки
xcodebuild -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  build | xcbeautify
# → Build succeeded

# Анализ времени сборки
xcodebuild -scheme MyApp -configuration Release build -showBuildTimingSummary
# → Выводит таблицу времени по target'ам

# Проверка подписи IPA
codesign -vvvv -d ./build/ipa/MyApp.ipa
# → Valid on disk

# Проверка статуса симуляторов
xcrun simctl list devices | grep -E "Booted|Shutdown"
# → iPhone 16 (Booted)
# → iPhone 16 Pro (Shutdown)
```

### Управление кэшем и DerivedData

```bash
# Очистка DerivedData
rm -rf ~/Library/Developer/Xcode/DerivedData/*

# Очистка кэша SPM
rm -rf ~/Library/Caches/org.swift.swiftpm/*

# Очистка модульного кэша
rm -rf ~/Library/Developer/Xcode/DerivedData/ModuleCache.noindex/*

# Очистка неиспользуемых симуляторов
xcrun simctl delete unavailable
```

### Управление artifact storage

```bash
# Валидация IPA
codesign -vvvv -d ./build/Export/MyApp.ipa
# → Valid on disk

# Проверка dSYM
dwarfdump --uuid ./build/Export/MyApp.app.dSYM
# → UUID для сопоставления с crash logs

# Загрузка артефактов в self-hosted storage
# Пример с MinIO через mc
mc alias set myminio http://minio.local:9000 $MINIO_ACCESS_KEY $MINIO_SECRET_KEY
mc cp ./build/Export/MyApp.ipa myminio/artifacts/ios/MyApp-2.5.0.ipa
mc cp ./build/Export/MyApp.app.dSYM myminio/artifacts/ios/MyApp-2.5.0.dSYM.zip
```

---

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|---|---|---|
| **Xcode build timeout** | Зависший симулятор, нехватка RAM или deadlock в линковке. | Увеличьте `-jobs` до 2–4, завершите зависшие процессы (`pkill -f xcodebuild`), убедитесь что симуляторы закрываются после тестов (`xcrun simctl shutdown all`). |
| **Gradle OOM Error** | Недостаточно памяти для Gradle Daemon. | Увеличьте `org.gradle.jvmargs` в `gradle.properties` (например, `-Xmx4g`). |
| **"Operation not permitted"** | TCC в macOS блокирует доступ терминала к диску/сети. | Добавьте runner-аккаунт в Full Disk Access (System Settings → Privacy & Security). |
| **Code signing failed** | Неверный профиль, истекший сертификат или неверная Team ID. | Проверьте `security find-identity -p codesigning`, убедитесь что Match repo доступен. |
| **No matching provisioning profile** | Bundle Identifier не совпадает с App ID в App Store Connect. | Проверьте `PRODUCT_BUNDLE_IDENTIFIER` и provisioning profile. |
| **Scheme not found** | Scheme не shared или отсутствует в workspace. | Убедитесь что scheme отмечен как Shared, или создайте через `xcodegen`. |
| **Build cache corruption** | Поврежденный DerivedData после обновления Xcode. | Выполните полную очистку `rm -rf ~/Library/Developer/Xcode/DerivedData/*`. |
| **Simulator boot loop** | Поврежденный runtime или конфликт версий. | Удалите проблемный симулятор через `xcrun simctl delete <UDID>` и пересоздайте. |
| **"Command PhaseScriptExecution failed"** | Ошибка в кастомном скрипте Build Phase. | Запустите скрипт локально с `set -x` для дебага. Проверьте пути и права. |
| **Bitcode deprecated warning** | `ENABLE_BITCODE = YES` в проекте или зависимости. | Установите `ENABLE_BITCODE = NO` в xcconfig. |
| **"Library not found"** | Фреймворк не найден в пути поиска. | Проверьте `FRAMEWORK_SEARCH_PATHS`, убедитесь что фреймворк добавлен в target. |
| **ExportOptions.plist invalid** | Неверный `method` или отсутствующие ключи. | Проверьте метод экспорта (`app-store`, `ad-hoc`, `enterprise`, `development`). |
| **dSYM not found** | Отключен `DEBUG_INFORMATION_FORMAT` или архив поврежден. | Включите `dwarf-with-dsym` в Build Settings, пересоберите архив. |
| **"Duplicate symbols"** | Одинаковые объектные файлы линкуются дважды. | Проверьте `Other Linker Flags` (`-ObjC`, `-all_load`), уберите дубликаты. |
| **Provisioning profile expired** | Профиль истек или отозван. | Обновите через Fastlane Match или App Store Connect. |

---

## Наблюдаемость пайплайна

**Метрики сборки:**
- **Build Success Rate** — процент успешных сборок. SLO: > 95%.
- **Build Duration** — среднее время сборки. Target: < 10 минут (инкрементальная), < 15 минут (полная).
- **Time to First Install (TTFI)** — время от merge до готового IPA. Target: < 15 минут.
- **Cache Hit Rate** — процент сборок, использующих кэш. SLO: > 80%.
- **Build Flake Rate** — процент нестабильных сборок. SLO: < 2%.
- **Build Infrastructure MTTR** — время восстановления после сбоя. Target: < 15 минут.
- **DerivedData Growth Rate** — скорость роста кэша. Alert при превышении 10GB на раннер.
- **Artifact Size Trend** — мониторинг размера IPA. Рост > 20% за релиз требует анализа.

**Логирование:**
- Логируйте каждый запуск сборки: commit SHA, branch, author, timestamp, runner ID, Xcode version, scheme, configuration, результат.
- Сохраняйте `-showBuildTimingSummary` output в CI artifacts для анализа узких мест.
- Архивируйте build logs на 7–14 дней.
- Используйте structured logging (JSON) для корреляции с deployment events.
- Верифицируйте коды возврата `xcodebuild`: `0` — успех, `65` — ошибка сборки, `70` — ошибка компиляции.

**Alerting:**
- Срабатывание при Build Success Rate < 95% за 1 час.
- Срабатывание при Build Duration > 20 минут.
- Срабатывание при Cache Hit Rate < 60%.
- Срабатывание при Build Flake Rate > 2% за 24 часа.
- Срабатывание при отсутствии dSYM для нового релиза.
- Срабатывание при истечении provisioning profiles (< 7 дней до expiration).

---

## Best Practices

### Безопасность

1. **Секреты в CI:** Никогда не храните секреты в коде или xcconfig в репозитории. Используйте masked CI variables или Fastlane Match.
2. **Эфемерный Keychain:** Создавайте временный Keychain для каждой сборки. Удаляйте после завершения.
3. **OIDC (OpenID Connect):** Используйте для динамической аутентификации к App Store Connect / Google Play без статических ключей.
4. **Защита артефактов:** IPA и dSYM содержат символы. Ограничьте доступ к artifact storage.
5. **Ротация ключей:** Сертификаты Distribution — раз в год. Service Account ключи — раз в квартал.
6. **Full Disk Access:** Runner-аккаунт должен иметь Full Disk Access для работы с Keychain и DerivedData.

### Производительность

1. **Кэширование DerivedData:** Настройте persistent volume или remote cache для хранения DerivedData между джобами.
2. **Инкрементальные сборки:** Используйте `-derivedDataPath` и сохраняйте кэш между запусками.
3. **Параллелизация:** Укажите `-jobs $(sysctl -n hw.ncpu)` для параллельной компиляции.
4. **Очистка:** Удаляйте DerivedData при изменении major зависимостей (Swift version, deployment target).
5. **Мониторинг:** Отслеживайте `-showBuildTimingSummary` для выявления медленных target'ов.

### Стабильность

1. **Фиксация версий:** Фиксируйте Xcode version на раннере. Используйте `xcode-select -s /Applications/Xcode_16.2.app`.
2. **Shared Schemes:** Все schemes должны быть shared. Проверяйте в CI: `xcodebuild -list`.
3. **xcconfig вместо GUI:** Версионируйте Build Settings в xcconfig. Избегайте ручного редактирования в Xcode.
4. **Retries:** Настройте повторные попытки для сетевых ошибок (скачивание зависимостей, загрузка артефактов).
5. **Time limit:** Устанавливайте таймаут для джоб. UI-тесты: 30–45 минут, сборка: 10–15 минут.
6. **Bitcode:** Отключите `ENABLE_BITCODE` для всех target'ов. Deprecated в Xcode 14+.
7. **Clean builds:** Периодически выполняйте чистые сборки (`xcodebuild clean`) для выявления проблем с кэшем.

### SRE: наблюдаемость и метрики

**Ключевые SLI для Xcode Build System:**

| SLI | Описание | Целевое значение |
|:---|:---|:---|
| **Build Success Rate** | Процент успешных сборок | > 95% |
| **Build Duration P95** | 95-й перцентиль времени сборки | < 15 минут |
| **Cache Hit Rate** | Процент сборок с использованием кэша | > 80% |
| **Time to First Install** | Время от merge до готового IPA | < 15 минут |
| **Build Flake Rate** | Процент нестабильных сборок | < 2% |
| **Build Infrastructure MTTR** | Время восстановления после сбоя | < 15 минут |
| **DerivedData Size** | Размер кэша на раннере | < 10GB |
| **Artifact Size Growth** | Рост размера IPA за релиз | < 20% |

**Error Budget:** Договоритесь с командой о допустимом проценте проваленных сборок (например, 5% в месяц). При исчерпании бюджета фокус смещается на стабилизацию пайплайна.

**Toil Reduction:**
- Автоматизируйте очистку DerivedData и логов.
- Автоматизируйте проверку schemes и xcconfig в pre-commit hooks.
- Автоматизируйте валидацию подписи IPA после сборки.

**Runbook'и:** Для каждого типичного сбоя (code signing, provisioning profile, simulator) должно быть пошаговое руководство.

**Promotion Workflow:** Сборка Dev → Staging → Production должна быть автоматической с ручным approval gate для Production.

### Управление зависимостями

1. **SPM (Swift Package Manager):** Предпочтительный менеджер зависимостей для новых проектов. Интегрирован в Xcode. Кэшируется в DerivedData.
2. **CocoaPods:** Используйте `pod install --repo-update` только при изменении Podfile. Кэшируйте `Pods/` между джобами.
3. **Carthage:** Устарел. Мигрируйте на SPM.
4. **XcodeGen:** Используйте для управления проектом как кодом. Генерирует `.xcodeproj` из `project.yml`.
5. **Lock files:** Всегда коммитьте `Package.resolved` (SPM) и `Podfile.lock` (CocoaPods) для воспроизводимости.

---

## См. также

- **[iOS CI/CD](./ios-ci-cd.md)** — подпись кода, управление профилями, Fastlane Match.
- **[GitLab CI/CD для iOS и macOS](./gitlab-ios-ci.md)** — настройка GitLab Runner, shell executor, ephemeral keychain, масштабирование пулов.
- **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins и интеграция с iOS/Android пайплайнами.
