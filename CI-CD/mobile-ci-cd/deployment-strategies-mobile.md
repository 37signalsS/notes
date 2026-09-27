# Deployment Strategies для мобильных приложений

## Определения

**Deployment Strategy** — подход к развертыванию обновлений приложения среди пользователей, минимизируя риски и обеспечивая непрерывность сервиса. В мобильной экосистеме deployment ограничен механизмами магазинов приложений (App Store, Google Play) и требует специфических подходов к контролю распространения.

**Phased Release** — поэтапное обновление приложения: сначала небольшой процент пользователей, затем увеличение до 100%. Основной механизм App Store Connect. В отличие от server-side canary, mobile phased release управляет не трафиком, а доступностью артефакта для скачивания.

**Staged Rollout** — аналог phased release для Google Play с возможностью остановки на любом этапе при обнаружении проблем. Управляется через Google Play Console API или Fastlane Supply.

**Release Gate** — критерий, который должен быть выполнен перед продвижением на следующий этап rollout. В mobile контексте: crash-free rate, ANR rate, бизнес-метрики, время uptime.

**Rollback** — откат к предыдущей стабильной версии приложения при обнаружении критических проблем. В mobile ecosystems rollback означает публикацию предыдущей версии как нового релиза или использование kill switch.

**Hotfix** — экстренное исправление, выпускаемое в production в кратчайшие сроки. В мобильном контексте hotfix требует прохождения той же подписи и ревью, что и обычный релиз, что увеличивает MTTR по сравнению с backend.

**MTTR (Mean Time To Recover)** — среднее время восстановления после инцидента deployment. Для mobile включает время сборки, подписи, модерации магазина и распространения обновления.

**MTTA (Mean Time To Acknowledge)** — среднее время между срабатыванием алерта о проблеме с новым релизом и принятием решения дежурным инженером.

**Error Budget (Deployment)** — допустимый объем проблемных релизов в течение месяца. При исчерпании бюджета — фокус на улучшение качества сборок и тестирования вместо новых фич.

**Blameless Postmortem (Deployment)** — разбор deployment-инцидента без персональной ответственности, фокусирующийся на системных причинах: недостаточное тестирование, нарушение release gates, деградация метрик.

---

## Базовые концепции

### Ограничения Mobile Deployments

В отличие от server-side deployments, мобильные deployments имеют фундаментальные ограничения:

1. **Нет мгновенного отката:** Пользователи контролируют обновление приложения. Новая версия распространяется постепенно, и невозможно мгновенно вернуть всех пользователей на старую версию.
2. **Зависимость от магазинов:** App Store и Google Play выступают gatekeeper'ами. Модерация, обработка сборок и распространение занимают время.
3. **Однородность артефакта:** Все пользователи получают один и тот же бинарный файл (IPA/AAB). Невозможно различать конфигурации для разных сегментов без feature flags.
4. **Срок подписи:** Сертификаты подписи имеют срок действия (1 год). Истечение сертификата блокирует все deployments.
5. **Задержка распространения:** Even с phased release, пользователи могут получать обновление с задержкой из-за кэширования магазинов, настроек автообновления и сетевых условий.

### Сравнение Mobile и Server-Side Deployment Strategies

Общая теория стратегий развертывания (Blue-Green, Canary, Rolling Update) описана в **[Стратегиях развертывания](../Core_Concepts/deployment_strategies.md)** и **[Сравнении стратегий](../Deployment_Strategies/comparison.md)**. Ниже — адаптация под мобильные ограничения:

| Стратегия | Server-Side | Mobile аналог | Ограничения |
|:---|:---|:---|:---|
| **Blue-Green** | Два сервера, переключение трафика | Невозможно напрямую: пользователи должны обновить приложение | Требует ручного управления версиями |
| **Canary** | 1% трафика на новый сервер | Phased Release: 1% пользователей получают обновление | Зависит от настроек автообновления |
| **Rolling** | Обновление по одному серверу | Staged Rollout: постепенное увеличение процента | Нет контроля над конкретными пользователями |
| **Feature Flags** | Включение на сервере | Включение через remote configuration service | Требует интеграции SDK в приложение |
| **Rollback** | Мгновенное переключение трафика | Публикация предыдущей версии или kill switch | Задержка распространения обновления |

### Жизненный цикл Mobile Deployment

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│     Dev      │───►│   Staging    │───►│  Production  │───►│  Monitoring  │
│  (Local)     │    │  (TestFlight/│    │  (Store)     │    │  (Rollout)   │
│              │    │   Internal)  │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
       │                   │                   │                   │
       ▼                   ▼                   ▼                   ▼
  Fastlane CI        Internal Track      Phased Release      Metrics Review
  build + test       1% → 100%           1% → 25% → 100%     Crash rate, ANR
```

### Phased Release в App Store Connect

**Этапы iOS Phased Release:**
| Этап | Пользователи | Длительность | Действие |
|:---|:---|:---|:---|
| 1 | 1% | День 1 | Мониторинг crash rate |
| 2 | 2% | День 2 | Проверка ANR, бизнес-метрик |
| 3 | 5% | День 3 | Аудит пользовательских отзывов |
| 4 | 10% | День 4 | Оценка производительности |
| 5 | 20% | День 5 | Полная валидация |
| 6 | 50% | День 6 | Подготовка к полному rollout |
| 7 | 100% | День 7 | Завершение phased release |

**Особенности:**
- Phased Release можно приостановить и возобновить в любой момент.
- Пользователи в первых этапах не могут откатить обновление самостоятельно.
- App Store не позволяет автоматический откат — требуется публикация предыдущей версии как нового релиза.

### Staged Rollout в Google Play

**Этапы Android Staged Rollout:**
| Этап | Пользователи | Рекомендация |
|:---|:---|:---|
| 1 | 1% | Мониторинг crash-free rate |
| 2 | 5% | Проверка ANR, Crashes |
| 3 | 20% | Аудит ключевых метрик |
| 4 | 50% | Полный rollout |
| 5 | 100% | Завершение |

**Особенности:**
- Staged Rollout можно остановить в любой момент.
- Приостановка rollout останавливает распространение, но не откатывает уже получивших пользователей.
- Для полного отката требуется публикация предыдущей версии с увеличенным versionCode.

### SRE-подход к Mobile Deployment

**Принципы:**

- **MTTR как KPI:** Измеряйте время от решения о деплое до полного распространения обновления. Для mobile учитывайте не только техническое время, но и время модерации магазина.
- **Error Budget для релизов:** Договоритесь о допустимом количестве проблемных релизов в месяц. При исчерпании бюджета — фокус на улучшение тестирования, а не на новые фичи.
- **Toil Reduction:** Автоматизируйте управление phased release, мониторинг метрик, уведомление команд. Ручное управление rollout через UI магазина — это toil.
- **Observability:** Каждый релиз должен иметь полный trace: build → upload → phased release → metrics → decision.
- **Release Gates:** Автоматизируйте проверку crash rate, ANR, бизнес-метрик перед продвижением на следующий этап rollout.

### Sysadmin: управление окружением для deployment

macOS-раннеры для deployment требуют дополнительной конфигурации:

- **Fastlane с доступом к магазинам:** Убедитесь, что ASC Key / Service Account JSON актуальны и имеют необходимые права.
- **Тестирование на реальных устройствах:** Настройте ферму устройств или симуляторы для smoke-тестирования перед upload.
- **Артефакт-хранилище:** Настройте хранение IPA/AAB артефактов с retention policy и доступом для emergency rollback.
- **Сертификаты подписи:** Мониторьте срок действия сертификатов. Настройте алерты за 30/7/1 день до истечения.
- **Скорость upload:** Тестируйте скорость загрузки артефактов в TestFlight/Google Play. Медленный upload может задержать начало phased release.

---

## Практические сценарии

### 1. Fastlane: Phased Release для iOS

```ruby
# fastlane/Fastfile

default_platform(:ios)

platform :ios do
  desc "Deploy to TestFlight with phased release"
  lane :deploy_phased do
    app_store_connect_api_key(...)
    match(type: "appstore", readonly: true)
    increment_build_number(xcodeproj: "MyApp.xcodeproj")
    build_app(scheme: "MyApp")
    
    upload_to_testflight(
      skip_waiting_for_build_processing: true,
      phased_release: true,
      distribute_external: false
    )
    
    # Ожидание обработки Apple
    sleep(300)
    
    # Запуск phased release
    start_phased_release(
      build_number: Actions.latest_testflight_build_number
    )
  end

  desc "Pause phased release"
  lane :pause_phased do
    app_store_connect_api_key(...)
    
    build_number = latest_testflight_build_number
    
    pause_phased_release(
      build_number: build_number
    )
    
    UI.message("Phased release PAUSED for build #{build_number}")
  end

  desc "Resume phased release"
  lane :resume_phased do
    app_store_connect_api_key(...)
    
    build_number = latest_testflight_build_number
    
    resume_phased_release(
      build_number: build_number
    )
    
    UI.message("Phased release RESUMED for build #{build_number}")
  end

  desc "Rollback to previous build"
  lane :rollback_ios do
    app_store_connect_api_key(...)
    
    previous_build = get_previous_build_number(
      app_identifier: "com.company.app"
    )
    
    build_app(scheme: "MyApp")
    upload_to_testflight(
      build_number: previous_build,
      skip_waiting_for_build_processing: true,
      phased_release: true
    )
  end
end
```

### 2. Fastlane: Staged Rollout для Android

```ruby
# fastlane/Fastfile

default_platform(:android)

platform :android do
  desc "Deploy to Internal Testing"
  lane :deploy_internal do
    supply(
      track: "internal",
      aab: "app/build/outputs/bundle/release/app-release.aab",
      json_key_data: ENV["ANDROID_SERVICE_ACCOUNT_JSON"]
    )
  end

  desc "Start staged rollout 1%"
  lane :start_staged_rollout do
    supply(
      track: "production",
      rollout: "0.01",
      json_key_data: ENV["ANDROID_SERVICE_ACCOUNT_JSON"]
    )
  end

  desc "Increase rollout to 25%"
  lane :increase_rollout_25 do
    supply(
      track: "production",
      rollout: "0.25",
      json_key_data: ENV["ANDROID_SERVICE_ACCOUNT_JSON"]
    )
  end

  desc "Full rollout 100%"
  lane :full_rollout do
    supply(
      track: "production",
      rollout: "1.0",
      json_key_data: ENV["ANDROID_SERVICE_ACCOUNT_JSON"]
    )
  end

  desc "Rollback Android"
  lane :rollback_android do
    previous_version = get_previous_version_code
    
    supply(
      track: "production",
      version_code: previous_version,
      json_key_data: ENV["ANDROID_SERVICE_ACCOUNT_JSON"]
    )
  end
end
```

### 3. GitLab CI: Automated Phased Release Pipeline

```yaml
stages:
  - deploy
  - monitor

variables:
  ROLLOUT_PERCENTAGE: "0.01"

deploy_phased_release:
  stage: deploy
  tags:
    - macos
    - arm64
  cache:
    paths:
      - vendor/bundle
  script:
    - bundle install
    - bundle exec fastlane deploy_phased
    - sleep 300
    - bundle exec fastlane start_phased_release --percentage $ROLLOUT_PERCENTAGE
  only:
    - main
  when: manual
  environment:
    name: production

monitor_phased_release:
  stage: monitor
  tags:
    - linux
    - docker
  script:
    - |
      for hour in 1 2 4 8 12 24; do
        CRASH_RATE=$(curl -s "https://api.example.com/crash-rate?app=ios&hours=$hour")
        if (( $(echo "$CRASH_RATE > 0.01" | bc -l) )); then
          echo "Crash rate too high: $CRASH_RATE"
          exit 1
        fi
      done
    - bundle exec fastlane pause_phased
  dependencies:
    - deploy_phased_release
```

### 4. GitLab CI: Android Staged Rollout

```yaml
stages:
  - build
  - test
  - deploy_internal
  - deploy_staged
  - promote

build_android:
  stage: build
  script:
    - ./gradlew bundleRelease
  artifacts:
    paths:
      - app/build/outputs/bundle/release/

test_android:
  stage: test
  script:
    - ./gradlew test
  artifacts:
    reports:
      junit: app/build/test-results/**/*.xml

deploy_internal:
  stage: deploy_internal
  script:
    - bundle exec fastlane deploy_internal
  only:
    - main

deploy_staged:
  stage: deploy_staged
  script:
    - bundle exec fastlane start_staged_rollout
  when: manual
  only:
    - tags

promote_to_25:
  stage: promote
  script:
    - bundle exec fastlane increase_rollout_25
  when: manual

promote_to_100:
  stage: promote
  script:
    - bundle exec fastlane full_rollout
  when: manual
```

### 5. Monitoring во время Phased Release

```ruby
# fastlane/actions/monitor_rollout.rb
module Fastlane
  module Actions
    class MonitorRollout < Action
      def self.run(params)
        app = params[:app]
        platform = params[:platform]
        
        # Получение метрик
        crash_rate = get_crash_rate(app: app, platform: platform)
        anr_rate = get_anr_rate(app: app, platform: platform)
        
        # Пороговые значения
        CRASH_THRESHOLD = 0.01 # 1%
        ANR_THRESHOLD = 0.005 # 0.5%
        
        if crash_rate > CRASH_THRESHOLD
          UI.error("CRASH RATE TOO HIGH: #{crash_rate}%")
          Actions.pause_phased unless params[:dry_run]
          return false
        end
        
        if anr_rate > ANR_THRESHOLD
          UI.error("ANR RATE TOO HIGH: #{anr_rate}%")
          Actions.pause_phased unless params[:dry_run]
          return false
        end
        
        UI.success("Metrics OK - Crash: #{crash_rate}%, ANR: #{anr_rate}%")
        true
      end

      def self.available_options
        [
          FastlaneCore::ConfigItem.new(key: :app, description: "App bundle ID"),
          FastlaneCore::ConfigItem.new(key: :platform, description: "ios or android"),
          FastlaneCore::ConfigItem.new(key: :dry_run, description: "Don't actually pause", default_value: false)
        ]
      end
    end
  end
end
```

### 6. Promotion Workflow (Dev → Staging → Production)

**Promotion** — процесс продвижения сборки из одного окружения в другое (Dev → Staging → Production).

**Environment Protection Rules** — правила, ограничивающие доступ к определенным окружениям (manual approval, branch restrictions).

**Approval Gate** — этап, требующий ручного одобрения перед продолжением пайплайна.

```yaml
stages:
  - build
  - deploy_staging
  - approve_production
  - deploy_production

build:
  stage: build
  tags:
    - macos
    - arm64
  script:
    - xcodebuild build
  only:
    - main

deploy_staging:
  stage: deploy_staging
  tags:
    - macos
    - arm64
  script:
    - bundle exec fastlane deploy_testflight \
        --api_key $ASC_KEY_CONTENT \
        --team_id $APPLE_TEAM_ID
    - bundle exec fastlane test_smoke
  environment:
    name: staging
  only:
    - main

approve_production:
  stage: approve_production
  script:
    - echo "Manual approval required"
  when: manual
  only:
    - main
  environment:
    name: production

deploy_production:
  stage: deploy_production
  tags:
    - macos
    - arm64
  script:
    - bundle exec fastlane deploy_appstore --phased_release true
  needs:
    - approve_production
  environment:
    name: production
    url: https://appstore.com/company/app
  only:
    - main
```

---

## Операции и команды

### Управление Phased Release (iOS)

```bash
# Проверка статуса phased release
fastlane spaceauth -u user@company.com
# → Вставьте код в App Store Connect

# Получение информации о текущем билде
fastlane latest_testflight_build_number
# → 42

# Пауза phased release
fastlane pause_phased_release build_number:42
# → Phased release paused for build 42

# Возобновление phased release
fastlane resume_phased_release build_number:42
# → Phased release resumed for build 42

# Проверка статуса сборки в App Store Connect
fastlane app_store_connect_api_key(...)
fastlane get_build_info(app_identifier: "com.company.app")
```

### Управление Staged Rollout (Android)

```bash
# Проверка текущего rollout
fastlane supply track:production --json_key ./service-account.json
# → Current rollout: 25%

# Увеличение rollout до 50%
fastlane supply track:production rollout:0.5 --json_key ./service-account.json
# → Rollout increased to 50%

# Полный rollout
fastlane supply track:production rollout:1.0 --json_key ./service-account.json
# → Rollout completed: 100%

# Остановка rollout
fastlane supply track:production rollout:0.5 --json_key ./service-account.json
# → Rollout paused at 50%
```

### Проверка артефактов перед deployment

```bash
# Проверка подписи IPA
codesign -vvvv -d ./build/ipa/MyApp.ipa
# → Valid on disk
# → Authority=Apple Distribution: Company (TEAMID)

# Проверка метаданных AAB
aapt2 dump badging app/build/outputs/bundle/release/app-release.aab | grep version
# → versionCode:'42'
# → versionName:'2.5.0'

# Проверка размера артефакта
du -sh ./build/ipa/MyApp.ipa app/build/outputs/bundle/release/app-release.aab
# → 45M
# → 42M

# Проверка Provisioning Profile
security cms -D -i ./embedded.mobileprovision
# → <plist version="1.0"><dict>...</dict></plist>
```

### Rollback команды

```bash
# iOS: Получение предыдущей версии
fastlane get_previous_build_number(app_identifier: "com.company.app")
# → 41

# Android: Получение предыдущего versionCode
fastlane get_previous_version_code
# → 41

# Быстрый откат через ADB (для тестирования)
adb install -r app-previous.apk
# → Performing Streamed Install
# → Success
```

### Health Check команды

```bash
# Проверка Xcode
xcodebuild -version
# → Xcode 16.2
# → Build version 16C5032a

# Проверка сертификатов
security find-identity -v -p codesigning
# → 1) ABCD1234 "Apple Distribution: Company (TEAMID)" (valid)

# Проверка Fastlane
fastlane --version
# → fastlane 2.220.0

# Проверка Java
java -version
# → openjdk version "21.0.2" 2024-01-16
```

---

## Устранение проблем

| Ошибка | Причина | Решение | MTTR impact |
|:---|:---|:---|:---|
| **Phased release не запускается** | Build еще обрабатывается Apple, недостаточные права API Key | Проверьте статус обработки в App Store Connect, убедитесь что ASC Key активен | 30 минут |
| **Crash rate растет во время rollout** | Регрессия в новой версии, несовместимость с устройствами | Остановите phased release, соберите crash logs, подготовьте hotfix | 2 часа |
| **Staged rollout застрял на 1%** | Нет достаточного числа пользователей для статистики, проблема с распространением | Увеличьте процент rollout, проверьте логи Google Play Console | 1 час |
| **TestFlight upload failed** | Неверный API Key, ключ отозван, сертификат истек | Проверьте ASC_KEY_ID и ASC_ISSUER_ID, обновите сертификат | 1 час |
| **Google Play API 403** | Service Account не имеет прав, JSON ключ неверный | Проверьте права в Google Play Console, обновите ключ | 30 минут |
| **Rollback не работает** | Отсутствует предыдущая версия, versionCode не увеличен | Подготовьте предыдущий бинарник, увеличьте versionCode | 2 часа |
| **Provisioning Profile mismatch** | Bundle ID не совпадает, профиль истек | Проверьте PRODUCT_BUNDLE_IDENTIFIER, обновите через Match | 30 минут |
| **Code signing failed** | Сертификат не найден, Keychain заблокирован | Проверьте setup_ci_keychain в Fastfile, импортируйте сертификат | 30 минут |
| **Artifact size too large** | Превышен лимит App Store (200 MB OTA, 4 GB iTunes Connect) | Оптимизируйте ресурсы, включите App Thinning, проверьте On-Demand Resources | 1 час |
| **Сертификат подписи истек** | Срок действия сертификата закончился | Обновите сертификат в App Store Connect / Google Play Console, перевыпустите через Fastlane Match | 4 часа |
| **Модерация отклонена** | Нарушение guidelines, техническая проблема | Проверьте письмо Apple/Google, исправьте проблему, перезагрузите бинарник | 24 часа |
| **Build processing завис** | Apple обрабатывает сборку дольше ожидаемого | Проверьте статус в App Store Connect, подождите или перезагрузите бинарник | 2 часа |
| **ANR rate растет после rollout** | Проблема с производительностью на новых устройствах | Остановите rollout, профилируйте ANR, подготовьте hotfix | 4 часа |
| **Crash-free rate упал ниже 90%** | Критическая регрессия в новой версии | Немедленная остановка rollout, активация kill switch, подготовка rollback | 1 час |
| **Feature Flags не работают** | SDK не инициализирован, конфигурация не загружена | Проверьте интеграцию remote configuration SDK, убедитесь в загрузке конфигурации при старте | 30 минут |
| **ADB install failed** | Несовместимость версии Android, поврежденный APK | Проверьте minSdkVersion, пересоберите артефакт | 30 минут |

---

## Best Practices

### SRE: метрики и наблюдаемость

**Ключевые SLI для Mobile Deployment:**

| SLI | Описание | Целевое значение |
|:---|:---|:---|
| **Deployment Success Rate** | % успешных deployments | > 95% |
| **Rollback Time** | Время от решения до начала отката | < 30 минут |
| **Time to Full Rollout** | Время от upload до 100% распространения | < 7 дней |
| **Crash-free Rate** | % сессий без crash | > 99% |
| **MTTR Deployment** | Среднее время восстановления после deployment-инцидента | < 2 часа |
| **Error Budget (Deployment)** | Допустимое количество проблемных релизов | 5% в месяц |
| **MTTA** | Время от алерта до принятия решения | < 15 минут |

**Error Budget для релизов:** Договоритесь с командой о допустимом проценте проблемных релизов (например, 5% в месяц). При исчерпании бюджета фокус смещается на улучшение тестирования, а не на новые фичи.

**Toil Reduction:** Автоматизируйте управление phased release, мониторинг метрик, уведомление команд. Ручное управление rollout через UI магазина — это toil.

**Release Gates:** Автоматизируйте проверку crash rate, ANR, бизнес-метрик перед продвижением на следующий этап rollout.

### Sysadmin: инфраструктура

1. **Runner Provisioning:** Убедитесь, что macOS-раннеры имеют актуальные сертификаты, Fastlane и доступ к магазинам.
2. **Artifact Storage:** Настройте reliable хранилище IPA/AAB с retention policy и доступом для emergency rollback.
3. **Certificate Monitoring:** Мониторьте срок действия сертификатов подписи. Настройте алерты за 30/7/1 день до истечения.
4. **Network Reliability:** Тестируйте скорость upload в TestFlight/Google Play. Медленный upload задержит начало phased release.
5. **Cleanup:** Регулярно очищайте старые артефакты и логи. Настройте автоматическую очистку через launchd/cron.

### Безопасность

1. **Секреты в CI:** Никогда не храните секреты в коде. Используйте Variables в CI/CD или внешние менеджеры секретов.
2. **OIDC:** Используйте для динамической аутентификации без статических ключей.
3. **Ephemeral Runners:** Одноразовые раннеры гарантируют, что секреты не остаются на диске.
4. **Защита Keychain:** Используйте временные связки ключей и удаляйте их после сборки.
5. **Ротация ключей:** Периодически обновляйте API-ключи и пароли (минимум 1 раз в год).

### Производительность

1. **Кэширование:** Настройте кэширование зависимостей (SPM, Gradle, CocoaPods).
2. **Параллелизация:** Запускайте линтинг, тесты и сборку параллельно.
3. **Инкрементальные сборки:** Используйте инкрементальные билды для iOS.
4. **Очистка:** Удаляйте артефакты предыдущих сборок перед новой.

### Стабильность

1. **Фиксация версий:** Всегда фиксируйте версии инструментов (Xcode, Ruby, Fastlane, JDK).
2. **Retries:** Настройте автоматические повторные попытки для сетевых ошибок.
3. **Time limit:** Устанавливайте разумные таймауты для джобов.
4. **Мониторинг зависимостей:** Отслеживайте уязвимости в зависимостях.
5. **Rollback plan:** Имейте протестированный план быстрого отката.

### Edge Cases и ограничения

1. **Одновременные failures:** Если раннер и сертификаты выходят из строя одновременно — восстанавливайте приоритетно сертификаты.
2. **Apple лимиты:** Apple устанавливает лимиты на количество сертификатов (100 Development, 100 Distribution на команду).
3. **Сертификаты expiration:** Сертификаты подписи имеют срок действия (1 год). Настройте алерты за 30/7/1 день до истечения.
4. **Модерация App Store:** Модерация может занимать до 24-48 часов. Учитывайте это при планировании release.
5. **Google Play Review:** Аналогично App Store, review может занять время. Plan accordingly.
6. **Сетевые задержки:** Загрузка артефактов может занимать до 30 минут в часы пик.
7. **Пользовательский контроль:** Пользователи могут отложить обновление. Phased release не гарантирует 100% распространение за 7 дней.
8. **Feature Flags ограничения:** Встроенные feature flags (iOS原生) ограничены по сравнению с dedicated remote configuration service. Для сложных сценариев используйте отдельный service.

### Мониторинг и Observability

**Ключевые метрики:**
- **Deployment Frequency:** частота релизов
- **Deployment Success Rate:** % успешных deployments
- **Rollback Rate:** % deployments, завершившихся rollback
- **Time to Deploy:** время от merge до полного rollout
- **Crash-free Rate:** % сессий без crash после release
- **MTTR:** время восстановления после deployment-инцидента

**Alert Rules:**
```yaml
groups:
  - name: deployment_alerts
    rules:
      - alert: DeploymentCrashRateHigh
        expr: deployment_crash_rate > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Crash rate too high after deployment"
      
      - alert: DeploymentRollbackNeeded
        expr: deployment_anr_rate > 0.005
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "ANR rate exceeds threshold, consider rollback"
      
      - alert: DeploymentStuck
        expr: deployment_rollout_progress == 0
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Phased release stuck, no progress for 1 hour"
```

**Quality Gates:**
- Crash-free rate > 99% перед продвижением на следующий этап
- ANR rate < 0.5%
- Отсутствие Critical/High CVE в новых зависимостях
- Все smoke-тесты пройдены

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — процедуры реагирования на deployment-инциденты, MTTR, postmortem.
- **[Feature Flags в мобильных приложениях](./feature-flags-mobile.md)** — kill switch, progressive delivery, observability.
