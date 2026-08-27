# Типичный поток пайплайна

## Определения

- **Поток пайплайна (Pipeline Workflow)** — логически упорядоченная последовательность этапов (Stages) и задач (Jobs), обеспечивающая автоматизированную доставку изменений кода от момента фиксации (commit) до развертывания в продуктивной среде. Поток описывается как код (Pipeline as Code) и выполняется на собственных (self-hosted) раннерах.
- **Ворота качества (Quality Gates)** — автоматизированные точки контроля в пайплайне, которые проверяют соответствие кода установленным критериям (покрытие тестами, отсутствие уязвимостей, соблюдение лимитов FinOps). Если критерии не выполнены, продвижение пайплайна блокируется.
- **Направленный ациклический граф (Directed Acyclic Graph, DAG)** — метод организации пайплайна, при котором задачи запускаются сразу после выполнения своих прямых зависимостей, не дожидаясь завершения всей стадии. Сокращает критический путь выполнения.
- **Эфемерные окружения (Ephemeral Environments / Preview Apps)** — временные изолированные экземпляры приложения, создаваемые пайплайном «на лету» (обычно для Merge Request) для функционального тестирования и ревью, с последующим автоматическим удалением.
- **Иммутабельный артефакт (Immutable Artifact)** — собранный один раз бинарный образ/пакет, который продвигается по средам без пересборки. Гарантирует, что в production попадает именно проверенная версия.
- **Аттестация и происхождение (Provenance / Attestation)** — криптографически подписанные метаданные о том, как, где и из какого исходного кода собран артефакт (уровни **SLSA**). Подтверждают целостность цепочки поставок.
- **OIDC (OpenID Connect)** — протокол беспарольной аутентификации пайплайна во внешних системах через получение временных токенов на основе установленного доверия (trust). Исключает долгоживущие статические секреты.
- **SLO / Error Budget (SRE)** — целевой уровень надёжности сервиса и допустимая доля его нарушений. В пайплайне используются для автоматического разрешения canary-релизов и триггера отката.

## Основные концепции

### Принципы эффективного пайплайна

Современный пайплайн должен быть быстрым, безопасным и прозрачным:

1.  **Fail-Fast (Падай быстро):** Самые быстрые и критические проверки (линтеры, Unit-тесты) выполняются в первую очередь. Это обеспечивает мгновенную обратную связь разработчику и экономит ресурсы раннеров.
2.  **Параллелизм и DAG:** Использование директив `needs` (в GitLab CI) для построения графа зависимостей, что сокращает общее время выполнения за счет обхода синхронных барьеров стадий.
3.  **Иммутабельность артефактов:** Артефакт (например, контейнерный образ) собирается один раз на ранних этапах и без изменений продвигается через все среды (Staging → Prod).
4.  **Аттестация и SBOM:** Генерация программного счета материалов (**SBOM**, форматы CycloneDX или SPDX) и подпись артефакта (уровни **SLSA**) для обеспечения безопасности цепочки поставок.
5.  **OIDC-First (OpenID Connect):** Отказ от статических секретов в пользу временных токенов при взаимодействии с внутренними сервисами и хранилищами секретов (**[Vault / менеджер секретов](../DevSecOps/secrets_management.md)**).
6.  **Shift-Left Security & FinOps:** Интеграция сканеров безопасности и инструментов оценки стоимости инфраструктуры на этапе сборки. Подробнее в **[Оптимизации затрат в CI/CD](./cost-optimization.md)**.

### Структура канонического пайплайна

Жизненный цикл изменений в современном конвейере:

1.  **Валидация (Validate / Lint)**
    *   Проверка стиля кода (Linters) и форматирования.
    *   Проверка IaC-манифестов (Terraform, Ansible, манифесты оркестратора).
    *   **Secret Detection:** Поиск случайно закоммиченных паролей и токенов.
    *   *DevOps-замечание:* самый дешёвый этап по ресурсам; должен завершаться за секунды, чтобы не задерживать обратную связь.
2.  **Тестирование (Test)**
    *   Unit-тестирование с генерацией отчетов о покрытии (Coverage).
    *   Интеграционные тесты с изоляцией зависимостей (например, через **Testcontainers**).
    *   *Оптимизация:* применение **Test Impact Analysis (TIA)** — запуск только тестов, затрагивающих изменённые файлы.
3.  **Сборка и Аттестация (Build & Attest)**
    *   Сборка бинарных файлов или образов (воспроизводимая сборка, Reproducible Build).
    *   Генерация **SBOM** (CycloneDX или SPDX).
    *   Подпись артефакта (Cosign/Sigstore) и формирование **Provenance**.
4.  **Безопасность (Security Scan)**
    *   **SCA (Software Composition Analysis):** Поиск уязвимостей в сторонних библиотеках.
    *   **SAST:** Статический анализ безопасности кода.
    *   **Container Scanning:** Поиск CVE в слоях контейнерного образа (например, Trivy).
5.  **Финансовый контроль (FinOps Gate)**
    *   Автоматическая оценка изменения стоимости инфраструктуры при изменении IaC-кода. Блокировка при превышении бюджета. См. **[Оптимизацию затрат](./cost-optimization.md)**.
6.  **Развертывание в Preview (Deploy Preview)**
    *   Автоматическое создание эфемерного окружения для ветки с ограничением времени жизни (TTL).
    *   Запуск динамических тестов (**DAST**) и сквозных сценариев (**E2E**).
7.  **Верификация после слияния (Post-merge Verification)**
    *   Повторный прогон пайплайна в ветке `main` после слияния. Гарантирует, что интеграция прошла успешно и код готов к выкатке.
8.  **Продуктивное развертывание (Production Deploy)**
    *   Выкатка через **GitOps** (Pull Model, см. **[пример пайплайна GitOps](../../GitOps/gitops_pipeline_example.md)**) или Push-стратегии (Canary, Blue-Green — см. **[Стратегии развертывания](./deployment_strategies.md)**).
    *   **Автоматическая верификация после деплоя:** системы мониторинга на базе **SLO/Error Budget** анализируют метрики (Error Rate, Latency) сразу после выкатки и автоматически инициируют **Rollback** при аномалиях.

### Роль платформенной команды и SysAdmin

Надёжность пайплайна зависит не только от YAML, но и от инфраструктуры, которую обслуживает SysAdmin / Platform-команда:

- **Парк раннеров (Runner Fleet):** изоляция (контейнерные/витруальные исполнители), квоты и политики распределения ресурсов, вытесняемые (best-effort) раннеры для неприоритетных задач. См. **[Управление парком раннеров](../runner-fleet-management.md)**.
- **Хранение артефактов и кэша:** политики ротации (retention), очистка устаревших образов в реестре, внешние объектные хранилища (MinIO, Nexus) для обмена кэшем между раннерами.
- **Очистка эфемерных сред:** гарантированный `on_stop` и `auto_stop_in`, чтобы избежать «утечки» ресурсов от заброшенных MR.
- **Секреты:** централизованное хранение и ротация через **[менеджер секретов](../DevSecOps/secrets_management.md)**, минимальные права (least privilege).

### SRE-подход: SLO, Error Budget и MTTR в пайплайне

- **SLO / SLI / Error Budget** задают критерии успешности релиза (см. **[Концепции SRE](../../Concepts/sre_concepts_main.md)**).
- **Автоматический откат (Auto-Rollback):** при исчерпании Error Budget в окне наблюдения canary-релиз откатывается без участия человека.
- **MTTR (Mean Time To Recovery):** короткие, обратимые деплои и готовые процедуры отката снижают время восстановления.
- **DORA-метрики** (Deployment Frequency, Lead Time, Change Failure Rate, Time to Restore) измеряют эффективность потока — см. **[Метрики DORA](./dora_metrics.md)**.

### Наблюдаемость пайплайна

Сбор метрик и трассировок самих задач CI/CD (длительность этапов, «мигающие» flaky-тесты, загрузка раннеров) позволяет выявлять узкие места. Подробнее в **[Наблюдаемости пайплайнов](./pipeline_observability.md)**.

## Практические сценарии

### Реализация оптимизированного пайплайна (GitLab CI)

Пример конфигурации с использованием DAG, кэширования и OIDC:

```yaml
stages:
  - validate
  - test
  - build
  - security
  - deploy-preview
  - deploy-prod

# Глобальные настройки кэша
default:
  cache:
    key: ${CI_COMMIT_REF_SLUG}
    paths:
      - .npm/
      - vendor/

# 1. Валидация (Fail-Fast)
lint_code:
  stage: validate
  script:
    - npm run lint
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# 2. Тестирование
unit_tests:
  stage: test
  script:
    - npm test -- --coverage
  artifacts:
    reports:
      junit: report.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

# 3. Сборка с DAG и OIDC
build_image:
  stage: build
  needs: ["unit_tests"] # DAG: запускается сразу после тестов
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.internal
  script:
    - # Получение временных прав через OIDC в Vault
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - syft . -o cyclonedx-json=sbom.json
  artifacts:
    paths: [sbom.json]

# 4. Сканирование безопасности
security_scan:
  stage: security
  needs: ["build_image"]
  script:
    - trivy image --exit-code 1 $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
    - trivy sbom sbom.json

# 5. Эфемерное окружение (self-hosted, docker compose)
deploy_review:
  stage: deploy-preview
  script:
    - docker compose -f docker-compose.review.yml -p "review-$CI_COMMIT_REF_SLUG" up -d
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

stop_review:
  stage: deploy-preview
  script:
    - docker compose -f docker-compose.review.yml -p "review-$CI_COMMIT_REF_SLUG" down -v
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  when: manual

# 6. Прод (с ручным подтверждением)
deploy_prod:
  stage: deploy-prod
  when: manual
  script:
    - ./deploy.sh production $CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Пример: OIDC-доступ к Vault без статических секретов (DevSecOps / SysAdmin)

```yaml
fetch_secret:
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.internal
  script:
    - export TOKEN=$(vault write -field=token auth/jwt/login role=ci jwt=$VAULT_ID_TOKEN)
    - export DB_PASSWORD=$(vault read -field=password secret/ci/db)
    # секрет используется только в рантайме задачи и не попадает в логи
```

### Пример: Canary-выкатка с автооткатом по SLO (SRE)

```yaml
deploy_canary:
  stage: deploy
  script:
    - docker compose -f docker-compose.canary.yml up -d   # 10% трафика у балансировщика
  environment:
    name: production-canary

verify_slo:
  stage: verify
  needs: [deploy_canary]
  script:
    - check-slo --window 10m --threshold 99.9   # падает при нарушении SLO

promote:
  stage: deploy
  needs: [verify_slo]
  when: on_success
  script:
    - docker compose -f docker-compose.prod.yml up -d   # расширяем canary до 100%

rollback:
  stage: deploy
  when: on_failure
  script:
    - docker compose -f docker-compose.prod.yml up -d   # возврат к стабильной версии
```

### Стратегии оптимизации пайплайна

1.  **Test Impact Analysis (TIA):** Запуск только тех тестов, которые затрагивают измененные файлы. Сокращает время `test` стадии на 50–80%.
2.  **Использование BuildKit:** Оптимизация сборки контейнерных образов через кэширование слоев и параллельную сборку стадий Multi-stage.
3.  **Динамическая генерация пайплайнов:** Для монорепозиториев — создание конфигурации CI «на лету» только для измененных модулей.
4.  **Упреждающее кэширование:** Использование внешних объектных хранилищ (MinIO, Nexus) для обмена кэшем между разными раннерами.
5.  **Шардинг и матричный параллелизм:** Разбиение большого набора тестов на параллельные задачи (`parallel: matrix`) для сокращения общего времени.
6.  **Вытесняемые раннеры (best-effort):** Неприоритетные задачи (например, ночные E2E) выполняются на дешёвых вытесняемых узлах, что снижает стоимость владения (см. **[Оптимизацию затрат](./cost-optimization.md)**).

## См. также

- **[Глоссарий пайплайнов](./pipeline_glossary.md)** — детальные определения терминов.
- **[Стратегии развертывания](./deployment_strategies.md)** — методы минимизации рисков при выкатке.
- **[Метрики DORA](./dora_metrics.md)** — оценка эффективности потока поставки.
