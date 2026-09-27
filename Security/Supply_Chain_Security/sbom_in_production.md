# SBOM в продакшене: чтение, интерпретация, реакция

## Определения

* **SBOM (Software Bill of Materials):** Машиночитаемый инвентарный список всех компонентов программного продукта (библиотеки, пакеты, модули, зависимости). Основные форматы — CycloneDX 1.7 и SPDX 3.1.
* **Blast Radius (Радиус поражения):** Масштаб затронутых сервисов при обнаружении уязвимости в общем компоненте. Определяется по графу зависимостей SBOM.
* **Reachability Analysis (Анализ достижимости):** Определение того, вызывается ли уязвимая функция библиотеки в конкретном приложении. Снижает количество ложных срабатываний CVE на 80–90%.
* **SBOM-as-Artifact:** Модель, при которой SBOM прикрепляется к OCI-образу как аттестация через Referrers API и верифицируется перед деплоем.
* **Living SBOM:** Динамический граф зависимостей, непрерывно обогащаемый данными об уязвимостях (VEX) и их статусе. Заменяет статический «снимок» SBOM.

## Основные концепции

### Зачем нужен SBOM в продакшене

SBOM — это не просто комплаенс-документ. В продакшене он решает три задачи:
1. **Реагирование на CVE:** Когда появляется новая уязвимость, SBOM позволяет за минуты определить, какие сервисы затронуты.
2. **Аудит зависимостей:** Позволяет ответить на вопрос «где используется библиотека X?» без поиска по коду.
3. **Проверка перед деплоем:** Admission-контроллер (Kyverno/OPA) блокирует образ без валидного SBOM или с критичными CVE.

### Структура SBOM (CycloneDX)

```json
{
  "bomFormat": "CycloneDX",
  "specVersion": "1.7",
  "version": 1,
  "components": [
    {
      "type": "library",
      "name": "requests",
      "version": "2.31.0",
      "purl": "pkg:pypi/requests@2.31.0",
      "licenses": [{"license": {"id": "Apache-2.0"}}],
      "properties": [
        {"name": "swid:tagId", "value": "requests-2.31.0"}
      ]
    }
  ],
  "vulnerabilities": [
    {
      "id": "CVE-2024-EXAMPLE",
      "source": {"name": "NVD"},
      "ratings": [{"severity": "CRITICAL", "score": 9.8}],
      "affects": {"ref": "urn:uuid:requests-2.31.0"}
    }
  ]
}
```

**Ключевые поля для чтения:**
- `components[].name` / `version` — имя и версия компонента
- `components[].purl` — уникальный идентификатор пакета (Package URL)
- `vulnerabilities[].id` — CVE ID
- `vulnerabilities[].ratings[].severity` — severity (CRITICAL, HIGH, MEDIUM, LOW)
- `vulnerabilities[].affects[].ref` — ссылка на затронутый компонент

### Процесс реагирования на новую CVE

```
Новая CVE опубликована
    │
    ├── 1. Получение CVE ID и описания
    │       (NVD, GitHub Advisory, vendor security bulletin)
    │
    ├── 2. Проверка SBOM: есть ли затронутый компонент?
    │       trivy sbom sbom.json --vuln CVE-2024-EXAMPLE
    │       → Да / Нет
    │
    ├── 3. Reachability: вызывается ли уязвимая функция?
    │       grype image:latest --show-vulnerability-reachability
    │       → Reachable / Unreachable
    │
    ├── 4. Определение Blast Radius: какие сервисы используют компонент?
    │       GUAC: "show all artifacts depending on requests@2.31.0"
    │       → Список сервисов
    │
    ├── 5. Триаж и решение:
    │       ├── Critical + Reachable → немедленный hotfix
    │       ├── Critical + Unreachable → VEX not_affected + мониторинг
    │       ├── High → плановое обновление (SLA 7 дней)
    │       └── Low/Medium → следующий релиз
    │
    └── 6. Отчёт: какой SBOM, какой компонент, какое решение
```

## Практические сценарии

### Сценарий 1: Быстрый поиск затронутых сервисов по CVE

```bash
# 1. Сканирование конкретного образа на CVE
trivy image harbor.internal/my-app:v1.2.3 --vuln CVE-2024-EXAMPLE
# → NAME          INSTALLED  FIXED   SEVERITY
# requests      2.31.0     2.32.0  CRITICAL

# 2. Сканирование всех образов в проекте Harbor
for img in $(curl -s -u admin:$HARBOR_PASS "https://harbor.internal/api/v2.0/projects/myapp/repositories" | jq -r '.[].name'); do
  digest=$(curl -s -u admin:$HARBOR_PASS "https://harbor.internal/api/v2.0/projects/myapp/repositories/$img/artifacts?tags=true" | jq -r '.[0].digest')
  echo "Checking $img@$digest..."
  trivy image --vuln CVE-2024-EXAMPLE --format json "harbor.internal/$img@$digest" | jq '.Results[].Vulnerabilities[]?.VulnerabilityID'
done
```

### Сценарий 2: Чтение SBOM и извлечение компонентов

```bash
# 1. Генерация SBOM из образа
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json > sbom.json

# 2. Список всех компонентов с версиями
jq '.components[] | {name: .name, version: .version, purl: .purl}' sbom.json

# 3. Фильтрация по типу (например, только Python-пакеты)
jq '.components[] | select(.purl | startswith("pkg:pypi")) | {name: .name, version: .version}' sbom.json

# 4. Поиск конкретной библиотеки
jq '.components[] | select(.name == "requests")' sbom.json
# → {"type":"library","name":"requests","version":"2.31.0","purl":"pkg:pypi/requests@2.31.0",...}

# 5. Подсчёт общего количества компонентов
jq '.components | length' sbom.json
# → 142
```

### Сценарий 3: Определение Blast Radius через GUAC

```bash
# 1. Импорт SBOM в GUAC (если развёрнут)
guaclite ingest -filename sbom.json

# 2. Запрос: какие артефакты используют requests@2.31.0?
curl -s -X POST http://guac.internal:8080/query -d '{
  "query": {
    "neighbors": {
      "node": {"ids": ["pkg:pypi/requests@2.31.0"]},
      "only": {"forward": ["DEPENDS_ON"]}
    }
  }
}'
# → Список артефактов, которые зависят от requests@2.31.0

# 3. Альтернатива: grep по всем SBOM в репозитории
find . -name "sbom.json" -exec jq -r '.components[] | select(.name=="requests") | input_filename' {} \;
# → ./apps/api/sbom.json
# → ./apps/auth/sbom.json
# → ./apps/gateway/sbom.json
```

### Сценарий 4: VEX-отчет для подтверждения not_affected

```bash
# 1. Проверка: вызывается ли уязвимая функция?
grype harbor.internal/my-app:v1.2.3 --show-vulnerability-reachability
# → CVE-2024-EXAMPLE: unreachable

# 2. Создание VEX-отчета
cat > vex-cve-2024-example.json << 'EOF'
{
  "vulnerabilities": [
    {
      "id": "CVE-2024-EXAMPLE",
      "status": "not_affected",
      "justification": "vulnerable_code_not_present",
      "detail": "Библиотека requests установлена, но уязвимый модуль HTTPDigestAuth не используется в приложении."
    }
  ]
}
EOF

# 3. Применение VEX к SBOM при сканировании
trivy sbom --vex vex-cve-2024-example.json sbom.json --severity CRITICAL
# → 0 vulnerabilities (CVE-2024-EXAMPLE исключена из отчёта)

# 4. Коммит VEX-отчета в репозиторий для аудита
git add vex-cve-2024-example.json
git commit -m "VEX: mark CVE-2024-EXAMPLE as not_affected for my-app"
```

### Сценарий 5: Admission-контроль по SBOM в Kubernetes

```yaml
# Kyverno: блокировка подов без SBOM или с критичными CVE
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-sbom
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-sbom-attestation
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["harbor.internal/*"]
          attestations:
            - type: https://cyclonedx.org/bom
              attestors:
                - entries:
                    - keys:
                        publicKeys: |-
                          -----BEGIN PUBLIC KEY-----
                          ...
                          -----END PUBLIC KEY-----
```

```bash
# Применение политики
kubectl apply -f require-sbom.yaml

# Проверка: попытка запуска без SBOM
kubectl run test --image=harbor.internal/my-app:unsigned --dry-run=server
# → Error: admission webhook denied the request

# Проверка: попытка запуска с SBOM
kubectl run test --image=harbor.internal/my-app:v1.2.3-signed --dry-run=server
# → pod/test created (dry-run)
```

## Лучшие практики

1. **SBOM при каждом релизе:** Генерация SBOM — часть пайплайна сборки. SBOM подписывается и прикрепляется к образу через Referrers API.
2. **VEX-процесс:** При обнаружении ложного CVE создавайте VEX-отчет и коммитьте в репозиторий. Это документирует решение для аудита.
3. **GUAC для blast radius:** В кластере с несколькими сервисами используйте GUAC для мгновенного определения затронутых артефактов.
4. **Сравнение SBOM между версиями:** Перед деплоем сравнивайте SBOM текущей и новой версии для обнаружения неожиданных изменений.
5. **Retention:** Храните SBOM для каждого релиза минимум 12 месяцев (требование EU CRA).

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| SBOM не содержит ожидаемых компонентов | Syft не распознал экосистему | `syft dir:. -o cyclonedx-json` | Используйте `cdxgen` как fallback для неподдерживаемых языков |
| CVE не отображается в SBOM | Trivy DB устарела | `trivy image --download-db-only` | Обновите базу: `trivy image --reset && trivy image ...` |
| VEX не применяется | Неверный формат VEX | `cat vex.json \| jq .` | Убедитесь, что VEX соответствует CycloneDX или SPDX профилю |
| GUAC не возвращает результатов | SBOM не импортирован | `guaclite ingest -filename sbom.json` | Импортируйте все SBOM в GUAC перед запросами |
| Kyverno блокирует валидный образ | SBOM не подписан или ключ устарел | `cosign verify ...` | Обновите публичный ключ в ClusterPolicy |

## Граничные случаи и ограничения

* **Динамические зависимости (dlopen):** SBOM фиксирует зависимости на этапе сборки. В рантайме могут загружаться дополнительные библиотеки. Для детекции — eBPF-агенты (Falco/Tetragon).
* **Mono-repo:** В монорепозитории с несколькими сервисами SBOM генерируется для каждого сервиса отдельно. Общий SBOM не отражает изоляцию сервисов.
* **Обратная совместимость:** SBOM в формате CycloneDX 1.7 может не читаться старыми версиями Trivy. Проверяйте версию формата и инструмента.

## Дополнительная информация

### Связанные документы

* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — генерация SBOM, VEX, SCA.
* [Подпись артефактов](./artifact_signing.md) — подпись SBOM через Cosign/Notation.
* [Целостность сборки](./build_integrity.md) — аттестации SLSA и интеграция SBOM в пайплайн.
* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз и регуляторика.
