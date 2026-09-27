# Beta Testing и Distribution Automation

## Определения

**TestFlight** — система beta-тестирования iOS от Apple. Включает Internal Testing (до 100 пользователей) и External Testing (до 10 000 пользователей с beta review).

**Google Play Testing Tracks** — система staged distribution Android: Internal → Closed → Open → Production. Каждый track имеет свои лимиты и скорость rollout.

**Custom Distribution** — self-hosted решение для дистрибуции бинарников тестерам через внутренний сервер или CDN.

**Beta Tester** — пользователь, тестирующий pre-release версию приложения перед production релизом.

**Beta Review** — процесс модерации beta-версии Apple для External Testing. Требует compliance с guidelines.

**Internal Testing** — тестирование внутри компании/команды. Быстрый доступ, без beta review (iOS), без review (Android Internal).

**External Testing** — тестирование внешними пользователями. Требует beta review (iOS), соответствует track policy (Android).

**Closed Testing** — тестирование по приглашениям (Google Play). Доступ по ссылке или email.

**Open Testing** — публичное тестирование (Google Play). Доступно для всех пользователей по ссылке.

**Beta Feedback** — обратная связь от тестеров: crash reports, suggestions, usability issues.

**Build Processing** — время обработки бинарника магазином перед появлением у тестеров.

**Beta Cohort** — сегмент тестеров, объединенных по признаку (внутренняя команда, внешние пользователи, конкретная география). Используется для изолированного rollout и оценки метрик по сегментам.

**Canary Cohort** — малая группа тестеров (обычно < 5% от общего пула), получающая билд первой. Предназначена для раннего обнаружения критических регрессий перед массовым распространением.

**Retention Policy** — политика хранения beta-артефактов и данных обратной связи. Определяет сроки хранения IPA/AAB, dSYM/ProGuard mapping, crash reports и feedback.

**Build Expiration** — автоматическое удаление бинарника из магазина после истечения срока. TestFlight builds expire через 90 дней, Google Play builds не имеют автоматического expiration, но policy требует регулярного обновления.

**OTA Manifest (Over-The-Air)** — XML/Plist файл, описывающий iOS-бинарник для установки без участия App Store. Содержит URL, bundle identifier, version, и информацию о подписи.

**TestFlight Beta Review** — модерация Apple для External Testing. Проверяет compliance с guidelines, наличие Test Information, export compliance declaration. Среднее время: 24–48 часов.

**Track Promotion** — процесс продвижения бинарника между Google Play Testing Tracks (Internal → Closed → Open → Production) или между Internal и External в TestFlight.

**Phased Rollout Gate** — автоматический или ручной контроль, пропускающий билд на следующий этап rollout только при выполнении критериев (crash-free rate > 99%, no critical bugs, positive feedback).

**Crash-free Rate** — процент сессий без crash. Ключевая метрика для принятия решения о продвижении beta-билда в production. Целевое значение: > 99% на каждом track.

**Feedback Triage** — процесс сортировки обратной связи по severity и приоритету: SEV1 (критический crash), SEV2 (major regression), SEV3 (minor issue), SEV4 (enhancement).

**Keystone (Beta Distribution)** — критичные инфраструктурные компоненты, без которых beta-дистрибуция не работает: Pact Broker для API contract testing, artifact storage для pacts и binaries, notification service для уведомления тестеров.

**Golden Build** — эталонный бинарник, прошедший все quality gates и используемый для сравнения размера, производительности и стабильности с последующими релизами.

**Build Artifact** — итоговый бинарный файл приложения (IPA, AAB, APK) и сопутствующие артефакты (dSYM, ProGuard mapping, manifest).

**Beta Lifecycle** — полный цикл жизни beta-версии: Build → Upload → Processing → Internal Testing → External Testing → Promotion Gate → Production Release.

**Distribution Automation** — автоматизация загрузки бинарников в магазины или внутренние серверы, уведомления тестеров, управления tracks и сбора метрик без ручного вмешательства.

**Self-hosted Distribution Infrastructure** — совокупность серверов, хранилищ и сервисов для самостоятельной дистрибуции мобильных бинарников: веб-сервер (Nginx/Apache), SSL-сертификаты, artifact storage, notification service, feedback API.

**Artifact Retention (Beta)** — политика хранения beta-артефактов. Рекомендуется хранить IPA/AAB и mapping минимум 90 дней для возможности отладки production-инцидентов и compliance.

**Build Cache (Beta)** — кэширование артефактов между beta-запусками для ускорения загрузки и повторного использования неизмененных зависимостей.

**Toil (Beta Distribution)** — ручная работа при дистрибуции: повторная загрузка бинарника после rejection, ручное управление tester lists, ручной запуск promotion. Цель: снизить долю toil до < 10% от времени релизного цикла.

**Error Budget (Beta)** — допустимый процент критических багов или breaking changes в beta. При исчерпании бюджета release halt и фокус на стабилизацию.

**MTTR (Beta)** — среднее время от обнаружения критического бага в beta до фикса и повторной загрузки. Целевое значение: < 24 часа.

---

## Базовые концепции

### Архитектура пайплайна: Beta Distribution Lifecycle

Типовой пайплайн beta testing и distribution в Mobile CI/CD:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Build &     │───►│   Upload to  │───►│   Beta       │───►│   Quality    │───►│   Promotion  │
│  Sign        │    │   Store      │    │   Testing    │    │   Gate       │    │   Gate       │
│              │    │              │    │              │    │              │    │              │
│  xcodebuild  │    │ TestFlight   │    │ Internal     │    │ Crash-free   │    │ Auto /       │
│  gradle      │    │ Fastlane     │    │ External     │    │ rate > 99%   │    │ Manual       │
│  match       │    │ supply       │    │ Google Play  │    │ No critical  │    │ approval     │
│              │    │ scp/curl     │    │ tracks       │    │ bugs         │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
         │                   │                   │                   │                   │
         ▼                   ▼                   ▼                   ▼                   ▼
    Code signing        Upload IPA/AAB       Tester feedback     Metrics review       Production
    Build artifact      Beta Review          Crash reports        Approval             Release
```

**Этапы lifecycle:**

1. **Build & Sign:** Сборка приложения, подпись сертификатами, создание IPA/AAB.
2. **Upload to Store:** Загрузка бинарника в TestFlight, Google Play Console или внутренний сервер.
3. **Beta Testing:** Распространение среди Internal/External тестеров или по Google Play tracks.
4. **Quality Gate:** Автоматическая проверка crash-free rate, absence of critical bugs, feedback sentiment.
5. **Promotion Gate:** Продвижение в production после прохождения quality gates и approval.

### iOS: TestFlight

**Треки тестирования:**

| Track | Лимит | Review | Скорость |
|:---|:---|:---|:---|
| **Internal** | 100 пользователей | Нет | Мгновенно (после processing) |
| **External** | 10 000 пользователей | Beta Review (24–48ч) | После approval |

**TestFlight Workflow:**
```
Build → Upload → Processing (10–30 мин) → Internal Testing
                                               ↓
                                         Beta Review (24–48ч)
                                               ↓
                                         External Testing
                                               ↓
                                         Production Release
```

**Beta Review Requirements:**
- Test Information: описание, what's new, contact info
- Export Compliance: encryption declaration
- Content Rights: подтверждение прав на контент
- App Review Guidelines: соответствие guidelines

### Android: Google Play Tracks

**Треки тестирования:**

| Track | Лимит | Review | Скорость |
|:---|:---|:---|:---|
| **Internal** | 100 тестеров | Нет | Мгновенно |
| **Closed** | До 2 000 тестеров | Нет | Несколько часов |
| **Open** | Неограниченно | Нет | Несколько часов |
| **Production** | Все пользователи | Review | 24–48ч |

**Staged Rollout через Tracks:**
```
Internal (100%) → Closed (25%) → Open (50%) → Production (1% → 100%)
```

### Self-hosted Distribution

**Возможности:**
- Дистрибуция iOS/Android бинарников через внутренний сервер
- Tester management (email, groups)
- Встроенная обратная связь через custom API
- CI/CD интеграция (Fastlane, GitLab CI)

### Sysadmin: инфраструктура self-hosted distribution

Для организации собственной инфраструктуры beta-дистрибуции требуются следующие компоненты:

**Веб-сервер и SSL:**
- **Nginx/Apache:** Размещение IPA/AAB/APK и OTA manifest.
- **SSL-сертификат:** Для HTTPS доступа к бинарникам и feedback API. Используйте Let's Encrypt или внутренний CA.
- **Content-Type:** Корректные MIME-типы (`application/octet-stream` для IPA/AAB, `application/xml` для manifest).

**Artifact Storage:**
- **Локальное хранилище:** `/var/www/beta/` или выделенный раздел диска.
- **Резервное копирование:** Ежедневный backup критичных бинарников и dSYM/mapping.
- **Очистка:** Retention policy: хранить бинарники 90 дней, затем удалять.

**Notification Service:**
- **Slack/Telegram webhook:** Уведомление тестеров о новом билде.
- **Email:** Для внешних тестеров, не использующих Slack.
- **API endpoint:** `/api/beta/notify` для программных уведомлений из CI.

**Feedback API:**
- **REST endpoint:** `POST /api/beta` для сбора обратной связи.
- **Storage:** PostgreSQL или SQLite для хранения feedback.
- **Triage interface:** Веб-интерфейс или CLI для классификации feedback.

**Сетевая инфраструктура:**
- **Firewall:** Ограничьте доступ к beta-серверу только из корпоративной сети или VPN.
- **DNS:** Внутренний DNS-record (`dist.internal`) для доступа тестеров.
- **Load Balancer:** Если используется несколько серверов, настройте round-robin.

### Beta Testing Strategy

**Фазы beta-тестирования:**

```
Phase 1: Internal Testing (1–2 дня)
  ↓ Команда, QA
  ↓ Быстрый feedback
  
Phase 2: Closed Testing (3–7 дней)
  ↓ Приглашенные тестеры, stakeholders
  ↓ Функциональное тестирование
  
Phase 3: Open Testing (1–2 недели)
  ↑ Широкая аудитория
  ↑ Performance, stability, UX
  
Phase 4: Production Release
  ↑ Phased rollout 1% → 25% → 100%
  ↑ Monitoring crash-free rate
```

### Tester Management

**iOS Testers:**
- Internal: члены команды в App Store Connect
- External: email invites, public link, TestFlight app

**Android Testers:**
- Internal/Closed: email lists, Google Groups
- Open: public link
- Opt-in URL для быстрого доступа

### Feedback Collection

**Автоматический сбор:**
- **Crash reports:** Sentry, custom crash reporters
- **Feedback form:** встроенный в приложение
- **App Store reviews:** мониторинг отзывов
- **Analytics:** behavioral data, session recordings

### SRE-подход к Beta Testing

- **Error Budget для beta:** Договоритесь о допустимом проценте критических багов в beta (например, 0). При обнаружении — halt release.
- **MTTR (Beta):** Среднее время от обнаружения критического бага до фикса. Цель: < 24 часа для beta.
- **Toil Reduction:** Автоматизируйте дистрибуцию, уведомления тестеров, сбор feedback. Измеряйте долю ручной работы.
- **Observability:** Каждый beta-билд должен иметь метрики: crash rate, ANR, user feedback sentiment.

---

## Практические сценарии

### 1. TestFlight: Internal Testing

**Fastlane: Upload to TestFlight:**
```ruby
platform :ios do
  desc "Upload to TestFlight Internal"
  lane :beta_internal do
    setup_ci
    
    match(type: "appstore", readonly: true)
    build_app(
      scheme: "MyApp",
      export_method: "app-store",
      output_directory: "./build"
    )
    
    upload_to_testflight(
      skip_waiting_for_build_processing: true,
      distribute_external: false,
      notify_external_testers: false
    )
    
    UI.success("Build uploaded to TestFlight Internal")
  end
end
```

**GitLab CI:**
```yaml
upload_testflight:
  stage: deploy_staging
  script:
    - bundle exec fastlane beta_internal
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### 2. TestFlight: External Testing

**Fastlane: External Testing с beta review:**
```ruby
platform :ios do
  desc "External Testing"
  lane :beta_external do
    build_app(
      scheme: "MyApp",
      export_method: "app-store"
    )
    
    upload_to_testflight(
      skip_waiting_for_build_processing: true,
      distribute_external: true,
      notify_external_testers: true,
      changelog: "New checkout flow, bug fixes",
      
      # Beta Review Information
      beta_app_description: "Test the new checkout flow",
      beta_app_feedback_email: "beta@company.com",
      
      # Compliance
      export_compliance: {
        encryption: false
      },
      
      # Test Groups
      groups: ["External Testers", "Beta Group"]
    )
  end
end
```

**Beta Review Information:**
```yaml
# В App Store Connect или через Fastlane:
beta_app_review:
  contact_email: beta@company.com
  contact_first_name: John
  contact_last_name: Doe
  contact_phone: +1-555-0123
  demo_account: demo@company.com
  demo_password: demo123
  notes: "Test the new checkout flow, focus on payment methods"
```

### 3. Google Play: Testing Tracks

**Fastlane: Internal Testing:**
```ruby
platform :android do
  desc "Deploy to Internal Testing"
  lane :beta_internal do
    gradle(task: "bundle", build_type: "Release")
    
    supply(
      track: "internal",
      aab: "app/build/outputs/bundle/release/app-release.aab",
      json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"],
      metadata_path: "./fastlane/metadata/android",
      changelog: "Internal testing build"
    )
  end
end
```

**Fastlane: Closed Testing:**
```ruby
platform :android do
  desc "Deploy to Closed Testing"
  lane :beta_closed do
    gradle(task: "bundle", build_type: "Release")
    
    supply(
      track: "beta",
      aab: "app/build/outputs/bundle/release/app-release.aab",
      json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"],
      metadata_path: "./fastlane/metadata/android",
      changelog: "Closed testing build",
      
      # Email list для testers
      email_list: "testers@company.com"
    )
  end
end
```

**Fastlane: Staged Rollout через Tracks:**
```ruby
platform :android do
  desc "Promote from Internal to Closed"
  lane :promote_to_closed do
    supply(
      track: "internal",
      track_promote_to: "beta",
      json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"]
    )
  end
  
  desc "Promote from Closed to Open"
  lane :promote_to_open do
    supply(
      track: "beta",
      track_promote_to: "alpha",
      json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"]
    )
  end
  
  desc "Promote to Production (Staged Rollout 1%)"
  lane :promote_to_production do
    supply(
      track: "internal",
      track_promote_to: "production",
      rollout: "0.01",
      json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"]
    )
  end
end
```

### 4. Self-hosted Distribution

**Generic distribution через HTTP server:**
```bash
# Загрузка бинарника на внутренний сервер
scp ./build/MyApp.ipa user@dist.internal:/var/www/beta/

# Генерация manifest для OTA установки (iOS)
cat > manifest.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
  <key>items</key>
  <array>
    <dict>
      <key>assets</key>
      <array>
        <dict>
          <key>kind</key>
          <string>software-package</string>
          <key>url</key>
          <string>https://dist.internal/beta/MyApp.ipa</string>
        </dict>
      </array>
      <key>metadata</key>
      <dict>
        <key>bundle-identifier</key>
        <string>com.company.app</string>
        <key>bundle-version</key>
        <string>2.5.0</string>
        <key>kind</key>
        <string>software</string>
        <key>title</key>
        <string>MyApp Beta</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
EOF

# Опубликование manifest
curl -X POST https://dist.internal/beta/manifest.plist \
  -H "Content-Type: application/xml" \
  --data-binary @manifest.plist
```

**Fastlane: Self-hosted distribution:**
```ruby
platform :ios do
  desc "Upload to internal distribution server"
  lane :beta_internal do
    build_app(
      scheme: "MyApp",
      export_method: "ad-hoc"
    )
    
    # Загрузка на внутренний сервер
    sh "scp ./build/MyApp.ipa user@dist.internal:/var/www/beta/"
    
    # Уведомление тестеров
    slack(
      message: "New beta build available: https://dist.internal/beta/MyApp.ipa",
      channel: "#beta-testers"
    )
  end
end
```

**GitLab CI:**
```yaml
upload_internal_distribution:
  stage: deploy_staging
  script:
    - scp ./build/MyApp.ipa user@dist.internal:/var/www/beta/
    - curl -X POST https://dist.internal/beta/notify \
        -H "Content-Type: application/json" \
        -d '{"version": "2.5.0", "url": "https://dist.internal/beta/MyApp.ipa"}'
```

### 5. Automated Beta Feedback Collection

**iOS: Custom Feedback Form:**
```swift
// Показ формы перед отправкой
func showFeedbackForm() {
    let alert = UIAlertController(
        title: "Beta Feedback",
        message: "Describe the issue:",
        preferredStyle: .alert
    )
    
    alert.addTextField { textField in
        textField.placeholder = "Enter your feedback"
    }
    
    alert.addAction(UIAlertAction(title: "Send", style: .default) { _ in
        guard let text = alert.textFields?.first?.text else { return }
        self.submitFeedback(text)
    })
    
    present(alert, animated: true)
}

// Отправка feedback на внутренний сервер
func submitFeedback(_ text: String) {
    guard let url = URL(string: "https://feedback.internal/api/beta") else { return }
    
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.httpBody = try? JSONSerialization.data(
        withJSONObject: ["feedback": text, "version": "2.5.0"],
        options: []
    )
    
    URLSession.shared.dataTask(with: request).resume()
}
```

**Android: Custom Feedback Form:**
```kotlin
// Показ формы перед отправкой
fun showFeedbackForm() {
    val builder = AlertDialog.Builder(this)
    builder.setTitle("Beta Feedback")
    builder.setMessage("Describe the issue:")
    
    val input = EditText(this)
    input.hint = "Enter your feedback"
    builder.setView(input)
    
    builder.setPositiveButton("Send") { dialog, _ ->
        val text = input.text.toString()
        submitFeedback(text)
    }
    
    builder.show()
}

// Отправка feedback на внутренний сервер
fun submitFeedback(text: String) {
    val request = Request.Builder()
        .url("https://feedback.internal/api/beta")
        .post(
            JSONObject()
                .put("feedback", text)
                .put("version", "2.5.0")
                .toString()
                .toRequestBody("application/json".toMediaType())
        )
        .build()
}
```

**Feedback API (self-hosted):**
```bash
# Простой API для сбора feedback
POST /api/beta
{
  "feedback": "App crashes on login",
  "version": "2.5.0",
  "platform": "ios",
  "device": "iPhone 15 Pro",
  "os_version": "17.0"
}

# Ответ
{
  "id": "feedback-123",
  "status": "received",
  "created_at": "2026-09-26T10:30:00Z"
}
```

### 6. Beta Testing Analytics

**Метрики для beta:**
- **Crash-free rate:** % сессий без crash (цель: > 99%)
- **Beta adoption:** % тестеров, установивших beta
- **Feedback volume:** количество feedback'ов
- **Critical bugs:** количество SEV1/SEV2 багов
- **Time to feedback:** среднее время от установки до первого feedback

**Prometheus метрики:**
```yaml
groups:
  - name: beta_testing_metrics
    rules:
      - alert: BetaCrashRateHigh
        expr: crash_free_rate{track="beta"} < 0.99
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Beta crash-free rate below 99%"
      
      - alert: BetaCriticalBug
        expr: beta_critical_bugs_total > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Critical bug in beta"
```

### 7. Beta → Production Promotion

**Promotion Workflow:**
```
Internal Testing (1–2 дня)
  ↓ Crash-free rate > 99%
  
Closed Testing (3–7 дней)
  ↓ No critical bugs
  ↓ Positive feedback
  
Open Testing (1–2 недели)
  ↓ Crash-free rate > 99%
  ↓ No critical bugs
  
Production Staged Rollout (1% → 25% → 100%)
  ↓ Monitoring crash-free rate
```

**Automated Promotion:**
```ruby
lane :promote_beta_to_production do
  # Проверка метрик beta
  crash_rate = get_crash_rate(track: "beta")
  
  if crash_rate > 0.01
    UI.error("Crash rate too high for promotion: #{crash_rate}")
    raise "Beta metrics not ready for production"
  end
  
  # Продвижение
  supply(
    track: "internal",
    track_promote_to: "production",
    rollout: "0.01",
    json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"]
  )
  
  UI.success("Promoted to production 1%")
end
```

---

## Операции и команды

### TestFlight Management

```bash
# Проверка сборок в TestFlight
fastlane pilot list
# → Build 42: MyApp 2.5.0 (42)

# Проверка статуса beta review
fastlane pilot beta_review_info
# → Beta Review: Approved

# Отправка beta review
fastlane pilot beta_review submit
# → Beta review submitted
```

### Google Play Tracks

```bash
# Проверка текущего track
fastlane supply track:internal --json_key ./service-account.json
# → Current track: internal

# Продвижение между tracks
fastlane supply track:internal track_promote_to:beta \
  --json_key ./service-account.json
# → Promoted to beta track

# Управление rollout
fastlane supply track:production rollout:0.01 \
  --json_key ./service-account.json
# → Rollout started: 1%
```

### Self-hosted Distribution CLI

```bash
# Загрузка бинарника на внутренний сервер
scp ./build/MyApp.ipa user@dist.internal:/var/www/beta/

# Уведомление тестеров через API
curl -X POST https://dist.internal/api/beta/notify \
  -H "Content-Type: application/json" \
  -d '{
    "version": "2.5.0",
    "platform": "ios",
    "url": "https://dist.internal/beta/MyApp.ipa",
    "groups": ["qa-team", "beta-testers"]
  }'
```

### Очистка и ротация beta-артефактов

```bash
# Удаление бинарников старше 90 дней с дистрибуционного сервера
find /var/www/beta/ -type f -mtime +90 -delete

# Очистка старых IPA/AAB из CI артефактов (GitLab)
# GitLab: настроить expire_in при upload

# Очистка старых builds из TestFlight (через App Store Connect API)
fastlane pilot delete_all_builds \
  --app_identifier com.company.app \
  --days 90

# Очистка старых builds из Google Play (через Fastlane)
fastlane supply track:internal \
  --json_key ./service-account.json \
  --skip_upload_apk \
  --skip_upload_aab
# Примечание: Fastlane не удаляет builds, используйте Google Play Console API
```

### Управление retention policy

```bash
# Настройка автоматической очистки через launchd (macOS)
cat <<'EOF' | sudo tee /Library/LaunchDaemons/com.company.beta-cleanup.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.company.beta-cleanup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/beta-cleanup.sh</string>
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

sudo launchctl load /Library/LaunchDaemons/com.company.beta-cleanup.plist
```

---

## Устранение проблем

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Build processing stuck** | Apple/Google обрабатывает бинарник дольше ожидаемого | Проверьте статус в App Store Connect / Play Console, подождите или перезагрузите бинарник |
| **Beta review rejected** | Нарушение guidelines, неполная информация | Заполните все обязательные поля, исправьте проблемы, отправьте повторно |
| **TestFlight build expired** | Build не обновлялся 90 дней | Загрузите новый бинарник, увеличьте build number |
| **Tester not receiving invitation** | Неверный email, спам-фильтр | Проверьте email, отправьте повторное приглашение |
| **Crash rate high in beta** | Критическая регрессия в новой версии | Остановите beta, соберите crash logs, подготовьте hotfix |
| **Distribution upload failed** | Неверный app ID, токен истек, сетевые проблемы | Проверьте credentials, обновите токен, проверьте сеть |
| **Google Play 403** | Service Account не имеет прав | Добавьте аккаунт с ролью "Release Manager" в Play Console |
| **External testing limit reached** | Превышен лимит 10 000 тестеров | Удалите неактивных тестеров или перейдите на Open Testing |
| **Beta feedback not arriving** | SDK не инициализирован, неправильная конфигурация | Проверьте инициализацию feedback SDK в приложении |
| **Promotion failed** | Не пройдены quality gates | Проверьте crash-free rate, security scan, все тесты |
| **OTA install failed (iOS)** | Неверный manifest, URL недоступен, SSL ошибка | Проверьте manifest.plist, доступность URL, срок действия SSL-сертификата |
| **Self-hosted server disk full** | Beta-артефакты заполнили диск | Настройте retention policy, автоматическую очистку через launchd/cron |
| **Beta feedback spam** | Боты или нерелевантные отзывы | Настройте фильтрацию по keywords, CAPTCHA или ограничьте доступ по invite |
| **TestFlight Beta Review затягивается** | Неполная Test Information, missing demo account | Предоставьте все данные заранее, убедитесь что demo account работает |

---

## Рекомендации

### Best Practices

- **Phased Beta:** Начинайте с Internal (1–2 дня), затем Closed (3–7 дней), затем Open (1–2 недели). Не пропускайте фазы.
- **Automated Distribution:** Автоматизируйте загрузку в TestFlight/Play Console/внутренний сервер. Ручной процесс — источник ошибок.
- **Beta Review Preparation:** Заполняйте Test Information заранее. Это ускоряет beta review на 24–48 часов.
- **Feedback Automation:** Встроите feedback form в приложение. Автоматически собирайте crash reports и analytics.
- **Quality Gates:** Установите crash-free rate > 99% как prerequisite для продвижения в следующий track.
- **Tester Management:** Документируйте тестеров, их роли и feedback. Используйте группы для targeting.
- **Toil Reduction:** Автоматизируйте уведомления тестеров, сбор feedback, отчеты. Измеряйте долю ручной работы.
- **Error Budget:** Установите 0 critical bugs в beta. При обнаружении — halt release.
- **Artifact Retention:** Храните beta-артефакты минимум 90 дней. Настройте автоматическую очистку.
- **Keystone Protection:** Разворачивайте distribution infrastructure на dedicated серверах с hot-standby. Мониторьте доступность отдельно от пайплайна.

### Edge Cases и ограничения

1. **TestFlight processing time:** Build может обрабатываться 10–30 минут. Учитывайте это при планировании beta release.
2. **Beta review delay:** External Testing требует beta review (24–48ч). Plan accordingly.
3. **Tester limits:** TestFlight Internal — 100, External — 10 000. Google Play Internal — 100, Closed — 2 000, Open — неограниченно.
4. **Build expiration:** TestFlight builds expire через 90 дней. Автоматически обновляйте builds.
5. **Distribution limits:** Внутренние серверы могут иметь лимиты на количество distributions в день. Plan accordingly.
6. **Feedback spam:** Beta feedback может содержать спам. Используйте moderation или automated filtering.
7. **Platform-specific issues:** iOS и Android имеют разные процессы. Документируйте различия.
8. **Compliance:** Beta-тестирование может требовать NDA, особенно для regulated industries.
9. **SSL certificate expiration:** Self-hosted distribution требует валидного SSL. Настройте мониторинг и auto-renewal.
10. **Network reliability:** Загрузка бинарников на внутренний сервер может падать из-за сетевых проблем. Настройте retry и fallback.

---

## Мониторинг и Observability

**Ключевые метрики:**
- **Beta Adoption Rate:** % тестеров, установивших beta
- **Crash-free Rate (Beta):** % сессий без crash (цель: > 99%)
- **Feedback Volume:** количество feedback'ов per день
- **Critical Bugs (Beta):** количество SEV1/SEV2 багов
- **Time to Feedback:** среднее время от установки до первого feedback
- **Build Processing Time:** время от upload до availability у тестеров
- **Promotion Success Rate:** % успешно продвинутых builds
- **Distribution Uptime:** доступность self-hosted distribution серверов

**Alert Rules:**
```yaml
groups:
  - name: beta_testing_alerts
    rules:
      - alert: BetaCrashRateHigh
        expr: crash_free_rate{track="beta"} < 0.99
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Beta crash-free rate below 99%"
      
      - alert: BetaCriticalBug
        expr: beta_critical_bugs_total > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Critical bug in beta"
      
      - alert: BetaAdoptionLow
        expr: beta_adoption_rate < 0.5
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Beta adoption rate below 50%"
      
      - alert: DistributionServerDown
        expr: up{job="beta-distribution"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Self-hosted beta distribution server is down"
      
      - alert: BuildProcessingStuck
        expr: testflight_build_processing_seconds > 1800
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "TestFlight build processing stuck for > 30 min"
```

**Quality Gates:**
- Crash-free rate > 99% на Internal Testing
- No critical bugs перед продвижением в External/Closed Testing
- Все feedback'ы reviewed и triaged
- Beta review approved (iOS External)
- Distribution infrastructure healthy (self-hosted)

**SRE Observability для beta distribution:**
- **Latency:** Время загрузки бинарника с дистрибуционного сервера (p50, p95, p99).
- **Availability:** Uptime дистрибуционного сервера и feedback API (target: 99.9%).
- **Error Rate:** % неудачных загрузок и API-вызовов.
- **Build Queue Depth:** Количество бинарников в очереди на обработку магазином.

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — процедуры реагирования на beta-инциденты.
- **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins, интеграция с TestFlight/Play Console.
