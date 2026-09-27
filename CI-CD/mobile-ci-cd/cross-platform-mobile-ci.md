# Cross-Platform Mobile CI/CD

**Актуально для:** Flutter 3.27.x, React Native 0.87.x, GitLab CI/CD 2024–2026

---

## Определения

**Cross-Platform Mobile Development** — разработка мобильных приложений для iOS и Android из единой кодовой базы, исключающей необходимость поддерживать два отдельных проекта.

**Flutter** — фреймворк от Google на Dart для кроссплатформенной разработки. Компилируется в нативный код (AOT) для iOS и Android.

**React Native** — фреймворк от Meta на JavaScript/TypeScript. Использует нативные мосты для рендеринга UI и JavaScript-движок для выполнения логики.

**Dart SDK** — инструментарий для Flutter: компилятор (`dart`), менеджер пакетов (`pub`), статический анализатор (`dart analyze`), тестовый раннер (`dart test`).

**pub** — менеджер пакетов для Dart/Flutter. Работает с `pubspec.yaml` (декларативный) и `pubspec.lock` (фиксированные версии).

**Metro** — bundler для React Native. Транслирует JS/TS-код, обрабатывает зависимости и готовит бандл для устройства/симулятора.

**Hermes** — JavaScript-движок, оптимизированный для React Native. Уменьшает время старта приложения и потребление памяти по сравнению с JSC.

**CocoaPods integration** — Flutter генерирует iOS-проект с `Podfile`, управляемым через CocoaPods для нативных зависимостей.

**MTTR (Build)** — среднее время восстановления после сбоя сборки в CI. В mobile-контексте включает время диагностики, перезапуска на эфемерном раннере и повторного прохождения этапов.

---

## Базовые концепции

### Архитектура сборки

**Flutter:**
```
Dart-код → (AOT/JIT компиляция) → нативный ARM/x86 бинарный код
         → Skia/Impeller рендеринг → нативные виджеты iOS/Android
```
Команда сборки: `flutter build ios` / `flutter build apk` / `flutter build appbundle`.

**React Native:**
```
JS/TS-код → Metro bundler → Hermes/JSC байт-код
         → Нативные мосты → UIView (iOS) / View (Android)
```
Команда сборки: `npx react-native build-ios` / `cd android && ./gradlew assembleRelease`.

### Ограничения кросс-платформенного CI

Ключевое отличие от backend/web-пайплайнов — различие инфраструктуры для iOS и Android:

- **iOS-сборки требуют macOS-раннеры.** Docker-контейнеры для iOS не поддерживаются. Используйте Apple Silicon (M2/M3/M4) с предустановленным Xcode и симуляторами. См. также [Runner Management для Mobile CI/CD](./runner-management-mobile.md) — Tart/Orka, эфемерные ВМ, disk cleanup.
- **Android-сборки могут выполняться в Linux-контейнерах.** Это дешевле и масштабируется быстрее. Для headless-эмуляторов требуется KVM.
- **Очереди и стоимость:** Для кросс-платформенных проектов необходим пул macOS-раннеров (дорогие, низкая плотность) и пул Linux-раннеров (дешевые, высокая плотность). Планируйте capacity с запасом 30–50% для iOS-очереди.

### Файлы блокировок зависимостей

| Фреймворк | Lock-файл | Сторонние lock-файлы |
|-----------|-----------|---------------------|
| Flutter | `pubspec.lock` | `Podfile.lock` (iOS), `Package.resolved` (Xcode) |
| React Native | `package-lock.json` / `yarn.lock` | `Podfile.lock` (iOS) |

**Важно:** В CI всегда коммитить lock-файлы. Отсутствие `pubspec.lock` или `Podfile.lock` приводит к недетерминированным сборкам. Кроме того, lock-файлы защищают от supply chain атак: коммит фиксирует точный набор зависимостей, и SCA-сканеры могут выявлять CVE в зафиксированных версиях.

### Целостность артефактов

После сборки верифицируйте артефакты перед публикацией:

```bash
# iOS: проверка подписи
codesign --verify --deep --strict --verbose=2 build/ios/Runner.xcarchive

# Android: проверка подписи
apksigner verify --verbose app-release.aab
```

Хеши артефактов (SHA256) следует хранить в artifact registry для последующей проверки. Это предотвращает распространение поврежденных или скомпрометированных бинарников.

### Сборка iOS

Flutter генерирует Xcode-проект в `ios/`. Сборка происходит через `xcodebuild`:

```bash
flutter build ios --release --no-codesign
xcodebuild \
  -workspace ios/Runner.xcworkspace \
  -scheme Runner \
  -configuration Release \
  -archivePath build/ios/Runner.xcarchive \
  archive \
  CODE_SIGN_IDENTITY="Apple Distribution" \
  PROVISIONING_PROFILE_SPECIFIER="match AppStore com.example.app"
```

**Важно:** iOS-сборка выполняется только на macOS-раннерах. В GitLab CI это означает использование `tags: [macos]` вместо Docker-образа.

### Сборка Android

Flutter делегирует Gradle:

```bash
flutter build appbundle --release \
  --build-number=42 \
  --build-name=2.3.1
```

Результат: `build/app/outputs/bundle/release/app-release.aab`.

### Тестирование

- **Unit tests:** логика на Dart/TS без UI.
- **Widget/Component tests:** изолированные компоненты (Flutter: `flutter test`; RN: Jest + React Native Testing Library).
- **Integration tests:** полный прогон на устройстве/эмуляторе (Flutter: `flutter drive`; RN: `detox`).

**Quarantine flaky-тестов:** Нестабильные UI-тесты (flaky) должны выноситься в отдельную джобу с ограниченным retry. Ведите реестр flaky-тестов с SLA на починку (например, 5 рабочих дней). См. также [Mobile Test Automation](./testing-mobile.md).

### Производительность

- **Время сборки:** зависит от размера кодовой базы и количества зависимостей. Кэширование `~/.pub-cache`, `node_modules`, `build/` критично.
- **Размер артефакта:** Flutter с AOT создает крупные бинарники. Для Android используйте AAB вместо APK для уменьшения загрузочного размера.
- **Remote Build Cache:** Для Gradle используйте remote cache (например, `--build-cache` с сетевой директорией). Для Xcode кэшируйте DerivedData на shared storage между джобами.

### Наблюдаемость пайплайна

Отслеживайте метрики, позволяющие выявлять деградацию до того, как она приведет к инциденту:

- **Build Duration Trend:** алерт при росте времени сборки >20% за неделю.
- **Test Flakiness Rate:** % нестабильных тестов в общем наборе. Цель: <2%.
- **Pipeline Success Rate:** % успешных пайплайнов. Цель: >95%.
- **Cache Hit Rate:** % попаданий в кэш. Низкий hit rate означает проблемы с кэшированием или нестабильные зависимости.

---

## Практические сценарии

### 1. GitLab CI для Flutter

```yaml
stages:
  - test
  - build

variables:
  FLUTTER_VERSION: "3.27.0"
  DART_SDK: "/opt/flutter"

cache:
  key: "$CI_COMMIT_REF_SLUG-flutter"
  paths:
    - ~/.pub-cache
    - .dart_tool
    - build/

before_script:
  - export PATH="$DART_SDK/bin:$PATH"
  - flutter --version
  - flutter pub get

flutter_analyze:
  stage: test
  script:
    - dart analyze

flutter_test:
  stage: test
  script:
    - flutter test

build_android:
  stage: build
  image: ghcr.io/cirruslabs/flutter:3.27.0
  script:
    - flutter build appbundle --release
  artifacts:
    paths:
      - build/app/outputs/bundle/release/*.aab

build_ios:
  stage: build
  tags:
    - macos
  script:
    - flutter build ios --release --no-codesign
    - xcodebuild -workspace ios/Runner.xcworkspace -scheme Runner -configuration Release archive
  artifacts:
    paths:
      - build/ios/Runner.xcarchive
```

**Примечание:** Образы `ghcr.io/cirruslabs/flutter` прекратили обновление 1 мая 2026 года. Для актуальных версий используйте community fork `ghcr.io/adrianjagielak/flutter` с тем же форматом тегов. Для iOS-сборки используйте macOS-раннеры (`tags: [macos]`), Docker-образы для iOS не применяются.

### 2. GitLab CI для React Native

```yaml
stages:
  - lint
  - test
  - build

cache:
  key: "$CI_COMMIT_REF_SLUG-rn"
  paths:
    - node_modules/
    - ~/.npm
    - ios/Pods/

before_script:
  - npm ci --prefer-offline
  - cd ios && pod install && cd ..

lint:
  stage: lint
  script:
    - npx eslint src/
    - npx tsc --noEmit

test:
  stage: test
  script:
    - npx jest --coverage

build_android:
  stage: build
  image: reactnativecommunity/react-native-android:v21.0
  script:
    - cd android && ./gradlew assembleRelease
  artifacts:
    paths:
      - android/app/build/outputs/apk/release/*.apk

build_ios:
  stage: build
  tags:
    - macos
  script:
    - cd ios && xcodebuild -workspace YourApp.xcworkspace -scheme YourApp -configuration Release -derivedDataPath build
  artifacts:
    paths:
      - ios/build/Build/Products/Release-iphoneos/*.app
```

**Примечание:** Официального Docker-образа `reactnativecommunity/react-native-ios` не существует. iOS-сборка React Native выполняется на macOS-раннерах с предустановленным Xcode и Fastlane. Android-сборка использует `reactnativecommunity/react-native-android:v21.0` (на базе Ubuntu 24.04).

### 3. Управление зависимостями

**Flutter (pub):**
```bash
flutter pub get          # разрешение зависимостей
flutter pub upgrade      # обновление до последних совместимых версий
flutter pub outdated     # проверка устаревших пакетов
```

**React Native (npm):**
```bash
npm ci                   # установка по package-lock.json (детерминированная)
npm audit --audit-level=high  # проверка уязвимостей
```

**iOS (CocoaPods):**
```bash
cd ios && pod install    # установка нативных зависимостей
pod repo update          # обновление репозитория перед install (если версия не найдена)
```

### 4. Стратегии тестирования

```bash
# Flutter: unit + widget + integration
flutter test                          # unit + widget
flutter drive --target=test_driver/app.dart  # integration

# React Native: Jest + Detox
npx jest                              # unit + component
npx detox test --configuration ios.sim.release  # E2E
```

**Device Farm в CI:**
- Для Flutter используйте `flutter test` на эмуляторах внутри Linux-контейнера или на self-hosted ферме симуляторов.
- Для React Native используйте Detox на симуляторах macOS-раннера или self-hosted ферме реальных устройств.

### 5. Подпись кода iOS

Переиспользуйте существующие сертификаты и профили:

```bash
# Импорт сертификата и provisioning profile
security create-keychain -p "" build.keychain
security import cert.p12 -k build.keychain -P "$CERT_PASSWORD" -T /usr/bin/codesign
security import profile.mobileprovision -k build.keychain

# Установка ключа в Keychain
security set-keychain-settings -t 3600 -l build.keychain
security unlock-keychain -p "" build.keychain

# Сборка с подписью
xcodebuild -workspace ios/Runner.xcworkspace \
  -scheme Runner \
  -configuration Release \
  CODE_SIGN_IDENTITY="Apple Distribution" \
  PROVISIONING_PROFILE_SPECIFIER="match AppStore com.example.app" \
  archive
```

**Fastlane Match** позволяет хранить сертификаты в репозитории и автоматически скачивать их в CI:

```bash
match appstore --type appstore --readonly
```

### 6. Оптимизация производительности

```yaml
# Кэширование pub в GitLab CI
cache:
  key: "$CI_COMMIT_REF_SLUG-flutter"
  paths:
    - ~/.pub-cache
    - .dart_tool
    - build/

# Кэширование node_modules
cache:
  key: "$CI_COMMIT_REF_SLUG-rn"
  paths:
    - node_modules/
    - ~/.npm
    - ios/Pods/
```

**Ускорение сборки Flutter:**
```bash
flutter build ios --release --no-codesign --obfuscate --split-debug-info=build/debug-info
# --obfuscate сжимает Dart-код
# --split-debug-info выносит символы крашей в отдельный файл
```

**Ускорение сборки React Native:**
```bash
# Включение Hermes (android/app/build.gradle)
project.ext.react = [
  enableHermes: true
]

# Отключение линтера в release
NODE_OPTIONS="--max-old-space-size=4096" npx react-native bundle \
  --platform android \
  --dev false \
  --entry-file index.js \
  --bundle-output android/app/src/main/assets/index.android.bundle \
  --assets-dest android/app/src/main/res/
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| CocoaPods cache corrupted | Устаревший кэш, несовместимость версий | `pod cache clean --all && rm -rf ios/Pods ios/Podfile.lock && pod install` |
| Gradle daemon memory exhausted | Недостаточно памяти для параллельной сборки | Увеличьте `org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g` в `gradle.properties` |
| Xcode build cache stale | DerivedData устарел после обновления зависимостей | `flutter clean && rm -rf ~/Library/Developer/Xcode/DerivedData/*` |
| Flaky tests в CI | Нестабильные UI-тесты, race conditions | Вынесите flaky-тесты в отдельную джобу с retry, ведите реестр нестабильных тестов |
| iOS signing failures | Эфемерный раннер без сертификатов | Используйте Fastlane Match с `--readonly`, импортируйте сертификат перед сборкой |
| Metro bundler cache invalidation | Устаревший бандл после обновления зависимостей | `npx react-native start --reset-cache` или удалите `node_modules/.cache` |

---

## Best Practices

### SRE: метрики и наблюдаемость

**Ключевые SLI для Cross-Platform CI:**

| SLI | Описание | Целевое значение |
|:---|:---|:---|
| **Build Success Rate** | % успешных сборок | > 95% |
| **Build MTTR** | Время от падения до восстановления | < 30 минут |
| **Time to First Failure** | Время от запуска до первого упавшего теста | < 5 минут для unit-тестов |
| **Flaky Test Rate** | % нестабильных тестов в общем наборе | < 2% |
| **Error Budget (CI)** | Допустимый % проваленных пайплайнов | 5% в месяц |
| **MTTA** | Время от алерта до принятия решения | < 15 минут для P0 |

**Error Budget для CI:** Договоритесь с командой о допустимом проценте проваленных сборок (например, 5% в месяц). При исчерпании бюджета фокус смещается на стабилизацию пайплайна, а не на новые фичи.

**Toil Reduction:** Автоматизируйте управление зависимостями, очистку кэшей, уведомление о падениях. Ручной перезапуск сборок — это toil.

### Sysadmin: инфраструктура

1. **Runner Provisioning:** Для iOS используйте macOS-раннеры на Apple Silicon с Golden Image (Xcode, Fastlane, симуляторы). Для Android — Linux-контейнеры с Flutter/RN SDK.
2. **Artifact Storage:** Настройте reliable хранилище IPA/AAB/APK с retention policy и versioning.
3. **Certificate Monitoring:** Мониторьте срок действия сертификатов подписи. Настройте алерты за 30/7/1 день до истечения.
4. **Cleanup:** Регулярно очищайте stale кэши (CocoaPods, Gradle, DerivedData, `~/.pub-cache`, `node_modules`).
5. **Network Reliability:** Тестируйте скорость upload артефактов в хранилище. Медленный upload задержит distribution.

### Безопасность

1. **Секреты в CI:** Никогда не храните секреты в коде. Используйте Variables в CI/CD или внешние менеджеры секретов.
2. **Ephemeral Runners:** Одноразовые раннеры гарантируют, что секреты и сертификаты не остаются на диске после сборки.
3. **Artifact Integrity:** Верифицируйте артефакты после сборки: `codesign --verify` для iOS, `apksigner verify` для Android.
4. **Lock Files:** Коммитьте `pubspec.lock`, `package-lock.json`, `Podfile.lock` для предотвращения supply chain атак.
5. **SCA Integration:** Интегрируйте проверку CVE в пайплайн (OWASP Dependency-Check, Gradle Vulnerability Plugin).

### Производительность

1. **Кэширование:** Настройте кэширование зависимостей на уровне раннера (`~/.pub-cache`, `node_modules`, `ios/Pods`).
2. **Параллелизация:** Запускайте lint, тесты и сборку для Android/iOS параллельно.
3. **Remote Build Cache:** Для Gradle используйте remote cache; для Xcode кэшируйте DerivedData на shared storage.
4. **Incremental Builds:** Избегайте `flutter clean` в CI. Используйте кэширование `build/` между джобами.
5. **Один пайплайн на фреймворк:** Не смешивайте Flutter и RN логику в одном файле. Разделите на отдельные джобы.

---

## Дополнительная информация

- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout, approval gates, rollback procedures.
- **[Incident Response для мобильных приложений](./incident-response-mobile.md)** — hotfix workflow, MTTR, postmortem.
- **[Security Scanning в Mobile CI/CD](./security-scanning-mobile.md)** — SAST, SCA, DAST, MTTR Security.
