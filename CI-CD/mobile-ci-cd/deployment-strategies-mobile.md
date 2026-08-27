# Deployment Strategies для мобильных приложений

## Определения

**Deployment Strategy** — подход к развертыванию обновлений приложения среди пользователей, минимизируя риски и обеспечивая непрерывность сервиса.

**Phased Release** — поэтапное обновление приложения: сначала небольшой процент пользователей, затем увеличение до 100%. Основной механизм App Store и Google Play.

**Staged Rollout** — аналог phased release с возможностью остановки на любом этапе, если обнаружены проблемы.

**Rollback** — откат к предыдущей стабильной версии приложения при обнаружении критических проблем.

---

## Базовые концепции

### Стратегии для Mobile (отличия от Server-Side)

| Стратегия | Server-Side | Mobile |
|:---|:---|:---|
| **Blue-Green** | Два сервера, переключение трафика | Невозможно: пользователи должны обновить приложение |
| **Canary** | 1% трафика на новый сервер | Фаза 1: 1% пользователей получают обновление |
| **Rolling** | Обновление по одному серверу | Фазовое обновление через магазины |
| **Feature Flags** | Включение на сервере | Включение через Remote Config |

### Процесс обновления Mobile App

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Dev → QA    │───►│ Beta/Test    │───►│  Production  │
│  (Internal)  │    │ Flight       │    │  (Store)     │
└──────────────┘    └──────────────┘    └──────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
  Fastlane CI        TestFlight/      Phased Release
  build + test       Internal Track   1% → 25% → 100%
```

### Phased Release в App Store Connect

**Этапы iOS Phased Release:**
| Этап | Пользователи | Длительность |
|:---|:---|:---|
| 1 | 1% | День 1 |
| 2 | 2% | День 2 |
| 3 | 5% | День 3 |
| 4 | 10% | День 4 |
| 5 | 20% | День 5 |
| 6 | 50% | День 6 |
| 7 | 100% | День 7 |

**Управление через Fastlane:**
```ruby
# Загрузка с включенным phased release
upload_to_testflight(
  skip_waiting_for_build_processing: true,
  phased_release: true
)

# Откат phased release (приостановка)
lane :pause_release do
  app_store_connect_api_key(...)
  
  # Получение информации о текущем билде
  build_info = latest_testflight_build_number
  
  # Пауза phased release
  pause_phased_release(
    build_number: build_info
  )
end
```

### Staged Rollout в Google Play

**Этапы Android Staged Rollout:**
| Этап | Пользователи | Рекомендация |
|:---|:---|:---|
| 1 | 1% | Мониторинг crash rate |
| 2 | 5% | Проверка ANR |
| 3 | 20% | Аудит ключевых метрик |
| 4 | 50% | Полный rollout |
| 5 | 100% | Завершение |

**Управление через Fastlane Supply:**
```ruby
# Загрузка с staged rollout
supply(
  track: "production",
  aab: "app-release.aab",
  rollout: "0.1", # 1%
  json_key_data: ENV["GCP_SERVICE_ACCOUNT_JSON"]
)

# Увеличение rollout
lane :increase_rollout do
  supply(
    track: "production",
    rollout: "0.5", # 50%
    json_key_data: ENV["GCP_SERVICE_ACCOUNT_JSON"]
  )
end

# Полный rollout
lane :full_release do
  supply(
    track: "production",
    rollout: "1.0", # 100%
    json_key_data: ENV["GCP_SERVICE_ACCOUNT_JSON"]
  )
end
```

---

## Практическая реализация

### 1. GitHub Actions: Automated Phased Release Pipeline

```yaml
name: iOS Phased Release

on:
  workflow_dispatch:
    inputs:
      rollout_percentage:
        description: 'Rollout percentage (0.01-1.0)'
        required: true
        default: '0.01'

jobs:
  deploy:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Ruby
        uses: ruby/setup-ruby@v1
        with:
          ruby-version: '3.2'
          bundler-cache: true
      
      - name: Deploy to TestFlight
        env:
          ASC_KEY_ID: ${{ secrets.ASC_KEY_ID }}
          ASC_ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          ASC_KEY_CONTENT: ${{ secrets.ASC_KEY_CONTENT }}
        run: |
          bundle exec fastlane deploy_testflight
      
      - name: Wait for Processing
        run: sleep 300
      
      - name: Start Phased Release
        run: |
          bundle exec fastlane start_phased_release \
            --percentage ${{ github.event.inputs.rollout_percentage }}

  monitor:
    needs: deploy
    runs-on: ubuntu-latest
    strategy:
      matrix:
        hour: [1, 2, 4, 8, 12, 24]
    steps:
      - name: Check Crash Rate
        run: |
          CRASH_RATE=$(curl -s "https://api.example.com/crash-rate?app=ios&hours=${{ matrix.hour }}")
          if (( $(echo "$CRASH_RATE > 0.01" | bc -l) )); then
            echo "Crash rate too high: $CRASH_RATE"
            exit 1
          fi
      
      - name: Pause if Issues Detected
        if: failure()
        run: |
          bundle exec fastlane pause_phased_release
```

### 2. GitLab CI: Android Staged Rollout

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
    - ./gradlew assembleRelease
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
    - bundle exec fastlane supply track:internal
  only:
    - main

deploy_staged:
  stage: deploy_staged
  script:
    - bundle exec fastlane supply track:production rollout:0.01
  when: manual
  only:
    - tags

promote_to_25:
  stage: promote
  script:
    - bundle exec fastlane supply track:production rollout:0.25
  when: manual

promote_to_100:
  stage: promote
  script:
    - bundle exec fastlane supply track:production rollout:1.0
  when: manual
```

### 3. Fastlane: Полный цикл Staged Rollout

```ruby
# fastlane/Fastfile

default_platform(:ios)

platform :ios do
  desc "Deploy to TestFlight with phased release"
  lane :deploy_testflight do
    app_store_connect_api_key(...)
    match(type: "appstore", readonly: true)
    increment_build_number(xcodeproj: "MyApp.xcodeproj")
    build_app(scheme: "MyApp")
    
    upload_to_testflight(
      skip_waiting_for_build_processing: true,
      phased_release: true
    )
  end

  desc "Increase rollout percentage"
  lane :promote_rollout do |options|
    percentage = options[:percentage] || "1.0"
    
    app_store_connect_api_key(...)
    
    # Получение текущего build_number
    build_number = latest_testflight_build_number
    
    # Обновление rollout
    update_phased_release(
      build_number: build_number,
      percentage: percentage.to_f
    )
    
    slack(message: "Rollout increased to #{percentage}%")
  end

  desc "Pause phased release"
  lane :pause_release do
    app_store_connect_api_key(...)
    
    build_number = latest_testflight_build_number
    
    pause_phased_release(
      build_number: build_number
    )
    
    slack(message: "Phased release PAUSED for build #{build_number}")
  end

  desc "Resume phased release"
  lane :resume_release do
    app_store_connect_api_key(...)
    
    build_number = latest_testflight_build_number
    
    resume_phased_release(
      build_number: build_number
    )
    
    slack(message: "Phased release RESUMED for build #{build_number}")
  end
end
```

### 4. Мониторинг во время Phased Release

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
          Actions.pause_release unless params[:dry_run]
          return false
        end
        
        if anr_rate > ANR_THRESHOLD
          UI.error("ANR RATE TOO HIGH: #{anr_rate}%")
          Actions.pause_release unless params[:dry_run]
          return false
        end
        
        UI.success("Metrics OK - Crash: #{crash_rate}%, ANR: #{anr_rate}%")
        return true
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

### 5. Rollback сценарии

**iOS Rollback через App Store Connect:**
```ruby
# Откат к предыдущему билду
lane :rollback_ios do
  app_store_connect_api_key(...)
  
  # Получение предыдущего билда
  previous_build = get_previous_build_number(
    app_identifier: "com.company.app"
  )
  
  # Откат через TestFlight
  # Примечание: App Store не позволяет автоматический откат,
  # необходимо отправить предыдущую версию как новый билд
  build_app(scheme: "MyApp")
  upload_to_testflight(
    build_number: previous_build,
    skip_waiting_for_build_processing: true
  )
end
```

**Android Rollback через Google Play:**
```ruby
# Откат через Google Play Console
lane :rollback_android do
  supply(
    track: "production",
    version_code: get_previous_version_code,
    json_key_data: ENV["GCP_SERVICE_ACCOUNT_JSON"]
  )
end

# Быстрый откат через ADB (для тестирования)
lane :quick_rollback do
  system("adb install -r app-previous.apk")
end
```

---

## Дополнительная информация

### Decision Matrix

| Критерий | Phased Release | Feature Flags | A/B Testing |
|:---|:---|:---|:---|
| **Скорость** | Медленная (7 дней) | Мгновенная | Мгновенная |
| **Контроль** | Высокий | Очень высокий | Высокий |
| **Откат** | Остановка rollout | Выключение флага | Переключение варианта |
| **Метрики** | Crash rate, ANR | Конверсия, retention | Статистическая значимость |
| **Сложность** | Низкая | Средняя | Высокая |

### Best Practices

1. **Automated Rollback:** Настройте автоматический откат при crash rate > 1%.
2. **Monitoring Dashboard:** Создайте дашборд с ключевыми метриками во время rollout.
3. **Communication:** Уведомляйте команду о каждом этапе rollout через Slack.
4. **Documentation:** Документируйте каждый rollout с указанием метрик и решений.
5. **Testing:** Всегда тестируйте rollback процедуру перед реальным инцидентом.

### См. также:
*   **[Mobile CI/CD Overview](./index.md)**
*   **[Feature Flags](./feature-flags-mobile.md)**
*   **[Incident Response](./incident-response-mobile.md)**
*   **[iOS CI/CD](./ios-ci-cd.md)**
*   **[Android CI/CD](./android-ci-cd.md)**
