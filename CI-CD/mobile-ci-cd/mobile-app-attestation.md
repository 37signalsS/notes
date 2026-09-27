# Mobile App Attestation в CI/CD

**Актуально для:** Android API 23+, iOS 16–27, watchOS 9+, macOS 15+

---

## Определения

**Mobile App Attestation** — механизм подтверждения, что запросы приходят от легитимного, неповрежденного приложения.

**Google Play Integrity** — сервис Google для проверки целостности Android-приложения.

**Apple App Attest** — сервис Apple для проверки целостности iOS-приложения.

**Device Integrity** — уровень целостности устройства (чистый/модифицированный).

**Jailbreak/Root Detection** — обнаружение модифицированных устройств.

**Anti-Tampering** — защита от reverse engineering и модификации кода.

**SafetyNet Attestation** — устаревший API Google, заменен на Play Integrity.

**DeviceCheck** — сервис Apple для проверки устройства.

**Attestation MTTR** — среднее время от обнаружения неработающего attestation pipeline до фикса или отката конфигурации.

**Attestation Error Budget** — допустимый процент проваленных attestation checks в месячном окне, при исчерпании которого фокус смещается на стабилизацию, а не на новые фичи.

**Build Evidence (Attestation)** — артефакты CI-сборок attestation: mock responses, логи валидации, отчеты о провалах, nonce rotation logs.

**Attestation Flake** — недетерминированный провал attestation в CI, возникающий периодически без изменений в коде или конфигурации.

**Real Device Farm** — инфраструктура физических устройств, размещенная on-premises или в rented дата-центре, используемая для запуска тестов attestation в условиях, приближенных к production.

---

## Базовые концепции

### Зачем нужна attestation

Attestation решает несколько проблем:

- **Боты и автоматизация** — предотвращает автоматизированные атаки на API
- **Эмуляторы и симуляторы** — блокирует запросы с виртуальных устройств
- **Модифицированные приложения** — обнаруживает патченные/взломанные сборки
- **Повторное использование артефактов** — защищает от переиспользования старых APK/IPA
- **Man-in-the-middle** — делает сложнее перехват и модификация трафика

### Архитектура Play Integrity

```
Client App → Play Integrity API → Google возвращает signed JWT token
    ↓
Backend валидирует token через Google API
    ↓
Решение: allow / deny / warn
```

Play Integrity возвращает три основных поля:
- `integrity verdict` — MEETS_BASIC, MEETS_STRONG, MEETS_DEVICE_INTEGRITY
- `device integrity` — MEETS_DEVICE_INTEGRITY, MEETS_STRONG_INTEGRITY, MEETS_BASIC_INTEGRITY
- `account details` — статус лицензии приложения

### Архитектура App Attest (Apple)

```
Device → App Attest Service → Apple возвращает signed attestation object
    ↓
Backend валидирует через Apple API
    ↓
Создается device-bound key для последующих запросов
```

Apple App Attest использует ключевую пару, привязанную к устройству. Attestation object проверяется на сервере с помощью публичного ключа Apple.

### Интеграция в CI/CD

Основная сложность: эмуляторы/симуляторы по определению имеют низкий integrity level.

**Стратегии тестирования:**

1. **Mock Attestation Response** — в CI возвращаем предсказуемый результат
2. **Test Environment Mode** — отдельный конфиг, пропускающий attestation для dev-сборок
3. **Real Device Farm** — on-premises или rented ферма реальных устройств для production-grade тестов
4. **Gradle/Xcodebuild Flags** — флаги для принудительного успешного attestation в тестах

### Nonce Generation для тестирования

Nonce должен быть:
- Уникальным для каждой проверки
- Случайным (минимум 16 байт)
- Проверяемым на бэкенде (чтобы предотвратить replay attacks)
- Срок действия ограничен (например, 5 минут)

### Test Environments vs Production

| Environment | Integrity Required | Attestation Check | Fallback |
|-------------|-------------------|-------------------|----------|
| Production | MEETS_DEVICE_INTEGRITY | Strict | Block |
| Staging | MEETS_BASIC_INTEGRITY | Lenient | Warn |
| CI/CD | None | Mock/Skip | Skip |
| Development | None | Disabled | Skip |

### SRE-подход к Mobile App Attestation

**Принципы:**

- **Attestation MTTR:** Измеряйте время от обнаружения падения attestation pipeline до фикса. Target: < 30 минут для blocking-инцидентов.
- **Attestation Error Budget:** Договоритесь о допустимом проценте проваленных attestation checks в месяц. При исчерпании — фокус на стабилизацию пайплайна.
- **Toil Reduction:** Автоматизируйте генерацию mock-токенов, ротацию nonce, проверку подписей. Ручная валидация каждого attestation object — это toil.
- **Observability:** Каждый attestation failure должен иметь полный trace: client request → token received → backend validation → allow/deny/warn.
- **On-call Rotation:** Attestation alerts должны приходить дежурному инженеру, а не в общий канал.

### Sysadmin: управление инфраструктурой attestation

- **Real Device Farm:** Для production-релизов требуются физические устройства. On-premises ферма требует управления актуальностью ОС, provisioning, cable connectivity.
- **Runner requirements:** CI-раннеры для attestation тестов должны иметь доступ к real device farm или эмуляторам с настроенным Google Play Services.
- **Network egress:** Убедитесь что раннеры имеют доступ к Play Integrity API и Apple App Attest endpoints. В air-gapped окружениях attestation невозможен.
- **Retention:** Храните attestation logs, nonce rotation history, mock response templates минимум 90 дней.
- **Secrets management:** API ключи для backend validation должны храниться в vault, не в CI variables. Ротация: 90 дней.

---

## Практические сценарии

### 1. Google Play Integrity в CI/CD

**Android-side (Kotlin):**

```kotlin
// integrity-check.kt
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.IntegrityTokenRequest

class IntegrityChecker(private val context: Context) {
    private val integrityManager = IntegrityManagerFactory.create(context)

    suspend fun requestIntegrityToken(nonce: ByteArray): String? {
        return try {
            val tokenResponse = integrityManager
                .requestIntegrityToken(IntegrityTokenRequest.builder()
                    .setNonce(nonce)
                    .build())
                .await()

            tokenResponse.token()
        } catch (e: Exception) {
            null
        }
    }
}
```

**Backend validation (Node.js):**

```javascript
// integrity-validator.js
const { GoogleAuth } = require('google-auth-library');
const jwt = require('jsonwebtoken');

async function validateIntegrityToken(token) {
    try {
        // Verify token locally (public key from Google)
        const decoded = jwt.decode(token, { complete: true });
        const publicKey = getGooglePublicKey(decoded.header.kid);
        
        const verified = jwt.verify(token, publicKey, {
            algorithms: ['RS256']
        });

        const verdict = verified?.playIntegrity?.appIntegrity?.appRecognitionVerdict;
        const deviceIntegrity = verified?.playIntegrity?.deviceIntegrity?.deviceRecognitionVerdict;

        return {
            valid: true,
            verdict: verdict,
            deviceIntegrity: deviceIntegrity,
            allowed: deviceIntegrity?.includes('MEETS_DEVICE_INTEGRITY')
        };
    } catch (error) {
        return { valid: false, error: error.message };
    }
}
```

**GitLab CI job:**

```yaml
# .gitlab-ci.yml
stages:
  - test
  - attestation-test

play_integrity_test:
  stage: test
  image: openjdk:17-jdk-slim
  script:
    - ./gradlew testDebugUnitTest
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

integrity_emulator_test:
  stage: attestation-test
  image: openjdk:17-jdk-slim
  variables:
    BUILD_TYPE: "debug"
    INTEGRITY_MODE: "mock"  # mock | skip | real
  script:
    - echo "Running with integrity mode: $INTEGRITY_MODE"
    - ./gradlew connectedAndroidTest -PintegrityMode=$INTEGRITY_MODE
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### 2. Apple App Attest в CI/CD

**iOS-side (Swift):**

```swift
// AppAttestManager.swift
import DeviceCheck

class AppAttestManager {
    private let appAttestService = DCAppAttestService.shared

    func attestDevice(keyId: String) async throws -> Data? {
        guard appAttestService.isSupported else {
            throw AppAttestError.notSupported
        }

        do {
            let attestationObject = try await appAttestService.attestKey(keyId, clientDataHash: generateNonce())
            return attestationObject
        } catch {
            throw AppAttestError.attestationFailed(error)
        }
    }

    private func generateNonce() -> Data {
        var nonce = Data(count: 32)
        _ = nonce.withUnsafeMutableBytes { bytes in
            SecRandomCopyBytes(kSecRandomDefault, 32, bytes.baseAddress!)
        }
        return nonce
    }
}
```

**Backend validation (Python/Flask):**

```python
# app_attest_validator.py
import jwt
import requests
from flask import Flask, request

app = Flask(__name__)

APPLE_PUBLIC_KEYS_URL = "https://apple.com/-/apple/application/keys"

@app.route('/validate-attestation', methods=['POST'])
def validate_attestation():
    data = request.json
    attestation_object = data.get('attestationObject')
    key_id = data.get('keyId')

    try:
        # Fetch Apple public keys
        keys = requests.get(APPLE_PUBLIC_KEYS_URL).json()['keys']
        
        # Validate JWT
        decoded = jwt.decode(
            attestation_object,
            options={'verify_signature': False}
        )
        
        return {
            'valid': True,
            'keyId': decoded.get('keyId'),
            'environment': decoded.get('environment')
        }
    except Exception as e:
        return {'valid': False, 'error': str(e)}
```

**GitLab CI job:**

```yaml
app_attest_test:
  stage: attestation-test
  image: swift:5.9
  variables:
    SIMULATOR_ATTESTATION: "true"  # Enable mock for simulator
  script:
    - xcodebuild test \
        -workspace App.xcworkspace \
        -scheme App \
        -destination 'platform=iOS Simulator,name=iPhone 15' \
        -resultBundlePath TestResults
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### 3. Jailbreak/Root Detection

**Android detection (Kotlin):**

```kotlin
object SecurityChecker {
    fun isDeviceCompromised(context: Context): Boolean {
        return isRooted() || isEmulator() || hasDebuggableFlag(context)
    }

    private fun isRooted(): Boolean {
        val paths = arrayOf(
            "/system/app/Superuser.apk",
            "/sbin/su",
            "/system/bin/su",
            "/system/xbin/su",
            "/data/local/xbin/su",
            "/data/local/bin/su",
            "/system/sd/xbin/su",
            "/system/bin/failsafe/su",
            "/data/local/su"
        )
        return paths.any { File(it).exists() }
    }

    private fun isEmulator(): Boolean {
        return ((Build.BRAND.startsWith("generic") && Build.DEVICE.startsWith("generic"))
            || Build.FINGERPRINT.startsWith("generic")
            || Build.FINGERPRINT.startsWith("unknown"))
    }

    private fun hasDebuggableFlag(context: Context): Boolean {
        return (context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
    }
}
```

**iOS detection (Swift):**

```swift
import UIKit

class JailbreakDetector {
    func isJailbroken() -> Bool {
        return checkSuspiciousPaths() || checkCydiaURL() || checkForkStatus()
    }

    private func checkSuspiciousPaths() -> Bool {
        let paths = [
            "/Applications/Cydia.app",
            "/Library/MobileSubstrate/MobileSubstrate.dylib",
            "/bin/bash",
            "/usr/sbin/sshd"
        ]
        return paths.contains { FileManager.default.fileExists(atPath: $0) }
    }

    private func checkCydiaURL() -> Bool {
        return UIApplication.shared.canOpenURL(URL(string: "cydia://")!)
    }
}
```

**Server-side validation:**

```javascript
// server-side checks
app.post('/api/validate-request', (req, res) => {
    const { attestationToken, deviceFingerprint } = req.body;
    
    const validation = validateIntegrityToken(attestationToken);
    
    // Additional server-side checks
    const checks = {
        tokenValid: validation.valid,
        deviceKnown: isKnownDevice(deviceFingerprint),
        requestFrequency: checkRateLimit(req.ip),
        geoAnomaly: checkGeoAnomaly(req.ip, deviceFingerprint)
    };

    const riskScore = calculateRiskScore(checks);
    
    if (riskScore > RISK_THRESHOLD) {
        return res.status(403).json({ error: 'Device not trusted' });
    }

    res.json({ allowed: true });
});
```

### 4. Интеграция с Fastlane

**Custom Fastlane action для Android:**

```ruby
# fastlane/actions/check_play_integrity.rb
module Fastlane
  module Actions
    class CheckPlayIntegrityAction < Action
      def self.run(params)
        require 'net/http'
        require 'json'

        token = params[:integrity_token]
        api_key = params[:google_api_key]

        uri = URI("https://playintegrity.googleapis.com/v1/#{params[:package_name]}:decodeIntegrityToken")
        req = Net::HTTP::Post.new(uri)
        req['Authorization'] = "Bearer #{api_key}"
        req.body = { token: token }.to_json

        response = Net::HTTP.start(uri.hostname, uri.port, use_ssl: true) do |http|
          http.request(req)
        end

        result = JSON.parse(response.body)
        
        UI.user_error!("Integrity check failed") unless result['tokenPayloadExternal']['integrityVerdict']
        
        UI.success("Integrity check passed")
        result
      end

      def self.description
        "Validates Play Integrity token"
      end

      def self.available_options
        [
          FastlaneCore::ConfigItem.new(key: :integrity_token, type: String),
          FastlaneCore::ConfigItem.new(key: :google_api_key, type: String),
          FastlaneCore::ConfigItem.new(key: :package_name, type: String)
        ]
      end
    end
  end
end
```

**Fastlane lane:**

```ruby
# Fastfile
lane :integrity_check do
  if ENV['CI'] == 'true'
    # CI: skip actual check or use mock
    UI.message("CI environment: skipping integrity check")
  else
    # Production/staging: real check
    check_play_integrity(
      integrity_token: get_latest_token,
      google_api_key: ENV['GOOGLE_API_KEY'],
      package_name: "com.example.app"
    )
  end
end
```

### 5. Testing Strategies

**Mock testing approach:**

```kotlin
// Test-only implementation
class MockIntegrityChecker : IntegrityChecker {
    override suspend fun requestIntegrityToken(nonce: ByteArray): String? {
        return when (BuildConfig.FLAVOR) {
            "mockIntegrity" -> createMockToken(nonce, "MEETS_DEVICE_INTEGRITY")
            "mockTampered" -> createMockToken(nonce, "MEETS_BASIC_INTEGRITY")
            else -> null
        }
    }

    private fun createMockToken(nonce: ByteArray, verdict: String): String {
        return Base64.encodeToString(
            createMockJwt(nonce, verdict),
            Base64.NO_WRAP
        )
    }
}
```

**Gradle build variant configuration:**

```groovy
android {
    buildTypes {
        debug {
            buildConfigField "boolean", "INTEGRITY_ENABLED", "false"
        }
        release {
            buildConfigField "boolean", "INTEGRITY_ENABLED", "true"
            minifyEnabled true
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
        }
    }

    flavorDimensions "integrity"
    productFlavors {
        mockIntegrity {
            dimension "integrity"
            buildConfigField "boolean", "USE_MOCK_INTEGRITY", "true"
        }
        production {
            dimension "integrity"
            buildConfigField "boolean", "USE_MOCK_INTEGRITY", "false"
        }
    }
}
```

### 6. Fallback Strategies

```kotlin
class AttestationManager(
    private val integrityChecker: IntegrityChecker,
    private val fallbackPolicy: FallbackPolicy
) {
    suspend fun verifyRequest(request: ApiRequest): VerificationResult {
        if (!fallbackPolicy.isAttestationRequired()) {
            return VerificationResult.Allowed("Attestation disabled")
        }

        val token = integrityChecker.requestIntegrityToken(generateNonce())
        
        return when {
            token == null -> handleAttestationUnavailable()
            !validateToken(token) -> VerificationResult.Denied("Invalid token")
            else -> VerificationResult.Allowed("Token valid")
        }
    }

    private fun handleAttestationUnavailable(): VerificationResult {
        return when (fallbackPolicy.mode) {
            FallbackMode.STRICT -> VerificationResult.Denied("Attestation required")
            FallbackMode.LENIENT -> VerificationResult.Warn("Attestation unavailable")
            FallbackMode.SKIP -> VerificationResult.Allowed("Attestation skipped")
        }
    }
}

enum class FallbackMode {
    STRICT,   // Block requests when attestation fails
    LENIENT,  // Allow but log warning
    SKIP      // Completely skip attestation
}

class FallbackPolicy(private val environment: Environment) {
    fun isAttestationRequired(): Boolean {
        return when (environment) {
            Environment.PRODUCTION -> true
            Environment.STAGING -> true
            Environment.DEVELOPMENT -> false
            Environment.CI -> false
        }
    }
}
```

---

## Операции и команды

### Верификация окружения и API доступности

| Команда | Назначение | Ожидаемый результат |
|---|---|---|
| `adb shell dumpsys package com.google.android.gms \| grep versionName` | Проверка версии Google Play Services | Версия ≥ 21.0.0 для Play Integrity |
| `xcrun simctl list devices` | Доступные симуляторы | Перечень устройств с статусом `Booted`/`Shutdown` |
| `security find-identity -p codesigning` | Список сертификатов в Keychain | Строки вида `1) XXXXXXXX "Apple Distribution: ..."` |
| `xcodebuild -showBuildSettings -scheme App` | Проверка entitlements App Attest | `CODE_SIGNING_ALLOWED = YES` |
| `./gradlew connectedAndroidTest -PintegrityMode=mock` | Запуск тестов с mock integrity | Сборка проходит без обращения к Google API |

### Валидация attestation artifacts

```bash
#!/bin/bash
# validate_attestation_artifacts.sh

set -e

echo "=== Проверка Play Integrity mock responses ==="
if [ -d "app/build/reports/attestation" ]; then
  echo "✓ Attestation reports found"
  ls -la app/build/reports/attestation/
else
  echo "⚠ No attestation reports (expected for mock mode)"
fi

echo "=== Проверка App Attest entitlements ==="
plutil -p MyApp.app/Entitlements.plist | grep -A5 "com.apple.developer.devicecheck.appattest-environment"
# → "com.apple.developer.devicecheck.appattest-environment" => "sandbox" или "production"

echo "=== Проверка embedded App Groups ==="
plutil -p MyApp.app/Entitlements.plist | grep application-groups
# → "com.apple.security.application-groups" => { "group.com.company.app" }

echo "=== Все проверки пройдены ==="
```

### Управление nonce в CI

```bash
# Генерация nonce для CI
python3 -c "import secrets; print(secrets.token_hex(32))"
# → 64 hex characters (32 bytes)

# Проверка freshness nonce (must be < 5 minutes old)
find . -name "nonce_*.bin" -mmin +5 -delete
```

### Очистка окружения attestation

```bash
# Очистка temporary keychain после тестов с App Attest
security delete-keychain "attestation_test.keychain"

# Очистка mock attestation artifacts
rm -rf app/build/reports/attestation/
rm -rf build/AttestationTest/
```

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
|---|---|---|---|
| `INTEGRITY_API_NOT_AVAILABLE` | Google Play Services устарел или отсутствует | `adb shell pm list packages \| grep com.google.android.gms` | Обновить Play Services, использовать `StandardIntegrityManager` с warm-up |
| `STANDARD_INTEGRITY_INITIALIZATION_NEEDED` | Требуется вызов `prepareIntegrityToken` перед запросом | Проверить что `prepareIntegrityToken` вызван с `requestHash` | Добавить warm-up вызов при старте приложения |
| `NONCE_TOO_SHORT` / `NONCE_TOO_LONG` | Nonce вне допустимого диапазона | Проверить длину nonce в логах | Nonce должен быть 16–64 байта |
| `APP_UID_MISMATCH` | Приложение подписано другим сертификатом чем в Play Store | Проверить signing certificate | Переподписать приложение правильным сертификатом |
| `TOO_MANY_REQUESTS` | Превышен rate limit Google API | Проверить частоту запросов | Реализовать exponential backoff, кэшировать токены |
| `DCError.serverUnavailable` | Apple App Attest service недоступен | Проверить сеть, повторить запрос | Retry с тем же nonce и keyId, не генерировать новый ключ |
| `App Attest not supported` | Устройство или extension не поддерживает App Attest | Проверить `DCAppAttestService.shared.isSupported` | Обработать gracefully, использовать fallback |
| `App Attest rate limited` | Превышен лимит 100 req/sec на app | Проверить throttle errors в логах | Постепенный rollout, < 10M users/day ramp |
| `Sandbox vs Production mismatch` | Attestation object из sandbox отправлен на production endpoint | Проверить `aaguid` field в attestation object | Использовать `data-development.appattest.apple.com` для sandbox |
| `Jailbreak detection bypassed` | Применен runtime patch через Frida | Проверить наличие Frida на устройстве | Добавить anti-tampering, integrity check, server-side validation |
| `Attestation Flake в CI` | Нестабильный network к attestation service | Перезапуск: `./gradlew connectedAndroidTest --rerun-tasks` | Изолировать тест, добавить quarantine для flaky runs |
| `Nonce replay detected` | Nonce повторно использован или истек срок | Проверить timestamp nonce на бэкенде | Увеличить TTL или улучшить синхронизацию времени |
| `Device Farm недоступен` | Устройство offline, cable отключен | Проверить connectivity через vendor API | Перезапустить устройство, переключить на reserve device |

---

## Наблюдаемость пайплайна

**Метрики:**
- **Attestation Success Rate** — процент успешных attestation checks. SLO: > 99.5%.
- **Attestation Latency P95** — 95-й перцентиль времени валидации attestation. SLO: < 2 секунды.
- **Attestation MTTR** — время от падения attestation pipeline до фикса. Target: < 30 минут.
- **Mock Usage Rate (CI)** — процент CI-сборок использующих mock attestation. Target: 100% для non-production.
- **Real Device Farm Utilization** — процент времени, которое устройства spend в testing vs idle. Target: > 60%.
- **Attestation Flake Rate** — процент недетерминированных падений attestation тестов. Target: < 1%.

**Логирование:**
- Логируйте `integrity verdict` и `device integrity` для каждого запроса (не логируйте полные токены).
- Архивируйте `xcresult` bundles и Android test results для каждого attestation-запуска.
- Сохраняйте nonce rotation logs и mock response templates как артефакты.

**Alerting:**
- Срабатывание при падении Attestation Success Rate ниже 99.5%.
- Срабатывание при Attestation Latency P95 выше 5 секунд.
- Срабатывание при отсутствии real device farm availability для production-сборок.
- Срабатывание при исчерпании Attestation Error Budget.
- Срабатывание при Attestation Flake Rate выше 1%.

---

## Best Practices

- Используйте `StandardIntegrityManager` для Android API 23+ с warm-up вызовом `prepareIntegrityToken` перед запросом токена.
- Для Apple App Attest всегда проверяйте `DCAppAttestService.shared.isSupported` перед использованием. Обрабатывайте `false` как fraud signal.
- Генерируйте nonce длиной 32 байта через криптографически стойкий PRNG (`SecRandomCopyBytes` на iOS, `SecureRandom` на Android).
- Никогда не передавайте attestation токены через URL parameters — используйте POST body с TLS 1.3.
- В CI всегда используйте mock attestation. Real attestation в CI возможен только при наличии outbound connectivity к Google/Apple API и реальных устройств.
- Для production release используйте real device farm — эмуляторы не покрывают device integrity verdict.
- Изолируйте attestation логику в отдельный модуль/сервис. Это упрощает mocking и тестирование.
- Кэшируйте Apple public keys и Google public keys на бэкенде с TTL 1 час. Не делайте HTTP запрос на каждую валидацию.
- Ротация API ключей: 90 дней для CI/testing, 1 год для production.
- Логируйте все attestation failures с контекстом (device model, OS version, app version) для forensic analysis.
- Настройте quarantine для flaky attestation тестов: автоматический quarantine при 2 последовательных падениях.
- Используйте build variants/flavors для分离 production и mock attestation кода.
- Для Apple App Attest: не превышайте 100 requests/second ramp-up; постепенный rollout: < 10M users/day.
- Архивируйте Build Evidence (Attestation): логи, артефакты, mock responses, nonce rotation history минимум 90 дней.

---

## См. также

- [security-scanning-mobile.md](./security-scanning-mobile.md) — SAST, DAST, jailbreak/root detection, code signing verification
- [incident-response-mobile.md](./incident-response-mobile.md) — MTTR, SEV levels, incident response procedures, kill switch
- [supply-chain-security-mobile.md](./supply-chain-security-mobile.md) — artifact signing, SBOM, provenance, reproducible builds
