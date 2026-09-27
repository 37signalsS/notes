# Триаж CVE: практический workflow

## Определения

* **Триаж CVE (CVE Triage):** Процесс классификации и приоритизации newly discovered уязвимостей (CVE) по уровню риска для конкретного продукта/инфраструктуры. Включает проверку наличия уязвимого компонента, анализ достижимости (reachability), оценку CVSS и принятие решения: исправить, принять риск или пометить как неэксплуатируемое.
* **CVSS (Common Vulnerability Scoring System):** Стандарт оценки тяжести уязвимостей по шкале 0–10. Компоненты: Base (неизменный), Temporal (с учётом эксплойтов), Environmental (с учётом среды).
* **Reachability (Достижимость):** Определяет, вызывается ли уязвимая функция библиотеки в конкретном приложении. Уязвимость с `unreachable` кодом — ложное срабатывание.
* **VEX (Vulnerability Exploitability eXchange):** Документ, фиксирующий решение по triage: `not_affected`, `fixed`, `affected`, `under_investigation`.
* **SLA по исправлению:** Временные рамки для устранения уязвимости в зависимости от severity: Critical — 24 часа, High — 7 дней, Medium — 30 дней, Low — следующий релиз.

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
    │    grype --show-vulnerability-reachability
    │    → Вызывается ли уязвимый код?
    │
    ├─── SHAG 3: Оценка риска
    │    CVSS + reachability + контекст среды
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
| **Trivy** | Сканирование образов/SBOM на CVE | Table, JSON, CycloneDX |
| **Grype** | Сканирование + reachability analysis | JSON, table |
| **osv-scanner** | Сканирование по OSV-базе (Google) | JSON |
| **GUAC** | Граф зависимостей, blast radius | GraphQL |
| **VEX** (CycloneDX) | Документирование решений | CycloneDX JSON |

## Практические сценарии

### Сценарий 1: Полный triage-пайплайн в CI

```yaml
# GitLab CI: автоматический triage при обнаружении CVE
cve_triage:
  stage: security
  image: aquasec/trivy:0.55.0
  script:
    # 1. Сканирование SBOM на критичные CVE
    - trivy sbom --format json --output triage-result.json $SBOM_FILE
    - CRITICAL_COUNT=$(jq '[.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' triage-result.json)
    
    # 2. Если есть Critical — проверяем reachability
    - |
      if [ "$CRITICAL_COUNT" -gt 0 ]; then
        echo "=== Critical CVEs found: $CRITICAL_COUNT ==="
        jq -r '.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL") | "\(.VulnerabilityID) \(.PkgName) \(.InstalledVersion) → \(.FixedVersion)"' triage-result.json
        
        # Reachability check через Grype
        grype sbom:$SBOM_FILE --show-vulnerability-reachability -o json > grype-result.json
        
        # Если все Critical unreachable — создаём VEX
        UNREACHABLE=$(jq '[.matches[] | select(.vulnerability.severity == "CRITICAL" and .matchDetails[0].maxReachability == "UNREACHABLE")] | length' grype-result.json)
        
        if [ "$UNREACHABLE" -eq "$CRITICAL_COUNT" ]; then
          echo "All critical CVEs are UNREACHABLE — creating VEX"
          # Генерация VEX (упрощённо)
          jq -r '.matches[] | select(.vulnerability.severity == "CRITICAL") | {id: .vulnerability.id, status: "not_affected", justification: "vulnerable_code_not_present"}' grype-result.json > vex-auto.json
        else
          echo "Some critical CVEs are REACHABLE — blocking pipeline"
          exit 1
        fi
      fi
  artifacts:
    paths:
      - triage-result.json
      - grype-result.json
      - vex-auto.json
    when: always
  allow_failure: false
```

### Сценарий 2: Ручной triage через CLI

```bash
# 1. Сканирование конкретного CVE
CVE="CVE-2024-EXAMPLE"
trivy image harbor.internal/my-app:v1.2.3 --vuln $CVE
# → NAME        INSTALLED  FIXED    SEVERITY  ...
# requests    2.31.0     2.32.0   CRITICAL  ...

# 2. Reachability check
grype harbor.internal/my-app:v1.2.3 --show-vulnerability-reachability | grep $CVE
# → requests  2.31.0  2.32.0  Critical  CVE-2024-EXAMPLE  UNREACHABLE

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
  
  # Сканирование
  RESULT=$(trivy image --format json --vuln "$CVE" "harbor.internal/$svc:$IMAGE" 2>/dev/null)
  VULN=$(echo "$RESULT" | jq -r ".Results[].Vulnerabilities[]? | select(.VulnerabilityID == \"$CVE\") | .Severity")
  
  if [ -n "$VULN" ]; then
    # Reachability
    REACH=$(grype "harbor.internal/$svc:$IMAGE" --show-vulnerability-reachability -o json 2>/dev/null | \
      jq -r ".matches[] | select(.vulnerability.id == \"$CVE\") | .matchDetails[0].maxReachability")
    
    echo "  AFFECTED: $svc:$IMAGE — $VULN — Reachability: $REACH"
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
# Reachability check
grype harbor.internal/my-app:v1.2.3 --show-vulnerability-reachability | grep CVE-2024-1234
# → requests  2.31.0  2.32.0  Critical  CVE-2024-1234  UNREACHABLE

# Проверка: импортируется ли requests в коде
grep -r "import requests" ./src/
# → Ничего (библиотека не используется)
```

**Решение:** VEX `not_affected` с justification `vulnerable_code_not_present`.

```json
{
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
# Reachability: функция не вызывается
grype harbor.internal/my-app:v1.2.3 --show-vulnerability-reachability | grep CVE-2024-5678
# → flask  2.3.0  2.3.1  Critical  CVE-2024-5678  UNREACHABLE

# Проверка: используется ли flask.testing
grep -r "flask.testing\|from flask.testing" ./src/
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
trivy image harbor.internal/my-app:latest --vuln CVE-2023-45803
# → urllib3  2.0.7  ---  Critical  (но affected range: >=1.25.0,<2.0.0)
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
# Reachability: UNREACHABLE
grype harbor.internal/my-app:v1.2.3 --show-vulnerability-reachability | grep CVE-2024-9999
# → vulnerable_lib  1.0.0  1.0.1  Critical  CVE-2024-9999  UNREACHABLE

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

## Лучшие практики

1. **Автоматический triage в CI:** Каждый PR проходит сканирование. Critical + Reachable → блокировка pipeline.
2. **VEX для документирования:** Не оставляйте решение в голове — фиксируйте в VEX-отчёте и коммитьте в репозиторий.
3. **SLA как метрика:** Отслеживайте время от обнаружения до исправления (MTTR). Цель: Critical < 24ч, High < 7дн.
4. **Reachability-first подход:** Не все CVE требуют немедленного исправления. Reachability снижает количество ложных срабатываний на 80–90%.
5. **Группировка CVE:** Объединяйте CVE по компоненту/сервису в один тикет, чтобы не засорять трекер.
6. **Ежедневный review:** Security-команда проводит daily review новых CVE и обновляет статусы тикетов.
7. **Скептицизм к reachability:** Reachability не идеален — проверяйте транзитивные цепочки вручную при сомнениях.
8. **VEX как аудит:** Каждый VEX — документальное решение. Храните историю VEX для аудита.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Grype не показывает reachability | Версия < v0.35 | Обновите Grype: `grype --version` |
| Trivy не находит CVE в SBOM | SBOM не содержит уязвимый компонент | Проверьте: `syft image -o cyclonedx-json \| jq '.components[] \| select(.name=="requests")'` |
| VEX не применяется при сканировании | Неверный формат VEX | Используйте CycloneDX VEX: `trivy sbom --vex vex.json sbom.json` |
| Тикеты не создаются в Jira | Неверный токен/проект | Проверьте permissions токена и ключ проекта |

## Граничные случаи и ограничения

* **Zero-day:** При отсутствии фикса — VEX `under_investigation` + мониторинг + возможный временный откат сервиса.
* **Транзитивные зависимости:** Reachability не проверяет транзитивные вызовы. Если библиотека A вызывает уязвимую библиотеку B, а та — C, то C может быть unreachable напрямую, но reachable через A→B→C.
* **Мульти-архитектура:** Reachability может различаться для linux/amd64 и linux/arm64. Проверяйте каждую архитектуру отдельно.
* **Частые обновления:** При ежедневных релизах triage может стать шумным. Используйте группировку и автоматический VEX для неизменных компонентов.

## Дополнительная информация

### Связанные документы

* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM и blast radius.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX, инструменты.
* [Реагирование на инциденты supply chain](./supply_chain_incident_response.md) — пошаговый response.
* [Целостность сборки](./build_integrity.md) — SLSA и аттестации.
