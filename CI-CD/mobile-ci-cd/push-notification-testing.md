# Push Notification Testing в Mobile CI/CD

**Актуально для:** iOS 17–27 / iPadOS 17–27 / macOS 15+, Android API 24–35, Xcode 16–26, Gradle 8.x

---

## Определения

**Push Notification** — уведомление, отправляемое сервером на мобильное устройство через APNS (iOS) или FCM (Android).

**APNS (Apple Push Notification Service)** — сервис push-уведомлений Apple.

**FCM (Firebase Cloud Messaging)** — сервис push-уведомлений Google для Android.

**Device Token** — уникальный идентификатор устройства для доставки push.

**Push Certificate** — сертификат для авторизации на APNS.

**FCM Service Account** — учетные данные для авторизации на FCM.

**Push Payload** — содержимое push-уведомления (`aps` для iOS, `data`/`notification` для FCM).

**Silent Push** — push-уведомление без пользовательского интерфейса.

**Push-to-Kill** — механизм удаленного управления через push.

**Push Notification MTTR** — среднее время от обнаружения неработающего push pipeline до фикса или отката конфигурации.

**Push Delivery SLO** — целевой процент успешно доставленных push-уведомлений в production (например, > 99.5%).

**Push Test Flake** — недетерминированный провал push-теста в CI, возникающий периодически без изменений в коде или конфигурации.

**Push Token Rotation** — периодическая смена device tokens из-за переустановки приложения, очистки данных или истечения срока действия.

**Device Farm (self-hosted)** — инфраструктура физических устройств, размещенная on-premises, используемая для запуска тестов push в условиях, приближенных к production.

**Push Payload Drift** — неконтролируемое изменение структуры push payload между версиями приложения и бэкенда.

---

## Базовые концепции

### Архитектура push-уведомлений

```
Client App → APNS/FCM → устройство
```

APNS и FCM — точки доставки. Ваше приложение регистрирует токен, передает его на бэкенд, и бэкенд отправляет уведомление через эти сервисы.

### Типы push

| Тип | iOS | Android | Использование |
|-----|-----|---------|---------------|
| Notification | `aps.alert` | `notification` | UI-уведомление |
| Data | `aps.content-available` | `data` | Фоновая обработка |
| Silent | `aps.content-available: 1`, без `alert` | `data` только | Обновление данных без UI |
| Mixed | `aps.alert` + `aps.content-available` | `notification` + `data` | UI + фон |

### Lifecycle push в CI/CD

Тестирование доставки должно быть автоматизировано:
1. Сборка приложения с поддержкой push
2. Установка на устройство/эмулятор
3. Регистрация device token
4. Отправка тестового push из CI
5. Верификация доставки в приложении
6. Очистка токенов

### Ограничения testing

- **Эмуляторы iOS**: не поддерживают реальный APNS. Используйте mock-серверы или реальные устройства.
- **Эмуляторы Android**: поддерживают FCM через Google Play Services.
- **Self-hosted Device Farm**: для production-grade тестов требуются реальные устройства, размещенные on-premises.

### Sandbox vs Production

| Среда | APNS | FCM | Использование |
|-------|------|-----|---------------|
| Sandbox | `api.sandbox.push.apple.com` | Отдельный project identifier | Разработка, CI |
| Production | `api.push.apple.com` | Отдельный project identifier | Релизы, App Store |

### SRE-подход к Push Notifications

**Принципы:**

- **Push Notification MTTR:** Измеряйте время от обнаружения падения push pipeline до фикса. Target: < 30 минут для blocking-инцидентов.
- **Push Delivery SLO:** Договоритесь о целевом проценте доставки (например, > 99.5%). При падении ниже SLO — фокус на стабилизацию инфраструктуры.
- **Toil Reduction:** Автоматизируйте генерацию mock-токенов, ротацию device tokens, проверку payload. Ручная отправка тестовых push — это toil.
- **Observability:** Каждый push failure должен иметь полный trace: device token registration → push sent → delivery confirmation → app received.
- **Push Test Flake Management:** Ведите реестр flaky push-тестов. Устанавливайте SLA на починку (например, 5 рабочих дней).

### Sysadmin: управление инфраструктурой push testing

- **Self-hosted Device Farm:** Для production-релизов требуются физические устройства. On-premises ферма требует управления актуальностью ОС, provisioning, cable connectivity.
- **Runner requirements:** CI-раннеры для push тестов должны иметь доступ к real device farm или эмуляторам с настроенным Google Play Services.
- **Network egress:** Убедитесь что раннеры имеют доступ к APNS и FCM endpoints. В air-gapped окружениях push testing невозможен.
- **Retention:** Храните push test logs, device token rotation history, mock payload templates минимум 90 дней.
- **Secrets management:** APNS certificates и FCM service account credentials должны храниться в vault, не в CI variables. Ротация: APNS certificates — 1 год, FCM keys — 90 дней.

---

## Практические сценарии

### 1. Эмуляция APNS в CI

Используйте [Pusher](https://github.com/noodlewerk/NWPusher) или собственный mock-сервер.

```swift
// PushReceiver.swift — прием push в приложении для тестов
import UserNotifications

class PushTestReceiver: NSObject, UNUserNotificationCenterDelegate {
    static var lastPayload: [AnyHashable: Any]?
    
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse) {
        PushTestReceiver.lastPayload = response.notification.request.content.userInfo
    }
}
```

```ruby
# Fastfile — отправка тестового push
lane :test_push do
  # Получаем device token из последнего запуска
  token = lane_context[SharedValues::DEVICE_TOKEN]
  
  # Отправляем push через APNS
  apns(
    device_token: token,
    payload: {
      aps: {
        alert: "CI Test Push",
        sound: "default",
        badge: 1
      }
    },
    environment: "sandbox"
  )
end
```

### 2. Эмуляция FCM в CI

```kotlin
// FirebaseMessagingService.kt — обработка push для тестов
class TestFirebaseMessagingService : FirebaseMessagingService() {
    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        // Сохраняем payload для assertions
        TestPushCollector.lastPayload = remoteMessage.data
    }
}
```

```yaml
# .gitlab-ci.yml — тест push на self-hosted device farm
push_test:
  stage: test
  image: openjdk:17-jdk
  script:
    - ./gradlew assembleDebug assembleAndroidTest
    - ./gradlew connectedAndroidTest \
        -Pandroid.testInstrumentationRunnerArguments.class=com.company.app.PushTest
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### 3. Automated push testing

```ruby
# Fastfile — полный цикл push-тестирования
lane :push_integration_test do
  # Собираем и устанавливаем приложение
  build_app(scheme: "MyApp", configuration: "Debug")
  install_app(path: "build/MyApp.ipa")
  
  # Запускаем приложение и получаем device token
  run_tests(
    scheme: "MyApp",
    destination: "platform=iOS Simulator,name=iPhone 15"
  )
  
  token = get_device_token
  
  # Отправляем различные типы push
  push_scenarios = [
    { name: "alert", payload: { aps: { alert: "Test" } } },
    { name: "silent", payload: { aps: { "content-available": 1 } } },
    { name: "mixed", payload: { aps: { alert: "Test", "content-available": 1 } } }
  ]
  
  push_scenarios.each do |scenario|
    result = apns(
      device_token: token,
      payload: scenario[:payload],
      environment: "sandbox"
    )
    
    # Проверяем доставку
    sh "./scripts/verify_push_delivery.rb #{scenario[:name]}"
  end
end
```

### 4. Device token management в CI

```ruby
# fastlane/actions/register_device_token.rb
register_device_token(
  app_identifier: "com.example.myapp",
  user: "ci-bot",
  output_path: "tmp/device_token.txt"
)
```

```ruby
# Очистка токенов после тестов
lane :cleanup_push_tokens do
  # Удаляем тестовые токены из бэкенда
  sh "curl -X DELETE #{ENV['BACKEND_URL']}/api/test-tokens"
  
  # Удаляем файл с токеном
  sh "rm -f tmp/device_token.txt"
end
```

### 5. Push notification regression testing

```ruby
# scripts/verify_push_payload.rb
require 'json'

def verify_push_payload(payload_file, expected_keys)
  payload = JSON.parse(File.read(payload_file))
  
  expected_keys.each do |key|
    unless payload.key?(key)
      abort "Push payload missing required key: #{key}"
    end
  end
  
  # Проверяем размер payload (APNS limit: 4096 bytes)
  payload_size = File.size(payload_file)
  if payload_size > 4096
    abort "Push payload too large: #{payload_size} bytes (max 4096)"
  end
end

# Использование
verify_push_payload("tmp/last_push.json", ["aps", "aps.alert", "aps.sound"])
```

```kotlin
// PushPayloadValidator.kt
object PushPayloadValidator {
    fun validate(payload: Map<String, Any>): ValidationResult {
        val errors = mutableListOf<String>()
        
        // Проверяем обязательные поля
        if (!payload.containsKey("aps")) {
            errors.add("Missing 'aps' key")
        }
        
        // Проверяем размер
        val size = payload.toJson().toByteArray().size
        if (size > 4096) {
            errors.add("Payload too large: $size bytes")
        }
        
        return ValidationResult(errors.isEmpty(), errors)
    }
}
```

### 6. End-to-end testing

```yaml
# .gitlab-ci.yml — полный E2E цикл
stages:
  - build
  - deploy
  - test_push
  - cleanup

build_ios:
  stage: build
  script:
    - fastlane build_for_test

deploy_to_device:
  stage: deploy
  script:
    - fastlane install_on_device
  environment:
    name: push-test

send_and_verify_push:
  stage: test_push
  script:
    - fastlane test_push
    - ./scripts/verify_push_delivery.rb
  dependencies:
    - deploy_to_device

cleanup:
  stage: cleanup
  script:
    - fastlane cleanup_push_tokens
  when: always
```

```ruby
# scripts/verify_push_delivery.rb
#!/usr/bin/env ruby
require 'json'
require 'timeout'

TIMEOUT = 30 # секунд на доставку

def wait_for_push(scenario_name)
  start_time = Time.now
  
  loop do
    elapsed = Time.now - start_time
    raise "Push delivery timeout after #{elapsed}s" if elapsed > TIMEOUT
    
    # Проверяем, что приложение получило push
    result = `xcrun simctl spawn booted defaults read com.example.myapp LastPushReceived`
    break if result.strip == scenario_name
    
    sleep 1
  end
  
  puts "Push '#{scenario_name}' delivered successfully"
end

wait_for_push(ARGV[0] || "alert")
```

---

## Операции и команды

### Верификация окружения и инструментов

| Команда | Назначение | Ожидаемый результат |
|---|---|---|
| `xcrun simctl list devices` | Доступные симуляторы | Перечень устройств с статусом `Booted`/`Shutdown` |
| `adb devices` | Подключенные Android-устройства | Список device IDs с статусом `device` |
| `security find-identity -p codesigning` | Список сертификатов APNS | Строки вида `1) XXXXXXXX "Apple Distribution: ..."` |
| `xcodebuild -showBuildSettings -scheme App` | Проверка entitlements | `CODE_SIGNING_ALLOWED = YES` |
| `openssl s_client -connect api.push.apple.com:443` | Проверка доступности APNS endpoint | TLS handshake successful |
| `curl -v https://fcm.googleapis.com/v1/projects/my-project/messages:send` | Проверка доступности FCM endpoint | HTTP 401 (ожидаемо без токена) |

### Управление mock-сервером APNS

```bash
# Установка NWPusher (self-hosted mock APNS)
brew install noodlewerk/nwpusher/nwpusher

# Запуск mock-сервера
nwpulsar -port 2195 -cert /path/to/cert.pem -key /path/to/key.pem
# → Mock APNS server running on port 2195

# Отправка тестового push через mock
nwpush --to <device-token> --payload '{"aps":{"alert":"Test"}}' --cert /path/to/cert.pem
```

### Управление payload

```bash
# Валидация payload размера
echo '{"aps":{"alert":"Test","sound":"default"}}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Size: {len(json.dumps(d))} bytes')"
# → Size: XX bytes (max 4096)

# Проверка обязательных полей
python3 scripts/verify_push_payload.py tmp/last_push.json aps alert sound
```

### Очистка окружения push testing

```bash
# Очистка temporary keychain после тестов с APNS
security delete-keychain "push_test.keychain"

# Очистка device tokens из CI workspace
rm -f tmp/device_token.txt
rm -f tmp/last_push.json

# Очистка mock-артефактов
rm -rf build/PushTest/
```

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
|---|---|---|---|
| `Device token invalid` | Токен истек, переустановлено приложение, очищены данные | Проверить регистрацию токена на бэкенде | Перерегистрировать токен, обновить на сервере |
| `APNS certificate expired` | Сертификат APNS истек (1 год) | `security find-certificate -p -c "Apple Push"` | Обновить сертификат в Apple Developer Portal, перевыпустить provisioning profile |
| `Sandbox/Production mismatch` | Токен из sandbox отправлен на production endpoint | Проверить environment в коде и на бэкенде | Использовать соответствующие эндпоинты: `api.sandbox.push.apple.com` vs `api.push.apple.com` |
| `Payload too large` | Размер payload превышает лимит APNS (4096 bytes) | Проверить размер JSON payload | Сократить payload, использовать `content-available` для data-only push |
| `No such device token` | Токен удален из APNS/FCM, устройство сброшено | Обработать ошибку в коде, обновить токен | Реализовать token refresh logic, удалить невалидные токены |
| `Push not received on simulator` | Симулятор iOS не поддерживает APNS | Проверить тип устройства | Использовать mock-сервер (NWPusher) или реальное устройство |
| `FCM registration failed` | Google Play Services устарел или отсутствует | `adb shell dumpsys package com.google.android.gms \| grep versionName` | Обновить Google Play Services, использовать mock FCM в CI |
| `Notification permission denied` | Пользователь отклонил permission, приложение не запросило заново | Проверить `UNUserNotificationCenter` status | Запросить permission заново, обработать `denied` status gracefully |
| `Push Payload Drift` | Структура payload изменилась без обновления тестов | Сравнить текущий payload с эталоном | Версионировать payload schema, обновить тесты |
| `Push Test Flake в CI` | Нестабильный network к APNS/FCM, race condition в тесте | Перезапуск: `./gradlew connectedAndroidTest --rerun-tasks` | Изолировать тест, добавить quarantine для flaky runs |
| `Token rotation storm` | Массовая перерегистрация токенов после обновления приложения | Мониторинг регистраций в логах | Использовать exponential backoff, batch updates |
| `Mock server not responding` | NWPusher упал, порт занят | `lsof -i :2195` | Перезапустить mock-сервер, проверить certificate files |
| `Background push not delivered` | iOS ограничивает silent push, приложение в suspended state | Проверить `content-available` и background mode | Добавить `remote-notification` в UIBackgroundModes, использовать push notification service extension |
| `Push delivery timeout` | Network latency, APNS/FCM overloaded | Проверить network connectivity, APNS/FCM status | Увеличить timeout, добавить retry logic |

---

## Наблюдаемость пайплайна

**Метрики:**
- **Push Delivery Rate** — процент успешно доставленных push в production. SLO: > 99.5%.
- **Push Latency P95** — 95-й перцентиль времени от отправки до доставки. SLO: < 5 секунд.
- **Push Notification MTTR** — время от падения push pipeline до фикса. Target: < 30 минут.
- **Push Test Pass Rate** — процент успешных push-тестов в CI. SLO: > 98%.
- **Push Test Flake Rate** — процент недетерминированных падений push-тестов. Target: < 1%.
- **Device Token Refresh Rate** — частота обновления токенов. Spike может указывать на проблему с регистрацией.
- **Mock Usage Rate (CI)** — процент CI-сборок использующих mock push. Target: 100% для non-production.

**Логирование:**
- Логируйте device token registration/refresh events с контекстом (app version, OS version, device model).
- Архивируйте push payloads и delivery confirmations для каждого тестового запуска.
- Сохраняйте mock server logs и FCM/APNS response codes как артефакты.
- Не логируйте полные device tokens в production — используйте truncated/hashed версии.

**Alerting:**
- Срабатывание при падении Push Delivery Rate ниже 99.5%.
- Срабатывание при Push Latency P95 выше 5 секунд.
- Срабатывание при отсутствии self-hosted device farm availability для production-сборок.
- Срабатывание при исчерпании Push Error Budget.
- Срабатывание при Push Test Flake Rate выше 1%.
- Срабатывание при массовой токен-ротации (spike > 3σ от среднего).

---

## Best Practices

- Используйте separate APNS environments для sandbox и production. Никогда не смешивайте токены между окружениями.
- Для Apple App Attest всегда проверяйте `DCAppAttestService.shared.isSupported` перед использованием. Обрабатывайте `false` как fraud signal.
- Генерируйте nonce длиной 32 байта через криптографически стойкий PRNG (`SecRandomCopyBytes` на iOS, `SecureRandom` на Android).
- Никогда не передавайте push payload через URL parameters — используйте POST body с TLS 1.3.
- В CI всегда используйте mock APNS/FCM. Real push в CI возможен только при наличии outbound connectivity к Apple/Google API и реальных устройств.
- Для production release используйте self-hosted device farm — эмуляторы не покрывают real push delivery.
- Изолируйте push логику в отдельный модуль/сервис. Это упрощает mocking и тестирование.
- Реализуйте exponential backoff для retry логики при ошибках доставки.
- Ротация APNS certificates: 1 год. Ротация FCM service account keys: 90 дней.
- Логируйте все push failures с контекстом (device model, OS version, app version, error code) для forensic analysis.
- Настройте quarantine для flaky push-тестов: автоматический quarantine при 2 последовательных падениях.
- Используйте build variants/flavors для разделения production и mock push кода.
- Архивируйте Build Evidence (Push): логи, артефакты, mock responses, token rotation history минимум 90 дней.
- Реализуйте graceful degradation: если push недоступен, приложение должно работать в offline mode с periodic sync.

---

## См. также

- [testing-mobile.md](./testing-mobile.md) — XCUITest, Espresso, Appium, self-hosted device farm management
- [ios-ci-cd.md](./ios-ci-cd.md) — APNS certificates, provisioning profiles, Keychain management
- [backend-integration-mobile.md](./backend-integration-mobile.md) — API contracts, mock services, backward compatibility
