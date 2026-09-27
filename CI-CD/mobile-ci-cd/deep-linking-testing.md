# Deep Link Testing в Mobile CI/CD

**Актуально для:** iOS 17.x, Android 14, GitLab CI/CD 2024–2026

---

## Определения

- **Deep Linking** — механизм открытия конкретного экрана/функции приложения через URL.
- **Universal Links (iOS)** — стандартизированные URL, открывающиеся в приложении с fallback на Safari.
- **App Links (Android)** — аналог Universal Links для Android через Intent Filter.
- **Custom URL Scheme** — устаревший механизм deep linking через схему типа `myapp://`.
- **Deferred Deep Linking** — deep link, который работает даже если приложение не установлено (через сервис редиректа / self-hosted redirector).
- **App Site Association (ASA)** — файл на веб-сервере, подтверждающий владение доменом для Universal Links.
- **Digital Asset Links (DAL)** — файл на веб-сервере для Android App Links.
- **Link Routing** — обработка входящих ссылок внутри приложения.
- **MTTR (Deep Link)** — среднее время от обнаружения неработающего deep link до фикса или отката.
- **Error Budget (Deep Link)** — допустимый процент падений deep link тестов в месяц.
- **Flaky Test** — недетерминированный тест, который периодически падает без изменений в коде.
- **Test Evidence** — артефакты тестового прогона: логи, скриншоты, видео, отчеты.
- **Deep Link Regression** — breaking change в маршрутизации ссылок, приводящий к неверной навигации или крашам.

---

## Базовые концепции

### Custom URL Scheme vs Universal Links / App Links

| Критерий | Custom URL Scheme | Universal Links / App Links |
|---|---|---|
| Fallback при отсутствии приложения | Нет | Да (браузер) |
| Безопасность | Низкая | Высокая (верификация домена) |
| Настройка | Простая | ASA/DAL + entitlements/intent filter |
| Поддержка iOS 9+ | Да | Да |
| Поддержка Android 6+ | Да | Да |

### Архитектура deep linking

```
URL → OS → приложение → роутинг → экран
```

1. Пользователь открывает ссылку.
2. OS проверяет ассоциацию (ASA/DAL).
3. Приложение запускается и обрабатывает URL в `AppDelegate` / `Activity`.
4. Роутер определяет целевой экран и навигирует.

### Безопасность и верификация deep links

**Проверки в CI:**
- **Domain verification:** ASA/DAL файлы должны быть размещены по корректному пути и с правильным MIME-типом (`application/json` или `application/pkcs7-mime` для iOS).
- **Entitlement validation:** В iOS бинарнике должен присутствовать Associated Domains entitlement.
- **Intent filter validation:** В Android манифесте должен быть `<intent-filter>` с `android:autoVerify="true"`.
- **Signature check:** Для iOS проверяется подпись ASA; для Android — подпись DAL.

### Настройка Universal Links (iOS)

1. Включить Associated Domains в Xcode capabilities.
2. Добавить entitlement `applinks:example.com`.
3. Разместить `apple-app-site-association` на веб-сервере.
4. Обработать URL в `AppDelegate`:

```swift
func application(_ application: UIApplication,
                 continue userActivity: NSUserActivity,
                 restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void) -> Bool {
    guard let url = userActivity.webpageURL else { return false }
    Router.shared.handle(url)
    return true
}
```

### Настройка App Links (Android)

1. Добавить `<intent-filter>` в `AndroidManifest.xml`:

```xml
<intent-filter android:autoVerify="true">
    <action android:name="android.intent.action.VIEW" />
    <category android:name="android.intent.category.DEFAULT" />
    <category android:name="android.intent.category.BROWSABLE" />
    <data android:scheme="https" android:host="example.com" />
</intent-filter>
```

2. Разместить `assetlinks.json` на `https://example.com/.well-known/assetlinks.json`.
3. Обработать в `Activity`:

```kotlin
override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    intent.data?.let { Router.handle(it) }
}
```

### Testing strategies

- **Unit tests** — тестирование роутера в изоляции.
- **UI tests** — навигация через deep link в симуляторе/эмуляторе.
- **E2E tests** — Fastlane lanes с открытием ссылок и проверкой UI.

### Ограничения CI

- Симуляторы/эмуляторы поддерживают deep links, но могут не воспроизводить edge cases (особенно кэширование ASA/DAL на уровне OS).
- Universal Links требуют реального домена или self-hosted мок-сервера с ASA-файлом.
- App Links требуют доступ к сети для валидации DAL и могут кэшировать результат на уровне OS.
- macOS-раннеры для iOS требуют управления симуляторами через `xcrun simctl`; Android-раннеры требуют поднятого эмулятора или подключенного устройства.
- При наличии flaky тестов — применяйте quarantine и retry-политику на уровне пайплайна.

---

## Практические сценарии

### Валидация ASA / DAL файлов

```bash
# Проверка доступности ASA для iOS
curl -I https://example.com/.well-known/apple-app-site-association
# Ожидаемый заголовок: HTTP/2 200, Content-Type: application/json или application/pkcs7-mime

# Проверка доступности DAL для Android
curl https://example.com/.well-known/assetlinks.json | jq .
```

```yaml
# .gitlab-ci.yml — валидация ссылок
validate:deep-links:
  stage: test
  image: alpine:latest
  script:
    - apk add curl jq
    - |
      curl -sfI https://example.com/.well-known/apple-app-site-association \
        -H "Accept: application/json" || (echo "ASA not reachable" && exit 1)
    - |
      curl -sf https://example.com/.well-known/assetlinks.json | jq '. | length > 0' \
        || (echo "DAL invalid or empty" && exit 1)
  tags:
    - docker
```

### 1. Тестирование Universal Links в CI

```swift
// RouterTests.swift
import XCTest

class RouterTests: XCTestCase {
    func testProductDeepLink() {
        let url = URL(string: "https://example.com/product/123")!
        let expectation = XCTestExpectation(description: "Navigate to product")
        
        Router.shared.handle(url) { screen in
            XCTAssertEqual(screen, .product(id: "123"))
            expectation.fulfill()
        }
        
        wait(for: [expectation], timeout: 1.0)
    }
}
```

```yaml
# .gitlab-ci.yml
test:ios:
  stage: test
  script:
    - xcodebuild test -scheme App -destination 'platform=iOS Simulator,name=iPhone 15'
  tags:
    - ios-runner
```

**Ожидаемый результат:** Все тесты проходят, `XCTest` выводит `Test Succeeded`.

### 2. Тестирование App Links в CI

```kotlin
// RouterTests.kt
class RouterTests {
    @Test
    fun `product deep link resolves to product screen`() {
        val uri = Uri.parse("https://example.com/product/123")
        val screen = Router.handle(uri)
        assertEquals(Screen.Product("123"), screen)
    }
}
```

```yaml
# .gitlab-ci.yml
test:android:
  stage: test
  script:
    - ./gradlew test
  tags:
    - android-runner
```

**Ожидаемый результат:** Gradle завершается с `BUILD SUCCESSFUL`, все тесты из `RouterTests` пройдены.

### 3. Custom URL Scheme testing

```bash
# iOS симулятор
xcrun simctl open-url booted "myapp://product/123"

# Android эмулятор
adb shell am start -a android.intent.action.VIEW -d "myapp://product/123" com.example.app
```

**Валидация в CI:**
```bash
# Проверка, что приложение обработало ссылку и не крашнулось
adb shell dumpsys activity top | grep "com.example.app" || exit 1
```

### 4. End-to-end deep link testing

```ruby
# fastlane/Fastfile
lane :test_deep_links do
  run_tests(
    scheme: "App",
    devices: ["iPhone 15"],
    build_for_testing: true
  )
  
  # Verify deep link opens correct screen
  sh("xcrun simctl open-url booted 'https://example.com/product/123'")
  sleep(2)
  
  snapshot(
    devices: ["iPhone 15"],
    languages: ["en-US"]
  )
end
```

```bash
# Android
adb shell am start -a android.intent.action.VIEW \
  -d "https://example.com/product/123" \
  com.example.app
```

### 5. Regression testing

```swift
// DeepLinkRegressionTests.swift
class DeepLinkRegressionTests: XCTestCase {
    let deepLinks: [String: Screen] = [
        "https://example.com/product/123": .product(id: "123"),
        "https://example.com/profile": .profile,
        "https://example.com/settings": .settings
    ]
    
    func testAllDeepLinksResolve() {
        for (urlString, expectedScreen) in deepLinks {
            let url = URL(string: urlString)!
            let screen = Router.shared.resolve(url)
            XCTAssertEqual(screen, expectedScreen, "Failed for \(urlString)")
        }
    }
}
```

### 6. Mocking deep links

```swift
// URLProtocolMock.swift
class URLProtocolMock: URLProtocol {
    static var requestHandler: ((URLRequest) -> (HTTPURLResponse, Data))?
    
    override class func canInit(with request: URLRequest) -> Bool {
        return true
    }
    
    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        return request
    }
    
    override func startLoading() {
        guard let handler = URLProtocolMock.requestHandler else {
            return
        }
        let (response, data) = handler(request)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    
    override func stopLoading() {}
}
```

```kotlin
// DeepLinkTest.kt
@Test
fun `deep link with mock server`() {
    val mockServer = MockWebServer()
    mockServer.enqueue(MockResponse().setBody("{\"screen\":\"product\",\"id\":\"123\"}"))
    
    val url = mockServer.url("/product/123")
    val screen = Router.handle(url)
    
    assertEquals(Screen.Product("123"), screen)
    mockServer.shutdown()
}
```

### Deferred Deep Link testing (self-hosted)

Без облачных сервисов deferred deep link тестируется через self-hosted redirector, который:
1. Запоминает исходный URL в базе данных.
2. После установки приложения первым запуском передает сохраненный URL через intent/scheme.
3. Проверяет, что приложение открылось на правильном экране.

```bash
# Пример запуска self-hosted redirector (Docker)
docker run -d -p 8080:8080 \
  -e REDIRECT_DB_PATH=/data \
  myregistry/redirector:stable
```

```yaml
# .gitlab-ci.yml
test:deferred-deep-link:
  stage: test
  script:
    - docker start deferred-redirector
    - curl -X POST http://deferred-redirector:8080/link \
        -d '{"url":"https://example.com/product/123","device_id":"test-001"}'
    - adb install app-debug.apk
    - adb shell am start -a android.intent.action.VIEW \
        -d "http://deferred-redirector:8080/install?device_id=test-001"
    - sleep 5
    - adb shell dumpsys activity top | grep "com.example.app" || exit 1
  tags:
    - android-runner
```

---

## Наблюдаемость пайплайна

**Метрики:**
- **Deep Link Test Pass Rate** — процент успешных прогонов deep link тестов. Target: > 99%.
- **MTTR (Deep Link)** — время от падения теста до фикса. Target: < 4 часа для блокирующих failures.
- **Flaky Deep Link Rate** — процент недетерминированных падений. Target: < 1%.
- **ASA/DAL Validation Success** — успешность проверки файлов ассоциации. Target: 100%.

**Логирование:**
- Сохраняйте вывод `xcrun simctl open-url` и `adb shell am start` как артефакты.
- Логируйте результат обработки URL в приложении (в staging-режиме).
- Фиксируйте MIME-тип и HTTP-статус ASA/DAL файлов.

**Alerting:**
- Срабатывание при падении deep link тестов на release-раннере.
- Срабатывание при изменении MIME-типа ASA/DAL файлов.
- Срабатывание при исчерпании Error Budget для deep link регрессий.

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
|---|---|---|---|
| Universal Links открываются в Safari, а не в приложении | ASA не найден или неверифицирован | `curl -I https://example.com/.well-known/apple-app-site-association`, проверить entitlement | Разместить ASA с правильным MIME, перезапустить симулятор |
| App Links открываются в браузере | DAL отсутствует или имеет синтаксическую ошибку | `curl https://example.com/.well-known/assetlinks.json \| jq .`, `adb shell pm verify-app-links --reinstall com.example.app` | Исправить JSON, переустановить приложение |
| Deep link тест падает на CI, но проходит локально | Кэширование ASA/DAL на уровне runner | Очистить кэш симулятора: `xcrun simctl erase all`; для Android — `adb shell pm clear com.example.app` | Добавить шаг очистки кэша в пайплайн перед тестом |
| `simctl open-url` возвращает ошибку | Симулятор не запущен или booted неверный | `xcrun simctl list devices` | Запустить нужный симулятор, использовать корректный UDID |
| Intent filter не срабатывает | `autoVerify="true"` отсутствует или DAL не загружен | `adb shell dumpsys package com.example.app \| grep -A5 "IntentFilter"` | Добавить `autoVerify`, убедиться что DAL доступен по сети |
| Flaky deep link тесты | Гонки при навигации, кэширование роутера | Добавить ожидание навигации (`XCTestExpectation`, `IdlingResource`) | Использовать deterministic router mock, увеличить timeout |
| Deferred deep link не работает после установки | Redirector не передал сохраненный URL | Проверить логи redirector, intent extras при первом запуске | Убедиться что redirector сохраняет device_id и возвращает URL в `onNewIntent` |

---

## Best Practices

- Используйте Universal Links / App Links вместо Custom URL Scheme.
- Тестируйте fallback-поведение (приложение не установлено).
- Проверяйте entitlement / intent filter в CI на каждом PR.
- Мокайте сетевые запросы в unit tests; для E2E используйте self-hosted mock-сервер.
- Валидируйте ASA/DAL файлы отдельным пайплайн-стадией с проверкой MIME-типа и JSON-синтаксиса.
- Версионируйте deep link схемы для обратной совместимости.
- Квотируйте Error Budget на deep link регрессии: при исчерпании — freeze навигационных изменений.
- Изолируйте deep link тесты от flaky UI-тестов: используйте unit-тесты роутера как первую линию защиты.
- Архивируйте Test Evidence (логи, скриншоты, видео) для compliance и root-cause анализа.
- Настраивайте quarantine для flaky тестов: автоматический quarantine при 2 последовательных падениях, автоматический release при 3 последовательных прохождениях.

---

## См. также

- [testing-mobile.md](./testing-mobile.md)
- [backend-integration-mobile.md](./backend-integration-mobile.md)
- [security-scanning-mobile.md](./security-scanning-mobile.md)
