# SBOM для Docker-образов

## Определения

**SBOM (Software Bill of Materials) для Docker** — это машиночитаемый инвентарный перечень всех компонентов Docker-образа: прямых и транзитивных зависимостей, их версий, лицензий и идентификаторов — **PURL (Package URL)**, **CPE (Common Platform Enumeration)**. SBOM является фундаментом для процесса **SCA (Software Composition Analysis)**.

**Living SBOM** — концепция динамического графа зависимостей (актуальна для 2026 года), который обновляется на каждом этапе жизненного цикла: от сборки (Build-time SBOM) до эксплуатации (Runtime SBOM), отражая реально загруженные в память библиотеки.

**VEX (Vulnerability Exploitability eXchange)** — сопроводительный документ (профиль CycloneDX или SPDX), уточняющий статус уязвимости в конкретном контексте приложения. Позволяет официально заявить, что уязвимость "не влияет" (not affected), что радикально снижает количество ложных срабатываний при сканировании.

**CBOM (Cryptographic BOM)** — специализированный раздел SBOM (стандарт CycloneDX 1.6+), содержащий сведения об используемых криптографических алгоритмах и ключах. Необходим для аудита устойчивости к квантовым угрозам (PQC).

См. подробнее: **[анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.

## Базовые концепции

Безопасность цепочки поставок в 2026 году требует прозрачности состава ПО на всех этапах.

### Стандартные форматы

| Формат | Версия | Фокус | Примечание |
| :--- | :--- | :--- | :--- |
| **CycloneDX** | 1.7 | Безопасность, VEX, CBOM, AI/ML-модели | Основной формат для автоматизации DevSecOps. |
| **SPDX** | 3.0 | Юридический комплаенс, лицензии, Linked Data | Модульная архитектура (JSON-LD), стандарт ISO. |

### Современные инструменты и процессы (2026)

1. **Генерация**: **Syft v1.x+** и **Trivy** являются индустриальными стандартами. `docker buildx --sbom` интегрирует генерацию прямо в процесс сборки BuildKit.
2. **Аттестация и хранение**: SBOM подписывается через **Cosign** и хранится как аттестация. В 2026 году активно используется **OCI 1.1 Referrers API**, позволяющий прикреплять SBOM к образу без изменения его основного дайджеста.
3. **Верификация (VSA)**: **Verification Summary Attestation** — итоговый документ, подтверждающий, что SBOM был сгенерирован и проверен сканерами в соответствии с политиками организации.
4. **ASPM (Application Security Posture Management)**: Платформы типа **Docker Scout** или **Dependency-Track** агрегируют SBOM для непрерывного мониторинга новых CVE.

### Требования ФСТЭК (РФ, 2025)

Для сертификации средств в контейнерном исполнении (Инф. сообщение от 13.01.2025) установлены специфические требования к SBOM:
*   **Формат:** CycloneDX версии 1.6 и выше.
*   **Обогащение (Properties):** Обязательная разметка каждого компонента по его отношению к функциям безопасности и поверхности атаки (бинарные поля).
*   **Поле `ghost provided by`:** Используется для подтверждения, что компонент заимствован из сертифицированной ОС.
*   **Валидация:** Формальная проверка состава с помощью скриптов (verifier) от **ЦКИ СП РАН (ИСП РАН)**.

Подробнее: **[Сертификация ФСТЭК для контейнеров](../../Linux/Security/Fstec/container_certification.md)**.

## Практические сценарии

### 1. Глубокая генерация SBOM с помощью Syft v1.0+

Syft анализирует слои образа, пакетные менеджеры (npm, go mod, pip) и даже бинарные файлы.

```bash
# Генерация Living SBOM в формате CycloneDX 1.7 JSON
syft image my-app:latest -o cyclonedx-json > sbom.json

# Анализ конкретной директории с генерацией SPDX 3.0
syft dir:./src -o spdx-json > project.spdx.json
```

### 2. Сборка с аттестациями (BuildKit + OCI 1.1)

Начиная с Docker v27+, BuildKit поддерживает расширенные аттестации, которые реестры (например, Harbor 2.11+, GitHub Container Registry) отображают нативно.

```bash
# Сборка с генерацией SBOM, Provenance (происхождение) и загрузкой в реестр
docker buildx build \
  --tag my-registry/my-app:1.2.0 \
  --sbom=true \
  --provenance=mode=max \
  --push \
  .

# Проверка аттестаций через CLI
docker buildx imagetools inspect my-registry/my-app:1.2.0 --format '{{ json .SBOM }}'
```

### 3. Интеграция VEX для фильтрации уязвимостей (Trivy)

Использование VEX-файла позволяет игнорировать уязвимости, которые присутствуют в библиотеке, но недоступны для эксплуатации в вашем приложении.

```bash
# Сканирование SBOM с применением VEX-исключений
trivy sbom sbom.json \
  --vex my-app-vex.json \
  --severity HIGH,CRITICAL \
  --exit-code 1
```

### 4. Использование Docker Scout для анализа аттестаций

Docker Scout автоматически анализирует аттестации образов в реестре и сопоставляет их с политиками безопасности.

```bash
# Анализ состава и рисков на основе прикрепленного SBOM
docker scout cves my-app:latest

# Сравнение состава двух образов (drift analysis)
docker scout compare my-app:v1 --to my-app:v2
```

### 5. Автоматическое исправление через Copacetic (Copa)

Если сканирование SBOM выявило уязвимости в системных пакетах, их можно исправить без пересборки всего образа (без доступа к Dockerfile).

```bash
# 1. Сканирование и получение отчета в формате JSON (Trivy)
trivy image --format json --output report.json my-app:1.2.0

# 2. Патчинг образа на основе отчета
copa patch -i my-app:1.2.0 -r report.json -t my-app:1.2.0-patched
```

### Что такое SBOM и как он генерируется?

**SBOM (Software Bill of Materials)** — формализованный перечень всех компонентов, библиотек и зависимостей, входящих в образ или приложение. Используется для аудита цепочки поставок, быстрого поиска уязвимостей и соблюдения требований регулирования.

**Инструменты генерации:**
- **Syft v1.x+** — эталонный генератор SBOM (поддерживает CycloneDX, SPDX).
- **Trivy** — генерирует SBOM командой `trivy image --format cyclonedx <image>`.
- **Docker BuildKit** — `docker buildx --sbom=true` интегрирует генерацию прямо в процесс сборки.

**Форматы:** CycloneDX (рекомендуется), SPDX.

## Дополнительная информация

**Связанные документы:**
- **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** — общая теория SCA и концепция Living SBOM.
- **[Сертификация ФСТЭК для контейнеров](../../Linux/Security/Fstec/container_certification.md)** — регуляторные требования к составу образов и SBOM.
- **[Сканирование уязвимостей](./vulnerability_scanning.md)** — практическое использование Trivy и Grype.
- **[Подписание и верификация образов](./image_signature_and_verification.md)** — аттестации, Cosign и VSA.
- **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)** — уровни SLSA и защита пайплайнов.

**Внешние ресурсы:**
- **CycloneDX Specification (v1.7):** [cyclonedx.org](https://cyclonedx.org/).
- **SPDX Standard (v3.0):** [spdx.dev](https://spdx.dev/).
- **OCI 1.1 Referrers API Guide:** [opencontainers.org](https://opencontainers.org/).
- **Docker Scout Docs:** [docs.docker.com/scout/](https://docs.docker.com/scout/).

**Инструменты:** `Syft` (генерация v1.0+), `Trivy` (сканирование и VEX), `Cosign` (подпись аттестаций), `Copacetic` (быстрый патчинг), `Docker Scout` (ASPM платформа).
