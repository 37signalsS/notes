# Сравнение SCA-инструментов (Software Composition Analysis)

**Актуально для:** Trivy 0.76+, Grype 0.120+, Syft 1.54+, osv-scanner v2.7+ (V2), OWASP Dependency-Check 13.0, Snyk CLI 1.1308+; self-hosted / on-prem (Linux bare metal, GitLab Runner, Harbor, Kubernetes-кластеры). Проверено на исходниках: Trivy v0.76.0, Grype v0.120.1, Syft v1.54.1, osv-scanner v2.7.0, OWASP Dependency-Check 13.0.0.

## Определения

- **SCA (Software Composition Analysis):** поиск уязвимостей и лицензий в открытых зависимостях проекта (транзитивных и прямых) на основе их идентификаторов (PURL/CPE/verification) и баз знаний (NVD, OSV, GHSA, distro-specific).
- **SBOM (Software Bill of Materials):** машинночитаемый список компонентов продукта (CycloneDX / SPDX / Syft JSON). Генерируют сканеры и менеджеры пакетов; сканеры потребляют SBOM для повторного сканирования без оригинального артефакта.
- **VEX (Vulnerability Exploitability eXchange):** документ (CycloneDX VEX / OpenVEX / CSAF), где производитель заявляет статус уязвимости (`not_affected`, `under_investigation`, `in_triage`, `fixed`, `not_affected` с `justification: vulnerable_code_not_present`/`code_not_reachable`). Применяется сканерами для подавления ложных срабативаний; отличается от SBOM: SBOM = *что есть*, VEX = *что реально влияет*.
- **Reachability (достижимость):** статический (call-graph / govulncheck) и динамический (eBPF, runtime) анализ, выявляющий, вызывается ли уязвимая функция в приложении.
- **EPSS (Exploit Prediction Scoring System):** вероятность эксплуатации CVE в ближайшие 30 дней (0.0–1.0).
- **KEV (CISA Known Exploited Vulnerabilities):** список CVE с подтверждённой эксплуатацией в публичном доступе.
- **CVSS:** Common Vulnerability Scoring System — базовый/временный/окружающий score.
- **PURL / CPE:** унифицированный идентификатор пакета (PURL) и формат идентификатора продукта (CPE) для сопоставления с базами CVE.
- **OSV:** Open Source Vulnerabilities — агрегатор экосистемных advisory (NVD, GHSA, distro). osv-scanner — фронтенд к OSV + библиотека Scalibr.

Более глубокие определения SBOM/VEX/CBOM/CDXA см. в [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md).

## Как SCA работает в pipeline (архитектура)

Типичный конвейер SCA состоит из цепочки независимых шагов, каждый из которых может исполнить отдельный инструмент:

```
 Исходники / образ / lock-файл
        │
        ▼
 1. Discovery  ── Syft / Trivy fs / osv-scanner scan source
        │  (выделение пакетов → PURL/CPE)
        ▼
 2. SBOM       ── Syft (-o cyclonedx-json|spdx-json) / Trivy fs --format cyclonedx
        │  (воспроизодимый артефакт, подпись через cosign)
        ▼
 3. Matching   ── Trivy sbom / Grype sbom: / osv-scanner scan sbom
        │  (NVD, OSV, GHSA, distro, vuln-list)
        ▼
 4. Triage     ── VEX (--vex) / govulncheck / Grype --sort-by risk,kev,epss / Snyk prioritization
        │  (отбраковка not_affected, порог CVSS/EPSS/KEV)
        ▼
 5. Gate       ── fail-on-severity / fail-on-policy / policy-as-code (Kyverno/OPA)
        ▼
 6. Remediation ── Renovate / Dependabot / ручной апдейт → новый SBOM
```

Ключевые принципы:
- **Генерировать SBOM один раз, сканировать много раз** — `syft` собирает manifest, `grype`/`trivy` сопоставляют с DB. Это позволяет пересканировать артефакт по мере обновления баз, не трогая образ.
- **VEX ≠ замена reachability** — VEX документирует решение о недостижимости; реальная достижимость требует статического (govulncheck) или динамического (eBPF) анализа.
- **Политика fail-fast в CI, но не для всех CVE** — глушите `not_affected` через VEX и `wont_fix`/`ignored` списки, иначе пайплайн забьётся на ложных срабатываниях.

> **Ограничение OSS:** в открытых сборках Trivy и Grype **нет встроенного reachability-сканирования и фильтра EPSS как пользовательского флага** (это функции коммерческого уровня). Reachability в OSS — через внешние `govulncheck` (Go) и VEX с `justification: code_not_reachable`; EPSS/KEV — через `Grype --sort-by epss/risk/kev`, `osv-scanner` (через OSV) и `Snyk`.

## Сравнение инструментов

| Критерий | **Trivy** 0.76+ | **Grype** 0.120+ | **Snyk** 1.1308+ | **osv-scanner** v2.7+ | **OWASP Dependency-Check** 13.0 | **Syft** 1.54+ |
|:---|:---|:---|:---|:---|:---|
| **Тип** | Сканер + SBOM (через Syft) | Сканер уязвимостей | Платформа SaaS + CLI | Сканер | Сканер (многоплатформенный) | Генератор SBOM |
| **Фокус** | образы, FS, SBOM, IaC, конфиги, K8s, secrets, лицензии | образы, SBOM, FS (matching) | код (SAST+SCA), контейнеры, IaC | lock-файлы, образы, источники | Java/Maven/Gradle + npm, pip, Ruby, .NET, Rust | SBOM из образов/FS/lock-файлов/кода |
| **Языки / форматы** | 30+ экосистем (apk, dpkg, rpm, Go, Java, JS, Python, Ruby, Rust, PHP, .NET) | читает Syft JSON, CycloneDX, SPDX, образ, FS | npm, Maven, Gradle, pip, Go, NuGet, RubyGems, Composer, Cocoapods, Cargo, Hex | 11+ экосистем, 19+ lock-файла, образы | Java/Maven, Gradle, npm, pip, Ruby, .NET, Rust | 30+ экосистем, CycloneDX, SPDX, Syft JSON |
| **Базы CVE** | NVD, GitHub Advisory, OSV, distro (Alpine/Red Hat/Ubuntu), vuln-list (Aqua) | vunnel DB: NVD, GHSA, 6 distro-канала | NVD + Snyk Vulnerability DB | OSV.dev (агрегатор NVD + экосистемных) | NVD API (+ Sonatype, NPM Audit, OSS Index, RetireJS, Bundler Audit) | — (генератор) |
| **SBOM** | генерация + чтение (`trivy fs/sbom --format cyclonedx/spdx`, `trivy sbom`) | чтение + сканирование SBOM; вывод `table, json, cyclonedx` (`grype sbom:`) | генерация + чтение | чтение (сканирует SBOM) | чтение (формирует manifest) | генерация (CycloneDX, SPDX, Syft JSON) |
| **VEX** | применение (`--vex`, `trivy vex repo`) | применение (`--vex`, VEX-processor) | Да | нет | нет | — |
| **Reachability (call-graph)** | Нет (commercial Aero); Go — `govulncheck`; иначе VEX `code_not_reachable` | Нет (OSS) | Да (Snyk reachability) | Да (`--call-analysis=go` по умолчанию, Java, Rust) | Нет | — |
| **EPSS / приоритизация** | Нет (OSS; EPSS — commercial/plopsec) | Да (`--sort-by epss`; составной `--sort-by risk` = EPSS+KEV+CVSS) | Да (EPSS/CVSS + exploit maturity) | Нет в CLI (данные через OSV) | Нет | — |
| **KEV (CISA)** | коммерчески (Aero) | Да (`--sort-by kev`) | Да | через OSV | Нет | — |
| **Лицензии** | Да (`--scanners license`) | Нет | Да | Да (`--licenses`) | Нет | — |
| **IaC / конфиги** | Да (Terraform, K8s, Dockerfile, K8s cluster, Helm) | Нет | Да | Нет | Нет | Нет |
| **Air-gapped / offline** | Да (`--skip-db-update`, `--db-repository`, `--download-db-only`) | Да (локальная DB, `--no-db-update`) | частично | Да (`--offline --download-offline-databases`) | Да (`--nvdDatafeed` локально) | Да (локальные pURL/CPE) |
| **Лицензия** | Apache 2.0 | Apache 2.0 | Snyk Agent (freemium) | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **CI / self-hosted** | CLI, GitHub Action, GitLab CI, Harbor | CLI, GitHub Action | CLI, GitHub Action, 70+ интеграций | CLI, GitHub Action | Maven/Gradle плагин, CLI, Jenkins | CLI, GitHub Action, GitHub Action |

> Суждения о Reachability/EPSS проверены на исходниках Trivy v0.76.0 и Grype v0.120.1: флаги `--show-vulnerability-reachability` и `--epss-score` в OSS-сборках **отсутствуют** (см. `docs/commercial/compare.md` — reachability помечен `-` для OSS; для Go Trivy рекомендует внешний `govulncheck`).

## Когда использовать

| Сценарий | Инструмент | Комментарий |
|:---|:---|:---|
| Сканирование Docker-образа в CI | **Trivy** (≥ 0.70.1) | Быстро, `--severity`, `--exit-code 1`, `--scanners vuln,secret,misconfig` |
| Повторное сканирование по SBOM | **Grype** `sbom:` / **Trivy** `sbom` | DB обновляется — сканируйте SBOM без образа |
| Приоритизация CRITICAL/HIGH | **Grype** `--sort-by risk` | Составной score: EPSV+KEV+CVSS |
| SBOM для каждого релиза | **Syft** | CycloneDX + SPDX; подпись `cosign` |
| Анализ достижимости (Go) | **govulncheck** | Единственный проверенный OSS-механизм call-graph |
| Анализ достижимости (Java/JS/...) | **osv-scanner** `--call-analysis` / **Snyk** | call analysis / коммерческий reachability |
| Lock-файлы и monorepo | **osv-scanner** v2 `scan source -r` | 19+ форматов; `--lockfile` |
| Лицензионный аудит | **Trivy** `--scanners license` / **osv-scanner** `--licenses` / **Snyk** | allowlist подход лучше fail-листа |
| Enterprise + Jira/служба/incident lifecycle | **Snyk** | SaaS dashboard, авто-PR с fix'ами |
| Java/Maven в Jenkins | **OWASP Dependency-Check** (≥ 13.0) | NVD API key обязателен; иначе rate-limit |
| Air-gapped / без доступа в сеть | **Trivy** + **Syft** `Grype` | `--skip-db-update`, `--db-repository`, локальные DB |

## Предварительные требования

- **ОС/хост:** Linux (ядро ≥ 5.4) bare metal или ВМ; Docker/Podman для сканer-as-a-tool или rootless.
- **Сеть:** доступ к `registry-1.docker.io`, `github.com`, зерку NVD/OSV/GHSA либо локальный VEX/SBOM-репо. В air-gapped — скачайте DB один раз (`trivy db`, `grype db update`, `osv-scanner --download-offline-databases`).
- **Версии (не манипулируйте `latest`):** Trivy ≥ 0.70.1 (из-за CVE-2026-33634 — компрометация образов сканера в v0.69.4; безопасны 0.69.2, 0.69.3 и ≥ 0.70; рекомендовано 0.76+), Syft 1.52+, Grype ≥ 0.82.0, osv-scanner v2 (v1 deprecated). SHA256-контрольные суммы артефактов обязательны — см. [Безопасный релиз в CI/CD](../../CI-CD/DevSecOps/secure_release_pipeline.md).
- **NVD API key:** для OWASP Dependency-Check и Trivy — дешифрует rate-limit (35 req/мин без ключа → 5000 req/мин с ключом).
- **Подписанты:** `cosign` (v2.6+) для подписи SBOM/VEX — key-based для air-gapped, OIDC/Fulcio только если транспорный уровень допущен (это public infra, а не cloud-vendor).

## Практические сценарии

### Сценарий 1: Сканирование Docker-образа (Trivy 0.76+)

```bash
# 1. Базовое сканирование на CVE
trivy image harbor.internal/my-app:v1.2.3
# → Total: 42 vulnerabilities (5 critical, 12 high)

# 2. Только CRITICAL/HIGH с исправлениями, fail в CI
trivy image \
  --severity CRITICAL,HIGH \
  --ignore-unfixed \
  --exit-code 1 \
  --scanners vuln,secret,misconfig \
  harbor.internal/my-app:v1.2.3

# 3. Сужение до прямых зависимостей (меньше шума; НЕ совмещать с --vex/SBOM)
trivy image --pkg-relationships root,direct harbor.internal/my-app:v1.2.3

# 4. Применение VEX (подавление not_affected / code_not_reachable)
trivy image --vex ./vex.cdx harbor.internal/my-app:v1.2.3
# → уязвимости со статусом not_affected исчезают из отчёта

# 5. IaC / конфиги проекта
trivy config ./k8s/ --severity CRITICAL,HIGH --exit-code 1
```

**Валидация:** `# → exit code 0` при отсутствии CRITICAL/HIGH; `# → CRITICAL: 0` в итоговой строке.

> **Reachability/EPSS в Trivy OSS:** флагов `--show-vulnerability-reachability`/`--epss-score` **нет** (проверено на исходнике v0.76.0). Reachability требует `govulncheck` (Go) или VEX с `justification: code_not_reachable`; EPSS-приоритизацию делайте в Grype (`--sort-by epss`) или Snyk.

### Сценарий 2: Приоритизация и объяснение находок (Grype 0.120+)

```bash
# 1. Сканирование SBOM с композитной оценкой риска (EPSS+KEV+CVSS, default)
grype sbom:./sbom.cdx.json -o json --sort-by risk > grype-result.json

# 2. Фильтр по EPSS (наиболее вероятные к эксплуатации)
grype sbom:./sbom.cdx.json --sort-by epss -o json | \
  jq '.matches[] | {id: .vulnerability.id, risk: .vulnerability.risk.score}'

# 3. Объяснение находки
grype explain --id CVE-2024-1234

# 4. Гейт в CI
grype sbom:./sbom.cdx.json --fail-on high --only-fixed -o table

# 5. Применение VEX
grype sbom:./sbom.cdx.json --vex ./vex.cdx -o json
```

**Валидация:** `jq '[.matches[]?] | length' grype-result.json`; `# → 0` после VEX для покрытых CVE.

> **Reachability в Grype OSS:** флаг `--show-vulnerability-reachability` **отсутствует** (проверено на v0.82.0 и v0.120.1). Приоритизация реализуется через `--sort-by {risk|epss|kev}` и `grype explain`.

### Сценарий 3: Генерация SBOM (Syft 1.54+)

```bash
# 1. SBOM из образа (CycloneDX — основной формат для VEX/SCA)
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json > sbom.cdx.json

# 2. SBOM из lock-файла (npm)
syft ./package-lock.json -o spdx-json > sbom-npm.spdx.json

# 3. SBOM из каталога исходников
syft dir:. -o cyclonedx-json > sbom-app.cdx.json
```

**Валидация:** `jq -e '.components[]? | select(.name=="log4j")' sbom.cdx.json`; `# → {"name":"log4j",...}`.

### Сценарий 4: Сканирование lock-файлов (osv-scanner v2)

```bash
# V2: подкоманда scan source (V1-синтаксис --lockfile/-r deprecated)
osv-scanner scan source -r ./src --format=cyclonedx-1-5 --output-file=./sbom.cdx.json

# Сканирование конкретного lock-файла
osv-scanner scan source --lockfile=/app/package-lock.json   # или -L

# Сканирование образа
osv-scanner scan image harbor.internal/my-app:v1.2.3

# Call analysis (reachability) для Go — включена по умолчанию
osv-scanner scan source ./go-project --call-analysis=go
```

**Валидация:** `jq '.results[] | select(.severity=="CRITICAL")' ./sbom.cdx.json`; `# → пусто` при чистом lock-файле.

### Сценарий 5: Сканирование зависимостей Java в Jenkins (OWASP Dependency-Check 13.0)

```bash
# Maven
mvn dependency-check:check -Dformat=ALL -DfailBuildOnAnyVulnerability=true -DnvdApiKey=$NVD_API_KEY

# CLI (универсальный)
dependency-check.sh --scan /app --format ALL --project "my-app" \
  --nvdApiKey $NVD_API_KEY --out /app/results
```

**Валидация:** HTML-отчёт `dependency-check-report.html`; CLI `grep -c "CVE-" *.json`.

> **NVD rate-limit:** без ключа ≥ 35 req/мин → 429. Ключ обязателен; для air-gapped — `--nvdDatafeed` (зеркало NVD) либо локальная копия. Issue #8618 в проекте — "wont fix", т.к. NVD API требует ключ.

### Сценарий 6: Лицензионный аудит (licensing)

```bash
# Trivy — лицензии в CI
trivy image --scanners license harbor.internal/my-app:v1.2.3 -o json | \
  jq '.Results[].Licenses[] | {name: .Name, severity: .Severity}'

# osv-scanner — allowlist подход
osv-scanner scan source ./ --licenses="MIT,Apache-2.0" --format=json
# → exit 0, только неизвестные/читающиеся лицензии попадают в report

# Snyk — policy-as-code
snyk test --org $ORG --fail-on=patchable-vulns
```

**Валидация:** `# → "severity":"UNKNOWN"` для packages без декларированной лицензии.

### Сценарий 7: Сравнение SBOM (drift detection)

```bash
# 1. Эталонный SBOM (baseline релиза)
syft harbor.internal/my-app:v1.0.0 -o cyclonedx-json > sbom-baseline.json
# 2. Текущий SBOM
syft harbor.internal/my-app:v1.1.0 -o cyclonedx-json > sbom-current.json
# 3. Сравнение состава (добавленные / удалённые пакеты)
diff <(jq -r '.components[].purl' sbom-baseline.json | sort) \
     <(jq -r '.components[].purl' sbom-current.json | sort)
# → пустой вывод = состав идентичен (нет drift)
```

> `trivy diff` в OSS **не существует** (проверено на v0.76.0: подкоманда `diff` отсутствует среди command Use). Сравнение SBOM делайте через `syft` + `diff`/`jq`, либо `snyk sbom diff` (коммерчески). См. также [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md).

### Сценарий 8: Полный pipeline в CI (GitLab CI, self-hosted)

```yaml
# .gitlab-ci.yml — SCA + SBOM + gate
image: docker:29
services: [docker:29-dind]

stages: [build, security, deploy]

variables:
  REGISTRY: harbor.internal
  IMAGE: $REGISTRY/my-app:$CI_COMMIT_REF_SLUG

sca_scan:
  stage: security
  image:
    name: anchore/grype:0.120.1
    entrypoint: [""]
  script:
    # 1. SBOM (Syft) — один раз, переиспользуемый артефакт
    - syft $IMAGE -o cyclonedx-json > sbom.cdx.json
    # 2. Сканирование SBOM на CVE (Grype) с приоритизацией
    - grype sbom:sbom.cdx.json --sort-by risk --fail-on high -o sarif --file grype.sarif
    # 3. Trivy — secrets + misconfig в образе
    - trivy image --scanners vuln,secret,misconfig --severity CRITICAL --exit-code 1 $IMAGE
    # 4. Trivy — IaC в репо
    - trivy config ./k8s/ --severity CRITICAL,HIGH --exit-code 1 || exit 1
    # 5. osv-scanner — lock-файлы с call analysis (Go)
    - osv-scanner scan source --recursive --call-analysis=go ./src
  artifacts:
    reports:
      sast:
        - grype.sarif
    paths:
      - sbom.cdx.json
  allow_failure: false

sbom_sign:
  stage: security
  image: bitnami/cosign:2.6.0
  script:
    - cosign sign --key cosign.key $IMAGE
  only:
    - /^release-.*/
```

**Валидация:** `# → CRITICAL: 0` и exit 0 на `grype --fail-on high`; SARIF-отчёт в GitLab SAST UI.

## Лучшие практики

1. **Pin версий сканеров + SHA256.** Никогда `latest`/`0.x.x` в production. Trivy ≥ 0.70.1 (CVE-2026-33634 в 0.69.4), Syft 1.52+, Grype 0.82+, osv-scanner v2. Проверяйте checksums артефактов — см. [Лучшие практики Docker security](../../Docker/Docker_security/vulnerability_scanning.md).
2. **SBOM один раз — сканируйте много раз.** `syft` собирает manifest → `grype`/`trivy`/`osv-scanner` сопоставляют с DB. Пересканивайте SBOM по мере обновления баз, не пересобирая образ.
3. **VEX для not_affected, а не reachability-фильтры.** Если CVE `code_not_reachable`, документируйте в CycloneDX VEX и применяйте через `--vex`; это воспроизводимо и аудитируемо.
4. **EPSS/KEV для приоритизации, а не CVSS-одиночки.** `--sort-by risk` (Grype) / `snyk test` (Snyk). CVSS alone перегружает трек: Low/REACHABLE часто важнее Critical/UNREACHABLE.
5. **Fail-fast, но с allow-list.** `--fail-on high` + `ignore`-файлы; не блокируйте на каждый CVE, иначе пайплайн забьётся.
6. **Lock-файлы в CI.** `npm ci` вместо `npm install` (см. [Supply Chain атаки](./supply_chain_attack_examples.md)); `syft`/`osv-scanner` по lock-файлу для reproducibility.
7. **Air-gapped:** скачивайте DB один раз, отключайте сеть (`--skip-db-update`, `--offline`), подписывайте SBOM/VEX через `cosign` с **key-based** (Fulcio/FDO — public infra).
8. **Не сканируйте `latest`-теги образов баз.** Используйте digest pinning (`image@sha256:...`) — иначе drift базы ОС невозможно воспроизвести.

## Устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| `unknown flag: --show-vulnerability-reachability` | Флаг не существует в OSS Trivy/Grype (commercial-only) | Используйте `govulncheck` (Go), `osv-scanner --call-analysis`, либо VEX `code_not_reachable` |
| `--epss-score: unknown flag` | EPSS — не OSS-флаг Trivy | Приоритизируйте через `grype --sort-by epss/risk` или `snyk test` |
| `trivy: unknown command diff` | Подкоманда `diff` в OSS Trivy отсутствует | `diff <(jq -r '.components[].purl' a.json\|sort) <(jq -r '.components[].purl' b.json\|sort)` |
| OWASP DC 429 Too Many Requests | NVD API rate limit (без ключа) | `-DnvdApiKey=$NVD_API_KEY` или `--nvdDatafeed` (зеркало) |
| Grype: `dependency not found in SBOM` | SBOM в формате Syft 0.x, а Grype ждёт 1.x | Регенерируйте SBOM через `syft` ≥ 1.52 |
| Trivy: `no such host` в air-gapped | DB/remote cache | `--skip-db-update --db-repository file://.../trivy-db` |
| osv-scanner: V2 syntax `scan source` | V1 помечен deprecated; `osv-scanner -r` больше не работает | Используйте `osv-scanner scan source -r ./` |

## Граничные случаи и ограничения

- **Transitive depth vs. false positives.** Trivy `--pkg-relationships root,direct` сужает до прямых, но `--pkg-relationships` **не совмещается** с `--vex` и SBOM-форматами (проверено на v0.76.0: `pkg/flag/options.go` — `cannot be used with --dependency-tree, --vex or SBOM formats`).
- **Go reachability отдельна.** Ни Trivy, ни Grype OSS не делают Go call-graph; это `govulncheck`. osv-scanner v2 имеет call analysis для Go (по умолчанию) и Java.
- **Alpine distroless.** `scratch`/`gcr.io/distroless` — Trivy/Grype справляются через SBOM, но сканирование образа без pkg-менеджера требует `syft` отдельно.
- **Private registries.** Trivy/Grype/Syft требуют `--registry-username`/`--registry-password` или `DOCKER_CONFIG`; обход через `cosign`/`skopeo` + `--skip-insecure` только в dev.
- **Multi-platform образы.** `trivy image --platform linux/amd64,linux/arm64` для кросс-арх; `skopeo inspect` для digest.

## См. также

- [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — категории SCA-инструментов (2026), жизненный цикл SBOM, VEX generation.
- [Триаж CVE: практический workflow](./cve_triage_workflow.md) — модель triage (CVSS + Reachability + EPSS).
- [Уязвимости Docker-образов](./../../Docker/Docker_security/vulnerability_scanning.md) — Trivy 0.74+, Grype 0.85+, Docker Scout, Cosign.
- [Безопасный релиз в CI/CD](./../../CI-CD/DevSecOps/secure_release_pipeline.md) — фиксированные версии сканеров, проверка SHA256.
- [Сравнение инструментов DevSecOps](./../../CI-CD/DevSecOps/devsecops_tools_comparison.md) — высокоуровневая матрица SAST/DAST/SCA/IaC/ASPM.

## Источники

- Trivy: <https://github.com/aquasecurity/trivy> — все-в-одном сканер; CLI reference `trivy --help`.
- Grype: <https://github.com/anchore/grype> — сканер с `--sort-by {risk|epss|kev|severity}`, `grype explain`, `--vex`.
- Syft: <https://github.com/anchore/syft> — генератор SBOM (CycloneDX + SPDX).
- osv-scanner: <https://github.com/google/osv-scanner> — V2 (V1 deprecated); `scan source`/`scan image`, `--call-analysis`, `--licenses`, `--offline`.
- OWASP Dependency-Check: <https://github.com/DependencyCheck/DependencyCheck> — NVD-based; требует `--nvdApiKey` (v13.0).
- Snyk: <https://snyk.io> — платформа SaaS + CLI; reachability analysis (<https://docs.snyk.io/scan-fix-and-prevent/fix/prioritize-issues-for-fixing/reachability-analysis>).
