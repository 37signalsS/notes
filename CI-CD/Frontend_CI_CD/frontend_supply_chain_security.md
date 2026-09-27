**Актуально для:** npm 10+, Node.js 22 LTS, GitLab CI 16+, Syft v1.5+, Trivy v0.55+, Cosign v3.1+

# Supply Chain Security для фронтенда

## Определения

- **SBOM (Software Bill of Materials)** — машиночитаемый перечень всех зависимостей и компонентов сборки в форматах CycloneDX 1.7 или SPDX 3.0+.
- **SCA (Software Composition Analysis)** — статический анализ зависимостей на известные CVE и лицензионные риски.
- **Vulnerability Scanning** — сканирование артефакта, lock-файла или образа на уязвимости (Trivy, Grype).
- **License Compliance** — проверка лицензий зависимостей на соответствие политике проекта.
- **Automated Patching** — автоматическое создание MR с обновлением уязвимых пакетов (Renovate, Dependabot).
- **Cosign/Sigstore** — keyless-подпись артефактов и аттестаций SBOM/provenance в OCI-реестре.
- **SLSA (Supply-chain Levels for Software Artifacts)** — фреймворк оценки зрелости цепочки поставки ПО (актуальна версия v2.0).
- **Artifact Promotion** — продвижение неизменяемого артефакта между средами (dev → stage → prod) без пересборки.
- **Dependency Confusion** — атака, при которой внутреннее имя пакета перехватывается публичной версией с более высоким номером в реестре.
- **Lock-file Integrity** — гарантия, что `package-lock.json`/`pnpm-lock.yaml` не изменён между сборками без ревью.

---

## Предварительные требования

- **Node.js LTS (v22+):** версия зафиксирована в `.nvmrc` и `engines`; совпадает в CI и локально.
- **CI/CD:** GitLab CI 16+ с self-hosted раннерами, имеющими сетевую доступность до registry и Vault.
- **Сеть:** egress от раннеров к registry/Nexus/Harbor; для runtime — egress от пода к registry при необходимости.
- **Registry:** внутренний npm-реестр (GitLab Package Registry, Nexus, Verdaccio) или доверенный публичный registry с контрольными суммами.
- **Секреты:** CI/CD Variables для registry tokens; долгоживущие токены должны храниться в Vault, а не в проекте.
- **Артефакты:** хранилище CI артефактов с retention policy (минимум 5–10 релизов для отката).
- **Документация:** общие принципы SBOM и подписи описаны в **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)**; этот файл фокусируется на фронтенд-специфике.

---

## Основные концепции

### Угрозы фронтенд-цепочки

Фронтенд-пайплайн уязвим на специфических уровнях:
1. **Зависимости npm:** вредоносный или уязвимый пакет попадает в `node_modules` через Typosquatting, compromised account или Dependency Confusion.
2. **Сборка:** compromised раннер или toolchain внедряет backdoor в бандл.
3. **Артефакт:** подмена `dist/` при передаче между раннерами или в registry.
4. **Реестр:** атака на registry, отравление кэша или загрузка старого уязвимого образа.
5. **Деплой:** деплой артефакта без проверки подписи/целостности.

### Почему обычного `npm audit` недостаточно

`npm audit` проверяет только базу CVE npm и часто даёт false positives. Production-grade стратегия включает:
- **Pre-build:** `npm audit`, `license-checker`, Renovate/Dependabot.
- **Build:** воспроизводимая сборка (`npm ci`), lock-file integrity, SBOM generation (`syft`).
- **Scan:** Trivy/Grype на артефакт и lock-файл.
- **Sign:** Cosign подпись + аттестация SBOM/provenance.
- **Deploy:** проверка подписи перед деплоем, retention policies.

### Build-time секреты фронтенда

Секреты, необходимые только на этапе сборки:
- **npm registry token:** доступ к приватным пакетам; должен жить только во время `npm ci`.
- **GPG/Cosign ключ:** подпись артефактов; передаётся через Vault и никогда не попадает в слой образа или артефакт.
- **CDN origin token:** загрузка артефактов в origin-хранилище remote.

Принцип: build-time секреты запрашиваются через Vault в момент выполнения шага и не передаются между этапами пайплайна.

### Разделение артефактов по окружениям

- **Preview/MR:** изолированные артефакты от production; retention 1–7 дней.
- **Production:** артефакты с максимальным TTL, отдельная политика, аудит каждого чтения.
- **Static/SSG:** если секреты не нужны в рантайме — исключить их из билда полностью.

### Воспроизводимость и детерминизм

Фронтенд-сборка должна быть детерминированной:
- `npm ci` (а не `npm install`) гарантирует идентичный набор зависимостей.
- Lock-файл проверяется на целостность (хеш в CI Variables или git commit).
- Сборка изолируется в контейнере с фиксированной версией Node.js.

---

## Практические сценарии

### Сценарий 1: Pre-build аудит зависимостей + Renovate

```yaml
# .gitlab-ci.yml
dependency_scan:
  stage: test
  image: node:22-bookworm
  cache:
    key:
      files:
        - package-lock.json
      prefix: "deps-$CI_JOB_NAME"
    paths:
      - node_modules/
    policy: pull-push
  script:
    - npm ci --ignore-scripts
    - npm audit --audit-level=high --json > npm-audit.json
    - npx license-checker --json --onlyAllow "MIT;Apache-2.0;BSD-3-Clause" || exit 1
  artifacts:
    reports:
      dependency_scanning: npm-audit.json
    expire_in: 1 week
```

```json
// renovate.json
{
  "extends": ["config:base"],
  "packageRules": [
    {
      "matchUpdateTypes": ["minor", "patch"],
      "groupName": "frontend dependencies",
      "automerge": true,
      "automergeType": "branch"
    },
    {
      "matchDepTypes": ["devDependencies"],
      "matchBaseBranches": ["main"],
      "automerge": false
    }
  ],
  "schedule": ["before 6am on Monday"],
  "timezone": "Europe/Moscow"
}
```

```yaml
# .gitlab-ci.yml — Renovate runner
renovate:
  stage: .pre
  image: renovate/renovate:latest
  variables:
    RENOVATE_TOKEN: $CI_JOB_TOKEN
    RENOVATE_GIT_AUTHOR: "Renovate Bot <bot@example.com>"
  script:
    - renovate --platform=gitlab --endpoint=$CI_API_V4_URL
```

**Валидация:**
- `npm audit --audit-level=high` завершается с `0` vulnerabilities high/critical.
- `license-checker` возвращает exit code 0; forbidden licenses отсутствуют.
- Renovate открывает MR с обновлениями; schedule работает, merge policy настроен.

**Troubleshooting:**
- *npm audit блокирует каждый MR:* группируйте patch/minor обновления через Renovate; для legacy-зависимостей используйте `npm audit ignore` с обоснованием.
- *Renovate не открывает MR:* проверьте `RENOVATE_TOKEN` и `platform=gitlab`; убедитесь, что runner имеет доступ к API.
- *License checker блокирует devDependencies:* разделите allowlist на production и dev.

### Сценарий 2: SBOM generation + Trivy scan

```bash
# 1. Сборка артефакта
npm ci && npm run build

# 2. SBOM (CycloneDX)
syft dir:. -o cyclonedx-json > sbom.cdx.json

# 3. Trivy scan файловой системы
trivy fs --format cyclonedx --output trivy-report.cdx.json .

# 4. Trivy scan артефакта (если используется)
trivy fs --severity CRITICAL,HIGH --exit-code 1 .
```

**Валидация:**
- `sbom.cdx.json` содержит все production зависимости; инкрементальный SBOM совпадает с полным.
- `trivy fs` возвращает `0` CRITICAL/HIGH уязвимостей.

**Troubleshooting:**
- *Trivy падает на monorepo:* сканируйте только changed workspace, кэшируйте результаты.
- *SBOM устарел:* генерируйте SBOM на каждом build артефакте, а не только на main.
- *Долгий scan на CI:* используйте incremental scan и кэширование trivy-db.

### Сценарий 3: Cosign подпись артефакта

```bash
# Подпись артефакта
cosign sign --yes "registry.example.com/frontend:${CI_COMMIT_SHORT_SHA}"

# Аттестация SBOM
cosign attest --predicate sbom.cdx.json --type cyclonedx \
  "registry.example.com/frontend:${CI_COMMIT_SHORT_SHA}"

# Верификация перед деплоем
cosign verify --certificate-identity-regexp '^https://gitlab\.com/org/frontend' \
  --certificate-oidc-issuer https://gitlab.com \
  "registry.example.com/frontend:${CI_COMMIT_SHORT_SHA}"
```

**Валидация:**
- `cosign verify` проходит для всех production-артефактов.
- SBOM аттестация прикреплена к образу; видна в registry.

**Troubleshooting:**
- *Cosign verify не проходит:* проверьте identity regex и issuer; убедитесь, что реестр поддерживает Referrers API.
- *Аттестация не прикрепляется:* обновите cosign до v3.1+ и убедитесь, что registry поддерживает OCI 1.1.

### Сценарий 4: Rotate npm registry token через Vault

```bash
# 1. Ротация токена в Vault
vault write -force secret/data/frontend/production/npm-token

# 2. Обновление CI/CD Variable (GitLab)
curl -X POST "$VAULT_ADDR/v1/auth/jwt/login" \
  -H "Authorization: Bearer $JWT" \
  -d '{"role":"ci-frontend"}' | jq -r '.auth.client_token'
```

**Валидация:**
- Старый токен возвращает `401` после ротации.
- Новый токен работает; пайплайн не имеет доступа к старому.

**Troubleshooting:**
- *Ротация ломает сборку:* npm кэширует токен — используйте `npm logout` перед новой аутентификацией.
- *Токен в логе CI:* отключите `--loglevel verbose` или используйте `npm_config_` префикс.

### Сценарий 5: GitLab Dependency Scanning integration

```yaml
# Встроенный GitLab Dependency Scanning
include:
  - template: Dependency-Scanning.gitlab-ci.yml

dependency_scanning:
  variables:
    DS_EXCLUDE_PATHS: "test/,docs/"
  allow_failure: false
```

**Валидация:**
- Отчёт Dependency Scanning генерируется на каждый MR.
- Критические уязвимости блокируют мерж.

**Troubleshooting:**
- *Сканирование падает на monorepo:* исключите нерелевантные пути через `DS_EXCLUDE_PATHS`.
- *False positives:* используйте `DS_EXCLUDE_PATHS` и `.gitlab/dependency_scanning/allowlist.yaml`.

---

## Операционные команды

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `npm audit --audit-level=high` | Аудит зависимостей | # → exit code 0 при отсутствии high/critical уязвимостей |
| `npx license-checker --json` | Аудит лицензий | # → JSON-отчёт; exit code 0 при разрешённых лицензиях |
| `syft dir:. -o cyclonedx-json > sbom.json` | Генерация SBOM | # → файл `sbom.json` со всеми зависимостями |
| `trivy fs --severity CRITICAL,HIGH --exit-code 1 .` | Сканирование fs | # → exit code 0 при отсутствии критических уязвимостей |
| `trivy image frontend:${CI_COMMIT_SHORT_SHA}` | Сканирование образа | # → отчёт уязвимостей |
| `cosign sign --yes registry.example.com/frontend:tag` | Подпись образа | # → подтверждение подписи |
| `cosign verify --identity ... registry.example.com/frontend:tag` | Верификация подписи | # → Verification succeeded |
| `cosign attest --predicate sbom.json --type cyclonedx ...` | Аттестация SBOM | # → SBOM прикреплён к образу |
| `vault read secret/data/frontend/production/npm-token` | Чтение npm-токена | # → значение токена (только в CI) |
| `vault write -force secret/data/frontend/production/npm-token` | Ротация npm-токена | # → новое значение токена |

---

## Валидация

- **npm audit:** `npm audit --audit-level=high` завершается с `0` vulnerabilities high/critical.
- **License checker:** все зависимости разрешённых лицензий; forbidden licenses — блокируют пайплайн.
- **Renovate:** открывает MR с обновлениями; schedule работает, merge policy настроен.
- **Trivy:** `trivy fs` и `trivy image` возвращают `0` CRITICAL/HIGH уязвимостей.
- **Cosign:** `cosign verify` проходит для всех production-артефактов.
- **SBOM:** файл содержит все production зависимости; генерируется на каждый build.
- **Reproducibility:** `npm ci` с одинаковым lock-файлом даёт идентичный `dist/` на разных раннерах.
- **Rotation:** после `vault write -force` новый токен работает, старый — `401`.

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| npm audit блокирует каждый MR | Древние transitive зависимости | Renovate с группировкой minor/patch |
| Renovate не открывает MR | Нет `RENOVATE_TOKEN` или неправильный endpoint | Проверить CI_JOB_TOKEN и platform=gitlab |
| Trivy падает на monorepo | Слишком много lock-файлов | Сканировать только changed workspace, кэшировать результаты |
| Cosign verify не проходит | Реестр не поддерживает Referrers API | Включить referrers в Harbor, обновить cosign |
| SBOM устарел | Генерируется только на main | Генерировать SBOM на каждом build артефакте |
| License checker блокирует devDependencies | Слишком строгий allowlist | Разделить production/dev allowlists |
| Долгий scan на CI | Полный scan monorepo на каждый PR | Incremental scan, кэширование trivy-db, only changed packages |
| Уязвимость в transitive dep | Нет fix от upstream | Use `overrides`/`resolutions` + Renovate PR; monitor CVE |
| Невоспроизводимая сборка | Разные Node.js версии или `npm install` вместо `npm ci` | Фиксировать Node.js в `.nvmrc`, всегда `npm ci` |
| Секрет в npm registry | Leaked token в логе | Masked variables, BuildKit secrets |

---

## Инцидент: compromised npm dependency

1. **Немедленный отзыв:** отозвать скомпрометированный токен registry в панели управления.
2. **Ротация:** сгенерировать новые учетные данные в Vault.
3. **Аудит:** проверить Vault Audit Logs и логи CI на предмет подозрительной активности.
4. **Очистка:** удалить скомпрометированную версию пакета из registry; опубликовать исправление.
5. **Постмортем:** blameless postmortem, обновление политик доступа и правил сканеров.

Полный runbook — в **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/supply_chain_incident_response.md)**.

---

## Лучшие практики

1. Используйте `npm ci` (а не `npm install`) для детерминированной сборки.
2. Включайте `npm audit --audit-level=high` в каждый MR; critical — блокируют мерж.
3. Настройте Renovate с automerge для patch/minor и manual review для major.
4. Генерируйте SBOM (`syft`) на каждом build и храните как артефакт.
5. Сканируйте артефакт Trivy/Grype перед push в registry.
6. Подписывайте production-артефакты Cosign; проверяйте подпись перед деплоем.
7. Разделяйте allowlist лицензий для production и devDependencies.
8. Для monorepo используйте incremental SBOM и кэширование Trivy DB.
9. Храните registry tokens в Vault с TTL, а не в CI/CD Variables без истечения.
10. Для preview-окружений используйте отдельные registry namespace с retention 1–7 дней.

---

## Дополнительная информация

### См. также

- **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)** — общие концепции SLSA, SBOM, threat model.
- **[Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)** — Cosign, Notation, VSA и проверка подписей.
- **[Управление артефактами](../artifact_management.md)** — жизненный цикл артефактов, immutability, retention policies, promotion между средами.
