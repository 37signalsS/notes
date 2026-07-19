# SBOM для Docker-образов

## Определения

**SBOM (Software Bill of Materials) для Docker** — это машиночитаемый перечень всех компонентов Docker-образа: прямых и транзитивных зависимостей, их версий, лицензий и идентификаторов — **PURL (Package URL)**, **CPE (Common Platform Enumeration)**. SBOM является базой для процесса **SCA (Software Composition Analysis — анализ состава ПО)**.

**VEX (Vulnerability Exploitability eXchange)** — формат метаданных, позволяющий уточнить статус уязвимости в конкретном продукте. VEX сообщает, является ли уязвимость эксплуатируемой или она не представляет угрозы (например, из-за того, что уязвимый код не вызывается), что радикально снижает "шум" при сканировании.

См. подробнее: **[анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.

## Базовые концепции

### Стандартные форматы

| Формат | Фокус | Разработчик | Примечание |
| :--- | :--- | :--- | :--- |
| **SPDX** | Лицензии, соответствие | Linux Foundation | Стандарт ISO/IEC 5962:2021 |
| **CycloneDX** | Безопасность, уязвимости | OWASP | Поддержка VEX, ML-компонентов |

### Современные инструменты и процессы

1. **Генерация**: `Syft`, `Trivy`, `docker buildx --sbom` создают SBOM.
2. **Анализ и фильтрация**: **Docker Scout** (встроенная платформа Docker) и сканеры (Grype, Trivy) сопоставляют SBOM с базами CVE и применяют VEX-фильтры.
3. **Аттестация**: SBOM подписывается как аттестация. В 2025 году стандартом становится прикрепление **VSA (Verification Summary Attestation)** для подтверждения факта проверки.

## Практические сценарии

### 1. Генерация SBOM с помощью Syft

**Syft** — инструмент от Anchore для глубокого анализа слоев образа и создания SBOM.

```bash
# Генерация SBOM в формате CycloneDX JSON (рекомендуется для анализа безопасности)
syft python:3.9-slim -o cyclonedx-json > sbom.json

# Генерация SBOM в формате SPDX JSON (для юридического аудита лицензий)
syft python:3.9-slim -o spdx-json > sbom.spdx.json
```

### 2. Генерация SBOM при сборке с Docker BuildKit

Начиная с `docker buildx` v0.10+, SBOM можно генерировать как аттестацию прямо во время сборки и прикреплять к манифесту образа в реестре.

```bash
# Сборка образа с прикрепленной SBOM-аттестацией
docker buildx build \
  --tag my-registry/my-app:1.0.0 \
  --provenance=true \
  --sbom=true \
  --push \
  .

# Проверка наличия аттестации в реестре
docker buildx imagetools inspect my-registry/my-app:1.0.0 --format '{{ json .SBOM }}'
```

### 3. Использование Docker Scout для анализа SBOM и VEX

**Docker Scout** — это современная замена базовым сканерам, интегрированная в экосистему Docker.

```bash
# Просмотр SBOM и анализ зависимостей
docker scout sbom my-app:latest

# Сканирование на уязвимости с учетом политик организации
docker scout cves my-app:latest

# Фильтрация только эксплуатируемых уязвимостей (на основе данных VEX)
docker scout cves --filter "vulnerability exploitability=exploitable" my-app:latest
```

### 4. CI/CD-пайплайн: Генерация, сканирование и исправление

Современный цикл управления уязвимостями (Shift Left):

1. **Генерация SBOM (`Syft`):**
    ```bash
    syft my-app:1.2.3 -o cyclonedx-json > sbom.json
    ```

2. **Сканирование с учетом VEX (`Grype`):**
    ```bash
    # Сканирование SBOM и применение VEX-файла для исключения ложных срабатываний
    grype sbom:sbom.json --vex my-product-vex.yaml
    ```

3. **Автоматическое исправление (`Copacetic`):**
    ```bash
    # Патчинг образа без пересборки (прямое обновление уязвимых пакетов в слоях)
    copa patch -i my-app:1.2.3 -r report.json -t my-app:1.2.3-patched
    ```

## Дополнительная информация

**Связанные документы:**
- **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** — общая теория SCA.
- **[Сканирование уязвимостей](./vulnerability_scanning.md)** — практическое использование Trivy и Grype.
- **[Подписание образов](./image_signature_and_verification.md)** — аттестации и Sigstore/Cosign.
- **[Безопасность публичных реестров](../Docker_registries/public_registry_security.md)** — управление доверием.

**Внешние ресурсы:**
- **CIS Docker Benchmark:** Рекомендация 4.1 (Инвентаризация образов через SBOM).
- **Docker Scout Documentation:** [docs.docker.com/scout/](https://docs.docker.com/scout/).
- **CycloneDX VEX Guide:** [cyclonedx.org/capabilities/vex/](https://cyclonedx.org/capabilities/vex/).

**Инструменты:** `Syft` (генерация), `Grype` (сканирование), `Trivy` (универсальный комбайн), `Copacetic` (быстрое исправление), `Docker Scout` (платформа безопасности).
