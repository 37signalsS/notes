# Incident Response для мобильных приложений

## Определения

**Incident** — неплановое событие, при котором ключевая функциональность мобильного приложения нарушена, критический баг попал в production, или произошло падение сервиса, влияющее на пользователей.

**Hotfix** — экстренное исправление, выпускаемое в production в кратчайшие сроки (часы, а не дни). В мобильном контексте hotfix требует прохождения той же подписи и ревью, что и обычный релиз, что делает MTTR мобильных инцидентов выше, чем у backend.

**MTTR (Mean Time To Repair)** — среднее время восстановления сервиса после начала инцидента. Для mobile инцидентов целевое значение: < 4 часа.

**MTTA (Mean Time To Acknowledge)** — среднее время между срабатыванием алерта и принятием инцидента дежурным. Целевое значение: < 15 минут для P0.

**SEV (Severity)** — уровень тяжести инцидента: SEV1 (критично, простой продукта), SEV2 (частичная деградация), SEV3 (локальная проблема).

**On-call** — дежурный инженер, готовый отреагировать на алерт в нерабочее время.

**War Room** — координационный канал/созвон во время активного инцидента.

**Blameless Postmortem** — анализ инцидента без персональной ответственности, фокусирующийся на системных причинах и action items.

**Kill Switch** — feature flag, позволяющий мгновенно отключить проблемную функциональность без публикации новой версии.

**Degraded Mode** — безопасный режим приложения с ограниченной функциональностью, активируемый при проблемах с backend или внешними сервисами.

---

## Базовые концепции

### Особенности Mobile Incident Response

Мобильные инциденты имеют специфические ограничения, отличающие их от backend/web:

1. **Невозможность мгновенного развертывания:** После обнаружения проблемы нельзя применить исправление за секунды. Требуется сборка, подпись, ревью и публикация в магазин. Минимальное время hotfix — от 30 минут (TestFlight/Internal Track) до нескольких часов (App Store Review).
2. **Асинхронное обновление пользователей:** Даже после публикации исправления пользователи обновляются постепенно. Некоторое время приложение будет работать в деградированном состоянии.
3. **Ограниченная наблюдаемость:** Мобильное приложение работает на устройствах пользователей. Нет прямого доступа к логам, сети или состоянию системы. Диагностика строится на crash reports, метриках производительности и обратной связи пользователей.
4. **Зависимость от магазинов:** App Store Connect и Google Play Console — внешние системы с собственными SLA и процессами. Их недоступность блокирует публикацию исправлений.
5. **Каскадные эффекты:** Ошибка в новой версии может одновременно повлиять на миллионы пользователей при phased release или через automatic update.

### Типы Mobile Incident'ов

| Тип | Пример | Критичность |
|:---|:---|:---|
| **Crash** | Приложение падает на определенных устройствах/ОС | SEV1 |
| **Data Loss** | Пользователи теряют данные при синхронизации | SEV1 |
| **Security Breach** | Утечка пользовательских данных, компрометация ключей | SEV1 |
| **Performance** | Запуск > 5 секунд, ANR > 1% | SEV2 |
| **Feature Regression** | Функция перестала работать после обновления | SEV2 |
| **UI Bug** | Некорректное отображение, поломка layout | SEV3 |

### Жизненный цикл Mobile Incident'а

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Detection   │───►│  Triage      │───►│  Mitigation  │
│  (Alert)     │    │  (SEV/IC)    │    │  (Kill Flag) │
│  Crashlytics │    │  On-call     │    │  Degraded    │
│  Prometheus  │    │  War Room    │    │  Hotfix      │
└──────────────┘    └──────────────┘    └──────────┬───┘
                                                  │
┌──────────────┐    ┌──────────────┐    ┌─────────▼────┐
│  Postmortem  │◄───│  Resolution  │◄───│  Resolution  │
│  (Learning)  │    │  (Permanent) │    │  (Hotfix)    │
│  RCA         │    │  Patch       │    │  Rollout     │
└──────────────┘    └──────────────┘    └──────────────┘
```

### Severity Levels и SLI

| SEV | Описание | Время реакции | Время решения | Пример |
|:---|:---|:---|:---|:---|
| **SEV1** | Критический: crash/data loss/security | 15 минут | 4 часа | Crash rate > 5% на iOS 17 |
| **SEV2** | Высокий: major feature broken | 1 час | 24 часа | ANR > 1% при открытии чекаута |
| **SEV3** | Средний: minor feature broken | 4 часа | 3 дня | UI баг на определенном экране |

### SRE-подход к Mobile Incident Response

**Принципы:**

- **Error Budget для стабильности:** Договоритесь о допустимом crash rate и downtime. При исчерпании бюджета фокус смещается на стабилизацию, а не на новые фичи.
- **MTTR как KPI:** Измеряйте и улучшайте среднее время восстановления. Для mobile это включает время сборки, подписи и публикации.
- **Toil Reduction:** Автоматизируйте типовые действия: извлечение crash reports, проверку метрик, уведомление команд, создание инцидента в трекере.
- **Observability:** Каждый SEV1/SEV2 инцидент должен иметь полный trace: алерт → принятие → mitigation → resolution → postmortem.

---

## Практические сценарии

### 1. Hotfix Workflow для iOS

**Git Flow Hotfix:**
```bash
# 1. Создание hotfix ветки от main
git checkout -b hotfix/critical-crash-ios main

# 2. Исправление бага с минимальными изменениями
# ... исправления ...

# 3. Коммит с префиксом HOTFIX
git add .
git commit -m "hotfix: fix critical crash on iOS 17.4 launch"

# 4. Push и создание Merge Request
git push origin hotfix/critical-crash-ios
# Создайте Merge Request через GitLab UI или API

# 5. Мерж через GitLab UI и удаление ветки
```

**Fastlane Hotfix Lane:**
```ruby
platform :ios do
  desc "Hotfix: быстрая сборка и публикация"
  lane :hotfix do |options|
    # Установка версии (build number)
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
      message: "HOTFIX deployed to TestFlight: #{options[:description]}",
      channel: "#incidents",
      success: true
    )
  end
end
```

### 2. GitLab CI: Hotfix Pipeline

```yaml
stages:
  - build
  - deploy
  - notify

variables:
  FASTLANE_USER: $FASTLANE_USER
  FASTLANE_APPLE_APPLICATION_SPECIFIC_PASSWORD: $FASTLANE_APPLE_APPLICATION_SPECIFIC_PASSWORD

fast_build:
  stage: build
  tags:
    - macos
  script:
    - xcodebuild build \
        -project MyApp.xcodeproj \
        -scheme MyApp \
        -destination 'generic/platform=iOS' \
        -parallelizeTargets \
        CODE_SIGN_IDENTITY="$CODE_SIGN_IDENTITY"
  artifacts:
    paths:
      - build/*.ipa
    expire_in: 1 week

upload_testflight:
  stage: deploy
  tags:
    - macos
  script:
    - bundle exec fastlane upload_hotfix
  dependencies:
    - fast_build

notify_team:
  stage: notify
  script:
    - |
      curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"HOTFIX deployed: $CI_COMMIT_MESSAGE\"}" \
        $SLACK_WEBHOOK_URL
```

### 3. Mitigation через Feature Flags (Kill Switch)

Вместо немедленного hotfix, для быстрого отключения проблемной функциональности используйте feature flag:

```swift
// Проверка флага перед использованием опасной функции
func loadNewCheckout() {
    guard FeatureFlags.shared.isEnabled("new_checkout_flow") else {
        return loadLegacyCheckout()
    }
    // ... новая логика ...
}
```

**Процедура включения Kill Switch:**
1. Оценка impact: какой процент пользователей затронут?
2. Активация флага через Admin Dashboard или CI-пайплайн.
3. Мониторинг: crash rate, ANR, API latency в течение 15 минут.
4. Если проблема устранена — постепенное включение флага обратно.

### 4. Incident Communication Template

```markdown
# Incident Report: [Title]

**Date:** YYYY-MM-DD
**SEV:** SEV1/SEV2/SEV3
**Status:** Investigating / Identified / Monitoring / Resolved
**Incident Commander:** @name

## Impact
- [ ] Crash rate: X% (базовое: Y%)
- [ ] Затронуто Z% пользователей
- [ ] Feature N unavailable

## Timeline
- HH:MM — Issue detected via [alert/monitoring/user report]
- HH:MM — Triage: SEV assigned, IC declared
- HH:MM — War Room opened
- HH:MM — Root cause identified
- HH:MM — Mitigation deployed (hotfix/kill switch/rollback)
- HH:MM — Monitoring confirmed recovery
- HH:MM — Issue resolved

## Root Cause
[Description of the root cause]

## Resolution
[What was done to fix the issue]

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
**SEV:** SEV1/SEV2/SEV3

## Summary
[1-2 sentences about what happened]

## Impact
- Crash rate: X% → Y%
- Users affected: Z
- Duration: T hours

## Timeline
- HH:MM — deployment started
- HH:MM — alert fired
- ...

## Root Cause (5 Why)
1. Почему произошло? → ...
2. Почему система это позволила? → ...
3. ...

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

## Операции и команды

### Диагностика crash reports

```bash
# Извлечение crash reports из симулятора iOS
xcrun simctl spawn booted log show --predicate 'subsystem == "com.apple.runningboard"' --last 1h

# Просмотр Device logs iOS
xcrun simctl spawn booted log stream --predicate 'process == "MyApp"' --level debug

# Android: извлечение crash reports через adb
adb shell "am crash com.company.app"
adb logcat -d | grep -i "fatal\|exception\|androidruntime"

# Просмотр SharedPreferences для отладки флагов
adb shell "run-as com.company.app cat shared_prefs/feature_flags.xml"
```

### Быстрая проверка метрик

```bash
# Проверка crash rate через API (пример)
curl -s "https://monitoring.internal/api/v1/query?query=rate(mobile_crash_rate[5m])"

# Проверка ANR rate
curl -s "https://monitoring.internal/api/v1/query?query=rate(mobile_anr_rate[10m])"

# Проверка версии приложения на устройстве
adb shell dumpsys package com.company.app | grep versionName
xcrun simctl spawn booted defaults read com.company.app CFBundleShortVersionString
```

### Управление hotfix веткой

```bash
# Создание hotfix ветки
git checkout -b hotfix/SEV1-critical-crash main

# Быстрый коммит и push
git commit -am "hotfix: SEV1 critical crash fix"
git push origin hotfix/SEV1-critical-crash

# Создание Merge Request через GitLab UI или API

# После мержа - удаление ветки
git branch -d hotfix/SEV1-critical-crash
git push origin --delete hotfix/SEV1-critical-crash
```

### Проверка состояния App Store / Google Play

```bash
# Проверка статуса TestFlight билда (через App Store Connect API)
curl -s "https://api.appstoreconnect.apple.com/v1/builds?filter[app]=com.company.app" \
  -H "Authorization: Bearer ${ASC_KEY}"

# Проверка статуса релиза в Google Play
# (через Google Play Developer API)
curl -s "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/com.company.app/edits" \
  -H "Authorization: Bearer ${GOOGLE_PLAY_TOKEN}"
```

---

## Устранение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Crash при старте** | Некорректная миграция данных, обновление БД | Откатите миграцию через version code, включите legacy mode через флаг |
| **ANR на главном экране** | Блокирующий вызов на UI потоке | Выпустите hotfix с переносом логики в background queue |
| **Потеря данных** | Ошибка синхронизации, конфликт версий | Включите read-only mode через флаг, восстановите данные из бэкапа |
| **Высокий crash rate после релиза** | Регрессия в новой версии | Остановите phased release, подготовьте hotfix или откатите версию |
| **Feature перестал работать** | Сломанная интеграция с backend | Включите degraded mode через feature flag, сообщите backend команде |
| **Пользователи не обновляются** | Проблемы с магазином, кэширование CDN | Проверьте статус App Store/Google Play, публикуйте в alternate track |
| **Hotfix не проходит ревью** | Нехватка ресурсов, праздники, out-of-hours | Соберите War Room, назначьте alternate reviewer, используйте emergency review |
| **Ключи подписи скомпрометированы** | Утечка сертификатов | Отзовите ключ, сгенерируйте новый, выпустите экстренное обновление |

---

## Рекомендации

### Best Practices

- **Runbook для типовых инцидентов:** Документируйте шаги для crash on launch, API endpoint down, authentication failure, data sync issues. Runbook должен быть доступен оффлайн.
- **Автоматизация детекции:** Настройте алерты на crash rate, ANR, API latency, user-reported crashes. Алерты должны быть actionnable и привязаны к SLO.
- **War Room процедура:** Заранее определите канал коммуникации (Slack/Teams), назначьте Incident Commander, подготовьте шаблоны сообщений.
- **Feature Flags для mitigation:** Используйте kill switch и degraded mode как первую линию защиты. Это быстрее, чем hotfix.
- **Phased Release:** Всегда используйте поэтапный rollout для новых версий. Это ограничивает blast radius инцидента.
- **Drills:** Проводите регулярные учения по incident response. Симулируйте SEV1 сценарий, измеряйте MTTR.
- **Error Budget:** Свяжите стабильность приложения с возможностью выпуска. При исчерпании бюджета — freeze на новые фичи.

### Edge Cases и ограничения

1. **Out-of-hours incidents:** Обеспечьте on-call ротацию с escalation policy. Автоматические алерты должны приходить дежурному, а не в общий канал.
2. **App Store Review Delay:** Для критических исправлений используйте expedited review запрос. Имейте backup план на случай отказа.
3. **Пользователи на старых версиях:** Не все пользователи обновляются сразу. Hotfix должен быть обратно совместим с данными старой версии.
4. **Каскадные инциденты:** Проблема в одной функции может повлиять на другие. Изоляция через feature flags и degraded mode критически важна.
5. **Third-party SDK failures:** Зависимость от внешних SDK (аналитика, реклама, платежи) создает риски. Мониторьте их доступность и иметь fallback.

### Мониторинг и Observability

**Ключевые метрики для алертов:**
- **Crash Rate:** > 1% = SEV1, > 0.5% = SEV2
- **ANR Rate (Android):** > 0.5% = SEV1, > 0.3% = SEV2
- **App Launch Time:** > 3 секунды = SEV2
- **Network Errors:** > 5% = SEV2
- **API Response Time:** > 2 секунды = SEV2

**Prometheus Alert Rules:**
```yaml
groups:
  - name: mobile_alerts
    rules:
      - alert: HighCrashRate
        expr: rate(mobile_crash_rate[5m]) > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High crash rate detected"
      
      - alert: HighANRRate
        expr: rate(mobile_anr_rate[10m]) > 0.005
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High ANR rate detected"
```

**Runbook'и для частых инцидентов:**

**Runbook: Crash on App Launch**
1. Проверьте crash reports в системе мониторинга
2. Определите affected devices/OS versions
3. Если device-specific: создайте hotfix с проверкой
4. Если universal: rollback через TestFlight/Google Play или откатите phased release
5. Уведомите команду в War Room

**Runbook: API Endpoint Down**
1. Проверьте статус API через health check endpoint
2. Включите degraded mode через feature flag
3. Уведомите backend команду
4. Мониторинг impact на пользователей

**Runbook: Phased Release Incident**
1. Остановите rollout (pause phased release)
2. Соберите метрики: crash rate, ANR, user reports
3. Определите: проблема в новой версии или совпадение
4. Если версия виновна — подготовьте hotfix или откатите rollout
5. Документируйте в incident report

### Безопасность

- **Аутентификация в трекере инцидентов:** Доступ к War Room и incident management только у authorized personnel.
- **Аудит изменений:** Все hotfix коммиты должны содержать ссылку на incident ticket.
- **Секреты:** Ключи подписи и API токены не должны попадать в логи или crash reports.
- **Communication security:** Используйте encrypted каналы для обсуждения инцидентов, особенно если затрагиваются security breaches.

---

## Дополнительная информация

- **[Обзор Mobile CI/CD и инфраструктуры](./index.md)** — архитектура macOS-раннеров, Golden Image, SRE-подход к пайплайнам.
- **[Feature Flags в мобильных приложениях](./feature-flags-mobile.md)** — Kill Switch как средство mitigation, degraded mode.
- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout, процедуры отката через магазины.
