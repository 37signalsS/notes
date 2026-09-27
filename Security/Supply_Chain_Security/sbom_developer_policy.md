# SBOM-политика для разработчиков

## Определения

* **SBOM-политика (SBOM Policy):** Набор правил и требований, определяющих, как команды разработки создают, поддерживают и используют Software Bill of Materials на всех этапах жизненного цикла ПО. Включает формат, обязательные поля, процесс обновления и ответственность.
* **RACI-матрица:** Модель распределения ответственности: **R**esponsible (исполнитель), **A**ccountable (ответственный), **C**onsulted (консультант), **I**nformed (информированный). Применяется для определения, кто создаёт, кто проверяет, кто использует SBOM.
* **SBOM Quality Gate:** Набор автоматических проверок SBOM в CI/CD, которые должны быть пройдены перед допуском к деплою. Включает: наличие обязательных полей, корректность PURL, отсутствие критичных CVE.
* **Living SBOM:** Динамический граф зависимостей, обновляемый при каждом релизе и обогащаемый данными VEX. Заменяет статический «снимок» на непрерывный поток данных.

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
    "tools": [{"vendor": "anchore", "name": "syft", "version": "1.5.0"}],
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

### Процесс работы разработчика

```
Добавление зависимости в проект
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
```

### Сценарий 2: CI-quality gate для SBOM

```yaml
# GitLab CI: проверка SBOM перед деплоем
sbom-quality-gate:
  stage: verify
  image: anchore/syft:v1.5.0
  script:
    # 1. Проверка формата
    - jq -e '.bomFormat == "CycloneDX"' sbom.json || { echo "ERROR: Invalid format"; exit 1; }
    - jq -e '.specVersion == "1.7"' sbom.json || { echo "ERROR: Invalid spec version"; exit 1; }
    
    # 2. Проверка обязательных полей
    - MISSING=$(jq '[.components[] | select(.purl == null or .version == null)] | length' sbom.json)
    - '[ "$MISSING" -eq 0 ] || { echo "ERROR: $MISSING components missing purl/version"; exit 1; }'
    
    # 3. Проверка на критичные CVE
    - trivy sbom --severity CRITICAL --exit-code 1 sbom.json
    
    # 4. Количество компонентов (для детекции аномалий)
    - COUNT=$(jq '.components | length' sbom.json)
    - echo "SBOM contains $COUNT components"
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

### Сценарий 4: Автоматическое уведомление при новой CVE

```yaml
# GitLab CI: ежедневная проверка CVE в зависимостях
daily-cve-check:
  stage: security
  script:
    - trivy fs --severity CRITICAL,HIGH --format json --output daily-cve-report.json .
    - CRITICAL=$(jq '[.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' daily-cve-report.json)
    - |
      if [ "$CRITICAL" -gt 0 ]; then
        echo "CRITICAL CVEs found — creating issue"
        # Создание тикета в Jira/GitLab Issues
        curl -X POST "$CI_API_V4_URL/projects/$CI_PROJECT_ID/issues" \
          -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
          -d "title=[SECURITY] Critical CVEs detected" \
          -d "description=$(cat daily-cve-report.json | jq -r '.Results[].Vulnerabilities[]? | select(.Severity == "CRITICAL") | "- \(.VulnerabilityID): \(.PkgName) \(.InstalledVersion)"')"
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

## Лучшие практики

1. **SBOM — часть Definition of Done:** Без SBOM нет релиза. Это автоматизированная проверка в CI.
2. **Lock-файлы в Git:** Все lock-файлы коммитятся. Без них SBOM некорректен.
3. **VEX для каждого false positive:** Если CVE не эксплуатируется — создавайте VEX и коммитьте. Это документирует решение.
4. **Ежедневный CVE-check:** Автоматический сканер проверяет зависимости и создаёт тикеты при обнаружении критичных CVE.
5. **Обзор SBOM quarterly:** Security-команда проводит ежеквартальный аудит SBOM: удаление неиспользуемых зависимостей, обновление устаревших.
6. **Шаблоны VEX:** Используйте стандартные шаблоны VEX для типичных ситуаций (unreachable, not_present, mitigated).

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| SBOM не содержит нового компонента | CI не генерирует SBOM для нового языка | Используйте `cdxgen` как fallback |
| Разработчик добавил CVE | Нет quality gate | Включите `trivy sbom --severity CRITICAL --exit-code 1` в CI |
| VEX не применяется | Неверный формат | Используйте CycloneDX VEX, не SPDX |
| SBOM слишком большой | Слишком много зависимостей | Audit: удалите неиспользуемые компоненты |

## Граничные случаи и ограничения

* **Mono-repo:** В монорепозитории SBOM генерируется для каждого сервиса. Общий SBOM не отражает изоляцию.
* **Проприетарные библиотеки:** Внутренние библиотеки должны быть в SBOM с корректным PURL.
* **Динамические зависимости:** SBOM фиксирует зависимости на этапе сборки. Runtime drift — отдельная тема (см. [Runtime drift detection](./runtime_drift_detection.md)).
* **Частые релизы:** При ежедневных релизах SBOM обновляется автоматически. Процесс не должен замедлять delivery.

## Дополнительная информация

### Связанные документы

* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM, blast radius, VEX.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — SCA, VEX, инструменты.
* [Целостность сборки](./build_integrity.md) — SLSA и интеграция SBOM в пайплайн.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз.
