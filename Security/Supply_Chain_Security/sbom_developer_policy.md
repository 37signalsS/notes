# SBOM-политика для разработчиков

**Актуально для:** CycloneDX 1.7, Syft v1.54+, Trivy ≥ 0.71.0, VEX (CycloneDX 1.7), GitLab CI 16+

## Определения

* **SBOM-политика (SBOM Policy):** Набор правил и требований, определяющих, как команды разработки создают, поддерживают и используют Software Bill of Materials на всех этапах жизненного цикла ПО. Включает формат, обязательные поля, процесс обновления и ответственность.
* **RACI-матрица:** Модель распределения ответственности: **R**esponsible (исполнитель), **A**ccountable (ответственный), **C**onsulted (консультант), **I**nformed (информированный). Применяется для определения, кто создаёт, кто проверяет, кто использует SBOM.
* **SBOM Quality Gate:** Набор автоматических проверок SBOM в CI/CD, которые должны быть пройдены перед допуском к деплою. Включает: наличие обязательных полей, корректность PURL, отсутствие критичных CVE.
* **Living SBOM:** Динамический граф зависимостей, непрерывно обогащаемый данными об уязвимостях (VEX) и их статусе. Заменяет статический «снимок» SBOM. См. также: [SBOM в продакшене](./sbom_in_production.md#определения).

## Основные концепции

### RACI-матрица для SBOM

| Активность | Разработчик | Tech Lead | Security | DevOps/SRE |
| :--- | :--- | :--- | :--- | :--- |
| Генерация SBOM при сборке | I | A | C | R |
| Заполнение обязательных полей | R | A | I | I |
| Проверка SBOM на CVE | I | I | R | A |
| Создание VEX-отчета | R | A | C | I |
| Обновление зависимостей | R | A | I | I |
| Верификация SBOM перед деплоем | I | I | I | R |
| Аудит SBOM в продакшене | I | I | R | A |
| Решение по risk acceptance | I | C | R | A |

### Обязательные поля SBOM (CycloneDX)

```json
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.7",
  "version": 1,
  "metadata": {
    "timestamp": "2026-09-21T10:00:00Z",
    "tools": [{"vendor": "anchore", "name": "syft", "version": "1.54.0"}],
    "component": {
      "type": "application",
      "name": "my-app",
      "version": "1.2.3",
      "bom-ref": "my-app-1.2.3"
    }
  },
  "components": [
    {
      "type": "library",
      "name": "requests",
      "version": "2.31.0",
      "purl": "pkg:pypi/requests@2.31.0",
      "scope": "required",
      "licenses": [{"license": {"id": "Apache-2.0"}}],
      "hashes": [
        {"alg": "SHA-256", "value": "abcdef1234567890..."}
      ]
    }
  ]
}
```

**Обязательные поля:**
- `bomFormat` — всегда `CycloneDX`
- `specVersion` — `1.7`
- `components[].name` — имя компонента
- `components[].version` — точная версия (без диапазонов)
- `components[].purl` — Package URL
- `components[].scope` — `required` или `optional`
- `metadata.timestamp` — время генерации

> **Примечание:** Поля `licenses` и `hashes` (см. пример выше) не являются обязательными по спецификации CycloneDX 1.7, но рекомендуются для production-потребления и комплаенса. Подробнее — в [Структура SBOM](./sbom_in_production.md#структура-sbom-cyclonedx-17).

### Source Track и EU CRA: обязанности разработчика

В 2026 году требования SLSA Source Track и EU CRA делают разработчика ответственным за целостность исходного кода — не только за правильность SBOM. Source Track защищает «голову» цепочки поставок: процесс создания и изменения исходного кода.

**Source Track (SLSA v1.2) — обязанности разработчика:**

* **Source L3 — Подпись коммитов:** Все коммиты в защищённую ветку (`main`) должны быть подписаны SSH-ключом или GPG-ключом. Это гарантирует, что изменения внесены авторизованным разработчиком и не были подменены.
  ```bash
  # Включение подписи коммитов через SSH-ключ (рекомендуется для GitLab)
  git config gpg.format ssh
  git config user.signingkey ~/.ssh/id_ed25519.pub
  git config commit.gpgsign true
  
  # Проверка подписи коммита
  git log --show-signature -1
  # → gpg: Signature made Sun Oct 18 ...
  # → gpg:                using SSH key <KEY_ID>
  ```

* **Source L4 — Two-party review:** Все изменения в критических зависимостях и конфигурационных файлах требуют двух независимых одобрений (MR approval) и верифицированную идентичность автора. В GitLab: `Settings → Merge requests → Merge request approvals → Minimum number of approvals = 2`.

* **EU CRA (Article 14):** Производители обязаны уведомлять ENISA CRA Single Reporting Platform об эксплуатируемых уязвимостях. Разработчики участвуют в triage и генерируют VEX-отчёты для каждого reachable CVE. См. также: [Триаж CVE](./cve_triage_workflow.md).

> **Связь с SBOM:** Source Provenance (аттестация источника) и SBOM-аттестация генерируются на одном этапе сборки и обе прикрепляются к образу через OCI 1.1 Referrers API. Это обеспечивает сквозную прослеживаемость от коммита до production-образа. Подробнее — в [Целостности сборки](./build_integrity.md).

### Процесс работы разработчика

```
Добавление зависимости в проект
    │
    ├── 0. Подпись кода (Source L3/L4)
    │       ├── Коммит подписан (git commit -S)
    │       └── Защита ветки main (two-party review)
    │
    ├── 1. Выбор пакета
    │       ├── Проверка лицензии (SBOM license field)
    │       ├── Проверка CVE (SCA-сканер)
    │       └── Проверка последнего релиза (активность maintainer)
    │
    ├── 2. Установка с фиксацией
    │       ├── npm install <package> → коммит package-lock.json
    │       ├── pip install <package> → коммит requirements.txt + hashes
    │       └── go get <package> → коммит go.sum
    │
    ├── 3. Верификация SBOM
    │       ├── CI автоматически генерирует SBOM
    │       └── Проверка: все компоненты присутствуют, CVE отсутствуют
    │
    └── 4. VEX (при необходимости)
            ├── Если CVE есть, но unreachable → VEX not_affected
            └── Коммит VEX-отчета в репозиторий
```

## Предварительные требования

### Инструменты и версии

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Syft** | v1.54+ | Генерация SBOM в формате CycloneDX 1.7 |
| **Trivy** | ≥ 0.71.0 | Сканирование SBOM на CVE, VEX-фильтрация (v0.70.x не поддерживает CycloneDX 1.7 SBOM; v0.69.4 исключён из-за CVE-2026-33634) |
| **cdxgen** | 1.5+ | Генерация CycloneDX для языков, не покрытых Syft |
| **GitLab CI** | 16+ | CI/CD-пайплайн с поддержкой `id_tokens` для OIDC (GitLab Server ≥ 15.7) |
| **Harbor** | v2.15+ | OCI-реестр с поддержкой OCI 1.1 Referrers API |
| **Kyverno** | v1.19+ | Admission-контроль для верификации подписей SBOM |
| **jq** | 1.7+ | Валидация JSON-структуры SBOM |
| **skopeo** | 1.14+ | Инспекция OCI-образов и извлечение digest для Referrers API |

### Аппаратные требования

* CPU с поддержкой AES-NI для ускорения криптографических операций.
* Минимум 4 ГБ ОЗУ на CI/CD-раннере.
* Доступ к внутреннему реестру (Harbor) и git-серверу (GitLab/Gitea).

### Начальное состояние окружения

* Создан проект в GitLab с включённым CI/CD.
* Настроен robot-аккаунт Harbor с правами `push` в целевой проект.
* Доступен внутренний DNS, разрешающий `harbor.internal` и `gitlab.internal`.
* Для keyless-подписи: настроен OIDC (GitLab Server ≥ 15.7) с `id_tokens` в `.gitlab-ci.yml`.
* Защищённая ветка `main` с обязательной подписью коммитов (Source L3) и two-party review (Source L4).

## Практические сценарии

### Сценарий 1: Checklist для разработчика при добавлении зависимости

```markdown
## Checklist: Новая зависимость

- [ ] Пакет из доверенного источника (npm, PyPI, Go modules)
- [ ] Лицензия совместима с проектом (MIT, Apache-2.0, BSD)
- [ ] Активно поддерживается (последний релиз < 6 месяцев)
- [ ] Нет известных CRITICAL/HIGH CVE
- [ ] Версия зафиксирована (lock-файл обновлён)
- [ ] SBOM обновлён автоматически (CI)
- [ ] Если CVE — создан VEX-отчет
- [ ] Коммит подписан (Source L3)
```

### Сценарий 2: CI-quality gate для SBOM

```yaml
# GitLab CI: проверка SBOM перед деплоем
sbom-quality-gate:
  stage: verify
  image: aquasec/trivy:0.71.0
  script:
    - apk add --no-cache jq
    # 1. Проверка формата
    - jq -e '.bomFormat == "CycloneDX"' sbom.json || { echo "ERROR: Invalid format"; exit 1; }
    - jq -e '.specVersion == "1.7"' sbom.json || { echo "ERROR: Invalid spec version"; exit 1; }
    
    # 2. Проверка обязательных полей
    - MISSING=$(jq '[.components[] | select(.purl == null or .version == null)] | length' sbom.json)
    - '[ "$MISSING" -eq 0 ] || { echo "ERROR: $MISSING components missing purl/version"; exit 1; }'
    
    # 3. Проверка на критичные CVE
    - trivy sbom --severity CRITICAL --exit-code 1 sbom.json
    # → ERROR: 1 vulnerability found: CVE-2024-1234
    
    # 4. Количество компонентов (для детекции аномалий)
    - COUNT=$(jq '.components | length' sbom.json)
    - echo "SBOM contains $COUNT components"
    # → SBOM contains 142 components
  artifacts:
    paths:
      - sbom.json
```

### Сценарий 3: VEX-шаблон для разработчика

```json
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.7",
  "version": 1,
  "vulnerabilities": [
    {
      "id": "CVE-2024-EXAMPLE",
      "source": {"name": "NVD"},
      "status": "not_affected",
      "justification": "vulnerable_code_not_present",
      "detail": "Библиотека установлена, но уязвимый модуль не используется в приложении. Reachability: UNREACHABLE."
    }
  ]
}
```

**Статусы VEX:**
- `not_affected` — уязвимый код не присутствует в продукте
- `affected` — уязвимость присутствует, fix planned
- `fixed` — уязвимость исправлена в указанной версии
- `under_investigation` — анализ продолжается

**Значения `justification` (для статуса `not_affected`):**
- `not_imported` — уязвимый модуль не импортируется
- `not_executed` — модуль импортирован, но уязвимая функция не вызывается
- `not_accessible` — функция вызывается, но недоступна извне
- `vulnerable_code_not_present` — уязвимый код отсутствует в продукте
- `component_not_present` — компонент не входит в продукт
- `component_unreachable` — компонент недостижим из production-контекста

### Сценарий 4: Автоматическое уведомление при новой CVE

```yaml
# GitLab CI: ежедневная проверка CVE в зависимостях
daily-cve-check:
  stage: security
  image: aquasec/trivy:0.71.0
  script:
    - trivy fs --severity CRITICAL,HIGH --format json --output daily-cve-report.json .
    - CRITICAL=$(jq '[.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' daily-cve-report.json)
    # → 1 (CVE-2024-1234 в libssh)
    - |
      if [ "$CRITICAL" -gt 0 ]; then
        echo "CRITICAL CVEs found — creating issue"
        # Сбор списка уязвимостей для описания тикета
        VULN_LIST=$(jq -r '.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL") | "- \(.VulnerabilityID): \(.PkgName) \(.InstalledVersion)"' daily-cve-report.json)
        # Создание тикета в GitLab Issues
        curl -X POST "$CI_API_V4_URL/projects/$CI_PROJECT_ID/issues" \
          -H "PRIVATE-TOKEN: $GITLAB_ACCESS_TOKEN" \
          -d "title=[SECURITY] Critical CVEs detected" \
          --data-urlencode "description=$VULN_LIST"
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### Сценарий 5: DevOps/SRE — проверка SBOM перед деплоем (Admission Control)

DevOps/SRE потребляют SBOM, сгенерированный разработчиком, при деплое в production. Это второй этап quality gate, дополняющий проверку на этапе сборки.

```bash
# 1. Проверка наличия SBOM-аттестации в реестре (Referrers API)
SBOM_DIGEST=$(skopeo inspect docker://harbor.internal/my-app:v1.2.3 --format '{{.Digest}}' | cut -d: -f2)
curl -u "robot$ci-bot:$ROBOT_SECRET" \
  "https://harbor.internal/v2/my-app/manifests/sha256:${SBOM_DIGEST}/referrers"
# → {"manifest":{"layers":[{"mediaType":"application/vnd.cyclonedx.bom.v1+json",...}]}}

# 2. Сканирование SBOM на CVE с VEX-фильтрацией
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json > sbom-deploy.json
trivy sbom --vex vex-report.json sbom-deploy.json --severity CRITICAL
# → 0 vulnerabilities (VEX not_affected applied)

# 3. Автоматический алерт при обнаружении новых CRITICAL CVE
# (через Prometheus/Alertmanager, интегрированный с GUAC)
curl -s -X POST "http://alertmanager:9093/api/v1/alerts" \
  -H 'Content-Type: application/json' \
  -d '[{"labels":{"alertname":"NewCVE","severity":"critical"},"annotations":{"summary":"Critical CVE detected in production"}}]'
```

**Валидация:** SBOM-аттестация присутствует в реестре, VEX корректно исключает `not_affected` CVE, алерт отправляется при обнаружении новых уязвимостей. См. также: [SBOM в продакшене](./sbom_in_production.md).

### Сценарий 6: Sysadmin — управление инфраструктурой SBOM

Sysadmin обеспечивает работоспособность и безопасность инфраструктуры, на которой работает SBOM-конвейер.

```bash
# 1. Ротация ключей подписи SBOM (раз в 90 дней)
# Проверка срока действия Fulcio CA-сертификата
openssl x509 -in /etc/sigstore/fulcio-ca.crt -noout -dates
# → notBefore=Sep  1 00:00:00 2026 GMT
# → notAfter=Oct  1 23:59:59 2027 GMT

# 2. Обновление локальной базы Trivy DB для air-gapped сред
# На машине с интернетом:
trivy image --download-db-only --db-repository ghcr.io/aquasecurity/trivy-db
# Перенос DB на air-gapped машину через data diode:
scp trivy.db sysadmin@airgapped-host:/var/lib/trivy/

# 3. Настройка политики retention в Harbor (очистка старых SBOM-артефактов)
curl -u "admin:$HARBOR_ADMIN_PASS" -X POST \
  "https://harbor.internal/api/v2.0/projects/my-app/retentions" \
  -H "Content-Type: application/json" \
  -d '{
    "algorithm": "latestN",
    "tagSelectors": [{"kind":"regular","decoration":"","pattern":"**"}],
    "scope": {"kind":"lastX","value":"30"},
    "trigger": "daily"
  }'
# → 201 Created

# 4. Мониторинг свежести SBOM через Prometheus
# Метрика: время последней генерации SBOM для каждого сервиса
cat <<'EOF' > /etc/prometheus/rules/sbom_rules.yml
groups:
- name: sbom.rules
  rules:
  - alert: SBOMStale
    expr: time() - sbom_timestamp_seconds > 86400
    for: 1h
    labels:
      severity: warning
    annotations:
      summary: "SBOM для сервиса {{ $labels.service }} устарел более 24 часов"
      description: "Свежий SBOM не генерировался более 24 часов. Проверьте CI/CD пайплайн."
EOF

# 5. Аудит всех подписанных SBOM в реестре
for img in $(curl -s -u "robot$ci-bot:$ROBOT_SECRET" \
  "https://harbor.internal/api/v2.0/projects/my-app/repositories" | jq -r '.[].name'); do
  curl -s -u "robot$ci-bot:$ROBOT_SECRET" \
    "https://harbor.internal/v2/my-app/manifests/sha256:$(skopeo inspect docker://harbor.internal/$img:latest --format '{{.Digest}}' | cut -d: -f2)/referrers" | \
    jq -r '.manifest.layers[] | select(.mediaType=="application/vnd.cyclonedx.bom.v1+json") | "SBOM found for: \(input_filename)"' 2>/dev/null || echo "SBOM MISSING for: $img"
done
```

**Валидация:** Ключи ротируются согласно графику (90 дней), Trivy DB синхронизируется в air-gapped средах, Harbor retention политика работает, мониторинг SBOM активен.

## Валидация внедрения

После настройки выполните комплексную проверку всех компонентов:

```bash
# 1. Проверка: CI генерирует SBOM в CycloneDX 1.7
curl -u "robot$ci-bot:$ROBOT_SECRET" \
  "https://harbor.internal/v2/my-app/manifests/sha256:<DIGEST>/referrers"
# → {"manifest":{"layers":[{"mediaType":"application/vnd.cyclonedx.bom.v1+json",...}]}}

# 2. Проверка: quality gate блокирует образ с CRITICAL CVE
trivy sbom sbom.json --severity CRITICAL --exit-code 1
# → ERROR: 1 vulnerability found: CVE-2024-EXAMPLE

# 3. Проверка: VEX корректно исключает CVE
trivy sbom --vex vex-report.json sbom.json --severity CRITICAL | grep -c "CVE-2024-EXAMPLE"
# → 0 (CVE исключена через VEX not_affected)

# 4. Проверка: все компоненты имеют обязательные поля
jq '[.components[] | select(.purl == null or .version == null)] | length' sbom.json
# → 0

# 5. Проверка: lock-файл синхронизирован с SBOM
npm ls --json > /dev/null 2>&1 && echo "OK" || echo "OUT OF SYNC"
# → OK

# 6. Проверка: коммит подписан (Source L3)
git log --show-signature -1 | grep "Good signature"
# → gpg: Good signature from <author>

# 7. Проверка: двухфакторное одобрение MR включено (Source L4)
curl -s "$CI_API_V4_URL/projects/$CI_PROJECT_ID" -H "PRIVATE-TOKEN: $GITLAB_ACCESS_TOKEN" | \
  jq '.merge_requests_author_approval_enabled'
# → true
```

## Очистка

```bash
# 1. Удаление SBOM-артефакта из Harbor (через Referrers API)
curl -u "robot$ci-bot:$ROBOT_SECRET" -X DELETE \
  "https://harbor.internal/api/v2.0/projects/my-app/repositories/my-app/artifacts/sha256:<SBOM_DIGEST>"
# → 200 OK

# 2. Отзыв VEX-отчёта (удаление из репозитория)
git rm vex-report.json
git commit -m "Remove VEX report for CVE-2024-EXAMPLE (not_affected → resolved)"

# 3. Очистка временных артефактов CI/CD
rm -f sbom.json daily-cve-report.json vex-report.json

# 4. Отключение daily-cve-check pipeline (удаление расписания через API)
curl -X DELETE "$CI_API_V4_URL/projects/$CI_PROJECT_ID/pipeline_schedules/$SCHEDULE_ID" \
  -H "PRIVATE-TOKEN: $GITLAB_ACCESS_TOKEN"
# → 204 No Content

# 5. Очистка старых артефактов в Harbor через retention job
curl -u "admin:$HARBOR_ADMIN_PASS" -X POST \
  "https://harbor.internal/api/v2.0/tasks" \
  -H "Content-Type: application/json" \
  -d '{"type":"RETENTION","params":{"retention_id":1}}'
```

## Лучшие практики

1. **SBOM — часть Definition of Done:** Без SBOM нет релиза. Это автоматизированная проверка в CI.
2. **Lock-файлы в Git:** Все lock-файлы коммитятся. Без них SBOM некорректен.
3. **VEX для каждого false positive:** Если CVE не эксплуатируется — создавайте VEX и коммитьте. Это документирует решение.
4. **Ежедневный CVE-check:** Автоматический сканер проверяет зависимости и создаёт тикеты при обнаружении критичных CVE.
5. **Обзор SBOM quarterly:** Security-команда проводит ежеквартальный аудит SBOM: удаление неиспользуемых зависимостей, обновление устаревших.
6. **Шаблоны VEX:** Используйте стандартные шаблоны VEX для типичных ситуаций (unreachable, not_present, mitigated).
7. **Подпись коммитов (Source L3):** Все коммиты в защищённую ветку должны быть подписаны. Это предотвращает подмену исходного кода.
8. **Two-party review (Source L4):** Критические изменения требуют двух одобрений.
9. **Ротация ключей каждые 90 дней:** Регулярно ротируйте ключи подписи SBOM и Fulcio CA-сертификаты.
10. **Мониторинг свежести SBOM:** Настройте алерты при задержке генерации SBOM более 24 часов (см. Сценарий 6).
11. **Digest-pinning:** Никогда не используйте теги `latest` или `v1` в production. Фиксируйте образы по digest.
12. **Эфемерные среды:** Каждая сборка выполняется в чистом контейнере/ВМ с `--network=none` для предотвращения подмены пакетов.

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| SBOM не содержит нового компонента | CI не генерирует SBOM для нового языка | `syft dir:. -o cyclonedx-json \| jq '.components \| length'` | Используйте `cdxgen` как fallback для неподдерживаемых языков |
| Разработчик добавил CVE | Нет quality gate | `trivy sbom sbom.json --severity CRITICAL` | Включите `trivy sbom --severity CRITICAL --exit-code 1` в CI |
| VEX не применяется | Неверный формат VEX или отсутствие полей `status` | `cat vex-report.json \| jq .` | Используйте CycloneDX 1.7 VEX с обязательными полями `bomFormat`, `specVersion`, `vulnerabilities[].status` |
| SBOM слишком большой | Слишком много транзитивных зависимостей | `jq '.components \| length' sbom.json` | Аудит: удалите неиспользуемые компоненты через `jq` или используйте `--exclude-type` в Syft |
| SBOM содержит уязвимый компонент | Новая CVE в базе Trivy | `trivy sbom --vex vex.json sbom.json --severity CRITICAL,HIGH` | Создайте VEX с `not_affected` + `vulnerable_code_not_present`, или обновите зависимость |
| Quality gate падает в CI | `jq` не установлен или sbom.json отсутствует | `docker run syft:v1.54.0 ls sbom.json` | Убедитесь, что SBOM генерируется до quality gate; используйте `dependencies:` в GitLab CI |
| VEX не исключает CVE | Статус VEX не `not_affected` или `justification` неверен | `cat vex.json \| jq '.vulnerabilities[].status'` | Исправьте статус на `not_affected` с `justification: "vulnerable_code_not_present"` |
| Lock-файл не синхронизирован | Зависимости обновлены без обновления lock-файла | `npm ls --json > /dev/null 2>&1 && echo "OK" || echo "OUT OF SYNC"` | Закоммитьте lock-файл перед сборкой; используйте `npm ci` вместо `npm install` |
| Trivy не распознаёт CycloneDX 1.7 | Версия Trivy < 0.71.0 | `trivy --version` | Обновите Trivy до ≥ 0.71.0 (поддержка 1.7 добавлена в v0.71.0, #10184) |
| SBOM устарел в Harbor | Retention policy не удаляет старые версии | `curl -s harbor.internal/api/v2.0/projects/my-app/artifacts` | Проверьте конфигурацию retention policy (см. Сценарий 6) |
| Reachability для non-Go языков | govulncheck поддерживает только Go | `govulncheck ./...` → работает только для Go | Используйте `osv-scanner --call-analysis` для Java/Python/JS или VEX `not_affected` |
| Подпись коммита не проверяется | Git не настроен на подпись | `git log --show-signature -1` | Включите `git config commit.gpgsign true` и настройте SSH/GPG ключ |
| Key rotation пропущен | 90-дневный график не автоматизирован | `openssl x509 -in fulcio-ca.crt -noout -enddate` | Автоматизируйте ротацию через cron + уведомление 7 дней до истечения |

## Граничные случаи и ограничения

* **Mono-repo:** В монорепозитории SBOM генерируется для каждого сервиса. Общий SBOM не отражает изоляцию.
* **Проприетарные библиотеки:** Внутренние библиотеки должны быть в SBOM с корректным PURL.
* **Динамические зависимости:** SBOM фиксирует зависимости на этапе сборки. Runtime drift — отдельная тема (см. [Runtime drift detection](./runtime_drift_detection.md)).
* **Частые релизы:** При ежедневных релизах SBOM обновляется автоматически. Процесс не должен замедлять delivery.
* **Air-gapped среды:** Отсутствие доступа к базам CVE требует локального зеркала Trivy DB и использования `--skip-db-update` (см. Сценарий 6).
* **Multi-architecture образы:** SBOM и аттестации должны генерироваться для каждого архитектурного варианта (`linux/amd64`, `linux/arm64`) отдельно. Используйте `docker buildx imagetools inspect` для просмотра constituent-манифестов.
* **Квантовые угрозы (HNDL):** SBOM подписи должен использовать двойную подпись (ECDSA + ML-DSA через KMS) для защиты от атак "собери сейчас, расшифруй позже" (Harvest Now, Decrypt Later). См. также: [Подпись артефактов](./build_integrity.md).

## Дополнительная информация

### Связанные документы

* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM, blast radius, VEX.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX, инструменты.
* [Целостность сборки](./build_integrity.md) — SLSA и интеграция SBOM в пайплайн.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз, SLSA v1.2, EU CRA.
* [Триаж CVE](./cve_triage_workflow.md) — процесс классификации и приоритизации CVE.
* [Runtime drift detection](./runtime_drift_detection.md) — обнаружение расхождений SBOM в рантайме.
* [Подпись артефактов](./artifact_signing.md) — Sigstore, Cosign и PQC-алгоритмы подписи.
* [Сравнение SCA-инструментов](./sca_tools_comparison.md) — Trivy vs Grype vs osv-scanner.

### Стандарты и ресурсы

* **CycloneDX VEX Specification (v1.7):** <https://cyclonedx.org/docs/specification/vex/> — спецификация VEX и justification values.
* **SLSA.dev:** <https://slsa.dev/> — фреймворк целостности цепочки поставок (Build + Source tracks).
* **EU CRA (Article 14):** <https://digital-strategy.ec.europa.eu/en/policies/cyber-resilience-act> — требования к отчётности об уязвимостях.
* **ENISA CRA SRP:** <https://www.enisa.europa.eu/> — платформа отчётности по EU CRA.
* **Trivy:** <https://trivy.dev/> — сканер уязвимостей и лицензий для образов, SBOM, filesystem.
* **Syft:** <https://github.com/anchore/syft> — генерация SBOM в форматах CycloneDX и SPDX.
