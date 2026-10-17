# Мобильное тестирование (iOS/Android)

**Актуально для:** Appium 3.8.0, iOS 17, Android 15, Xcode 16

## Определения

**Мобильное тестирование** — комплекс проверок нативных и гибридных приложений на iOS/Android: функциональное, UI (E2E), интеграционное, перф-тесты, тесты сетевой связи и нестабильных сетей, обновлений, прерываний (звонок/уведомление), доступности (accessibility), а также Device Farm-тестирование на реальных устройствах.

**Appium** — open-source фреймворк автоматизации мобильных приложений, построенный на **W3C WebDriver-протоколе** (наследник Selenium). Актуальная ветка — Appium 2.x/3.x (последняя стабильная — Appium 3.x, требует Node.js 20.19+, поддерживает независимые драйверы).

**XCUITest** — нативный фреймворк UI-тестирования iOS от Apple (Swift/Objective-C, `XCTest`).

**Espresso** — официальный UI-тест-фреймворк Android (Kotlin/Java, Google).

**UI Automator** — фреймворк от Google для тестирования Android, работающий вне процесса приложения (системные взаимодействия, чёрный ящик).

**Monkey Test** — stress-тестирование, генерирующее случайные пользовательские события для поиска крашей и утечек памяти.

**Fuzz Test** — тестирование с невалидными/случайными входными данными для поиска крашей и проблем безопасности.

**Visual Regression Testing** — сравнение скриншотов текущего UI с эталоном для обнаружения нежелательных визуальных изменений.

**Accessibility Audit** — автоматическая проверка соответствия стандартам доступности (WCAG, ADA) для экранных элементов.

**Device Farm** — инфраструктура реальных устройств для тестирования. Self-hosted (USB-ферма) или облачные сервисы.

**Network Conditioning** — эмуляция сетевых условий (throttling, latency, packet loss) для тестирования поведения приложения в плохих сетях.

**IdlingResource** — механизм Espresso для определения готовности приложения к взаимодействию (синхронизация с фоновыми задачами).

**Orchestrator** — Google Test Orchestrator для запуска каждого теста в отдельном процессе (изоляция).

**XCTestExpectation** — механизм асинхронного ожидания в XCUITest с таймаутом.

**Test Sharding** — разделение набора тестов на группы для параллельного выполнения на разных устройствах/раннерах.

**Flaky Test** — недетерминированный тест, который периодически падает без изменений в коде.

**Test Artifact Retention** — политика хранения артефактов: отчётов, логов, видео (сроки и правила очистки).

**XCResult Bundle** — формат отчёта Xcode для тестовых прогонов: логи, скриншоты, видео, покрытие кода.

**Code Coverage** — метрика, показывающая процент кода покрытый тестами. iOS: XCTest coverage; Android: JaCoCo.

## Основные концепции

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

Для mobile-проектов пропорции смещены в сторону UI-тестов по сравнению с backend/web:

- **Unit Tests:** 50–60% — быстрая обратная связь на уровне бизнес-логики.
- **Integration/UI Tests:** 30–40% — проверка взаимодействия слоёв и UI.
- **E2E/Monkey/Fuzz:** 5–10% — end-to-end сценарии, stress-тесты.

### Иерархия: Appium = сервер + драйверы + клиент

В Appium 2/3 сервер и драйверы разделены (в отличие от монолитного Appium 1):

- **Appium Server** — npm-пакет, принимает W3C-команды.
- **Драйверы** — отдельные пакеты: `uiautomator2` (Android), `xcuitest` (iOS), `espresso` (Android-ведомый), `gecko` (Web). Установка: `appium driver install uiautomator2`.
- **Клиентские библиотеки** — Java, Python (`appium-python-client`), JS, Ruby.

Архитектура:

```
Тест (клиент) → Appium Server (:4723) → драйвер → приложение на устройстве/симуляторе
```

### Capabilities

Описывают сессию (W3C-формат с `appium:` префиксом):

```json
{
  "platformName": "iOS",
  "appium:platformVersion": "17.0",
  "appium:deviceName": "iPhone 15",
  "appium:automationName": "XCUITest",
  "appium:app": "/path/to/app-ios.app",
  "appium:udid": "00008030-00000000000000"
}
```

Для Android: `automationName: UiAutomator2`, `appPackage`/`appActivity` (для already installed), либо `appium:app` для установки APK.

### Эмуляторы, симуляторы, реальные устройства

| Термин | Платформа | Особенности |
| :--- | :--- | :--- |
| **Simulator** | iOS | Обычно быстрее; не тестирует графический/датчиковый слой нативно |
| **Emulator** | Android | AVD; медленнее, но доступен на Linux/Windows |
| **Real device** | iOS/Android | Обязательны для камеры, биометрии, push, работы с железом, флагов |

⚠️ Для продакшн-важных проверок — обязателен слой реальных устройств (Device Farm / приватная ферма). Graybox и реальные метрики батареи/сети реалистичны только там.

### XCUITest: нативный стек iOS

```swift
import XCTest

final class LoginFlowTests: XCTestCase {
    func testLogin() throws {
        let app = XCUIApplication()
        app.launch()
        app.textFields["email"].tap()
        app.textFields["email"].typeText("user@example.com")
        app.secureTextFields["password"].typeText("secret")
        app.buttons["Войти"].tap()
        XCTAssertTrue(app.staticTexts["Добро пожаловать"].waitForExistence(timeout: 5))
    }
}
```

- Определения элементов через accessibility identifiers/`testID`.
- Запуск: `xcodebuild test -scheme MyApp -destination 'platform=iOS Simulator,name=iPhone 15'`.
- Линейная связь с pipeline: macOS-раннеры и Xcode — см. [Mobile CI/CD (iOS/Android)](../CI-CD/mobile-ci-cd/index.md).

### Espresso: нативный стек Android

```kotlin
@Test
fun signInTest() {
    onView(withId(R.id.et_email)).perform(typeText("user@example.com"))
    onView(withId(R.id.et_password)).perform(typeText("secret"))
    onView(withId(R.id.btn_signin)).perform(click())
    onView(withId(R.id.tv_welcome)).check(matches(isDisplayed()))
}
```

- Espresso синхронизируется с UI-потоком автоматически (следование `idle`);
- Матчеры: `withId`, `withText`, `withContentDescription`, `allOf`, `not`.

### Гибридные приложения (WebView)

Appium работает с WebView (WebDriver), при этом:

- переключение контекста: `driver.contexts()` → `WEBVIEW_com.example` или `NATIVE_APP`;
- для iOS — `appium:autoWebview` (XCTest WKWebView), прокидывание аргументов бандла.

## Практические сценарии

### Сценарий 1: Установка Appium 3

```bash
node -v            # >= 20.19
npm install -g appium
appium driver install uiautomator2    # android
appium driver install xcuitest        # ios
appium driver list                    # проверка установленных
appium driver doctor xcuitest         # проверка окружения iOS
```

Запуск сервера: `appium --port 4723` (по умолчанию `http://localhost:4723/`).

### Сценарий 2: Запуск первого теста Python

```python
from appium import webdriver

caps = {
    "platformName": "Android",
    "appium:automationName": "UiAutomator2",
    "appium:app": "/app/app-debug.apk",
    "appium:deviceName": "emulator-5554",
}
driver = webdriver.Remote("http://localhost:4723/", caps)

driver.find_element(by="id", value="et_email").send_keys("user@example.com")
driver.find_element(by="id", value="btn_signin").click()
assert driver.find_element(by="id", value="tv_welcome").is_displayed()
driver.quit()
```

### Сценарий 3: Переключение контекста WebView

```python
contexts = driver.contexts          # ['NATIVE_APP', 'WEBVIEW_...']
driver.switch_to.context("WEBVIEW_com.example")
driver.find_element("id", "wc_email").send_keys("user@example.com")
driver.switch_to.context("NATIVE_APP")
```

### Сценарий 4: Скриншоты и видео на провале

```python
def take(self):
    driver.get_screenshot_as_file("artifacts/failure.png")
```

Навешивается в `teardown`/`finally`; также нативные видео Android (`adb shell screenrecord`). Артефакты — часть CI.

### Сценарий 5: Интеграция в mobile pipeline

Мобильный CI построен вокруг модели из [Mobile CI/CD (iOS/Android)](../CI-CD/mobile-ci-cd/index.md):

- **Android**: job `./gradlew connectedAndroidTest` (Espresso) и/или Appium-джобы против эмуляторов в Docker;
- **iOS**: `xcodebuild test` против симуляторов на macOS-раннере; Appium-джобы против фермы реальных устройств;
- артефакты: отчёты HTML/XML, screenshots, video; ретраи флаки-апкастов.

### Сценарий 6: Тестирование прерываний и сети

- **Прерывания**: на звонок/уведомление — Espresso `Intent` to ringtone, XCTest `XCUIApplication.activate` events;
- **Сеть**: iOS — Apple Network Link Conditioner; Android — `adb`/персонификация ограничений bandwidth; в 2026 типовой путь — встроенные debug menus (ATS, прочее);
- **Fitness**: тесты батареи и производительности только на реальных устройствах.

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `An unknown server-side error occurred` | Нет совпадения capabilities (automationName, version) | Запустить `appium driver doctor <driver>`, проверить deviceId |
| `No such element` в WebView | Тест ищет нативный элемент в web-контексте | Переключиться на `WEBVIEW_...` и сделать `wait_for_element` |
| Сессия не создаётся на реальном устройстве iOS | Нет доверенности/разработчик, Xcode не подключён | Проверить `xcodebuild -runFirstLaunch`, `appium:udid` |
| Эмулятор не отвечает (стоп: cold boot) | Нет GPU/hardware acceleration, запуск tablet | Включить host GPU, развёртывать AVD в host-режиме |
| Espresso «app has not started» | Отсутствует синхронизация с idle / activity отложена | `Intents.intended`, `onView` ждать `waitForIdle` с timeout |
| Тесты флакают в CI (но не локально) | Различие скоростей эмуляторов/сетей | RetryMechanism, retries на CI, функциональные артёфакты |
| Appium-сервер не видит устройство | `adb devices` пуст; включённых инстансов нет | `adb kill-server; adb start-server`, проверить UDID |

## Лучшие практики

### Архитектура и проектирование тестов

- **Test Pyramid:** Соблюдайте пропорции — больше unit-тестов, меньше E2E. UI-тесты — последний рубеж, не заменяйте ими unit-тесты.
- **Deterministic Tests:** Избегайте `sleep()`. Используйте ожидания (`XCTestExpectation`, Espresso `IdlingResource`). Flaky-тесты подрывают доверие к пайплайну.
- **Accessibility by Default:** Включайте accessibility audit в каждый PR. Исправляйте проблемы на этапе разработки, а не перед релизом.
- **Device Selection:** Тестируйте на минимальной поддерживаемой версии ОС и актуальном флагмане. Покрывайте 80% активной пользовательской базы.

### Инфраструктура и параллелизм

- **Parallel Execution:** Запускайте тесты параллельно на нескольких устройствах/симуляторах. Цель: время выполнения < 30 минут для полного набора.
- **Test Parallelization:** Используйте sharding для распределения тестов по устройствам. Один набор тестов на одно устройство.
- **Device Farm:** Для продакшн-важных проверок (камера, биометрия, push, батарея) — обязательен слой реальных устройств. Simulators/emulators не тестируют датчики и железо.
- **Network Conditioning:** Эмулируйте плохие сети через Network Link Conditioner (iOS) или `tc`/`adb` (Android) для валидации offline-first логики.

### CI/CD и артефакты

- **Artifacts:** Сохраняйте логи, скриншоты и видео при падении тестов. Это ускоряет debugging.
- **Build Cache:** Используйте кэширование на уровне раннера (SPM, Gradle, CocoaPods). Настраивайте TTL и invalidation по версии инструментов.
- **Test Evidence:** Архивируйте отчёты, логи, видео для каждого прогона. Retention policy: 30–90 дней.
- **Retry Logic:** Настраивайте автоматический retry для flaky-тестов. Flaky-тесты не должны блокировать merge, но должны иметь owner и дату починки.

### SRE-подход и observability

Mobile тестирование требует SRE-подхода для инфраструктуры device farm и тестовых окружений:

- **Error Budget для тестов:** Допустимый процент flaky-тестов — < 2%. При превышении — freeze на новые тесты до стабилизации.
- **MTTR для тестов:** Среднее время восстановления после падения тестового окружения. Целевое значение: < 30 минут.
- **Toil Reduction:** Автоматизируйте перезапуск упавших устройств, очистку симуляторов/эмуляторов, обновление фермы. Измеряйте долю ручной работы по администрированию.
- **Observability:** Каждый тест генерирует артефакты (логи, скриншоты, видео). Для flaky-тестов — полный trace.

**Ключевые метрики:**

| Метрика | Цель |
| :--- | :--- |
| Test Pass Rate | > 95% |
| Test Duration (full suite) | < 30 мин |
| Flaky Test Rate | < 2% |
| Device Utilization | > 70% |
| MTTR (Test Environment) | < 30 мин |
| Cache Hit Rate | > 80% |

## Дополнительная информация

### См. также

- **[Mobile CI/CD (iOS/Android)](../CI-CD/mobile-ci-cd/index.md)** — сборка, подпись, кэширование, пайплайны мобильных приложений (SSoT по инфраструктуре команды).
- **[Selenium WebDriver и Selenium Grid](./testing_selenium_grid.md)** — протокол WebDriver, на котором построен Appium.
- **[E2E-тестирование с помощью Cypress](./cypress_e2e_testing.md)** — веб-E2E для мобильных веб-версий.

### Внешние ресурсы

- [Appium Documentation](https://appium.io/docs/en/latest/) — официальная документация Appium (drivers, migration 1→2/3).
- [Appium GitHub](https://github.com/appium/appium) — исходный код, релизы сервера.