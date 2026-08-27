# Fastlane: Автоматизация Mobile CI/CD

## Определения

**Fastlane** — это Open Source платформа для автоматизации жизненного цикла мобильных приложений. Она абстрагирует сложные команды командной строки Apple (xcodebuild) и Google (gradle), предоставляя единый интерфейс на языке Ruby для сборки, тестирования и публикации.

К 2026 году Fastlane является стандартом индустрии (SSoT) для мобильных пайплайнов, позволяя реализовать подход **Automation as Code**.

---

## Базовые концепции

### Архитектура компонентов

*   **Actions:** Атомарные функции (например, `gym` для сборки iOS, `gradle` для Android). Существует более 200 встроенных действий.
*   **Lanes:** Группы действий, объединенные в логический сценарий (например, `lane :beta` выполняет сборку -> отправку в TestFlight -> уведомление в Slack).
*   **Fastfile:** Основной конфигурационный файл на языке Ruby.
*   **Appfile:** Файл для хранения статичных идентификаторов (Bundle ID, Team ID, Apple ID).
*   **Plugins:** Дополнительные модули, расширяющие возможности Fastlane (например, интеграция с Sentry или Firebase).

### Среда выполнения (Environment)

Fastlane написан на Ruby. Для стабильности в CI/CD **критически важно** фиксировать версии зависимостей.

1.  **Ruby:** Рекомендуется использовать менеджеры версий (`mise`, `asdf`, `rbenv`) и версию Ruby 3.2+.
2.  **Bundler:** Всегда запускайте Fastlane через `bundle exec fastlane`. Это гарантирует, что все плагины и сама платформа имеют ту же версию, что и у разработчика.
3.  **Локаль:** macOS-раннеры требуют явного указания кодировки UTF-8 для корректной обработки имен файлов.

---

## Практическая реализация

### 1. Подготовка окружения (Gemfile)

Создайте `Gemfile` в корне проекта:
```ruby
source "https://rubygems.org"

gem "fastlane"
gem "cocoapods" # Если проект использует CocoaPods
```
Затем выполните `bundle install`.

### 2. Сценарий: Комплексный Fastfile (iOS + Android)

Современные проекты часто используют единый Fastfile для обеих платформ.

```ruby
default_platform(:ios)

platform :ios do
  desc "Сборка и загрузка iOS в TestFlight"
  lane :beta do
    # Аутентификация через API Key
    app_store_connect_api_key(
      key_id: ENV["ASC_KEY_ID"],
      issuer_id: ENV["ASC_ISSUER_ID"],
      key_content: ENV["ASC_KEY_CONTENT"]
    )
    
    match(type: "appstore", readonly: true)
    increment_build_number(xcodeproj: "MyApp.xcodeproj")
    build_app(scheme: "MyApp", output_directory: "./build")
    upload_to_testflight(skip_waiting_for_build_processing: true)
    
    slack(message: "iOS build uploaded successfully!")
  end
end

platform :android do
  desc "Сборка и загрузка Android в Play Store Internal"
  lane :internal do
    gradle(task: "bundle", build_type: "Release")
    
    supply(
      track: "internal",
      aab: "app/build/outputs/bundle/release/app-release.aab",
      json_key_data: ENV["GCP_SERVICE_ACCOUNT_JSON"]
    )
    
    slack(message: "Android build uploaded successfully!")
  end
end
```

**Расширенный Fastfile с обработкой ошибок и retry:**
```ruby
default_platform(:ios)

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
      
      # Сборка с проверкой
      build_app(
        scheme: "MyApp",
        output_directory: "./build",
        clean: true,
        export_method: "app-store"
      )
      
      # Загрузка с retry
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
      
      slack(message: "iOS build uploaded successfully!")
      
    rescue => e
      slack(message: "iOS build failed: #{e.message}")
      raise
    ensure
      # Очистка после сборки
      clean_build_artifacts
    end
  end

  desc "Тестирование с детальным отчетом"
  lane :test do
    run_tests(
      project: "MyApp.xcodeproj",
      scheme: "MyAppTests",
      devices: ["iPhone 15 Pro", "iPad Pro (12.9-inch)"],
      code_coverage: true,
      output_types: "junit,html",
      output_directory: "fastlane/test_output",
      fail_build: false
    )
  end

  desc "Сборка скриншотов для App Store"
  lane :screenshots do
    capture_screenshots(
      project: "MyApp.xcodeproj",
      scheme: "MyAppUITests",
      devices: ["iPhone 15 Pro", "iPhone 15 Pro Max", "iPad Pro (12.9-inch)"],
      languages: ["en-US", "ru-RU"],
      clear_previous_screenshots: true,
      local_only: false
    )
  end
end
```

### 3. Управление версиями

**Автоматическое увеличение версии:**
```ruby
# Увеличение build_number
increment_build_number(
  xcodeproj: "MyApp.xcodeproj",
  build_number: Time.now.strftime("%Y%m%d%H%M")
)

# Увеличение version_number (маркетинговая версия)
increment_version_number(
  xcodeproj: "MyApp.xcodeproj",
  bump_type: "patch" # patch, minor, major
)
```

**Использование плагина versioning:**
```ruby
# Получение текущей версии
current_version = get_version_number(
  xcodeproj: "MyApp.xcodeproj"
)

# Установка версии из переменной окружения
if ENV["APP_VERSION"]
  increment_version_number(
    xcodeproj: "MyApp.xcodeproj",
    version_number: ENV["APP_VERSION"]
  )
end
```

### 4. Интеграция с Match

**Использование Match в CI/CD:**
```ruby
# Match для App Store
match(
  type: "appstore",
  readonly: true, # В CI используйте только readonly
  app_identifier: "com.company.app"
)

# Match для Development
match(
  type: "development",
  readonly: false, # Только локально
  app_identifier: "com.company.app"
)

# Проверка сертификатов
match_verify(
  type: "appstore",
  app_identifier: "com.company.app"
)
```

### 5. Создание Custom Actions

Если встроенных действий недостаточно, можно создать свои. Это позволяет переиспользовать сложную логику между проектами.

```bash
fastlane new_action --name my_custom_logic
```
Это создаст файл в `fastlane/actions/my_custom_logic.rb`, где можно описать параметры, описание и саму логику на Ruby.

**Пример Custom Action с параметрами:**
```ruby
# fastlane/actions/build_with_cache.rb
module Fastlane
  module Actions
    class BuildWithCache < Action
      def self.run(params)
        # Проверка кэша
        if File.exist?("build/cache.txt")
          UI.message("Используем кэш сборки")
          # Восстановление из кэша
        else
          UI.message("Создаем новый кэш")
          # Выполнение сборки
        end
      end

      def self.description
        "Сборка с кэшированием"
      end

      def self.available_options
        [
          FastlaneCore::ConfigItem.new(
            key: :scheme,
            description: "Название схемы",
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
        ["Your Name"]
      end

      def self.is_supported?(platform)
        [:ios, :android].include?(platform)
      end
    end
  end
end
```

---

## Безопасность и секреты

### Аутентификация (2025-2026)

*   **iOS:** Используйте **App Store Connect API Key** (.p8 файл). Это избавляет от проблем с 2FA и истекающими сессиями. Содержимое файла `.p8` должно передаваться через переменную окружения `ASC_KEY_CONTENT`.
*   **Android:** Используйте **Google Cloud Service Account JSON**. Права доступа должны быть ограничены только "Release Manager" в Play Console.

### Переменные окружения (Dotenv)
Fastlane автоматически подгружает файлы `.env`. В CI/CD эти переменные должны задаваться через настройки пайплайна (Secrets).

---

## Валидация и диагностика

### Проверка конфигурации
```bash
bundle exec fastlane lanes   # Список всех доступных сценариев
bundle exec fastlane action <action_name> # Документация по конкретному действию
```

**Диагностические команды:**
```bash
# Проверка всех установленных плагинов
bundle exec fastlane search_plugins

# Проверка текущей версии Fastlane
bundle exec fastlane --version

# Проверка Gemfile.lock
bundle check

# Проверка доступных устройств (iOS)
xcrun simctl list devices

# Проверка версии Xcode
xcodebuild -version

# Проверка доступных сертификатов
security find-identity -v -p codesigning
```

**Отладка Fastfile:**
```bash
# Запуск с подробным логом
bundle exec fastlane beta --verbose

# Запуск конкретного шага
bundle exec fastlane beta --debug

# Проверка синтаксиса Fastfile
bundle exec fastlane lanes --json
```

### Устранение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Invalid Ruby version** | Используется системный Ruby macOS. | Установите Ruby через `mise` и используйте `Gemfile`. |
| **Timeout during build** | xcodebuild не получает ответа от симулятора. | Используйте `xcrun simctl shutdown all` перед тестами. |
| **401 Unauthorized (App Store)** | Неверный API Key или истекшая сессия. | Проверьте `ASC_KEY_ID` и убедитесь, что ключ не отозван в App Store Connect. |
| **"No such file or directory"** | Неверный путь к проекту или артефакту. | Проверьте пути в `xcodeproj` и `output_directory`. |
| **"Fastlane not found"** | Fastlane не установлен или не добавлен в PATH. | Выполните `gem install fastlane` или используйте `bundle exec`. |
| **"Could not find Action"** | Плагин не установлен или имя действия неверно. | Выполните `bundle exec fastlane search_plugins <action_name>` и установите плагин. |
| **"No code signing identity"** | Сертификат не найден в Keychain. | Убедитесь, что `match` запущен с `readonly: true` и сертификаты доступны. |
| **"Provisioning profile expired"** | Профиль истек или не обновлен. | Выполните `fastlane match appstore --force_for_new_devices`. |
| **"Build output directory not found"** | Неверный путь для сохранения артефактов. | Проверьте `output_directory` в `build_app`. |
| **"Invalid JSON key file"** | Неверный формат JSON для Google Play. | Убедитесь, что JSON ключ валиден и содержит необходимые поля. |
| **"Sandbox error: Permission denied"** | macOS sandbox блокирует доступ к файлам. | Добавьте терминал в **Full Disk Access** в системных настройках. |
| **"Unable to find a destination"** | Указанное устройство/симулятор не найдено. | Проверьте список: `xcrun simctl list devices available`. |
| **"timeout_fastlane_build"** | Сборка превысила таймаут CI. | Увеличьте таймаут в настройках раннера или оптимизируйте сборку. |
| **"No artifacts found"** | Артефакты не созданы или путь неверен. | Проверьте, что `build_app` создает IPA/AAB в указанной директории. |

---

## Мониторинг и Observability

### Метрики для отслеживания
- **Lane Success Rate:** Процент успешных запусков lane (целевое значение: > 95%).
- **Lane Duration:** Среднее время выполнения lane (целевое значение: < 15 минут для beta).
- **Error Rate:** Частота ошибок по типам (build, upload, test).
- **Build Size:** Размер IPA/AAB (целевое значение: < 150 МБ для iOS, < 100 МБ для Android).
- **Test Coverage:** Процент покрытия кода тестами (целевое значение: > 70%).

### Интеграция с метриками
```ruby
# В Fastfile - отправка метрик в Prometheus pushgateway
lane :beta do
  start_time = Time.now
  
  # ... выполнение lane ...
  
  duration = Time.now - start_time
  
  # Отправка метрик
  system("echo 'fastlane_lane_duration_seconds{lane=\"beta\",platform=\"ios\"} #{duration}' | curl -X POST --data-binary @- http://localhost:9091/metrics/job/fastlane")
end
```

### Логирование и отчеты
```ruby
# Включение подробного логирования
ENV["FASTLANE.verbose"] = "true"
ENV["FASTLANE.hide_xcode_output"] = "false"

# Генерация HTML-отчета
lane :beta do
  # ... выполнение lane ...
  
  # Создание отчета
  html_report = File.read("fastlane/report.html")
  File.write("fastlane/report_#{Time.now.strftime('%Y%m%d_%H%M%S')}.html", html_report)
end
```

### См. также:

---

## Edge Cases и ограничения

1.  **Версии Ruby:** Системный Ruby macOS может конфликтовать с требуемыми версиями. Всегда используйте менеджеры версий (`mise`, `rbenv`).
2.  **Кэширование Gemfile:** Не кэшируйте `vendor/bundle` между разными ветками — это может привести к конфликтам зависимостей.
3.  **Лимиты API:** App Store Connect API Key имеет лимиты на количество запросов. Не запускайте слишком много lane одновременно.
4.  **Временные файлы:** Fastlane создает временные файлы в `fastlane/report.xml` и `fastlane/README.md`. Очищайте их после сборки.
5.  **Совместимость плагинов:** Некоторые плагины могут быть несовместимы с последними версиями Fastlane. Проверяйте changelog перед обновлением.
6.  **Ошибки Ruby:** Ошибки в Fastfile могут быть неочевидными. Используйте `bundle exec fastlane lanes --verbose` для отладки.
7.  **Сетевые задержки:** На удаленных раннерах загрузка зависимостей может занять много время. Используйте локальные зеркала.
8.  **Лимиты артефактов:** Fastlane не ограничивает размер артефактов, но CI-система может иметь ограничения.

### Важные плагины
- `fastlane-plugin-versioning`: Управление версиями без редактирования plist/gradle.
- `fastlane-plugin-firebase_app_distribution`: Загрузка в Firebase.
- `fastlane-plugin-badge`: Добавление иконки "Beta" на иконку приложения.
- `fastlane-plugin-match`: Управление сертификатами и профилями.
- `fastlane-plugin-increment_build_number`: Увеличение build number.
- `fastlane-plugin-scan`: Управление тестами с отчетами.

### См. также:
*   **[iOS CI/CD: Подробности про Match и API Key](./ios-ci-cd.md)**
*   **[Android CI/CD: Supply и Keystore](./android-ci-cd.md)**
*   **[Обзор Mobile CI/CD и инфраструктуры](./index.md)**
*   **[GitLab CI/CD для iOS и macOS](./gitlab-ios-ci.md)**
*   **[Официальная документация Fastlane](https://docs.fastlane.tools/)**
