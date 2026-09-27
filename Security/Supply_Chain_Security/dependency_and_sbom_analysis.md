# Анализ зависимостей и SBOM

## Определения

* **SCA (Software Composition Analysis — анализ состава ПО):** Автоматизированный процесс идентификации сторонних компонентов (open-source библиотек, коммерческих модулей) и оценки связанных с ними рисков безопасности, лицензионной чистоты и качества. В 2026 году интегрирован с **ASPM** для приоритизации рисков.
* **SBOM (Software Bill of Materials — состав программного обеспечения):** Машиночитаемый инвентарный перечень всех компонентов программного продукта. В 2026 году рассматривается как **Living SBOM** — динамический граф зависимостей, обновляемый в реальном времени.
* **VEX (Vulnerability Exploitability eXchange):** Сопроводительный документ к SBOM, в котором производитель указывает статус уязвимостей (например, `not_affected`, `fixed`). Позволяет фильтровать ложные срабатывания на основе фактической конфигурации продукта.
* **REACH Analysis (Анализ достижимости):** Технология, сочетающая статический анализ кода и динамический мониторинг (**eBPF / IAST**), которая определяет, вызываются ли уязвимые функции библиотеки. Снижает количество ложных срабатываний на 90%.
* **CBOM (Cryptographic BOM):** Перечень криптографических алгоритмов, ключей и библиотек (стандарт **ECMA-424**). Критичен для миграции на постквантовую криптографию (**PQC**).
* **CDXA (Cybersecurity Disclosure eXchange Architecture):** Протокол для автоматизированного обмена SBOM/VEX данными между вендорами и потребителями, необходимый для выполнения требований **EU CRA (Article 14)**.
* **PURL (Package URL):** Унифицированный идентификатор пакета, позволяющий однозначно ссылаться на компонент независимо от экосистемы и реестра. Формат: `pkg:type/namespace/name@version?qualifiers#subpath`.
* **CPE (Common Platform Enumeration):** Структурированный идентификатор для продуктов и платформ, используемый при сопоставлении уязвимостей (NVD).

## Основные концепции

В 2026 году анализ зависимостей стал обязательным согласно **EU Cyber Resilience Act (CRA)**. Производители обязаны уведомлять об эксплуатируемых уязвимостях в течение 24 часов и предоставлять SBOM для всех продуктов.

### Сравнение форматов SBOM (2026)

| Формат | Текущая версия | Ключевые особенности | Сфера применения |
| :--- | :--- | :--- | :--- |
| **SPDX** | 3.1+ | Модульная архитектура (Profiles), JSON-LD, расширенная поддержка лицензионного комплаенса. | Юридический комплаенс, сложные корпоративные системы. |
| **CycloneDX** | 1.7+ | Родная поддержка VEX, CBOM, CDXA, аттестаций соответствия. | DevSecOps, контейнеры, автоматизация безопасности, PQC. |

### Концепция "Living SBOM"

Современный SBOM — это не результат разового сканирования, а непрерывно обновляемый поток данных (Dynamic Dependency Graph):
1.  **Build Phase:** Генерация базового SBOM во время сборки с использованием **BuildKit / Syft**, фиксирующая точный состав артефакта.
2.  **Continuous Enrichment:** Автоматическое обогащение данными об уязвимостях и их статусе через **CDXA**-каналы поставщиков.
3.  **VEX & REACH Automation:** Применение VEX-отчетов и результатов анализа достижимости (REACH) для фильтрации неэксплуатируемых CVE.
4.  **Runtime Monitoring:** Сравнение состава ПО в памяти с SBOM для обнаружения инъекций кода в рантайме.
5.  **Graph Observability:** Агрегация всех SBOM и аттестаций в **GUAC** для мгновенного анализа влияния новых уязвимостей на всю инфраструктуру.

### Категории инструментов SCA (2026)

*   **Сканеры (Scanners):** `Trivy v0.55+`, `Grype`, `osv-scanner`, `Snyk`. Поддерживают семантический анализ и REACH.
*   **Генераторы (Generators):** `Syft v1.5+`, `cdxgen`, `CycloneDX CLI`. Поддержка профилей для специализированных систем и CBOM.
*   **Платформы ASPM / SBOM:** `Dependency-Track v5.x`, `Harbor v2.12+` (с нативной поддержкой Referrers), `Snyk AppRisk`.
*   **Наблюдаемость (Observability):** `GUAC` (Graph for Understanding Artifact Composition).

### Жизненный цикл SBOM в пайплайне

1.  **Генерация:** На этапе сборки создается базовый SBOM (Syft, BuildKit, cdxgen).
2.  **Подпись:** SBOM подписывается ключом или keyless (Cosign, Notation) и прикрепляется к артефакту через OCI 1.1 Referrers API.
3.  **Сканирование:** Trivy/Grype сопоставляют компоненты с базами CVE (NVD, OSV).
4.  **Фильтрация:** VEX-отчет исключает неэксплуатируемые уязвимости.
5.  **Хранение:** Harbor или внутренний реестр хранит SBOM как аттестацию, связанную с digest образа.
6.  **Верификация:** Admission-контроллер (Kyverno/OPA) проверяет наличие подписанного SBOM и отсутствие критических CVE перед деплоем.

## Практические сценарии

### Предварительные требования

Для реализации сквозного анализа зависимостей и SBOM на bare metal / on-prem инфраструктуре необходимы следующие компоненты:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Syft** | v1.5+ | Генерация SBOM/CBOM в форматах SPDX 3.1 и CycloneDX 1.7. |
| **Trivy** | v0.55+ | Сканирование зависимостей и артефактов, VEX-фильтрация. |
| **Grype** | v0.35+ | Анализ достижимости (reachability) уязвимостей. |
| **cdxgen** | 1.5+ | Генерация CycloneDX для языков, не покрытых Syft. |
| **Harbor** | v2.11+ | Локальный OCI-реестр с поддержкой OCI 1.1 Referrers API для хранения SBOM. |
| **Kyverno** | v1.19+ | Admission-контроль для верификации наличия SBOM и блокировки уязвимых образов. |
| **Git-сервер** | Gitea 1.21+ / GitLab 16+ | Хостинг исходного кода с защитой веток и подписью коммитов. |
| **Kubernetes** | 1.29+ | Целевая платформа для деплоя с Admission-политиками. |

**Аппаратные требования:**
* CPU с поддержкой AES-NI для ускорения криптографических операций при подписи SBOM.
* Минимум 8 ГБ ОЗУ на узел CI/CD-раннера, 16 ГБ — для сборки многомодульных проектов с глубоким деревом зависимостей.

**Начальное состояние окружения:**
* Два выделенных сервера: один для CI/CD (GitLab Runner / GitHub Actions self-hosted), второй для registry (Harbor).
* Отдельный кластер Kubernetes для продакшна с включенными admission-вебхуками.
* Внутренний DNS-сервер, разрешающий `harbor.internal` и `git.internal`.

### Генерация и фильтрация через VEX (Trivy v0.55+)

Использование VEX позволяет игнорировать уязвимости, которые присутствуют в коде библиотеки, но не могут быть эксплуатированы в текущей конфигурации.

```bash
# 1. Генерация SBOM в формате CycloneDX 1.7 (JSON)
trivy fs --format cyclonedx --output sbom.json .

# 2. Создание VEX-отчета для ложноположительных CVE
cat > vex-report.json << 'EOF'
{
  "vulnerabilities": [
    {
      "id": "CVE-2024-EXAMPLE",
      "status": "not_affected",
      "justification": "vulnerable_code_not_present",
      "detail": "Уязвимый модуль не импортируется приложением."
    }
  ]
}
EOF

# 3. Сканирование SBOM с применением VEX-отчета для исключения ложных срабатываний
trivy sbom --vex vex-report.json sbom.json
# Статус "not_affected" в VEX автоматически снимает алерт с конкретной CVE.
```

**Валидация:** Уязвимость CVE-2024-EXAMPLE отсутствует в итоговом отчете Trivy после применения VEX.

```bash
trivy sbom sbom.json --severity CRITICAL
# → 2026-09-18T14:00:00.000000000Z	INFO	Number of vulnerabilities: 0
```

### Анализ достижимости (REACH) через Grype и eBPF

Современные сканеры сочетают статический анализ с динамическими данными о выполнении кода.

```bash
# Статический анализ достижимости (Go, Java, Python)
grype my-app:latest --show-vulnerability-reachability

# В 2026 году данные о достижимости могут обогащаться через eBPF (например, Falco/Tetragon)
# Это позволяет подтвердить, что уязвимый бинарный файл действительно был загружен в память.
```

**Валидация:** Grype помечает уязвимости как `reachable` или `unreachable` в зависимости от статического анализа импортов.

```bash
grype my-app:latest -o json | jq '.matches[] | select(.vulnerability.severity=="HIGH") | {cve: .vulnerability.id, reachable: .matchDetails[0].maxReachability}'
# → {"cve":"CVE-2024-EXAMPLE","reachable":"UNREACHABLE"}
```

### Инвентаризация криптографии (CBOM через ECMA-424)

Критично для оценки готовности к постквантовой миграции.

```bash
# Генерация CBOM в формате CycloneDX 1.7
cdxgen -t java --output-format json --output cbom.json
# Позволяет выявить использование RSA/ECC библиотек, подлежащих замене на ML-DSA (PQC).
```

**Валидация:** Подсчет уязвимых алгоритмов в CBOM.

```bash
grep -E '"(RSA|ECDSA|AES)"' cbom.json | wc -l
# → Должен показать 0 уязвимых алгоритмов после миграции на ML-DSA
```

### Безопасная установка зависимостей в CI/CD

**Золотое правило:** Использование только детерминированных методов установки с проверкой целостности (Integrity Check).

| Язык | Команда | Файл фиксации | Особенности 2026 |
| :--- | :--- | :--- | :--- |
| **Node.js** | `npm ci` | `package-lock.json` | Поддержка **Isolated Installs** (pnpm-style). |
| **Python** | `pip install --require-hashes` | `requirements.txt` | Проверка SHA-256 для каждого колеса (wheel). |
| **Go** | `go mod download` | `go.sum` | Обязательная проверка через `GOSUMDB`. |
| **Rust** | `cargo fetch --locked` | `Cargo.lock` | Гарантия неизменности дерева зависимостей. |
| **Java** | `mvn dependency:resolve` | `pom.xml` + `maven.lock` | Использование `--no-transfer-progress` для стабильного вывода. |

### Lock-файлы: практические примеры

**Node.js — `.npmrc` для безопасности:**

```ini
# .npmrc (в корне проекта)
engine-strict=true
prefer-offline=true
package-lock=true
# Принудительная установка из внутреннего реестра для scope
@mycorp:registry=https://nexus.internal/repository/npm-internal/
```

```bash
# Установка строго по lock-файлу
npm ci
# → Использует ТОЛЬКО пакеты из package-lock.json с проверкой integrity

# Проверка: lock-файл синхронизирован
npm ls --json > /dev/null 2>&1 && echo "OK" || echo "OUT OF SYNC"
```

**Python — `pip-compile` для deterministic builds:**

```bash
# Генерация requirements.txt с хешами из pyproject.toml
pip install pip-tools
pip-compile --generate-hashes pyproject.toml -o requirements.txt

# Установка с проверкой хешей
pip install --require-hashes -r requirements.txt
# → pip проверяет SHA-256 каждого колеса перед установкой

# Обновление зависимостей (перекомпиляция)
pip-compile --upgrade --generate-hashes pyproject.toml -o requirements.txt
```

```ini
# requirements.txt с хешами
requests==2.31.0 --hash=sha256:abcdef1234567890...
urllib3==2.0.7 --hash=sha256:1234abcdef567890...
certifi==2024.7.4 --hash=sha256:fedcba0987654321...
```

**Go — vendoring для изолированных сборок:**

```bash
# Копирование зависимостей в vendor-каталог
go mod vendor
# → Все зависимости копируются в ./vendor/

# Сборка из vendor (без обращения к сети)
go build -mod=vendor ./...

# Проверка целостности vendor
go mod verify
# → all modules verified

# Gitignore: vendor/ — вопрос стратегии
# Вариант 1: коммитить vendor (для air-gapped и воспроизводимости)
# Вариант 2: не коммитить (gitignore), но guarantee vendor в CI
```

**Rust — `Cargo.lock` и вендоринг:**

```toml
# .cargo/config.toml (для альтернативного реестра)
[source.crates-io]
replace-with = "nexus-proxy"

[source.nexus-proxy]
registry = "https://nexus.internal/repository/cargo-registry/"
```

```bash
# Вендоринг зависимостей
cargo vendor
# → ./vendor/ содержит все зависимости

# Сборка из vendor
cargo build --offline
```

### Аудит зависимостей на air-gapped хосте

В изолированных сегментах сети сканеры не могут обращаться к внешним базам CVE. Необходимо локальное зеркалирование баз и периодическое обновление через механизм "data diode".

```bash
# На машине с интернетом: экспорт базы Trivy
trivy image --download-db-only --db-repository ghcr.io/aquasecurity/trivy-db

# На air-gapped машине: импорт базы
trivy image --db-repository localhost:5000/trivy-db --skip-db-update my-app:latest

# Генерация SBOM офлайн
syft my-app:latest -o cyclonedx-json > sbom-offline.json
```

**Валидация:** Trivy завершает сканирование без попыток сетевых запросов.

```bash
trivy image --skip-db-update my-app:latest
# → 2026-09-18T14:00:00.000000000Z	INFO	Detected OS: debian
# → 2026-09-18T14:00:01.000000000Z	INFO	Number of vulnerabilities: 0
```

### Сравнение SBOM между эталонами и Runtime

Отслеживание дрейфа зависимостей между версиями для обнаружения неавторизованных изменений.

```bash
# Генерация эталонного SBOM
syft my-app:v1.0.0 -o cyclonedx-json > sbom-baseline.json

# Генерация текущего SBOM
syft my-app:v1.1.0 -o cyclonedx-json > sbom-current.json

# Сравнение через trivy diff
trivy diff sbom:./sbom-baseline.json sbom:./sbom-current.json
```

**Валидация:** При отсутствии дрифта Trivy возвращает пустой отчет.

```bash
trivy diff sbom:./sbom-baseline.json sbom:./sbom-current.json
# → Total: 0 dependencies added, 0 removed, 0 changed.
```

### Интеграция SCA в GitLab CI (фрагмент пайплайна)

```yaml
stages:
  - scan

variables:
  SBOM_FILE: sbom.json
  VEX_FILE: vex-report.json

sbom-generate:
  stage: scan
  image: aquasec/syft:v1.5.0
  script:
    - syft dir:. -o cyclonedx-json > $SBOM_FILE
  artifacts:
    paths:
      - $SBOM_FILE
    reports:
      sbom: $SBOM_FILE

trivy-scan:
  stage: scan
  image: aquasec/trivy:0.55.0
  script:
    - trivy sbom $SBOM_FILE --severity CRITICAL,HIGH --exit-code 1
  only:
    - main
  dependencies:
    - sbom-generate

vex-apply:
  stage: scan
  image: aquasec/trivy:0.55.0
  script:
    - trivy sbom --vex $VEX_FILE $SBOM_FILE --severity CRITICAL,HIGH
  only:
    - main
  dependencies:
    - sbom-generate
```

## Валидация внедрения

После настройки пайплайна выполните комплексную проверку всех компонентов:

```bash
# 1. Проверка целостности SBOM и аттестаций
syft $REGISTRY:$IMAGE_TAG -o cyclonedx-json | jq '.components | length'
# → Число компонентов (например, 142)

# 2. Проверка наличия SBOM в реестре через Referrers API
curl -u "robot$ci-bot:$ROBOT_SECRET" \
  "https://harbor.internal/v2/my-app/manifests/sha256:$(skopeo inspect docker://$REGISTRY:$IMAGE_TAG --format '{{.Digest}}' | cut -d: -f2)/referrers"
# → {"manifest":{"layers":[{"mediaType":"application/vnd.dev.cosign.artifact.sig.v1+json",...}]}}

# 3. Проверка VEX-фильтрации
trivy sbom --vex vex-report.json sbom.json --severity CRITICAL
# → Уязвимости со статусом not_affected исключаются из отчета

# 4. Проверка CBOM для криптографических компонентов
cdxgen -t generic --output-format json --output cbom.json .
grep -E '"(RSA|ECDSA|AES)"' cbom.json | wc -l
# → Должен показать 0 уязвимых алгоритмов после миграции на ML-DSA

# 5. Проверка дрейфа SBOM (сравнение эталона и Runtime)
trivy diff sbom:./expected-sbom.json sbom:./runtime-sbom.json
# → Должен показать 0 изменений, если дрейф отсутствует
```

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Syft: unsupported package manager` | Язык/экосистема не покрыта стандартными плагинами | `syft dir:. -o cyclonedx-json` | Установите соответствующий плагин или используйте `cdxgen` как fallback. |
| `Trivy: false positive на CVE` | Уязвимый код не вызывается (reachability) | `trivy sbom --show-vulnerability-reachability` | Создайте VEX-отчет со статусом `not_affected`. |
| `SBOM generation failed: multi-arch` | Syft не поддерживает манифест image index | `syft -o spdx-json ...` | Используйте `docker buildx imagetools inspect --format '{{json .Manifest}}'` и генерацию SBOM для каждого архитектурного варианта отдельно. |
| `VEX не применяется` | Неверный формат VEX-файла или отсутствие полей `status` | `cat vex-report.json \| jq .` | Убедитесь, что VEX соответствует CycloneDX или SPDX VEX-профилю. |
| `SBOM drift detected` | В Runtime загружены библиотеки, отличные от SBOM | `syft runtime:process --output json` | Сравните загруженные библиотеки с SBOM через eBPF-агенты (Falco/Tetragon). |
| `cdxgen: unsupported language` | Экосистема не распознана | `cdxgen -t <lang> --help` | Укажите тип явно (`-t python`, `-t java`, `-t go`) или используйте `cdxgen --directory`. |
| `Trivy: DB connection refused (air-gapped)` | Сканер пытается обновить базу уязвимостей | `trivy image --skip-db-update ...` | Используйте флаг `--skip-db-update` и локальное зеркало базы Trivy. |
| `SBOM подпись не найдена` | Аттестация не прикреплена к образу | `curl /v2/.../referrers` | Убедитесь, что `docker buildx build` завершился с `--push` и флагом `--attest type=sbom`. |

## Лучшие практики и очистка

1.  **Least Privilege для CI-раннеров:** Используйте отдельные robot-аккаунты в Harbor с правами `push` только в целевой проект. В Kubernetes применяйте ServiceAccount с минимальными RBAC-правами для пайплайна.
2.  **Digest-pinning:** Никогда не используйте теги `latest` или `v1` в продакшне. Фиксируйте образы и зависимости по digest (`image@sha256:...`).
3.  **Эфемерные среды:** Каждая сборка выполняется в чистом Docker-контейнере или виртуальной машине, которая удаляется после выполнения. Никаких постоянных runner'ов с кешем зависимостей.
4.  **Ротация ключей:** Периодически (раз в 90 дней) ротируйте ключи подписи SBOM-аттестаций. Для keyless-сценария обновляйте Fulcio CA-корневой сертификат.
5.  **Очистка артефактов:** Настройте политику удержания (retention) в Harbor: удаляйте неу referencing-теги и старые аттестации через Harbor API или `docker buildx prune`.
6.  **Аудит SBOM:** Ведите журнал всех изменений зависимостей. Храните эталонные SBOM в версионном контроле (Git LFS) для последующего сравнения.

```bash
# Пример очистки старых артефактов в Harbor (через API)
curl -u "admin:Harbor12345" -X POST \
  "https://harbor.internal/api/v2.0/projects/my-app/repositories/my-app/artifacts/sha256:abc123" \
  -H "Content-Type: application/json" \
  -d '{"with_tag":false,"with_label":false}'
# → 200 OK (артефакт помечен для удаления)
```

## Граничные случаи и ограничения

* **Multi-architecture образы:** `docker buildx build` создает image index, а не единый манифест. SBOM и аттестации должны генерироваться для каждого архитектурного варианта (`linux/amd64`, `linux/arm64`) отдельно. Используйте `docker buildx imagetools inspect` для просмотра constituent-манифестов.
* **Air-gapped среды:** Отсутствие доступа к базам CVE требует развертывания локального зеркала Trivy DB и использования offline-режимов Syft/cdxgen. Все обновления баз должны проходить через механизм "data diode" с денормализацией.
* **Dynamic linking (`dlopen`):** Даже при корректной сборке SBOM, запущенный контейнер может загружать библиотеки динамически, не указанные в SBOM. Для обнаружения используйте eBPF-агенты (Falco/Tetragon) и сравнивайте загруженные библиотеки с SBOM в Runtime.
* **Dependency Confusion в air-gapped:** Внутренние namespace в реестрах (Harbor, Nexus) должны быть защищены от подмены публичными пакетами с одинаковыми именами. Используйте префиксы `internal-` или отдельные домены реестров.
* **SBOM дрейф в Runtime:** Даже при корректной сборке, запущенный контейнер может отличаться от SBOM из-за динамической загрузки библиотек (например, через `dlopen`). Для обнаружения используйте eBPF-агенты (Falco/Tetragon) и сравнивайте загруженные библиотеки с SBOM.
* **Обратная совместимость PQC в SBOM:** Алгоритмы ML-DSA/SLH-DSA не поддерживаются клиентами OpenSSL < 3.4. Для гибридной миграции используйте связку `ECDSA + ML-DSA`, пока все узлы не будут обновлены.

## Дополнительная информация

### Стандарты и ресурсы

* **CycloneDX Specification (v1.7):** <https://cyclonedx.org/> — формат SBOM с родной поддержкой VEX, CBOM и CDXA.
* **SPDX Specification (v3.1):** <https://spdx.dev/> — модульный формат с JSON-LD поддержкой и ISO-стандартизацией.
* **NIST PQC Standards:** <https://csrc.nist.gov/Projects/post-quantum-cryptography> — стандарты FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) и FIPS 205 (SLH-DSA).
* **EU CRA:** <https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act> — официальный текст закона о киберустойчивости ЕС.
* **ECMA-424:** <https://www.ecma-international.org/> — стандарт Cryptography Bill of Materials (CBOM).
* **IETF SCITT:** <https://datatracker.ietf.org/wg/scitt/> — цепочка доверия для программных артефактов (Supply Chain Integrity, Transparency, and Trust).
* **OpenSSF:** <https://openssf.org/> — инициативы GUAC, Scorecard и Sigstore.

### Связанные документы

* [Обзор безопасности цепочки поставок](./overview.md) — фундаментальные принципы, SLSA v2.0 и регуляторика (EU CRA).
* [Целостность сборки](./build_integrity.md) — SLSA v2.0, герметичные сборки и воспроизводимость.
* [Подпись артефактов](./artifact_signing.md) — подпись SBOM и VSA-аттестаций.
* [SBOM для Docker](../../Docker/Docker_security/docker_sbom.md) — специфика генерации через BuildKit.
* [Сканирование уязвимостей](../../Docker/Docker_security/vulnerability_scanning.md) — детальное использование Trivy и Grype.
* [ASPM: Управление безопасностью приложений](../../CI-CD/DevSecOps/devsecops_overview.md) — централизация результатов SCA.
