# Mobile CI/CD (iOS/Android): Архитектура и инфраструктура

## Определения

**Mobile CI/CD** — специализированный процесс непрерывной интеграции и доставки мобильных приложений, связывающий локальную разработку с экосистемами App Store и Google Play. В отличие от backend/web-пайплайнов, мобильный цикл включает управление проприетарной инфраструктурой, криптографическую подпись артефактов и взаимодействие с закрытыми API магазинов приложений.

**Ephemeral Runner (эфемерный раннер)** — исполнитель CI/CD, создаваемый под конкретную задачу и уничтожаемый после выполнения. Исключает накопление состояния, «сноубол» зависимостей и утечки секретов между джобами. Для Mobile CI/CD эфемерность особенно критична из-за требований подписи и сертификатов.

**Golden Image (золотой образ)** — предварительно настроенный шаблон macOS, содержащий стандартный набор инструментов (Xcode, JDK, Ruby, Fastlane, симуляторы). Обеспечивает идемпотентность развертывания и исключает «дрейф» конфигурации между раннерами.

**Idempotency (идемпотентность)** — свойство операции, при котором повторное выполнение дает тот же результат, что и первое. В Mobile CI/CD применяется к provisioning раннеров, установке зависимостей и управлению сертификатами.

**Toil (рутинный труд)** — ручная, повторяющаяся, масштабирующаяся работа, не дающая долгосрочной ценности. В Mobile CI/CD toil проявляется в ручном обновлении Provisioning Profiles, реагировании на исчерпание лимитов Apple и «тушении пожаров» при падении сборок.

**Error Budget (бюджет ошибок)** — допустимый объём сбоев, связывающий надёжность и скорость поставки. Для Mobile CI/CD применяется к стабильности пайплайна, доле flaky-тестов и времени восстановления после инцидентов.

---

## Базовые концепции

### Влияние стратегии ветвления на Mobile CI/CD

Выбор стратегии ветвления определяет частоту интеграции и сложность пайплайна. Подробное описание каждой модели см. в **[Рабочие процессы в Git](../../Git/git_workflows.md)**.

- **Trunk-Based Development (рекомендуется):** минимум конфликтов, быстрые обратные циклы, пайплайн запускается на каждый PR.
- **GitFlow (legacy):** CI запускается на нескольких ветках одновременно, увеличивая нагрузку на инфраструктуру. Подходит для медленного релизного цикла.
- **GitLab Flow:** компромисс между простотой и контролем.

### Архитектура пайплайна (Build Lifecycle)

Типовой современный пайплайн строится по модульному принципу:

1.  **Prepare:** Установка зависимостей, выбор версии SDK (`mise`, `asdf`), синхронизация сертификатов (Fastlane Match).
2.  **Lint & Static Analysis:** Проверка стиля кода (SwiftLint, Detekt), поиск уязвимостей и опечаток.
3.  **Build for Testing:** Сборка приложения специально для запуска тестов (ускоряет параллельный запуск).
4.  **Test:** Запуск Unit-тестов и UI-тестов на симуляторах или фермах реальных устройств.
5.  **Archive & Sign:** Создание финального билда и его подпись ключами дистрибуции.
6.  **Distribute:** Загрузка в системы бета-тестирования (TestFlight, Google Play tracks) или в релизные каналы.

### Типы пайплайнов

**PR Validation (эфемерный):**
- Запускается на каждый Pull/Merge Request.
- Включает: lint, unit-тесты, сборку (без подписи), проверку размера артефакта.
- Время выполнения: < 10 минут (целевой KPI).
- Результат: блокирующий check для merge.

**Nightly Build (продолжительный):**
- Запускается раз в сутки.
- Включает: полную сборку, UI-тесты на реальных устройствах, сканирование уязвимостей.
- Артефакты доступны для ручного тестирования.

**Release Pipeline (монолитный):**
- Запускается по тегу или ручному триггеру.
- Включает: финальную сборку, подпись, загрузку в TestFlight/Google Play, создание релиза.
- Требует одобрения (manual approval) перед публикацией.

### Инфраструктура: macOS-раннеры

К 2026 году стандартом стал полный переход на архитектуру **Apple Silicon** (чипы M-серии). Инфраструктура строится на собственных (self-hosted) мощностях без привязки к внешним облачным провайдерам.

| Тип раннера | Технические особенности | Сфера применения |
| :--- | :--- | :--- |
| **Apple Silicon (M2/M3/M4)** | Поддержка аппаратного ускорения виртуализации (Tart, Orka). Нативная работа симуляторов iOS. NVMe SSD для быстрого ввода-вывода. | Основные рабочие лошадки для быстрых сборок (< 10 мин). |
| **Intel macOS** | **Legacy.** Не поддерживают новые версии Xcode (начиная с Xcode 16/17). Медленный ввод-вывод. | Только для поддержки очень старых проектов (iOS < 12). |
| **Linux (Docker)** | Используется **только для Android** частей или Flutter/React Native (без iOS-сборки). | Сборка AAB/APK, линтинг, запуск Android-эмуляторов в headless-режиме. |

#### Формы собственности инфраструктуры

| Форма | Описание | Когда выбирать |
| :--- | :--- | :--- |
| **Dedicated Runners** | Физические Mac mini или Mac Studio, выделенные под конкретную команду/проект. | Высокий объем сборок, требования к изоляции, predictable latency. |
| **Virtualized Pool (Tart/Orka)** | Эфемерные виртуальные машины на базе гипервизора Apple. Обеспечивают чистоту окружения и параллелизм. | Необходимость изоляции между джобами, частые пересборки окружения. |
| **Shared Runners** | Общий пул раннеров, используемый несколькими командами через CI/CD-платформу (GitLab Runner). | Мелкие команды, нестабильная нагрузка, экономия ресурсов. |

### SRE-подход к Mobile CI/CD

**Принципы применения SRE:**

- **Error Budget для пайплайна:** Договоритесь с командой о допустимом проценте проваленных сборок (например, 5% в месяц). При исчерпании бюджета фокус смещается на стабилизацию пайплайна, а не на новые фичи.
- **MTTR (Mean Time To Repair):** Среднее время восстановления после инцидента пайплайна. Целевое значение: < 30 минут для blocking-инцидентов.
- **Toil Reduction:** Автоматизируйте рутинные операции (обновление сертификатов, очистка кэша, ротация логов). Измеряйте долю toil в работе команды.
- **Flaky Test Management:** Ведите реестр «мигающих» тестов. Устанавливайте SLA на починку (например, 5 рабочих дней). Flaky-тесты подрывают доверие к пайплайну.
- **Runbook'и:** Для каждого типичного сбоя (исчерпание лимитов Apple, падение Keychain, зависание симулятора) должно быть пошаговое руководство по восстановлению.

### Sysadmin: управление парком macOS-раннеров

**Provisioning и конфигурация:**

macOS-раннеры требуют специализированного подхода к администрированию:

- **Установка пакет:** Homebrew (`/opt/homebrew` на Apple Silicon, `/usr/local` на Intel) используется для установки Xcode Command Line Tools, JDK, Fastlane, симуляторов.
- **Системные сервисы:** Используется `launchd` (аналог `systemd` в macOS). Раннер CI (GitLab Runner) регистрируется как системный сервис с автозапуском и автоматическим восстановлением после падения.
- **Политика SIP (System Integrity Protection):** Ограничивает изменения защищённых разделов диска. Для установки некоторых инструментов может потребоваться отключение SIP на dedicated-раннерах (не рекомендуется для shared-пулов).
- **Управление дисками:** DerivedData и кэши могут занимать десятки гигабайт. Настройте log rotation и регулярную очистку через `launchd` или `cron`.
- **Мониторинг:** Установите `prometheus_node_exporter` или `datadog-agent` на каждый раннер для сбора метрик CPU, RAM, disk I/O, температуры. Мониторинг критичен для proactive-замены «умирающего» железа.

---

## Практическая реализация

### Требования (Prerequisites)

Для запуска macOS-раннера «с нуля»:
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

### Основные команды сборки

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
```

### Стратегии кэширования

Эффективное кэширование экономит до 60% времени пайплайна.

- **Swift Package Manager (SPM):** Кэшируйте `~/Library/Developer/Xcode/DerivedData` и `.build/`.
- **Gradle:** Кэшируйте `~/.gradle/caches` и `~/.gradle/wrapper`.
- **CocoaPods:** Фиксируйте `Podfile.lock` и кэшируйте папку `Pods/`.
- **Remote Caching (Bazel/Tuist):** Для крупных проектов рекомендуется Tuist Binary Caching.

**Пример кэширования в GitLab CI:**
```yaml
cache:
  key: spm-$CI_COMMIT_REF_SLUG
  paths:
    - ~/Library/Developer/Xcode/DerivedData/**/SourcePackages
    - .build/

# Отдельный кэш для Gradle
cache:
  key: gradle-$CI_COMMIT_REF_SLUG
  paths:
    - ~/.gradle/caches
    - ~/.gradle/wrapper
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

### Keystone-компоненты инфраструктуры

В гибридной инфраструктуре всегда есть компоненты, без которых система не может функционировать. Для Mobile CI/CD к ним относятся:

- **Keychain-сервер:** Хранит сертификаты подписи (Fastlane Match).
- **Сервис аутентификации:** App Store Connect API Key или Google Play Service Account.
- **Сервис уведомлений:** Slack/Telegram для оповещения о статусе сборок.

**Стратегия защиты keystone:**
- Используйте резервные (hot-standby) инстансы для критичных сервисов.
- Мониторьте доступность keystone-компонентов отдельно от основного пайплайна.
- Автоматизируйте восстановление через Infrastructure as Code.

### Примеры конфигураций пайплайнов

**GitLab CI (iOS + Android):**
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

.android_base:
  tags:
    - android
    - linux
  before_script:
    - ./gradlew --version

setup_dependencies:
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
  stage: test
  parallel:
    matrix:
      - include:
          - extends: .ios_base
            script: bundle exec fastlane test
          - extends: .android_base
            script: ./gradlew test

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

build_aab:
  extends: .android_base
  stage: build
  script:
    - ./gradlew bundleRelease
  artifacts:
    paths:
      - app/build/outputs/bundle/release/*.aab
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_TAG
```

Подробные примеры для iOS: **[GitLab CI/CD для iOS и macOS](./gitlab-ios-ci.md)**.

### Provisioning macOS-раннера (Sysadmin Guide)

Для reproducible-окружения используйте подход Infrastructure as Code. Ниже — пример базового provisioning Mac mini/Studio для роли CI-раннера.

**Шаг 1: Базовая конфигурация системы**
```bash
# Установка Homebrew (Apple Silicon)
/bin/bash -c "$(curl -fsSL https://brew.sh/install)"

# Установка базовых пакетов
brew install git ruby mise jq

# Настройка Ruby через mise
mise use ruby@3.2 --global

# Установка Fastlane
gem install fastlane

# Установка Xcode Command Line Tools
xcode-select --install
```

**Шаг 2: Установка симуляторов iOS**
```bash
# Скачивание дополнительных симуляторов (пример для Xcode 16)
xcodebuild -downloadAllSimulators

# Проверка доступных runtime
xcrun simctl list runtimes available
# → iOS 18.0 (18.0.0) - com.apple.CoreSimulator.SimRuntime.iOS-18-0
```

**Шаг 3: Регистрация как CI-раннер (GitLab Runner example)**
```bash
# Установка GitLab Runner
brew install gitlab-runner

# Регистрация с тегами для маршрутизации
sudo gitlab-runner register \
  --url https://gitlab.company.com/ \
  --token $RUNNER_TOKEN \
  --tag-list macos,arm64,xcode-16 \
  --run-untagged=false \
  --locked=false \
  --executor shell

# Запуск как системный сервис (launchd)
sudo gitlab-runner install --user gitlab-runner --working-directory /srv/gitlab-runner
sudo gitlab-runner start
```

**Шаг 4: Автоматическая очистка**
```bash
# Создание скрипта очистки
cat <<'EOF' | sudo tee /usr/local/bin/ci-cleanup.sh
#!/bin/bash
# Очистка DerivedData старше 7 дней
find ~/Library/Developer/Xcode/DerivedData -type d -mtime +7 -exec rm -rf {} + 2>/dev/null

# Очистка кэша SPM старше 7 дней
find ~/Library/Caches/org.swift.swiftpm -type f -mtime +7 -delete 2>/dev/null

# Очистка логов Xcode
find ~/Library/Logs -type f -mtime +7 -delete 2>/dev/null
EOF

sudo chmod +x /usr/local/bin/ci-cleanup.sh

# Добавление в launchd для ежедневного запуска
cat <<'EOF' | sudo tee /Library/LaunchDaemons/com.company.ci-cleanup.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.company.ci-cleanup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/ci-cleanup.sh</string>
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

sudo launchctl load /Library/LaunchDaemons/com.company.ci-cleanup.plist
```

---

## Операции и команды

### Проверка состояния окружения

```bash
# Версия Xcode иBuild
xcodebuild -version
# → Xcode 16.2
# → Build version 16C5032a

# Доступные симуляторы
xcrun simctl list devices available | grep -i iphone
# → iPhone 16, iPhone 16 Pro, iPhone 15 и т.д.

# Статус симуляторов
xcrun simctl list devices | grep -E "Booted|Shutdown"
# → iPhone 16 (Booted)
# → iPhone 16 Pro (Shutdown)

# Проверка Java
java -version
# → openjdk version "21.0.2" 2024-01-16

# Проверка Ruby и Bundler
ruby --version && bundle --version
# → ruby 3.2.2 (2024-04-23 revision c31463cd45) [arm64-darwin23]
# → Bundler version 2.5.6

# Проверка сертификатов в Keychain
security find-identity -v -p codesigning
# → 1) ABCD1234 "Apple Distribution: Company (TEAMID)" (valid)
```

### Диагностика сборки

```bash
# Детальный лог сборки iOS
xcodebuild -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  build | xcbeautify
# → Build succeeded

# Проверка размера артефакта
du -sh ./build/MyApp.xcarchive
# → 45M

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

---

## Валидация и проверка качества

После завершения сборки убедитесь в целостности артефакта:

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
| **Runner offline (GitLab)** | Сервис раннера не запущен или устарел. | Проверьте `systemctl status gitlab-runner` или `launchctl list | grep run`. Обновите бинарник. |
| **Disk full on runner** | DerivedData, кэши или логи заполнили диск. | Выполните cleanup-скрипт или расширьте диск. Настройте автоматическую очистку. |
| **Simulator boot loop** | Поврежденный runtime симулятора. | Удалите проблемный симулятор через `xcrun simctl delete <UDID>` и пересоздайте. |

---

## Best Practices и рекомендации

### Безопасность

1.  **Секреты в CI:** Никогда не храните секреты в коде. Используйте Variables в CI/CD или внешние менеджеры секретов (HashiCorp Vault).
2.  **OIDC (OpenID Connect):** Используйте для динамической аутентификации без статических ключей. Это исключает утечку долгоживущих токенов.
3.  **Ephemeral Runners:** Использование одноразовых виртуальных машин гарантирует, что секреты и «мусор» от предыдущих сборок не останутся на диске.
4.  **Защита Keychain:** Используйте временные связки ключей (Ephemeral Keychain) и удаляйте их после сборки.
5.  **Ротация ключей:** Регулярно обновляйте API-ключи и пароли (минимум 1 раз в год).

### Производительность

1.  **Параллелизация:** Запускайте линтинг, тесты и сборку параллельно (если это возможно).
2.  **Кэширование:** Настройте кэширование зависимостей (SPM, Gradle, CocoaPods).
3.  **Инкрементальные сборки:** Используйте инкрементальные билды для iOS.
4.  **Очистка:** Удаляйте артефакты предыдущих сборок перед новой (особенно DerivedData для iOS).
5.  **Мониторинг:** Отслеживайте время сборки и размер артефактов. Резкий рост может указывать на проблемы.

### Стабильность

1.  **Фиксация версий:** Всегда фиксируйте версии инструментов (Xcode, Ruby, Fastlane, JDK).
2.  **Retries:** Настройте автоматические повторные попытки для сетевых ошибок.
3.  **Time limit:** Устанавливайте разумные таймауты для джобов (особенно для UI-тестов).
4.  **Мониторинг зависимостей:** Отслеживайте уязвимости в зависимостях (Dependabot, Renovate).
5.  **Rollback:** Имейте возможность быстрого отката к предыдущей стабильной версии.

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

**Toil Reduction:** Автоматизируйте рутинные операции (обновление сертификатов, очистка кэша, ротация логов). Измеряйте долю toil в работе команды.

**Flaky Test Management:** Ведите реестр «мигающих» тестов. Устанавливайте SLA на починку (например, 5 рабочих дней). Flaky-тесты подрывают доверие к пайплайну.

**Runbook'и:** Для каждого типичного сбоя (исчерпание лимитов Apple, падение Keychain, зависание симулятора) должно быть пошаговое руководство по восстановлению.

Внедрите базовый мониторинг для CI-инфраструктуры:

- **Prometheus + Grafana:** Сбор метрик с раннеров (CPU, RAM, disk, network) через `node_exporter`.
- **CI-специфичные метрики:** Длительность сборок, доля успешных джоб, время в очереди, размер артефактов.
- **Алерты:** Настройте оповещения при падении успешности сборок ниже порога (например, < 95% за 1 час) или превышении времени сборки (например, > 20 минут).

---

## Edge Cases и ограничения

1.  **Лимиты Apple:** Apple устанавливает лимиты на количество сертификатов (100 Development, 100 Distribution на команду).
2.  **Размер IPA:** App Store ограничивает размер приложения (200 МБ для OTA, 4 ГБ для загрузки через iTunes Connect).
3.  **Время сборки:** Сборка iOS-приложения может занимать до 30 минут на сложных проектах.
4.  **Параллелизация тестов:** UI-тесты могут конфликтовать при одновременном запуске на одном устройстве.
5.  **Сетевые задержки:** Загрузка артефактов в TestFlight/Google Play может занимать до 30 минут в часы пик.
6.  **Обновления Xcode:** Обновление Xcode может сломать существующие конфигурации подписи.
7.  **Apple Silicon vs Intel:** Некоторые старые зависимости и инструменты могут требовать Rosetta 2 или перекомпиляцию под arm64.
8.  **SIP ограничения:** На macOS с включенным SIP нельзя модифицировать защищённые разделы, что влияет на способ установки некоторых инструментов.

---

## Promotion Workflow (Dev → Staging → Production)

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

### Environment Protection

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

## См. также

*   **[Mobile Test Automation](./testing-mobile.md)** — XCUITest, Espresso, Appium, device farm, visual regression.
*   **[Crash Reporting и Symbolication](./crash-reporting-mobile.md)** — dSYM/ProGuard mapping, Sentry integration, crash-free rate.
*   **[Release Management для Mobile](./release-management-mobile.md)** — SemVer, automated changelog, approval gates, audit trail.
*   **[Dependency Management](./dependencies-mobile.md)** — SPM/CocoaPods/Gradle, private registries, lock files, reproducible builds.
*   **[Backend ↔ Mobile Integration](./backend-integration-mobile.md)** — API contracts, backward compatibility, schema migration, mock services.
*   **[App Size Optimization](./app-size-optimization.md)** — App Thinning, Dynamic Delivery, resource shrinking, size monitoring.
*   **[Beta Testing Automation](./beta-testing-mobile.md)** — TestFlight, Google Play tracks, self-hosted distribution, beta feedback.
*   **[GitLab CI/CD для iOS и macOS](./gitlab-ios-ci.md)** — настройка GitLab Runner, shell executor, ephemeral keychain, масштабирование пулов.
*   **[Gradle и Android Build System](./gradle-android-build-system.md)** — deep dive: build scans, remote cache, signingConfigs, AGP, daemon, performance tuning.
*   **[Xcode Build System](./xcode-build-system.md)** — xcconfig, schemes, targets, build phases, multi-target проекты.
*   **[iOS Extensions CI/CD](./ios-extensions-ci-cd.md)** — Watch, TV, Siri, Share, Today extensions: сборка, подпись, multi-target пайплайны.
*   **[Cross-Platform Mobile CI/CD](./cross-platform-mobile-ci.md)** — Flutter, React Native: multi-platform пайплайны в GitLab.
*   **[Mobile App Attestation](./mobile-app-attestation.md)** — Google Play Integrity, Apple App Attest, jailbreak/root detection.
*   **[Push Notification Testing](./push-notification-testing.md)** — тестирование APNS/FCM в CI.
*   **[Deep Link Testing](./deep-linking-testing.md)** — Universal Links, App Links, custom URL schemes.
*   **[Supply Chain Security для Mobile](./supply-chain-security-mobile.md)** — cosign/Sigstore, SLSA provenance, SBOM для IPA/AAB.
*   **[Test Data Management](./test-data-management-mobile.md)** — управление тестовыми данными, factories, cleanup.
*   **[Runner Management](./runner-management-mobile.md)** — Tart/Orka, симуляторы, эмуляторы, disk cleanup, cost optimization.
*   **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)** — детали Provisioning Profiles, Fastlane Match и Keychain management.
*   **[Android CI/CD: Keystore и публикация](./android-ci-cd.md)** — управление Upload Key, App Signing и Google Play App Signing.
*   **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins и интеграция с iOS/Android пайплайнами.
