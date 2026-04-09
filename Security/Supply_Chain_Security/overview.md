# Supply Chain Security Overview

## Definitions

* **Software Supply Chain Security:** Комплекс мер по защите программных артефактов, их зависимостей и процессов сборки/доставки от умышленных или случайных уязвимостей. Цель — гарантировать, что в production используется только доверенное, проверенное и неизменённое ПО.
* **SLSA (Supply-chain Levels for Software Artifacts):** Фреймворк стандартов для обеспечения целостности и безопасности артефактов на всех этапах цепочки поставок. Определяет 4 уровня зрелости — от документирования сборки до полной изоляции и верификации. Подробнее: <https://slsa.dev/>.

## Basic Concepts

Безопасность цепочки поставок строится на четырёх ключевых практиках, каждая из которых закрывает определённый вектор атак:

```
Исходный код ──► Сборка ──► Артефакт ──► Развёртывание ──► Runtime
     │              │            │              │              │
  Зависимости   Целостность    Подпись       Политики       Мониторинг
  и SBOM        сборки                        допуска
```

### 1. Dependency & SBOM Analysis

Инвентаризация всех прямых и транзитивных зависимостей, их версий, лицензий. Сканирование на известные уязвимости (CVE) через базы NVD/OSV.

* **Инструменты:** SCA-сканеры (Trivy, Grype, osv-scanner), генераторы SBOM (Syft, CycloneDX CLI).
* **Подробнее:** [Dependency and SBOM Analysis](./dependency_and_sbom_analysis.md).

### 2. Build Integrity

Гарантия того, что артефакты собираются из доверенного исходного кода в предсказуемой и изолированной (герметичной) среде. Воспроизводимость сборок.

* **Практики:** Hermetic builds, reproducible builds, provenance-аттестации, уровни SLSA.
* **Подробнее:** [Build Integrity](./build_integrity.md).

### 3. Artifact Signing

Криптографическая подпись артефактов (образы, SBOM, аттестации, Helm-чарты), доказывающая происхождение от доверенного источника и неизменность.

* **Модели:** Keyless (OIDC/Sigstore), GPG/PKI.
* **Подробнее:** [Artifact Signing](./artifact_signing.md).

### 4. Runtime Security

Мониторинг поведения приложения в реальном времени после развёртывания для обнаружения аномалий, не выявленных статическими анализаторами.

* **Инструменты:** [Falco](../Tools/falco.md), eBPF-мониторинг, политики сетевого взаимодействия.
* **Подробнее:** [Falco: Runtime Security](../Tools/falco.md).

### Уровни SLSA (сводная таблица)

| Уровень | Требование | Защита от | Этап |
| :--- | :--- | :--- | :--- |
| **SLSA 1** | Документированный процесс сборки | Случайных ошибок | Build |
| **SLSA 2** | Hosted build-система, provenance | Несанкционированных изменений | Build |
| **SLSA 3** | Герметичная сборка, изолированная среда | Подмены зависимостей | Build |
| **SLSA 4** | Двухэтапная верификация, воспроизводимость | Компрометации сборочной инфраструктуры | Build + Sign |

## Practical Scenarios

### Аудит конфигураций безопасности

| Область | Инструмент | Назначение |
| :--- | :--- | :--- |
| **Аудит образов** | `Dive` | Анализ слоёв Docker-образа, оптимизация поверхности атаки |
| **Аудит хоста** | `Docker Bench Security` | Проверка конфигурации Docker-демона (CIS Benchmarks) |
| **Анализ IaC** | `tfsec`, `terrascan`, `checkov` | Статический анализ Dockerfile, Terraform, K8s-манифестов |

### Построение защищённого пайплайна

Типичный CI/CD-пайплайн с практиками Supply Chain Security:

1. **SCA-сканирование** зависимостей → блокировка при CRITICAL CVE.
2. **Hermetic build** с фиксацией по дайджесту → генерация provenance + SBOM.
3. **Keyless-подпись** артефакта через Sigstore → запись в Rekor.
4. **Верификация подписи** перед развёртыванием → admission-политика (Kyverno).
5. **Runtime-мониторинг** → Falco/eBPF для обнаружения аномалий.

## Additional Information

### Стандарты и фреймворки

* **SLSA:** <https://slsa.dev/> — уровни зрелости безопасности цепочки поставок.
* **OWASP SCVS:** [Software Component Verification Standard](https://owasp.org/www-project-software-component-verification-standard/) — контрольные требования к верификации компонентов.
* **NIST SSDF:** [Secure Software Development Framework](https://csrc.nist.gov/projects/ssdf) — рекомендации безопасной разработки.

### Связанные документы

* [Dependency and SBOM Analysis](./dependency_and_sbom_analysis.md) — SCA, lock-файлы, генерация SBOM
* [Build Integrity](./build_integrity.md) — воспроизводимые сборки, SLSA provenance
* [Artifact Signing](./artifact_signing.md) — Sigstore/Cosign, keyless-подпись
* [Falco: Runtime Security](../Tools/falco.md) — мониторинг аномалий в runtime
* [Docker SBOM](../../Docker/Docker_security/docker_sbom.md) — SBOM для контейнерных образов
* [Безопасность публичных реестров](../../Docker/Docker_registries/public_registry_security.md) — угрозы Docker Hub
