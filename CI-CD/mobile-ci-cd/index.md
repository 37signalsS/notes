# Mobile CI/CD (iOS/Android): Архитектура и инфраструктура

## Определения

**Mobile CI/CD** — это специализированный процесс непрерывной интеграции и доставки мобильных приложений, который выступает связующим звеном между локальной разработкой и закрытыми экосистемами магазинов приложений (App Store, Google Play).

В отличие от Backend/Web CI/CD, мобильный цикл имеет уникальные характеристики:
*   **Зависимость от проприетарного «железа»:** Сборка iOS требует macOS и Xcode. Это диктует выбор между арендой специализированных облаков (Mac-as-a-Service) или поддержкой собственного парка Mac-серверов.
*   **Сложность жизненного цикла артефактов:** Артефакт (IPA/AAB) проходит через этапы компиляции, линковки, **подписи (Code Signing)** и упаковки. Любое нарушение на этапе подписи делает артефакт бесполезным для установки на реальные устройства.
*   **Дистрибуция через посредников:** Доставка (Delivery) происходит не на сервер компании, а в системы App Store Connect и Google Play Console, которые накладывают свои правила валидации и требуют прохождения ручного или автоматического ревью.

---

## Базовые концепции

### Стратегии ветвления в Mobile CI/CD

Выбор стратегии ветвления определяет частоту интеграции и сложность пайплайна. Подробное описание каждой модели (Git Flow, GitHub Flow, Trunk-Based, GitLab Flow, Forking) см. в **[Рабочие процессы в Git](../../Git/git_workflows.md)**.

**Влияние на Mobile CI/CD:**
- **Trunk-Based Development (рекомендуется):** минимум конфликтов, быстрые обратные циклы, пайплайн запускается на каждый PR.
- **GitFlow (legacy):** CI запускается на нескольких ветках одновременно, увеличивая нагрузку на инфраструктуру. Подходит для медленного релизного цикла (1 раз в месяц и реже).
- **GitHub Flow:** компромисс между простотой и контролем, релизы могут быть ручными.

### Архитектура конвейера (Build Lifecycle)

Типовой современный пайплайн (2025–2026) строится по модульному принципу:
1.  **Prepare:** Установка зависимостей, выбор версии SDK (`mise`, `asdf`), синхронизация сертификатов (`Fastlane Match`).
2.  **Lint & Static Analysis:** Проверка стиля кода (SwiftLint, Detekt), поиск уязвимостей и опечаток.
3.  **Build for Testing:** Сборка приложения специально для запуска тестов (ускоряет параллельный запуск).
4.  **Test:** Запуск Unit-тестов и UI-тестов на симуляторах или фермах реальных устройств (Firebase Test Lab).
5.  **Archive & Sign:** Создание финального билда и его подпись ключами дистрибуции.
6.  **Distribute:** Загрузка в системы бета-тестирования (TestFlight, Firebase App Distribution) или в релизные каналы.

### Типы пайплайнов

**PR Validation (phemeral):**
- Запускается на каждый Pull/Merge Request.
- Включает: lint, unit-тесты, сборку (без подписи), проверку размера артефакта.
- Время выполнения: < 10 минут (целевой KPI).
- Результат: блокирующий check для merge.

**Nightly Build (продолжительный):**
- Запускается раз в сутки (обычно ночью).
- Включает: полную сборку, UI-тесты на реальных устройствах, сканирование уязвимостей.
- Артефакты доступны для ручного тестирования.

**Release Pipeline (монолитный):**
- Запускается по тегу или ручному триггеру.
- Включает: финальную сборку, подпись, загрузку в TestFlight/Google Play, создание релиза в GitHub.
- Требует одобрения (manual approval) перед публикацией.

### Инфраструктура: macOS-раннеры

К 2026 году стандартом стал полный переход на архитектуру **Apple Silicon** (чипы M-серии).

| Тип раннера | Технические особенности | Сфера применения |
| :--- | :--- | :--- |
| **Apple Silicon (M2/M3/M4)** | Поддержка аппаратного ускорения виртуализации (Tart, Orka). Нативная работа симуляторов iOS. | Основные рабочие лошадки для быстрых сборок (< 10 мин). |
| **Intel macOS** | **Legacy.** Не поддерживают новые версии Xcode (начиная с Xcode 16/17). Медленный ввод-вывод. | Только для поддержки очень старых проектов (iOS < 12). |
| **Linux (Docker)** | Используется **только для Android** частей или Flutter/React Native (без iOS-сборки). | Сборка AAB/APK, линтинг, запуск Android-эмуляторов в headless-режиме. |

#### Облачные провайдеры (2026):
*   **GitHub Actions:** Раннеры `macos-14/15` (M-series). Популярны за счет интеграции с GitHub, но требуют тщательной настройки кэширования.
*   **Bitrise:** Специализированный Mobile DevOps лидер. Предлагает готовые шаги (Steps) и раннеры на базе M4 Pro.
*   **MacStadium / AWS Mac Instances:** Предоставляют «голое железо» или виртуализацию (Orka) для построения собственной инфраструктуры.
*   **Cirrus CI:** Облачный CI с нативной поддержкой macOS-контейнеров и конкурентной ценовой политикой.

---

## Практическая реализация

### 1. Требования (Prerequisites)

Для запуска мобильного CI/CD раннера «с нуля» необходимо:
- **macOS:** Актуальная версия (минимум Ventura/Sonoma для поддержки Xcode 15+).
- **Xcode:** Установленные Command Line Tools.
- **Java:** JDK 17 или 21 (для Android/Gradle).
- **Ruby + Bundler:** Для управления версией Fastlane.
- **Homebrew:** Для установки системных утилит.

**Проверка готовности окружения:**
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

### 2. Основные команды сборки

Хотя Fastlane является стандартом, важно понимать, что происходит «под капотом».

**iOS (xcodebuild):**
```bash
# Очистка и сборка архива
xcodebuild archive \
  -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -configuration Release \
  -archivePath ./build/MyApp.xcarchive \
  CODE_SIGNING_ALLOWED=NO # Если подпись происходит на отдельном шаге
# → ** ARCHIVE SUCCEEDED **

# Проверка созданного архива
ls -lh ./build/MyApp.xcarchive
# → MyApp.xcarchive  45M  2026-08-27 10:30

# Экспорт IPA из архива (с подписью)
xcodebuild -exportArchive \
  -archivePath ./build/MyApp.xcarchive \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath ./build/ipa
# → ** EXPORT SUCCEEDED **
# → ./build/ipa/MyApp.ipa
```

**Android (Gradle):**
```bash
# Сборка App Bundle (AAB) для Google Play
./gradlew bundleRelease \
  -Dorg.gradle.daemon=false \
  -Dorg.gradle.parallel=true
# → BUILD SUCCESSFUL in 2m 34s
# → 127 actionable tasks: 125 executed, 2 up-to-date

# Проверка созданного AAB
ls -lh app/build/outputs/bundle/release/app-release.aab
# → app-release.aab  42M  2026-08-27 10:35

# Сборка APK для отладки (без подписи)
./gradlew assembleDebug
# → BUILD SUCCESSFUL in 45s
# → 127 actionable tasks: 125 executed, 2 up-to-date
```

### 3. Стратегии кэширования

Эффективное кэширование экономит до 60% времени пайплайна.

*   **Swift Package Manager (SPM):** Кэшируйте `~/Library/Developer/Xcode/DerivedData` и `.build/`.
*   **Gradle:** Кэшируйте `~/.gradle/caches` и `~/.gradle/wrapper`.
*   **CocoaPods:** Фиксируйте `Podfile.lock` и кэшируйте папку `Pods/` (если она не в Git).
*   **Remote Caching (Bazel/Tuist):** Для сверхкрупных проектов рекомендуется использовать Tuist Binary Caching, чтобы скачивать уже скомпилированные модули вместо их пересборки.

**Пример кэширования в GitHub Actions:**
```yaml
- name: Cache SPM dependencies
  uses: actions/cache@v4
  with:
    path: |
      ~/Library/Developer/Xcode/DerivedData/**/SourcePackages
      .build/
    key: spm-${{ runner.os }}-${{ hashFiles('**/Package.resolved') }}
    restore-keys: |
      spm-${{ runner.os }}-

- name: Cache Gradle
  uses: actions/cache@v4
  with:
    path: |
      ~/.gradle/caches
      ~/.gradle/wrapper
    key: gradle-${{ runner.os }}-${{ hashFiles('**/*.gradle*', '**/gradle-wrapper.properties') }}
    restore-keys: |
      gradle-${{ runner.os }}-
```

**Проверка эффективности кэша:**
```bash
# Проверка размера кэша SPM
du -sh ~/Library/Developer/Xcode/DerivedData/**/SourcePackages
# → 1.2G

# Проверка времени сборки с кэшем и без
time xcodebuild build -scheme MyApp -destination 'platform=iOS Simulator,name=iPhone 16' 2>&1 | tail -5
# → С кэшем: 2m 15s
# → Без кэша: 8m 42s
```

### 4. Keystone-подход в инфраструктуре

**Keystone (обязательный компонент):** В гибридной инфраструктуре всегда есть один или несколько компонентов, без которых система не может функционировать. Для Mobile CI/CD к ним относятся:
- **Keychain-сервер:** Хранит сертификаты подписи (Fastlane Match).
- **Сервис аутентификации:** App Store Connect API Key или Google Play Service Account.
- **Сервис уведомлений:** Slack/Telegram для оповещения о статусе сборок.

**Стратегия защиты keystone:**
- Используйте резервные (hot-standby) инстансы для критичных сервисов.
- Мониторьте доступность keystone-компонентов отдельно от основного пайплайна.
- Автоматизируйте восстановление через Infrastructure as Code (Terraform/Ansible).

### 5. Полные примеры конфигураций пайплайнов

**GitHub Actions (iOS + Android):**
```yaml
name: Mobile CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  LC_ALL: "en_US.UTF-8"
  LANG: "en_US.UTF-8"

jobs:
  ios-build:
    runs-on: macos-15
    steps:
      - uses: actions/checkout@v4

      - name: Cache SPM
        uses: actions/cache@v4
        with:
          path: |
            ~/Library/Developer/Xcode/DerivedData/**/SourcePackages
            .build/
          key: spm-${{ runner.os }}-${{ hashFiles('**/Package.resolved') }}
          restore-keys: spm-${{ runner.os }}-

      - name: Install dependencies
        run: bundle install --path vendor/bundle

      - name: Setup certificates
        env:
          MATCH_PASSWORD: ${{ secrets.MATCH_PASSWORD }}
          MATCH_GIT_URL: ${{ secrets.MATCH_GIT_URL }}
          ASC_KEY_CONTENT: ${{ secrets.ASC_KEY_CONTENT }}
        run: |
          bundle exec fastlane setup_ci
          bundle exec fastlane match readonly

      - name: Build
        run: bundle exec fastlane build

      - name: Run tests
        run: bundle exec fastlane test

      - name: Upload artifacts
        if: github.ref == 'refs/heads/main'
        uses: actions/upload-artifact@v4
        with:
          name: ios-ipa
          path: build/*.ipa
          retention-days: 7

  android-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up JDK
        uses: actions/setup-java@v4
        with:
          java-version: '21'
          distribution: 'temurin'

      - name: Cache Gradle
        uses: actions/cache@v4
        with:
          path: |
            ~/.gradle/caches
            ~/.gradle/wrapper
          key: gradle-${{ runner.os }}-${{ hashFiles('**/*.gradle*', '**/gradle-wrapper.properties') }}
          restore-keys: gradle-${{ runner.os }}-

      - name: Decode keystore
        env:
          ANDROID_KEYSTORE_BASE64: ${{ secrets.ANDROID_KEYSTORE_BASE64 }}
        run: echo "$ANDROID_KEYSTORE_BASE64" | base64 -d > app/upload-key.jks

      - name: Build AAB
        run: ./gradlew bundleRelease

      - name: Cleanup keystore
        if: always()
        run: rm -f app/upload-key.jks

      - name: Upload AAB
        if: github.ref == 'refs/heads/main'
        uses: actions/upload-artifact@v4
        with:
          name: android-aab
          path: app/build/outputs/bundle/release/*.aab
          retention-days: 7
```

**GitLab CI (iOS):**
```yaml
variables:
  LC_ALL: "en_US.UTF-8"
  LANG: "en_US.UTF-8"

stages:
  - setup
  - test
  - build
  - deploy

.ios_base:
  tags:
    - ios
    - macos
  before_script:
    - bundle install --path vendor/bundle

setup_dependencies:
  extends: .ios_base
  stage: setup
  script:
    - bundle exec fastlane install_plugins
  cache:
    key:
      files:
        - Gemfile.lock
    paths:
      - vendor/bundle

unit_tests:
  extends: .ios_base
  stage: test
  script:
    - bundle exec fastlane test
  artifacts:
    reports:
      junit: fastlane/test_output/report.xml

build_ipa:
  extends: .ios_base
  stage: build
  script:
    - bundle exec fastlane release
  artifacts:
    paths:
      - ./build/*.ipa
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_TAG
```

---

## Валидация и проверка качества

После завершения сборки необходимо убедиться в целостности артефакта:
1.  **Проверка подписи (iOS):** `codesign -vvvv -d ./MyApp.app` — должна возвращать `valid on disk`.
2.  **Анализ размера артефакта:** Сравнение размера текущего билда с предыдущим. Резкий рост может указывать на утечку ресурсов или лишние зависимости.
3.  **Проверка метаданных:** Утилита `aapt2` (для Android) позволяет убедиться, что `versionCode` и `versionName` установлены корректно.
4.  **Проверка ProGuard/R8 (Android):** Убедитесь, что обфускация не сломала критичную функциональность.
5.  **Тестирование на реальном устройстве:** Установите IPA/APK на физическое устройство перед публикацией.

---

## Устранение проблем (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Missing private key** | Раннер не имеет доступа к Keychain или Match запущен без `readonly`. | Проверьте `MATCH_PASSWORD` и права доступа к репозиторию сертификатов. |
| **Xcode build timeout** | Зависший симулятор или нехватка ресурсов (RAM). | Используйте `--parallel` и убедитесь, что симуляторы закрываются после тестов (`xcrun simctl shutdown all`). |
| **Gradle OOM Error** | Недостаточно памяти для Gradle Daemon. | Увеличьте `org.gradle.jvmargs` в `gradle.properties` (например, `-Xmx4g`). |
| **No matching provisioning profile** | Несоответствие Bundle Identifier в проекте и в App Store Connect. | Проверьте `PRODUCT_BUNDLE_IDENTIFIER` в Xcode и App ID в Match. |
| **Google Play API 403** | Service Account не имеет прав в Play Console. | Добавьте Service Account с ролью "Release Manager" в Google Play Console. |
| **TestFlight upload failed** | Неверный API Key или ключ отозван в App Store Connect. | Проверьте `ASC_KEY_ID` и `ASC_ISSUER_ID`, убедитесь что ключ не отозван. |
| **CocoaPods install fails** | Конфликт версий зависимостей или устаревший кэш. | Выполните `pod cache clean --all` и `pod install --repo-update`. |
| **Android SDK not found** | Переменная `ANDROID_HOME` не задана или указывает на неверный путь. | Установите `ANDROID_HOME` или используйте `sdkmanager` для установки SDK. |

---

## Best Practices и рекомендации

### Безопасность
1.  **Секреты в CI:** Никогда не храните секреты в коде. Используйте Variables в CI/CD (GitHub Actions Secrets, GitLab CI Variables) или внешние сервисы (Vault, AWS Secrets Manager).
2.  **OIDC (OpenID Connect):** Используйте для беспарольного доступа к облакам (AWS/GCP) из GitHub/GitLab. Это исключает утечку статических ключей.
3.  **Ephemeral Runners:** Использование одноразовых виртуальных машин гарантирует, что секреты и «мусор» от предыдущих сборок не останутся на диске.
4.  **Защита Keychain:** Используйте временные связки ключей (Ephemeral Keychain) и удаляйте их после сборки.
5.  **Ротация ключей:** Регулярно обновляйте API-ключи и пароли (минимум 1 раз в год).

### Производительность
1.  **Параллелизация:** Запускайте линтинг, тесты и сборку параллельно (если это возможно).
2.  **Кэширование:** Настройте кэширование зависимостей (SPM, Gradle, CocoaPods).
3.  **Инкрементальные сборки:** Используйте инкрементальные билды для iOS (не полная пересборка).
4.  **Очистка:** Удаляйте артефакты предыдущих сборок перед новой (особенно DerivedData для iOS).
5.  **Мониторинг:** Отслеживайте время сборки и размер артефактов. Резкий рост может указывать на проблемы.

### Стабильность
1.  **Фиксация версий:** Всегда фиксируйте версии инструментов (Xcode, Ruby, Fastlane).
2.  **Retries:** Настройте автоматические повторные попытки для сетевых ошибок.
3.  **Time limit:** Устанавливайте разумные таймауты для джобов (особенно для UI-тестов).
4.  **Мониторинг зависимостей:** Отслеживайте уязвимости в зависимостях (Dependabot, Renovate).
5.  **Rollback:** Имейте возможность быстрого отката к предыдущей стабильной версии.

### Edge Cases и ограничения
1.  **Лимиты Apple:** Apple устанавливает лимиты на количество сертификатов (100 Development, 100 Distribution на команду).
2.  **Размер IPA:** App Store ограничивает размер приложения (200 МБ для OTA, 4 ГБ для загрузки через iTunes Connect).
3.  **Время сборки:** Сборка iOS-приложения может занимать до 30 минут на сложных проектах.
4.  **Параллелизация тестов:** UI-тесты могут конфликтовать при одновременном запуске на одном устройстве.
5.  **Сетевые задержки:** Загрузка артефактов в TestFlight/Google Play может занимать до 30 минут в часы пик.
6.  **Обновления Xcode:** Обновление Xcode может сломать существующие конфигурации подписи.

---

## SLA/SLO/SLI для Mobile CI/CD

### Определения

**SLI (Service Level Indicator)** — количественная метрика качества сервиса. Для Mobile CI/CD: время сборки, процент успешных сборок, размер артефакта.

**SLO (Service Level Objective)** — целевое значение SLI. Например: "95% сборок должны завершаться менее чем за 15 минут".

**SLA (Service Level Agreement)** — соглашение об уровне сервиса с бизнесом. Например: "Релиз будет доступен в TestFlight в течение 4 часов после merge в main".

### Ключевые SLI для Mobile CI/CD

| SLI | Описание | Целевое значение |
|:---|:---|:---|
| **Build Success Rate** | Процент успешных сборок | > 95% |
| **Build Duration** | Среднее время сборки | < 15 минут |
| **PR Validation Time** | Время проверки PR | < 10 минут |
| **Flaky Test Rate** | Процент "мигающих" тестов | < 2% |
| **Time to First Install (TTFI)** | Время от merge до TestFlight | < 2 часа |
| **Release Frequency** | Частота релизов | > 1 раза в неделю |
| **Rollback Time** | Время отката | < 30 минут |

### Мониторинг SLI

**Prometheus метрики:**
```yaml
# .gitlab-ci.yml - отправка метрик
report_sli:
  stage: .post
  script:
    - |
      # Build Duration
      echo "mobile_build_duration_seconds{project=\"$CI_PROJECT_NAME\",branch=\"$CI_COMMIT_BRANCH\"} $CI_JOB_DURATION" | \
      curl -X POST --data-binary @- http://localhost:9091/metrics/job/mobile_ci
      
      # Build Success
      echo "mobile_build_success{project=\"$CI_PROJECT_NAME\",branch=\"$CI_COMMIT_BRANCH\"} 1" | \
      curl -X POST --data-binary @- http://localhost:9091/metrics/job/mobile_ci
  when: always
```

**Grafana Dashboard:**
```json
{
  "panels": [
    {
      "title": "Build Duration",
      "targets": [{"expr": "mobile_build_duration_seconds"}],
      "thresholds": {"value": 900}
    },
    {
      "title": "Build Success Rate",
      "targets": [{"expr": "rate(mobile_build_success[5m]) * 100"}],
      "thresholds": {"value": 95}
    }
  ]
}
```

---

## Promotion Workflow (Dev → Staging → Production)

### Определения

**Promotion** — процесс продвижения сборки из одного окружения в другое (Dev → Staging → Production).

**Environment Protection Rules** — правила, ограничивающие доступ к определенным окружениям (manual approval, branch restrictions).

**Approval Gate** — этап, требующий ручного одобрения перед продолжением пайплайна.

### Promotion Flow

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

### GitHub Actions: Environment Protection

```yaml
name: iOS Deploy Pipeline

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      - name: Build
        run: xcodebuild build
      
  deploy_staging:
    needs: build
    runs-on: macos-14
    environment: staging
    steps:
      - name: Deploy to Staging
        run: |
          bundle exec fastlane deploy_testflight \
            --api_key ${{ secrets.ASC_KEY_CONTENT }} \
            --team_id ${{ secrets.APPLE_TEAM_ID }}
      
      - name: Run Smoke Tests
        run: |
          bundle exec fastlane test_smoke

  deploy_production:
    needs: deploy_staging
    runs-on: macos-14
    environment: 
      name: production
      url: https://appstore.com/company/app
    steps:
      - name: Deploy to Production
        run: |
          bundle exec fastlane deploy_appstore \
            --phased_release true
      
      - name: Notify
        uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {"text": "✅ iOS app deployed to App Store"}
```

### GitLab CI: Manual Approval

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

## Cost Optimization для Mobile CI/CD

### Текущие расходы

| Компонент | Стоимость | Оптимизация |
|:---|:---|:---|
| **GitHub-hosted Mac** | $0.08/мин | Параллелизация, кэширование |
| **Self-hosted Mac Mini** | $50-100/мес (оборудование) | Амортизация, энергопотребление |
| **TestFlight** | Бесплатно | - |
| **Google Play** | $25 (одноразово) | - |
| **Fastlane** | Бесплатно | - |

### Стратегии оптимизации

**1. Кэширование зависимостей:**
```yaml
# Экономия: 30-60% времени сборки
cache:
  key:
    files:
      - Gemfile.lock
      - Podfile.lock
  paths:
    - vendor/bundle
    - Pods/
```

**2. Параллелизация тестов:**
```yaml
# Экономия: 50-70% времени тестирования
test:
  parallel: 4
  script:
    - bundle exec fastlane test --parallel_count 4
```

**3. Инкрементальные сборки:**
```yaml
# Экономия: 40-60% времени сборки
build:
  script:
    - xcodebuild build -incremental
```

**4. Очистка артефактов:**
```yaml
# Экономия: дисковое пространство
cleanup:
  script:
    - rm -rf ~/Library/Developer/Xcode/DerivedData
    - rm -rf ~/Library/Caches/org.swift.swiftpm
```

### ROI Analysis

| Мероприятие | Стоимость | Экономия | ROI |
|:---|:---|:---|:---|
| **Self-hosted Mac** | $500 (оборудование) | $200/мес | 2.5 мес |
| **Кэширование** | 0 | 30% времени сборки | ∞ |
| **Параллелизация** | 0 | 50% времени тестирования | ∞ |

---

## GitOps для Mobile CI/CD

### Определения

**GitOps** — подход, при котором Git является единственным источником правды (SSoT) для всей инфраструктуры и конфигураций.

**Pull-based Deployment** — модель, при которой компоненты самостоятельно проверяют Git на наличие изменений и применяют их.

### GitOps в Mobile Context

| Компонент | GitOps Implementation |
|:---|:---|
| **CI/CD конфигурация** | `.github/workflows/`, `.gitlab-ci.yml` в Git |
| **Fastlane конфигурация** | `fastlane/Fastfile` в Git |
| **Feature Flags** | Remote Config (Firebase) с version control |
| **Certificates** | Match Repository (Git-based) |
| **Infrastructure** | Terraform/Ansible для Mac provisioning |

### Пример: GitOps для Feature Flags

```yaml
# .github/workflows/sync-feature-flags.yml
name: Sync Feature Flags

on:
  push:
    paths:
      - 'feature-flags/*.json'

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Deploy to Firebase
        run: |
          firebase remoteconfig:set \
            --template feature-flags/defaults.json \
            --project my-app
```

---

## Artifact Repository для Mobile

### Определения

**Artifact Repository** — централизованное хранилище артефактов сборки (IPA, AAB, APK) с поддержкой версионирования и доступа.

### Типы хранилищ

| Тип | Инструмент | Использование |
|:---|:---|:---|
| **Git LFS** | Git Large File Storage | Маленькие артефакты (< 100 МБ) |
| **Nexus Repository** | Sonatype Nexus | Организации с собственной инфраструктурой |
| **Artifactory** | JFrog Artifactory | Enterprise, поддержка всех форматов |
| **GitHub Releases** | GitHub | Open source, малые проекты |
| **GitLab Package Registry** | GitLab | Интеграция с GitLab CI |

### Fastlane: Загрузка в Artifact Repository

```ruby
# Загрузка в Nexus
lane :upload_to_nexus do
  # Загрузка IPA
  system("curl -u admin:password -T ./build/MyApp.ipa http://nexus.company.com/repository/ios-releases/")
  
  # Загрузка dSYM
  system("curl -u admin:password -T ./build/MyApp.app.dSYM.zip http://nexus.company.com/repository/ios-releases/")
end

# Загрузка в Artifactory
lane :upload_to_artifactory do
  system("curl -u admin:password -T ./build/MyApp.ipa https://artifactory.company.com/ios-releases/")
end
```

### GitHub Actions: Сохранение артефактов

```yaml
save_artifacts:
  runs-on: macos-14
  steps:
    - name: Save IPA
      uses: actions/upload-artifact@v4
      with:
        name: MyApp-${{ github.sha }}
        path: ./build/*.ipa
        retention-days: 30
    
    - name: Save dSYM
      uses: actions/upload-artifact@v4
      with:
        name: MyApp-dSYM-${{ github.sha }}
        path: ./build/*.dSYM.zip
        retention-days: 90
```

---

## Дополнительная информация

### См. также:
*   **[GitLab CI/CD для iOS и macOS: Настройка](./gitlab-ios-ci.md)**
*   **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)**
*   **[Android CI/CD: Keystore и публикация](./android-ci-cd.md)**
*   **[Автоматизация через Fastlane](./fastlane-guide.md)**
*   **[Feature Flags для мобильных приложений](./feature-flags-mobile.md)**
*   **[Deployment Strategies для мобильных](./deployment-strategies-mobile.md)**
*   **[Incident Response для мобильных](./incident-response-mobile.md)**
*   **[Security Scanning в Mobile CI/CD](./security-scanning-mobile.md)**
*   **[Disaster Recovery для Mobile CI/CD](./disaster-recovery-mobile-ci.md)**
*   **[Оптимизация кэширования в GitLab CI](../GitLab_CI/Advanced/gitlab_ci_caching/cache_scenarios.md#сценарий-5--java-maven--gradle)**
