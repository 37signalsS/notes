# Feature Flags в мобильных приложениях

## Определения

**Feature Flag** (также Feature Toggle) — механизм динамического включения/выключения функциональности в рантайме без публикации новой версии в магазин. Feature flags разделяют **развертывание кода** (code deployment) и **развертывание функциональности** (feature release).

**Progressive Delivery** — подход к доставке обновлений, при котором новый функционал разворачивается постепенно: внутренние тестеры → малый процент пользователей → 100%. Feature flags являются основным инструментом progressive delivery в мобильных приложениях.

**Kill Switch** — специальный feature flag, позволяющий мгновенно отключить проблемную функциональность в production без публикации hotfix-версии.

**Remote Config** — внешняя конфигурация флагов, получаемая приложением из управляющего сервиса. Может быть реализована через self-hosted API, push-уведомления или локальный файл конфигурации.

**Bootstrap File** — файл с последним известным состоянием флагов, поставляемый внутри бинарника или загружаемый при первом запуске. Обеспечивает работоспособность приложения при отсутствии сети или недоступности сервиса.

---

## Базовые концепции

### Типы Feature Flags

| Тип | Время жизни | Пример использования |
|:---|:---|:---|
| **Release Flags** | Дни-недели | Новая функция, разворачиваемая поэтапно |
| **Experiment Flags** | Дни-месяцы | A/B тесты (новый UI vs старый) |
| **Ops Flags** | Недели-месяцы | Degraded mode, rate limiting, emergency kill switch |
| **Permission Flags** | Постоянные | Premium-функции, role-based доступ |

### Архитектура Feature Flag System

```
┌─────────────────────────────────────────────┐
│              Mobile App                      │
│  ┌─────────────┐    ┌──────────────────┐   │
│  │ Flag Cache  │◄───│ Flag Evaluation  │   │
│  │ (local)     │    │ Engine           │   │
│  │             │    │ + Fallback       │   │
│  └─────────────┘    └────────┬─────────┘   │
│                              │              │
└──────────────────────────────┼──────────────┘
                                │
                     ┌──────────▼──────────┐
                     │  Config Service API │
                     │  (self-hosted /     │
                     │   internal CDN)     │
                     └──────────┬──────────┘
                                │
                     ┌──────────▼──────────┐
                     │  Admin Dashboard    │
                     │  + Targeting Rules  │
                     └─────────────────────┘
```

### Паттерны использования в Mobile

1. **Dark Launching:** Новая функция выполняется в фоне, но результат не показывается пользователю. Используется для сбора метрик производительности перед релизом и проверки корректности интеграции с backend.

2. **Canary Releases:** Функция включена для 1% → 5% → 25% → 100% пользователей. На каждом этапе мониторится crash rate, ANR, API latency и бизнес-метрики. При превышении порога — автоматический откат или ручное вмешательство.

3. **A/B Testing:** Два варианта функции показываются разным сегментам пользователей. Сравниваются конверсия, удержание, производительность и stability. Важно: группы должны быть репрезентативными и независимыми.

4. **User Segmentation:** Функции доступны только определенным пользователям (beta-тестеры, premium-подписчики, определенный регион или версия ОС).

5. **Degraded Mode:** При проблемах с backend или внешними сервисами флаг переключает приложение в безопасный режим с ограниченной функциональностью, предотвращая каскадные сбои.

### Ключевые метрики для Feature Flags

- **Flag Evaluation Latency:** Время получения значения флага (< 50ms целевое).
- **Cache Hit Rate:** Процент обращений к локальному кэшу (> 95%).
- **Flag Consistency:** Время распространения нового значения флага среди активных сессий (< 5 секунд).
- **Crash Rate Delta:** Изменение crash rate после включения флага (прирост > 0.1% = стоп-сигнал).
- **Rollout Funnel:** Процент пользователей на каждом этапе progressive delivery.

### SRE-подход к Feature Flags

**Принципы:**

- **Error Budget для флагов:** Договоритесь о допустимом проценте проваленных evaluations (например, 0.1% в месяц). При исчерпании бюджета фокус смещается на стабилизацию сервиса конфигурации.
- **MTTR (Mean Time To Repair):** Среднее время восстановления работы флага после сбоя. Целевое значение: < 15 минут для production-флагов.
- **Toil Reduction:** Автоматизируйте проверку конфликтов флагов, ротацию экспериментальных флагов, отчетность по rollout-ам. Измеряйте долю ручной работы по управлению флагами.
- **Observability:** Каждый критический флаг должен иметь visibility: кто включил, когда, для какого сегмента и с какой целью. Все изменения логируются.

---

## Практические сценарии

### 1. Self-hosted локальная реализация (iOS/Android)

Локальный подход не требует внешних облачных сервисов. Флаги хранятся в файле конфигурации, получаемом через CDN или bundled в приложение.

**iOS (Swift):**
```swift
import Foundation

protocol FeatureFlagProvider {
    func isEnabled(_ flag: String) -> Bool
    func refresh(completion: @escaping () -> Void)
}

final class LocalFeatureFlags: FeatureFlagProvider {
    static let shared = LocalFeatureFlags()
    
    private let userDefaults = UserDefaults.standard
    private let cacheKey = "feature_flags"
    private let fallbackKey = "feature_flags_fallback"
    
    private init() {}
    
    func isEnabled(_ flag: String) -> Bool {
        guard let flags = userDefaults.dictionary(forKey: cacheKey) as? [String: Bool] else {
            return fallbackValue(for: flag)
        }
        return flags[flag] ?? fallbackValue(for: flag)
    }
    
    func refresh(completion: @escaping () -> Void) {
        guard let url = URL(string: "https://cdn.example.com/flags/ios.json") else {
            completion()
            return
        }
        
        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Bool] else {
                DispatchQueue.main.async { completion() }
                return
            }
            
            self?.userDefaults.set(json, forKey: self?.cacheKey ?? "feature_flags")
            self?.bootstrapFallback(from: json)
            DispatchQueue.main.async { completion() }
        }.resume()
    }
    
    private func fallbackValue(for flag: String) -> Bool {
        guard let fallback = userDefaults.dictionary(forKey: fallbackKey) as? [String: Bool] else {
            return false
        }
        return fallback[flag] ?? false
    }
    
    private func bootstrapFallback(from flags: [String: Bool]) {
        var current = userDefaults.dictionary(forKey: fallbackKey) as? [String: Bool] ?? [:]
        flags.forEach { current[$0.key] = $0.value }
        userDefaults.set(current, forKey: fallbackKey)
    }
}
```

**Android (Kotlin):**
```kotlin
import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URL

interface FeatureFlagProvider {
    fun isEnabled(flag: String): Boolean
    suspend fun refresh()
}

class LocalFeatureFlags(private val context: Context) : FeatureFlagProvider {
    private val prefs: SharedPreferences = context.getSharedPreferences("feature_flags", Context.MODE_PRIVATE)
    private val fallbackPrefs: SharedPreferences = context.getSharedPreferences("feature_flags_fallback", Context.MODE_PRIVATE)
    
    override fun isEnabled(flag: String): Boolean {
        return prefs.all[flag] as? Boolean ?: fallbackValue(flag)
    }
    
    override suspend fun refresh() = withContext(Dispatchers.IO) {
        try {
            val url = URL("https://cdn.example.com/flags/android.json")
            val text = url.readText()
            val json = JSONObject(text)
            
            prefs.edit().clear().apply {
                json.keys().forEachRemaining { key ->
                    putBoolean(key, json.getBoolean(key))
                }
                apply()
            }
            
            bootstrapFallback(json)
        } catch (e: Exception) {
            // Логируем, но не падаем — используем fallback
        }
    }
    
    private fun fallbackValue(flag: String): Boolean {
        return fallbackPrefs.all[flag] as? Boolean ?: false
    }
    
    private fun bootstrapFallback(json: JSONObject) {
        val editor = fallbackPrefs.edit()
        json.keys().forEachRemaining { key ->
            editor.putBoolean(key, json.getBoolean(key))
        }
        editor.apply()
    }
}
```

### 2. CI/CD интеграция

**Fastlane: Custom Action для управления флагами:**
```ruby
# fastlane/actions/toggle_feature_flag.rb
module Fastlane
  module Actions
    class ToggleFeatureFlagAction < Action
      def self.run(params)
        flag_name = params[:flag_name]
        enabled = params[:enabled]
        config_path = params[:config_path] || "fastlane/feature_flags.json"
        
        unless File.exist?(config_path)
          UI.user_error!("Config file not found: #{config_path}")
        end
        
        require "json"
        config = JSON.parse(File.read(config_path))
        
        unless config["flags"].is_a?(Hash)
          UI.user_error!("Invalid config format: expected flags hash")
        end
        
        config["flags"][flag_name] = enabled
        
        File.write(config_path, JSON.pretty_generate(config))
        UI.success("Flag #{flag_name} set to #{enabled}")
        
        { flag: flag_name, enabled: enabled }
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
            optional: false,
            type: Boolean
          ),
          FastlaneCore::ConfigItem.new(
            key: :config_path,
            description: "Путь к JSON-конфигу флагов",
            optional: true
          )
        ]
      end
    end
  end
end
```

**GitLab CI: обновление флагов перед сборкой:**
```yaml
update_feature_flags:
  stage: setup
  image: alpine:latest
  script:
    - apk add --no-cache curl jq
    - |
      curl -s "https://config-service.internal/api/v1/flags?app=myapp&platform=ios" \
        -H "Authorization: Bearer ${CONFIG_SERVICE_TOKEN}" \
        -o fastlane/feature_flags.json
    - cat fastlane/feature_flags.json | jq .
  artifacts:
    paths:
      - fastlane/feature_flags.json
    expire_in: 1 day
  only:
    - main
    - develop
```

### 3. Тестирование Feature Flags

```swift
import XCTest

protocol FeatureFlagProvider {
    func isEnabled(_ flag: String) -> Bool
}

final class CheckoutViewModelTests: XCTestCase {
    func testNewCheckoutFlowEnabled() {
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
    
    func testFallbackWhenFlagMissing() {
        let mockFlags = MockFeatureFlags()
        mockFlags.setFlag("unrelated_flag", enabled: true)
        
        let viewModel = CheckoutViewModel(featureFlags: mockFlags)
        
        XCTAssertFalse(viewModel.shouldUseNewFlow())
    }
}

final class MockFeatureFlags: FeatureFlagProvider {
    private var flags: [String: Bool] = [:]
    
    func isEnabled(_ flag: String) -> Bool {
        return flags[flag] ?? false
    }
    
    func setFlag(_ flag: String, enabled: Bool) {
        flags[flag] = enabled
    }
}
```

### 4. Observability в рантайме

Feature flags влияют на поведение приложения и должны быть частью observability stack:

**OpenTelemetry Span Attributes:**
```swift
import OpenTelemetryApi

func evaluateFlag(_ flag: String, provider: FeatureFlagProvider) -> Bool {
    let span = Tracer.currentSpan()
    let flagValue = provider.isEnabled(flag)
    
    span?.setAttribute("feature.flag.name", flag)
    span?.setAttribute("feature.flag.value", flagValue ? "true" : "false")
    span?.setAttribute("feature.flag.source", "local_cache")
    
    return flagValue
}
```

**Метрики для экспорта в Prometheus:**
- `feature_flag_evaluations_total{flag="new_checkout",value="true"}` — счетчик evaluations
- `feature_flag_fallback_used_total{flag="new_checkout"}` — fallback сработал
- `feature_flag_refresh_duration_seconds` — длительность обновления
- `feature_flag_cache_hit_ratio` — доля попаданий в кэш

---

## Операции и команды

### Управление конфигурацией флагов

```bash
# Валидация JSON-конфига флагов
jq '.' fastlane/feature_flags.json > /dev/null && echo "OK" || echo "INVALID JSON"

# Проверка обязательных полей
jq '.flags | keys | sort' fastlane/feature_flags.json

# Поиск устаревших экспериментов (старше 30 дней)
find . -name "feature_flags_*.json" -mtime +30
```

### Диагностика на устройстве

```bash
# iOS: просмотр кэшированных флагов в симуляторе
xcrun simctl spawn booted defaults read com.company.app feature_flags

# Android: просмотр SharedPreferences
adb shell "run-as com.company.app cat shared_prefs/feature_flags.xml"
```

### Аудит изменений

```bash
# История изменений feature_flags.json в Git
git log --oneline -- fastlane/feature_flags.json

# Diff последнего изменения
git diff HEAD~1 -- fastlane/feature_flags.json

# Поиск кто изменил конкретный флаг
git log -S "new_checkout_flow" --oneline -- fastlane/feature_flags.json
```

---

## Устранение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Stale flag value** | Приложение использует устаревшее значение из кэша. | Проверьте TTL кэша. Убедитесь, что `refresh()` вызывается при старте и по pull-to-refresh. |
| **Config fetch timeout** | CDN или Config Service недоступен. | Проверьте сетевой доступ с устройства. Убедитесь, что bootstrap file содержит безопасные дефолты. |
| **Flag conflict** | Два флага находятся в противоречивом состоянии. | Внедрите dependency matrix. Тестируйте комбинации флагов в pre-release. |
| **Memory leak (Android)** | `SharedPreferences` не очищается при удалении флага. | Добавьте миграцию `onUpgrade()` в `SharedPreferences`. |
| **Crash on missing flag** | Код ожидает наличие флага, но он отсутствует в конфиге. | Всегда используйте `fallbackValue`. Никогда не force-unwrap. |
| **Inconsistent rollout** | Разные сегменты пользователей видят разные значения. | Проверьте targeting rules в Admin Dashboard. Убедитесь, что clock drift между сервисами минимален. |
| **Feature flag sprawl** | В конфиге сотни устаревших флагов. | Настройте автоматический alert при отсутствии флага в коде > 14 дней. |
| **Cannot disable flag** | Флаг встроен в бизнес-логику и его отключение ломает flow. | Проектируйте флаги как opt-in паттерны с graceful degradation. |

---

## Рекомендации

### Best Practices

- **Version Pinning:** Фиксируйте схему конфига флагов. При изменении формата увеличивайте версию конфига и поддерживайте миграцию.
- **Least Privilege:** Доступ к Admin Dashboard только у Release Engineers и Product Owners. Изменения через PR с review.
- **Secrets Management:** Не храните секреты в конфиге флагов. Используйте CI-секреты и OS-provided secure storage (Keychain, Keystore).
- **Idempotency:** Переключение флага дважды даёт тот же результат. Избегайте side effects в evaluation logic.
- **Graceful Degradation:** Каждый флаг должен иметь безопасный fallback. Приложение должно работать корректно при отключении любого флага.
- **Flag Ownership:** Каждый флаг имеет владельца (команда или человек). При увольнении/ротации владельца — передача прав.
- **Cleanup:** Удаляйте флаги через 2-4 недели после полного rollout. Автоматизируйте detection of dead flags.

### Edge Cases и ограничения

1. **Оффлайн-режим:** При отсутствии сети приложение использует bootstrap file. Убедитесь, что дефолтные значения безопасны и не exposing неготовый функционал.
2. **Версии приложения:** Старые версии приложения не должны ломаться при добавлении новых флагов. Всегда задавайте `default_value` при чтении флага.
3. **Конфликты флагов:** Документируйте зависимости между флагами (флаг B работает только если флаг A включен). Используйте automated conflict detection.
4. **Производительность:** Feature flags не должны блокировать UI-поток. Используйте кэширование и асинхронную загрузку конфигурации.
5. **Приватность:** Не передавайте PII (идентификаторы пользователей, геолокацию) в feature flag service без шифрования и explicit consent.
6. **Clock Skew:** При использовании временных правил (например, показывать флаг только в рабочие часы) учитывайте drift на устройствах пользователей.
7. **A/B Test Duration:** Эксперименты должны иметь фиксированную длительность. Автоматически завершайте тесты по истечении срока, чтобы не оставлять флаги в подвешенном состоянии.

### Мониторинг и Observability

- **Логи:** Все изменения флагов (кто, когда, старое/новое значение) пишутся в audit log.
- **Метрики:** Экспортируйте evaluation rate, cache hit ratio, fallback usage в Prometheus или внутренний сборщик метрик.
- **Алерты:** Настройте оповещения при:
  - Crash rate delta > 0.1% после включения флага
  - Config fetch failure rate > 1%
  - Stale flag age > 24 часа
- **Runbook'и:** Для каждого типичного сбоя (падение Config Service, stale flags, конфликтующие флаги) должно быть пошаговое руководство.

### Безопасность

- **Transport Security:** Все запросы к Config Service должны идти по TLS с проверкой сертификата. Никогда не используйте HTTP для production.
- **Input Validation:** Валидируйте входящий JSON на стороне приложения. Ожидайте атаки на Config Service.
- **Access Control:** Config Service API требует аутентификации. Используйте short-lived токены или mTLS.
- **Rollback Safety:** Каждое изменение флага должно быть откатываемо в течение секунд. Храните историю значений минимум 30 дней.

---

## Дополнительная информация

- **[Обзор Mobile CI/CD и инфраструктуры](./index.md)** — архитектура macOS-раннеров, Golden Image, SRE-подход к пайплайнам.
- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout, Canary Releases.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — Kill Switch как средство mitigation, hotfix workflow, runbook.
