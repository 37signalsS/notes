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

1. **Fail-Fast (Падай быстро):** Самые быстрые и критические проверки (линтеры, Unit-тесты) выполняются в первую очередь. Это обеспечивает мгновенную обратную связь разработчику и экономит ресурсы раннеров.
2. **Параллелизм и DAG:** Использование директив `needs` (в GitLab CI) для построения графа зависимостей, что сокращает общее время выполнения за счет обхода синхронных барьеров стадий.
3. **Иммутабельность артефактов:** Артефакт (например, контейнерный образ) собирается один раз на ранних этапах и без изменений продвигается через все среды (Staging → Prod).
4. **Аттестация и SBOM:** Генерация программного счета материалов (**SBOM**, форматы CycloneDX или SPDX) и подпись артефакта (уровни **SLSA**) для обеспечения безопасности цепочки поставок.
5. **OIDC-First (OpenID Connect):** Отказ от статических секретов в пользу временных токенов при взаимодействии с внутренними сервисами и хранилищами секретов (**[Vault / менеджер секретов](../DevSecOps/secrets_management.md)**).
6. **Shift-Left Security & FinOps:** Интеграция сканеров безопасности и инструментов оценки стоимости инфраструктуры на этапе сборки. Подробнее в **[Оптимизации затрат в CI/CD](./cost-optimization.md)**.

### Каноническая структура пайплайна

Жизненный цикл изменений в современном конвейере:

1. **Валидация (Validate / Lint)**
   - Проверка стиля кода (Linters) и форматирования.
   - Проверка IaC-манифестов (Terraform, Ansible, манифесты оркестратора).
   - **Secret Detection:** Поиск случайно закоммиченных паролей и токенов.
   - *DevOps-замечание:* самый дешёвый этап по ресурсам; должен завершаться за секунды, чтобы не задерживать обратную связь.
2. **Тестирование (Test)**
   - Unit-тестирование с генерацией отчетов о покрытии (Coverage).
   - Интеграционные тесты с изоляцией зависимостей (например, через **Testcontainers**).
   - *Оптимизация:* применение **Test Impact Analysis (TIA)** — запуск только тестов, затрагивающих изменённые файлы.
3. **Сборка и Аттестация (Build & Attest)**
   - Сборка бинарных файлов или образов (воспроизводимая сборка, Reproducible Build).
   - Генерация **SBOM** (CycloneDX или SPDX).
   - Подпись артефакта (Cosign/Sigstore) и формирование **Provenance**.
4. **Безопасность (Security Scan)**
   - **SCA (Software Composition Analysis):** Поиск уязвимостей в сторонних библиотеках.
   - **SAST:** Статический анализ безопасности кода.
   - **Container Scanning:** Поиск CVE в слоях контейнерного образа (например, Trivy).
5. **Финансовый контроль (FinOps Gate)**
   - Автоматическая оценка изменения стоимости инфраструктуры при изменении IaC-кода. Блокировка при превышении бюджета. См. **[Оптимизацию затрат](./cost-optimization.md)**.
6. **Развертывание в Preview (Deploy Preview)**
   - Автоматическое создание эфемерного окружения для ветки с ограничением времени жизни (TTL).
   - Запуск динамических тестов (**DAST**) и сквозных сценариев (**E2E**).
7. **Верификация после слияния (Post-merge Verification)**
   - Повторный прогон пайплайна в ветке `main` после слияния. Гарантирует, что интеграция прошла успешно и код готов к выкатке.
8. **Продуктивное развертывание (Production Deploy)**
   - Выкатка через **GitOps** (Pull Model, см. **[пример пайплайна GitOps](../../GitOps/gitops_pipeline_example.md)**) или Push-стратегии (Canary, Blue-Green — см. **[Стратегии развертывания](./deployment_strategies.md)**).
   - **Автоматическая верификация после деплоя:** системы мониторинга на базе **SLO/Error Budget** анализируют метрики (Error Rate, Latency) сразу после выкатки и автоматически инициируют **Rollback** при аномалиях.

### Роли и ответственность в CI/CD

| Задача / Фаза | DevOps | SRE | Sysadmin |
|---|---|---|---|
| Проектирование пайплайна | Разработка стадий, шаблонов, политик | Определение SLO/Error Budget для пайплайна | Выделение ресурсов раннеров, квот, сетевой политики |
| Безопасность | Интеграция сканеров, OIDC, политик | Настройка ворот качества, автоотката | Управление секретами, least privilege, изоляция раннеров |
| Наблюдаемость | Метрики DORA, алерты, dashboards | SLO пайплайна, трассировка, burn rate | Инфраструктурные метрики раннеров, среда исполнения |
| Оптимизация | Кэширование, параллелизм, TIA | Снижение flaky-тестов, MTTR | Правоуправление, bin-packing, энергоэффективность |
| Инциденты | Исправление конфигурации, hotfix | Разбор инцидентов, post-mortem | Восстановление инфраструктуры, сети, хранилищ |

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

1. **Test Impact Analysis (TIA):** Запуск только тех тестов, которые затрагивают измененные файлы. Сокращает время `test` стадии на 50–80%.
2. **Использование BuildKit:** Оптимизация сборки контейнерных образов через кэширование слоев и параллельную сборку стадий Multi-stage.
3. **Динамическая генерация пайплайнов:** Для монорепозиториев — создание конфигурации CI «на лету» только для измененных модулей.
4. **Упреждающее кэширование:** Использование внешних объектных хранилищ (MinIO, Nexus) для обмена кэшем между разными раннерами.
5. **Шардинг и матричный параллелизм:** Разбиение большого набора тестов на параллельные задачи (`parallel: matrix`) для сокращения общего времени.
6. **Вытесняемые раннеры (best-effort):** Неприоритетные задачи (например, ночные E2E) выполняются на дешёвых вытесняемых узлах, что снижает стоимость владения (см. **[Оптимизацию затрат](./cost-optimization.md)**).

## Операции и команды

### Валидация и отладка пайплайна

```bash
# Проверка YAML-синтаксиса через CI Lint API (GitLab)
curl --request POST "https://gitlab.example.com/api/v4/projects/123/ci/lint" \
  -H "PRIVATE-TOKEN: <token>" \
  -d "content=$(cat .gitlab-ci.yml)"
# → {"status":"valid","errors":[],"warnings":[]}
```

```bash
# Локальная валидация синтаксиса YAML через yamllint
yamllint .gitlab-ci.yml
# → .gitlab-ci.yml
# →  1:1  warning  missing-start-block  missing start block document
# →  2:1  error    wrong-indentation  wrong indentation (expected 2 but found 0)  (indentation)
```

```bash
# Запуск пайплайна для конкретного MR через API
curl --request POST --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/123/merge_requests/45/pipelines" \
  -d "ref=feature-branch"
# → {"id":678,"status":"pending","web_url":"https://gitlab.example.com/.../p/678"}
```

### Управление задачами и стадиями

```bash
# Повторный запуск упавшей задачи (job) через API
curl --request POST --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/123/jobs/12345/retry"
# → {"id":12350,"status":"pending","stage":"test"}
```

```bash
# Отмена запущенного пайплайна через API
curl --request POST --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/123/pipelines/678/cancel"
# → {"id":678,"status":"canceled"}
```

```bash
# Просмотр логов конкретной задачи через API
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/123/jobs/12350/trace"
# → [0;33mWARNING:[0m npm audit found 2 vulnerabilities
# → [0;32mSUCCESS:[0m Build completed in 1m24s
```

### Визуализация DAG и зависимостей

```bash
# Получение DAG пайплайна через GitLab API (формат Mermaid)
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/123/pipelines/678/dag"
# → {"status":"success","dags":{"mermaid":"graph TD; A[lint_code] --> B[unit_tests]; B --> C[build_image]; ..."}}
```

```bash
# Экспорт DAG в PNG через Mermaid CLI (mmdc)
echo 'graph TD; A[lint_code] --> B[unit_tests]; B --> C[build_image]' | mmdc -o pipeline-dag.png
# → pipeline-dag.png written (3 nodes, 2 edges)
```

### Очистка окружений и артефактов

```bash
# Принудительная остановка зависшего review-окружения
docker compose -f docker-compose.review.yml -p "review-stale-branch" down -v
# → Stopping review-stale-branch ... done
# → Removing review-stale-branch ... done
```

```bash
# Очистка устаревших тегов в registry (оставить последние 10)
curl --request DELETE --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/123/registry/repositories/456/tags?order_by=created_at&sort=desc&per_page=10&keep=N"
# → {"status":"success","message":"2 tags deleted"}
```

### Мониторинг очереди и раннеров

```bash
# Проверка статуса всех раннеров
gitlab-runner list
# → runner-001: active, idle=0, running=3/5 (docker+machine)
# → runner-002: active, idle=2, running=1/5 (docker)
# → runner-003: paused, idle=0, running=0/5
```

```bash
# Просмотр очереди задач, ожидающих раннер
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/123/jobs?scope[]=pending"
# → [{"id":999,"status":"pending","stage":"test","created_at":"2026-09-27T10:00:00Z"}, ...]
```

## Типичные ошибки и решения

| Симптом | Причина | Решение | Роль |
|---|---|---|---|
| Пайплайн зависает на стадии `validate` | Линтер зависает на большом volume изменений, нет ограничения по памяти/таймауту | Установить `timeout` для задачи, добавить `ulimit` в конфиг раннера, запускать линтер только на изменённых файлах | DevOps |
| `needs` создаёт циклическую зависимость | Две или более задачи ссылаются друг на друга через `needs`, образуя цикл в DAG | Убрать лишнюю `needs`, разбить на отдельные стадии или использовать `stage` для последовательности | DevOps |
| Раннер не provisioning (status `pending` > 10 мин) | Исчерпаны ресурсы Kubernetes (CPU/memory), нет свободных слотов | Проверить `kubectl get nodes` и `kubectl describe node`, проверить ResourceQuotas, проверить PriorityClasses | Sysadmin |
| Ошибка `403 Forbidden` при скачивании артефакта | Истёк токен registry, отсутствуют права pull у проекта | Обновить `image:policy`, проверить права проекта в registry, перевыпустить deploy token | DevOps |
| OIDC-токен не передаётся в задачу | `id_tokens` не сконфигурирован на уровне задачи или неверный `aud` | Проверить синтаксис `id_tokens` в YAML, убедиться что доверие (trust) настроено на стороне Vault | DevOps / Sysadmin |
| Canary-верификация падает по SLO | Падение Error Rate или Latency сразу после выкатки 10% трафика | Откатить canary, собрать трейсы (`pipeline_observability.md`), проверить кэш/подключение к зависимостям | SRE |
| Post-merge верификация падает при `main` | Несовместимость изменений, неработающие тесты, неверный секрет | Проверить diff между MR и `main`, проверить что все секреты доступны в `main`-пайплайне | DevOps |
| Эфемерное окружение не удаляется по TTL | `on_stop` не определен, нет прав на удаление namespace/resources | Добавить задачу `stop_review` с `action: stop`, проверить права сервис-аккаунта на удаление | Sysadmin |
| Flaky-тест мешает пайплайну | Тест зависит от внешнего состояния, гонки, таймауты сети | Перенести тест в карантин (flaky quarantine), добавить retry на уровне джобы, исправить корневую причину | DevOps / SRE |
| SBOM не генерируется или пустой | Сканер (syft/trivy) не имеет доступа к контексту сборки, образ не существует | Проверить что `docker build` завершился успешно, добавить `docker save` или использовать `--dir` для syft | DevOps |
| Артефакт пересобирается при каждом прогоне | Неправильный `cache` key, отсутствие кэширования зависимостей | Использовать стабильный `cache:key` (например, хеш `package-lock.json`), проверить пути в `cache:paths` | DevOps |
| Пайплайн падает с `403 Forbidden` на Registry | Истёк registry token, отсутствуют права push/pull | Обновить токен, проверить `image:policy` и права проекта | DevOps |

## Лучшие практики

### Архитектура пайплайна

- **Гранулярность стадий:** Каждая стадия должна отвечать за одно логическое действие (валидация, тест, сборка, безопасность, деплой). Не объединяйте несвязанные проверки в одну стадию — это усложняет параллелизм и DAG.
- **Fail-Fast в приоритете:** Самые быстрые проверки (линтеры, статические анализаторы) размещайте в первой стадии. Это экономит ресурсы раннеров и даёт разработчику обратную связь за секунды.
- **Одна сборка — много среде:** Артефакт собирается один раз на ранней стадии и продвигается по окружениям без пересборки (Build Once, Deploy Many). Это исключает различия между staging и production.

### Надёжность и отказоустойчивость

- **Иммутабельные артефакты:** Используйте теги на основе коммита SHA или семантического версионирования, а не `latest`. Запретите перезапись тегов в реестре.
- **Аттестация и SLSA:** Подписывайте артефакты и генерируйте SBOM на этапе сборки. Это позволяет верифицировать происхождение бинарника в production без доступа к исходному коду.
- **SLO-ориентированные ворота:** Встраивайте проверки SLO/Error Budget в пайплайн так, чтобы canary-релиз автоматически откатывался при нарушении целевых метрик.
- **Эфемерность окружений:** Каждый MR получает временное окружение с жёстким TTL. Автоматическая очистка предотвращает «утечку» ресурсов и снижает нагрузку на инфраструктуру.

### Безопасность

- **OIDC-First:** Откажитесь от статических секретов в YAML. Используйте `id_tokens` для получения временных прав в Vault, реестре или облачных сервисах.
- **Shift-Left Security:** Сканеры SCA, SAST и Container Scanning должны выполняться на этапе сборки, а не после деплоя. Блокируйте пайплайн при критических уязвимостях.
- **Least Privilege:** Сервис-аккаунты и роли, используемые пайплайном, должны иметь минимально необходимые права. Изолируйте раннеры по проектам и уровням доверия.

### Производительность

- **DAG вместо последовательных стадий:** Используйте `needs` для параллельного выполнения независимых задач. Визуализируйте граф зависимостей для поиска узких мест.
- **Кэширование зависимостей:** Настройте кэширование на уровне runner'ов или используйте внешние прокси (Nexus, MinIO) для обмена кэшем между разными исполнителями.
- **Test Impact Analysis (TIA):** Запускайте только тесты, затрагивающие изменённые файлы. Для монорепозиториев — динамическая генерация пайплайна только для затронутых модулей.
- **Вытесняемые раннеры (best-effort):** Неприоритетные задачи (ночные E2E, линтинг) выполняйте на дешёвых вытесняемых узлах, оставляя выделенные ресурсы для критичных деплоев.

### Организация процесса

- **Шаблонизация:** Вынесите общие стадии (валидация, тест, безопасность) в централизованные шаблоны или CI Components. Это исключает дублирование и обеспечивает единообразие.
- **Мониторинг пайплайна:** Отслеживайте DORA-метрики и SLI самого пайплайна (длительность p95, процент успешных запусков, время ожидания раннера). Настройте алерты при деградации конвейера.
- **Аудит и отладка:** Храните логи всех запусков минимум 30–90 дней. Используйте трассировку (OpenTelemetry) для диагностики задержек на критическом пути.
- **Финансовая осознанность:** Интегрируйте FinOps Gate в пайплайн для оценки стоимости изменений IaC. Следите за Unit Cost per Build и очищайте неиспользуемые окружения и артефакты.

## Дополнительная информация

- **[Глоссарий пайплайнов](./pipeline_glossary.md)** — детальные определения терминов.
- **[Стратегии развертывания](./deployment_strategies.md)** — методы минимизации рисков при выкатке.
- **[Метрики DORA](./dora_metrics.md)** — оценка эффективности потока поставки.
