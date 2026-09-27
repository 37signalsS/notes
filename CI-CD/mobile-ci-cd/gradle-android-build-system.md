# Gradle и Android Build System в Mobile CI/CD

**Актуально для:** AGP 8.13.x, Gradle 8.14.x

---

## Определения

- **Gradle** — система сборки для Android, используемая для компиляции, тестирования и публикации приложений.
- **AGP (Android Gradle Plugin)** — плагин Gradle, интегрирующий Android-специфичные задачи (компиляция, подпись, bundling).
- **Gradle Daemon** — фоновый процесс, ускоряющий повторные сборки за счет кэширования состояния.
- **Build Cache** — механизм кэширования outputs сборки для переиспользования между джобами.
- **signingConfigs** — конфигурация подписи в `build.gradle(.kts)`, включающая `storeFile`, `storePassword`, `keyAlias`, `keyPassword`.
- **versionCode** — целочисленный идентификатор сборки.
- **versionName** — маркетинговая версия.
- **AAB (Android App Bundle)** — современный формат публикации.
- **APK (Android Package)** — формат для прямой установки.
- **bundletool** — утилита для работы с AAB.
- **apksigner** — утилита для проверки и подписи APK.
- **Gradle Wrapper** — гарантирует использование фиксированной версии Gradle в проекте.
- **Build MTTR** — среднее время от обнаружения неработающей сборки до фикса или отката.
- **Build Error Budget** — допустимый процент падений сборок в месяц.
- **Build Evidence** — артефакты сборки: логи, APK/AAB, отчеты, метрики.
- **Build Flake** — недетерминированная сборка, которая периодически падает без изменений в коде.
- **Variant API** — механизм AGP для определения комбинаций build type, flavor, signing config. Начиная с AGP 10, новый Variant API становится обязательным.
- **Version Catalog** — централизованное управление версиями зависимостей через `gradle/libs.versions.toml` (Gradle 7.0+).
- **SBOM (Software Bill of Materials)** — инвентаризация всех компонентов сборки для отслеживания уязвимостей в supply chain.

---

## Базовые концепции

### Архитектура Gradle build

```
settings.gradle(.kts)
    └── build.gradle(.kts) (project)
            └── build.gradle(.kts) (app)
                    └── signingConfigs
                    └── buildTypes (debug/release)
                    └── productFlavors
            └── gradle.properties
```

**Файлы проекта:**
- `settings.gradle(.kts)` — определение модулей и репозиториев.
- `build.gradle(.kts)` (project) — плагины, зависимости, задачи на уровне проекта.
- `build.gradle(.kts)` (app) — Android-конфигурация: `signingConfigs`, `buildTypes`, `productFlavors`, `defaultConfig`.
- `gradle.properties` — свойства сборки: кэш, JVM-аргументы, AndroidX, signing properties.
- `gradle/wrapper/gradle-wrapper.properties` — фиксированная версия Gradle.

### Жизненный цикл сборки

1. **Initialization:** Gradle определяет проект (`settings.gradle(.kts)`) и подключает модули.
2. **Configuration:** Загрузка скриптов сборки, создание задач (tasks) на основе конфигурации.
3. **Execution:** Выполнение задач в соответствии с dependency graph. AGP добавляет Android-специфичные задачи: `mergeResources`, `compileDebugKotlin`, `bundleRelease`, `signReleaseBundle`.

### Build Variants

- **Build Type:** `debug` (отладочная сборка, без минификации), `release` (продакшен, с минификацией и подписью).
- **Product Flavor:** Кастомизация сборки под каналы (например, `free`/`paid`, `dev`/`staging`/`prod`).
- **Variant:** Декартово произведение build types × product flavors. Например, `freeDebug`, `paidRelease`.

### Версионирование

- `versionCode` — monotonically increasing integer. Используется Play Store для определения новизны.
- `versionName` — пользовательская версия, отображается в магазине.
- В CI `versionCode` часто привязан к `CI_PIPELINE_IID` или git commit count.

### Dependency management

- `implementation` — зависимость доступна внутри модуля, но не транзитивно экспортируется.
- `api` — зависимость транзитивно доступна потребителям модуля.
- `compileOnly` — только на этапе компиляции (например, annotation processors).
- `runtimeOnly` — только на этапе выполнения.
- **Lock-файлы:** `gradle/libs.versions.toml.lock` гарантируют reproducible builds.

### Build Cache

- **Local cache:** На уровне раннера (`~/.gradle/caches/`, `.gradle/buildCache/`). Ускоряет повторные сборки в рамках одного джоба.
- **Remote cache:** Self-hosted сервер (Gradle Enterprise или эквивалент). Кэширует outputs между джобами и разработчиками.
- **CI cache:** Кэширование зависимостей между пайплайн-запусками. Ключ кэша должен учитывать `gradle-wrapper.properties` и lock-файлы.

### Parallel builds и configuration on demand

- `org.gradle.parallel=true` — параллельное выполнение независимых задач.
- `org.gradle.configureondemand=true` — конфигурация только тех модулей, которые участвуют в текущей сборке.
- `--max-workers=N` — ограничение параллельных потоков. В CI обычно `2–4` в зависимости от CPU.

### Daemon vs no-daemon

- **Daemon (локально):** Ускоряет повторные сборки за счет сохранения состояния в памяти. `org.gradle.daemon=true`.
- **No-daemon (CI):** Гарантирует чистоту окружения между джобами. `org.gradle.daemon=false` или `--no-daemon`.

### SRE-подход к Gradle builds

- **Build Error Budget:** Договоритесь о допустимом проценте падений сборок в месяц. При исчерпании — фокус на стабилизацию пайплайна, а не на новые фичи.
- **Build MTTR:** Среднее время от падения сборки до фикса. Target: < 30 минут для blocking-инцидентов.
- **Flaky Build Management:** Ведите реестр «мигающих» сборок. Устанавливайте SLA на починку.
- **Build SLI/SLO:**
  - **Build Success Rate** — процент успешных сборок. SLO: > 99%.
  - **Build Duration P95** — 95-й перцентиль времени сборки. SLO: < 10 минут для release.
  - **Cache Hit Rate** — процент задач, выполненных из кэша. SLO: > 70%.

### Sysadmin: управление раннерами Android/Gradle

- **Диски:** Gradle кэш (`~/.gradle/caches/`), Android SDK (`/opt/android-sdk/`), артефакты могут занимать десятки гигабайт. Настройте log rotation и регулярную очистку через `systemd-tmpfiles` или `cron`.
- **Права:** CI-раннер должен иметь доступ к рабочему каталогу, но не к signing keys напрямую. Используйте injected secrets.
- **JVM tuning:** `org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g`. На раннерах с < 8 GB RAM уменьшите значения.
- **Мониторинг:** Собирайте метрики CPU, RAM, disk I/O через `node_exporter`. Настройте алерты на заполнение диска > 85%.
- **Очистка:** При смене major версии Gradle удаляйте `~/.gradle/caches/` полностью. Устанавливайте TTL 7–14 дней на CI cache.

### Безопасность signing в CI

- **Keystore injection:** Keystore декодируется из CI-секрета (Base64) в рабочий каталог раннера. Никогда не храните пароли в репозитории.
- **Google Play App Signing:** CI отвечает за Upload Key. Его потеря не критична — поддержка Google позволяет сбросить ключ.
- **Signing verification:** После сборки проверяйте подпись через `apksigner verify --verbose`.
- **Key rotation:** Планируйте ротацию Upload Key раз в 1–2 года. Архивируйте старые keystores.

---

## Практические сценарии

### 1. Gradle Wrapper и версионирование

Wrapper гарантирует, что все разработчики и CI используют одну и ту же версию Gradle.

```bash
# Проверка версии Gradle wrapper
./gradlew --version
# → Gradle 8.14

# Обновление wrapper на новую версию Gradle
./gradlew wrapper --gradle-version 8.14 --distribution-type bin
```

```kotlin
// build.gradle(.kts) — проверка версии AGP
plugins {
    id("com.android.application") version "8.13.0" apply false
}
```

```yaml
# .gitlab-ci.yml — кэширование Gradle wrapper
build:
  cache:
    paths:
      - .gradle/wrapper/
      - ~/.gradle/caches/
  script:
    - ./gradlew --version
```

### 2. Настройка signingConfigs для CI

Параметры подписи передаются через injected properties. Никогда не храните пароли в репозитории.

```kotlin
// build.gradle(.kts) — app модуль
android {
    signingConfigs {
        create("release") {
            storeFile = project.findProperty("RELEASE_STORE_FILE")?.let { file(it) }
            storePassword = project.findProperty("RELEASE_STORE_PASSWORD") as String?
            keyAlias = project.findProperty("RELEASE_KEY_ALIAS") as String?
            keyPassword = project.findProperty("RELEASE_KEY_PASSWORD") as String?
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
}
```

```yaml
# .gitlab-ci.yml — передача переменных
build_release:
  stage: build
  variables:
    GRADLE_OPTS: "-Dorg.gradle.daemon=false"
  script:
    - ./gradlew assembleRelease \
        -PRELEASE_STORE_FILE=$RELEASE_STORE_FILE \
        -PRELEASE_STORE_PASSWORD=$RELEASE_STORE_PASSWORD \
        -PRELEASE_KEY_ALIAS=$RELEASE_KEY_ALIAS \
        -PRELEASE_KEY_PASSWORD=$RELEASE_KEY_PASSWORD
```

```kotlin
// gradle.properties — безопасное хранение (только для локальной разработки)
# В CI переменные передаются через -P или environment variables
# RELEASE_STORE_FILE=/path/to/keystore.jks
# RELEASE_STORE_PASSWORD=*****
# RELEASE_KEY_ALIAS=upload
```

### 3. Автоматическое версионирование

Инкремент `versionCode` через CI pipeline ID или git tags.

```kotlin
// build.gradle(.kts) — динамическое версионирование
android {
    defaultConfig {
        val pipelineId = System.getenv("CI_PIPELINE_IID") ?: "1"
        versionCode = pipelineId.toInt()
        versionName = "1.0.${pipelineId}"
    }
}
```

```bash
# Альтернатива: версионирование через git tag
git describe --tags --always
# → v2.5.0-12-gabcdef
```

```yaml
# .gitlab-ci.yml — fallback для versionCode
variables:
  VERSION_CODE: "${CI_PIPELINE_IID:-1}"
build_release:
  script:
    - ./gradlew assembleRelease -PversionCode=$VERSION_CODE
```

### 4. Build Cache в CI/CD

Кэширование зависимостей и outputs для ускорения сборок.

```properties
# gradle.properties — конфигурация кэша
org.gradle.caching=true
org.gradle.caching.debug=false
org.gradle.parallel=true
org.gradle.configureondemand=true
```

```yaml
# .gitlab-ci.yml — локальный кэш
build:
  stage: build
  cache:
    key: "${CI_COMMIT_REF_SLUG}"
    paths:
      - .gradle/caches/
      - .gradle/buildCache/
      - app/build/
    policy: pull-push
  script:
    - ./gradlew assembleDebug --build-cache
```

```yaml
# Для remote cache требуется отдельный self-hosted сервер
# В gradle.properties указывается удаленный endpoint:
# org.gradle.caching.remote.url=https://cache.internal.example.com/cache/
```

### 5. Performance tuning

Настройка производительности сборки в CI.

```properties
# gradle.properties — оптимизации
org.gradle.daemon=false  # false в CI, true локально
org.gradle.parallel=true
org.gradle.configureondemand=true
org.gradle.workers.max=4
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g -Dfile.encoding=UTF-8
android.useAndroidX=true
android.enableJetifier=false
```

```yaml
# .gitlab-ci.yml — опции запуска
build_release:
  stage: build
  script:
    - ./gradlew assembleRelease \
        --no-daemon \
        --parallel \
        --configure-on-demand \
        --max-workers=4 \
        --build-cache
```

```bash
# Build scans для диагностики производительности
./gradlew assembleRelease --scan
# → Scan published: https://gradle.com/s/...
```

### 6. SCA и dependency management

Управление зависимостями и проверка уязвимостей.

```kotlin
// build.gradle(.kts) — gradle-versions-plugin
// Примечание: com.github.ben-manes.versions устарел, используйте io.github.ben-manes.versions
plugins {
    id("io.github.ben-manes.versions") version "0.61.0" apply false
}
```

```bash
# Проверка актуальных версий зависимостей
./gradlew dependencyUpdates -Drevision=release
```

```kotlin
// gradle/libs.versions.toml — catalog версий (Gradle 7.0+)
[versions]
agp = "8.13.0"
kotlin = "2.3.0"
retrofit = "2.11.0"

[libraries]
retrofit = { module = "com.squareup.retrofit2:retrofit", version.ref = "retrofit" }
```

```yaml
# .gitlab-ci.yml — Dependency Check (OWASP)
dependency_check:
  stage: test
  image: owasp/dependency-check
  script:
    - dependency-check.sh --project MyApp --scan . --format JSON
  artifacts:
    reports:
      dependency_check: dependency-check-report.json
```

```bash
# Lock-файлы для reproducible builds
./gradlew dependencies --write-locks
git add gradle/libs.versions.toml.lock
```

### 7. Валидация AAB

Проверка и подпись Android App Bundle в CI.

```bash
# Генерация APK из AAB через bundletool
bundletool build-apks \
  --bundle=app-release.aab \
  --output=app-release.apks \
  --mode=universal \
  --ks=release.jks \
  --ks-key-alias=upload \
  --ks-pass=pass:${RELEASE_STORE_PASSWORD} \
  --key-pass=pass:${RELEASE_KEY_PASSWORD}
```

```bash
# Установка APK из APKS
bundletool install-apks --apks=app-release.apks
```

```bash
# Проверка подписи APK через apksigner
apksigner verify --verbose app-release.apk
# → Verifies successfully
```

```yaml
# .gitlab-ci.yml — полная валидация
validate_aab:
  stage: verify
  script:
    - apksigner verify --verbose app/build/outputs/bundle/release/app-release.aab
    - bundletool validate --bundle=app/build/outputs/bundle/release/app-release.aab
```

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
|---|---|---|---|
| `Could not resolve all files for configuration` | Nexus/registry недоступен или dependency corrupted | `./gradlew dependencies --configuration releaseRuntimeClasspath --refresh-dependencies` | Проверить доступность registry, очистить кэш: `rm -rf ~/.gradle/caches/modules-2/` |
| Daemon OOM / `GC overhead limit exceeded` | `org.gradle.jvmargs` недостаточны для проекта | `cat ~/.gradle/daemon/*/daemon-*.out.log \| grep -i "outofmemory"` | Увеличить `-Xmx` до 6–8 GB, добавить `-XX:+HeapDumpOnOutOfMemoryError` |
| Cache corruption / `Circular dependency` | Поврежденный локальный кэш после сбоя сборки | `./gradlew build --refresh-dependencies` | Очистить кэш: `rm -rf .gradle/ build/` |
| `signingConfigs` не применяется | Отсутствует `signingConfig` в `buildTypes.release` или переменные не переданы | `./gradlew assembleRelease -Pverbose=true` | Проверить, что `RELEASE_STORE_FILE` существует, `signingConfig` присвоен |
| Build Flake: тест падает периодически | Кэширование тестовых данных, гонки, нестабильные моки | Перезапуск: `./gradlew test --rerun-tasks` | Изолировать тест, добавить `@Flaky` quarantine, увеличить timeout |
| `java.lang.UnsupportedClassVersionError` | JDK в CI старше требуемого AGP | `java -version` | AGP 8.13 требует JDK 17+. Установить JDK 17 или 21. |
| `Execution failed for task ':app:mergeDebugResources'` | Конфликт ресурсов, устаревший build-tools | `./gradlew :app:mergeDebugResources --info` | Обновить `build-tools` до 35.0.0+, очистить `app/build/` |
| Remote cache недоступен | Self-hosted cache сервер упал или сконфигурирован неверно | `curl -I https://cache.internal.example.com/cache/` | Проверить доступность endpoint,Fallback на локальный кэш: убрать `org.gradle.caching.remote.url` |
| Версионирование сбивается | `CI_PIPELINE_IID` сбрасывается или пустой | `echo $CI_PIPELINE_IID` | Использовать git-based fallback: `git rev-list --count HEAD` |
| `bundletool` / `apksigner` не найден | Инструменты не установлены в PATH раннера | `which bundletool && which apksigner` | Добавить в PATH или установить через SDK manager |
| Build зависает на `Configure project` | Большой проект, `configureondemand` не помогает | `./gradlew build --profile` | Анализировать profile report, выносить heavy logic в `afterEvaluate` |

---

## Наблюдаемость пайплайна

**Метрики:**
- **Build Success Rate** — процент успешных сборок. Target: > 99%.
- **Build Duration P95** — 95-й перцентиль времени сборки. Target: < 10 минут для release.
- **Cache Hit Rate** — процент задач, выполненных из кэша. Target: > 70%.
- **Build MTTR** — время от падения до фикса. Target: < 30 минут.
- **Flaky Build Rate** — процент недетерминированных падений. Target: < 1%.

**Логирование:**
- Сохраняйте `build/reports/profile` и `build/reports/dependency-check` как артефакты.
- Логируйте `versionCode`/`versionName` для каждого сборка.
- Архивируйте `gradle/libs.versions.toml.lock` для аута зависимостей.

**Alerting:**
- Срабатывание при падении Build Success Rate ниже 99%.
- Срабатывание при Build Duration P95 выше 15 минут.
- Срабатывание при Cache Hit Rate ниже 50%.
- Срабатывание при исчерпании Build Error Budget.

---

## Best Practices

- Используйте Gradle Wrapper с фиксированной версией. Никогда не вызывайте системный `gradle` в CI.
- Выносите sensitive данные (keystore passwords, signing keys) в CI secrets. Используйте injected properties, не файлы на диске.
- Фиксируйте версии всех плагинов (AGP, Kotlin, gradle-versions-plugin) в `build.gradle(.kts)` или version catalog.
- Используйте Version Catalog (`gradle/libs.versions.toml`) для централизованного управления версиями.
- Включайте lock-файлы (`dependencies --write-locks`) для reproducible builds.
- Кэшируйте `~/.gradle/caches/` и `.gradle/wrapper/` в CI. Устанавливайте TTL 7–14 дней.
- В CI всегда используйте `--no-daemon` и `--build-cache`.
- Настройте `org.gradle.workers.max` под количество CPU раннера. Обычно `2–4`.
- Валидируйте AAB/APK подпись отдельным пайплайн-стадией (`apksigner verify`, `bundletool validate`).
- Архивируйте Build Evidence: логи, артефакты, SBOM, scan reports.
- Настраивайте quarantine для flaky builds: автоматический quarantine при 2 последовательных падениях.
- При смене major версии Gradle полностью очищайте `~/.gradle/caches/` на всех раннерах.
- Используйте `--profile` и `--scan` для диагностики производительности. Архивируйте отчеты.
- Настройте retention policy для артефактов: храните release-артефакты 90–180 дней, debug — 7–14 дней.
- Автоматизируйте ротацию signing keys. Архивируйте старые keystores с комментарием даты ротации.

---

## См. также

- [android-ci-cd.md](./android-ci-cd.md) — подпись, Google Play App Signing, Fastlane Supply, SRE/SysAdmin контекст для Android
- [security-scanning-mobile.md](./security-scanning-mobile.md) — SCA, OWASP Dependency-Check, SBOM, signing verification
- [release-management-mobile.md](./release-management-mobile.md) — versioning, artifact retention, build cache management, release evidence
