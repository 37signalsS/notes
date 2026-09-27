# Release Management для Mobile

## Определения

**Release Management (Mobile)** — дисциплина планирования, координации и контроля выпуска мобильных приложений в App Store и Google Play. Включает версионирование, approval gates, audit trail и compliance.

**Semantic Versioning (SemVer)** — схема версионирования `MAJOR.MINOR.PATCH`. В mobile применяется к маркетинговым версиям (`versionName`/`CFBundleShortVersionString`).

**versionCode (Android)** — целочисленный идентификатор сборки, который всегда увеличивается с каждым релизом. Используется Google Play для определения новизны версии. Не виден пользователям.

**versionName (Android)** — маркетинговая версия, отображаемая пользователям в Google Play. Формат: `MAJOR.MINOR.PATCH`.

**CFBundleShortVersionString (iOS)** — маркетингская версия, отображаемая пользователям в App Store. Формат: `MAJOR.MINOR.PATCH`.

**CFBundleVersion (iOS)** — build number, целочисленный или строковый идентификатор сборки, который должен увеличиваться с каждым релизом. Используется App Store Connect для определения новизны.

**Release Candidate (RC)** — промежуточная версия приложения, проходящая финальное тестирование перед production релизом.

**Approval Gate** — этап пайплайна, требующий ручного или автоматического одобрения перед продвижением в production.

**Audit Trail** — неизменяемый журнал всех действий с релизом: кто, когда, какую версию опубликовал, какие изменения вошли.

**Changelog** — структурированный список изменений между версиями. Генерируется автоматически из conventional commits или заполняется вручную.

**Hotfix** — экстренный патч для production, выпускаемый вне регулярного релизного цикла.

**Release Train** — запланированный цикл релизов (например, еженедельный по вторникам). Все фичи, готовые к дате поезда, попадают в релиз.

**Phased Release** — поэтапное обновление приложения: сначала небольшой процент пользователей, затем увеличение до 100%. Основной механизм App Store Connect.

**Staged Rollout** — аналог Phased Release для Google Play с возможностью остановки на любом этапе.

**Rollback Plan** — документированная процедура отката к предыдущей стабильной версии. В mobile включает публикацию предыдущей версии или активацию kill switch.

**Release Evidence** — структурированный JSON-отчет для каждого релиза: коммиты, тесты, артефакты, approvers, rollback plan.

**Maintenance Window** — запланированный период времени для проведения deployment-работ. В mobile учитывает время модерации магазина.

**Freeze Period** — период запрета на релизы (конец года, аудит, праздники). Требует планирования release calendar.

**Artifact Retention (Release)** — политика хранения IPA/AAB артефактов, dSYM/mapping, SBOM. Определяет сроки хранения и правила очистки.

**Build Cache (Release)** — кэширование артефактов для ускорения rollback и повторных сборок. Локальный кэш на macOS-раннерах и артефакт-хранилище.

**Toil (Release Management)** — рутинный труд по ручному версионированию, загрузке артефактов, заполнению release notes. Цель: автоматизировать и минимизировать.

**Error Budget (Release)** — допустимый процент проблемных релизов в месяц. При исчерпании — фокус на стабилизацию вместо новых фич.

**MTTR (Release)** — среднее время от обнаружения проблемы до отката или фикса. Для mobile включает время модерации магазина (< 4 часа).

---

## Базовые концепции

### Архитектура Release Management Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│              Release Management Lifecycle (Mobile CI/CD)           │
│                                                                     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │
│  │  Commit   │───►│  Version  │───►│   Build   │───►│  Approval │ │
│  │  Stage    │    │  Bump     │    │  & Test   │    │   Gate    │ │
│  │           │    │           │    │           │    │           │ │
│  │ Git merge │    │ SemVer +  │    │ IPA/AAB   │    │ QA + PM + │ │
│  │ PR merge  │    │ CI ID     │    │ SCA scan  │    │ Security  │ │
│  └───────────┘    └───────────┘    └───────────┘    └───────────┘ │
│        │                 │                  │                │     │
│        ▼                 ▼                  ▼                ▼     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │
│  │  Release  │    │  Changelog│    │  Artifact │    │  Promote  │ │
│  │  Tag      │    │  Generate │    │ Retention │    │  to Prod  │ │
│  │           │    │           │    │           │    │           │ │
│  │ git tag   │    │ Conv.     │    │ IPA/AAB   │    │ Phased    │ │
│  │ v2.5.0    │    │ Commits   │    │ dSYM/map  │    │ Release   │ │
│  └───────────┘    └───────────┘    │ SBOM      │    │           │ │
│        │                 │         └───────────┘    └───────────┘ │
│        ▼                 ▼                  │                │     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐           │     │
│  │  Audit    │    │  Release  │    │  Build    │           │     │
│  │  Trail    │    │  Evidence │    │  Cache    │           │     │
│  │           │    │           │    │           │           │     │
│  │ JSON log  │    │ JSON +    │    │ SPM/Gradle│           │     │
│  │ immutab.  │    │ artifacts │    │ CocoaPods │           │     │
│  └───────────┘    └───────────┘    └───────────┘           │     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Фазы lifecycle:**

1. **Commit Stage:** Merge PR, запуск CI pipeline. Автоматические проверки: lint, tests, SCA scan.
2. **Version Bump:** Увеличение `versionCode`/`CFBundleVersion`, обновление `versionName`/`CFBundleShortVersionString`. Используется CI pipeline ID или git tag.
3. **Build & Test:** Компиляция IPA/AAB, запуск unit/integration/e2e тестов, SCA-скан на CVE.
4. **Approval Gate:** Automated checks (crash-free rate, security) + Manual approval (QA, PM, Security).
5. **Release Tag:** Создание git tag `vX.Y.Z`, привязка к коммиту SHA.
6. **Changelog Generation:** Автоматическая генерация из conventional commits.
7. **Artifact Retention:** Загрузка IPA/AAB, dSYM/mapping, SBOM в artifact storage с retention policy.
8. **Promote to Prod:** Deployment в App Store/Google Play через Phased Release/Staged Rollout.
9. **Audit Trail:** Запись всех действий в immutable audit log.
10. **Release Evidence:** Генерация JSON-отчета с коммитами, тестами, артефактами, approvers.
11. **Build Cache:** Кэширование артефактов для ускорения rollback и повторных сборок.

### Mobile Versioning Schemes

**Android:**
- `versionCode` (integer): monotonically increasing, required by Google Play
- `versionName` (string): user-facing, follows SemVer

**iOS:**
- `CFBundleShortVersionString` (string): user-facing, follows SemVer
- `CFBundleVersion` (string): build number, must increase with each release

**Правила версионирования:**
- `versionCode`/`CFBundleVersion` всегда увеличиваются
- `versionName`/`CFBundleShortVersionString` следуют SemVer
- Hotfix: bump PATCH только
- Minor release: bump MINOR, сброс PATCH на 0
- Major release: bump MAJOR, сброс MINOR и PATCH на 0

### Release Strategies

| Стратегия | Описание | Когда использовать |
|:---|:---|:---|
| **Continuous Release** | Каждый прошедший релиз-кандидат автоматически публикуется | Высокомaturные команды, частые релизы |
| **Release Candidate (RC)** | Промежуточная версия перед stable, бета-тестирование | Крупные релизы, major версии |
| **Hotfix** | Экстренный патч из ветки `hotfix/*` | Критические баги в production |
| **Pre-release** | Alpha/Beta версии для тестирования | Публичное тестирование |
| **CalVer** | Календарное версионирование `YYYY.MM.PATCH` | Инфраструктурные приложения |
| **Release Train** | Запланированный цикл релизов (еженедельный, ежемесячный) | Команды с predictable release cadence |

### Approval Gates

Mobile release pipeline требует multiple approval gates:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Build &    │───►│   Staging    │───►│  Production  │
│   Test       │    │   Approval   │    │   Approval   │
└──────────────┘    └──────────────┘    └──────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
   Automated           QA Lead /          Release Manager /
   Checks              PM                  Security Team
```

**Gate Types:**
- **Automated:** crash-free rate > 99%, no Critical CVE, all tests passed
- **Manual:** QA approval, PM approval, Security review
- **Compliance:** GDPR review, legal approval for regulated industries

### Automated Changelog

Генерация release notes из conventional commits:
- `feat:` → New Features
- `fix:` → Bug Fixes
- `docs:` → Documentation
- `chore:` → Maintenance
- `BREAKING CHANGE:` → Breaking Changes

### Audit Trail

Каждый релиз должен иметь:
- **Commit SHA:** точная версия исходного кода
- **Build Number:** версия бинарника
- **Who:** кто инициировал релиз
- **When:** timestamp публикации
- **What:** список изменений (changelog)
- **Approvers:** кто одобрил релиз
- **Artifacts:** IPA/AAB, dSYM, mapping, SBOM

### SRE-подход к Release Management

- **Error Budget для релизов:** Договоритесь о допустимом проценте проблемных релизов (например, 5% в месяц). При исчерпании — фокус на стабилизацию.
- **MTTR (Release):** Среднее время от обнаружения проблемы до отката или фикса. Для mobile: < 4 часа.
- **Toil Reduction:** Автоматизируйте версионирование, генерацию changelog, загрузку артефактов. Измеряйте долю ручной работы.
- **Observability:** Каждый релиз должен иметь полный trace: commit → build → test → approval → deploy → monitor.

### Sysadmin: инфраструктура self-hosted release management

**Компоненты инфраструктуры:**

- **macOS-раннеры:** Self-hosted раннеры с Xcode, Fastlane, актуальными сертификатами подписи. Изолированные окружения для сборки.
- **Artifact Storage:** Self-hosted хранилище IPA/AAB, dSYM, mapping, SBOM. Для enterprise: Nexus Repository Manager, MinIO, S3-compatible storage.
- **Certificate Management:** Мониторинг сроков действия сертификатов подписи (Apple Distribution, Google Play Signing). Настройка алертов за 30/7/1 день до истечения.
- **Signing Infrastructure:** Fastlane Match или собственный сервер для управления сертификатами и Provisioning Profiles.
- **Audit Log Storage:** Self-hosted хранилище audit trail (immutable, append-only). JSON-файлы или база данных.
- **Retention Policy Automation:** Скрипты для очистки старых артефактов, логов, audit trail. Запуск через launchd/cron.
- **Build Cache Management:** Локальный кэш на macOS-раннерах (SPM, Gradle, CocoaPods). Очистка при смене major версий инструментов.
- **Network Configuration:** Ограничение исходящих подключений раннеров. Whitelist для реестров, магазинов, API.

**Retention Policy (Release Artifacts):**
- **IPA/AAB:** 90–180 дней, в зависимости от compliance требований.
- **dSYM/mapping:** 90–180 дней. Для crash reporting требуется доступ к символам.
- **SBOM:** Бессрочно для каждого релиза (compliance).
- **Audit Log:** Бессрочно или минимум 1 год (SOX, GDPR).
- **Release Evidence:** 90–180 дней.
- **Build Cache:** 7–14 дней на уровне раннера.

**Build Cache Management (Release):**
- **SPM:** `~/Library/Caches/org.swift.swiftpm` — кэш скачанных пакетов. Очищать старше 7 дней.
- **CocoaPods:** `~/Library/Caches/CocoaPods` — кэш pods. Очищать при минорных версиях.
- **Gradle:** `~/.gradle/caches` — кэши модулей. Очищать при смене major версии Gradle.
- **CI Cache:** Настройте GitLab cache с ключом на основе lock-файла. TTL: 7–14 дней.
- **Artifact Cache:** Кэширование IPA/AAB для быстрого rollback. Хранить последние 3–5 версий.

---

## Практические сценарии

### 1. Automated Versioning (iOS + Android)

**Fastlane: Automated Version Bump:**
```ruby
platform :ios do
  desc "Bump version for new release"
  lane :bump_version do |options|
    bump_type = options[:bump_type] || "patch" # patch, minor, major
    
    # Получение текущей версии
    current_version = get_version_number(xcodeproj: "MyApp.xcodeproj")
    
    # Bump marketing version
    increment_version_number(
      xcodeproj: "MyApp.xcodeproj",
      bump_type: bump_type
    )
    
    # Автоматический bump build number
    increment_build_number(xcodeproj: "MyApp.xcodeproj")
    
    UI.message("Version bumped: #{current_version} → #{get_version_number(xcodeproj: 'MyApp.xcodeproj')}")
  end
end
```

**Android: Automated Versioning via CI:**
```groovy
// build.gradle.kts
android {
    defaultConfig {
        // versionCode из CI pipeline ID
        versionCode = System.getenv("CI_PIPELINE_IID")?.toIntOrNull() ?: 1
        
        // versionName из git tag
        versionName = getGitTag() ?: "1.0.0"
    }
}

def getGitTag() {
    def stdout = new ByteArrayOutputStream()
    exec {
        commandLine 'git', 'describe', '--tags', '--exact-match'
        standardOutput = stdout
    }
    return stdout.toString().trim()
}
```

### 2. Automated Changelog Generation

**Conventional Commits → Changelog:**
```bash
# Генерация changelog из git history
git log --oneline --no-merges v1.2.0..HEAD \
  | grep -E "^(feat|fix|docs|chore|refactor|perf|BREAKING)" \
  | sed 's/^[a-f0-9]* //' \
  > CHANGELOG.md
```

**Fastlane changelog automation:**
```ruby
lane :generate_changelog do
  # Получение commits с последнего тега
  changelog = changelog_from_git_commits(
    commits_count: 20,
    pretty: "- %s",
    date_format: "short",
    match_lightweight_tag: false
  )
  
  # Запись в файл
  File.write("fastlane/metadata/ios/en-US/release_notes.txt", changelog)
  File.write("fastlane/metadata/android/en-US/changelogs/default.txt", changelog)
  
  UI.success("Changelog generated")
end
```

**GitLab CI:**
```yaml
generate_changelog:
  stage: build
  script:
    - |
      CHANGELOG=$(git log --oneline --no-merges $CI_COMMIT_BEFORE_SHA..$CI_COMMIT_SHA \
        | grep -E "^(feat|fix|docs|chore)" \
        | sed 's/^[a-f0-9]* //' \
        | head -20)
    - echo "$CHANGELOG" > CHANGELOG.md
  artifacts:
    paths:
      - CHANGELOG.md
    expire_in: 1 week

upload_testflight:
  stage: deploy_staging
  script:
    - bundle exec fastlane upload_to_testflight changelog: "$(cat CHANGELOG.md)"
  dependencies:
    - generate_changelog
```

### 3. Approval Gates в CI/CD

**GitLab CI: Manual Approval + Compliance**
```yaml
stages:
  - build
  - test
  - deploy_staging
  - approve_production
  - deploy_production

approve_production:
  stage: approve_production
  script:
    - echo "Manual approval required for production deployment"
  when: manual
  allow_failure: false
  only:
    - tags
```

### 4. Audit Trail для Production Releases

**Fastlane: Audit Logging**
```ruby
lane :deploy_with_audit do
  # Сбор метаданных
  metadata = {
    version: get_version_number(xcodeproj: "MyApp.xcodeproj"),
    build_number: get_build_number(xcodeproj: "MyApp.xcodeproj"),
    commit_sha: `git rev-parse HEAD`.strip,
    branch: `git branch --show-current`.strip,
    deployed_by: ENV["GITLAB_USER_LOGIN"] || `git config user.name`.strip,
    deployed_at: Time.now.utc.iso8601
  }
  
  # Запись в audit log
  File.open("audit/audit-log.json", "a") do |f|
    f.puts(metadata.to_json)
  end
  
  # Загрузка в artifact storage
  upload_to_testflight
  
  UI.success("Audit log created: #{metadata}")
end
```

**GitLab CI: Audit Trail**
```yaml
audit_release:
  stage: deploy_production
  script:
    - |
      cat <<EOF > release-audit.json
      {
        "version": "$VERSION",
        "build_number": "$BUILD_NUMBER",
        "commit_sha": "$CI_COMMIT_SHA",
        "branch": "$CI_COMMIT_BRANCH",
        "deployed_by": "$GITLAB_USER_NAME",
        "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
        "approvers": "$CI_APPROVERS",
        "artifacts": ["$IPA_PATH", "$DSYM_PATH"]
      }
      EOF
    - curl -X POST "$AUDIT_API/audit/release" \
        -H "Content-Type: application/json" \
        -d @release-audit.json
```

### 5. Release Evidence и SBOM

**Генерация Release Evidence:**
```json
{
  "version": "2.5.0",
  "build_number": "42",
  "commit_sha": "abc123def456",
  "timestamp": "2026-09-26T10:30:00Z",
  "tests_passed": true,
  "crash_free_rate": 0.995,
  "dependencies": {
    "ios": ["SwiftLint 0.54.0", "Alamofire 5.8.0"],
    "android": ["AGP 8.4.0", "Gradle 8.7"]
  },
  "artifacts": [
    "MyApp.ipa",
    "MyApp.dSYM.zip",
    "app-release.aab",
    "mapping.txt"
  ],
  "sbom": "sbom-2.5.0.json",
  "approvals": ["qa-lead", "pm", "security"],
  "rollback_plan": "rollback to 2.4.0 via TestFlight/Play Console"
}
```

**SBOM Generation (iOS):**
```bash
# Генерация SBOM через SPDX
swift package resolve
swift package show-dependencies --format json > sbom-ios.json
```

**SBOM Generation (Android):**
```bash
./gradlew dependencies --configuration releaseRuntimeClasspath \
  | grep -E "^\\+" \
  | sed 's/^\\+ //' > sbom-android.txt
```

### 6. Hotfix Workflow

**Git Flow Hotfix:**
```bash
# 1. Создание hotfix ветки от main
git checkout -b hotfix/critical-crash main

# 2. Исправление с минимальными изменениями
# ... исправления ...

# 3. Bump PATCH version только
fastlane bump_version bump_type:patch

# 4. Коммит с префиксом HOTFIX
git add .
git commit -m "hotfix: fix critical crash on iOS 17.4 launch"

# 5. Push и создание PR
git push origin hotfix/critical-crash main
gh pr create --base main --title "HOTFIX: Critical crash" --label "hotfix,sev1"

# 6. Fast-track approval + merge
gh pr merge --squash --delete-branch
```

**Hotfix Release Evidence:**
```json
{
  "type": "hotfix",
  "version": "2.5.1",
  "previous_version": "2.5.0",
  "reason": "SEV1: Critical crash on iOS 17.4 launch",
  "changes": ["fix: critical crash on launch"],
  "approved_by": "release-manager",
  "rollback_plan": "rollback to 2.5.0 via TestFlight/Play Console"
}
```

### 7. Compliance и Governance

**Change Management Process:**
1. **Request:** Product Manager создает Change Request
2. **Review:** Security/Compliance team reviews changes
3. **Approval:** Release Manager approves
4. **Deploy:** Automated deployment to staging → production
5. **Verify:** QA verifies production
6. **Audit:** Log all actions to immutable audit trail

**Compliance Requirements:**
- **GDPR:** Audit trail для всех изменений, затрагивающих PII
- **HIPAA:** Immutable audit log, access control, encryption at rest
- **PCI DSS:** Sign-off для всех changes в payment-related коде
- **SOX:** Separation of duties, approval chain documentation

### 8. Artifact Retention и Cleanup

**Очистка старых артефактов:**
```bash
# Удаление IPA старше 90 дней
find /opt/app/releases -name "*.ipa" -type f -mtime +90 -delete 2>/dev/null

# Удаление dSYM старше 90 дней
find /opt/app/releases -name "*.dSYM.zip" -type f -mtime +90 -delete 2>/dev/null

# Удаление SBOM старше 180 дней (архивировать перед удалением)
find /opt/app/releases -name "sbom-*.json" -type f -mtime +180 -exec gzip {} \;

# Очистка audit trail старше 1 года (архивировать)
find /var/log/audit/releases -name "*.json" -type f -mtime +365 -exec gzip {} \;
```

**Retention Policy Enforcement via launchd (macOS):**
```bash
# /usr/local/bin/release-cleanup.sh
#!/bin/bash
RETENTION_DAYS=90
ARCHIVE_DIR="/opt/app/archive"

find /opt/app/releases -type f \( -name "*.ipa" -o -name "*.aab" -o -name "*.dSYM.zip" \) -mtime +$RETENTION_DAYS -exec mv {} $ARCHIVE_DIR/ \;
```

---

## Операции и команды

### Version Management

```bash
# iOS: Текущая версия
xcrun agvtool what-version
# → 42

xcrun agvtool what-marketing-version
# → 2.5.0

# Android: Текущие версии
aapt dump badging app/build/outputs/bundle/release/app-release.aab | grep version
# → versionCode:'42'
# → versionName:'2.5.0'
```

### Changelog Generation

```bash
# Conventional Commits → Changelog
conventional-changelog -p angular -i CHANGELOG.md -s
# → Обновляет CHANGELOG.md на основе git history

# Или custom script
git log --oneline --no-merges v1.0.0..HEAD \
  | grep -E "^(feat|fix|docs|chore)" \
  | sed 's/^[a-f0-9]* //' \
  > RELEASE_NOTES.md
```

### Release Tagging

```bash
# Создание тега
git tag -a v2.5.0 -m "Release 2.5.0: New checkout flow"
git push origin v2.5.0

# Проверка тега
git tag -l "v*"
# → v2.5.0
```

### Artifact Retention: очистка и ротация релизных артефактов

```bash
# Удаление старых артефактов из CI workspace (GitLab)
# GitLab: настроить expire_in при upload

# Очистка артефактов старше 90 дней
find /opt/app/releases -type f -mtime +90 -delete 2>/dev/null

# Очистка audit trail старше 1 года (с архивацией)
find /var/log/audit/releases -type f -mtime +365 -exec gzip {} \;
```

### Управление retention policy

```bash
# Настройка автоматической очистки через launchd (macOS)
cat <<'EOF' | sudo tee /Library/LaunchDaemons/com.company.release-cleanup.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.company.release-cleanup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/release-cleanup.sh</string>
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
| **VersionCode already used** | Попытка загрузить билд с тем же versionCode | Увеличьте versionCode на 1 или используйте CI pipeline ID |
| **CFBundleVersion not increasing** | Build number не обновлен | Используйте `increment_build_number` или CI build number |
| **CFBundleShortVersionString invalid** | Неправильный формат SemVer | Формат: `MAJOR.MINOR.PATCH`, максимум 3 компонента |
| **Release rejected (metadata)** | Неполные или некорректные release notes | Заполните все обязательные поля в App Store Connect / Play Console |
| **Approval gate timeout** | Нет доступных approvers | Настройте escalation policy, добавьте backup approvers |
| **Changelog empty** | Нет conventional commits | Внедрите Conventional Commits convention в команду |
| **SBOM missing** | Не сгенерирован dependency manifest | Добавьте шаг генерации SBOM в release pipeline |
| **Audit log incomplete** | Пропущен шаг аудита | Добавьте audit step как обязательный stage в pipeline |
| **Hotfix conflict with main** | Параллельный release занял тот же versionCode | Используйте pre-assigned versionCode pool или sequential numbering |
| **Rollback not documented** | Нет rollback plan в Release Evidence | Добавьте обязательное поле rollback_plan в Release Evidence |
| **Artifact retention exceeded** | Диск переполнен старыми артефактами | Настройте автоматическую очистку через launchd/cron, архивируйте старые артефакты |
| **Certificate expired** | Сертификат подписи истек | Обновите сертификат, перевыпустите через Fastlane Match |
| **Build cache stale** | Кэш содержит артефакты от предыдущих версий | Очистите кэш при смене major версии инструментов |
| **Release evidence missing** | Пропущен шаг генерации Release Evidence | Добавьте обязательный шаг в pipeline, валидируйте наличие JSON |
| **Audit log not immutable** | Audit log можно изменить или удалить | Используйте append-only storage, ограничьте права доступа |

---

## Рекомендации

### Best Practices

- **Semantic Versioning:** Используйте SemVer для всех public-facing версий. Внутренний `versionCode`/`CFBundleVersion` всегда увеличивается.
- **Conventional Commits:** Внедрите соглашение о коммитах. Это основа для автоматического changelog и SemVer bump.
- **Automated Versioning:** Никогда не bump версии вручную. Используйте CI pipeline или Fastlane.
- **Release Gates:** Настройте multiple approval gates: automated (crash-free rate, security) + manual (QA, PM).
- **Audit Trail:** Все релизы должны быть auditable. Храните audit log минимум 1 год.
- **Release Evidence:** Генерируйте JSON-отчет для каждого релиза: коммиты, тесты, артефакты, approvers, rollback plan.
- **Hotfix Process:** Документируйте hotfix workflow. Hotfix должен проходить те же gates, что и обычный релиз, но с fast-track approval.
- **Toil Reduction:** Автоматизируйте версионирование, changelog, загрузку артефактов, audit logging.
- **Artifact Retention:** Настройте политику хранения IPA/AAB, dSYM, SBOM. Очищайте устаревшие данные регулярно.
- **Build Cache:** Используйте кэширование на уровне раннера и CI. Настройте TTL и invalidation based на версии инструментов.
- **Certificate Management:** Мониторьте срок действия сертификатов. Настройте алерты за 30/7/1 день до истечения.
- **Self-hosted Infrastructure:** Для enterprise используйте self-hosted artifact storage, audit log, certificate management.

### Edge Cases и ограничения

1. **App Store Review time:** Модерация может занимать 24–48 часов. Учитывайте это при планировании release window.
2. **Google Play processing:** Обработка AAB может занимать несколько часов. Не планируйте release на крайний срок.
3. **VersionCode exhaustion:** `versionCode` — 32-bit integer, максимум ~2.1 миллиарда. При очень частых релизах может быть исчерпан. Планируйте стратегию.
4. **CFBundleVersion collision:** App Store не разрешает повторные `CFBundleVersion`. Убедитесь что каждый бинарник имеет уникальный build number.
5. **Rollback delay:** Откат через новую версию требует модерации. Для быстрого отката используйте kill switch + phased release pause.
6. **Simultaneous releases:** Параллельные релизы из разных веток могут конфликтовать. Используйте sequential release queue.
7. **Compliance freeze:** В regulated industries могут быть freeze периоды (конец года, аудит). Планируйте release calendar accordingly.
8. **Hotfix coordination:** Hotfix должен быть совместим с текущим production backend. Координируйте с backend командой.
9. **Certificate expiration:** Сертификаты подписи имеют срок действия (1 год). Истечение блокирует все deployments. Настройте алерты.
10. **Network reliability:** Загрузка артефактов в магазины может занимать до 30 минут. Тестируйте скорость upload.

---

## Мониторинг и Observability

**Ключевые метрики:**
- **Release Frequency:** частота релизов (цель: > 1 в неделю)
- **Release Success Rate:** % успешных релизов (цель: > 95%)
- **Rollback Rate:** % релизов, завершившихся rollback (цель: < 5%)
- **MTTR (Release):** время от detection до rollback/fix (цель: < 4 часа)
- **Time to Market:** время от merge до production (цель: < 24 часа)
- **Approval Gate Time:** время ожидания одобрения (цель: < 4 часа)
- **Artifact Upload Time:** время загрузки IPA/AAB в магазины (цель: < 30 минут)
- **Certificate Expiry Alert Coverage:** % сертификатов с настроенными алертами (цель: 100%)

**Alert Rules:**
```yaml
groups:
  - name: release_management_alerts
    rules:
      - alert: ReleaseFailureRateHigh
        expr: rate(release_failures_total[1h]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Release failure rate too high"
      
      - alert: VersionCodeCollision
        expr: release_versioncode_duplicate_total > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "VersionCode collision detected"
      
      - alert: ApprovalGateTimeout
        expr: time() - approval_gate_created_timestamp > 86400
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Approval gate pending for > 24h"
      
      - alert: CertificateExpiryWarning
        expr: certificate_expiry_days < 7
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Signing certificate expires in < 7 days"
      
      - alert: ArtifactRetentionExceeded
        expr: disk_usage_percent{path="/opt/app/releases"} > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Artifact storage disk usage > 80%"
```

**Quality Gates:**
- Crash-free rate > 99% на staged rollout 1%
- No Critical/High CVE в новых зависимостях
- Все smoke-тесты пройдены
- Release Evidence сгенерирован и approved
- Audit trail записан
- Certificate валиден на момент deployment

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout, approval gates, rollback procedures.
- **[Feature Flags в мобильных приложениях](./feature-flags-mobile.md)** — Kill Switch, progressive delivery.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — hotfix workflow, MTTR, postmortem.
