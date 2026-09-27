# Test Data Management для Mobile CI/CD

**Актуально для:** iOS 17–26, Android API 24–35, GitLab CI 17.x, Xcode 16.x, Gradle 8.x

---

## Определения

- **Test Data Management (TDM)** — дисциплина подготовки, генерации и очистки данных для тестов.
- **Fixture** — фиксированный набор входных данных для теста.
- **Factory** — генератор тестовых данных с вариативностью.
- **Seed Data** — начальные данные для тестирования (пользователи, посты, контент).
- **Mock Data** — поддельные данные, имитирующие реальные.
- **State Management** — управление состоянием приложения между тестами.
- **Test Database** — изолированная БД для тестов.
- **Data Cleanup** — очистка состояния после тестов.
- **Test Data Freshness SLO** — максимальное время между изменением схемы данных и обновлением seed data. Target: < 24 часа.
- **Test Environment Recovery MTTR** — среднее время восстановления тестового окружения после сбоя. Target: < 15 минут.
- **Test Flake Rate** — процент flaky-тестов, вызванных проблемами с тестовыми данными или окружением. Target: < 2%.
- **Test Data Isolation** — обеспечение изоляции тестовых данных между параллельными запусками.
- **Secrets Management for Tests** — управление секретами (API-ключи, токены) в тестовом окружении через CI variables или HashiCorp Vault.
- **Audit Logging for Test Data** — логирование доступа и изменений тестовых данных для compliance и troubleshooting.
- **Ephemeral Test Environment** — разворачиваемое под конкретный запуск тестов окружение, уничтожаемое после выполнения.

---

## Базовые концепции

### Пирамида тестирования для Mobile

```
       E2E
    Integration
  Widget / UI
Unit
```

- **Unit** — логика ViewModel, UseCase, чистые функции. Быстрые, изолированные.
- **Widget / UI** — тесты отдельных экранов и компонентов. Используют mocked data.
- **Integration** — взаимодействие между модулями, навигация, API + UI.
- **E2E** — полные сценарии через реальное приложение. Самые медленные, самые дорогие.

### State management и cross-test contamination

Главная проблема: состояние из одного теста влияет на следующий.

**iOS (XCUITest):**
- Каждый тест должен начинаться с чистого состояния.
- Используйте `app.launchArguments` для сброса.
- Удаляйте файлы в `Application Support` перед каждым запуском.

**Android (Espresso):**
- `@Rule` для сброса SharedPreferences, БД.
- `clearPackageData` в ADB для полного сброса.

### API mocking для мобильных тестов

| Инструмент | Платформа | Где используется |
|---|---|---|
| MockWebServer | Android | Unit / Integration |
| URLProtocol | iOS | Unit / Integration |
| MSW (Mock Service Worker) | Оба | Web-heavy приложения |
| WireMock | CI / Backend | Contract testing |

### Local storage подготовка

- **iOS**: Core Data memory store для тестов, Realm с in-memory конфигурацией.
- **Android**: Room in-memory БД, Realm in-memory instance.

### Network mocking

**iOS — URLProtocol:**

```swift
class MockURLProtocol: URLProtocol {
    static var requestHandler: ((URLRequest) -> (HTTPURLResponse, Data?))?

    override class func canInit(with request: URLRequest) -> Bool {
        return true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        return request
    }

    override func startLoading() {
        guard let handler = MockURLProtocol.requestHandler else {
            fatalError("Handler not set")
        }
        let (response, data) = handler(request)
        if let data = data {
            client?.urlProtocol(self, didLoad: data)
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
```

**Android — MockWebServer:**

```kotlin
val mockWebServer = MockWebServer()
mockWebServer.start()

val mockResponse = MockResponse()
    .setResponseCode(200)
    .setBody("{\"id\": 1, \"name\": \"Test User\"}")
mockWebServer.enqueue(mockResponse)

// Base URL для тестов
val baseUrl = mockWebServer.url("/").toString()
```

### SRE/SysAdmin: управление тестовыми окружениями

**Secrets Management for Tests:**
- Используйте CI/CD variables для хранения API-ключей и токенов тестового окружения.
- Для sensitive данных используйте HashiCorp Vault или equivalente self-hosted решение.
- Никогда не коммитьте секреты в репозиторий. Используйте masked variables в GitLab CI.
- Ротация test credentials: минимум 1 раз в квартал. Автоматизируйте через pipeline.

**Audit Logging:**
- Логируйте каждый запуск тестового окружения: commit SHA, branch, author, timestamp, environment variables (исключая секреты).
- Архивируйте логи тестов в artifact storage на 30–90 дней для compliance.
- Используйте structured logging (JSON) для корреляции с deployment events.

**Test Environment Recovery:**
- Target MTTR: < 15 минут для полностью разрушенного окружения.
- Используйте ephemeral runners (Tart/Orka) для быстрого пересоздания окружения.
- Golden Image для macOS-раннеров обеспечивает идемпотентное развертывание за < 5 минут.
- Для Android используйте headless эмуляторы с pre-built system images.

**Key Rotation for Test Credentials:**
- Ротация API-ключей бэкенда: квартал.
- Ротация сертификатов для внутренних сервисов: 6 месяцев.
- Храните ключи в encrypted storage с access control. Не храните на диске runner'а в открытом виде.

---

## Практические сценарии

### 1. Подготовка тестовых данных в CI (Fastlane)

```ruby
lane :prepare_test_data do
  # Скачиваем seed data из self-hosted хранилища (MinIO)
  sh "mc cp myminio/artifacts/test-data/seed.sql ./seed.sql"

  # Разворачиваем тестовую БД
  sh "bundle exec rake db:drop db:create db:schema:load db:seed:test"

  # Генерируем токены и переменные окружения для CI
  actions = generate_ci_environment()
  ENV['TEST_API_TOKEN'] = actions['TEST_API_TOKEN']
end
```

### 2. State cleanup между тестами

**iOS — App reset:**

```swift
func resetAppState() {
    let app = XCUIApplication()
    app.terminate()
    
    // Очистка Application Support
    let appSupport = FileManager.default.urls(
        for: .applicationSupportDirectory,
        in: .userDomainMask
    ).first!
    try? FileManager.default.removeItem(at: appSupport)
    
    app.launchArguments = ["--uitesting", "--reset-state"]
    app.launch()
}
```

**Android — ADB clear:**

```kotlin
@Before
fun resetApp() {
    // Очистка данных приложения
    Runtime.getRuntime().exec("adb shell pm clear com.example.app")
    
    // Или через instrumentation
    InstrumentationRegistry.getInstrumentation().uiAutomation
        .executeShellCommand("pm clear ${applicationContext.packageName}")
}
```

### 3. Factory pattern для mobile

**Swift:**

```swift
class UserFactory {
    static func build(
        id: Int = Int.random(in: 1...1000),
        name: String = "Test User \(Int.random(in: 1...1000))",
        email: String = "test\(Int.random(in: 1...1000))@example.com"
    ) -> User {
        return User(
            id: id,
            name: name,
            email: email,
            createdAt: Date()
        )
    }

    static func buildList(count: Int) -> [User] {
        return (0..<count).map { _ in build() }
    }
}

// Использование
let user = UserFactory.build()
let users = UserFactory.buildList(count: 10)
```

**Kotlin:**

```kotlin
object UserFactory {
    fun build(
        id: Int = (1..1000).random(),
        name: String = "Test User ${(1..1000).random()}",
        email: String = "test${(1..1000).random()}@example.com"
    ): User {
        return User(
            id = id,
            name = name,
            email = email,
            createdAt = Instant.now()
        )
    }

    fun buildList(count: Int): List<User> {
        return List(count) { build() }
    }
}

// Использование
val user = UserFactory.build()
val users = UserFactory.buildList(10)
```

### 4. API mocking в CI (pre-recorded responses)

**GitLab CI + MockWebServer:**

```yaml
stages:
  - test
  - e2e

setup_mock_server:
  stage: .pre
  image: python:3.11
  script:
    - pip install httpbin
    - httpbin --port 8080 &
    - sleep 2
    - echo "Mock server started"
  services:
    - name: wiremock/wiremock:latest
      alias: wiremock

unit_tests_android:
  stage: test
  image: openjdk:17
  script:
    - ./gradlew testDebugUnitTest
  variables:
    MOCK_SERVER_URL: "http://wiremock:8080"

unit_tests_ios:
  stage: test
  image: ruby:3.2
  script:
    - bundle exec fastlane unit_tests
  variables:
    MOCK_SERVER_URL: "http://wiremock:8080"

e2e_tests_android:
  stage: e2e
  image: openjdk:17
  script:
    - ./gradlew connectedDebugAndroidTest
  variables:
    MOCK_SERVER_URL: "http://wiremock:8080"

e2e_tests_ios:
  stage: e2e
  image: ruby:3.2
  script:
    - bundle exec fastlane ui_tests
  variables:
    MOCK_SERVER_URL: "http://wiremock:8080"
```

### 5. Тестирование с реальными данными (GDPR compliance)

**Анонимизация данных:**

```swift
struct AnonymizedUser {
    let id: UUID
    let name: String
    let email: String

    init(from user: User) {
        self.id = user.id
        self.name = "Anonymized User"
        self.email = "anonymized@example.com"
    }
}

// Использование в тестах
let realUser = fetchUserFromProduction()
let anonymized = AnonymizedUser(from: realUser)
```

**Kotlin:**

```kotlin
data class AnonymizedUser(
    val id: UUID,
    val name: String = "Anonymized User",
    val email: String = "anonymized@example.com"
) {
    companion object {
        fun from(user: User): AnonymizedUser {
            return AnonymizedUser(
                id = user.id
            )
        }
    }
}
```

### 6. Performance testing data

**Генерация больших наборов данных:**

```swift
func generateLargeDataset(count: Int) -> [Post] {
    return (0..<count).map { index in
        Post(
            id: index,
            title: "Post \(index) with some longer title text",
            body: String(repeating: "Body content ", count: 100),
            authorId: index % 1000
        )
    }
}
```

```kotlin
fun generateLargeDataset(count: Int): List<Post> {
    return (0 until count).map { index ->
        Post(
            id = index,
            title = "Post $index with some longer title text",
            body = "Body content ".repeat(100),
            authorId = index % 1000
        )
    }
}
```

**Fastlane lane для performance:**

```ruby
lane :performance_tests do
  # Генерируем тестовые данные
  sh "python3 scripts/generate_test_data.py --count 10000 --output ./performance-data.json"

  # Запускаем performance тесты
  scan(
    scheme: "AppPerformance",
    device: "iPhone 15 Pro Max",
    skip_build: false
  )
end
```

### Edge Cases и ограничения

1. **Лимиты параллелизма:** UI-тесты на одном устройстве/симуляторе нельзя запускать параллельно. Используйте отдельные устройства или шардирование.
2. **Flaky-тесты из-за данных:** Нефиксированные seed data или timing-dependent assertions приводят к нестабильным результатам. Фиксируйте seed и используйте deterministic factories.
3. **Размер seed data:** Большие наборы данных (>1GB) замедляют развертывание тестового окружения. Используйте сэмплирование или репрезентативные подмножества.
4. **Совместный доступ к БД:** Параллельные джобы не должны использовать одну БД. Каждый тестовый запуск требует изолированной инстанции БД.
5. **Bitcode и reproducible builds:** iOS Bitcode пересобирается на стороне Apple, что влияет на reproducibility тестов. Отключайте Bitcode для deterministic тестов.
6. **Кэширование тестовых данных:** Кэшируйте seed data в CI artifacts, но не бесконечно. Устанавливайте retention policy (например, 30 дней).
7. **Network flakiness:** Для E2E-тестов, зависящих от внешних API, используйте pre-recorded responses или self-hosted mock services.

### Promotion Workflow (Dev → Staging → Production)

**Promotion** — процесс продвижения сборки из одного окружения в другое (Dev → Staging → Production).

**Environment Protection Rules** — правила, ограничивающие доступ к определенным окружениям (manual approval, branch restrictions).

**Approval Gate** — этап, требующий ручного одобрения перед продолжением пайплайна.

#### Promotion Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│     Dev      │───►│   Staging    │───►│  Production  │
│  (Auto)      │    │  (Auto/Man) │    │  (Manual)    │
└──────────────┘    └──────────────┘    └──────────────┘
         │                   │                   │
         ▼                   ▼                   ▼
    PR Validation      Smoke Tests        Release Notes
    Unit Tests         UI Tests           Approval Gate
    Lint               Integration        Phased Release
```

#### Environment Protection

```yaml
stages:
  - build
  - deploy_staging
  - approve_production
  - deploy_production

build:
  stage: build
  tags:
    - ios
    - macos
  script:
    - bundle exec fastlane build
  artifacts:
    paths:
      - ./build/*.ipa
    expire_in: 1 week

deploy_staging:
  stage: deploy_staging
  tags:
    - ios
    - macos
  script:
    - bundle exec fastlane deploy_testflight
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

approve_production:
  stage: approve_production
  script:
    - echo "Manual approval required"
  when: manual
  only:
    - main

deploy_production:
  stage: deploy_production
  tags:
    - ios
    - macos
  script:
    - bundle exec fastlane deploy_appstore \
        --phased_release true
  environment:
    name: production
    url: https://appstore.com/company/app
  needs:
    - approve_production
  only:
    - main
```

#### GitLab CI: Manual Approval

```yaml
stages:
  - build
  - test
  - deploy_staging
  - approve_production
  - deploy_production

deploy_staging:
  stage: deploy_staging
  script:
    - bundle exec fastlane supply track:internal
  only:
    - main

approve_production:
  stage: approve_production
  script:
    - echo "Manual approval required"
  when: manual
  only:
    - main

deploy_production:
  stage: deploy_production
  script:
    - bundle exec fastlane supply track:production rollout:0.01
  when: on_success
  only:
    - main
  needs:
    - approve_production
```

---

## Операции и команды

### Проверка готовности окружения

```bash
# Проверка версии Xcode
xcodebuild -version
# → Xcode 16.2
# → Build version 16C5032a

# Проверка доступных симуляторов
xcrun simctl list devices available | grep -i iphone
# → iPhone 16, iPhone 16 Pro, iPhone 15 и т.д.

# Проверка Java
java -version
# → openjdk version "21.0.2" 2024-01-16

# Проверка Ruby и Bundler
ruby --version && bundle --version
# → ruby 3.2.2 (2024-04-23 revision c31463cd45) [arm64-darwin23]
# → Bundler version 2.5.6
```

### Диагностика тестового окружения

```bash
# Детальный лог сборки iOS
xcodebuild -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  build | xcbeautify
# → Build succeeded

# Проверка статуса симуляторов
xcrun simctl list devices | grep -E "Booted|Shutdown"
# → iPhone 16 (Booted)
# → iPhone 16 Pro (Shutdown)

# Проверка подписи IPA
codesign -vvvv -d ./build/ipa/MyApp.ipa
# → Valid on disk

# Проверка метаданных Android
aapt2 dump badging app/build/outputs/bundle/release/app-release.aab | grep version
# → versionCode:'42'
# → versionName:'2.5.0'
```

### Очистка окружения

```bash
# Очистка DerivedData
rm -rf ~/Library/Developer/Xcode/DerivedData/*

# Очистка кэша SPM
rm -rf ~/Library/Caches/org.swift.swiftpm/*

# Очистка кэша Gradle
rm -rf ~/.gradle/caches/*

# Завершение всех симуляторов
xcrun simctl shutdown all

# Очистка неиспользуемых симуляторов
xcrun simctl delete unavailable
```

### Управление seed data и artifact storage

```bash
# MinIO через mc (MinIO Client)
mc alias set myminio http://minio.local:9000 $MINIO_ACCESS_KEY $MINIO_SECRET_KEY

# Загрузка seed data
mc cp seed.sql myminio/artifacts/test-data/seed.sql

# Загрузка SBOM и provenance
mc cp sbom.json myminio/artifacts/sbom-1.0.0.json
mc cp provenance.json myminio/artifacts/provenance-1.0.0.json

# Retention policy (удаление старше 30 дней для test-data)
mc ilm import myminio/artifacts/test-data --expire-days 30
```

---

## Валидация и проверка качества

После завершения тестов убедитесь в целостности данных и окружения:

1. **Проверка seed data:** Сравните checksum seed data с ожидаемым значением. Изменение seed без обновления версии приводит к невоспроизводимым тестам.
2. **Анализ размера артефакта:** Сравнение размера текущего билда с предыдущим. Резкий рост может указывать на утечку ресурсов или лишние зависимости.
3. **Проверка метаданных:** Утилита `aapt2` (для Android) позволяет убедиться, что `versionCode` и `versionName` установлены корректно.
4. **Проверка ProGuard/R8 (Android):** Убедитесь, что обфускация не сломала критичную функциональность.
5. **Тестирование на реальном устройстве:** Установите IPA/APK на физическое устройство перед публикацией.

---

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|---|---|---|
| **Missing private key** | Раннер не имеет доступа к Keychain или Match запущен без `readonly`. | Проверьте `MATCH_PASSWORD` и права доступа к репозиторию сертификатов. |
| **Xcode build timeout** | Зависший симулятор или нехватка ресурсов (RAM). | Используйте `--parallel` и убедитесь, что симуляторы закрываются после тестов (`xcrun simctl shutdown all`). |
| **Gradle OOM Error** | Недостаточно памяти для Gradle Daemon. | Увеличьте `org.gradle.jvmargs` в `gradle.properties` (например, `-Xmx4g`). |
| **No matching provisioning profile** | Несоответствие Bundle Identifier в проекте и в App Store Connect. | Проверьте `PRODUCT_BUNDLE_IDENTIFIER` в Xcode и App ID в Match. |
| **Google Play API 403** | Service Account не имеет прав в Play Console. | Добавьте Service Account с ролью "Release Manager" в Google Play Console. |
| **TestFlight upload failed** | Неверный API Key или ключ отозван в App Store Connect. | Проверьте `ASC_KEY_ID` и `ASC_ISSUER_ID`, убедитесь что ключ не отозван. |
| **CocoaPods install fails** | Конфликт версий зависимостей или устаревший кэш. | Выполните `pod cache clean --all` и `pod install --repo-update`. |
| **Android SDK not found** | Переменная `ANDROID_HOME` не задана или указывает на неверный путь. | Установите `ANDROID_HOME` или используйте `sdkmanager` для установки SDK. |
| **Runner offline (GitLab)** | Сервис раннера не запущен или устарел. | Проверьте `launchctl list | grep run`. Обновите бинарник. |
| **Disk full on runner** | DerivedData, кэши или логи заполнили диск. | Выполните cleanup-скрипт или расширьте диск. Настройте автоматическую очистку. |
| **Simulator boot loop** | Поврежденный runtime симулятора. | Удалите проблемный симулятор через `xcrun simctl delete <UDID>` и пересоздайте. |
| **Mock server timeout** | WireMock/Prism не отвечает или перегружен. | Проверьте статус контейнера/сервиса, увеличьте timeout в тестах. |
| **Test data checksum mismatch** | Seed data изменился, но тест ожидает старую версию. | Обновите expected checksum в тесте или откатите seed data. |
| **Flaky test: race condition** | Параллельные тесты модифицируют общие данные. | Используйте изолированные БД или синхронизацию доступа к общим ресурсам |
| **Test DB connection refused** | Тестовая БД не запущена или перегружена. | Проверьте статус БД, увеличьте пул соединений, используйте in-memory БД для unit-тестов |

---

## Наблюдаемость пайплайна

**Метрики тестового пайплайна:**
- **Build Success Rate** — процент успешных сборок. SLO: > 95%.
- **Build Duration** — среднее время сборки. Target: < 15 минут.
- **PR Validation Time** — время проверки PR. Target: < 10 минут.
- **Test Flake Rate** — процент "мигающих" тестов. SLO: < 2%.
- **Time to First Install (TTFI)** — время от merge до TestFlight. Target: < 2 часа.
- **Test Data Freshness** — время между изменением схемы и обновлением seed data. SLO: < 24 часа.
- **Test Environment Recovery MTTR** — время восстановления тестового окружения. Target: < 15 минут.
- **Seed Data Coverage** — процент тестов, использующих версионированные seed data. SLO: 100%.

**Логирование:**
- Логируйте каждый запуск тестов: commit SHA, branch, author, timestamp, runner ID, test suite, результат.
- Архивируйте логи тестов в CI artifacts на 30–90 дней.
- Сохраняйте seed data checksum и версию схемы БД вместе с artifacts.
- Используйте structured logging (JSON) для корреляции с deployment events.

**Alerting:**
- Срабатывание при Build Success Rate < 95% за 1 час.
- Срабатывание при Build Duration > 20 минут.
- Срабатывание при Test Flake Rate > 2% за 24 часа.
- Срабатывание при Test Data Freshness > 24 часов.
- Срабатывание при Test Environment Recovery MTTR > 15 минут.
- Срабатывание при отсутствии seed data для нового релиза.

---

## Best Practices

### Безопасность

1. **Секреты в CI:** Никогда не храните секреты в коде. Используйте Variables в CI/CD или внешние менеджеры секретов (HashiCorp Vault).
2. **OIDC (OpenID Connect):** Используйте для динамической аутентификации без статических ключей. Это исключает утечку долгоживущих токенов.
3. **Ephemeral Runners:** Использование одноразовых виртуальных машин гарантирует, что секреты и «мусор» от предыдущих сборок не останутся на диске.
4. **Защита Keychain:** Используйте временные связки ключей (Ephemeral Keychain) и удаляйте их после сборки.
5. **Ротация ключей:** Регулярно обновляйте API-ключи и пароли (минимум 1 раз в квартал для test credentials, 1 раз в год для release).

### Производительность

1. **Параллелизация:** Запускайте линтинг, тесты и сборку параллельно (если это возможно).
2. **Кэширование:** Настройте кэширование зависимостей (SPM, Gradle, CocoaPods).
3. **Инкрементальные сборки:** Используйте инкрементальные билды для iOS.
4. **Очистка:** Удаляйте артефакты предыдущих сборок перед новой (особенно DerivedData для iOS).
5. **Мониторинг:** Отслеживайте время сборки и размер артефактов. Резкий рост может указывать на проблемы.

### Стабильность

1. **Фиксация версий:** Всегда фиксируйте версии инструментов (Xcode, Ruby, Fastlane, JDK).
2. **Retries:** Настройте автоматические повторные попытки для сетевых ошибок.
3. **Time limit:** Устанавливайте разумные таймауты для джобов (особенно для UI-тестов).
4. **Мониторинг зависимостей:** Отслеживайте уязвимости в зависимостях (Dependabot, Renovate).
5. **Rollback:** Имейте возможность быстрого отката к предыдущей стабильной версии.

### SRE: наблюдаемость и метрики

**Ключевые SLI для Mobile CI/CD:**

| SLI | Описание | Целевое значение |
|:---|:---|:---|
| **Build Success Rate** | Процент успешных сборок | > 95% |
| **Build Duration** | Среднее время сборки | < 15 минут |
| **PR Validation Time** | Время проверки PR | < 10 минут |
| **Flaky Test Rate** | Процент "мигающих" тестов | < 2% |
| **Time to First Install (TTFI)** | Время от merge до TestFlight | < 2 часа |
| **Release Frequency** | Частота релизов | > 1 раза в неделю |
| **Rollback Time** | Время отката | < 30 минут |

**Error Budget для пайплайна:** Договоритесь с командой о допустимом проценте проваленных сборок (например, 5% в месяц). При исчерпании бюджета фокус смещается на стабилизацию пайплайна, а не на новые фичи.

**MTTR (Mean Time To Repair):** Среднее время восстановления после инцидента пайплайна. Целевое значение: < 30 минут для blocking-инцидентов.

**Toil Reduction:** Автоматизируйте рутинные операции (обновление сертификатов, очистку кэша, ротацию логов). Измеряйте долю toil в работе команды.

**Flaky Test Management:** Ведите реестр «мигающих» тестов. Устанавливайте SLA на починку (например, 5 рабочих дней). Flaky-тесты подрывают доверие к пайплайну.

**Runbook'и:** Для каждого типичного сбоя (исчерпание лимитов Apple, падение Keychain, зависание симулятора) должно быть пошаговое руководство по восстановлению.

Внедрите базовый мониторинг для CI-инфраструктуры:

- **Prometheus + Grafana:** Сбор метрик с раннеров (CPU, RAM, disk, network) через `node_exporter`.
- **CI-специфичные метрики:** Длительность сборок, доля успешных джоб, время в очереди, размер артефактов.
- **Алерты:** Настройте оповещения при падении успешности сборок ниже порога (например, < 95% за 1 час) или превышении времени сборки (например, > 20 минут).

### Test Data Management

1. **Изоляция данных** — каждый тестовый запуск использует уникальный набор данных. Никакого разделения между параллельными тестами.
2. **Воспроизводимость** — seed data должны быть зафиксированы в CI артефактах. Не генерируйте случайные данные без фиксации seed.
3. **Скорость** — in-memory БД и моки быстрее реальных API. Используйте реальные данные только для критических E2E.
4. **Очистка** — всегда очищайте состояние после теста. Используйте `defer` / `finally` / `try-finally`.
5. **GDPR** — никогда не используйте реальные production данные в CI. Анонимизируйте или генерируйте синтетические данные.
6. **Seed versioning** — версионируйте seed data вместе с кодом. При изменении схемы БД обновляйте seed.
7. **Contract testing** — используйте Pact / WireMock для проверки контрактов между мобильным приложением и бэкендом.
8. **Test Data Freshness** — обновляйте seed data в течение 24 часов после изменения схемы. Устанавливайте SLO и мониторьте.
9. **Secrets Rotation** — ротируйте test credentials минимум раз в квартал. Автоматизируйте через pipeline.
10. **Audit Logging** — логируйте каждый запуск тестового окружения и доступ к seed data. Архивируйте логи на 30–90 дней.

---

## См. также

- **[Mobile Test Automation](./testing-mobile.md)** — XCUITest, Espresso, Appium, device farm, visual regression.
- **[Backend ↔ Mobile Integration](./backend-integration-mobile.md)** — API contracts, backward compatibility, schema migration, mock services.
- **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins и интеграция с iOS/Android пайплайнами.
