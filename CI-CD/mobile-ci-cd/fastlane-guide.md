# Fastlane: Автоматизация Mobile CI/CD

## Определения

**Fastlane** — open-source платформа для автоматизации жизненного цикла мобильных приложений. Абстрагирует команды `xcodebuild` (Apple) и `gradle` (Android), предоставляя единый интерфейс на Ruby для сборки, тестирования и публикации.

**Action** — атомарная операция Fastlane (например, `gym`, `scan`, `sigh`, `supply`). Существует более 200 встроенных actions.

**Lane** — именованный сценарий, объединяющий actions в логическую последовательность (например, `lane :beta` выполняет сборку → подпись → загрузку в TestFlight).

**Fastfile** — основной конфигурационный файл на Ruby, описывающий lanes, платформы и их параметры.

**Appfile** — файл для хранения статичных идентификаторов (Bundle ID, Team ID, Apple ID, Play Store service account).

**Plugin** — внешний модуль, расширяющий стандартный набор actions (например, интеграция с Sentry, Firebase, versioning).

**Automation as Code** — подход, при котором весь пайплайн описан в виде управляемого кода (Fastfile + CI config), что обеспечивает идемпотентность и auditability.

---

## Базовые концепции

### Архитектура компонентов

Fastlane состоит из трёх уровней:

1. **Core:** Движок на Ruby, парсящий Fastfile, управляющий зависимостями между actions и передающий параметры.
2. **Built-in Actions:** Встроенный набор operations (сборка, тесты, подпись, загрузка). Каждый action имеет входные параметры, выходные значения и обработку ошибок.
3. **Plugins:** Дополнительный слой, подключаемый через `plugins` в Fastfile или `fastlane plugin add`. Позволяют переиспользовать корпоративную логику между проектами.

### Жизненный цикл lane

```
Запуск lane
    ↓
Загрузка Appfile / Fastfile
    ↓
Проверка зависимостей (Ruby gems, plugins)
    ↓
Последовательное/параллельное выполнение actions
    ↓
Обработка ошибок (rescue/ensure блоки)
    ↓
Очистка артефактов / отключение Keychain
    ↓
Отправка уведомлений / метрик
```

### Среда выполнения

Fastlane написан на Ruby. Для production-grade окружения критична фиксация версий:

- **Ruby:** Используйте менеджеры версий (`mise`, `asdf`, `rbenv`) с версией Ruby 3.2+.
- **Bundler:** Всегда запускайте через `bundle exec fastlane`. Это гарантирует, что плагины и Fastlane имеют зафиксированные версии, идентичные локальной разработке.
- **Локаль:** macOS-раннеры требуют явного указания UTF-8 для корректной обработки имен файлов и путей.

### SRE-подход к Fastlane

**Принципы:**

- **Error Budget для lanes:** Договоритесь о допустимом проценте проваленных запусков lane (например, 5% в месяц). При исчерпании бюджета фокус смещается на стабилизацию, а не на новые фичи.
- **MTTR (Mean Time To Repair):** Среднее время восстановления lane после сбоя. Целевое значение: < 15 минут для production-сборок.
- **Toil Reduction:** Автоматизируйте рутинные операции (инкремент версий, очистка DerivedData, ротацию сертификатов). Измеряйте долю toil в работе команды.
- **Observability:** Каждый lane должен генерировать структурированные логи и метрики (длительность, статус, размер артефакта) для последующего анализа.

---

## Практические сценарии

### 1. Подготовка окружения

#### Gemfile

Создайте `Gemfile` в корне проекта:

```ruby
source "https://rubygems.org"

gem "fastlane"
gem "cocoapods" # Опционально, для iOS проектов
```

Выполните `bundle install`. Убедитесь, что `Gemfile.lock` зафиксирован в репозитории.

#### Инициализация

```bash
fastlane init
# Выберите тип автоматизации: iOS, Android или обоих
# Создаст Fastfile и Appfile
```

### 2. Единый Fastfile для iOS и Android

Современные проекты используют единый Fastfile с платформенными lanes:

```ruby
default_platform(:ios)

platform :ios do
  desc "Сборка и загрузка iOS в TestFlight"
  lane :beta do
    app_store_connect_api_key(
      key_id: ENV["ASC_KEY_ID"],
      issuer_id: ENV["ASC_ISSUER_ID"],
      key_content: ENV["ASC_KEY_CONTENT"]
    )

    match(type: "appstore", readonly: true)
    increment_build_number(xcodeproj: "MyApp.xcodeproj")
    build_app(
      scheme: "MyApp",
      output_directory: "./build",
      clean: true,
      export_method: "app-store"
    )
    upload_to_testflight(skip_waiting_for_build_processing: true)

    notify_slack(message: "iOS build uploaded successfully!")
  end
end

platform :android do
  desc "Сборка и загрузка Android в Play Store Internal"
  lane :internal do
    gradle(task: "bundle", build_type: "Release")

    supply(
      track: "internal",
      aab: "app/build/outputs/bundle/release/app-release.aab",
      json_key_data: ENV["PLAY_STORE_SERVICE_ACCOUNT_JSON"]
    )

    notify_slack(message: "Android build uploaded successfully!")
  end
end
```

**Важно:** Переменная `PLAY_STORE_SERVICE_ACCOUNT_JSON` содержит JSON-ключ service account, передаваемый через CI-секреты. Никогда не коммитьте этот ключ в репозиторий.

### 3. Надёжная lane с обработкой ошибок и retry

```ruby
platform :ios do
  desc "Надежная сборка с обработкой ошибок"
  lane :beta do
    begin
      app_store_connect_api_key(
        key_id: ENV["ASC_KEY_ID"],
        issuer_id: ENV["ASC_ISSUER_ID"],
        key_content: ENV["ASC_KEY_CONTENT"]
      )

      match(type: "appstore", readonly: true)
      increment_build_number(xcodeproj: "MyApp.xcodeproj")

      build_app(
        scheme: "MyApp",
        output_directory: "./build",
        clean: true,
        export_method: "app-store"
      )

      # Retry-логика для загрузки
      retry_attempts = 3
      retry_attempts.times do |attempt|
        begin
          upload_to_testflight(skip_waiting_for_build_processing: true)
          break
        rescue => e
          UI.error("Попытка #{attempt + 1} не удалась: #{e.message}")
          sleep(30) if attempt < retry_attempts - 1
          raise if attempt == retry_attempts - 1
        end
      end

      notify_slack(message: "iOS build uploaded successfully!")

    rescue => e
      notify_slack(message: "iOS build failed: #{e.message}")
      raise
    ensure
      # Гарантированная очистка после сборки
      clean_build_artifacts
    end
  end
end
```

### 4. Управление версиями

```ruby
# Автоматическое увеличение build_number на основе timestamp
increment_build_number(
  xcodeproj: "MyApp.xcodeproj",
  build_number: Time.now.strftime("%Y%m%d%H%M")
)

# Маркетинговая версия
increment_version_number(
  xcodeproj: "MyApp.xcodeproj",
  bump_type: "patch" # patch, minor, major
)

# Версия из переменной окружения (для release-сборок)
if ENV["APP_VERSION"]
  increment_version_number(
    xcodeproj: "MyApp.xcodeproj",
    version_number: ENV["APP_VERSION"]
  )
end
```

### 5. Создание custom actions

Если встроенных actions недостаточно, создайте свои:

```bash
fastlane new_action --name build_with_cache
```

Генерирует файл `fastlane/actions/build_with_cache.rb`:

```ruby
module Fastlane
  module Actions
    class BuildWithCacheAction < Action
      def self.run(params)
        cache_path = "build/cache.txt"

        if File.exist?(cache_path)
          UI.message("Используем кэш сборки")
          # Восстановление из кэша
        else
          UI.message("Создаем новый кэш")
          # Выполнение сборки
        end
      end

      def self.description
        "Сборка с кэшированием для ускорения инкрементальных сборок"
      end

      def self.available_options
        [
          FastlaneCore::ConfigItem.new(
            key: :scheme,
            description: "Название схемы Xcode",
            optional: false
          ),
          FastlaneCore::ConfigItem.new(
            key: :clean,
            description: "Очищать ли перед сборкой",
            default_value: true
          )
        ]
      end

      def self.authors
        ["Team Name"]
      end

      def self.is_supported?(platform)
        [:ios, :android].include?(platform)
      end
    end
  end
end
```

### 6. Мониторинг и Observability

#### Метрики lane

Отслеживайте ключевые показатели:

- **Lane Success Rate:** Процент успешных запусков (цель: > 95%).
- **Lane Duration:** Среднее время выполнения (цель: < 15 минут для beta).
- **Error Rate:** Частота ошибок по типам (build, upload, test).
- **Build Size:** Размер IPA/AAB (цель: < 150 МБ iOS, < 100 МБ Android).

#### Интеграция с Prometheus Pushgateway

```ruby
lane :beta do
  start_time = Time.now

  # ... выполнение lane ...

  duration = Time.now - start_time

  # Отправка метрик
  system("echo 'fastlane_lane_duration_seconds{lane=\"beta\",platform=\"ios\"} #{duration}' | curl -X POST --data-binary @- http://localhost:9091/metrics/job/fastlane")
end
```

#### Структурированное логирование

```ruby
ENV["FASTLANE.verbose"] = "true"
ENV["FASTLANE.hide_xcode_output"] = "false"

# В lane — запись отчета
lane :beta do
  # ... выполнение lane ...

  report_path = "fastlane/report_#{Time.now.strftime('%Y%m%d_%H%M%S')}.html"
  File.write(report_path, File.read("fastlane/report.html"))
end
```

---

## Операции и команды

### Управление lanes

```bash
# Список всех доступных lanes
bundle exec fastlane lanes

# Документация по конкретному action
bundle exec fastlane action <action_name>

# Поиск плагинов
bundle exec fastlane search_plugins
```

### Диагностика окружения

```bash
# Версия Fastlane
bundle exec fastlane --version

# Проверка Gemfile
bundle check

# Доступные симуляторы iOS
xcrun simctl list devices available

# Версия Xcode
xcodebuild -version

# Сертификаты в Keychain
security find-identity -v -p codesigning

# Размер DerivedData
du -sh ~/Library/Developer/Xcode/DerivedData
```

### Отладка

```bash
# Запуск с подробным логом
bundle exec fastlane beta --verbose

# Запуск с debug-уровнем
bundle exec fastlane beta --debug

# Проверка синтаксиса Fastfile
bundle exec fastlane lanes --json
```

---

## Устранение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Invalid Ruby version** | Используется системный Ruby macOS. | Установите Ruby через `mise` и используйте `Gemfile`. |
| **Timeout during build** | `xcodebuild` не получает ответ от симулятора. | Выполните `xcrun simctl shutdown all` перед тестами. |
| **401 Unauthorized** | Неверный API Key или истекшая сессия. | Проверьте `ASC_KEY_ID` и убедитесь, что ключ активен в App Store Connect. |
| **"No such file or directory"** | Неверный путь к проекту или артефакту. | Проверьте `xcodeproj` и `output_directory`. |
| **"Fastlane not found"** | Fastlane не установлен или не в PATH. | Используйте `bundle exec fastlane` или `gem install fastlane`. |
| **"Could not find Action"** | Плагин не установлен или имя действия неверно. | `bundle exec fastlane search_plugins <action_name>` → установите плагин. |
| **"No code signing identity"** | Сертификат не найден в Keychain. | Убедитесь, что `match` запущен и сертификаты доступны. См. **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)**. |
| **"Provisioning profile expired"** | Профиль истек или не обновлен. | Выполните `fastlane match appstore --force_for_new_devices`. |
| **"Build output directory not found"** | Неверный путь для артефактов. | Проверьте `output_directory` в `build_app`. |
| **"Sandbox error: Permission denied"** | macOS sandbox блокирует доступ. | Добавьте терминал в **Full Disk Access**. |
| **"Unable to find a destination"** | Указанный симулятор/устройство не найден. | `xcrun simctl list devices available`. |
| **timeout_fastlane_build** | Сборка превысила таймаут CI. | Увеличьте таймаут раннера или оптимизируйте сборку. |
| **"No artifacts found"** | Артефакты не созданы или путь неверен. | Проверьте, что `build_app` создает IPA/AAB в указанной директории. |

---

## Рекомендации

### Best Practices

- **Version Pinning:** Фиксируйте версии Ruby, Fastlane и плагинов через `Gemfile.lock`. Никогда не используйте `gem install fastlane` в CI без Bundler.
- **Least Privilege:** Runner-аккаунт должен иметь минимальные права. Не запускайте `gitlab-runner` или Fastlane под `root`.
- **Ephemeral Keychain:** Для iOS-сборок всегда создавайте временный Keychain внутри lane. Не используете системный login.keychain. См. **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)**.
- **Secrets Management:** Храните `ASC_KEY_CONTENT`, `MATCH_PASSWORD`, `PLAY_STORE_SERVICE_ACCOUNT_JSON` в CI-секретах (GitLab CI Variables). Никогда в репозитории.
- **Idempotency:** Каждый lane должен быть идемпотентным — повторный запуск даёт тот же результат. Используйте `clean: true` в `build_app`.
- **Modular Lanes:** Разделяйте lanes по ответственности: `beta` (сборка + загрузка), `test` (юниты + UI), `screenshots` (скриншоты). Это упрощает отладку и переиспользование.

### Edge Cases и ограничения

1. **Версии Ruby:** Системный Ruby macOS может конфликтовать с требуемыми версиями. Всегда используйте менеджеры версий (`mise`, `rbenv`).
2. **Кэширование Gemfile:** Не кэшируйте `vendor/bundle` между разными ветками — это может привести к конфликтам зависимостей.
3. **Лимиты API:** App Store Connect API имеет rate limits. Не запускайте слишком много lane одновременно. Используйте `readonly: true` для `match` в CI.
4. **Временные файлы:** Fastlane создает временные файлы в `fastlane/report.xml`. Очищайте их после сборки через `clean_build_artifacts`.
5. **Совместимость плагинов:** Проверяйте changelog перед обновлением. Некоторые плагины могут быть несовместимы с новыми версиями Fastlane.
6. **Сетевые задержки:** На удаленных раннерах загрузка зависимостей может занять время. Используйте локальные зеркала RubyGems.
7. **macOS Permissions:** На macOS 14+ приложения требуют явного разрешения на доступ к файлам (Full Disk Access) и сети (Developer Disk Image для симуляторов).

### Мониторинг и Observability

- **Логи:** Структурируйте вывод Fastlane. Используйте `UI.message`, `UI.success`, `UI.error` для ключевых этапов.
- **Метрики:** Экспортируйте длительность lane, статус и размер артефактов в Prometheus Pushgateway или аналогичный системный сборщик.
- **Алерты:** Настройте оповещения при превышении MTTR lane или падении Success Rate ниже порога Error Budget.
- **Runbook'и:** Для каждого типичного сбоя (падение Keychain, зависание симулятора, 401 Unauthorized) должно быть пошаговое руководство.

### Безопасность

- **App Store Connect API Key:** Используйте `.p8` ключ вместо Apple ID + 2FA. Храните в CI-секретах. Ротируйте ключи периодически.
- **Android Service Account:** JSON-ключ должен иметь минимальные права. Не давайте "Owner" — достаточно "Release Manager".
- **Match Password:** `MATCH_PASSWORD` — мастер-пароль для шифрования сертификатов. Храните в защищенных системах (HashiCorp Vault, CI Variables). Ротируйте ежегодно: `fastlane match change_password`.
- **Keychain Access:** Ограничьте права runner-аккаунта. Не запускайте Fastlane под `root`.

---

## Дополнительная информация

- **[iOS CI/CD: Подпись кода и Match](./ios-ci-cd.md)** — Provisioning Profiles, Fastlane Match, Keychain management.
- **[Android CI/CD: Подпись и публикация](./android-ci-cd.md)** — Keystore, Gradle signing, Supply.
- **[Обзор Mobile CI/CD и инфраструктуры](./index.md)** — архитектура macOS-раннеров, Tart/Orka, Golden Image, SRE-подход.
