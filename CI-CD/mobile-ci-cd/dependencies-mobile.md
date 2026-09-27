# Управление зависимостями в Mobile CI/CD

## Определения

**SPM (Swift Package Manager)** — официальный менеджер пакетов Apple, интегрированный в Xcode. Использует `Package.resolved` как lock-файл. Работает с Git-репозиториями.

**CocoaPods** — менеджер зависимостей для iOS/macOS, использующий `Podfile` и `Podfile.lock`. Центральный реестр: CocoaPods Trunk.

**Gradle Dependency Management** — система управления зависимостями Android через `build.gradle`/`build.gradle.kts`. Lock-файлы: `gradle.lockfile` (с AGP 7.0+), `versions.lock`.

**Private Registry** — self-hosted реестрий пакетов для дистрибуции внутренних библиотек. Для mobile: private SPM registry, private CocoaPods trunk, private Maven/Nexus для Android.

**Lock File** — файл фиксации точных версий всех зависимостей (прямых и транзитивных). Гарантирует воспроизводимость сборки.

**Reproducible Build** — свойство сборки давать побайтово идентичный артефакт при одинаковых исходниках и зависимостях. Критично для аудита и отката.

**Supply Chain Attack** — компрометация зависимости или реестра для внедрения вредоносного кода. В mobile: compromised CocoaPods pod, compromised SPM package, compromised Gradle plugin.

**SBOM (Software Bill of Materials)** — инвентаризация всех компонентов приложения. Обязательна для compliance и security scanning.

**Dependency Drift** — расхождение между заявленными зависимостями в `Package.swift`/`Podfile`/`build.gradle` и фактическими версиями, зафиксированными в lock-файле.

**Version Catalog** — централизованное управление версиями зависимостей в Android через `libs.versions.toml` (Gradle 7.0+).

**Artifact Retention (Dependencies)** — политика хранения lock-файлов и артефактов зависимостей в CI/CD. Определяет сроки хранения и правила очистки.

**Build Cache (Dependencies)** — кэширование загруженных пакетов и скомпилированных артефактов для ускорения сборок и снижения нагрузки на реестры.

**Toil (Dependency Management)** — рутинный труд по обновлению зависимостей, разрешению конфликтов и поддержанию lock-файлов. Цель: автоматизировать и минимизировать.

**Error Budget (Dependencies)** — допустимое количество outdated/уязвимых зависимостей. При исчерпании — фокус на обновлении вместо новых фич.

**MTTR (Dependency)** — среднее время от обнаружения CVE до обновления зависимости. Для mobile включает время тестирования и модерации магазина.

---

## Базовые концепции

### Архитектура пайплайна: Dependency Management Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│              Dependency Management Lifecycle (Mobile CI/CD)         │
│                                                                     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │
│  │  Resolve  │───►│  Lock     │───►│   Build   │───►│  Verify   │ │
│  │           │    │  File     │    │           │    │           │ │
│  │ SPM/Cocoa │    │ Pins      │    │ Compile   │    │ SCA Scan  │ │
│  │ Pods/Gradle│   │ exact     │    │ Link      │    │ CVE Check │ │
│  └───────────┘    │ versions  │    │           │    │           │ │
│        │          └───────────┘    └───────────┘    └───────────┘ │
│        │                 │                  │                │     │
│        ▼                 ▼                  ▼                ▼     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │
│  │ Registry  │    │   Cache   │    │ Artifact  │    │  Report   │ │
│  │ (GitLab/  │    │ (SPM/     │    │ Retention │    │ (SBOM,    │ │
│  │  Trunk/   │    │  Gradle/  │    │ Policy    │    │  CVE List)│ │
│  │  Nexus)   │    │  CocoaPods)│   │           │    │           │ │
│  └───────────┘    └───────────┘    └───────────┘    └───────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Фазы lifecycle:**

1. **Resolve:** Определение версий зависимостей (SPM `swift package resolve`, CocoaPods `pod install`, Gradle `dependencies`). Обращение к реестрам.
2. **Lock File:** Фиксация точных версий. Обновление `Package.resolved`, `Podfile.lock`, `gradle.lockfile`. Гарантия воспроизводимости.
3. **Build:** Компиляция с зафиксированными зависимостями. Кэширование артефактов.
4. **Verify:** SCA-скан на CVE, проверка lock-файла на актуальность, валидация SBOM.
5. **Artifact Retention:** Политика хранения артефактов и lock-файлов. Очистка устаревших версий.
6. **Reporting:** Генерация отчета о зависимостях, уязвимостях, compliance статусе.

### iOS Dependency Managers

| Менеджер | Lock-файл | Реестр | Особенности |
|:---|:---|:---|:---|
| **SPM** | `Package.resolved` | GitLab, Git, private SPM registry | Встроен в Xcode, recommended Apple |
| **CocoaPods** | `Podfile.lock` | CocoaPods Trunk (public), private trunk | Меньше конфигурации, широкий ecosystem |
| **Carthage** | `Cartfile.resolved` | GitLab | Устаревший, не рекомендуется для новых проектов |

### Android Dependency Managers

| Менеджер | Lock-файл | Реестр | Особенности |
|:---|:---|:---|:---|
| **Gradle (Google)** | `gradle.lockfile`, `versions.lock` | Google Maven, Maven Central, private Nexus | Стандарт для Android |
| **Version Catalogs** | `libs.versions.toml` | Gradle | Централизованное управление версиями |

### Lock File Strategies

**iOS (SPM):**
```
Package.resolved:
{
  "pins": [
    {
      "package": "Alamofire",
      "state": {
        "branch": null,
        "revision": "abc123...",
        "version": "5.8.0"
      }
    }
  ]
}
```

**iOS (CocoaPods):**
```
Podfile.lock:
PODS:
  - Alamofire (5.8.0):
    - Alamofire/Retry (= 5.8.0)

DEPENDENCIES:
  - Alamofire (~> 5.8.0)

SPEC CHECKSUMS:
  Alamofire: abc123...
```

**Android (Gradle):**
```
# gradle.lockfile
com.squareup.retrofit2:retrofix:2.9.0 {
    module = com.squareup.retrofit2:retrofit
    version = 2.9.0
}
```

### Reproducible Builds для Mobile

**iOS:**
- Фиксация `Package.resolved` и `Podfile.lock`
- Фиксация версий Xcode и CocoaPods
- Использование deterministic build settings
- Отключение non-deterministic вставок (timestamps, random seeds)

**Android:**
- Фиксация `gradle.lockfile` и `versions.lock`
- Использование `gradle.properties` с pinned версиями
- Включение `buildCache` для reproducibility
- Версионирование через `CI_PIPELINE_IID` или git tag

### Private Registries

**SPM Private Registry (Git-based):**
```swift
// Package.swift
dependencies: [
    .package(url: "https://git.company.com/internal/ios-lib.git", from: "1.0.0")
]
```

**CocoaPods Private Trunk:**
```bash
# Публикация pod
pod trunk push InternalLib.podspec

# Использование private trunk
pod repo add company-trunk https://git.company.com/cocoapods/trunk.git
pod repo list
```

**Maven/Nexus для Android:**
```groovy
repositories {
    maven {
        url "https://nexus.company.com/repository/mobile-libs/"
        credentials {
            username = nexusUsername
            password = nexusPassword
        }
    }
}
```

### Renovate/Dependabot для Mobile

**Особенности mobile:**
- **SPM:** Renovate поддерживает `matchDatasources: ["github-tags"]` для SPM packages
- **CocoaPods:** Renovate использует `matchDatasources: ["cocoapods"]`
- **Gradle:** Renovate использует `matchDatasources: ["maven"]`, требует `gradle-versions-plugin` для accurate versioning
- **Lock file maintenance:** Renovate может обновлять `Package.resolved` и `Podfile.lock`

**Caveats:**
- **SPM:** Не все пакеты имеют SemVer tags. Renovate может пропустить обновления.
- **CocoaPods:** Trunk может lag behind git repo. Проверяйте actual versions.
- **Gradle:** Dynamic versions (`+`) блокируют Renovate. Используйте fixed versions.
- **Cross-platform:** Flutter/React Native имеют свои менеджеры (`pub`, `npm`). Настройте Renovate отдельно.

### SRE-подход к Dependency Management

- **Error Budget для зависимостей:** Договоритесь о допустимом количестве outdated/уязвимых зависимостей. При исчерпании — фокус на обновлении.
- **MTTR (Dependency):** Среднее время от обнаружения CVE до обновления. Для mobile учитывайте время тестирования и модерации.
- **Toil Reduction:** Автоматизируйте обновление lock-файлов, SCA-скан, уведомления. Измеряйте долю ручной работы.
- **Observability:** Каждая уязвимость должна иметь trace: CVE published → alert → triage → fix → release.

### Sysadmin: инфраструктура self-hosted dependency management

**Компоненты инфраструктуры:**

- **Private Registry (SPM/CocoaPods/Maven):** Разверните на corporate-сервере (GitLab, Nexus, Verdaccio). Кэширует публичные пакеты и хранит внутренние.
- **SCA Scanner:** Self-hosted OWASP Dependency-Check или Grype для сканирования CVE. Запускается в CI или по расписанию.
- **SBOM Generator:** Утилиты для генерации SBOM (Swift Package Manager, Gradle, Syft). Хранятся в artifact registry.
- **Web UI:** Nexus Repository Manager или Verdaccio для просмотра и управления пакетами.
- **Alerting:** Настройте уведомления при появлении Critical CVE в используемых зависимостях.
- **Firewall:** Ограничьте исходящие подключения раннеров к публичным реестрам. Используйте только approved sources.
- **DNS:** Внутренние имена registry (nexus.company.com) должны резолвиться внутри корпоративной сети.

**Retention Policy (Dependencies):**
- **Lock-файлы:** Хранить в git репозитории бессрочно. Не удалять историю.
- **Artifacts:** Время хранения зависит от compliance требований. Рекомендуется: 90–180 дней.
- **SBOM:** Хранить бессрочно для каждого релиза (compliance).
- **CVE Reports:** 90 дней, после чего архивировать.

**Build Cache Management (Dependencies):**
- **SPM:** `~/Library/Caches/org.swift.swiftpm` — кэш скачанных пакетов. Очищать старше 7 дней.
- **CocoaPods:** `~/Library/Caches/CocoaPods` — кэш pods. Очищать при минорных версиях.
- **Gradle:** `~/.gradle/caches` — кэши модулей. Очищать при смене major версии Gradle.
- **CI Cache:** Настройте GitLab cache с ключом на основе lock-файла. TTL: 7–14 дней.

---

## Практические сценарии

### 1. Lock File Validation в CI

**SPM:**
```bash
# Проверка что Package.resolved актуален
swift package resolve
git diff --exit-code Package.resolved
# → exit 0 (актуален) или exit 1 (устарел)
```

**CocoaPods:**
```bash
# Проверка что Podfile.lock актуален
pod install --no-repo-update
git diff --exit-code Podfile.lock
# → exit 0 или exit 1
```

**Gradle:**
```bash
# Проверка lock-файлов
./gradlew dependencies --configuration releaseRuntimeClasspath --write-locks
git diff --exit-code gradle.lockfile versions.lock
# → exit 0 или exit 1
```

### 2. SCA Scanning для Mobile

**iOS (SPM + OWASP):**
```bash
# Audit SPM dependencies
swift package resolve
swift package show-dependencies --format json | jq '.dependencies[].identity'

# SCA через OWASP Dependency-Check
dependency-check \
  --project "MyApp-iOS" \
  --scan . \
  --format JSON \
  --out dependency-check-report \
  --failOnCVSS 7.0
```

**Android (Gradle + OWASP):**
```groovy
// build.gradle (project level)
plugins {
    id 'org.owasp.dependencycheck' version '8.4.0'
}

dependencyCheck {
    failBuildOnCVSS = 7.0
    formats = ['HTML', 'JSON', 'SARIF']
    outputDirectory = "${buildDir}/reports/dependency-check"
}
```

### 3. Renovate Configuration для Mobile

**.renovaterc.json:**
```json
{
  "extends": ["config:recommended", ":semanticCommits"],
  "packageRules": [
    {
      "matchDatasources": ["github-tags"],
      "matchPackagePatterns": ["*"],
      "automerge": true,
      "automergeType": "branch"
    },
    {
      "matchDatasources": ["cocoapods"],
      "matchPackagePatterns": ["*"],
      "automerge": false,
      "labels": ["dependencies"]
    },
    {
      "matchDatasources": ["maven"],
      "matchPackagePatterns": ["*"],
      "automerge": false,
      "labels": ["dependencies"]
    }
  ],
  "lockFileMaintenance": {
    "enabled": true,
    "schedule": ["before 6am on monday"]
  }
}
```

### 4. Private Registry Setup

**SPM Private Registry (Git-based):**
```swift
// Package.swift
dependencies: [
    .package(
        url: "https://git.company.com/internal/ios-lib.git",
        from: "1.0.0"
    )
]
```

**CocoaPods Private Trunk:**
```bash
# Инициализация private trunk
pod repo add company-trunk https://git.company.com/cocoapods/trunk.git

# Публикация podspec
pod repo push company-trunk InternalLib.podspec

# Использование в Podfile
source 'https://git.company.com/cocoapods/trunk.git'
source 'https://cdn.cocoapods.org/'
pod 'InternalLib', '~> 1.0'
```

**Maven/Nexus для Android:**
```xml
<!-- settings.xml -->
<servers>
  <server>
    <id>company-nexus</id>
    <username>${env.NEXUS_USERNAME}</username>
    <password>${env.NEXUS_PASSWORD}</password>
  </server>
</servers>

<profiles>
  <profile>
    <id>company</id>
    <repositories>
      <repository>
        <id>company-nexus</id>
        <url>https://nexus.company.com/repository/mobile-libs/</url>
      </repository>
    </repositories>
  </profile>
</profiles>
```

### 5. Reproducible Build Verification

**iOS:**
```bash
# Включение reproducible builds
xcodebuild archive \
  -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -archivePath ./build/MyApp.xcarchive \
  CURRENT_PROJECT_VERSION=$(git rev-parse --short HEAD) \
  MARKETING_VERSION=2.5.0

# Проверка deterministic build
shasum -a 256 ./build/MyApp.xcarchive/Products/Applications/MyApp.app
```

**Android:**
```bash
# Reproducible build с pinned версиями
./gradlew assembleRelease \
  -PversionCode=42 \
  -PversionName=2.5.0 \
  --no-daemon \
  --build-cache

# Проверка deterministic build
sha256sum app/build/outputs/apk/release/app-release.apk
```

### 6. Dependency Update Automation

**GitLab CI: Renovate**
```yaml
# .gitlab-ci.yml
renovate:
  stage: .pre
  image: node:20
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: always
    - when: manual
  script:
    - npm install -g renovate
    - renovate --platform gitlab --token "$RENOVATE_TOKEN"
  only:
    - schedules
```

**GitLab CI: Dependabot**
```yaml
# .gitlab-ci.yml
dependabot:
  stage: .pre
  image: node:20
  script:
    - npm install -g @dependabot/gitlab-action
    - dependabot update
  only:
    - schedules
```

### 7. SBOM Generation

**iOS:**
```bash
# Генерация SBOM через Swift Package Manager
swift package resolve
swift package show-dependencies --format json > sbom-ios.json
```

**Android:**
```bash
# Генерация SBOM через Gradle
./gradlew dependencies --configuration releaseRuntimeClasspath \
  | grep -E "^\\+" \
  | sed 's/^\\+ //' > sbom-android.txt
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

# Проверка lock-файлов на изменения
git diff --name-only | grep -E "Package\.resolved|Podfile\.lock|build\.gradle|gradle\.lockfile"
```

### Vulnerability Scanning

```bash
# iOS: OWASP Dependency-Check
dependency-check \
  --project "MyApp-iOS" \
  --scan . \
  --format HTML \
  --format JSON \
  --out dependency-check-report \
  --failOnCVSS 7.0

# Android: Gradle Dependency Check
./gradlew dependencyCheckAnalyze

# Общий: Grype
grype dir:. --fail-on high
```

### Lock File Maintenance

```bash
# SPM: Обновление Package.resolved
swift package update
git add Package.resolved

# CocoaPods: Обновление Podfile.lock
pod update
git add Podfile.lock

# Gradle: Обновление lock-файлов
./gradlew dependencies --write-locks
git add gradle.lockfile versions.lock
```

### Artifact Retention: очистка и ротация lock-файлов и артефактов

```bash
# Удаление старых артефактов из CI workspace (GitLab)
# GitLab: настроить expire_in при upload

# Очистка кэша SPM старше 7 дней
find ~/Library/Caches/org.swift.swiftpm -type f -mtime +7 -delete 2>/dev/null

# Очистка кэша CocoaPods старше 7 дней
find ~/Library/Caches/CocoaPods -type f -mtime +7 -delete 2>/dev/null

# Очистка кэша Gradle старше 14 дней
find ~/.gradle/caches -type f -mtime +14 -delete 2>/dev/null
```

### Управление retention policy

```bash
# Настройка автоматической очистки через launchd (macOS)
cat <<'EOF' | sudo tee /Library/LaunchDaemons/com.company.dep-cleanup.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.company.dep-cleanup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/dep-cleanup.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>4</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
</plist>
EOF
```

---

## Устранение проблем

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **SPM resolve failed** | Невалидный Package.resolved, network issues | Удалите `Package.resolved` и выполните `swift package resolve` |
| **CocoaPods install fails** | Конфликт версий, устаревший кэш | Выполните `pod cache clean --all` и `pod install --repo-update` |
| **Gradle dependency conflict** | Две зависимости требуют разные версии одной библиотеки | Используйте `resolutionStrategy` в `build.gradle` |
| **Lock file drift** | Lock-файл устарел относительно Package.swift/Podfile | Выполните `pod update` / `swift package update` |
| **Dependency confusion** | Внутренняя библиотека переименована в публичную с тем же именем | Используйте private registry, pin версии по hash |
| **SCA false positive** | CVE не эксплуатируемо в вашем контексте | Добавьте suppression с обоснованием |
| **Renovate PR conflict** | Несколько авто-PR конфликтуют | Включите automerge, настроите grouping |
| **Private registry down** | Nexus/Trunk недоступен | Настройте fallback к кэшированным lock-файлам, используйте mirror |
| **Gradle version catalog conflict** | Два каталога определяют одну зависимость | Используйте `strictVersion` и `versionConflictResolution` |
| **Reproducible build fails** | Non-deterministic build (timestamps, paths) | Включите `SOURCE_DATE_EPOCH`, отключите `CURRENT_PROJECT_VERSION` из git |
| **SBOM generation failed** | Сканирование не поддерживает формат артефакта | Проверьте тип артефакта (dir, image); используйте соответствующий плагин |
| **CVE in transitive dependency** | Уязвимость во внутренней транзитивной зависимости | Используйте `resolutionStrategy` для принудительного обновления или исключения |

---

## Рекомендации

### Best Practices

- **Lock Files:** Фиксируйте lock-файлы в репозитории. Никогда не используйте floating versions в production.
- **Private Registries:** Разверните private registry для внутренних библиотек. Это ускоряет сборки и обеспечивает security.
- **SCA Scanning:** Запускайте SCA-скан на каждом PR. Блокируйте merge при Critical CVE.
- **Renovate/Dependabot:** Включите auto-merge для patch/minor обновлений. Major — на ревью.
- **Reproducible Builds:** Используйте pinned версии, lock-файлы, deterministic build settings.
- **SBOM:** Генерируйте SBOM для каждого релиза. Храните его для compliance.
- **Supply Chain Security:** Аудит зависимостей должен быть автоматизирован. Используйте lock-файлы и reproducible builds.
- **Toil Reduction:** Автоматизируйте обновление зависимостей, SCA-скан, уведомления. Измеряйте долю ручной работы.
- **Artifact Retention:** Настройте политику хранения lock-файлов и артефактов. Очищайте устаревшие данные регулярно.
- **Build Cache:** Используйте кэширование на уровне раннера и CI. Настройте TTL и invalidation based on lock-файл changes.

### Edge Cases и ограничения

1. **SPM limitations:** SPM не поддерживает binary frameworks без wrapper. Для proprietary библиотек используйте CocoaPods или Carthage.
2. **CocoaPods performance:** `pod install` может быть медленным на больших проектах. Используйте `pod cache` и `--no-repo-update`.
3. **Gradle daemon memory:** На CI отключайте daemon (`org.gradle.daemon=false`) для чистоты. На persistent раннерах — оставляйте включенным.
4. **Dependency hell (iOS):** Две зависимости могут требовать несовместимые версии третьей. Используйте `pod update` или пересмотрите зависимости.
5. **Dependency hell (Android):** Gradle разрешает конфликты через `resolutionStrategy`. Используйте `force` или `strictly` для критичных версий.
6. **Lock file merge conflicts:** Большие lock-файлы часто конфликтуют. Используйте `pod install --no-repo-update` или regenerate lock-файл.
7. **Private registry auth:** Убедитесь что CI-раннеры имеют доступ к private registry. Храните credentials в CI-секретах.
8. **Transitive dependencies:** Сканируйте не только прямые, но и транзитивные зависимости. Они часто содержат CVE.
9. **Version catalog migration:** При переходе на Version Catalogs в Android убедитесь что все модули используют единый источник truth.
10. **Carthage deprecation:** Для новых проектов используйте SPM. Carthage не обновляется и не поддерживает Swift Package Manager integration.

---

## Мониторинг и Observability

**Ключевые метрики:**
- **Outdated Dependencies:** % зависимостей с доступными обновлениями
- **Critical CVE Age:** средний возраст открытых Critical CVE
- **SCA Block Rate:** % пайплайнов, заблокированных SCA-гейтом
- **Lock File Freshness:** возраст последнего обновления lock-файла
- **Dependency Update Lead Time:** время от публикации CVE до обновления
- **Cache Hit Rate:** % сборок использующих кэшированные зависимости
- **Registry Availability:** доступность private registry (uptime)

**Alert Rules:**
```yaml
groups:
  - name: dependency_alerts
    rules:
      - alert: CriticalCVEDetected
        expr: dependency_cve_count{severity="critical"} > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Critical CVE detected in dependencies"
      
      - alert: LockFileStale
        expr: time() - lock_file_last_updated_timestamp > 604800
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Lock file not updated for > 7 days"
      
      - alert: DependencyUpdateStuck
        expr: dependency_update_open_total > 10
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Too many open dependency updates"
      
      - alert: PrivateRegistryDown
        expr: registry_up{name="nexus"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Private registry is down"
```

**Quality Gates:**
- No Critical CVE в release dependencies
- Lock-файлы обновлены в течение последних 7 дней
- Все авто-PR проходят CI
- Cache hit rate > 80% для зависимостей

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Security Scanning в Mobile CI/CD](./security-scanning-mobile.md)** — SCA, SAST, supply chain security.
- **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins, интеграция с dependency management.
