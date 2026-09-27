# Crash Reporting и Symbolication в Mobile CI/CD

## Определения

**dSYM (Debug Symbol)** — файл символов отладки iOS/macOS, содержащий маппинг машинных адресов на исходные имена функций и строки. Генерируется при сборке iOS-приложения. Без dSYM crash-отчеты содержат только нечитаемые адреса.

**ProGuard Mapping** — текстовый файл, генерируемый ProGuard/R8 при обфускации Android-приложения. Содержит соответствие обфусцированных имен исходным классам, методам и строкам.

**Symbolication** — процесс преобразования нечитаемых машинных адресов в crash-стеке в читаемые имена функций и строки исходного кода с использованием dSYM/mapping.

**Crash Report** — запись о падении приложения, содержащая стек вызовов, исключение, состояние памяти и устройства. Источники: Sentry, ADB logcat, Xcode Organizer, custom crash reporters.

**dSYM Upload** — автоматическая загрузка файлов символов в crash reporting service в рамках CI-пайплайна. Обеспечивает symbolication crash-отчетов в production.

**Crash-free Rate** — процент сессий пользователей без crash. Ключевая метрика стабильности приложения. Цель: > 99%.

**MTTR (Crash)** — среднее время от детекции crash до публикации исправления. Для mobile включает время сборки, подписи и модерации магазина.

**Crash Triage** — процесс классификации crash-отчетов по severity и приоритету: SEV1 (критический crash, блокирующий), SEV2 (major regression), SEV3 (minor issue), SEV4 (enhancement).

**Crash Fingerprinting** — алгоритм группировки одинаковых crash-отчетов на основе stacktrace и exception type. Позволяет дедуплицировать тысячи reports в уникальные инциденты.

**NDK Crash** — crash в нативном коде (C/C++), написанном через Android NDK. Требует отдельного symbolication через .so symbols и NDK stack traces.

**Crashlytics** — crash reporting service от Firebase/Google. Включает автоматический сбор crash reports, symbolication, analytics.

**Sentry** — open-source crash reporting и performance monitoring platform. Поддерживает self-hosted deployment.

**Bugsnag** — crash reporting и stability monitoring service. Поддерживает iOS и Android с автоматической symbolication.

**Keystone (Crash Reporting)** — критичные инфраструктурные компоненты crash reporting: symbol storage (dSYM/mapping), crash ingestion pipeline, symbolication service, alerting.

**Crash Artifact** — итоговый файл, генерируемый при сборке: IPA/AAB/APK бинарник, dSYM/mapping, manifest.

**Crash Lifecycle** — полный цикл обработки crash: Detection → Ingestion → Symbolication → Triage → Investigation → Fix → Verification → Deployment.

**Symbolication Pipeline** — автоматизированный конвейер обработки crash reports: сборка → генерация символов → загрузка в service → symbolication → уведомление команды.

**Self-hosted Symbolication Infrastructure** — совокупность серверов и сервисов для самостоятельной обработки crash reports: crash ingestion API, symbol storage, symbolication workers, web UI для triage.

**Artifact Retention (Crash)** — политика хранения dSYM/mapping и crash reports. Рекомендуется хранить dSYM/mapping минимум 90 дней, crash reports — 180 дней для compliance и postmortem анализа.

**Build Cache (Symbols)** — кэширование dSYM/mapping между CI-запусками для ускорения upload и повторного использования неизмененных артефактов.

**Toil (Crash Reporting)** — ручная работа при обработке crash: ручная symbolication, ручной запуск upload, ручной поиск нужного dSYM. Цель: снизить долю toil до < 10%.

**Error Budget (Stability)** — допустимый процент crash rate или downtime. При исчерпании бюджета release halt и фокус на стабилизацию.

---

## Базовые концепции

### Архитектура пайплайна: Crash Reporting Lifecycle

Полный lifecycle crash reporting в Mobile CI/CD:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Build &     │───►│   Symbol     │───►│   dSYM/      │───►│   Crash      │───►│   Alert &    │
│  Sign        │    │   Generation │    │   Mapping    │    │   Ingestion  │    │   Triage     │
│              │    │              │    │   Upload     │    │              │    │              │
│  xcodebuild  │    │  DWARF       │    │  Sentry      │    │  Crashlytics │    │  SEV assign  │
│  gradle      │    │  ProGuard    │    │  Bugsnag     │    │  Sentry      │    │  On-call     │
│  match       │    │  R8          │    │  Custom      │    │  Custom      │    │  War Room    │
│              │    │              │    │              │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
         │                   │                   │                   │                   │
         ▼                   ▼                   ▼                   ▼                   ▼
    Code signing        dSYM.zip            Symbolicated         Crash-free Rate     Hotfix / Rollback
    Build artifact      mapping.txt          Stacktrace           Crash Count         Postmortem
```

**Этапы lifecycle:**

1. **Build & Sign:** Сборка приложения, подпись сертификатами, создание IPA/AAB.
2. **Symbol Generation:** Генерация dSYM (iOS) или mapping (Android) в процессе сборки.
3. **dSYM/Mapping Upload:** Загрузка символов в crash reporting service для symbolication.
4. **Crash Ingestion:** Сбор crash reports с устройств через SDK (Crashlytics, Sentry, Bugsnag).
5. **Alert & Triage:** Классификация по severity, уведомление on-call, создание инцидента.

### iOS: dSYM и Symbolication

iOS crash report содержит адреса памяти. Для получения читаемого стека нужен dSYM-файл, соответствующий точной версии бинарника.

**Типы dSYM:**
- **Main dSYM:** для основного таргета приложения
- **Extension dSYM:** для App Extensions (Today, Share, Siri)
- **Framework dSYM:** для embedded фреймворков

**Структура dSYM:**
```
MyApp.app.dSYM/
├── Contents/
│   └── Resources/
│       └── DWARF/
│           └── MyApp  ← основной символ-файл
```

**dSYM и Bitcode:**
При включенном Bitcode Apple перекомпилирует бинарник на стороне App Store. dSYM может отличаться от локальной сборки. После загрузки бинарника скачайте dSYM через App Store Connect API или Xcode Organizer.

**UUID Verification:**
Каждый dSYM имеет UUID, который должен совпадать с UUID в бинарнике:
```bash
# Проверка UUID dSYM
dwarfdump --uuid ./build/dSYMs/MyApp.app.dSYM
# → UUID: 12345678-1234-1234-1234-123456789012 (arm64)

# Проверка UUID в бинарнике
dwarfdump --uuid ./build/MyApp.app
# → Должен совпадать с dSYM UUID
```

### Android: ProGuard Mapping

ProGuard/R8 обфусцируют код: классы `com.company.feature.LoginActivity` → `a.b.c`. Mapping-файл — ключ к деobfuscation.

**Типы mapping:**
- **release/mapping.txt:** основное соответствие для release-сборки
- **seed.txt:** исходные классы, retained без обфускации
- **usage.txt:** информация об unused классах

**R8 и mapping:**
R8 заменяет ProGuard в современных проектах. Mapping-файл генерируется аналогично, но может иметь дополнительную информацию о inline-оптимизациях.

### Crash Reporting Services

**Сравнение self-hosted и hosted:**

| Service | Type | Особенности |
|:---|:---|:---|
| **Sentry** | Self-hosted / SaaS | Open Source, полный контроль, on-premise deployment |
| **Crashlytics** | Hosted (Firebase) | Бесплатно, tight integration с Firebase, требует Google services |
| **Bugsnag** | Hosted / SaaS | Простой UI, multi-platform, автоматическая triage |
| **Custom / Prometheus + Grafana** | Self-hosted | Полный контроль, требует symbolication pipeline |

### Symbolication Pipeline

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   CI Build       │────►│   dSYM/Mapping   │────►│  Crash Service   │
│   (Fastlane)     │     │   Upload         │     │  (Sentry/        │
│                  │     │                  │     │   Custom)        │
└──────────────────┘     └──────────────────┘     └──────────────────┘
          │                       │                       │
          ▼                       ▼                       ▼
    IPA / AAB artifact     dSYM.zip /               Crash-free Rate
                           mapping.txt               Symbolicated Stacktrace
```

### SRE-подход к Crash Reporting

- **MTTR (Crash):** Измеряйте время от первого crash report до фикса. Цель: < 4 часа для SEV1.
- **Error Budget (Stability):** Договоритесь о допустимом crash-free rate (например, > 99%). При исчерпании бюджета — фокус на стабилизацию.
- **Toil Reduction:** Автоматизируйте загрузку dSYM/mapping, symbolication, уведомления. Ручной процесс — это toil.
- **Observability:** Каждый crash должен иметь полный trace: alert → triage → investigation → fix → verification.

### Sysadmin: инфраструктура self-hosted crash reporting

Для организации собственной инфраструктуры crash reporting требуются следующие компоненты:

**Crash Ingestion Service:**
- **API Endpoint:** `POST /api/crash` для приема crash reports от SDK.
- **Authentication:** API keys или mTLS для мобильных клиентов.
- **Rate Limiting:** Ограничение на количество reports с одного устройства для предотвращения spam.

**Symbol Storage:**
- **dSYM/mapping archive:** Хранилище символов по версиям приложения. Используйте S3-совместимое хранилище (MinIO) или локальный filesystem.
- **Retention Policy:** Хранить dSYM/mapping минимум 90 дней, crash reports — 180 дней.
- **Backup:** Ежедневный backup критичных символов для возможности symbolication старых crash reports.

**Symbolication Workers:**
- **Symbolication Service:** Worker, который преобразует raw crash stack в symbolicated stack используя dSYM/mapping.
- **Queue:** Очередь для обработки crash reports (Redis/Bull).
- **Caching:** Кэширование symbolicated результатов для одинаковых stacktraces.

**Web UI / Dashboard:**
- **Crash List:** Список уникальных crash с fingerprinting.
- **Triage Interface:** Возможность назначить severity, добавить комментарий, создать ticket.
- **Trends:** Графики crash rate по версиям и платформам.

**Alerting:**
- **Webhook:** Уведомление в Slack/Telegram при новом SEV1/SEV2 crash.
- **PagerDuty/OpsGenie:** Интеграция с on-call rotation.
- **Email:** Для SEV3/SEV4 уведомлений команде.

**Сетевая инфраструктура:**
- **Firewall:** Ограничьте доступ к crash ingestion API только из корпоративной сети или VPN.
- **DNS:** Внутренний DNS-record (`crash.internal`) для SDK.
- **Load Balancer:** Если используется несколько инстансов, настройте round-robin.

### Crash Reporting Strategy

**Фазы обработки crash:**

```
Phase 1: Detection (минуты)
  ↓ SDK обнаруживает crash
  ↓ Собирает stacktrace, device info
  
Phase 2: Ingestion (минуты)
  ↑ Отправка на crash ingestion API
  ↑ Сохранение в очередь
  
Phase 3: Symbolication (минуты)
  ↑ Загрузка dSYM/mapping
  ↑ Преобразование в читаемый stack
  
Phase 4: Triage (часы)
  ↑ Классификация по severity
  ↑ Назначение on-call
  
Phase 5: Investigation (часы)
  ↑ Анализ root cause
  ↑ Создание hotfix
  
Phase 6: Fix & Deploy (часы-дни)
  ↑ Сборка hotfix
  ↑ Публикация в магазин
  ↑ Verification
```

### Crash Triage Process

**Классификация crash:**
- **SEV1:** Приложение не запускается, crash > 5% users, data loss
- **SEV2:** Major feature broken, crash > 1% users, performance degradation
- **SEV3:** Minor feature broken, crash < 1% users, UI issues
- **SEV4:** Enhancement, cosmetic issues

**Triage Workflow:**
```
Crash Detected
  ↓
Fingerprinting (deduplication)
  ↓
Crash-free Rate Analysis
  ↓
SEV Assignment (SEV1/SEV2/SEV3/SEV4)
  ↓
On-call Notification (SEV1/SEV2)
  ↓
Investigation & Root Cause
  ↓
Hotfix / Fix in Next Release
```

### Crash-free Rate как SLO

**Определение SLO:**
- **Crash-free Rate Target:** > 99.5% для production
- **Error Budget:** 0.5% crash rate допустимо
- **Alerting:** При падении crash-free rate ниже 99% — PagerDuty alert

**Измерение:**
- Crash-free rate считается по сессиям, не по пользователям
- Исключают forced closes и OS-level kills
- Учитывают только production builds, не debug

---

## Практические сценарии

### 1. Xcode: Генерация и проверка dSYM

**Проверка что dSYM генерируется:**
```bash
# Проверка настроек Xcode
xcodebuild -project MyApp.xcodeproj \
  -scheme MyApp \
  -showBuildSettings \
  | grep DEBUG_INFORMATION_FORMAT
# → DEBUG_INFORMATION_FORMAT = dwarf-with-dsym

# Проверка что dSYM создан
ls -lh ~/Library/Developer/Xcode/Archives/*/MyApp.xcarchive/dSYMs/
# → MyApp.app.dSYM  15M  2026-09-26 10:30
```

**Экспорт dSYM из архива:**
```bash
# Путь к архиву
ARCHIVE_PATH="./build/MyApp.xcarchive"

# Проверка dSYM внутри архива
ls "$ARCHIVE_PATH/dSYMs/"
# → MyApp.app.dSYM

# Копирование для загрузки
cp -r "$ARCHIVE_PATH/dSYMs/MyApp.app.dSYM" ./build/dSYMs/
```

**Пакетирование dSYM для upload:**
```bash
# Создание ZIP архива для загрузки
cd ./build/dSYMs/
zip -r dSYMs.zip *.dSYM
# → adding: MyApp.app.dSYM/... (compression 60%)
```

### 2. Android: ProGuard Mapping Generation

**Включение mapping в build.gradle:**
```groovy
android {
    buildTypes {
        release {
            minifyEnabled true
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'),
                          'proguard-rules.pro'
            
            // Сохранение mapping.txt
            preserveArtifacts = true
        }
    }
}
```

**Проверка mapping:**
```bash
# Проверка что mapping.txt создан
if [ -f app/build/outputs/mapping/release/mapping.txt ]; then
  LINES=$(wc -l < app/build/outputs/mapping/release/mapping.txt)
  echo "Mapping lines: $LINES"
else
  echo "WARNING: No obfuscation mapping found"
  exit 1
fi
```

**Пакетирование mapping для upload:**
```bash
# Копирование mapping в artifact
cp app/build/outputs/mapping/release/mapping.txt ./build/mapping/
```

### 3. Sentry: dSYM/Mapping Upload

**Установка Sentry CLI:**
```bash
# macOS
brew install getsentry/tools/sentry-cli

# Linux
curl -sL https://sentry.io/get-cli/ | bash

# Проверка
sentry-cli --version
# → 2.25.0
```

**Загрузка dSYM (iOS):**
```bash
# Автоматическая загрузка всех dSYM из архива
sentry-cli upload-dsym \
  --org my-org \
  --project my-project \
  ./build/dSYMs/

# Или через API token
export SENTRY_AUTH_TOKEN=sentry_api_token
sentry-cli upload-dsym \
  --org my-org \
  --project my-project \
  ./build/dSYMs/
# → Uploaded 2 dSYM files
```

**Загрузка mapping (Android):**
```bash
# Загрузка ProGuard mapping
sentry-cli upload-proguard \
  --org my-org \
  --project my-project \
  --jar app/build/outputs/apk/release/app-release.apk \
  app/build/outputs/mapping/release/mapping.txt
# → Uploaded mapping.txt
```

**Интеграция в Fastlane:**
```ruby
lane :upload_symbols do
  # iOS dSYM
  if ENV["SENTRY_AUTH_TOKEN"]
    sentry upload_dsym(
      auth_token: ENV["SENTRY_AUTH_TOKEN"],
      org: "my-org",
      project: "my-project",
      dsym_paths: ["./build/dSYMs/"]
    )
  end
  
  # Android mapping
  if ENV["SENTRY_AUTH_TOKEN"]
    sentry upload_proguard(
      auth_token: ENV["SENTRY_AUTH_TOKEN"],
      org: "my-org",
      project: "my-project",
      jar_path: "./app/build/outputs/apk/release/app-release.apk",
      mapping_path: "./app/build/outputs/mapping/release/mapping.txt"
    )
  end
end
```

**GitLab CI workflow:**
```yaml
upload_dsyms:
  stage: upload_symbols
  image: getsentry/sentry-cli:latest
  script:
    - sentry-cli upload-dsym \
        --org my-org \
        --project my-project \
        ./build/dSYMs/
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+/
  variables:
    SENTRY_AUTH_TOKEN: $SENTRY_AUTH_TOKEN
```

### 4. Bugsnag: Интеграция

**Установка Bugsnag CLI:**
```bash
npm install -g @bugsnag/cli
```

**Загрузка dSYM:**
```bash
bugsnag-cli upload dsym \
  --api-key YOUR_API_KEY \
  ./build/dSYMs/MyApp.app.dSYM
# → Uploaded dSYM for MyApp
```

**Загрузка mapping (Android):**
```bash
bugsnag-cli upload mapping \
  --api-key YOUR_API_KEY \
  --app-id YOUR_APP_ID \
  --version-code 42 \
  app/build/outputs/mapping/release/mapping.txt
```

### 5. Firebase Crashlytics: Интеграция

**Fastlane: Upload dSYM to Crashlytics:**
```ruby
platform :ios do
  desc "Upload dSYMs to Crashlytics"
  lane :upload_crashlytics_symbols do
    upload_symbols_to_crashlytics(
      google_services_json: "./GoogleService-Info.plist",
      dsym_paths: ["./build/dSYMs/"]
    )
  end
end
```

**Gradle: Automatic upload:**
```groovy
android {
    buildTypes {
        release {
            firebaseCrashlytics {
                nativeSymbolUploadEnabled true
                mappingFileUploadEnabled true
            }
        }
    }
}
```

### 6. Автоматическая symbolication в CI

**Полный пайплайн (iOS + Android + Sentry):**
```yaml
stages:
  - build_ios
  - build_android
  - upload_symbols

build_ios:
  stage: build_ios
  tags:
    - macos
  script:
    - xcodebuild archive \
        -workspace MyApp.xcworkspace \
        -scheme MyApp \
        -archivePath ./build/MyApp.xcarchive
  artifacts:
    paths:
      - ./build/MyApp.xcarchive/dSYMs/
    expire_in: 1 week

build_android:
  stage: build_android
  image: openjdk:17
  script:
    - ./gradlew bundleRelease
  artifacts:
    paths:
      - app/build/outputs/apk/release/app-release.apk
      - app/build/outputs/mapping/release/mapping.txt
    expire_in: 1 week

upload_dsyms_ios:
  stage: upload_symbols
  image: getsentry/sentry-cli:latest
  needs:
    - build_ios
  script:
    - sentry-cli upload-dsym \
        --org my-org \
        --project my-project \
        ./build/MyApp.xcarchive/dSYMs/
  variables:
    SENTRY_AUTH_TOKEN: $SENTRY_AUTH_TOKEN
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+/

upload_mapping_android:
  stage: upload_symbols
  image: getsentry/sentry-cli:latest
  needs:
    - build_android
  script:
    - sentry-cli upload-proguard \
        --org my-org \
        --project my-project \
        --jar app/build/outputs/apk/release/app-release.apk \
        app/build/outputs/mapping/release/mapping.txt
  variables:
    SENTRY_AUTH_TOKEN: $SENTRY_AUTH_TOKEN
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+/
```

### 7. Мониторинг crash-free rate

**Prometheus метрики:**
```yaml
groups:
  - name: mobile_crash_alerts
    rules:
      - alert: HighCrashRateiOS
        expr: crash_free_rate{platform="ios"} < 0.99
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "iOS crash-free rate below 99%"
      
      - alert: HighCrashRateAndroid
        expr: crash_free_rate{platform="android"} < 0.99
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Android crash-free rate below 99%"
      
      - alert: NewCrashIntroduced
        expr: rate(crash_count_total[10m]) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "New crash introduced in recent release"
```

---

## Операции и команды

### dSYM Management (iOS)

```bash
# Поиск dSYM для конкретной версии
find ~/Library/Developer/Xcode/Archives -name "*.dSYM" \
  -newer ./build/MyApp.app

# Проверка UUID dSYM
dwarfdump --uuid ./build/dSYMs/MyApp.app.dSYM
# → UUID: 12345678-1234-1234-1234-123456789012 (arm64)

# Проверка UUID в бинарнике
dwarfdump --uuid ./build/MyApp.app
# → Должен совпадать с dSYM UUID

# Создание ZIP архива для upload
cd ./build/dSYMs/
zip -r dSYMs.zip *.dSYM
# → adding: MyApp.app.dSYM/... (compression 60%)

# Проверка всех dSYM в архиве
unzip -l dSYMs.zip
# → MyApp.app.dSYM/Contents/Resources/DWARF/MyApp
```

### Mapping Management (Android)

```bash
# Поиск mapping.txt
find app/build/outputs -name "mapping.txt"

# Проверка размера mapping
wc -l app/build/outputs/mapping/release/mapping.txt
# → 15000 mapping.txt

# Валидация mapping
head -20 app/build/outputs/mapping/release/mapping.txt
# → com.company.app → a.b.c

# Копирование mapping в artifact
cp app/build/outputs/mapping/release/mapping.txt ./build/mapping/
```

### Crash Report Extraction

```bash
# iOS: Извлечение crash reports из симулятора
xcrun simctl spawn booted log show \
  --predicate 'subsystem == "com.apple.runningboard"' \
  --last 1h

# iOS: Просмотр crash reports
xcrun simctl spawn booted log stream \
  --predicate 'process == "MyApp"' \
  --level debug

# Android: Извлечение через ADB
adb logcat -d | grep -i "fatal\|exception\|androidruntime"

# Android: Tombstones
adb shell "ls /data/tombstones"
adb pull /data/tombstones/tombstone_01 ./tombstones/

# Android: Извлечение crash reports через bugreport
adb bugreport ./bugreports/
```

### Symbolication

```bash
# iOS: Symbolication через atos
atos -arch arm64 \
  -o ./build/MyApp.app.dSYM/Contents/Resources/DWARF/MyApp \
  -l 0x100000000 \
   0x100001234
# → [MyApp viewDidLoad] + 45

# Android: Deobfuscation через retrace
retrace \
  -verbose \
  app/build/outputs/mapping/release/mapping.txt \
  crash-stacktrace.txt
# → Деобфусцированный стек
```

### Artifact Retention: очистка и ротация dSYM/mapping

```bash
# Удаление dSYM/mapping старше 90 дней из CI workspace
find ./build/dSYMs/ -type f -mtime +90 -delete
find ./build/mapping/ -type f -mtime +90 -delete

# Очистка старых IPA/AAB из CI артефактов (GitLab)
# Настроить expire_in при upload артефактов

# Очистка старых builds из TestFlight (через App Store Connect API)
fastlane pilot delete_all_builds \
  --app_identifier com.company.app \
  --days 90

# Проверка retention policy для crash reports в Sentry
sentry-cli projects list
# → my-project (retention: 90 days)
```

### Управление retention policy

```bash
# Настройка автоматической очистки через launchd (macOS)
cat <<'EOF' | sudo tee /Library/LaunchDaemons/com.company.dsym-cleanup.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.company.dsym-cleanup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/dsym-cleanup.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
</plist>
EOF

sudo launchctl load /Library/LaunchDaemons/com.company.dsym-cleanup.plist
```

---

## Устранение проблем

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **dSYM not found** | Отключен DEBUG_INFORMATION_FORMAT, архив поврежден | Включите `dwarf-with-dsym` в Build Settings, пересоберите архив |
| **UUID mismatch** | dSYM не соответствует бинарнику | Убедитесь что загружаете dSYM из той же сборки, что и IPA |
| **Mapping file missing** | ProGuard отключен, `minifyEnabled false` | Включите `minifyEnabled true` для release-сборки |
| **Symbolication failed** | Неправильный load address, поврежденный dSYM | Проверьте UUID через `dwarfdump`, перезагрузите dSYM в сервис |
| **Crash-free rate inaccurate** | Некорректная интеграция SDK, пропущенные сессии | Проверьте что Sentry/SDK инициализируется при старте |
| **dSYM upload failed** | Нет доступа к API токену, превышен лимит | Проверьте `SENTRY_AUTH_TOKEN`, увеличьте rate limit |
| **Duplicate crash reports** | Не настроен deduplication на стороне сервиса | Настройте fingerprinting по stacktrace + exception type |
| **Missing line numbers** | dSYM не загружен, устаревший mapping | Загрузите актуальный dSYM/mapping для каждой версии |
| **Crash reports not arriving** | SDK не инициализирован, сетевые проблемы | Проверьте инициализацию SDK, добавьте retry логику |
| **ProGuard broke functionality** | Reflection-код, JSON-сериализация | Добавьте keep rules в `proguard-rules.pro` |
| **Bitcode dSYM mismatch** | Apple перекомпилировал бинарник | Скачайте dSYM через App Store Connect API |
| **NDK crash not symbolicated** | .so symbols не загружены | Загрузите NDK symbols в crash reporting service |
| **Crashlytics dSYM not processing** | Google Services конфиг отсутствует | Проверьте `GoogleService-Info.plist` и `google-services.json` |
| **Fingerprint collision** | Разные crash имеют одинаковый fingerprint | Настройте более точный fingerprinting algorithm |
| **Symbolication latency high** | Большой dSYM, перегруженный symbolication worker | Используйте кэширование и horizontal scaling workers |
| **Crash report spam** | SDK отправляет duplicate reports | Настройте deduplication на клиенте, throttle отправку |
| **dSYM storage full** | Накопление старых символов | Настройте retention policy и автоматическую очистку через launchd/cron |

---

## Рекомендации

### Best Practices

- **Automated dSYM/Mapping Upload:** Загружайте символы автоматически в CI-пайплайне. Ручной процесс — источник ошибок.
- **Retention dSYM/Mapping:** Храните dSYM и mapping для каждой выпущенной версии минимум 90 дней. Crash может быть обнаружен через месяцы после релиза.
- **Crash-free Rate как SLO:** Установите crash-free rate > 99% как SLO. При падении ниже порога — автоматический алерт.
- **MTTR Tracking:** Измеряйте время от первого crash report до фикса. Используйте эти данные для улучшения процессов.
- **Toil Reduction:** Автоматизируйте symbolication, уведомления, создание тикетов. Измеряйте долю ручной работы.
- **Error Budget:** Установите лимит crash rate. При исчерпании бюджета — freeze на новые фичи до устранения критических крашей.
- **Crash Triage:** Классифицируйте краши по severity. Critical — немедленный hotfix, Medium — в backlog.
- **Keystone Protection:** Разворачивайте crash reporting infrastructure на dedicated серверах с hot-standby. Мониторьте доступность отдельно от пайплайна.

### Edge Cases и ограничения

1. **dSYM для App Extensions:** Каждый extension генерирует свой dSYM. Убедитесь что загружаете все dSYM, иначе crash в extension не будет symbolicated.
2. **Bitcode и dSYM:** При включенном Bitcode Apple перекомпилирует бинарник. dSYM может отличаться от локальной сборки. Используйте `Download dSYMs from App Store Connect`.
3. **ProGuard и библиотеки:** Некоторые библиотеки требуют кастомных keep rules. Тестируйте release-сборку перед публикацией.
4. **Crash deduplication:** Один и тот же crash может приходить тысячу раз. Настройте fingerprinting на стороне сервиса.
5. **Missing dSYM для старых версий:** Если dSYM утерян, crash-отчет остается нечитаемым. Храните dSYM/mapping долгосрочно.
6. **Symbolication latency:** symbolication может занимать минуты для больших dSYM. Используйте кэширование на стороне сервиса.
7. **Multiple architectures:** Fat binaries (fat .ipa) содержат dSYM для arm64 и x86_64. Убедитесь что загружаете правильный dSYM.
8. **NDK crashes (Android):** Нативные краши (C/C++) требуют отдельного symbolication через NDK stack traces и .so symbols.
9. **Crashlytics limitations:** Бесплатный план имеет лимиты. Для enterprise рассмотрите self-hosted Sentry.
10. **Network reliability:** Загрузка dSYM/mapping может падать из-за сетевых проблем. Настройте retry и fallback.

---

## Мониторинг и Observability

**Ключевые метрики:**
- **Crash-free Rate:** % сессий без crash (цель: > 99%)
- **Crash Count:** абсолютное количество уникальных крашей
- **MTTR (Crash):** время от первого report до фикса
- **Symbolication Rate:** % crash-отчетов, успешно symbolicated (цель: 100%)
- **dSYM/Mapping Coverage:** % версий с загруженными символами
- **Crash Triage Time:** время от detection до triage decision
- **Unique Crashes:** количество уникальных fingerprint'ов

**Alert Rules:**
```yaml
groups:
  - name: crash_reporting_alerts
    rules:
      - alert: CrashFreeRateLow
        expr: crash_free_rate < 0.99
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Crash-free rate below 99%"
      
      - alert: DsymMissing
        expr: count(dsym_upload_total{status="missing"}) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "dSYM missing for release"
      
      - alert: MappingMissing
        expr: count(mapping_upload_total{status="missing"}) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "ProGuard mapping missing for release"
      
      - alert: SymbolicationFailed
        expr: rate(symbolication_failures_total[5m]) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Symbolication failure rate too high"
      
      - alert: CrashIngestionDown
        expr: rate(crash_ingestion_total[5m]) == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Crash ingestion API is not receiving reports"
```

**Quality Gates:**
- Все релизы должны иметь загруженные dSYM/mapping перед публикацией
- Crash-free rate > 99% на phased release stage 1%
- Symbolication rate = 100% для production crash reports
- dSYM/mapping retention: минимум 90 дней

**SRE Observability для crash reporting:**
- **Latency:** Время symbolication crash report (p50, p95, p99).
- **Availability:** Uptime crash ingestion API и web UI (target: 99.9%).
- **Error Rate:** % неудачных upload dSYM/mapping и crash ingestion.
- **Symbolication Queue Depth:** Количество crash reports в очереди на symbolication.

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — процедуры реагирования на crash-инциденты, MTTR, postmortem.
- **[Security Scanning в Mobile CI/CD](./security-scanning-mobile.md)** — obfuscation, ProGuard, symbol stripping.
- **[Release Management для мобильных приложений](./release-management-mobile.md)** — релизный цикл, approval gates.
