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

### 3. Создание Custom Actions

Если встроенных действий недостаточно, можно создать свои. Это позволяет переиспользовать сложную логику между проектами.

```bash
fastlane new_action --name my_custom_logic
```
Это создаст файл в `fastlane/actions/my_custom_logic.rb`, где можно описать параметры, описание и саму логику на Ruby.

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

### Устранение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Invalid Ruby version** | Используется системный Ruby macOS. | Установите Ruby через `mise` и используйте `Gemfile`. |
| **Timeout during build** | xcodebuild не получает ответа от симулятора. | Используйте `xcrun simctl shutdown all` перед тестами. |
| **401 Unauthorized (App Store)** | Неверный API Key или истекшая сессия. | Проверьте `ASC_KEY_ID` и убедитесь, что ключ не отозван в App Store Connect. |

---

## Дополнительная информация

### Важные плагины
- `fastlane-plugin-versioning`: Управление версиями без редактирования plist/gradle.
- `fastlane-plugin-firebase_app_distribution`: Загрузка в Firebase.
- `fastlane-plugin-badge`: Добавление иконки "Beta" на иконку приложения.

### См. также:
*   **[iOS CI/CD: Подробности про Match и API Key](./ios-ci-cd.md)**
*   **[Android CI/CD: Supply и Keystore](./android-ci-cd.md)**
*   **[Обзор Mobile CI/CD и инфраструктуры](./index.md)**
*   **[Официальная документация Fastlane](https://docs.fastlane.tools/)**
