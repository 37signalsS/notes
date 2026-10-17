# Supply Chain Security для Mobile

**Актуально для:** iOS 17–26, Android API 24–35, GitLab CI 17.x, Cosign 2.x, Syft 1.x, SLSA v1.2

---

## Определения

**Supply Chain Security** — обеспечение целостности и происхождения артефактов от исходного кода до пользователя.

**SLSA (Supply-chain Levels for Software Artifacts)** — фреймворк зрелости цепочки поставок (L0-L4).

**SBOM (Software Bill of Materials)** — перечень компонентов приложения.

**Cosign/Sigstore** — инструменты подписи артефактов.

**Provenance** — метаданные о происхождении артефакта.

**Attestation** — подписанное заявление о свойствах артефакта.

**Reproducible Builds** — детерминированные сборки, дающие идентичный результат при одинаковых входных данных.

**MinIO** — self-hosted хранилище объектов, совместимое с API S3, для артефактов.

**HSM (Hardware Security Module)** — устройство или стандарт для безопасного хранения криптографических ключей подписи.

**Key Ceremony** — формализованная процедура генерации и распределения ключей подписи с участием нескольких доверенных лиц.

**Artifact Signing MTTR** — среднее время от компрометации ключа до отзыва и перевыпуска всех подписанных артефактов.

**SBOM Freshness SLO** — целевое максимальное время между изменением зависимостей и обновлением SBOM.

**Supply Chain Flake Rate** — процент джобов, проваленных из-за проблем с supply chain (неверная подпись, отсутствующий SBOM, drifted dependencies).

**Air-Gapped Signing** — процесс подписи артефактов в изолированной сети без внешнего доступа к интернет.

---

## Базовые концепции

### Угрозы supply chain для mobile

- Поддельные бинарники (tampered IPA/AAB)
- Скомпрометированные зависимости (malicious pods, gradle packages)
- Утечка ключей подписи (signing keys, keystore)
- Компрометация CI runner или артефактного хранилища
- Drift между SBOM и фактическим бинарником (SBOM не обновлен после изменения зависимостей)

### SLSA levels для mobile артефактов

| Level | Название | Требования |
|-------|----------|------------|
| L0 | Нет гарантий | Без provenance |
| L1 | Документирование | Скрипт сборки сохранён |
| L2 | hosted build | CI/CD с non-falsifiable provenance |
| L3 | Hardened | Изоляция, non-falsifiable provenance |
| L4 | hermetic | Reproducible builds, независимая верификация |

Для mobile: L2 достижим через GitLab CI с сохранением provenance JSON. L3 требует изоляции runners и подписи артефактов.

### Архитектура подписи артефактов (Cosign для IPA/AAB)

Cosign работает с любыми файлами. Для IPA/AAB:

```bash
# Подпись артефакта
cosign sign --key cosign.key myapp.ipa

# Верификация
cosign verify --key cosign.pub myapp.ipa
```

### SBOM generation для mobile

- iOS: SPM, CocoaPods зависимости
- Android: Gradle зависимости
- Форматы: CycloneDX, SPDX
- Инструменты: `syft`, `grype`, `cdxgen`

### Reproducible builds challenges

- Timestamps в бинарниках
- UUIDs и случайные значения
- Bitcode (iOS) — пересборка на стороне Apple
- Debug symbols (dSYM) — недетерминированы

### Хранение артефактов

Self-hosted: MinIO, Nexus Repository Manager, Artifactory, Nginx + объектное хранилище.

### Верификация в CI/CD

Проверка provenance и подписи артефакта на каждом stage пайплайна.

### Управление ключами подписи

**Принципы:**
- **Separation of duties:** Ключи для CI-сборок и release-подписи хранятся раздельно.
- **HSM/YubiKey:** Для release-ключей используйте HSM или YubiKey. CI-ключи могут храниться в encrypted artifact storage с access control.
- **Offline key ceremony:** Генерация release-ключей происходит на air-gapped машине с участием 2–3 доверенных лиц.
- **Key rotation:** CI-ключи — 90 дней, release-ключи — 1 год. Ротация автоматизирована через pipeline.
- **Compromise response:** При компрометации ключа — немедленный отзыв, перевыпуск артефактов, аудит всех подписей за период действия ключа.

**Air-gapped signing:**
- В high-security окружениях сборка происходит в air-gapped сети.
- Подпись артефакта выполняется на isolated signing station с HSM.
- После подписи artifact перемещается в artifact storage через sneakernet или internal mirror.
- Cosign в air-gapped режиме требует импорта публичных ключей (`cosign.pub`) и работы с локальными OCI-реестрами.

### Sysadmin: управление инфраструктурой supply chain

**Artifact Storage:**
- **Self-hosted:** MinIO, Nexus Repository Manager, Artifactory, Nginx + прокси объектного хранилища.
- **Retention:** Retention policy через MinIO ILM или Nexus cleanup tasks. Архивируйте SBOM и provenance бессрочно (compliance).
- **Backup:** Храните экспортированные шаблоны golden image и artifact snapshots в self-hosted storage (NFS, MinIO, локальный NAS) с versioning.

**Audit Logging:**
- Логируйте каждый signing event: artifact name, commit SHA, signer identity, timestamp, key ID.
- Архивируйте audit logs в immutable storage (WORM, append-only объектное хранилище) на 7–10 лет.
- Используйте SIEM для корреляции событий signing с deployment events.

**Secrets Rotation:**
- Ротация signing keys: CI — 90 дней, release — 1 год.
- Храните ключи в HSM или YubiKey, не на диске CI-раннера.
- Автоматизируйте ротацию через pipeline: новый ключ → подпись новыми артефактами → отзыв старого ключа.

**Network Hygiene:**
- Signing station не должен иметь лишнего outbound доступа.
- В air-gapped окружениях используйте internal mirror для dependency feeds (CocoaPods Specs, Gradle Plugin Portal, Swift Package Registry).

---

## Практические сценарии

### 1. Cosign для IPA/AAB

```bash
# Генерация ключей
cosign generate-key-pair

# Подпись IPA
cosign sign --key cosign.key build/output/myapp.ipa

# Подпись AAB
cosign sign --key cosign.key build/output/myapp.aab

# Верификация в CI
cosign verify --key cosign.pub build/output/myapp.ipa \
  --certificate-identity=myapp-ci \
  --certificate-oidc-issuer=https://gitlab.com
```

### 2. SBOM generation

```bash
# CycloneDX для iOS (SPM)
syft ./ios-app -o cyclonedx > sbom-ios.json

# CycloneDX для Android (Gradle)
syft ./android-app -o cyclonedx > sbom-android.json

# Сканирование CVE
grype sbom-ios.json
grype sbom-android.json
```

```yaml
# .gitlab-ci.yml
generate_sbom:
  stage: build
  image: anchore/syft:latest
  script:
    - syft . -o cyclonedx > sbom.json
  artifacts:
    paths:
      - sbom.json
    expire_in: 365 days
```

### 3. SLSA provenance для mobile

```ruby
# Ruby gem: slsa_provenance
require 'json'

provenance = {
  "_type" => "https://in-toto.io/Statement/v1",
  "predicateType" => "https://slsa.dev/provenance/v1",
  "subject" => [
    {
      "name" => "myapp.ipa",
      "digest" => {
        "sha256" => ENV['ARTIFACT_SHA256']
      }
    }
  ],
  "predicate" => {
    "builder" => {
      "id" => "https://gitlab.com/myproject"
    },
    "buildType" => "gitlab-ci",
    "invocation" => {
      "configSource" => {
        "uri" => ENV['CI_REPOSITORY_URL'],
        "digest" => {
          "sha1" => ENV['CI_COMMIT_SHA']
        },
        "entryPoint" => ".gitlab-ci.yml"
      }
    }
  }
}

File.write('provenance.json', provenance.to_json)
```

```yaml
# Генерация provenance в GitLab CI
generate_provenance:
  stage: build
  script:
    - ruby generate_provenance.rb
  artifacts:
    paths:
      - provenance.json
```

### 4. Reproducible builds

**Gradle (Android):**

```groovy
// android/build.gradle
android {
    buildTypes.release {
        // Фиксированный timestamp
        buildConfigField "long", "TIMESTAMP", "${System.currentTimeMillis() / 1000}L"
    }
}
```

```bash
# Детерминированная сборка
./gradlew assembleRelease \
  -PbuildTimestamp=20240101 \
  --no-daemon \
  --offline
```

**Xcode (iOS):**

```bash
# Детерминированная сборка
xcodebuild \
  -project MyApp.xcodeproj \
  -scheme MyApp \
  -configuration Release \
  -archivePath build/MyApp.xcarchive \
  CODE_SIGNING_ALLOWED=NO \
  CURRENT_PROJECT_VERSION=1 \
  MARKETING_VERSION=1.0 \
  archive
```

### 5. Artifact storage self-hosted

```bash
# MinIO через mc (MinIO Client)
mc alias set myminio http://minio.local:9000 $MINIO_ACCESS_KEY $MINIO_SECRET_KEY

# Загрузка артефактов
mc cp myapp.ipa myminio/artifacts/myapp-1.0.0.ipa
mc cp myapp.aab myminio/artifacts/myapp-1.0.0.aab
mc cp sbom.json myminio/artifacts/sbom-1.0.0.json
mc cp provenance.json myminio/artifacts/provenance-1.0.0.json

# Retention policy (удаление старше 180 дней)
mc ilm import myminio/artifacts --expire-days 180
```

```yaml
# Nginx + прокси объектного хранилища конфиг
server {
    listen 80;
    server_name artifacts.internal;

    location / {
        proxy_pass http://minio:9000;
        proxy_set_header Host $http_host;
    }
}
```

```ruby
# Ruby: проверка артефакта в deploy скрипте
require 'digest'
require 'json'

def verify_artifact(path, expected_sha256)
  actual = Digest::SHA256.file(path).hexdigest
  raise "SHA256 mismatch" unless actual == expected_sha256
  puts "Artifact verified: #{path}"
end

def verify_provenance(provenance_path)
  provenance = JSON.parse(File.read(provenance_path))
  raise "Missing subject" unless provenance['subject']
  puts "Provenance valid"
end
```

### 6. Верификация в deployment

```bash
# Проверка подписи перед публикацией в TestFlight
if ! cosign verify --key cosign.pub myapp.ipa; then
  echo "Artifact signature verification failed"
  exit 1
fi

# Проверка SBOM
if [ ! -f sbom.json ]; then
  echo "SBOM missing"
  exit 1
fi

# Проверка provenance
if ! ruby verify_provenance.rb provenance.json; then
  echo "Provenance verification failed"
  exit 1
fi

# Публикация
fastlane pilot upload -i myapp.ipa
```

```yaml
# GitLab CI: deployment stage
deploy_testflight:
  stage: deploy
  script:
    - cosign verify --key cosign.pub myapp.ipa
    - ruby verify_artifact.rb myapp.ipa $ARTIFACT_SHA256
    - ruby verify_provenance.rb provenance.json
    - bundle exec fastlane pilot upload -i myapp.ipa
  only:
    - main
```

### 7. Air-gapped signing workflow

```bash
# 1. Export artifact from build environment (sneakernet)
scp build-output/myapp.ipa signing-station:/tmp/

# 2. Verify checksum on signing station
sha256sum /tmp/myapp.ipa
# Compare with checksum from build environment

# 3. Sign with HSM-backed key
cosign sign --key yubikey:0 /tmp/myapp.ipa

# 4. Export signed artifact back
scp /tmp/myapp.ipa.sig artifact-storage:artifacts/

# 5. Import cosign.pub to verification environment
cosign verify --key cosign.pub myapp.ipa
```

---

## Операции и команды

### Верификация окружения signing

| Команда | Назначение | Ожидаемый результат |
|---|---|---|
| `cosign verify --key cosign.pub myapp.ipa` | Верификация подписи IPA | `Verified` или `Error: no signature` |
| `cosign verify --key cosign.pub myapp.aab` | Верификация подписи AAB | `Verified` |
| `syft . -o cyclonedx` | Генерация SBOM | JSON/CycloneDX документ |
| `grype sbom.json` | Сканирование CVE | Список CVE с severity |
| `security find-identity -p codesigning` | Проверка сертификатов в Keychain | Строки с `Apple Distribution` |
| `codesign -vvvv -d ./build/*.ipa` | Валидация подписи IPA | `valid on disk` |
| `aapt2 dump badging app-release.aab` | Проверка signing scheme AAB | `signingScheme=v2` или `v3` |
| `xcodebuild -version` | Версия Xcode | `Xcode 16.x` |
| `java -version` | Версия JDK для Android | `openjdk 17` или `21` |
| `gradle --version` | Версия Gradle | `Gradle 8.x` |
| `df -h /` | Дисковое пространство runner'а | Процент заполнения |

### Управление SBOM и provenance

```bash
# Генерация SBOM для iOS (SPM)
swift package resolve
swift package show-dependencies --format json > sbom-ios.json

# Генерация SBOM для Android (Gradle)
./gradlew dependencies --configuration releaseRuntimeClasspath \
  | grep -E "^\\+" \
  | sed 's/^\\+ //' > sbom-android.txt

# Валидация SBOM
syft sbom-ios.json -o cyclonedx-json | jq '.components | length'

# Проверка SBOM в deploy скрипте
if [ ! -f sbom.json ]; then
  echo "SBOM missing"
  exit 1
fi
```

### Очистка ключей и Keychain

```bash
# Удаление старых сертификатов из Keychain
security find-identity -p codesigning -v
security delete-identity -Z <SHA-1-hash> ~/Library/Keychains/login.keychain-db

# Очистка CocoaPods кэша перед подписью
rm -rf ~/Library/Caches/CocoaPods/*

# Очистка Gradle кэша
rm -rf ~/.gradle/caches/*
```

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
|---|---|---|---|
| **cosign: no signature** | Артефакт не подписан или ключ неверный | `cosign verify --key cosign.pub myapp.ipa` | Переподписать артефакт, проверить `cosign.pub` |
| **SBOM пустой или неверный** | syft не может прочитать проект | `syft . -o cyclonedx-json \| jq` | Использовать `syft dir:.` вместо `syft bin:` |
| **grype: no vulnerabilities database** | База CVE устарела | `grype sbom.json` | Обновить: `grype db update` |
| **Provenance JSON invalid** | Отсутствует `subject` или `predicate` | `jq . provenance.json` | Проверить структуру JSON, наличие обязательных полей |
| **Reproducible build mismatch** | Нефиксированный timestamp, UUID, bitcode | Сравнить два билда: `diffoscope build1.ipa build2.ipa` | Использовать фиксированный `CURRENT_PROJECT_VERSION`, отключить bitcode для тестов |
| **Key compromise / lost** | Утечка или потеря ключа подписи | Проверить audit log, отозвать ключ | Ротация ключей, переподпись всех артефактов, notification |
| **Artifact storage full** | Нет retention policy или бэкапы заполнили диск | `df -h /artifacts` | Настроить ILM/retention, архивировать старые артефакты |
| **MinIO connection refused** | MinIO не запущен или сконфигурирован неверно | `curl http://minio.local:9000` | Перезапустить MinIO, проверить `mc alias` |
| **Provisioning profile mismatch** | Профиль не соответствует сертификату | `security find-identity -p codesigning` | Обновить profile через `match` или Developer Portal |
| **Code signing: "The executable does not have the correct entitlements"** | Несоответствие entitlements между бинарником и profile | `codesign -d --entitlements :- MyApp.ipa` | Перевыпустить profile с правильными entitlements |
| **SBOM missing in release** | Шаг генерации SBOM пропущен или сломан | Проверить GitLab CI artifacts | Добавить SBOM generation в release pipeline, сделать обязательным |
| **Cosign OIDC verification failed** | Токен истек или issuer неверный | `echo $CI_JOB_JWT` | Проверить срок действия токена, настроить OIDC в GitLab |
| **Air-gapped: cosign cannot reach OCI registry** | Изолированная сеть без доступа к registry | `curl -v https://registry-1.docker.io` | Использовать локальный OCI registry, импортировать `cosign.pub` |

---

## Наблюдаемость пайплайна

**Метрики supply chain:**
- **Artifact Signing Success Rate** — процент успешно подписанных артефактов. SLO: > 99.5%.
- **SBOM Coverage** — процент артефактов с прикрепленным SBOM. SLO: 100%.
- **Supply Chain Flake Rate** — процент джобов, проваленных из-за проблем с supply chain. Target: < 0.5%.
- **SBOM Freshness** — время между изменением зависимостей и обновлением SBOM. SLO: < 24 часа.
- **Artifact Signing MTTR** — время от компрометации ключа до отзыва и перевыпуска. Target: < 4 часа.
- **Provenance Verification Pass Rate** — процент артефактов с валидной provenance. SLO: 100%.
- **CVE Remediation Time** — время от обнаружения CVE в SBOM до исправления. Target: P95 < 7 дней.
- **Key Rotation Compliance** — процент ключей, ротированных в срок. SLO: 100%.

**Логирование:**
- Логируйте каждый signing event: artifact name, commit SHA, signer identity, timestamp, key ID, exit code.
- Архивируйте SBOM и provenance вместе с артефактом в artifact storage.
- Сохраняйте audit log signing операций в immutable storage (WORM, append-only).
- Не храните секреты (key passwords, keystore passwords) в pipeline logs — используйте masked variables.

**Alerting:**
- Срабатывание при Artifact Signing Success Rate < 99.5%.
- Срабатывание при SBOM Coverage < 100%.
- Срабатывание при Supply Chain Flake Rate > 0.5%.
- Срабатывание при SBOM Freshness > 24 часов.
- Срабатывание при Artifact Signing MTTR > 4 часа.
- Срабатывание при CVE Remediation Time > 7 дней (P95).
- Срабатывание при Key Rotation Compliance < 100%.
- Срабатывание при отсутствии provenance у release-артефакта.

---

## Best Practices

- **Artifact Signing:** Подписывайте все артефакты (IPA/AAB) перед публикацией. Используйте CI-ключи для daily builds, release-ключи для production релизов.
- **SBOM Generation:** Генерируйте SBOM для каждого релиза и храните бессрочно. Обновляйте SBOM немедленно после изменения зависимостей.
- **Key Management:** Храните release-ключи в HSM или YubiKey. CI-ключи — в encrypted artifact storage с strict access control. Ротация: CI — 90 дней, release — 1 год.
- **Air-Gapped Signing:** Для high-security окружений используйте isolated signing station с HSM. Импортируйте только `cosign.pub` в verification environment.
- **Reproducible Builds:** Используйте фиксированные версии toolchain (Xcode, Gradle, JDK), фиксированные timestamps, отключайте bitcode для reproducibility-тестов.
- **Provenance:** Храните provenance и attestation вместе с артефактом. Верифицируйте provenance на каждом stage deployment.
- **Self-hosted Storage:** Для enterprise используйте MinIO, Nexus Repository Manager или Artifactory с retention policy и versioning.
- **Audit Logging:** Логируйте каждый signing event с полным контекстом (artifact, commit, signer, key ID, timestamp). Архивируйте в immutable storage.
- **Runbook'и:** Для компрометации ключа, failed signing, missing SBOM должно быть пошаговое руководство.
- **Compliance:** SBOM храните бессрочно. Artifact retention — минимум 1 год для daily builds, бессрочно для release.
- **CI Isolation:** Для release артефактов используйте dedicated runners (SLSA L3). Daily builds — shared runners с ограниченными permissions.
- **Dependency Pinning:** Используйте lock-файлы (Package.resolved, Podfile.lock, gradle.lockfile). Запретите floating версии (no `latest`, no ranges) в release pipeline.
- **CVE Remediation:** Автоматизируйте сканирование CVE через grype/trivy на каждом build. Блокируйте pipeline при Critical CVE в release dependencies.

---

## См. также

- **[Security Scanning в Mobile CI/CD](./security-scanning-mobile.md)** — SCA, SAST, supply chain scanning
- **[Dependencies Mobile](./dependencies-mobile.md)** — управление зависимостями, версионирование
- **[Release Management Mobile](./release-management-mobile.md)** — artifact retention, release evidence, SBOM storage
