# Security Scanning в Mobile CI/CD

## Определения

**SAST (Static Application Security Testing)** — статический анализ исходного кода, байт-кода или бинарника без запуска приложения. В mobile-контексте: **SwiftLint** (iOS), **Detekt** (Android), а также общие инструменты (Semgrep, CodeQL) с мобильными правилами.

**SCA (Software Composition Analysis)** — анализ зависимостей проекта (SPM, CocoaPods, Gradle, Maven) на известные CVE. В mobile-контексте: **OWASP Dependency-Check** с мобильной конфигурацией, **Gradle Vulnerability Plugin**.

**DAST (Dynamic Application Security Testing)** — тестирование работающего приложения в runtime. В mobile-контексте: **MobSF** (Mobile Security Framework), **Frida** для динамического instrumentation.

**SBOM (Software Bill of Materials)** — инвентаризация всех компонентов приложения (зависимости, фреймворки, native libs) для отслеживания уязвимостей в supply chain.

**Code Signing Verification** — проверка целостности и происхождения бинарника через cryptographic signature. В iOS: Apple Distribution certificate; в Android: APK Signing Scheme v2/v3/v4.

**Obfuscation** — запутывание кода для затруднения reverse engineering. В Android: **ProGuard**, **R8**; в iOS: минимизация символов, Swift compiler optimizations.

**Certificate Pinning** — механизм, при котором приложение проверяет, что серверный сертификат соответствует заранее известному значению (hash), предотвращая атаки man-in-the-middle.

**Jailbreak / Root Detection** — механизмы приложения для определения повышенных привилегий на устройстве и ограничения функциональности в compromised окружении.

**MTTR Security** — среднее время устранения уязвимости от момента обнаружения до публикации исправления. Для mobile учитывается время сборки, подписи и модерации магазина.

**Error Budget (Security)** — допустимый объем пропущенных уязвимостей, связывающий скорость поставки с уровнем риска. При исчерпании бюджета — freeze на новые фичи до устранения критических находок.

---

## Базовые концепции

### Типы уязвимостей в Mobile

| Тип | iOS | Android | Критичность | SRE-impact |
|:---|:---|:---|:---|:---|
| **Dependency CVE** | SPM, CocoaPods | Gradle, Maven | Высокая | MTTR ↑, supply chain risk |
| **Insecure Storage** | Keychain, UserDefaults | SharedPreferences, SQLite | Критическая | Data breach, compliance violation |
| **Insecure Network** | HTTP, ATS bypass | HTTP, Cleartext Traffic | Высокая | MITM, data interception |
| **Code Injection** | JavaScriptCore, WKWebView | WebView, addJavascriptInterface | Критическая | RCE, data exfiltration |
| **Hardcoded Secrets** | API Keys in code, Info.plist | API Keys in strings.xml | Критическая | Credential leakage |
| **Weak Crypto** | MD5, SHA1, custom cipher | MD5, SHA1, custom cipher | Средняя | Data compromise |
| **Improper Code Signing** | Expired cert, wrong profile | v1 signature only | Высокая | Reject by App Store/Google Play |
| **Obfuscation Missing** | Symbols not stripped | ProGuard disabled | Средняя | IP theft, reverse engineering |
| **Jailbreak/Root Bypass** | No detection | No detection | Средняя | Emulator fraud, tampering |

### Пайплайн безопасности (Mobile DevSecOps)

```
┌───────────────────────────────────────────────────────────────────┐
│                    Mobile CI/CD Pipeline                           │
│                                                                   │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌────┐│
│  │  Lint   │──►│  SAST   │──►│  SCA    │──►│ Signing │──►│DAST││
│  │SwiftLint│   │SwiftLint│   │OWASP    │   │Verify  │   │MobSF││
│  │Detekt   │   │Detekt   │   │DepCheck │   │Cert    │   │Frida││
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘   └────┘│
│       │             │             │             │             │   │
│       ▼             ▼             ▼             ▼             ▼   │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌────┐│
│  │ Report  │   │ Report  │   │ Report  │   │Verify  │   │Report│
│  │Linter   │   │SAST     │   │SCA/CVE  │   │Chain   │   │DAST ││
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘   └────┘│
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### Пороговые значения и Quality Gates

| Метрика | Порог | Действие | MTTR impact |
|:---|:---|:---|:---|
| **Critical CVE** | 0 | Блокировка пайплайна | Немедленный hotfix |
| **High CVE** | < 3 | Предупреждение + Security Review | Планирование исправления |
| **Medium CVE** | < 10 | Рекомендация | Backlog |
| **Low CVE** | Не ограничено | Информирование | Accept risk |
| **SAST Errors** | 0 | Блокировка пайплайна | Немедленный фикс |
| **SAST Warnings** | < 20 | Предупреждение | Tech debt |
| **Secrets Detected** | 0 | Блокировка + автоматический rotation | Критический инцидент |
| **Signing Failure** | 0 | Блокировка | Проверка Keychain/сертификатов |

### SRE-подход к Mobile Security Scanning

**Принципы:**

- **MTTR как KPI:** Измеряйте время от обнаружения CVE до публикации исправления. Для mobile это включает время сборки, подписи и модерации магазина. Цель: < 24 часа для Critical, < 7 дней для High.
- **Error Budget для security:** Договоритесь о допустимом количестве Medium CVE в релизе. При исчерпании бюджета — фокус на устранение долга, а не на новые фичи.
- **Toil Reduction:** Автоматизируйте извлечение crash reports, проверку CVE, уведомление команд, создание тикетов. Ручной анализ каждого отчета — это toil.
- **Observability:** Каждая уязвимость должна иметь полный trace: CVE published → alert fired → triage → fix → release → verified.
- **On-call Rotation:** Security alerts должны приходить дежурному инженеру, а не в общий канал. Настройте escalation policy для P0 уязвимостей.

---

## Практические сценарии

### 1. SAST: SwiftLint (iOS)

```yaml
sast_swiftlint:
  tags:
    - macos
  script:
    - brew install swiftlint
    - swiftlint lint --reporter json --output swiftlint-report.json --strict
    - |
      ERRORS=$(jq '.[] | select(.severity == "error") | length' swiftlint-report.json)
      if [ "$ERRORS" -gt 0 ]; then
        echo "Found $ERRORS SwiftLint errors"
        cat swiftlint-report.json
        exit 1
      fi
  artifacts:
    paths:
      - swiftlint-report.json
    when: always
```

**Кастомные правила для security:**
```yaml
# .swiftlint.yml
disabled_rules:
  - line_length
  - trailing_whitespace

opt_in_rules:
  - explicit_type_interface
  - force_unwrapping
  - force_try

security_rules:
  - force_unwrapping # Предотвращает crash, который может быть использован для DoS
  - force_try # То же самое для ошибок
```

### 2. SAST: Detekt (Android)

```groovy
// build.gradle (app level)
plugins {
    id 'io.gitlab.arturbosch.detekt'
}

detekt {
    input.setFrom("src/main/java", "src/main/kotlin")
    config.setFrom("config/detekt/detekt.yml")
    buildUponDefaultConfig = true
    allRules = false
    
    reports {
        html.required.set(true)
        sarif.required.set(true)
        xml.required.set(true)
    }
    
    basePath = project.projectDir.absolutePath
}
```

**Кастомные security правила:**
```yaml
# config/detekt/detekt.yml
style:
  StringLiteralDuplication:
    active: true
    threshold: 3

complexity:
  LongMethod:
    threshold: 30

security:
  UnsafeRawHash:
    active: true
  CryptoSignedRaw:
    active: true
```

### 3. SCA: OWASP Dependency-Check (iOS)

```yaml
sca_ios:
  tags:
    - macos
  script:
    - brew install dependency-check
    - dependency-check --project "MyApp-iOS" --scan . --format HTML --format JSON --format SARIF --out dependency-check-report --failOnCVSS 7.0 --enableExperimental
    - |
      CRITICAL=$(jq '[.dependencies[].vulnerabilities[]? | select(.cvssv3.severity == "CRITICAL")] | length' dependency-check-report/dependency-check-report.json)
      HIGH=$(jq '[.dependencies[].vulnerabilities[]? | select(.cvssv3.severity == "HIGH")] | length' dependency-check-report/dependency-check-report.json)
      echo "Critical CVEs: $CRITICAL"
      echo "High CVEs: $HIGH"
      if [ "$CRITICAL" -gt 0 ]; then
        echo "Blocking pipeline due to critical CVEs"
        exit 1
      fi
  artifacts:
    paths:
      - dependency-check-report/
    when: always
```

### 4. SCA: Gradle Dependency Check (Android)

```groovy
// build.gradle (project level)
plugins {
    id 'org.owasp.dependencycheck' version '8.4.0' apply false
}

// build.gradle (app level)
plugins {
    id 'org.owasp.dependencycheck'
}

dependencyCheck {
    failBuildOnCVSS = 7.0
    suppressionFile = 'dependency-check-suppressions.xml'
    formats = ['HTML', 'JSON', 'SARIF']
    outputDirectory = "${buildDir}/reports/dependency-check"
    analyzers {
        assemblyEnabled = false
        nugetConfEnabled = false
        golangEnabled = false
        pythonEnabled = false
        rubyEnabled = false
        dartEnabled = false
        swiftEnabled = false
        rustEnabled = false
        cppEnabled = false
        opensslEnabled = false
        cmakeEnabled = false
        nuspecEnabled = false
        cocoapodsEnabled = false
    }
}
```

### 5. DAST: MobSF (Mobile Security Framework)

```yaml
dast_mobsf:
  tags:
    - linux
    - docker
  image: docker:latest
  services:
    - docker:dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  script:
    - docker pull mobsf/mobsf-android:latest
    - docker run -d -p 8000:8000 --name mobsf mobsf/mobsf-android:latest
    - timeout 120 bash -c 'until curl -s http://localhost:8000/; do sleep 2; done'
    - ./gradlew assembleRelease
    - |
      curl -X POST http://localhost:8000/api/v1/upload \
        -F "file=@app/build/outputs/apk/release/app-release.apk"
      SCAN_ID=$(curl -s http://localhost:8000/api/v1/scan | jq -r '.scan_id')
      curl -X POST "http://localhost:8000/api/v1/scan" \
        -H "Content-Type: application/json" \
        -d "{\"scan_type\": \"apk\", \"file_name\": \"app-release.apk\", \"scan_id\": \"$SCAN_ID\"}"
    - curl -o mobsf-report.pdf http://localhost:8000/api/v1/report_pdf
    - docker rm -f mobsf
  artifacts:
    paths:
      - mobsf-report.pdf
    when: always
```

### 6. DAST: Frida (iOS Dynamic Analysis)

```bash
# Установка Frida
pip install frida-tools frida

# Проверка установки
frida --version
# → 16.1.11

# Список подключенных устройств
frida-ls-devices
# → iPhone 15 Pro (local, usb, ios)

# Мониторинг API вызовов
frida -U -f com.company.app -l ios_monitor.js --no-pause
# → [iOS] Spawned com.company.app. Resuming main thread!

# Сбор логов в файл
frida -U -f com.company.app -l ios_monitor.js --no-pause -o frida-log.txt
```

**Пример Frida-скрипта для проверки Keychain:**
```javascript
// keychain_check.js
ObjC.classes.KeychainItem['- addItem:'].implementation = function(query) {
    console.log('[SECURITY] Keychain Add:', JSON.stringify(query));
    return this.original(query);
};

ObjC.classes.KeychainItem['- findItem:'].implementation = function(query) {
    console.log('[SECURITY] Keychain Query:', JSON.stringify(query));
    return this.original(query);
};
```

### 7. Secrets Scanning в Mobile

```yaml
secrets_scan:
  tags:
    - linux
  script:
    - curl -sSfL https://gitleaks.io/latest/gitleaks-linux-amd64 -o gitleaks && chmod +x gitleaks
    - ./gitleaks detect --source . --report-path gitleaks-report.json --report-format json
    - |
      LEAKS=$(jq 'length' gitleaks-report.json)
      if [ "$LEAKS" -gt 0 ]; then
        echo "Found $LEAKS potential secrets"
        cat gitleaks-report.json
        exit 1
      fi
  artifacts:
    paths:
      - gitleaks-report.json
    when: always
```

### 8. Code Signing Verification

```bash
# iOS: Проверка подписи
codesign -dv --verbose=4 MyApp.app
# → Authority=Apple Distribution: Company (TEAMID)
# → Authority=Apple Root CA

# Проверка provisioning profile
security cms -D -i embedded.mobileprovision
# → <dict>...<key>ProvisionedDevices</key>...

# Android: Проверка подписи APK
apksigner verify --verbose app-release.apk
# → Verifies
# → Verified using v1 scheme (JAR signing)
# → Verified using v2 scheme (APK Signature Scheme v2)

# Проверка сертификата в APK
keytool -printcert -jarfile app-release.apk
# → Owner: CN=Company, OU=Dev, O=Company, L=City, ST=State, C=US
# → Issuer: CN=Google LLC, O=Google LLC, C=US
```

### 9. Obfuscation Verification

```bash
# Android: Проверка что ProGuard/R8 отработал
# 1. Проверка mappings.txt
if [ -f app/build/outputs/mapping/release/mapping.txt ]; then
  echo "Obfuscation enabled"
  # Проверка размера mappings.txt
  LINES=$(wc -l < app/build/outputs/mapping/release/mapping.txt)
  echo "Mapping lines: $LINES"
else
  echo "WARNING: No obfuscation mapping found"
  exit 1
fi

# 2. Проверка что классы обфусцированы
jadx -d decompiled app/build/outputs/apk/release/app-release.apk
grep -r "com/company/app/feature" decompiled/sources/ | head -5
# → com/a/b/c/feature/ (обфусцированные имена)

# iOS: Проверка stripped символов
# В Xcode Build Settings:
# DEAD_CODE_STRIPPING = YES
# STRIP_INSTALLED_PRODUCT = YES
# STRIP_STYLE = all

# Проверка символов
nm -gU MyApp | head -20
# → Должно быть минимум exported символов
```

---

## Операции и команды

### Dependency Audit

```bash
# iOS: Audit SPM dependencies
swift package resolve
swift package show-dependencies --format json | jq '.dependencies[].identity'

# iOS: Audit CocoaPods
pod outdated --no-repo-update

# Android: Audit Gradle dependencies
./gradlew dependencies --configuration releaseRuntimeClasspath

# Проверка всех lock-файлов на изменения
git diff --name-only | grep -E "Package\.resolved|build\.gradle|Podfile\.lock"
```

### Security Report Generation

```bash
# Генерация сводного отчета безопасности
cat > security-summary.sh << 'EOF'
#!/bin/bash
echo "=== Mobile Security Scan Summary ==="
echo "Date: $(date)"

echo ""
echo "--- SAST ---"
if [ -f swiftlint-report.json ]; then
  SAST_ERRORS=$(jq '.[] | select(.severity == "error") | length' swiftlint-report.json)
  echo "SwiftLint errors: $SAST_ERRORS"
fi

echo ""
echo "--- SCA ---"
if [ -f dependency-check-report/dependency-check-report.json ]; then
  CRITICAL=$(jq '[.dependencies[].vulnerabilities[]? | select(.cvssv3.severity == "CRITICAL")] | length' dependency-check-report/dependency-check-report.json)
  HIGH=$(jq '[.dependencies[].vulnerabilities[]? | select(.cvssv3.severity == "HIGH")] | length' dependency-check-report/dependency-check-report.json)
  echo "Critical CVEs: $CRITICAL"
  echo "High CVEs: $HIGH"
fi

echo ""
echo "--- Secrets ---"
if [ -f gitleaks-report.json ]; then
  LEAKS=$(jq 'length' gitleaks-report.json)
  echo "Potential secrets: $LEAKS"
fi

echo ""
echo "--- Signing ---"
codesign -dv --verbose=4 MyApp.app 2>&1 | grep Authority
apksigner verify --verbose app-release.apk 2>&1 | grep Verified
EOF
chmod +x security-summary.sh
```

### Mobile Vulnerability Scanner (MobSF) CLI

```bash
# Запуск MobSF в Docker
docker run -d -p 8000:8000 --name mobsf mobsf/mobsf-android:latest

# Загрузка APK/IPA
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@app-release.apk"

# Запуск сканирования
SCAN_ID=$(curl -s http://localhost:8000/api/v1/scan | jq -r '.scan_id')
curl -X POST "http://localhost:8000/api/v1/scan" \
  -H "Content-Type: application/json" \
  -d "{\"scan_type\": \"apk\", \"file_name\": \"app-release.apk\", \"scan_id\": \"$SCAN_ID\"}"

# Скачивание отчета
curl -o report.pdf http://localhost:8000/api/v1/report_pdf

# Остановка
docker rm -f mobsf
```

### Certificate Pinning Verification

```bash
# Android: Проверка network security config
aapt dump xmltree app-release.apk AndroidManifest.xml | grep networkSecurityConfig
# → android:networkSecurityConfig=@xml/network_security_config

# Извлечение и проверка pins
aapt2 dump resources app-release.apk | grep pin
# → <pin-digest algorithm="SHA256">...</pin-digest>

# iOS: Проверка ATS (App Transport Security)
plutil -p MyApp.app/Info.plist | grep NSAppTransportSecurity
# → "NSAppTransportSecurity" => { ... }
```

---

## Устранение проблем

| Ошибка | Причина | Решение | MTTR impact |
|:---|:---|:---|:---|
| **Critical CVE в релизе** | Уязвимая зависимость в production | Быстрый rollback + hotfix с обновлением зависимостей | SEV1 |
| **High CVE пропущен** | Порог SCA слишком высок, нет baseline | Снизить порог, добавить в baseline с due date | SEV2 |
| **SwiftLint/Detekt падает** | Ошибка в конфигурации, несовместимая версия | Откатить конфиг, использовать baseline | Build blocked |
| **MobSF недоступен** | Docker образ устарел, порт занят | Проверить `docker ps`, обновить образ, очистить port | Scan skipped |
| **Frida не подключается** | Устройство не подключено, app не установлена | Проверить `frida-ls-devices`, переустановить app | Dynamic scan skipped |
| **Code Signing verification failed** | Сертификат истек, wrong provisioning profile | Проверить `security find-identity -p codesigning`, обновить cert | Release blocked |
| **Obfuscation сломала функциональность** | ProGuard съел reflection-код, R8 агрессивен | Добавить keep rules в `proguard-rules.pro`, пересобрать | Build broken |
| **Secrets в коде** | API keys hardcoded, попали в git history | Rotate credentials, добавить pre-commit hook (gitleaks), очистить history | Credential leak |
| **Certificate Pinning сломан** | Сертификат сервера обновлен, pin не изменен | Обновить pins, использовать backup pins, implement fallback | MITM risk |
| **Jailbreak detection bypassed** | Применен runtime patch через Frida | Добавить anti-tampering, integrity check, server-side validation | Fraud risk |

---

## Рекомендации

### Best Practices

- **Shift Left Security:** Запускайте security scanning на каждом PR, а не только перед релизом. Чем раньше найдете уязвимость — тем дешевле исправить.
- **Fail on Critical:** Блокируйте пайплайн при обнаружении Critical CVE или secrets. Не делегируйте это решение на stage Release.
- **Baseline Management:** Используйте baseline для SAST/SCA, чтобы игнорировать известный technical debt. Baseline должен обновляться при каждом исправлении уязвимости.
- **Supply Chain Security:** Аудит зависимостей должен быть автоматизирован. Используйте lock-файлы (Package.resolved, Podfile.lock, gradle.lockfile) и проверяйте их на каждый PR.
- **Code Signing как Security Control:** Подпись кода — это не только требование магазинов, но и механизм гарантии целостности. Верифицируйте подпись на каждом этапе.
- **Obfuscation по умолчанию:** Включите ProGuard/R8 для release сборок Android. Для iOS используйте `STRIP_INSTALLED_PRODUCT = YES` и `DEAD_CODE_STRIPPING = YES`.
- **Runbook'и:** Для каждого типа уязвимости (Critical CVE, secrets leak, signing failure, jailbreak bypass) должно быть пошаговое руководство.
- **MTTR Tracking:** Измеряйте время от alert до fix для каждого severity level. Используйте эти данные для улучшения процессов.
- **Error Budget:** Установите лимит High CVE на релиз. При исчерпании — freeze на новые фичи.
- **Drills:** Проводите учения по incident response для security сценариев: compromised dependency, leaked secret, CVE in production.

### Edge Cases и ограничения

1. **False Positives:** SAST-инструменты генерируют ложные срабатывания. Используйте suppression files, но регулярно их пересматривайте.
2. **Supply Chain атаки:** Зависимости могут быть скомпрометированы после публикации (отравление зависимостей). Используйте lock-файлы, reproducible builds, pin версий.
3. **Dynamic Analysis limitations:** MobSF и Frida требуют работающего приложения и физического/эмуляторного устройства. В CI это означает дополнительную инфраструктуру (фармы устройств).
4. **Code Signing in CI:** Эфемерный Keychain должен создаваться внутри джобы и удаляться после. Shared Keychain между джобами — security risk.
5. **Obfuscation Debugging:** ProGuard/R8 могут сломать reflection, JSON-сериализацию, библиотеки. Всегда тестируйте release сборку перед публикацией.
6. **Third-party SDKs:** Аналитические, рекламные и платежные SDK добавляют CVE риск. Включите их в SCA-скан и назначьте owners.
7. **Certificate Pinning Maintenance:** При обновлении серверных сертификатов pin должен обновляться синхронно. Используйте backup pins и graceful fallback.
8. **Jailbreak Detection Evasion:**Runtime patch-инструменты (Frida, Xposed) могут обойти detection. Используйте multi-layer detection (runtime + behavioral + server-side).

### Мониторинг и Observability

**Ключевые метрики:**
- **Scan Coverage:** % зависимостей, покрытых SCA
- **MTTR Security:** время от CVE published до fix deployed
- **Pipeline Block Rate:** % пайплайнов, заблокированных security gates
- **False Positive Rate:** % ложных срабатываний SAST
- **CVE Age:** средний возраст открытых High/Critical CVE

**Quality Gates:**
```yaml
gates:
  - name: Critical CVE
    threshold: 0
    action: block
  - name: High CVE
    threshold: 3
    action: warn
  - name: Secrets Detected
    threshold: 0
    action: block
  - name: Code Signing
    threshold: valid
    action: block
  - name: Obfuscation
    threshold: enabled
    action: warn
```

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Feature Flags в мобильных приложениях](./feature-flags-mobile.md)** — Kill Switch как средство быстрого отключения проблемной функциональности.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — процедуры реагирования на security incidents, MTTR, postmortem.
