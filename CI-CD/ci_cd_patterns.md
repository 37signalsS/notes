# Паттерны CI/CD

## Определения

**Паттерн CI/CD** — проверенный, эффективный и воспроизводимый подход к решению типовых задач в процессах непрерывной интеграции, доставки и развертывания. Применение паттернов направлено на минимизацию рисков при релизах, сокращение Time-to-Market и повышение стабильности систем. 

Паттерны являются прямыми решениями для соответствующих [анти-паттернов CI/CD](./ci_cd_antipatterns.md).

---

## Основные концепции

### Ключевые паттерны поставки

Для построения надежных и быстрых пайплайнов используются следующие паттерны:

1.  **Trunk-Based Development (TBD):** Модель разработки с единой основной веткой. Минимизирует "ад слияния" (merge hell) и ускоряет интеграцию. Подробности в **[Рабочие процессы в Git](../Git/git_workflows.md#3-trunk-based-development-tbd)**.
2.  **Feature Flags (фиче-флаги):** Управление доступностью кода во время выполнения. Позволяет разделять деплой (доставку кода) и релиз (открытие функционала пользователям). См. **[Обзор Feature Toggles](./Testing/feature_toggles/overview.md)**.
3.  **Fail Fast (быстрый отказ):** Проектирование пайплайна таким образом, чтобы самые быстрые проверки (линтинг, unit-тесты) выполнялись первыми. Это экономит ресурсы и дает разработчику немедленный фидбек.
4.  **Build Once, Deploy Many (сборка один раз):** Создание **Immutable Artifacts** (иммутабельных артефактов) на раннем этапе. Один и тот же образ проходит через все окружения, что исключает ошибки из-за разницы в процессе сборки. См. **[Управление артефактами](./artifact_management.md)**.
5.  **Separation of Config and Code:** Вынос настроек за пределы артефакта (Environment Variables, Secrets, ConfigMaps). Соответствует принципам [The Twelve-Factor App](https://12factor.net/config).
6.  **GitOps & Everything as Code:** Использование Git как единственного источника правды для инфраструктуры и состояний кластера. Пайплайн обновляет манифесты в Git, а агент (например, ArgoCD) синхронизирует состояние (Pull-модель).
7.  **Эфемерные окружения (Ephemeral Environments):** Автоматическое создание временных изолированных сред для каждого Merge Request. Позволяет тестировать фичу в реальных условиях до слияния в `main`.
8.  **Pipeline as Code & Centralized Templates:** Хранение конфигурации пайплайнов в коде с использованием общих шаблонов компании. Это стандарт **Platform Engineering**, упрощающий поддержку сотен микросервисов.
9.  **Shift-Left Security (DevSecOps):** Интеграция сканеров безопасности (SAST, SCA), генерации **SBOM** и подписи образов на этапе сборки. См. **[Обзор DevSecOps](./DevSecOps/devsecops_overview.md)**.
10. **Policy as Code (PaC):** Автоматизированная проверка политик безопасности и комплаенса (например, через OPA или Kyverno) внутри пайплайна. Позволяет блокировать деплой, если манифесты не соответствуют корпоративным стандартам.
11. **Supply Chain Security (SLSA):** Обеспечение целостности цепочки поставок через генерацию **Provenance** (доказательство происхождения) и **Attestation** (аттестация артефакта). Гарантирует, что артефакт был собран именно в доверенной CI-среде из конкретного коммита.
12. **Continuous Verification (CV):** Автоматизированная проверка состояния системы после деплоя (smoke-тесты, синтетический мониторинг), интегрированная в процесс CD. В случае деградации метрик срабатывает автоматический откат.
13. **Feedback Loops & DORA Metrics:** Автоматический сбор метрик эффективности (Deployment Frequency, Lead Time for Changes, Change Failure Rate, MTTR) непосредственно из инструментов CI/CD. См. **[Метрики DORA](./Core_Concepts/dora_metrics.md)**.

### Классификация паттернов

*   **Организационные:** Trunk-Based Development, Branch Protection, Developer Self-Service (IDP).
*   **Технические:** Immutable Artifacts, Fail Fast, Pipeline as Code, OIDC Authentication.
*   **Инфраструктурные:** GitOps, Ephemeral Environments, Infrastructure as Code (IaC), **[Runner Fleet Management](./runner-fleet-management.md)**, Configuration-as-Code Promotion, **Traditional Infrastructure Patterns (Bare Metal/VM)**.
*   **Безопасность:** Shift-Left Security, Secrets Management (Vault), Artifact Signing (Cosign), SLSA Attestations, Policy as Code, **Air-gapped Deployment Strategies**.
*   **Релизные:** Blue/Green, Canary, Dark Launches, Feature Toggles. См. **[Стратегии развертывания](./Deployment_Strategies/comparison.md)**.
*   **Операционные:** Continuous Verification, Auto-Rollback, Observability-driven Deployment.

---

## Практические сценарии

### Комплексный современный конвейер поставки

Типовой жизненный цикл изменения с применением паттернов 2026 года:

1.  **Этап проверки и изоляции (TBD + Fail Fast + PaC):**
    *   Разработчик коммитит в короткоживущую ветку.
    *   CI запускает линтеры, unit-тесты и **Policy-check** (проверка лимитов ресурсов, прав доступа в манифестах).
    *   Создается **Эфемерное окружение** для интеграционного тестирования.

2.  **Этап аттестации и сборки (Build Once + SLSA + DevSecOps):**
    *   После слияния с `main` собирается Docker-образ.
    *   Запускается SAST/SCA и генерация **SBOM**.
    *   CI генерирует **Provenance** и подписывает образ ключом через **OIDC** (без постоянных секретов).
    *   Образ считается "аттестованным" для Production.

3.  **Этап доставки и продвижения (GitOps + IaC Promotion):**
    *   CI обновляет Image Tag в Configuration Repo.
    *   GitOps-контроллер (ArgoCD) синхронизирует Staging.
    *   После успешных тестов на Staging происходит автоматическое продвижение (Promotion) изменений конфигурации в ветку/папку Production в Git.

4.  **Этап верификации и обратной связи (CV + DORA + Auto-Rollback):**
    *   Запускается **Canary-раскатка** на Production.
    *   Система **Continuous Verification** анализирует логи и метрики (Prometheus/Loki).
    *   Если `Change Failure Rate` растет или `Health Check` падает, выполняется **Auto-Rollback**.
    *   Данные о деплое автоматически уходят в дашборд **DORA** для анализа производительности команды.

---

## Дополнительная информация

### См. также

*   **[CI/CD: Обзор](./ci_cd_overview.md)** — фундаментальные определения и процессы.
*   **[CI/CD: Антипаттерны](./ci_cd_antipatterns.md)** — чего следует избегать при автоматизации.
*   **[Управление артефактами](./artifact_management.md)** — жизненный цикл, SBOM и хранение сборок.
*   **[Стратегии развертывания](./Deployment_Strategies/comparison.md)** — детальный разбор Canary, Blue/Green и других методов.
*   **[Традиционная инфраструктура](./Deployment_Strategies/traditional_infrastructure.md)** — паттерны деплоя для Bare Metal и VM.
*   **[Изолированные среды (Air-gapped)](./Core_Concepts/air_gapped_environments.md)** — стратегии синхронизации артефактов в закрытых контурах.
*   **[Метрики DORA](./Core_Concepts/dora_metrics.md)** — измерение эффективности процессов поставки.
*   **[Health Checks и Rollback](./Deployment_Strategies/deployment_health_checks_and_rollback.md)** — механизмы самовосстановления пайплайна.
