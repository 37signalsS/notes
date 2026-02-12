# Анализ зависимостей и SBOM

## Определения

*   **Анализ состава программного обеспечения (Software Composition Analysis, SCA)**: Процесс автоматического сканирования зависимостей проекта для выявления известных уязвимостей, конфликтов лицензий и проблем с качеством.
*   **Спецификация программного обеспечения (Software Bill of Materials, SBOM)**: Структурированный список всех компонентов, библиотек и модулей, которые требуются для сборки и запуска программного обеспечения. Это "инвентарный список" вашего ПО.

## Основные концепции

Отслеживание зависимостей — ключевая часть защиты цепочки поставок: большинство уязвимостей попадает в продукт через сторонние библиотеки, транзитивные цепочки и контейнерные образы. На практике применяются два комплементарных подхода: инвентаризация компонентов (SBOM) и анализ состава ПО (SCA) с сопоставлением базам уязвимостей.

### Категории инструментов

*   **Аудиторы экосистем:**
    *   JavaScript/Node.js: `npm audit`, `yarn audit`, `pnpm audit`
    *   Python: `pip-audit`, `safety`
    *   Go: `govulncheck`
    *   Rust: `cargo audit`
    *   Java: OWASP Dependency-Check, Maven/Gradle плагины
    *   PHP: `Composer audit`
*   **Универсальные SCA-сканеры и сканеры образов:**
    *   Trivy, Grype (уязвимости, лицензии), Syft (извлечение списка пакетов)
    *   osv-scanner (по базе OSV для множества экосистем)
*   **SBOM-генераторы и форматы:**
    *   Syft, CycloneDX CLI, SPDX tools; форматы CycloneDX и SPDX.
*   **Боты обновлений:**
    *   Dependabot, Renovate — автоматическое предложение обновлений зависимостей.

### Роль lock-файлов и пиннинга

Lock-файлы фиксируют точные версии и хэши, делая сборку воспроизводимой и сканируемой:

*   Node.js: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
*   Python: `requirements.txt` с хэшами или `pip-tools`/`Poetry lock`
*   Go: `go.mod`/`go.sum`, опционально vendoring
*   Rust: `Cargo.lock`
*   Java: версии в `pom.xml`/`gradle.lockfile`

Жесткая фиксация версий упрощает сопоставление с CVE/OSV и исключает «скрытые» апдейты.

### Базы уязвимостей и сопоставление

SCA-инструменты используют источники вроде NVD и OSV. Качество результатов зависит от точности идентификаторов пакетов, версии и контекста сборки (например, платформа и архитектура).

### Сравнение по задачам

| Задача                  | Инструменты                            | Экосистемы/Объекты  |
| ----------------------- | -------------------------------------- | ------------------- |
| Аудит зависимостей      | npm/yarn/pnpm audit, pip-audit, cargo audit, govulncheck | Языковые менеджеры  |
| Генерация SBOM          | Syft, CycloneDX CLI, SPDX tools        | Код, образы         |
| Матчинг уязвимостей    | Grype, Trivy, osv-scanner              | Универсально        |
| Полуавт. обновления     | Dependabot, Renovate                   | Git-репозитории     |
| Лицензии и комплаенс    | Trivy (license), FOSSology             | Исходники и образы  |

## Практические сценарии

### Быстрые примеры запуска

**Аудит экосистем:**
```css
npm ci && npm audit --production
pip-audit -r requirements.txt
cargo audit
govulncheck ./...
composer audit
```

**OSV и универсальные сканеры:**
```lua
osv-scanner --lockfile=package-lock.json
syft . -o cyclonedx-json > sbom.json
grype sbom:sbom.json --fail-on high
trivy fs . --scanners vuln,license --severity HIGH,CRITICAL
```

**Контейнерные образы:**
```lua
syft myimage:latest -o spdx-json > sbom.json
grype myimage:latest --fail-on critical
trivy image --ignore-unfixed myimage:latest
```

### Пример интеграции в CI (GitLab CI)

```yaml
stages:
  - sca

sca:
  image: alpine:3.19
  variables:
    GRYPE_DB_CACHE_DIR: .grype
  script:
    - apk add --no-cache curl
    - curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin
    - curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin
    - syft . -o cyclonedx-json > sbom.json
    - grype sbom:sbom.json --fail-on high --add-cpes-if-none
  cache:
    paths:
      - .grype
```

## Дополнительная информация

### Подход к внедрению

*   **Инвентаризация**: генерируйте SBOM для кода, образов и инфраструктурных артефактов; храните как артефакт сборки.
*   **Политики**: определяйте пороги отказа по severity, разрешенные/запрещенные лицензии, исключения с обоснованием и сроком действия.
*   **Базелайны**: фиксируйте текущие находки, блокируйте только регрессии, чтобы упростить внедрение в существующие проекты.
*   **Обновления**: подключайте Dependabot/Renovate, комбинируйте автоматические PR с SCA-гейтами.
*   **Кэширование и частота**: обновляйте базы уязвимостей регулярно, используйте кэш в CI для ускорения.
*   **Сквозное покрытие**: сканируйте и исходники, и бинарные артефакты, и контейнерные образы в реестре.
