# Feature Flags в мобильных приложениях

## Определения

**Feature Flag** (он же Feature Toggle) — это механизм динамического включения/выключения функциональности приложения без необходимости публикации новой версии в магазине. Feature flags разделяют **развертывание кода** (code deployment) и **развертывание функциональности** (feature release).

**Progressive Delivery** — подход, при котором новый функционал разворачивается постепенно: от внутренних тестеров → малого процента пользователей → всем. Feature flags являются основным инструментом progressive delivery.

**Kill Switch** — feature flag, который позволяет мгновенно отключить проблемную функциональность в production без публикации hotfix-версии.

---

## Базовые концепции

### Типы Feature Flags

| Тип | Время жизни | Пример использования |
|:---|:---|:---|
| **Release Flags** | Дни-недели | Новая функция, разворачиваемая поэтапно |
| **Experiment Flags** | Дни-месяцы | A/B тесты (новый UI vs старый) |
| **Ops Flags** | Недели-месяцы | Rate limiting, degraded mode |
| **Permission Flags** | Постоянные | Premium функции,.role-based доступ |

### Архитектура Feature Flag System

```
┌─────────────────────────────────────────────┐
│              Mobile App                      │
│  ┌─────────────┐    ┌──────────────────┐   │
│  │ Flag Cache  │◄───│ Flag Evaluation  │   │
│  │ (local)     │    │ Engine           │   │
│  └─────────────┘    └────────┬─────────┘   │
│                              │              │
└──────────────────────────────┼──────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Flag Service API   │
                    │  (remote config)    │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Admin Dashboard    │
                    │  (targeting rules)  │
                    └─────────────────────┘
```

### Паттерны использования в Mobile

1. **Dark Launching:** Новая функция выполняется в фоне, но результат не показывается пользователю. Используется для сбора метрик производительности перед релизом.

2. **Canary Releases:** Функция включена для 1% → 5% → 25% → 100% пользователей. Мониторинг crash rate и ключевых метрик на каждом этапе.

3. **A/B Testing:** Два варианта функции показываются разным сегментам пользователей. Сравниваются конверсии, удержание, производительность.

4. **User Segmentation:** Функции доступны только определенным пользователям (beta-тестеры, premium, определенный регион).

### Ключевые метрики для Feature Flags

- **Flag Evaluation Latency:** Время получения значения флага (< 50ms).
- **Cache Hit Rate:** Процент обращений к локальному кэшу (> 95%).
- **Flag Consistency:** Синхронизация флагов между сессиями (< 5 секунд задержки).
- **Crash Rate Delta:** Изменение crash rate после включения флага.

---

## Практическая реализация

### 1. Firebase Remote Config (популярный выбор)

**Настройка в iOS (Swift):**
```swift
import FirebaseRemoteConfig

class FeatureFlagManager {
    static let shared = FeatureFlagManager()
    private let remoteConfig = RemoteConfig.remoteConfig()
    
    func setup() {
        let settings = RemoteConfigSettings()
        settings.minimumFetchInterval = 300 // 5 минут в production
        remoteConfig.configSettings = settings
        
        // Значения по умолчанию
        remoteConfig.setDefaults([
            "new_checkout_flow": false,
            "dark_mode_enabled": true,
            "max_upload_size_mb": 100
        ])
    }
    
    func fetchFlags(completion: @escaping () -> Void) {
        remoteConfig.fetchAndActivate { status, error in
            if let error = error {
                print("Ошибка загрузки флагов: \(error)")
                // Используем значения по умолчанию
            }
            completion()
        }
    }
    
    func isNewCheckoutFlowEnabled() -> Bool {
        return remoteConfig.configValue(forKey: "new_checkout_flow").boolValue
    }
    
    func getMaxUploadSize() -> Int {
        return remoteConfig.configValue(forKey: "max_upload_size_mb").intValue
    }
}
```

**Настройка в Android (Kotlin):**
```kotlin
import com.google.firebase.remoteconfig.FirebaseRemoteConfig

class FeatureFlagManager {
    private val remoteConfig: FirebaseRemoteConfig = FirebaseRemoteConfig.getInstance()
    
    fun setup() {
        val configSettings = remoteConfigSettings {
            minimumFetchIntervalInSeconds = 300
        }
        remoteConfig.setConfigSettingsAsync(configSettings)
        
        // Значения по умолчанию
        val defaults = mapOf(
            "new_checkout_flow" to false,
            "dark_mode_enabled" to true,
            "max_upload_size_mb" to 100
        )
        remoteConfig.setDefaultsAsync(defaults)
    }
    
    fun fetchFlags(onComplete: () -> Unit) {
        remoteConfig.fetchAndActivate()
            .addOnCompleteListener { task ->
                if (task.isSuccessful) {
                    onComplete()
                }
            }
    }
    
    fun isNewCheckoutFlowEnabled(): Boolean {
        return remoteConfig.getBoolean("new_checkout_flow")
    }
    
    fun getMaxUploadSize(): Long {
        return remoteConfig.getLong("max_upload_size_mb")
    }
}
```

### 2. Интеграция с CI/CD

**GitHub Actions: обновление feature flags перед сборкой:**
```yaml
update_feature_flags:
  stage: setup
  runs-on: ubuntu-latest
  steps:
    - name: Update Firebase Remote Config
      uses: wix/github-action-firebase-remote-config@master
      with:
        credentials: ${{ secrets.FIREBASE_CREDENTIALS }}
        config-file: ./remote-config_defaults.json
```

**Fastlane: управление флагами через Custom Action:**
```ruby
# fastlane/actions/toggle_feature_flag.rb
module Fastlane
  module Actions
    class ToggleFeatureFlag < Action
      def self.run(params)
        flag_name = params[:flag_name]
        enabled = params[:enabled]
        
        # Обновление Remote Config через Firebase CLI
        system("firebase remoteconfig:set #{flag_name}=#{enabled}")
        
        UI.success("Флаг #{flag_name} установлен в #{enabled}")
      end

      def self.available_options
        [
          FastlaneCore::ConfigItem.new(
            key: :flag_name,
            description: "Название флага",
            optional: false
          ),
          FastlaneCore::ConfigItem.new(
            key: :enabled,
            description: "Включен ли флаг",
            default_value: true
          )
        ]
      end
    end
  end
end
```

### 3. Локальный Feature Flag Service (без внешних зависимостей)

```swift
// Для оффлайн-режима или внутренних инструментов
class LocalFeatureFlags {
    private var flags: [String: Bool] = [:]
    private let userDefaults = UserDefaults.standard
    
    func loadFlags() {
        // Загрузка из UserDefaults или plist
        if let savedFlags = userDefaults.dictionary(forKey: "feature_flags") as? [String: Bool] {
            flags = savedFlags
        }
    }
    
    func isEnabled(_ flag: String, default: Bool = false) -> Bool {
        return flags[flag] ?? `default`
    }
    
    func setFlag(_ flag: String, enabled: Bool) {
        flags[flag] = enabled
        userDefaults.set(flags, forKey: "feature_flags")
    }
    
    // Remote обновление через push notification или API
    func updateFromServer() {
        // Запрос к API с текущими версиями флагов
        // Обновление локального кэша
    }
}
```

### 4. Тестирование Feature Flags

```swift
// Unit-тесты с мокированием флагов
class CheckoutViewModelTests: XCTestCase {
    func testNewCheckoutFlow() {
        let mockFlags = MockFeatureFlags()
        mockFlags.setFlag("new_checkout_flow", enabled: true)
        
        let viewModel = CheckoutViewModel(featureFlags: mockFlags)
        
        XCTAssertTrue(viewModel.shouldUseNewFlow())
    }
    
    func testDefaultCheckoutFlow() {
        let mockFlags = MockFeatureFlags()
        
        let viewModel = CheckoutViewModel(featureFlags: mockFlags)
        
        XCTAssertFalse(viewModel.shouldUseNewFlow())
    }
}

class MockFeatureFlags: FeatureFlagProvider {
    private var flags: [String: Bool] = [:]
    
    func isEnabled(_ flag: String) -> Bool {
        return flags[flag] ?? false
    }
    
    func setFlag(_ flag: String, enabled: Bool) {
        flags[flag] = enabled
    }
}
```

---

## Дополнительная информация

### Edge Cases

1. **Кэширование:** При отсутствии сети приложение использует закэшированные значения флагов. Убедитесь, что дефолтные значения безопасны.
2. **Версии приложения:** Старые версии приложения не должны ломаться при добавлении новых флагов. Всегда задавайте `default_value`.
3. **Конфликты флагов:** Документируйте зависимости между флагами (флаг B работает только если флаг A включен).
4. **Performance:** Feature flags не должны блокировать UI-поток. Используйте кэширование и асинхронную загрузку.
5. **Приватность:** Не передавайте пользовательские данные в feature flag service без шифрования и consent.

### Best Practices

- **Naming convention:** `feature_<team>_<name>` (например, `feature_checkout_new_flow`).
- **Documentation:** Для каждого флага документируйте цель,_owner, дату включения, критерии успеха.
- **Cleanup:** Удаляйте старые feature flags через 2-4 недели после полного rollout.
- **Monitoring:** Отслеживайте crash rate, ANR, производительность до/после включения флага.

### См. также:
*   **[Mobile CI/CD Overview](./index.md)**
*   **[iOS CI/CD](./ios-ci-cd.md)**
*   **[Android CI/CD](./android-ci-cd.md)**
*   **[Deployment Strategies](./deployment-strategies-mobile.md)**
*   **[Incident Response](./incident-response-mobile.md)**
