# App Size и Bundle Optimization

## Определения

**App Size** — общий размер артефакта мобильного приложения (IPA, AAB, APK) и его влияния на процесс доставки, хранилище артефактов и конечный опыт пользователя.

**Bundle Optimization** — комплекс методов уменьшения размера приложения: obfuscation, resource shrinking, asset compression, dead code elimination, modularization.

**App Thinning** — технология Apple, доставляющая пользователям только те части приложения, которые необходимы для конкретного устройства. Включает App Slicing, Bitcode и On-Demand Resources.

**App Slicing** — автоматическая генерация вариантов IPA под конкретные устройства (architecture, screen density, resolution). App Store отдает только подходящий вариант.

**Bitcode** — промежуточное представление бинарника, которое Apple перекомпилирует под конкретное устройство при загрузке. Позволяет оптимизировать бинарник без нового релиза.

**On-Demand Resources (ODR)** — ресурсы приложения, загружаемые по требованию после установки основного бинарника. Используются для уровней игры, дополнительных фильтров, редких функций.

**Dynamic Delivery (Android)** — технология Google Play, доставляющая функциональность по требованию. Включает Dynamic Feature Modules и Asset Packs.

**Dynamic Feature Module** — модуль Android-приложения, который не входит в базовую установку, а загружается по требованию.

**Asset Pack** — ресурсы (изображения, видео, шрифты), загружаемые отдельно от APK/AAB.

**Resource Shrinking** — автоматическое удаление неиспользуемых ресурсов из APK/AAB.

**Code Shrinking (R8 / ProGuard)** — удаление неиспользуемого кода и obfuscation в Android-сборках. R8 является стандартным компилятором с Android Gradle Plugin 3.4+.

**Dead Code Elimination (DCE)** — удаление кода, который никогда не вызывается во время выполнения. В iOS реализуется через Link-Time Optimization (LTO).

**dSYM** — файл символов отладки для iOS, генерируемый Xcode при сборке. Содержит соответствие машинного адреса исходному коду. Критичен для symbolication crash-репортов.

**ProGuard Mapping** — текстовый файл, генерируемый ProGuard/R8 при обфускации Android-приложения. Содержит соответствие обфусцированных имен исходным классам, методам и строкам.

**Symbol Stripping** — удаление символов отладки из финального бинарника. Уменьшает размер и затрудняет reverse engineering.

**Artifact** — финальный продукт CI/CD пайплайна: IPA, AAB, APK, сопровождаемый dSYM/ProGuard mapping.

**Artifact Storage** — хранилище артефактов CI/CD. На macOS-раннерах управляется через `launchd`-сервисы или cron-задачи очистки. В GitLab CI — через настроенные `artifacts:expire_in`.

**Build Cache** — кэш зависимостей и промежуточных артефактов сборки. Ускоряет пересборки, но требует регулярной очистки из-за роста размера. На macOS-раннерах: `~/Library/Caches/org.swift.swiftpm`, `~/Library/Developer/Xcode/DerivedData`.

**Size Regression** — неконтролируемый рост размера артефакта между версиями. Обнаруживается через сравнение метрик Download Size / Install Size / Binary Size.

**Size Budget** — заранее согласованное максимальное значение размера артефакта. При превышении — срабатывает quality gate, блокирующий деплой.

**Download Size** — размер, который пользователь скачивает. Может отличаться от Install Size из-за App Thinning.

**Install Size** — размер приложения на устройстве после установки и распаковки.

**Binary Size** — размер машинного кода IPA/AAB без ресурсов.

**Resource Size** — размер ресурсов (изображения, шрифты, localized strings).

**App Size Limit** — ограничение размера приложения в магазинах. App Store: 200 MB OTA (over-the-air), 4 GB через iTunes Connect. Google Play: 200 MB для AAB.

**Ephemeral Runner (эфемерный раннер)** — исполнитель CI/CD, создаваемый под конкретную задачу и уничтожаемый после выполнения. Исключает накопление состояния и рост размера кэша между джобами.

**Golden Image (золотой образ)** — предварительно настроенный шаблон macOS, содержащий стандартный набор инструментов (Xcode, JDK, Ruby, Fastlane, симуляторы). Обеспечивает идемпотентность развертывания и исключает «дрейф» конфигурации между раннерами.

**Toil (рутинный труд)** — ручная, повторяющаяся, масштабирующаяся работа, не дающая долгосрочной ценности. В контексте App Size: ручной анализ размеров, ручная отправка отчетов, ручная чистка артефактов.

**Error Budget (бюджет ошибок)** — допустимый объём сбоев, связывающий надёжность и скорость поставки. Для App Size применяется к допустимому проценту регрессий размера и времени реакции на превышение Size Budget.

**SLO (Service Level Objective) для размера** — целевое значение размера артефакта, установленное командой. Например: Download Size < 150 MB, рост между версиями < 5%.

---

## Базовые концепции

### Архитектура пайплайна и размер артефакта

Типовой пайплайн Mobile CI/CD, связанный с размером приложения, включает следующие этапы:

1. **Prepare:** Установка зависимостей, синхронизация кэша. Размер DerivedData и кэша Gradle/SwiftPM напрямую влияет на диск раннера.
2. **Build for Testing:** Сборка без оптимизаций для unit-тестов. Размер артефакта может отличаться от релизного.
3. **Build & Optimize:** Релизная сборка с включенным shrinking, obfuscation, LTO. На этом этапе фиксируются базовые метрики размера.
4. **Sign & Archive:** Подпись артефакта и генерация dSYM/ProGuard mapping. Файлы символов добавляют к общему footprint артефакта.
5. **Size Analysis:** Измерение Binary Size, Resource Size, Download Size, Install Size. Генерация отчета.
6. **Size Gate:** Сравнение с Size Budget. При превышении — пайплайн блокируется.
7. **Artifact Upload:** Загрузка артефакта и символов в хранилище CI/CD.
8. **Distribute:** Загрузка в TestFlight / Google Play. Магазин применяет App Thinning / Dynamic Delivery перед доставкой пользователю.

**Важно для SRE:** Размер артефакта влияет не только на пользовательский опыт, но и на инфраструктуру:
- **Сеть:** Большие артефакты увеличивают время загрузки в хранилище и между раннерами.
- **Диск:** На macOS-раннерах DerivedData, `~/.gradle/caches`, `~/Library/Caches/org.swift.swiftpm` могут занимать 20–80 GB. Без регулярной очистки раннер перестает умещаться на NVMe SSD.
- **CPU/RAM:** Оптимизирующие сборки (LTO, R8 full mode) потребляют больше CPU и памяти. На Apple Silicon M4 это менее критично, но на Intel-раннерах может стать bottleneck.

### iOS: App Thinning

**Компоненты:**

| Компонент | Описание | Эффект |
|:---|:---|:---|
| **App Slicing** | Разные архитектуры и densities в одном IPA | Сокращает download size на 30–50% |
| **Bitcode** | Перекомпиляция Apple под конкретное устройство | Уменьшает binary size на 20–30% |
| **On-Demand Resources** | Ресурсы по требованию | Сокращает initial download на 50%+ |

**App Slicing:**
- iPhone 15 Pro Max: arm64, @3x изображения
- iPhone SE: arm64, @2x изображения
- App Store автоматически подбирает подходящий slice

**Bitcode:**
- Включение: `ENABLE_BITCODE = YES`
- Apple перекомпилирует при загрузке в App Store
- Локально dSYM может отличаться от production
- Включает `BITCODE_GENERATION_MODE = bitcode` в Xcode build settings

**On-Demand Resources:**
- Tags для группировки ресурсов
- Запрос через `NSBundleResourceRequest`
- Автоматическая очистка при нехватке места

### Android: Dynamic Delivery

**Компоненты:**

| Компонент | Описание | Эффект |
|:---|:---|:---|
| **Dynamic Feature Modules** | Модули, загружаемые по требованию | Сокращает initial install size |
| **Asset Packs** | Ресурсы (изображения, видео) | Загружаются отдельно от APK |
| **Resource Shrinking** | Удаление неиспользуемых ресурсов | Сокращает size на 20–40% |
| **Code Shrinking (R8)** | Удаление unused кода | Сокращает binary size на 30–50% |

**Dynamic Feature Modules:**
```gradle
// build.gradle.kts
android {
    dynamicFeatures = [":feature_checkout", ":feature_profile"]
}
```

**Asset Packs:**
```gradle
// build.gradle.kts
android {
    assetPacks = [":asset_pack_images"]
}
```

### Bundle Optimization Techniques

**1. Code Shrinking (Obfuscation):**
- **iOS:** `DEAD_CODE_STRIPPING = YES`, `STRIP_INSTALLED_PRODUCT = YES`
- **Android:** ProGuard/R8 с `minifyEnabled true`

**2. Resource Shrinking:**
- **iOS:** Compress PNG/JPEG, удаление неиспользуемых изображений
- **Android:** `shrinkResources true`, `resConfigs` для ограничения локалей

**3. Asset Compression:**
- **iOS:** Xcode автоматически сжимает PNG
- **Android:** WebP/AVIF вместо PNG/JPEG, сжатие шрифтов

**4. Dead Code Elimination:**
- **iOS:** Link-time optimization (LTO)
- **Android:** R8 full mode

**5. Library Optimization:**
- Удаление неиспользуемых фреймворков
- Замена тяжелых библиотек на lightweight аналоги
- Modularization для Android

**6. Symbol Stripping:**
- **iOS:** `STRIP_INSTALLED_PRODUCT = YES`, `STRIP_FLAGS = ["-x"]`
- **Android:** ProGuard/R8 с `dontobfuscate` для debug и `optimizationpasses 5` для release

### Size Monitoring в CI

**Метрики:**
- **Download Size:** размер, скачиваемый пользователем
- **Install Size:** размер на устройстве после установки
- **Binary Size:** размер IPA/AAB
- **Resource Size:** размер ресурсов (изображения, шрифты)
- **Code Size:** размер машинного кода
- **dSYM/ProGuard Mapping Size:** размер файлов символов отладки

**Пороговые значения:**
- iOS: download size < 150 MB (OTA)
- Android: AAB size < 150 MB
- Install size: < 200 MB
- dSYM/ProGuard mapping: < 100 MB

### SRE-подход к App Size

- **Error Budget для size:** Договоритесь о максимальном размере приложения. При превышении — фокус на оптимизацию.
- **MTTR (Size):** Среднее время от обнаружения роста размера до фикса. Цель: < 1 дня.
- **Toil Reduction:** Автоматизируйте мониторинг размера, алерты, отчеты. Измеряйте долю ручной работы.
- **Observability:** Каждый релиз должен иметь size report: binary, resources, assets, libraries, symbols.

### Sysadmin: управление ресурсами CI-инфраструктуры

**Дисковое пространство на macOS-раннерах:**

macOS-раннеры требуют регулярного управления дисковым пространством. Без proactive-очистки DerivedData и кэши могут заполнить NVMe SSD, что приведет к отказу сборок.

**Ключевые директории:**
- `~/Library/Developer/Xcode/DerivedData/` — кэш сборок Xcode (20–50 GB)
- `~/Library/Caches/org.swift.swiftpm/` — кэш Swift Package Manager (5–20 GB)
- `~/.gradle/caches/` — кэш Gradle для Android (10–30 GB)
- `~/Library/Caches/CocoaPods/` — кэш CocoaPods (2–10 GB)

**Очистка через launchd:**
```xml
<!-- /Library/LaunchDaemons/com.ci.cleanup.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ci.cleanup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>find ~/Library/Developer/Xcode/DerivedData -type f -atime +7 -delete 2>/dev/null; find ~/.gradle/caches -type f -atime +7 -delete 2>/dev/null; exit 0</string>
    </array>
    <key>StartInterval</key>
    <integer>86400</integer>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

```bash
# Загрузка launchd сервиса
sudo launchctl load /Library/LaunchDaemons/com.ci.cleanup.plist
# → Service loaded successfully
```

**Мониторинг диска:**
```bash
# Проверка свободного места
df -h /
# → Filesystem      Size  Used  Avail Capacity  Mounted on
# → /dev/disk1s1   466G  320G   146G    69%    /

# Проверка размера DerivedData
du -sh ~/Library/Developer/Xcode/DerivedData/
# → 32G

# Проверка размера кэша Gradle
du -sh ~/.gradle/caches/
# → 18G
```

**Артефакт-хранилище в GitLab CI:**
```yaml
# .gitlab-ci.yml
artifacts:
  paths:
    - build/ipa/MyApp.ipa
    - build/dSYMs/
  expire_in: 1 week
  reports:
    dotenv: build.env
```

**GitLab CI: артефакты:**
```yaml
# .gitlab-ci.yml
build_ios:
  stage: build
  artifacts:
    paths:
      - build/*.ipa
    expire_in: 1 week
```

**Управление кэшем GitLab CI:**
```yaml
# .gitlab-ci.yml
build_ios:
  cache:
    key: gradle-$CI_COMMIT_REF_SLUG
    paths:
      - .gradle/caches/
    policy: pull-push

  cache:
    key: swiftpm-$CI_COMMIT_REF_SLUG
    paths:
      - .build/
    policy: pull-push
```

**Сетевые ресурсы:**
- Большие артефакты (IPA 100+ MB) увеличивают время загрузки в artifact storage.
- На dedicated-раннерах с NVMe SSD и 1 GbE сетью время загрузки 150 MB артефакта: ~10–15 секунд.
- На shared-пулах с более медленной сетью: до 60 секунд.
- При параллельных джобах на одном раннере сеть может становиться bottleneck.

---

## Практические сценарии

### 1. iOS: App Thinning Configuration

**Включение App Thinning в Xcode:**
```bash
# Проверка настроек
xcodebuild -project MyApp.xcodeproj \
  -scheme MyApp \
  -showBuildSettings \
  | grep -E "BITCODE|STRIP|DEAD_CODE"
# → ENABLE_BITCODE = YES
# → DEAD_CODE_STRIPPING = YES
# → STRIP_INSTALLED_PRODUCT = YES
```

**Включение On-Demand Resources:**
```xml
<!-- Info.plist -->
<key>OnDemandResourcesEnabled</key>
<true/>
```

**Fastlane: ODR Tags:**
```ruby
lane :build_with_odr do
  build_app(
    scheme: "MyApp",
    export_method: "app-store",
    export_options: {
      onDemandResourcesEnabled: true,
      onDemandResourcesTags: ["level1", "level2", "assets"]
    }
  )
end
```

**Использование ODR в коде:**
```swift
let request = NSBundleResourceRequest(tags: ["level1"])
request.beginAccessingResources { error in
  if let error = error {
    print("Failed to load ODR: \(error)")
    return
  }
  
  // Ресурсы доступны
  let level = Bundle.main.path(forResource: "level1", ofType: "plist")
}
```

### 2. Android: Dynamic Feature Modules

**Создание dynamic feature модуля:**
```gradle
// settings.gradle.kts
include(":app")
include(":feature_checkout")
include(":feature_profile")
```

**Module build.gradle.kts:**
```kotlin
android {
    namespace = "com.company.app.feature_checkout"
    compileSdk = 34
    
    defaultConfig {
        minSdk = 21
    }
    
    buildFeatures {
        viewBinding = true
    }
}
```

**Базовый модуль:**
```gradle
// app/build.gradle.kts
android {
    dynamicFeatures = [":feature_checkout", ":feature_profile"]
}
```

**Загрузка dynamic feature:**
```kotlin
// MainActivity.kt
val splitInstallManager = SplitInstallManagerFactory.create(context)
val request = SplitInstallRequest.newBuilder()
    .addModule("feature_checkout")
    .build()

splitInstallManager.startInstall(request)
    .addOnSuccessListener {
        // Module installed
        val intent = Intent(context, CheckoutActivity::class.java)
        startActivity(intent)
    }
    .addOnFailureListener { exception ->
        // Handle failure
        Log.e("DynamicFeature", "Install failed", exception)
    }
```

### 3. Android: Resource Shrinking

**Включение resource shrinking:**
```gradle
android {
    buildTypes {
        release {
            shrinkResources true
            minifyEnabled true
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'),
                          'proguard-rules.pro'
            
            // Ограничение локалей
            resConfigs "en", "ru"
        }
    }
}
```

**Проверка unused resources:**
```bash
# Генерация отчета об unused ресурсах
./gradlew :app:release -Pandroid.debug.obsoleteApi=true

# Анализ APK
./gradlew :app:analyzeReleaseBundle
# → Android Studio: Analyze APK
```

### 4. Asset Compression

**iOS: Оптимизация изображений:**
```bash
# Сжатие PNG через ImageOptim
imageoptim ./assets/

# Конвертация в WebP (требует инструменты)
cwebp -q 80 input.png -o output.webp

# Проверка размера
du -sh ./assets/*.png ./assets/*.webp
```

**Android: WebP конвертация:**
```bash
# Конвертация PNG → WebP
cwebp -q 80 input.png -o output.webp

# Включение WebP в build.gradle
android {
    aaptOptions {
        noCompress "webp"
    }
}
```

### 5. Size Monitoring в CI

**iOS: Проверка размера IPA:**
```bash
# Размер IPA
IPA_SIZE=$(du -h ./build/MyApp.ipa | cut -f1)
echo "IPA size: $IPA_SIZE"

# Проверка лимита
MAX_SIZE=150000000  # 150 MB в байтах
IPA_SIZE_BYTES=$(stat -f%z ./build/MyApp.ipa)

if [ "$IPA_SIZE_BYTES" -gt "$MAX_SIZE" ]; then
  echo "ERROR: IPA size exceeds limit (150 MB)"
  exit 1
fi
```

**Android: Проверка размера AAB:**
```bash
# Размер AAB
AAB_SIZE=$(stat -f%z app/build/outputs/bundle/release/app-release.aab)
echo "AAB size: $((AAB_SIZE / 1024 / 1024)) MB"

# Проверка лимита
MAX_SIZE=150000000  # 150 MB
if [ "$AAB_SIZE" -gt "$MAX_SIZE" ]; then
  echo "ERROR: AAB size exceeds limit (150 MB)"
  exit 1
fi
```

**GitLab CI: пайплайн:**
```yaml
# .gitlab-ci.yml
build_ios:
  stage: build
  script:
    - ./build.sh
  artifacts:
    paths:
      - build/MyApp.ipa
    expire_in: 1 week
```

**GitLab CI: Size Gate:**
```yaml
# .gitlab-ci.yml
size_check:
  stage: test
  script:
    - |
      IPA_SIZE=$(stat -f%z build/MyApp.ipa)
      MAX_SIZE=150000000
      if [ "$IPA_SIZE" -gt "$MAX_SIZE" ]; then
        echo "ERROR: IPA size exceeds limit"
        exit 1
      fi
      echo "IPA size: $((IPA_SIZE / 1024 / 1024)) MB"
  only:
    - merge_requests
```

### 6. Size Analysis Tools

**iOS: App Size Report**
```bash
# Генерация отчета о размере
xcrun size ./build/MyApp.xcarchive/Products/Applications/MyApp.app \
  --sections __TEXT __DATA __LINKEDIT \
  --csv > size-report.csv

# Анализ через Xcode Organizer
# Window → Organizer → Archives → Distribute → App Store
```

**Android: APK Analyzer**
```bash
# CLI анализ AAB
bundletool analyze-bundle \
  --bundle app/build/outputs/bundle/release/app-release.aab \
  --output-dir ./analyze-output

# Или через Android Studio: Build → Analyze APK
```

### 7. Optimization Techniques

**iOS: Оптимизация бинарника:**
```bash
# Включение LTO (Link-Time Optimization)
xcodebuild archive \
  -workspace MyApp.xcworkspace \
  -scheme MyApp \
  -archivePath ./build/MyApp.xcarchive \
  SWIFT_OPTIMIZATION_LEVEL=-Owholemodule \
  LLVM_LTO=thin
```

**Android: R8 Optimization:**
```groovy
// build.gradle.kts
android {
    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile('proguard-android-optimize.txt'),
                'proguard-rules.pro'
            )
            
            // R8 full mode
            androidResources.ignoreAssetsPattern = ""
        }
    }
}
```

**Удаление неиспользуемых ресурсов:**
```bash
# iOS: Поиск неиспользуемых изображений
find ./assets -name "*.png" -exec basename {} \; | sort > all-images.txt
grep -r "imageName" ./Sources | sed 's/.*"\(.*\)".*/\1/' | sort > used-images.txt
comm -23 all-images.txt used-images.txt
# → Неиспользуемые изображения
```

### 8. dSYM и ProGuard Mapping: размер и управление

**dSYM size impact:**
```bash
# Проверка размера dSYM
DSYM_SIZE=$(du -sh ./build/MyApp.xcarchive/dSYMs/MyApp.app.dSYM | cut -f1)
echo "dSYM size: $DSYM_SIZE"

# dSYM может составлять 50–200 MB для больших приложений
# Убедитесь, что dSYM загружается в App Store Connect / TestFlight
```

**ProGuard mapping size impact:**
```bash
# Проверка размера mapping
MAPPING_SIZE=$(du -h app/build/outputs/mapping/release/mapping.txt | cut -f1)
echo "ProGuard mapping size: $MAPPING_SIZE"
# → mapping.txt  12M

# mapping.txt критичен для deobfuscation crash-репортов.
# Храните mapping в secure artifact storage с retention >= 1 year.
```

**Управление символами в CI:**
```yaml
# GitLab CI: загрузка dSYM
upload_dsym:
  stage: deploy
  artifacts:
    paths:
      - build/MyApp.xcarchive/dSYMs/
    expire_in: 52 weeks

# GitLab CI: загрузка mapping
upload_mapping:
  stage: deploy
  artifacts:
    paths:
      - app/build/outputs/mapping/release/mapping.txt
    expire_in: 52 weeks
```

### 9. Build Cache Management на macOS-раннерах

**Swift Package Manager cache:**
```bash
# Проверка размера кэша
du -sh .build/
# → .build  15G

# Очистка кэша (в CI после каждой сборки)
rm -rf .build/
```

**Gradle cache management:**
```bash
# Проверка размера кэша
du -sh ~/.gradle/caches/
# → ~/.gradle/caches  22G

# Очистка старых кэшей
find ~/.gradle/caches -type f -atime +7 -delete
```

**Xcode DerivedData cleanup:**
```bash
# Проверка размера DerivedData
du -sh ~/Library/Developer/Xcode/DerivedData/
# → DerivedData  45G

# Очистка через xcrun
xcrun simctl erase all
rm -rf ~/Library/Developer/Xcode/DerivedData/*

# Или через fastlane
fastlane run clear_derived_data
```

**Fastlane lane с cleanup:**
```ruby
lane :build_and_cleanup do
  build_app(scheme: "MyApp")
  
  # Очистка после сборки
  sh "rm -rf ~/Library/Developer/Xcode/DerivedData/*"
  sh "rm -rf .build/"
  
  # Проверка размера
  size = File.size("./build/MyApp.ipa")
  UI.user_error!("IPA too large") if size > 150_000_000
end
```

### 10. Artifact Retention Policy

**GitLab CI:**
```yaml
# .gitlab-ci.yml
default:
  artifacts:
    paths:
      - build/ipa/
      - build/dSYMs/
    expire_in: 1 week
  except:
    - tags

# Для релизных тегов — дольше
release:
  artifacts:
    paths:
      - build/ipa/MyApp.ipa
      - build/dSYMs/
    expire_in: 52 weeks
  only:
    - tags
```

**GitLab CI:**
```yaml
# .gitlab-ci.yml
build:
  stage: build
  script:
    - ./build.sh
  artifacts:
    paths:
      - build/ipa/
      - build/dSYMs/
    expire_in: 1 week
  except:
    - tags

release:
  stage: deploy
  script:
    - ./build.sh
  artifacts:
    paths:
      - build/ipa/MyApp.ipa
      - build/dSYMs/
    expire_in: 52 weeks
  only:
    - tags
```

---

## Операции и команды

### Size Measurement

```bash
# iOS: IPA size
du -h ./build/MyApp.ipa
# → 45M

# iOS: Разбор IPA
unzip -l ./build/MyApp.ipa | grep -E "Payload|App"
# → Payload/MyApp.app (45M)

# Android: AAB size
du -h app/build/outputs/bundle/release/app-release.aab
# → 42M

# Android: APK size
du -h app/build/outputs/apk/release/app-release.apk
# → 38M
```

### dSYM / Mapping Management

```bash
# iOS: dSYM size
du -sh ./build/MyApp.xcarchive/dSYMs/MyApp.app.dSYM
# → 85M

# iOS: Проверка что dSYM содержит UUID
dwarfdump --uuid ./build/MyApp.xcarchive/dSYMs/MyApp.app.dSYM
# → UUID: 12345678-1234-1234-1234-123456789012 (arm64)

# Android: ProGuard mapping size
du -sh app/build/outputs/mapping/release/mapping.txt
# → 12M
```

### Resource Analysis

```bash
# iOS: Размер ресурсов
find ./MyApp.app -name "*.png" -exec du -h {} \; | sort -rh | head -20

# Android: Размер ресурсов в APK
aapt2 dump resources app/build/outputs/apk/release/app-release.apk \
  | grep -E "type=.*png|type=.*webp" | head -20
```

### Cache Management

```bash
# Очистка DerivedData
rm -rf ~/Library/Developer/Xcode/DerivedData/*

# Очистка SwiftPM кэша
rm -rf .build/

# Очистка Gradle кэша
find ~/.gradle/caches -type f -atime +7 -delete

# Проверка свободного места на macOS
df -h /
# → Filesystem      Size  Used  Avail Capacity  Mounted on
# → /dev/disk1s1   466G  320G   146G    69%    /
```

### Compression

```bash
# iOS: Сжатие PNG
find ./assets -name "*.png" -exec pngquant --ext .png --force 256 {} \;

# Android: Конвертация в WebP
find ./assets -name "*.png" -exec cwebp -q 80 {} -o {}.webp \;

# Удаление исходных PNG после конвертации
find ./assets -name "*.png" -delete
```

---

## Устранение проблем

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **IPA exceeds 150 MB** | Слишком много ресурсов, не включен App Thinning | Включите App Thinning, сожмите ресурсы, удалите неиспользуемые ассеты |
| **AAB exceeds 150 MB** | Слишком много ресурсов, не включен shrinking | Включите `shrinkResources`, используйте Dynamic Delivery |
| **Download size too large** | Нет App Slicing/Dynamic Delivery, неоптимизированные ресурсы | Включите App Thinning, используйте WebP/AVIF, сжимайте изображения |
| **Install size too large** | Fat binary, неиспользуемые ресурсы | Используйте Bitcode, удалите unsupported architectures |
| **Bitcode increases size** | Bitcode добавляет ~20% к размеру IPA | Отключите Bitcode если не нужен App Store optimization |
| **ODR not working** | Неправильные tags, ресурсы не помечены | Проверьте tags в Xcode, убедитесь что ODR включен |
| **Dynamic feature not loading** | Ошибка в module configuration | Проверьте `dynamicFeatures` в build.gradle, убедитесь что module скачан |
| **Resource shrinking broke layout** | Удалены ресурсы, используемые через reflection | Добавьте `tools:keep` для этих ресурсов |
| **ProGuard broke functionality** | Удалены классы, используемые через reflection | Добавьте keep rules в `proguard-rules.pro` |
| **App Store rejected (size)** | Превышен лимит 200 MB OTA | Оптимизируйте ресурсы, используйте On-Demand Resources |
| **No space left on runner** | DerivedData / кэши заполнили диск | Настройте launchd cleanup, увеличьте SSD, добавьте alert на свободное место |
| **dSYM missing for crash reporting** | dSYM не загружен в App Store Connect | Проверьте upload-symbols fastlane action, настройте retention artifacts |
| **ProGuard mapping lost** | mapping.txt не сохранен в artifact storage | Добавьте mapping в artifacts с expire_in >= 52 weeks |
| **Build cache corruption** | Поврежденный кэш Gradle/SwiftPM | Удалите кэш, пересоберите с `--no-cache` |
| **Size regression undetected** | Нет size gate в CI | Добавьте size check в пайплайн, настройте alerting |

---

## Рекомендации

### Best Practices

- **App Thinning:** Включайте App Thinning для всех iOS-релизов. Это сокращает download size на 30–50%.
- **Dynamic Delivery:** Используйте Dynamic Feature Modules для Android. Разделяйте приложение на core и optional features.
- **Resource Optimization:** Сжимайте изображения (WebP/AVIF), удаляйте неиспользуемые ресурсы, используйте vector drawables.
- **Code Shrinking:** Включайте ProGuard/R8 для Android. Используйте `DEAD_CODE_STRIPPING` для iOS.
- **Size Monitoring:** Добавьте size check в CI. Блокируйте merge при превышении лимита.
- **Trend Analysis:** Отслеживайте рост размера версия за версией. Резкий рост = red flag.
- **Toil Reduction:** Автоматизируйте анализ размера, алерты, отчеты. Измеряйте долю ручной работы.
- **Error Budget:** Установите лимит размера. При превышении — freeze на новые фичи до оптимизации.
- **Artifact Retention:** Храните IPA/AAB и dSYM/mapping минимум 1 год для поддержки crash reporting.
- **Cache Hygiene:** Очищайте DerivedData и кэши сборки на раннерах. Настройте launchd/cron для автоматической очистки.
- **Disk Monitoring:** Устанавливайте alert при заполнении диска > 80%. Диск на macOS-раннере — частый причина отказов сборок.
- **Size Budget Governance:** Установите Size SLO. При превышении — создавайте epic на оптимизацию, а не hotfix.

### SRE-подход к App Size

- **Error Budget для размера:** Договоритесь с командой о максимальном размере приложения (например, 150 MB Download Size). При превышении бюджета в 5% релизов за месяц — freeze на новые фичи до оптимизации.
- **MTTR (Size):** Среднее время от обнаружения роста размера до фикса. Цель: < 1 дня.
- **Toil Reduction:** Автоматизируйте мониторинг размера, алерты, отчеты. Измеряйте долю ручной работы.
- **Observability:** Каждый релиз должен иметь size report: binary, resources, assets, libraries, symbols.
- **Runbook:** Создайте runbook для типичных scenarios: "IPA exceeds 150 MB", "dSYM missing", "Build cache corruption".
- **Capacity Planning:** Планируйте размер SSD на macOS-раннерах с учетом DerivedData и кэшей (минимум 512 GB NVMe для production-пула).

### Edge Cases и ограничения

1. **Bitcode и dSYM:** При включенном Bitcode dSYM может отличаться от локальной сборки. Загружайте dSYM из App Store Connect.
2. **ODR и offline mode:** ODR требует сети для загрузки ресурсов. Обеспечьте fallback для offline usage.
3. **Dynamic Features и configuration changes:** При повороте экрана dynamic feature может быть перезагружен. Обрабатывайте state restoration.
4. **WebP support:** Не все версии Android поддерживают WebP. Используйте Android 4.2+ или fallback.
5. **App Slicing и Testing:** Simulator не получает sliced IPA. Тестируйте на реальных устройствах.
6. **Asset Pack size:** Asset Packs должны быть < 100 MB каждая. Большие assets разбивайте на chunks.
7. **Resource shrinking и reflection:** Ресурсы, используемые через reflection, могут быть удалены. Добавьте keep rules.
8. **Size limits evolution:** Лимиты магазинов меняются. Мониторьте актуальные лимиты App Store и Google Play.
9. **Build cache invalidation:** При изменении зависимостей кэш Gradle/SwiftPM может стать невалидным. Используйте cache keys на основе lock-файлов.
10. **dSYM retention:** dSYM файлы требуются для symbolication crash-репортов. Храните их минимум 1 год.
11. **Symbol stripping и crash reporting:** Полное удаление символов облегчает reverse engineering, но усложняет debugging. Найдите баланс.
12. **Ephemeral runners и disk:** Эфемерные раннеры создаются и удаляются заново. Убедитесь, что образ (Golden Image) не переполняет диск при сборке.

---

## Мониторинг и Observability

**Ключевые метрики:**
- **Download Size:** размер скачивания (цель: < 150 MB)
- **Install Size:** размер на устройстве (цель: < 200 MB)
- **Binary Size:** размер IPA/AAB
- **Resource Size:** размер ресурсов
- **dSYM/ProGuard Mapping Size:** размер файлов символов
- **Size Growth Rate:** темп роста размера между версиями (цель: < 5% per release)
- **Build Cache Size:** размер кэша на раннере (алерт при > 50 GB)
- **Runner Disk Usage:** использование диска на macOS-раннере (алерт при > 80%)

**Alert Rules:**
```yaml
groups:
  - name: app_size_alerts
    rules:
      - alert: AppSizeTooLarge
        expr: app_download_size_bytes > 150000000
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "App download size exceeds 150 MB"
      
      - alert: AppSizeGrowthTooFast
        expr: rate(app_size_bytes[7d]) > 0.05
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "App size growing too fast"
      
      - alert: ResourceSizeTooLarge
        expr: app_resource_size_bytes > 50000000
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Resource size exceeds 50 MB"

      - alert: RunnerDiskFull
        expr: node_filesystem_avail_bytes{mountpoint="/"} < 50000000000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Runner disk space is low"
      
      - alert: BuildCacheTooLarge
        expr: node_filesystem_size_bytes{mountpoint="/"} - node_filesystem_free_bytes{mountpoint="/"} > 0.8 * node_filesystem_size_bytes{mountpoint="/"}
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Build cache is consuming too much disk"
```

**Quality Gates:**
- Download size < 150 MB перед публикацией
- Size growth rate < 5% между версиями
- Все ресурсы сжаты и оптимизированы
- Неиспользуемые ресурсы удалены
- dSYM / ProGuard mapping загружены в artifact storage
- Свободное место на раннере > 50 GB

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout.
- **[Security Scanning в Mobile CI/CD](./security-scanning-mobile.md)** — obfuscation, ProGuard, symbol stripping.
- **[Crash Reporting и Symbolication](./crash-reporting-mobile.md)** — dSYM/ProGuard mapping, Sentry integration, crash-free rate.
- **[Fastlane: Автоматизация Mobile CI/CD](./fastlane-guide.md)** — lanes, plugins, интеграция с App Store/Play Console.
