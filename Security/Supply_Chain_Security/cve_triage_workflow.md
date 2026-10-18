# Триаж CVE: практический workflow

**Актуально для:** Trivy ≥ 0.71.0, Grype v0.82+, Syft v1.54+, CycloneDX 1.7, SPDX 3.0, EPSS, CVSS v3.1, Kubernetes 1.31+, Harbor v2.15+

## Определения

* **Триаж CVE (CVE Triage):** Процесс классификации и приоритизации newly discovered уязвимостей (CVE) по уровню риска для конкретного продукта/инфраструктуры. Включает проверку наличия уязвимого компонента, анализ достижимости (reachability), оценку CVSS и принятие решения: исправить, принять риск или пометить как неэксплуатируемое.
* **CVSS (Common Vulnerability Scoring System):** Стандарт оценки тяжести уязвимостей по шкале 0–10. Компоненты: Base (неизменный), Temporal (с учётом эксплойтов), Environmental (с учётом среды).
* **EPSS (Exploit Prediction Scoring System):** Метрика от FIRST, оценивающая вероятность эксплуатации уязвимости в публичных эксплойтах (0–1). Используется для приоритизации CVE помимо CVSS.
* **Reachability (Достижимость):** Определяет, вызывается ли уязвимая функция библиотеки в конкретном приложении. Уязвимость с `unreachable` кодом — ложное срабатывание.
* **SBOM (Software Bill of Materials — состав программного обеспечения):** Машиночитаемый инвентарный перечень всех компонентов программного продукта (стандарты: CycloneDX 1.7+, SPDX 3.0+).
* **PURL (Package URL):** Унифицированный идентификатор пакета формата `pkg:type/namespace/name@version`. Позволяет однозначно ссылаться на компонент независимо от экосистемы.
* **CycloneDX:** Лёгкий стандарт SBOM/VEX для DevOps-конвейеров. Поддерживает VEX-профиль `frameworks` для документирования решений по CVE.
* **SPDX (Software Package Data Exchange):** Стандарт Linux Foundation для обмена метаданными о ПО. Более формальный, чем CycloneDX, используется для юридической compliance.
* **VEX (Vulnerability Exploitability eXchange):** Документ, фиксирующий решение по triage: `not_affected`, `fixed`, `affected`, `under_investigation`. Дополняет SBOM информацией о том, влияет ли конкретная CVE на продукт в его текущей конфигурации.
* **False Positive (Ложноположительное срабатывание):** CVE обнаружена в SBOM, но уязвимый код не вызывается в приложении (unreachable), версия пакета не попадает в affected range, или CVE находится только в dev-зависимостях.
* **Blast Radius (Радиус поражения):** Масштаб затронутых сервисов и сред. Определяется по графу зависимостей (SBOM) и топологии деплоя.
* **SLA по исправлению:** Временные рамки для устранения уязвимости в зависимости от severity: Critical — 24 часа, High — 7 дней, Medium — 30 дней, Low — следующий релиз.

## Предпосылки

| Инструмент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Trivy** | ≥ 0.71.0 | Сканирование образов/SBOM на CVE (v0.69.4 — CVE-2026-33634, исключить) |
| **Grype** | v0.82+ | Анализ зависимостей, reachability (fallback) |
| **Syft** | v1.54+ | Генерация SBOM |
| **Harbor** | v2.15+ | Реестр артефактов с SBOM attestation |
| **Guac** | v1.x | Граф зависимостей, blast radius |
| **Kubernetes** | 1.31+ | Admission control для проверки SBOM |

Аппаратные требования: сканеры запускаются в отдельном CI-раннере с 4 ГБ RAM, 10 ГБ диска для кэша Trivy DB. SBOM и VEX хранятся в Harbor как OCI-аттестации (Referrers API). Требования к окружению: Harbor API доступен с service-аккаунтом (scope `pull`), Trivy DB синхронизируется через офлайн-зеркало или `--skip-db-update`.

## Основные концепции

### Модель triage

```
Новая CVE опубликована
    │
    ├─── SHAG 1: Сканирование (автоматическое)
    │    trivy sbom / grype / osv-scanner
    │    → Есть ли CVE в наших SBOM?
    │
    ├─── SHAG 2: Reachability (автоматическое/ручное)
    │    govulncheck ./... (Go) / VEX not_affected + grype/trivy --vex
    │    → Вызывается ли уязвимый код?
    │
    ├─── SHAG 3: Оценка риска
    │    CVSS + EPSS + reachability + контекст среды
    │    → Реальный риск для нашего продукта?
    │
    ├─── SHAG 4: Решение
    │    ├── Fix (исправить) → горячий фикс / плановое обновление
    │    ├── Risk Accept (принять риск) → документальное решение
    │    └── Not Affected (не затронут) → VEX not_affected
    │
    └─── SHAG 5: Документирование
         VEX-отчет + тикет в трекере + аудит-запись
```

### Матрица решений по CVSS + Reachability

| CVSS Score | Reachability | Решение | SLA | Действие |
| :--- | :--- | :--- | :--- | :--- |
| **9.0–10.0 (Critical)** | Reachable | **Fix немедленно** | 24 часа | Hotfix + деплой |
| **9.0–10.0 (Critical)** | Unreachable | **VEX not_affected** | 48 часов | Документальное подтверждение |
| **7.0–8.9 (High)** | Reachable | **Fix планово** | 7 дней | Обновление в следующем релизе |
| **7.0–8.9 (High)** | Unreachable | **VEX not_affected** | 7 дней | Документирование |
| **4.0–6.9 (Medium)** | Reachable | **Fix в плановом порядке** | 30 дней | Следующий релиз |
| **4.0–6.9 (Medium)** | Unreachable | **Risk Accept** | Следующий релиз | Комментарий в тикете |
| **0.1–3.9 (Low)** | Reachable | **Следующий релиз** | Следующий релиз | Опционально |
| **0.1–3.9 (Low)** | Unreachable | **Закрыть** | — | Закрытие тикета |

### Инструменты triage

| Инструмент | Назначение | Формат вывода |
| :--- | :--- | :--- |
| **Trivy** | Сканирование образов/SBOM на CVE (VEX — применение) | Table, JSON, CycloneDX |
| **Grype** | Сканирование + анализ зависимостей | JSON, table |
| **Syft** | Генерация SBOM | CycloneDX, SPDX |
| **osv-scanner** | Сканирование по OSV-базе (Google) | JSON |
| **GUAC** | Граф зависимостей, blast radius | GraphQL |
| **VEX** (CycloneDX) | Документирование решений | CycloneDX JSON |

## Практические сценарии

### Сценарий 1: Полный triage-пайплайн в CI

```yaml
# GitLab CI: автоматический triage при обнаружении CVE
cve_triage:
  stage: security
  image: aquasec/trivy:0.76.0
  script:
    # 1. Сканирование SBOM на критичные CVE
    - trivy sbom --format json --output triage-result.json $SBOM_FILE
    - CRITICAL_COUNT=$(jq '[.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' triage-result.json)
    
    # 2. Если есть Critical — проверяем reachability
    - |
      if [ "$CRITICAL_COUNT" -gt 0 ]; then
        echo "=== Critical CVEs found: $CRITICAL_COUNT ==="
        jq -r '.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL") | "\(.VulnerabilityID) \(.PkgName) \(.InstalledVersion) → \(.FixedVersion)"' triage-result.json
        
        # Reachability: Trivy OSS не имеет флага --show-vulnerability-reachability
        # (коммерческая фича). Решение о недостижимости фиксируется в VEX (not_affected).
        jq -r '.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL") |
              {id: .VulnerabilityID, status: "not_affected",
               justification: "vulnerable_code_not_present"}' triage-result.json > vex-auto.json
        REMAINING=$(trivy sbom --vex vex-auto.json $SBOM_FILE --severity CRITICAL --format json 2>/dev/null |
          jq '[.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length')
        
        if [ "$REMAINING" -gt 0 ]; then
          echo "$REMAINING critical CVEs are REACHABLE — blocking pipeline"
          exit 1
        else
          echo "All critical CVEs covered by VEX (not_affected) — proceeding"
        fi
      fi
  artifacts:
    paths:
      - triage-result.json
      - vex-auto.json
    when: always
  allow_failure: false
```

### Сценарий 2: Ручной triage через CLI

```bash
# 1. Сканирование конкретного CVE (jq-фильтрация, т.к. --vuln флаг не поддерживается trivy image)
CVE="CVE-2024-EXAMPLE"
trivy image --format json harbor.internal/my-app:v1.2.3 | \
  jq --arg c "$CVE" '.Results[].Vulnerabilities[]? | select(.VulnerabilityID == $c) | {id: .VulnerabilityID, pkg: .PkgName, installed: .InstalledVersion, fixed: .FixedVersion, severity: .Severity}'
# → {"id":"CVE-2024-EXAMPLE","pkg":"requests","installed":"2.31.0","fixed":"2.32.0","severity":"CRITICAL"}

# 2. Reachability: Trivy OSS не сканирует (флаг --show-vulnerability-reachability отсутствует).
#    Определяйте достижимость через govulncheck (Go), osv-scanner --call-analysis, либо VEX.
govulncheck ./... 2>/dev/null | grep "$CVE" || echo "$CVE: не найдена в call graph → unreachable"

# 3. Оценка: CVSS 9.8 (Critical) + Unreachable → VEX not_affected
cat > vex-$CVE.json << EOF
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.7",
  "version": 1,
  "vulnerabilities": [
    {
      "id": "$CVE",
      "source": {"name": "NVD"},
      "status": "not_affected",
      "justification": "vulnerable_code_not_present",
      "detail": "Уязвимый модуль HTTPDigestAuth не используется. Библиотека requests установлена для HTTP-клиента, но authentication не реализована."
    }
  ]
}
EOF

# 4. Проверка: CVE исключена из отчёта
trivy sbom --vex vex-$CVE.json sbom.json --severity CRITICAL
# → 0 vulnerabilities
```

### Сценарий 3: Массовый triage всех сервисов

```bash
#!/bin/bash
# Скрипт массового triage по конкретной CVE
CVE=$1
echo "=== Mass Triage: $CVE ==="

SERVICES="api gateway auth worker payment notification"

for svc in $SERVICES; do
  echo "--- $svc ---"
  
  # Найти последний успешный образ
  IMAGE=$(curl -s -u admin:$HARBOR "https://harbor.internal/api/v2.0/projects/myapp/repositories/$svc/artifacts?with_tag=true&n=1" | jq -r '.[0].tags[0].name')
  
  if [ -z "$IMAGE" ] || [ "$IMAGE" = "null" ]; then
    echo "  SKIP: no image found"
    continue
  fi
  
  # Сканирование (jq-фильтрация вместо --vuln)
  RESULT=$(trivy image --format json "harbor.internal/$svc:$IMAGE" 2>/dev/null | \
    jq -c --arg c "$CVE" '.Results[].Vulnerabilities[]? | select(.VulnerabilityID == $c)')
  VULN=$(echo "$RESULT" | jq -r '.Severity')
  
  if [ -n "$VULN" ]; then
    # Reachability: Trivy OSS не сканирует (флаг --show-vulnerability-reachability отсутствует).
    # Приоритет — через Grype --sort-by risk; решение о достижимости — в VEX not_affected.
    REACH=$(grype "harbor.internal/$svc:$IMAGE" --sort-by risk 2>/dev/null | grep -c "$CVE" || echo 1)
    
    echo "  AFFECTED: $svc:$IMAGE — $VULN — risk-ranked: $REACH (VEX not_affected для unreachable)"
  else
    echo "  OK: $svc:$IMAGE — not affected"
  fi
done
```

### Сценарий 4: Интеграция triage с Jira/трекером

```python
#!/usr/bin/env python3
"""Автоматическое создание тикетов для triage CVE."""
import json
import subprocess
import requests

JIRA_URL = "https://jira.internal"
JIRA_TOKEN = os.environ["JIRA_TOKEN"]
PROJECT = "SEC"

def create_triage_ticket(cve_id, severity, service, reachability, recommendation):
    """Создание тикета для triage."""
    payload = {
        "fields": {
            "project": {"key": PROJECT},
            "summary": f"[{severity}] Triage: {cve_id} in {service}",
            "issuetype": {"name": "Task"},
            "priority": {"name": "Critical" if severity == "CRITICAL" else "High"},
            "description": {
                "type": "doc",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": f"""
CVE: {cve_id}
Service: {service}
Severity: {severity}
Reachability: {reachability}
Recommendation: {recommendation}
SLA: {'24h' if severity == 'CRITICAL' else '7d'}
                    """}]
                }]
            },
            "labels": ["security", "cve-triage", severity.lower()],
            "assignee": {"name": "security-team"}
        }
    }
    
    resp = requests.post(f"{JIRA_URL}/rest/api/3/issue", json=payload,
                        auth=("email", JIRA_TOKEN))
    return resp.json()["key"]

# Пример использования
ticket = create_triage_ticket(
    cve_id="CVE-2024-EXAMPLE",
    severity="CRITICAL",
    service="api-gateway",
    reachability="REACHABLE",
    recommendation="Fix immediately — upgrade requests to 2.32.0"
)
print(f"Created ticket: {ticket}")
```

### Практические кейсы false positives

При triage CVE часто возникают ложноположительные срабатывания. Ниже — реальные кейсы и как их обрабатывать.

#### Кейс 1: Библиотека установлена, но не используется

**Ситуация:** `requests==2.31.0` установлена в `requirements.txt`, но в коде импортируется только `urllib3`. CVE в `requests` — unreachable.

**Как обнаружить:**
```bash
# Reachability: Trivy OSS не сканирует (флаг --show-vulnerability-reachability отсутствует).
# Анализируем использование зависимости вручную и фиксируем решение в VEX (см. ниже).
grep -r "import requests\|from requests" ./src/
# → Ничего (библиотека не используется → unreachable)
```

**Решение:** VEX `not_affected` с justification `vulnerable_code_not_present`.

```json
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.7",
  "version": 1,
  "vulnerabilities": [{
    "id": "CVE-2024-1234",
    "status": "not_affected",
    "justification": "vulnerable_code_not_present",
    "detail": "Библиотека requests установлена, но не импортируется в приложении."
  }]
}
```

#### Кейс 2: Уязвимая функция не вызывается

**Ситуация:** Библиотека `flask==2.3.0` содержит CVE в модуле `flask.testing`. Модуль `flask.testing` не используется в production-коде.

**Как обнаружить:**
```bash
# Reachability: Trivy OSS не сканирует (флаг отсутствует). Проверяем, используется ли уязвимый модуль.
grep -r "flask.testing\|from flask.testing" ./src/
# → Ничего (модуль flask.testing не используется → unreachable)
# → Ничего
```

**Решение:** VEX `not_affected` с justification `vulnerable_code_not_present`.

#### Кейс 3: CVE в dev-зависимости (не попадает в production)

**Ситуация:** CVE в `pytest==7.4.0` (devDependency). Тесты не попадают в production-образ.

**Как обнаружить:**
```bash
# Проверка: есть ли pytest в production-образе
trivy image harbor.internal/my-app:latest | grep pytest
# → Ничего (pytest не в production-образе)

# SBOM production-образа не содержит pytest
syft harbor.internal/my-app:latest -o cyclonedx-json | jq '.components[] | select(.name=="pytest")'
# → Ничего
```

**Решение:** VEX `not_affected` с justification `vulnerable_code_not_present`. Если pytest есть в образе — Needs triage (возможно, нужно исключить из production).

#### Кейс 4: Версия пакета не совпадает с affected range

**Ситуация:** CVE затрагивает `urllib3>=1.25.0,<2.0.0`. Установлена `urllib3==2.0.7`. Пакет НЕ затронут.

**Как обнаружить:**
```bash
# Trivy покажет CVE, но affected range не совпадает
# (jq-фильтрация — --vuln флаг не поддерживается trivy image)
trivy image --format json harbor.internal/my-app:latest | \
  jq --arg c "CVE-2023-45803" '.Results[].Vulnerabilities[]? | select(.VulnerabilityID == $c)'
# → {"VulnerabilityID":"CVE-2023-45803","PkgName":"urllib3","InstalledVersion":"2.0.7",...,"Severity":"CRITICAL"}
# Проверьте affected range вручную на https://nvd.nist.gov/vuln/detail/CVE-2023-45803
# → Диапазон: >=1.25.0,<2.0.0 → urllib3 2.0.7 НЕ затронут
```

**Решение:** VEX `not_affected` с justification `version_not_affected`. Trivy может показать CVE из-за неточного matching — проверяйте affected range вручную.

#### Кейс 5: CVE исправлена в другой версии пакета

**Ситуация:** `jinja2==3.1.2` содержит CVE-2024-1234, исправленный в `jinja2==3.1.3`. Обновление до 3.1.3 решает проблему.

**Как обнаружить:**
```bash
trivy image harbor.internal/my-app:latest | grep jinja2
# → jinja2  3.1.2  3.1.3  Critical
```

**Решение:** Fix — обновление до `jinja2==3.1.3`. VEX не нужен, если есть фикс.

#### Кейс 6: Reachability ложно unreachable (транзитивные вызовы)

**Ситуация:** Reachability показывает `UNREACHABLE`, но библиотека вызывается через цепочку: `app → libA → libB → vulnerable_lib`. Grype не отслеживает транзитивные вызовы глубже 1 уровня.

**Как обнаружить:**
```bash
# Статический анализ (Trivy OSS не сканирует reachability — флаг --show-vulnerability-reachability
# отсутствует; решение фиксируется в VEX). Здесь grep не ловит транзитивные цепочки:
grep -rn "vulnerable_lib\|vulnerable_function" ./src/
# → пусто (не найдено напрямую; цепочка скрыта в транзитиве — см. ниже)

# Но в коде:
# app.py → import libA
# libA/__init__.py → from .helper import process
# libA/helper.py → import libB
# libB/core.py → import vulnerable_lib  ← REACHABLE через транзитивный вызов
```

**Решение:** Reachability может быть неточным для глубоких цепочек. При сомнениях — treats как `under_investigation` и проверяйте вручную. Используйте VEX только при полной уверенности.

#### Кейс 7: CVE в тестовом окружении (docker-compose, CI)

**Ситуация:** `redis:7-alpine` в `docker-compose.yml` используется только для тестов. В production используется managed Redis.

**Как обнаружить:**
```bash
# Trivy сканирует docker-compose и находит CVE в redis
trivy config docker-compose.yml --severity CRITICAL
# → redis:7-alpine — CRITICAL CVE
```

**Решение:** Исключите тестовые зависимости из production SBOM. Если redis только в `docker-compose.yml` — это не production-риск.

## Валидация внедрения

1. **CI pipeline блокирует Reachability Critical CVE:** `trivy sbom --format json sbom.json | jq '[.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length'` → 0 для unreachable, 1+ для reachable (pipeline blocks).
2. **VEX коммитится в репозиторий:** каждая VEX запись имеет `bomFormat: CycloneDX` и `specVersion: 1.7`. Проверьте: `git log --grep="VEX"` — минимум 1 коммит за последние 2 недели.
3. **VEX применяется при сканировании:** `trivy sbom --vex vex.json sbom.json --severity CRITICAL` → `0 vulnerabilities`.
4. **Тикет в трекере создаётся для каждого reachable Critical:** проверьте, что `Jira` содержит тикет с меткой `cve-triage` для каждого reachable Critical CVE за последние 24 часа.
5. **SLA мониторинг:** `CRITICAL_TIME_TO_FIX <= 24ч` — проверьте через Grafana dashboard или SQL-запрос к Jira.
6. **EPSS интегрирован:** для каждой Critical CVE проверяется `EPSS > 0.5` → приоритет в тикете повышается до P1.

## Лучшие практики

1. **Автоматический triage в CI:** Каждый PR проходит сканирование. Critical + Reachable → блокировка pipeline.
2. **VEX для документирования:** Не оставляйте решение в голове — фиксируйте в VEX-отчёте и коммитьте в репозиторий.
3. **SLA как метрика:** Отслеживайте время от обнаружения до исправления (MTTR). Цель: Critical < 24ч, High < 7дн.
4. **Reachability-first подход:** Не все CVE требуюют немедленного исправления. Reachability снижает количество ложных срабатываний на 80–90%.
5. **Группировка CVE:** Объединяйте CVE по компоненту/сервису в один тикет, чтобы не засорять трекер.
6. **Ежедневный review:** Security-команда проводит daily review новых CVE и обновляет статусы тикетов.
7. **Скептицизм к reachability:** Reachability не идеален — проверяйте транзитивные цепочки вручную при сомнениях.
8. **VEX как аудит:** Каждый VEX — документальное решение. Храните историю VEX для аудита.
9. **EPSS для приоритизации:** Используйте EPSS-оценку (Exploit Prediction Scoring System) помимо CVSS для приоритизации CVE. EPSS > 0.5 → повышенный приоритет даже для High.
10. **Cleanup старых VEX:** Периодически удаляйте VEX, сопоставимые с устаревшими версиями пакетов. VEX привязан к конкретному SBOM — при обновлении образа SBOM меняется, старая VEX теряет актуальность.
11. **Эфемерные среды для triage:** Выполняйте сканирование в чистых контейнерах, удаляйте после завершения. Не используйте постоянные runner'ы с кэшем зависимостей.

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Trivy не показывает reachability | Trivy OSS не имеет reachability (commercial-only) | `trivy image --version` → `< 0.70.1` | Используйте `govulncheck` (Go) / `osv-scanner --call-analysis` / VEX `code_not_reachable`. Требуйте Trivy ≥ 0.70.1 (CVE-2026-33634). |
| Grype не сканирует reachability | Grype OSS не имеет reachability (приоритизация через `--sort-by risk/epss/kev`) | `grype version` | Используйте `govulncheck` / VEX `--vex`, либо `grype explain --id <CVE>` для контекста. |
| Trivy не находит CVE в SBOM | SBOM не содержит уязвимый компонент | `syft image -o cyclonedx-json \| jq '.components[] \| select(.name=="requests")'` | Проверьте, что SBOM валидный CycloneDX/SPDX и содержит уязвимый компонент. |
| VEX не применяется при сканировании | Неверный формат VEX | `jq '.bomFormat, .specVersion' vex.json` | Используйте CycloneDX VEX: `bomFormat: "CycloneDX"`, `specVersion: "1.7"`. Проверьте: `trivy sbom --vex vex.json sbom.json`. |
| Тикеты не создаются в Jira | Неверный токен/проект | `curl -u "email:$JIRA_TOKEN" $JIRA_URL/rest/api/3/mystate` | Проверьте permissions токена и ключ проекта. |
| VEX-отчёт создаётся, но CVE остаётся | VEX не покрывает все affected component | `jq '.vulnerabilities[].id' vex.json` | Добавьте все затронутые компоненты в VEX. VEX применяется только к компонентам, указанным в `vulnerableCasns` или через PURL-мэтчинг. |
| EPSS не отображается | Trivy OSS не выводит EPSS (commercial-only; поле `.Epss` в JSON отсутствует) | — | Используйте `grype --sort-by epss` или `snyk test` для EPSS-приоритизации; OSV даёт exploitability-данные в osv-scanner. |
| Mass triage медленно работает | Последовательный цикл с `trivy image` per service | `time ./mass-triage.sh CVE-... 2>&1` | Параллелализуйте сканирование: GNU parallel или xargs -P4. Используйте `--skip-db-update` для повторных сканов. |

## Граничные случаи и ограничения

* **Zero-day:** При отсутствии фикса — VEX `under_investigation` + мониторинг OSV/GitHub Advisories + возможный временный откат сервиса или временный firewall-фильтр.
* **Транзитивные зависимости:** Reachability не проверяет транзитивные вызовы глже 1 уровня. Если библиотека A вызывает уязвимую библиотеку B, а та — C, то C может быть unreachable напрямую, но reachable через A→B→C. Используйте `trivy sbom --dependency-tree` для визуализации цепочки.
* **Мульти-архитектура:** Reachability может различаться для linux/amd64 и linux/arm64. Проверяйте каждую архитектуру отдельно: `trivy image --platform linux/arm64 ...`.
* **Частые обновления:** При ежедневных релизах triage может стать шумным. Используйте группировку CVE по компоненту и автоматический VEX для неизменных компонентов.
* **Конфликт VEX и новых обнаружений:** Если VEX помечает CVE как `not_affected`, но новая версия Trivy DB обнаруживает новые affected version range — VEX автоматически перестаёт применяться. Регулярно пересматривайте VEX при обновлении базы.
* **Dev vs Production:** CVE в dev-зависимостях (pytest, eslint) не требует VEX, если эти зависимости исключены из production-образа. Проверьте: `syft harbor.internal/my-app:latest -o cyclonedx-json | jq '.components[] | select(.name=="pytest")'` → должно быть пусто.
* **EU CRA:** Для товаров Class II (Critical) под EU CRA (Article 14), каждый reachable Critical CVE требует уведомления в ENISA SRP в течение 24 часов. VEX с `under_investigation` тоже считается уведомлением.

## Дополнительная информация

### Связанные документы

* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM, blast radius, VEX в production.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX generation, Syft/Trivy/Grype pipeline.
* [Реагирование на инциденты supply chain](./supply_chain_incident_response.md) — пошаговый response на компрометацию.
* [Целостность сборки](./build_integrity.md) — SLSA и аттестации.
* [Цифровые подписи артефактов](./artifact_signing.md) — Cosign/Notation подпись и проверка.
* [Сравнение SCA-инструментов](./sca_tools_comparison.md) — Trivy vs Grype vs osv-scanner.
* [Политика SBOM для разработчиков](./sbom_developer_policy.md) — RACI matrix, quality gate в CI.

### Стандарты и ресурсы

* [Trivy SBOM scanning](https://trivy.dev/docs/latest/supply-chain/sbom/) — официальная документация
* [CycloneDX VEX specification](https://cyclonedx.org/docs/specification/vex/) — VEX профиль
* [FIRST CVSS](https://www.first.org/cvss/) — оценка тяжести уязвимостей
* [FIRST EPSS](https://www.first.org/epss/) — предсказание эксплуатации
* [NIST NVD](https://nvd.nist.gov/) — база данных уязвимостей
