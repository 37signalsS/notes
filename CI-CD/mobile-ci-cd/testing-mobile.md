# Mobile Test Automation

## Определения

**XCUITest** — фреймворк для UI-тестирования iOS-приложений, интегрированный с Xcode. Использует Swift/Objective-C и работает с симуляторами и реальными устройствами.

**Espresso** — фреймворк для UI-тестирования Android-приложений от Google. Использует Kotlin/Java и работает с эмуляторами и реальными устройствами.

**Appium** — кроссплатформенный инструмент для UI-тестирования мобильных приложений. Использует WebDriver-протокол и позволяет тестировать iOS и Android нативных приложений, гибридных и мобильных веб-приложений.

**Device Farm** — инфраструктура реальных устройств для тестирования. Может быть self-hosted (USB-ферма, network-accessible) или использовать облачные сервисы. В контексте этого раздела рассматриваются только self-hosted решения.

**Test Pyramid (Mobile)** — стратегия организации тестов: базовый слой — unit-тесты, средний — integration/UI-тесты, верхний — E2E-тесты. Для mobile пропорции смещены в сторону UI-тестов из-за специфики платформ.

**UI Automator** — фреймворк от Google для тестирования Android, работающий вне процесса приложения. Используется для системных взаимодействий и черных ящиков.

**Accessibility Audit** — автоматизированная проверка соответствия стандартам доступности (WCAG, ADA). В mobile проверяет элементы управления, порядок фокуса, контрастность.

**Monkey Test** — stress-тестирование приложения генерацией случайных пользовательских событий. Выявляет краши и утечки памяти, которые не покрываются сценарийными тестами.

**Fuzz Test** — тестирование с невалидными/случайными входными данными для поиска крашей и проблем безопасности.

**Visual Regression Testing** — сравнение скриншотов текущего состояния UI с эталоном (baseline) для обнаружения нежелательных визуальных изменений.

**Snapshot (iOS)** — процесс создания скриншотов всех экранов приложения на разных устройствах и языках. Инструмент Fastlane для скриншот-тестирования.

**Screengrab (Android)** — инструмент для создания скриншотов Android-приложений. Аналог Fastlane Snapshot для Android.

**XCTestExpectation** — механизм асинхронного ожидания в XCUITest. Позволяет тесту ждать наступления условия с таймаутом.

**IdlingResource (Android)** — механизм Espresso для определения готовности приложения к взаимодействию. Отвечает за синхронизацию теста с фоновыми задачами.

**Orchestrator (Android)** — инструмент Google Test Orchestrator для запуска каждого теста в отдельном процессе. Изолирует тесты и предотвращает влияние упавшего теста на следующие.

**Flaky Test** — недетерминированный тест, который периодически падает без изменений в коде. Основная проблема UI-тестирования mobile.

**Network Conditioning** — эмуляция сетевых условий (throttling, latency, packet loss) для тестирования поведения приложения в плохих сетях.

**Test Evidence** — артефакты тестового прогона: логи, скриншоты, видео, XML/JUnit-отчеты, coverage-отчеты.

**Test Artifact Retention** — политика хранения артефактов тестов: отчетов, логов, видео. Определяет сроки хранения и правила очистки.

**Build Cache (Test)** — кэширование зависимостей и артефактов для ускорения тестовых прогонов. Включает SPM/Gradle/CocoaPods кэши и CI-level кэширование.

**Test Environment** — инфраструктура для запуска тестов: симуляторы, эмуляторы, реальные устройства, device farm, CI раннеры.

**Test Parallelization** — одновременный запуск тестов на нескольких устройствах/симуляторах для сокращения общего времени выполнения.

**Test Sharding** — разделение набора тестов на группы (shards) для параллельного выполнения на разных устройствах/раннерах.

**Accessibility Identifier** — уникальный идентификатор UI-элемента, используемый для автоматизированного тестирования. В iOS: `accessibilityIdentifier`, в Android: `contentDescription`/`tag`.

**XCResult Bundle** — формат отчета Xcode для тестовых прогонов. Содержит логи, скриншоты, видео, coverage.

**JUnit XML Report** — стандартный формат отчета о тестах. Используется CI-системами для отображения результатов.

**Code Coverage** — метрика, показывающая процент кода, покрытый тестами. В mobile: Istanbul/NYC для iOS, JaCoCo для Android.

---

## Базовые концепции

### Архитектура Mobile Testing Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│              Mobile Testing Lifecycle (CI/CD)                       │
│                                                                     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │
│  │  Code     │───►│  Build &  │───►│  Unit /   │───►│  Static   │ │
│  │  Commit   │    │  Compile  │    │ Integration│    │  Analysis │ │
│  │           │    │           │    │  Tests    │    │  (Lint)   │ │
│  │ Git push  │    │ Xcode /   │    │ XCTest /  │    │ SwiftLint │ │
│  │ PR merge  │    │ Gradle    │    │ JUnit     │    │ Detekt    │ │
│  └───────────┘    └───────────┘    └───────────┘    └───────────┘ │
│        │                 │                  │                │     │
│        ▼                 ▼                  ▼                ▼     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │
│  │  PR       │    │  UI /     │    │  Device   │    │  Test     │ │
│  │  Gate     │    │  XCUITest │    │  Farm     │    │  Report   │ │
│  │           │    │  Espresso │    │  Parallel │    │  Upload   │ │
│  │ Lint +    │    │  Appium   │    │  Sharding │    │  JUnit /  │ │
│  │ Unit tests│    │  Screen   │    │  macOS    │    │  XCResult │ │
│  │           │    │  Grab     │    │  Runners  │    │           │ │
│  └───────────┘    └───────────┘    └───────────┘    └───────────┘ │
│        │                 │                  │                │     │
│        ▼                 ▼                  ▼                ▼     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │
│  │  Release  │    │  Monkey / │    │  Test     │    │  Artifact │ │
│  │  Gate     │    │  Fuzz     │    │  Evidence │    │  Cache    │ │
│  │           │    │  Stress   │    │  Archive  │    │  Cleanup  │ │
│  │ E2E +     │    │  Crash    │    │  Logs +   │    │  SPM /    │ │
│  │ Regression│    │  Recovery │    │  Video    │    │  Gradle   │ │
│  │           │    │  Monkey   │    │           │    │           │ │
│  └───────────┘    └───────────┘    └───────────┘    └───────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Фазы lifecycle:**

1. **Code Commit:** Push в PR, запуск CI pipeline. Автоматические проверки: lint, static analysis.
2. **Build & Compile:** Компиляция IPA/AAP через Xcode/Gradle. Подготовка тестового окружения.
3. **Unit / Integration Tests:** Быстрые тесты без UI. XCTest (iOS), JUnit (Android). Цель: feedback < 5 минут.
4. **Static Analysis:** SwiftLint, Detekt, SCA-скан на CVE в зависимостях.
5. **PR Gate:** Объединение всех результатов. Блокировка merge при падении unit-тестов или lint.
6. **UI Tests:** XCUITest, Espresso, Appium на симуляторах/эмуляторах или device farm.
7. **Device Farm / Parallel:** Запуск на реальных устройствах, параллелизация, sharding.
8. **Test Report Upload:** Загрузка JUnit XML, XCResult, скриншотов, видео в artifact storage.
9. **Release Gate:** E2E-тесты, regression, visual regression, accessibility audit. Блокировка релиза при падении.
10. **Monkey / Fuzz / Stress:** Дополнительные проверки на устойчивость. Запуск по расписанию или перед релизом.
11. **Test Evidence Archive:** Архивирование отчетов, логов, видео для compliance и debugging.
12. **Build Cache Cleanup:** Очистка устаревших кэшей тестовых зависимостей.

### Mobile Test Pyramid

```
        ┌─────────────┐
        │   E2E /     │
        │  Monkey /   │
        │  Fuzz       │
        ├─────────────┤
        │   UI Tests  │
        │ XCUITest /  │
        │ Espresso    │
        ├─────────────┤
        │ Integration │
        │  Tests      │
        ├─────────────┤
        │  Unit Tests │
        └─────────────┘
```

Для mobile-проектов пропорции отличаются от backend/web:
- **Unit Tests:** 50–60%
- **Integration/UI Tests:** 30–40%
- **E2E/Monkey/Fuzz:** 5–10%

### XCUITest (iOS)

XCUITest запускает приложение в симуляторе или на реальном устройстве и управляет UI через accessibility identifiers.

**Особенности:**
- Запуск через `xcodebuild` или `xcrun`
- Требует предустановленного симулятора или подключенного устройства
- Интеграция с Fastlane (`scan`, `snapshot`)
- Тесты компилируются вместе с приложением или как отдельный таргет
- Результаты в формате XCResult bundle
- Поддержка параллельного выполнения через `-maximum-parallel-test-workers`

### Espresso (Android)

Espresso работает внутри процесса приложения и синхронизируется с UI-потоком.

**Особенности:**
- Запуск через Gradle (`connectedAndroidTest`)
- Требует эмулятора или реального устройства
- Интеграция с Fastlane (`gradle` task)
- Поддержка JUnit-аннотаций
- Android Test Orchestrator для изоляции тестов
- JUnit XML-отчеты для CI

### Appium

Appium использует WebDriver-протокол и работает как отдельный сервер, управляющий устройством.

**Особенности:**
- Кроссплатформенность: один тест-скрипт для iOS и Android
- Поддержка native, hybrid и mobile web
- Языки: Swift, Kotlin, Java, Python, JavaScript
- Серверная архитектура: Appium Server → Device
- Подходит для legacy-проектов или когда требуется единый фреймворк

### Device Farm Management

Self-hosted ферма реальных устройств требует:
- **USB-оркестрация:** ADB (Android) и `xcodebuild`/`ios-deploy` (iOS)
- **Network conditioning:** throttling bandwidth, latency, packet loss
- **Управление состояниями:** unlock, reset, очистка данных между тестами
- **Параллелизм:** ограничение по количеству одновременно работающих устройств
- **Мониторинг:** temperatura батареи, свободное место, overheat

### Visual Regression для Mobile

Специфика mobile visual regression:
- **Недетерминизм:** разные разрешения, density, версии ОС
- **Скриншоты:** через Fastlane `snapshot` (iOS) и `screengrab` (Android)
- **Сравнение:** Percy, BackstopJS, или кастомные решения с pixel tolerance
- **Devices:** тестирование на ключевых разрешениях (iPhone SE, iPhone 16 Pro Max, Android Small/Normal/Large)

### Performance Testing в Mobile

**Ключевые метрики:**
- **App Launch Time:** холодный и теплый запуск
- **Memory Usage:** потребление RAM, утечки
- **CPU Usage:** загрузка процессора
- **Network:** время отклика, потребление трафика
- **Battery:** drain на фоновые операции

**Инструменты:**
- iOS: Xcode Instruments, MetricKit
- Android: Android Profiler, Perfetto
- CI: профилирование через `xcodebuild` и `adb shell perf`

### Accessibility и i18n Testing

**Accessibility:**
- iOS: XCUITest accessibility audits, Accessibility Inspector
- Android: Espresso accessibility checks, uiautomator
- Automated axe-core для mobile

**Localization:**
- Проверка `.strings` (iOS) и `strings.xml` (Android)
- Missing translations detection
- RTL layout testing
- L10n QA automation

### SRE-подход к Mobile Testing

- **Error Budget для тестов:** Договоритесь о допустимом проценте flaky-тестов (например, < 2%). При превышении — freeze на новые тесты до стабилизации.
- **MTTR для тестов:** Среднее время восстановления после падения тестового окружения. Целевое значение: < 30 минут.
- **Toil Reduction:** Автоматизируйте перезапуск упавших устройств, очистку симуляторов, обновление фермы. Измеряйте долю ручной работы.
- **Observability:** Каждый тест должен генерировать артефакты: логи, скриншоты, видео. Для flaky-тестов — полный trace.

### Sysadmin: инфраструктура self-hosted testing

**Компоненты инфраструктуры:**

- **macOS-раннеры:** Self-hosted раннеры с Xcode, симуляторами, Fastlane. Изолированные окружения для UI-тестов.
- **Android Emulator Infrastructure:** macOS-раннеры с HAXM/Hypervisor, Android SDK, эмуляторы API 21–35.
- **Device Farm (USB):** USB-хабы, OpenSTF/STF для управления реальными устройствами. Оркестратор на Python/Node.js.
- **Network Conditioning:** `pfctl` (macOS) или `tc` (Linux) для эмуляции плохих сетей. Настройка throttling, latency, packet loss.
- **Certificate Management:** Мониторинг сертификатов подписи для тестовых сборок. Provisioning Profiles для test devices.
- **Test Artifact Storage:** Self-hosted хранилище отчетов, логов, видео, скриншотов. Retention policy.
- **Build Cache Management:** Локальный кэш на macOS-раннерах (SPM, Gradle, CocoaPods). Очистка при смене major версий инструментов.
- **Test Environment Provisioning:** Автоматизация развертывания симуляторов/эмуляторов, очистки состояния между тестами.
- **Parallel Execution Infrastructure:** Оркестрация параллельных прогонов, управление очередью устройств, sharding.

**Retention Policy (Test Artifacts):**
- **JUnit XML / XCResult:** 30–90 дней
- **Screenshots / Video:** 30–90 дней
- **Logs:** 30 дней
- **Coverage Reports:** 90 дней
- **Build Cache:** 7–14 дней на уровне раннера

**Build Cache Management (Test):**
- **SPM:** `~/Library/Caches/org.swift.swiftpm` — кэш скачанных пакетов. Очищать старше 7 дней.
- **CocoaPods:** `~/Library/Caches/CocoaPods` — кэш pods. Очищать при минорных версиях.
- **Gradle:** `~/.gradle/caches` — кэши модулей. Очищать при смене major версии Gradle.
- **CI Cache:** Настройте GitLab cache с ключом на основе lock-файла. TTL: 7–14 дней.
- **Simulator/Emulator Cache:** Очистка неиспользуемых симуляторов/эмуляторов для экономии disk space.

**Network Conditioning (Self-hosted):**
```bash
# macOS: pfctl для throttling
echo "dummynet-anchor \"100\"" | sudo pfctl -f -
echo "anchor \"100\"" | sudo pfctl -f -
echo "dummynet pipe 1 config bw 500Kbit/s delay 100ms" | sudo pfctl -a anchor:100 -f -
echo "pass out pipe 1 all" | sudo pfctl -a anchor:100 -f -
sudo pfctl -e
```

```bash
# Linux: tc для throttling
tc qdisc add dev eth0 root handle 1: htb default 12
tc class add dev eth0 parent 1: classid 1:1 htb rate 500kbit ceil 500kbit
tc class add dev eth0 parent 1: classid 1:12 htb rate 500kbit ceil 500kbit
tc qdisc add dev eth0 parent 1:12 netem delay 100ms
```

---

## Практические сценарии

### 1. XCUITest: Проект и запуск

**Создание UI-тестового таргета:**
```bash
# В Xcode: File → New → Target → UI Testing Bundle
# Или через Fastlane:
fastlane add_plugin scan
```

**Fastfile lane:**
```ruby
platform :ios do
  desc "Запуск UI-тестов на iPhone 16"
  lane :ui_tests do
    run_tests(
      scheme: "MyAppUITests",
      devices: ["iPhone 16"],
      testplan: "UITests",
      clean: true,
      code_coverage: true,
      output_types: "html,junit",
      output_directory: "./test_output/ui"
    )
  end
end
```

**Запуск через xcodebuild:**
```bash
xcodebuild test \
  -workspace MyApp.xcworkspace \
  -scheme MyAppUITests \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -resultBundlePath TestResults.xcresult \
  -enableCodeCoverage YES
# → Test Succeeded
```

### 2. Espresso: Проект и запуск

**build.gradle (app level):**
```groovy
android {
    defaultConfig {
        testInstrumentationRunner "androidx.test.runner.AndroidJUnitRunner"
    }
    
    testOptions {
        execution 'ANDROIDX_TEST_ORCHESTRATOR'
        animationsDisabled = true
    }
}

dependencies {
    androidTestImplementation 'androidx.test.ext:junit:1.1.5'
    androidTestImplementation 'androidx.test.espresso:espresso-core:3.5.1'
    androidTestUtil 'androidx.test:orchestrator:1.4.2'
}
```

**Fastfile lane:**
```ruby
platform :android do
  desc "Запуск instrumented-тестов"
  lane :ui_tests do
    gradle(
      task: "connectedAndroidTest",
      build_type: "Debug"
    )
  end
end
```

**Запуск через Gradle:**
```bash
./gradlew connectedAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.company.app.LoginTest
# → 15 tests completed, 0 failed
```

### 3. Appium: Кроссплатформенные тесты

**Установка Appium:**
```bash
npm install -g appium
appium --version
# → 2.1.0
```

**Пример теста (JavaScript + WebDriverIO):**
```javascript
const { remote } = require('webdriverio');

describe('Mobile App Tests', () => {
  it('should login', async () => {
    const driver = await remote({
      capabilities: {
        platformName: 'iOS',
        'appium:deviceName': 'iPhone 16',
        'appium:automationName': 'XCUITest',
        'appium:bundleId': 'com.company.app'
      },
      hostname: 'localhost',
      port: 4723
    });

    const loginBtn = await driver.$('~loginButton');
    await loginBtn.click();
  });
});
```

**GitLab CI workflow:**
```yaml
stages:
  - test

appium_ios_tests:
  stage: test
  tags:
    - macos
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/
  before_script:
    - npm install -g appium
    - appium --allow-insecure=adb_shell &
    - sleep 5
  script:
    - npm run test:ios
  artifacts:
    when: always
    expire_in: 1 week
    paths:
      - test_output/
```

### 4. Device Farm: Self-hosted USB-ферма

**Требования:**
- USB-хаб или USB-оверлей для подключения 5–10 устройств
- ADB (Android Debug Bridge) для управления устройствами
- `xcodebuild` и `ios-deploy` для iOS
- Оркестратор: custom-скрипт или OpenSTF/STF (Self-hosted Test Farm)

**Пример оркестратора (Python + ADB):**
```python
#!/usr/bin/env python3
# device_farm_orchestrator.py

import subprocess
import time

DEVICES = [
    {"id": "emulator-5554", "platform": "android"},
    {"id": "emulator-5556", "platform": "android"},
]

def run_tests_on_device(device_id, platform):
    """Запуск тестов на конкретном устройстве"""
    print(f"Running tests on {device_id} ({platform})")
    
    if platform == "android":
        subprocess.run([
            "adb", "-s", device_id, "shell",
            "am", "instrument", "-w",
            "com.company.app.test/androidx.test.runner.AndroidJUnitRunner"
        ])
    elif platform == "ios":
        subprocess.run([
            "xcrun", "simctl", "spawn", device_id,
            "xcodebuild", "test", "-destination", f"id={device_id}"
        ])

if __name__ == "__main__":
    for device in DEVICES:
        run_tests_on_device(device["id"], device["platform"])
```

**STF (Smartphone Test Farm) — self-hosted:**
```bash
# Запуск STF через Docker
docker run -d \
  --name stf \
  -p 7070:7070 \
  -p 8080:8080 \
  --privileged \
  devicefarmer/stf:latest
# → http://localhost:7070 — UI управления устройствами
```

### 5. Monkey / Fuzz Testing

**Monkey Test (Android):**
```bash
# Запуск Monkey на устройстве
adb shell monkey \
  -p com.company.app \
  -v 10000 \
  --throttle 100 \
  --randomize-throttle \
  --monitor-native-crashes \
  --kill-process-after-error
# → Events injected: 10000, crashes: 0
```

**Fuzz Test (iOS) с Swift:**
```swift
import XCTest

class FuzzTests: XCTestCase {
    func testRandomInputs() {
        for _ in 0..<1000 {
            let randomString = String.random(length: Int.random(in: 1...100))
            let randomInt = Int.random(in: -10000...10000)
            
            // Тестируем парсинг с невалидными данными
            _ = Parser.parse(randomString)
        }
    }
}

extension String {
    static func random(length: Int) -> String {
        let letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return String((0..<length).map { _ in letters.randomElement()! })
    }
}
```

### 6. Performance Testing в CI

**iOS: App Launch Time**
```bash
# Запуск с профилированием
xcrun xctrace record \
  --template "App Launch" \
  --device "iPhone 16" \
  --launch MyApp.app \
  --timeout 60s \
  --output launch.trace
# Анализ: среднее время запуска < 2 секунды
```

**Android: Memory Leak Detection**
```bash
# Запуск с профилированием памяти
adb shell am profile start com.company.app /sdcard/memory.hprof
adb shell input keyevent KEYCODE_APP_SWITCH
sleep 60
adb shell am profile stop com.company.app
# Анализ hprof через Android Studio
```

### 7. Accessibility Audit

**iOS: XCUITest Accessibility Check**
```swift
func testAccessibility() {
    let app = XCUIApplication()
    app.launch()
    
    // Проверка что все кнопки имеют accessibility labels
    let buttons = app.buttons
    for i in 0..<buttons.count {
        let button = buttons.element(boundBy: i)
        XCTAssertFalse(button.label.isEmpty, "Button missing accessibility label")
    }
}
```

**Android: Espresso Accessibility**
```kotlin
@Test
fun testAccessibility() {
    onView(withId(R.id.login_button))
        .check(matches(isDisplayed()))
        .check(matches(withContentDescription(not(isEmptyOrNullString()))))
}
```

### 8. Localization Validation

**Проверка отсутствующих переводов:**
```bash
# iOS: Проверка всех .strings файлов
find . -name "*.strings" -exec plutil -lint {} \;
# → OK или список ошибок

# Android: Проверка completeness
./gradlew lintVitalRelease
# → Lint report: missing translations
```

**RTL Layout Testing:**
```bash
# Android: Принудительный RTL режим
adb shell setprop debug.force_rtl 1
# Запуск тестов
./gradlew connectedAndroidTest
```

### 9. Visual Regression Testing

**Fastlane Snapshot (iOS):**
```ruby
lane :screenshots do
  snapshot(
    devices: ["iPhone 16", "iPhone 16 Pro Max"],
    languages: ["en-US", "ru"],
    scheme: "MyAppUITests",
    output_directory: "./screenshots"
  )
end
```

**Fastlane Screengrab (Android):**
```ruby
lane :screenshots do
  screengrab(
    app_package_name: "com.company.app",
    use_tests_in_classes: ["com.company.app.ScreenshotTest"],
    output_directory: "./screenshots"
  )
end
```

**Сравнение скриншотов:**
```bash
# BackstopJS
backstop test
# → Отчет о различиях между baseline и current

# Или кастомное сравнение
compare-screenshots baseline/ current/ --tolerance 0.1
```

---

## Операции и команды

### Управление симуляторами/эмуляторами

```bash
# iOS: Список доступных симуляторов
xcrun simctl list devices available
# → iPhone 16 (Booted) | iPhone 16 Pro (Shutdown)

# iOS: Запуск симулятора
xcrun simctl boot "iPhone 16"
open -a Simulator --args -CurrentDeviceUDID <UDID>

# iOS: Установка приложения
xcrun simctl install booted ./build/MyApp.app

# iOS: Запуск приложения
xcrun simctl launch booted com.company.app

# iOS: Очистка симулятора
xcrun simctl erase all

# Android: Список устройств
adb devices
# → emulator-5554 device | emulator-5556 device

# Android: Запуск эмулятора
emulator -avd Pixel_6_API_34 -no-snapshot-load &

# Android: Установка APK
adb install -r app/build/outputs/apk/debug/app-debug.apk

# Android: Очистка данных
adb shell pm clear com.company.app
```

### Диагностика тестов

```bash
# Просмотр логов теста iOS
xcrun simctl spawn booted log show \
  --predicate 'process == "MyAppUITests"' \
  --last 5m

# Просмотр логов Android
adb logcat -d | grep -E "E/AndroidRuntime|FATAL|AndroidTest"

# Скриншот при падении теста
xcrun simctl io booted screenshot test-failure.png
adb shell screencap -p /sdcard/test-failure.png
adb pull /sdcard/test-failure.png
```

### Параллелизация тестов

```bash
# XCUITest: параллельные тесты через xcodebuild
xcodebuild test \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -maximum-parallel-test-workers 4

# Espresso: параллельные тесты через Orchestrator
./gradlew connectedAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.numTests=4
```

### Управление кэшем тестовых зависимостей

```bash
# Очистка SPM кэша
rm -rf ~/Library/Caches/org.swift.swiftpm

# Очистка CocoaPods кэша
rm -rf ~/Library/Caches/CocoaPods
pod cache clean --all

# Очистка Gradle кэша
rm -rf ~/.gradle/caches/

# Очистка неиспользуемых симуляторов
xcrun simctl delete unavailable
xcrun simctl list devices | grep -i unavailable | awk -F'[()]' '{print $2}' | xargs -I {} xcrun simctl delete {}
```

### Artifact Retention: очистка тестовых артефактов

```bash
# Удаление старых отчетов из CI workspace
# GitLab: настроить expire_in при upload артефактов

# Очистка отчетов старше 30 дней
find ./test_output -type f -mtime +30 -delete 2>/dev/null

# Архивирование coverage отчетов старше 90 дней
find ./coverage -name "*.xml" -type f -mtime +90 -exec gzip {} \;
```

### Управление retention policy для тестовых артефактов

```bash
# /usr/local/bin/test-artifact-cleanup.sh
#!/bin/bash
RETENTION_DAYS=30
ARCHIVE_DIR="/opt/test/archive"

find /opt/test/reports -type f -mtime +$RETENTION_DAYS -exec mv {} $ARCHIVE_DIR/ \;
find /opt/test/logs -type f -mtime +$RETENTION_DAYS -exec mv {} $ARCHIVE_DIR/ \;

# Архивирование video отчетов
find /opt/test/videos -name "*.mp4" -type f -mtime +90 -exec gzip {} \;
```

---

## Устранение проблем

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Simulator boot timeout** | Недостаточно RAM/disk, поврежденный runtime | Увеличьте ресурсы Mac, удалите поврежденный симулятор через `xcrun simctl delete <UDID>` |
| **Simulator boot loop** | Поврежденный runtime, конфликт версий | Удалите симулятор и пересоздайте: `xcrun simctl delete unavailable && xcodebuild -downloadAllSimulators` |
| **Espresso IdlingResource timeout** | Фоновая задача не завершается | Увеличьте timeout или используйте `IdlingResource` для правильной синхронизации |
| **Appium session not created** | Устройство занято, неверные capabilities | Проверьте `adb devices` / `xcrun simctl list`, убедитесь что устройство свободно |
| **Test flakiness (iOS)** | Race condition, асинхронные операции | Используйте `XCTestExpectation` с appropriate timeout, добавьте retry логику |
| **Test flakiness (Android)** | Эмулятор не готов, network issues | Добавьте wait-for-device, проверьте `adb wait-for-device`, стабилизируйте сеть |
| **No tests found** | Неверный test plan, фильтры | Проверьте `-only-testing` фильтры, убедитесь что тесты компилируются |
| **Out of memory during tests** | Слишком много параллельных тестов | Уменьшите `maximum-parallel-test-workers`, добавьте `-Xmx4g` для Gradle |
| **Accessibility audit failed** | Отсутствуют labels, неправильный порядок фокуса | Добавьте `accessibilityLabel` и `accessibilityTraits`, проверьте через Accessibility Inspector |
| **RTL layout broken** | Жестко заданные constraints, отсутствие RTL support | Включите `android:supportsRtl="true"`, используйте `start/end` вместо `left/right` |
| **Visual regression false positive** | Разные версии ОС, density, GPU | Настройте pixel tolerance, запускайте на детерминированных окружениях |
| **Device farm queue overloaded** | Недостаточно устройств, долгие тесты | Увеличьте количество устройств, оптимизируйте время тестов, добавьте приоритизацию |
| **Network conditioning not working** | Неправильные правила pfctl/tc | Проверьте синтаксис правил, убедитесь что интерфейс существует, перезапустите pfctl/tc |
| **Certificate expired (test)** | Сертификат подписи тестовой сборки истек | Обновите сертификат, перевыпустите provisioning profile |
| **Build cache stale** | Кэш содержит артефакты от предыдущих версий | Очистите кэш при смене major версии инструментов |
| **Test artifact retention exceeded** | Диск переполнен отчетами и видео | Настройте автоматическую очистку через launchd/cron, архивируйте старые артефакты |
| **XCResult bundle corrupted** | Прерванный тестовый прогон, нехватка disk space | Увеличьте disk space на раннере, добавьте retry логику |
| **Flaky test not caught** | Retry логика отключена, неправильный порог | Настройте автоматический retry для flaky-тестов, ведите реестр мигающих тестов |

---

## Рекомендации

### Best Practices

- **Test Pyramid:** Соблюдайте пропорции: больше unit-тестов, меньше E2E. UI-тесты — последний рубеж, не заменяйте ими unit-тесты.
- **Parallel Execution:** Запускайте тесты параллельно на нескольких устройствах/симуляторах. Цель: время выполнения < 30 минут для полного набора.
- **Deterministic Tests:** Избегайте `sleep()`. Используйте ожидания (`XCTestExpectation`, `Espresso.onIdle`). Flaky-тесты подрывают доверие.
- **Device Selection:** Тестируйте на минимальной поддерживаемой версии ОС и актуальном флагмане. Покрывайте 80% активной пользовательской базы.
- **Artifacts:** Сохраняйте логи, скриншоты и видео при падении тестов. Это ускоряет debugging.
- **Accessibility by Default:** Включайте accessibility audit в каждый PR. Исправляйте проблемы на этапе разработки, а не перед релизом.
- **Toil Reduction:** Автоматизируйте перезапуск упавших устройств, очистку симуляторов. Измеряйте долю ручной работы по администрированию тестового окружения.
- **Flaky Test Management:** Ведите реестр мигающих тестов. Устанавливайте SLA на починку (например, 5 рабочих дней).
- **Error Budget для тестов:** Договоритесь о допустимом проценте flaky-тестов (< 2%). При превышении — freeze на новые тесты до стабилизации.
- **Test Evidence:** Архивируйте отчеты, логи, видео для каждого прогона. Retention policy: 30–90 дней.
- **Build Cache:** Используйте кэширование на уровне раннера и CI. Настройте TTL и invalidation based на версии инструментов.
- **Self-hosted Infrastructure:** Для enterprise используйте self-hosted device farm, artifact storage, audit log.

### Edge Cases и ограничения

1. **iOS Simulator limitations:** Симуляторы не эмулируют все железо (камера, NFC, датчики). Для этих сценариев требуются реальные устройства.
2. **Android Emulator performance:** Эмулятор требует hardware acceleration (HAXM/Hypervisor). Без этого работа медленная и ненадежная.
3. **Appium overhead:** Appium добавляет latency из-за WebDriver-протокола. Для быстрых циклов используйте нативные фреймворки.
4. **Device Farm bottlenecks:** Ограниченное количество устройств создает очередь. Используйте оркестрацию и приоритизацию.
5. **Visual regression noise:** Разные версии ОС, density и GPU дают незначительные отклонения. Настройте tolerance (обычно 0.1–0.5% pixel diff).
6. **Monkey test noise:** Monkey-тесты генерируют миллионы событий. Требуется фильтрация по known issues и crash deduplication.
7. **Parallel tests conflicts:** UI-тесты на одном устройстве/симуляторе не должны запускаться параллельно. Используйте изоляцию.
8. **Network conditioning in CI:** Emulation network conditions (throttling) требует дополнительных инструментов (`tc` на Linux, pfctl на macOS).
9. **Test environment drift:** Симуляторы/эмуляторы могут diverging по состоянию. Используйте очистку между тестами или воссоздавайте окружение.
10. **Flaky test accumulation:** Со временем flaky-тесты накапливаются. Регулярно проводите ауит и починку.
11. **Certificate expiration (test):** Сертификаты подписи тестовых сборок имеют срок действия. Истечение блокирует тестовые прогоны. Настройте алерты.
12. **Disk space exhaustion:** Тестовые артефакты (видео, логи) могут занимать много места. Настройте retention policy и автоматическую очистку.

---

## Мониторинг и Observability

**Ключевые метрики:**
- **Test Pass Rate:** % успешных прогонов (цель: > 95%)
- **Test Duration:** среднее время выполнения набора тестов
- **Flaky Test Rate:** % тестов, падающих недетерминированно (цель: < 2%)
- **Device Utilization:** % времени, которое устройства заняты тестами
- **Time to First Failure:** через сколько минут после запуска падает первый тест
- **MTTR (Test Environment):** среднее время восстановления после падения тестового окружения (цель: < 30 минут)
- **Artifact Upload Time:** время загрузки отчетов в artifact storage (цель: < 5 минут)
- **Cache Hit Rate:** % попаданий в build cache (цель: > 80%)

**Alert Rules:**
```yaml
groups:
  - name: mobile_test_alerts
    rules:
      - alert: MobileTestFailureRateHigh
        expr: rate(mobile_test_failures_total[10m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Mobile test failure rate too high"
      
      - alert: MobileTestFlaky
        expr: rate(mobile_test_flaky_total[1h]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Flaky test rate exceeds threshold"
      
      - alert: DeviceFarmOverload
        expr: device_farm_queue_length > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Device farm queue overloaded"
      
      - alert: TestEnvironmentDown
        expr: up{job="device-farm"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Test device/simulator unavailable"
      
      - alert: ArtifactStorageFull
        expr: disk_usage_percent{path="/opt/test/reports"} > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Test artifact storage disk usage > 85%"
      
      - alert: CertificateExpiryWarning
        expr: certificate_expiry_days < 7
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Signing certificate expires in < 7 days"
```

**Quality Gates:**
- Все unit-тесты должны проходить на Commit stage
- UI-тесты должны проходить на PR Validation stage
- Flaky-тесты не должны блокировать merge, но должны иметь owner и дату починки
- Accessibility audit — warning на PR, blocking на release stage
- Visual regression — warning на PR, blocking на release stage
- Test Evidence сгенерирован и uploaded

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout, approval gates, rollback procedures.
- **[Feature Flags в мобильных приложениях](./feature-flags-mobile.md)** — Kill Switch, progressive delivery.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — hotfix workflow, MTTR, postmortem.
