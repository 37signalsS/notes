# iOS Extensions CI/CD

**Актуально для:** Xcode 26–27, iOS 26–27, watchOS 11, tvOS 18, macOS 15.6+

---

## Определения

**App Extension** — дополнительный таргет в Xcode проекте, расширяющий функциональность основного приложения через стандартизированные точки интеграции iOS (Today, Share, Siri, Widget и др.).

**Today Extension** — виджет для Today View (Notification Center). Устарел в iOS 14+, заменён на WidgetKit. Поддерживается только для обратной совместимости.

**Share Extension** — расширение для шеринга контента из вашего приложения в другие приложения через системный share sheet.

**Siri Extension** — интеграция с Siri через SiriKit, позволяющая управлять приложением голосовыми командами.

**Watch Extension** — companion extension для Apple Watch, работающий в связке с основным iOS-приложением.

**TV Extension** — расширение для tvOS приложений (Top Shelf, Now Playing, TV Services).

**Widget Extension** — виджеты для домашнего экрана (iOS 14+), реализованные через WidgetKit и SwiftUI.

**App Clips** — облегчённая версия приложения, запускаемая по ссылке или NFC без полной установки.

**Multi-target проект** — Xcode проект, содержащий несколько таргетов (основное приложение, расширения, фреймворки, тесты).

**Embedded Binary** — встроенный бинарник (фреймворк или расширение), который упаковывается внутрь основного приложения или другого расширения.

**Build MTTR (Extensions)** — среднее время от обнаружения неработающей сборки расширения до фикса или отката.

**Build Error Budget (Extensions)** — допустимый процент падений сборок расширений в месяц.

**Build Evidence (Extensions)** — артефакты сборки расширений: логи, `.appex`, dSYM, отчеты.

**Build Flake (Extensions)** — недетерминированная сборка расширения, которая периодически падает без изменений в коде.

**WidgetKit** — фреймворк Apple для домашних экранов (iOS 14+), заменяющий Today Extension. Требует отдельного Widget Extension таргета.

**App Groups** — entitlement, позволяющий основному приложению и расширениям делиться данными через shared container.

---

## Базовые концепции

### Архитектура multi-target проектов в Xcode

Multi-target проект организуется вокруг одного `.xcodeproj` или `.xcworkspace` с несколькими таргетами:

- **Основное приложение** — главный таргет, который видит пользователь в App Store.
- **App Extensions** — отдельные таргеты, зависящие от основного приложения.
- **Embedding** — процесс включения расширения в состав основного приложения (copy files phase).
- **Linking** — связывание расширения с фреймворками или основным приложением.

Каждый extension таргет имеет:
- Собственный Bundle ID (обязательный суффикс типа `.extension`, `.widget`, `.clip`)
- Собственный provisioning profile
- Собственный entitlements.plist
- Собственный Info.plist

### Подпись расширений

Apple требует отдельной подписи для каждого таргета в multi-target проекте:

- Каждый extension имеет **свой App ID** в Apple Developer Portal.
- Каждый App ID имеет **свой provisioning profile** (Development, Ad Hoc, App Store).
- Entitlements extensions **ограничены** по сравнению с основным приложением (например, нет доступа к Keychain с полными правами).
- Bundle ID основного приложения и расширения **не могут быть одинаковыми**.
- Extensions не могут подписываться сертификатом, отличным от сертификата основного приложения.

### dSYM для расширений

Каждый extension таргет генерирует **собственный dSYM** файл:

- Основное приложение: `AppName.app.dSYM`
- Share Extension: `ShareExtension.appex.dSYM`
- Widget Extension: `WidgetExtension.appex.dSYM`
- Watch Extension: `WatchApp.app.dSYM`

Для symbolication crash-отчетов расширений необходим **конкретный dSYM** для каждого расширения, а не только для основного приложения.

### Зависимости между таргетами

**Embedding** — расширение физически копируется в `PlugIns` папку основного приложения:

```bash
# Проверка embedded extensions в готовом IPA
unzip -l MyApp.ipa | grep PlugIns
# → ShareExtension.appex
# → WidgetExtension.appex
```

**Linking** — расширение может зависеть от:
- Shared фреймворков (embedded в оба таргета)
- System фреймворков (UIKit, Foundation, WidgetKit)
- Основного приложения (не рекомендуется, может вызвать циклические зависимости)

### Bundle ID conventions

- Основное приложение: `com.company.appname`
- Share Extension: `com.company.appname.Share`
- Widget Extension: `com.company.appname.Widget`
- Siri Extension: `com.company.appname.Siri`
- Watch App: `com.company.appname.watchkitapp`
- App Clip: `com.company.appname.Clip`

### WidgetKit-specific considerations

Widget Extension (iOS 14+) имеет особенности по сравнению с классическими расширениями:

- **Timeline Provider:** Widget использует `TimelineProvider` для получения данных. В CI требуется тестирование timeline generation отдельно.
- **SwiftUI requirement:** WidgetKit требует SwiftUI. Убедитесь что CI-раннер имеет актуальный Swift toolchain.
- **Deep linking:** Widget может содержать deep link. Тестируйте `widgetURL(_:)` и `Link` targets.
- **App Groups:** Widget и основное приложение должны разделять App Group для обмена данными.
- **Memory limits:** Widget имеет строгие лимиты памяти (влияет на `sizeClasses` и timeline complexity).
- **Configuration:** `INIntent` или `ActivityConfiguration` требует отдельного тестирования.

### Тестирование расширений в CI

XCUITest для extensions требует:
- Отдельного test target для каждого extension
- Или использования `xcuitest` с `--only-testing` флагом для запуска тестов конкретного расширения
- На реальных устройствах (симуляторы имеют ограничения для некоторых extensions)

### SRE-подход к extension builds

- **Build Error Budget (Extensions):** Договоритесь о допустимом проценте падений сборок расширений в месяц. При исчерпании — фокус на стабилизацию пайплайна.
- **Build MTTR (Extensions):** Среднее время от падения сборки расширения до фикса. Target: < 30 минут для blocking-инцидентов.
- **Extension Build Success Rate:** Процент успешных сборок всех расширений. SLO: > 99%.
- **Extension dSYM Coverage:** 100% расширений должны иметь загруженные dSYM для symbolication.
- **Flaky Build Management:** Ведите реестр «мигающих» сборок расширений. Устанавливайте SLA на починку.

### Sysadmin: управление раннерами для extension builds

- **Диски:** DerivedData для multi-target проектов может занимать десятки гигабайт. Настройте log rotation и регулярную очистку через `launchd` или `cron`.
- **Права:** CI-раннер должен иметь доступ к рабочему каталогу, но не к signing keys напрямую. Используйте injected secrets.
- **JVM tuning:** Для проектов с CocoaPods/SPM кэшем: мониторьте `~/Library/Caches/`. Настройте TTL 7–14 дней.
- **Мониторинг:** Собирайте метрики CPU, RAM, disk I/O через `node_exporter`. Настройте алерты на заполнение диска > 85%.
- **Очистка:** При смене major версии Xcode удаляйте `~/Library/Developer/Xcode/DerivedData/` полностью.
- **Retention policy:** Храните IPA/AAB 90–180 дней, dSYM — минимум 90 дней.

---

## Практические сценарии

### 1. Настройка multi-target проекта для CI

Сборка multi-target проекта с помощью `xcodebuild`:

```bash
# Сборка основного приложения
xcodebuild build \
  -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build/MyApp \
  CODE_SIGN_STYLE=Manual \
  PROVISIONING_PROFILE_SPECIFIER="match AppStore com.company.appname" \
  CODE_SIGN_IDENTITY="Apple Distribution: Company Ltd"

# Сборка Widget Extension
xcodebuild build \
  -workspace MyApp.xcworkspace \
  -scheme MyWidgetExtension \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build/MyWidgetExtension \
  CODE_SIGN_STYLE=Manual \
  PROVISIONING_PROFILE_SPECIFIER="match AppStore com.company.appname.Widget" \
  CODE_SIGN_IDENTITY="Apple Distribution: Company Ltd"

# Проверка embedded extensions
find build/MyApp/Build/Products/Release-iphoneos -name "*.appex" -type d
```

### 2. Подпись расширений с Fastlane Match

`Fastfile` для multi-target проекта:

```ruby
lane :build_all do
  # Основное приложение
  match(
    type: "appstore",
    app_identifier: "com.company.appname",
    readonly: true
  )

  # Share Extension
  match(
    type: "appstore",
    app_identifier: "com.company.appname.Share",
    readonly: true
  )

  # Widget Extension
  match(
    type: "appstore",
    app_identifier: "com.company.appname.Widget",
    readonly: true
  )

  build_app(
    workspace: "MyApp.xcworkspace",
    scheme: "MyApp",
    export_method: "app-store",
    output_directory: "./build",
    output_name: "MyApp.ipa",
    export_options: {
      provisioningProfiles: {
        "com.company.appname" => "match AppStore com.company.appname",
        "com.company.appname.Share" => "match AppStore com.company.appname.Share",
        "com.company.appname.Widget" => "match AppStore com.company.appname.Widget"
      }
    }
  )
end
```

### 3. Сборка расширений в GitLab CI

`.gitlab-ci.yml` с параллельными джобами:

```yaml
stages:
  - build
  - test
  - upload-dsym

variables:
  FASTLANE_XCODEBUILD_SETTINGS_RETRIES: 3
  FASTLANE_XCODEBUILD_SETTINGS_TIMEOUT: 120
  DERIVED_DATA_PATH: "$CI_PROJECT_DIR/build"

build_app:
  stage: build
  script:
    - bundle exec fastlane build_app
  artifacts:
    paths:
      - build/MyApp.ipa
      - build/MyApp-dSYMs.zip
    expire_in: 1 week

build_widget:
  stage: build
  script:
    - bundle exec fastlane build_widget
  artifacts:
    paths:
      - build/MyWidgetExtension.appex
      - build/MyWidgetExtension-dSYMs.zip
    expire_in: 1 week

test_extensions:
  stage: test
  script:
    - xcodebuild test \
        -workspace MyApp.xcworkspace \
        -scheme MyApp \
        -destination 'platform=iOS Simulator,name=iPhone 15' \
        -only-testing:"MyAppShareExtensionTests" \
        -only-testing:"MyAppWidgetExtensionTests"
  artifacts:
    when: always
    paths:
      - build/TestResults.xml
    reports:
      junit: build/TestResults.xml

upload_dsyms:
  stage: upload-dsym
  script:
    - bundle exec fastlane upload_symbols
  dependencies:
    - build_app
    - build_widget
```

### 4. Тестирование расширений

Запуск тестов для конкретного расширения:

```bash
# Тесты для Share Extension
xcodebuild test \
  -workspace MyApp.xcworkspace \
  -scheme MyAppShareExtension \
  -destination 'platform=iOS Simulator,name=iPhone 15' \
  -resultBundlePath build/ShareExtensionTests.xcresult

# Конвертация xcresult в JUnit
xcrun xcresulttool get --format json --path build/ShareExtensionTests.xcresult \
  | xcpretty -r junit --output build/ShareExtensionTests.xml
```

### 5. dSYM management для extensions

Скрипт загрузки dSYM для всех расширений:

```bash
#!/bin/bash
# upload_dsyms.sh

BUILD_DIR="./build"
PROJECT="MyApp"

# Основное приложение
zip -r "${BUILD_DIR}/${PROJECT}-dSYMs.zip" \
  "${BUILD_DIR}/Build/Products/Release-iphoneos/${PROJECT}.app.dSYM"

# Extensions
find "${BUILD_DIR}/Build/Products/Release-iphoneos" -name "*.appex.dSYM" | while read dsym; do
  EXT_NAME=$(basename "$dsym" .appex.dSYM)
  zip -j "${BUILD_DIR}/${EXT_NAME}-dSYM.zip" "$dsym"
done

# Upload в self-hosted crash reporting service
crash-reporter-cli upload-dsym \
  --org company \
  --project ios \
  "${BUILD_DIR}/${PROJECT}-dSYMs.zip"
find "${BUILD_DIR}" -name "*-dSYM.zip" | while read zipfile; do
  crash-reporter-cli upload-dsym \
    --org company \
    --project ios \
    "$zipfile"
done
```

Fastlane lane для upload dSYM:

```ruby
lane :upload_symbols do
  # Upload dSYM в self-hosted crash reporting service
  if ENV["CRASH_REPORTER_AUTH_TOKEN"]
    crash_reporter_upload_dsym(
      auth_token: ENV["CRASH_REPORTER_AUTH_TOKEN"],
      org: "my-org",
      project: "my-project",
      dsym_paths: ["./build/dSYMs/"]
    )
  end

  # Дополнительно: загрузка dSYM extensions
  if ENV["CRASH_REPORTER_AUTH_TOKEN"]
    crash_reporter_upload_dsym(
      auth_token: ENV["CRASH_REPORTER_AUTH_TOKEN"],
      org: "my-org",
      project: "my-project",
      dsym_paths: ["./build/MyWidgetExtension-dSYMs.zip"]
    )
  end
end
```

### 6. Валидация embedding расширений

Проверка что extensions корректно встроены в основное приложение:

```bash
#!/bin/bash
# validate_embedding.sh

APP_PATH="./build/MyApp.app"
REQUIRED_EXTENSIONS=("ShareExtension.appex" "WidgetExtension.appex")

echo "=== Проверка embedded extensions ==="

for ext in "${REQUIRED_EXTENSIONS[@]}"; do
  if [ -d "$APP_PATH/PlugIns/$ext" ]; then
    echo "✓ $ext найден"
  else
    echo "✗ $ext отсутствует"
    exit 1
  fi
done

# Проверка подписи всех расширений
echo "=== Проверка подписи extensions ==="
codesign -vvv -d --verbose=4 "$APP_PATH"/PlugIns/*.appex

echo "=== Все проверки пройдены ==="
```

### 7. Extension-specific crash reporting workflow

Crash в extension требует отдельного dSYM для symbolication:

```bash
#!/bin/bash
# extension_crash_workflow.sh

# 1. Сборка основного приложения + extensions
xcodebuild build \
  -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -configuration Release \
  -derivedDataPath build/MyApp

# 2. Поиск всех dSYM (основное + extensions)
find build/MyApp/Build/Products/Release-iphoneos -name "*.dSYM" > dsym_list.txt

# 3. Валидация UUID каждого dSYM
while read dsym; do
  echo "Проверка: $dsym"
  dwarfdump --uuid "$dsym"
done < dsym_list.txt

# 4. Упаковка и upload
zip -r build/all-dSYMs.zip $(cat dsym_list.txt)

# 5. Upload в crash reporting service
crash-reporter-cli upload-dsym --org=company --project=ios build/all-dSYMs.zip
```

---

## Операции и команды

### Проверка окружения и подписи extensions

| Команда | Назначение | Ожидаемый результат |
|---|---|---|
| `xcodebuild -list -project MyApp.xcodeproj` | Список targets и schemes | Вывод содержит `MyApp`, `MyWidgetExtension`, `MyShareExtension` |
| `xcodebuild -showBuildSettings -scheme MyWidgetExtension` | Проверка настроек extension таргета | `PRODUCT_BUNDLE_IDENTIFIER = com.company.appname.Widget` |
| `codesign -vvv -d --verbose=4 MyApp.app/PlugIns/*.appex` | Проверка подписи всех расширений | `valid on disk` и `Identifier=com.company.appname.Share` |
| `security find-identity -p codesigning` | Список сертификатов в Keychain | Строки вида `1) XXXXXXXX "Apple Distribution: ..."` |
| `dwarfdump --uuid MyApp.app.dSYM` | UUID основного dSYM | `UUID: 12345678-1234-1234-1234-123456789012 (arm64)` |
| `dwarfdump --uuid MyApp.app/PlugIns/ShareExtension.appex.dSYM` | UUID dSYM расширения | UUID должен совпадать с бинарником расширения |
| `unzip -l MyApp.ipa \| grep PlugIns` | Проверка embedded extensions | Список всех `.appex` в IPA |
| `xcrun simctl list devices` | Доступные симуляторы | Перечень устройств с статусом `Booted`/`Shutdown` |

### Скрипт автоматической проверки подписи extensions

```bash
#!/bin/bash
# ios_extensions_signing_verify.sh

set -e

APP_PATH="./build/MyApp.app"
REQUIRED_EXTENSIONS=("ShareExtension.appex" "WidgetExtension.appex")

echo "=== Проверка embedded extensions ==="
for ext in "${REQUIRED_EXTENSIONS[@]}"; do
  if [ -d "$APP_PATH/PlugIns/$ext" ]; then
    echo "✓ $ext найден"
  else
    echo "✗ $ext отсутствует"
    exit 1
  fi
done

echo "=== Проверка подписи extensions ==="
codesign -vvv -d --verbose=4 "$APP_PATH"/PlugIns/*.appex

echo "=== Проверка dSYM ==="
find "$APP_PATH/../.." -name "*.dSYM" | while read dsym; do
  echo "✓ $dsym"
  dwarfdump --uuid "$dsym"
done

echo "=== Все проверки пройдены ==="
```

### Управление dSYM extensions

```bash
# Поиск всех dSYM (основное + extensions)
find build/ -name "*.dSYM" -type d

# Создание ZIP архива для upload
cd build/
zip -r all-dSYMs.zip *.dSYM

# Проверка UUID всех dSYM
for dsym in $(find build/ -name "*.dSYM"); do
  echo "=== $dsym ==="
  dwarfdump --uuid "$dsym"
done
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

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
|---|---|---|---|
| `No profiles for 'com.company.appname.Widget' were found` | Отсутствует provisioning profile для extension | `fastlane match development --app_identifier "com.company.appname.Widget"` | Создать/обновить profile через Match |
| `The extension's bundle identifier cannot be the same as its containing app` | Bundle ID расширения совпадает с основным приложением | Проверить `PRODUCT_BUNDLE_IDENTIFIER` в Build Settings | Измените Bundle ID на `com.company.appname.ExtensionName` |
| `Embedded binary is not signed with the same certificate as the parent app` | Расширение подписано другим сертификатом | `codesign -vvv -d --verbose=4 MyApp.app/PlugIns/*.appex` | Переподписать расширения через `match` |
| `Extension requires a development team` | В Xcode project settings extension таргета не указана Development Team | Проверить `DEVELOPMENT_TEAM` в Build Settings | Указать Development Team или добавить в xcconfig: `DEVELOPMENT_TEAM = ABC123XYZ` |
| `dSYM not found for extension` | `DEBUG_INFORMATION_FORMAT` отключен или archive поврежден | `xcodebuild -showBuildSettings \| grep DEBUG_INFORMATION_FORMAT` | Включить `dwarf-with-dsym`, пересобрать архив |
| `UUID mismatch for extension dSYM` | dSYM не соответствует бинарнику расширения | `dwarfdump --uuid` для dSYM и `.appex` | Убедитесь что загружаете dSYM из той же сборки |
| `WidgetKit timeline provider crashes` | Ошибка в `TimelineProvider` или неверные данные | Запустить widget в симуляторе, проверить логи | Изолировать provider, добавить error handling |
| `App Groups entitlement mismatch` | Основное приложение и extension имеют разные App Groups | Проверить `com.apple.security.application-groups` в entitlements | Убедиться что App Groups совпадают в обоих таргетах |
| `Extension binary not embedded` | Отсутствует Copy Files phase или неверный destination | `unzip -l MyApp.ipa \| grep PlugIns` | Добавить Copy Files phase с destination `PlugIns` |
| `Bitcode dSYM mismatch` | Apple перекомпилировал бинарник при включенном Bitcode | Скачать dSYM через App Store Connect API | Использовать `Download dSYMs from App Store Connect` |
| `Build Flake: extension test fails intermittently` | Кэширование тестовых данных, гонки, нестабильные моки | Перезапуск: `xcodebuild test --rerun-tasks` | Изолировать тест, добавить `@Flaky` quarantine |
| `signingConfigs не применяется к extension` | Отсутствует `PROVISIONING_PROFILE_SPECIFIER` для extension | `xcodebuild -showBuildSettings` для extension таргета | Проверить что profile передается для каждого extension |
| `xcresulttool conversion fails` | Неверный формат или путь к xcresult | `xcrun xcresulttool get --format json --path ...` | Проверить путь, обновить `xcpretty` |
| `Widget extension size exceeds limit` | Слишком большой bundled resources или framework | `App Store Connect` validation report | Оптимизировать assets, удалить unused resources |

---

## Наблюдаемость пайплайна

**Метрики:**
- **Extension Build Success Rate** — процент успешных сборок всех расширений. SLO: > 99%.
- **Extension Build Duration P95** — 95-й перцентиль времени сборки расширений. SLO: < 5 минут.
- **Extension dSYM Upload Rate** — процент расширений с загруженными dSYM. SLO: 100%.
- **Extension Test Pass Rate** — процент пройденных тестов расширений. SLO: > 98%.
- **Build MTTR (Extensions)** — время от падения до фикса. Target: < 30 минут.
- **Flaky Build Rate (Extensions)** — процент недетерминированных падений. Target: < 1%.

**Логирование:**
- Сохраняйте `build/reports/profile` и `build/TestResults.xml` как артефакты.
- Логируйте `PRODUCT_BUNDLE_IDENTIFIER` и `dSYM UUID` для каждого расширения.
- Архивируйте `xcresult` bundles для каждого тестового запуска.

**Alerting:**
- Срабатывание при падении Extension Build Success Rate ниже 99%.
- Срабатывание при отсутствии dSYM для любого расширения в release-сборке.
- Срабатывание при Build Duration P95 выше 10 минут.
- Срабатывание при исчерпании Build Error Budget для extensions.

---

## Best Practices

- Используйте отдельные App ID и provisioning profiles для каждого extension. Никогда не используйте wildcard App ID для extensions.
- Фиксируйте версии Xcode и Swift toolchain в CI. Используйте `xcode-select` или `xcversion` для переключения.
- Включайте `dwarf-with-dsym` для всех extension таргетов. Без dSYM crash-отчеты расширений будут несимволизированными.
- Тестируйте embedding на каждом сборке: `unzip -l MyApp.ipa | grep PlugIns`.
- Изолируйте entitlements: каждый extension должен иметь минимально необходимые entitlements (принцип least privilege).
- Используйте shared фреймворки вместо прямого embedding кода в extensions.
- Настраивайте quarantine для flaky builds extensions: автоматический quarantine при 2 последовательных падениях.
- Архивируйте Build Evidence: логи, артефакты, dSYM, xcresult bundles.
- Кэшируйте DerivedData и Match репозиторий для ускорения сборок. Устанавливайте TTL 7–14 дней.
- При смене major версии Xcode полностью очищайте `~/Library/Developer/Xcode/DerivedData/` на всех раннерах.
- Используйте `--profile` и `xcbeautify` для диагностики производительности сборок.
- Настройте retention policy для артефактов: храните release-артефакты 90–180 дней, debug — 7–14 дней.
- Для WidgetKit: тестируйте timeline provider отдельно, проверяйте deep links, ограничивайте memory usage.
- Для App Groups: проверяйте консистентность entitlements между основным приложением и extensions.

---

## См. также

- [ios-ci-cd.md](./ios-ci-cd.md) — подпись кода, Fastlane Match, ephemeral keychain, Provisioning Profiles
- [crash-reporting-mobile.md](./crash-reporting-mobile.md) — dSYM, symbolication, crash reporting services, extension dSYM upload
- [xcode-build-system.md](./xcode-build-system.md) — xcodebuild, xcconfig, schemes, multi-target сборки, build phases
