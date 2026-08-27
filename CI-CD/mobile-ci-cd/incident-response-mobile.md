# Incident Response для мобильных приложений

## Определения

**Incident** — инцидент, при котором ключевая функциональность мобильного приложения нарушена, или критический баг попал в production, влияющий на пользователей.

**Hotfix** — экстренное исправление, которое должно быть выпущено в production в кратчайшие сроки (обычно в течение часов, а не дней).

**Blameless Postmortem** — процесс анализа инцидента без персональной ответственности, фокусирующийся на системных улучшениях.

**MTTR (Mean Time To Repair)** — среднее время восстановления после инцидента. Для mobile инцидентов целевое значение: < 4 часа.

---

## Базовые концепции

### Типы Mobile Incident'ов

| Тип | Пример | Критичность |
|:---|:---|:---|
| **Crash** | Приложение падает на определенных устройствах | P0 |
| **Data Loss** | Пользователи теряют данные | P0 |
| **Security Breach** | Утечка пользовательских данных | P0 |
| **Performance** | Приложение работает очень медленно | P1 |
| **UI Bug** | Некорректное отображение элементов | P2 |
| **Feature Regression** | Функция перестала работать | P1 |

### Workflow Incident Response

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Detection   │───►│  Triage      │───►│  Mitigation  │
│  (Alert)     │    │  (Severity)  │    │  (Quick Fix) │
└──────────────┘    └──────────────┘    └──────────────┘
                                                 │
┌──────────────┐    ┌──────────────┐    ┌─────────▼────┐
│  Postmortem  │◄───│  Resolution  │◄───│  Resolution  │
│  (Learning)  │    │  (Permanent) │    │  (Hotfix)    │
└──────────────┘    └──────────────┘    └──────────────┘
```

### Severity Levels

| Severity | Описание | Время реагирования | Время решения |
|:---|:---|:---|:---|
| **P0** | Критический: crash/data loss/security | 15 минут | 4 часа |
| **P1** | Высокий: major feature broken | 1 час | 24 часа |
| **P2** | Средний: minor feature broken | 4 часа | 3 дня |
| **P3** | Низкий: cosmetic issues | 1 день | 1 спринт |

---

## Практическая реализация

### 1. Hotfix Workflow для iOS

**Git Flow Hotfix:**
```bash
# 1. Создание hotfix ветки
git checkout -b hotfix/critical-crash main

# 2. Исправление бага
# ... исправления ...

# 3. Коммит и push
git add .
git commit -m "fix: critical crash on iOS 17.4"
git push origin hotfix/critical-crash

# 4. Создание PR в main
gh pr create --base main --title "HOTFIX: Critical crash" --body "Fixes #123"

# 5. После мержа - автоматическая сборка и публикация
```

**Fastlane Hotfix Lane:**
```ruby
platform :ios do
  desc "Hotfix: быстрая сборка и публикация"
  lane :hotfix do |options|
    # Установка версии
    increment_build_number(
      xcodeproj: "MyApp.xcodeproj",
      build_number: options[:build_number] || Time.now.strftime("%Y%m%d%H%M")
    )
    
    # Сборка без тестов (для скорости)
    build_app(
      scheme: "MyApp",
      output_directory: "./build",
      clean: true
    )
    
    # Быстрая загрузка в TestFlight
    upload_to_testflight(
      skip_waiting_for_build_processing: true,
      notify_external_testers: false
    )
    
    # Уведомление команды
    slack(
      message: "🚨 HOTFIX deployed to TestFlight: #{options[:description]}",
      channel: "#incidents"
    )
  end
end
```

### 2. GitHub Actions: Hotfix Pipeline

```yaml
name: Hotfix Pipeline

on:
  push:
    branches:
      - hotfix/*

jobs:
  fast_build:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      
      - name: Fast Build (no tests)
        run: |
          xcodebuild build \
            -project MyApp.xcodeproj \
            -scheme MyApp \
            -destination 'generic/platform=iOS' \
            -parallelizeTargets \
            CODE_SIGN_IDENTITY="${{ secrets.CODE_SIGN_IDENTITY }}"
      
      - name: Upload to TestFlight
        env:
          ASC_KEY_ID: ${{ secrets.ASC_KEY_ID }}
          ASC_ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
          ASC_KEY_CONTENT: ${{ secrets.ASC_KEY_CONTENT }}
        run: |
          bundle exec fastlane upload_hotfix
      
      - name: Notify Team
        uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {
              "text": "🚨 HOTFIX deployed: ${{ github.event.head_commit.message }}"
            }
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK }}
```

### 3. Rollback Procedures

**iOS Rollback:**
```ruby
# Если критический баг обнаружен в TestFlight
lane :rollback_testflight do
  app_store_connect_api_key(...)
  
  # Получение предыдущего стабильного билда
  previous_build = get_previous_stable_build
  
  # Сборка предыдущей версии
  checkout_previous_version(version: previous_build)
  build_app(scheme: "MyApp")
  
  # Загрузка как новый билд
  upload_to_testflight(
    skip_waiting_for_build_processing: true
  )
  
  slack(message: "🔄 ROLLBACK deployed to TestFlight: #{previous_build}")
end
```

**Android Rollback:**
```ruby
# Быстрый откат через Google Play
lane :rollback_android do
  supply(
    track: "production",
    version_code: get_previous_version_code,
    json_key_data: ENV["GCP_SERVICE_ACCOUNT_JSON"],
    skip_upload_metadata: true,
    skip_upload_screenshots: true,
    skip_upload_apk: true
  )
end
```

### 4. Incident Communication Template

```markdown
# Incident Report: [Title]

**Date:** YYYY-MM-DD
**Severity:** P0/P1/P2/P3
**Status:** Investigating / Identified / Monitoring / Resolved

## Impact
- [ ] Crash rate > X%
- [ ] Y users affected
- [ ] Feature Z unavailable

## Timeline
- HH:MM - Issue detected via [monitoring/alert]
- HH:MM - Investigation started
- HH:MM - Root cause identified
- HH:MM - Hotfix deployed
- HH:MM - Issue resolved

## Root Cause
[Description of the root cause]

## Resolution
[What was done to fix the issue]

## Prevention
- [ ] Add monitoring for [X]
- [ ] Improve test coverage for [Y]
- [ ] Update runbook for [Z]

## Action Items
| Item | Owner | Due Date |
|:---|:---|:---|
| [Action] | [Name] | [Date] |
```

### 5. Blameless Postmortem Template

```markdown
# Postmortem: [Incident Title]

**Date:** YYYY-MM-DD
**Participants:** [Names]
**Duration:** [X hours]

## Summary
[1-2 sentences about what happened]

## What went well
- [Positive point 1]
- [Positive point 2]

## What went wrong
- [Issue 1]
- [Issue 2]

## Where we got lucky
- [Factor 1]

## Action Items
| Priority | Item | Owner | Due Date |
|:---|:---|:---|:---|
| High | [Action] | [Name] | [Date] |
| Medium | [Action] | [Name] | [Date] |

## Lessons Learned
- [Lesson 1]
- [Lesson 2]
```

---

## Дополнительная информация

### Monitoring для Incident Detection

**Ключевые метрики для алертов:**
- **Crash Rate:** > 1% = P0, > 0.5% = P1
- **ANR Rate (Android):** > 0.5% = P1
- **App Launch Time:** > 3 секунды = P2
- **Network Errors:** > 5% = P1
- **API Response Time:** > 2 секунды = P2

**Prometheus Alert Rules:**
```yaml
groups:
  - name: mobile_alerts
    rules:
      - alert: HighCrashRate
        expr: mobile_crash_rate > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High crash rate detected"
          
      - alert: HighANRRate
        expr: mobile_anr_rate > 0.005
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High ANR rate detected"
```

### Runbook для частых инцидентов

**Runbook: Crash on App Launch**
1. Проверьте crash reports в Firebase Crashlytics
2. ОпределитеAffected devices/OS versions
3. Если device-specific: создайте hotfix с проверкой
4. Если universal: rollback через TestFlight/Google Play
5. Уведомите команду в #incidents

**Runbook: API Endpoint Down**
1. Проверьте статус API через health check endpoint
2. Включите degraded mode через feature flag
3. Уведомите backend команду
4. Мониторинг impact на пользователей

### Best Practices

1. **Automated Detection:** Настройте автоматические алерты для ключевых метрик.
2. **Runbook Automation:** Используйте скрипты для типовых действий.
3. **Communication Plan:** Заранее определите каналы коммуникации.
4. **War Room:** Создайте временный канал для координации.
5. **Regular Drills:** Проводите регулярные учения по incident response.

### См. также:
*   **[Mobile CI/CD Overview](./index.md)**
*   **[Feature Flags](./feature-flags-mobile.md)**
*   **[Deployment Strategies](./deployment-strategies-mobile.md)**
*   **[Disaster Recovery](./disaster-recovery-mobile-ci.md)**
