# SBOM для Docker-образов

## Определения

**SBOM (Software Bill of Materials) для Docker** — это машиночитаемый перечень всех компонентов Docker-образа: прямых и транзитивных зависимостей, их версий, лицензий и идентификаторов — **PURL (Package URL)**, **CPE (Common Platform Enumeration)**. SBOM является частью процесса **SCA (Software Composition Analysis — анализ состава ПО)**, адаптированного для контейнерных образов. См. подробнее: **[анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.

## Базовые концепции

### Стандартные форматы

| Формат | Фокус | Разработчик |
| :--- | :--- | :--- |
| **SPDX** | Лицензии | Linux Foundation (ISO/IEC 5962:2021) |
| **CycloneDX** | Безопасность, уязвимости | OWASP |

### Место в экосистеме безопасности Docker

1. **Генерация**: `Syft`, `docker buildx --sbom` создают SBOM.
2. **Анализ**: SBOM используется **[сканерами уязвимостей](./vulnerability_scanning.md)** (Grype, Trivy) для поиска **CVE (Common Vulnerabilities and Exposures)**.
3. **Подтверждение**: SBOM подписывается как аттестация в процессе **[подписания образов](./image_signature_and_verification.md)**.

## Практические сценарии

### 1. Генерация SBOM с помощью Syft

**Syft** — популярный инструмент от Anchore для генерации SBOM из образов контейнеров.

```bash
# Генерация SBOM в формате CycloneDX JSON (рекомендуется для безопасности)
syft python:3.9-slim -o cyclonedx-json > sbom.json

# Генерация SBOM в формате SPDX JSON (для анализа лицензий)
syft python:3.9-slim -o spdx-json > sbom.spdx.json
```

### 2. Генерация SBOM при сборке с Docker BuildKit

Начиная с `docker buildx` v0.10+, SBOM можно генерировать как аттестацию прямо во время сборки и прикреплять к манифесту образа в реестре.

```bash
# Собрать образ и прикрепить к нему SBOM-аттестацию
docker buildx build \
  --tag my-registry/my-app:1.0.0 \
  --provenance=true \
  --sbom=true \
  .

# Проверить наличие аттестации в реестре
docker buildx imagetools inspect my-registry/my-app:1.0.0 --format '{{ json .SBOM }}'
```

Этот метод является предпочтительным, так как упрощает CI/CD-пайплайны.

### 3. CI/CD-пайплайн: Генерация, сканирование и исправление

Полный цикл управления уязвимостями может выглядеть так:

1. **Генерация SBOM (`Syft`):**

    ```bash
    syft my-app:1.2.3 -o cyclonedx-json > sbom.json
    ```

2. **Сканирование SBOM на уязвимости (`Grype`):**

    ```bash
    grype sbom:sbom.json -o json > report.json
    ```

3. **Автоматическое исправление (`Copacetic`):**

    ```bash
    copa patch -i my-app:1.2.3 -r report.json -t my-app:1.2.3-patched
    ```

## Дополнительная информация

**Связанные документы:** **[анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)** (общая теория SCA/SBOM), **[сканирование уязвимостей](./vulnerability_scanning.md)**, **[подписание образов](./image_signature_and_verification.md)**, **[безопасность публичных реестров](../Docker_registries/public_registry_security.md)**.

**CIS Docker Benchmark:** Требует генерации SBOM для всех образов (рекомендация 4.1).

**Инструменты:** `Syft` (генерация), `Grype` (сканирование SBOM), `Trivy` (универсальный сканер), `Copacetic` (автоматическое исправление уязвимостей), `docker buildx` (встроенная генерация).
