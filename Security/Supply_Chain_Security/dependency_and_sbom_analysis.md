# Dependency and SBOM Analysis

## Definitions

* **SCA (Software Composition Analysis):** Автоматическое сканирование зависимостей проекта для выявления известных уязвимостей (CVE), конфликтов лицензий и проблем качества.
* **SBOM (Software Bill of Materials):** Детальный машиночитаемый перечень всех компонентов, библиотек и зависимостей в приложении: прямых и транзитивных, с версиями, лицензиями, хешами и идентификаторами (PURL, CPE).
* **Lock-файл:** Файл фиксации точных версий и хешей зависимостей (`package-lock.json`, `go.sum`, `Cargo.lock`). Основа воспроизводимости сборок и SCA-сканирования.

## Basic Concepts

Отслеживание зависимостей — ключевая часть [безопасности цепочки поставок](./overview.md). Большинство уязвимостей попадает в продукт через сторонние библиотеки, которые разработчики не подключали напрямую.

### SBOM vs Манифесты зависимостей

| Аспект | Манифест (`package.json`, `pom.xml`) | SBOM |
| :--- | :--- | :--- |
| **Тип зависимостей** | Прямые | Прямые + транзитивные |
| **Runtime-компоненты** | Нет | Системные библиотеки, пакеты ОС |
| **Метаданные** | Версии, диапазоны | Хеши, лицензии, PURL, CPE |
| **Безопасность** | Управление версиями | Основа для мониторинга CVE/NVD |

### Форматы SBOM

| Формат | Фокус | Разработчик | Стандарт |
| :--- | :--- | :--- | :--- |
| **SPDX** | Лицензии | Linux Foundation | ISO/IEC 5962:2021 |
| **CycloneDX** | Безопасность, уязвимости | OWASP | OWASP standard |

### Категории инструментов

| Категория | Примеры | Назначение |
| :--- | :--- | :--- |
| **Аудиторы экосистем** | `npm audit`, `cargo audit`, `pip-audit` | Скан зависимостей в конкретной экосистеме |
| **Универсальные SCA** | Trivy, Grype, osv-scanner | Анализ кода, образов, SBOM |
| **SBOM-генераторы** | Syft, Trivy, CycloneDX CLI | Создание отчётов в SPDX/CycloneDX |
| **Платформы мониторинга** | Dependency-Track | Хранение и непрерывный мониторинг SBOM |
| **Боты обновлений** | Dependabot, Renovate | Автоматические PR для обновления зависимостей |

### Базы уязвимостей

SCA-инструменты сопоставляют компоненты с базами:

* **NVD (National Vulnerability Database)** — национальная база CVE.
* **OSV (Open Source Vulnerabilities)** — открытый формат, покрывает Go, Rust, Python, npm.
* **GitHub Advisory Database** — advisories для экосистем GitHub.

## Practical Scenarios

### Аудит зависимостей в коде

```bash
# JavaScript/Node.js
npm audit --production

# Python
pip-audit -r requirements.txt

# Go
govulncheck ./...

# Rust
cargo audit
```

### Генерация SBOM и сканирование образа

```bash
# 1. Генерация SBOM в формате CycloneDX
syft my-image:latest -o cyclonedx-json > sbom.json

# 2. Сканирование SBOM на уязвимости
grype sbom:sbom.json --fail-on high

# Альтернатива: Trivy сканирует образ напрямую
trivy image --ignore-unfixed --severity HIGH,CRITICAL my-image:latest
```

### Интеграция SCA в CI/CD (GitLab CI)

```yaml
sca-job:
  image: aquasec/trivy:latest
  script:
    # Сканирование файловой системы на уязвимости и лицензии
    - trivy fs --severity HIGH,CRITICAL --exit-code 1 .
  cache:
    paths:
      - .trivy/cache
```

### Безопасная установка зависимостей в CI/CD: `npm ci` вместо `npm install`

**Проблема:** `npm install` в пайплайне CI/CD обращается к живому реестру npm и заново разрешает диапазоны версий из `package.json`, создавая окно уязвимости для подмены пакета.

**Сценарий атаки:**

1. В `package.json` указан диапазон `"axios": "^1.7.9"`
2. `npm install` может установить более новую версию из этого диапазона
3. Злоумышленник публикует вредоносную версию в пределах semver range
4. CI/CD автоматически подхватывает скомпрометированную зависимость

**Решение — `npm ci`:**

| Характеристика | `npm install` | `npm ci` |
| :--- | :--- | :--- |
| **Источник версий** | Разрешает диапазоны из `package.json` | Строго из `package-lock.json` |
| **Обращение к реестру** | Да | Нет (только при отсутствии в кеше) |
| **Изменение lock-файла** | Возможно | Нет — ошибка при рассинхроне |
| **Поведение с `node_modules`** | Согласовывает существующее | Удаляет и устанавливает заново |
| **Безопасность** | Низкая | Высокая (детерминированная установка) |

**Правила работы с lock-файлом:**
* **Хранить в репозитории:** `package-lock.json` должен быть закоммичен и версионирован
* **Обновлять осознанно:** `npm update` локально, затем коммит обновлённого lock-файла
* **Не генерировать в CI:** CI/CD не должен создавать или модифицировать lock-файл
* **Ревью изменений:** Обновление lock-файла требует code review

### Автоматическое обновление зависимостей (Dependabot)

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "gomod"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
```

## Additional Information

### Рекомендации по внедрению

* **Инвентаризация:** Регулярно генерируйте SBOM для всех артефактов и храните их вместе со сборками. Подписывайте SBOM как аттестации — [подпись артефактов](./artifact_signing.md).
* **Политики:** Определите пороги срабатывания (блокировка сборки при CRITICAL) и управляйте исключениями.
* **Автоматизация:** SCA-сканирование на ранних этапах CI/CD + боты (Dependabot/Renovate) для обновлений.
* **Сквозное покрытие:** Сканируйте исходный код, артефакты и контейнерные образы в реестре.

### Связанные документы

* [SBOM для Docker](../../Docker/Docker_security/docker_sbom.md) — генерация SBOM из контейнерных образов
* [Сканирование уязвимостей](../../Docker/Docker_security/vulnerability_scanning.md) — Trivy, Grype, Clair
* [Подпись артефактов](./artifact_signing.md) — подпись SBOM и аттестаций
* [Контроль целостности сборки](./build_integrity.md) — воспроизводимые сборки, lock-файлы
