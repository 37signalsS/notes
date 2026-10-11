# Паттерны CI/CD

**Актуально для:** самоуправляемые CI/CD-системы (GitLab CI/CD, Jenkins, GitHub Self-Hosted Runners) 2024–2026

> Область применения заметок: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых (on-prem / self-hosted) систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, в данной базе знаний не рассматриваются.

## Определения

**Паттерн CI/CD** — проверенный, эффективный и воспроизводимый подход к решению типовых задач в процессах непрерывной интеграции, доставки и развертывания. Применение паттернов направлено на минимизацию рисков при релизах, сокращение Time-to-Market и повышение стабильности систем. Паттерны не являются жёсткими правилами — это «меню» проверенных решений, из которого команда собирает свой конвейер под конкретный контекст (монолит или микросервисы, Kubernetes или bare-metal/VM, частота релизов).

Паттерны являются прямыми решениями для соответствующих [анти-паттернов CI/CD](./ci_cd_antipatterns.md). Где антипаттерн описывает «чего делать нельзя», паттерн описывает «как делать правильно».

---

## Основные концепции

### Ключевые паттерны поставки

Для построения надежных и быстрых пайплайнов используются следующие паттерны:

1.  **Trunk-Based Development (TBD):** Модель разработки с единой основной веткой. Минимизирует «ад слияния» (merge hell) и ускоряет интеграцию. _Почему:_ чем дольше ветка живёт отдельно от `main`, тем дороже слияние; TBD заставляет интегрироваться ежедневно. _Ограничение:_ требует зрелого набора автотестов и использования Feature Flags для незавершённой работы. Подробности в **[Рабочие процессы в Git](../Git/git_workflows.md)**.
2.  **Feature Flags (фиче-флаги):** Управление доступностью кода во время выполнения. Позволяет разделять деплой (доставку кода) и релиз (открытие функционала пользователям). _Почему:_ код можно катить в прод «выключенным» и включать позже без пересборки. См. **[Обзор Feature Toggles](./Testing/feature_toggles/overview.md)**.
3.  **Fail Fast (быстрый отказ):** Проектирование пайплайна таким образом, чтобы самые быстрые и дешёвые проверки (линтинг, unit-тесты) выполнялись первыми. _Почему:_ экономит ресурсы раннеров и даёт разработчику немедленный фидбек вместо ожидания длинного E2E-прогона.
4.  **Build Once, Deploy Many (сборка один раз):** Создание **Immutable Artifacts** (иммутабельных артефактов) на раннем этапе. Один и тот же образ проходит через все окружения, что исключает ошибки из-за разницы в процессе сборки. См. **[Управление артефактами](./artifact_management.md)**.
5.  **Separation of Config and Code:** Вынос настроек за пределы артефакта (Environment Variables, Secrets, ConfigMaps). Соответствует принципам [The Twelve-Factor App](https://12factor.net/config). _Почему:_ один артефакт должен работать во всех средах, отличаясь только конфигом.
6.  **GitOps & Everything as Code:** Использование Git как единственного источника правды для инфраструктуры и состояний кластера. Пайплайн обновляет манифесты в Git, а агент (например, ArgoCD/Flux) синхронизирует состояние (Pull-модель). _Почему:_ вся история изменений аудируема через `git`, а откат — это `git revert`.
7.  **Эфемерные окружения (Ephemeral Environments):** Автоматическое создание временных изолированных сред для каждого Merge Request. Позволяет тестировать фичу в реальных условиях до слияния в `main`.
8.  **Pipeline as Code & Centralized Templates:** Хранение конфигурации пайплайнов в коде с использованием общих шаблонов компании. Это стандарт **Platform Engineering**, упрощающий поддержку сотен микросервисов и гарантирующий единые стандарты безопасности.
9.  **Shift-Left Security (DevSecOps):** Интеграция сканеров безопасности (SAST, SCA), генерации **SBOM** и подписи образов на этапе сборки. См. **[Обзор DevSecOps](./DevSecOps/devsecops_overview.md)**.
10. **Policy as Code (PaC):** Автоматизированная проверка политик безопасности и комплаенса (например, через OPA/Rego, Kyverno, Conftest) внутри пайплайна. Позволяет блокировать деплой, если манифесты не соответствуют корпоративным стандартам.
11. **Supply Chain Security (SLSA):** Обеспечение целостности цепочки поставок через генерацию **Provenance** (доказательство происхождения) и **Attestation** (аттестация артефакта). Гарантирует, что артефакт был собран именно в доверенной CI-среде из конкретного коммита и не модифицирован в пути.
12. **Continuous Verification (CV):** Автоматизированная проверка состояния системы после деплоя (smoke-тесты, синтетический мониторинг, анализ метрик), интегрированная в процесс CD. В случае деградации метрик срабатывает автоматический откат.
13. **Feedback Loops & DORA Metrics:** Автоматический сбор метрик эффективности (Deployment Frequency, Lead Time for Changes, Change Failure Rate, MTTR) непосредственно из инструментов CI/CD. См. **[Метрики DORA](./Core_Concepts/dora_metrics.md)**.

### Классификация паттернов

Паттерны удобно группировать по области применения — это помогает выбирать нужный набор под задачу:

*   **Организационные:** Trunk-Based Development, Branch Protection, Developer Self-Service (IDP).
*   **Технические:** Immutable Artifacts, Fail Fast, Pipeline as Code, OIDC Authentication.
*   **Инфраструктурные:** GitOps, Ephemeral Environments, Infrastructure as Code (IaC), **[Runner Fleet Management](./runner-fleet-management.md)**, Configuration-as-Code Promotion, **[Традиционная инфраструктура (Bare Metal/VM)](./Deployment_Strategies/traditional_infrastructure.md)**.
*   **Безопасность:** Shift-Left Security, Secrets Management (Vault), Artifact Signing (Cosign), SLSA Attestations, Policy as Code, **[Air-gapped Deployment Strategies](./Core_Concepts/air_gapped_environments.md)**.
*   **Релизные:** Blue/Green, Canary, Dark Launches, Feature Toggles. См. **[Стратегии развертывания](./Deployment_Strategies/comparison.md)**.
*   **Операционные:** Continuous Verification, Auto-Rollback, Observability-driven Deployment. См. **[Health Checks и Rollback](./Deployment_Strategies/deployment_health_checks_and_rollback.md)**.

### Подробный разбор ключевых паттернов

#### Trunk-Based Development + Feature Flags (организационный фундамент)

Паттерн TBD работает только в связке с автоматическими проверками и фиче-флагами. Типовая дисциплина:

*   Ветка от `main` живёт не дольше 1–2 дней; размер PR — не более ~400 строк.
*   `main` защищён (branch protection): слияние возможно только при зелёном пайплайне и ревью.
*   Незавершённая функциональность скрывается за флагом, чтобы не блокировать релизы.

Пример декларативного описания флага (формат, понятный движку типа Unleash / GoFeatureFlag / внутреннему конфиг-сервису):

```yaml
# feature-flags/app.yaml
flags:
  new-checkout-flow:
    description: "Экспериментальный процесс оформления заказа"
    enabled: false
    targeting:
      # Включается только для внутренних тестеров по атрибуту
      rules:
        - values: ["team-internal"]
          percentage: 100
```

CI-гейт проверяет, что новый код не ломает сборку даже при выключенном флаге:

```bash
# Запуск тестов в обоих состояниях флага
FEATURE_NEW_CHECKOUT_FLOW=false pytest tests/  # → 42 passed
FEATURE_NEW_CHECKOUT_FLOW=true  pytest tests/  # → 42 passed
```

_Важно:_ флаги — это технический долг. Заведите реестр флагов и процесс их удаления после стабилизации функции (flag debt cleanup), иначе конфигурация превращается в неуправляемую.

#### Build Once, Deploy Many + Supply Chain Security (технический фундамент)

Сборка выполняется ровно один раз, артефакт иммутабелен и подписан. Дальше по средам «гуляет» один и тот же digest.

1. **Сборка и фиксация digest:**

```bash
IMAGE="nexus.internal:5000/app"
DIGEST=$(docker build -q -t "$IMAGE" . | sed 's/sha256://')
echo "Собран образ: $IMAGE@sha256:$DIGEST"
# → Собран образ: nexus.internal:5000/app@sha256:a1b2c3...
```

2. **Подпись артефакта (Cosign, ключ из Vault, on-prem, без публичных сервисов):**

```bash
# Однократно: cosign generate-key-pair, приватный ключ кладём в Vault
cosign sign --yes \
  --key <(vault read -field=key kv/cosign) \
  "nexus.internal:5000/app@sha256:$DIGEST"
# → Pushing signature to: nexus.internal:5000/app:sha256-a1b2c3....sig

cosign verify --key <(vault read -field=pub kv/cosign) \
  "nexus.internal:5000/app@sha256:$DIGEST"
# → Verification successful. Signed by: ...
```

3. **Продвижение (promotion) по средам без пересборки** — меняется только ссылка на digest в манифесте/инвентаре. Staging и Prod получают байт-в-байт один и тот же артефакт, что исключает «работало в staging».

_Уровни SLSA (кратко):_ SLSA 1 — документированный процесс; SLSA 2 — сборка из автоматизированной CI с верифицируемыми метаданными; SLSA 3 — сильная целостность платформы сборки (эфемерные раннеры, Provenance); SLSA 4 — максимальная защита от компрометации (двусторонний review, герметичная среда). Для on-prem достаточно целиться в SLSA 2–3.

#### Ephemeral Environments (инфраструктурный паттерн)

Для каждого MR создаётся изолированная среда, после слияния — уничтожается. На VM/bare-metal это реализуется либо выделенной ВМ через `ansible-pull`/Packer, либо изолированным systemd-юнитом/контейнером на шаред-хосте.

```yaml
# .gitlab-ci.yml (фрагмент) — создание и удаление среды MR
review:
  stage: deploy
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script:
    - ansible-playbook -i inventory/review.ini playbooks/spin_up.yml \
        --extra-vars "env=$CI_MERGE_REQUEST_IID app_version=$CI_COMMIT_SHA"
    - ansible-playbook -i inventory/review.ini playbooks/smoke.yml \
        --extra-vars "env=$CI_MERGE_REQUEST_IID"
  environment:
    name: review/$CI_MERGE_REQUEST_IID
    on_stop: stop_review   # гарантирует очистку ресурсов
stop_review:
  stage: deploy
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      when: manual
  script:
    - ansible-playbook -i inventory/review.ini playbooks/teardown.yml \
        --extra-vars "env=$CI_MERGE_REQUEST_IID"
  environment:
    name: review/$CI_MERGE_REQUEST_IID
    action: stop
```

_Валидация:_ после `spin_up` сервис отвечает на `/healthz` по адресу `review-<MR_IID>.internal`; после `teardown` ВМ/юнит удаляются, DNS-запись вычищается.

#### GitOps для традиционной инфраструктуры (Pull-модель без открытого SSH)

На хостах настраивается `systemd-timer`/`cron`, периодически запускающий `ansible-pull`, который забирает желаемое состояние из Git. CI не имеет прямого доступа к серверам — устранён постоянный SSH-порт.

```bash
# На целевом хосте (запускается по таймеру)
ansible-pull -U https://git.internal/infra/config.git \
             -i localhost, \
             local.yml
# → fetched -> applied: 3 changes, 0 failures
```

#### Continuous Verification & Auto-Rollback (операционный паттерн)

После выкатки система автоматически наблюдает за «золотыми сигналами» (Error Rate, Latency, Saturation) и при деградации откатывается. Пример универсального гейта на базе Prometheus (работает и для VM-сервисов, и для Kubernetes):

```bash
# gate.sh — запускается через 5 минут после деплоя
ERROR_RATE=$(curl -s "http://vm-select.internal:8481/select/0/prometheus/api/v1/query" \
  --data-urlencode 'query=sum(rate(http_errors_total[5m])) / sum(rate(http_requests_total[5m]))' \
  | jq -r '.data.result[0].value[1]')

if (( $(echo "$ERROR_RATE > 0.02" | bc -l) )); then
  echo "CRITICAL: Error rate $ERROR_RATE > 2%. Rollback..."
  # VM: переключение симлинка на предыдущий релиз + рестарт
  ln -sfn "/opt/app/releases/$(cat /opt/app/previous_version)" /opt/app/current
  systemctl restart app
  # K8s: kubectl rollout undo deployment/api-server
  exit 1
fi
echo "OK: Error rate $ERROR_RATE within SLO"
# → OK: Error rate 0.004 within SLO
```

---

## Практические сценарии

### Комплексный современный конвейер поставки (Kubernetes / GitOps)

Типовой жизненный цикл изменения с применением паттернов:

1.  **Этап проверки и изоляции (TBD + Fail Fast + PaC):**
    *   Разработчик коммитит в короткоживущую ветку.
    *   CI запускает линтеры, unit-тесты и **Policy-check** (проверка лимитов ресурсов, прав доступа в манифестах).
    *   Создается **Эфемерное окружение** для интеграционного тестирования.
2.  **Этап аттестации и сборки (Build Once + SLSA + DevSecOps):**
    *   После слияния с `main` собирается Docker-образ.
    *   Запускается SAST/SCA и генерация **SBOM**.
    *   CI генерирует **Provenance** и подписывает образ ключом через **OIDC** (без постоянных секретов).
    *   Образ считается «аттестованным» для Production.
3.  **Этап доставки и продвижения (GitOps + IaC Promotion):**
    *   CI обновляет Image Tag (по digest) в Configuration Repo.
    *   GitOps-контроллер (ArgoCD) синхронизирует Staging.
    *   После успешных тестов на Staging происходит автоматическое продвижение (Promotion) изменений конфигурации в ветку/папку Production в Git.
4.  **Этап верификации и обратной связи (CV + DORA + Auto-Rollback):**
    *   Запускается **Canary-раскатка** на Production.
    *   Система **Continuous Verification** анализирует логи и метрики (Prometheus/Loki).
    *   Если `Change Failure Rate` растет или `Health Check` падает, выполняется **Auto-Rollback**.
    *   Данные о деплое автоматически уходят в дашборд **DORA** для анализа производительности команды.

### Сценарий: Доставка на Bare Metal / VM (Ansible Push + systemd + Canary)

Для сервисов вне оркестратора применяется тот же набор паттернов (Build Once, CV, Auto-Rollback), но раскатка идёт через Ansible, а «канарейка» — на уровне балансировщика (haproxy/nginx).

```yaml
# deploy.yml — атомарная раскатка с переключением симлинка
- hosts: app_servers
  become: true
  vars:
    app_version: "{{ lookup('env', 'APP_VERSION') }}"
  tasks:
    - name: Скачать артефакт из внутреннего registry (Build Once)
      get_url:
        url: "https://nexus.internal/repository/app/{{ app_version }}/app.tar.gz"
        dest: "/opt/app/releases/{{ app_version }}/app.tar.gz"
        checksum: "sha256:{{ lookup('url', 'https://nexus.internal/app.sha256') }}"
    - name: Переключить symlink (atomic)
      file:
        src: "/opt/app/releases/{{ app_version }}"
        dest: "/opt/app/current"
        state: link
        force: yes
    - name: Перезапустить systemd-сервис
      systemd:
        name: app
        daemon_reload: yes
        state: restarted
        enabled: yes
```

Пошаговая canary-раскатка на VM-парке:

1. Вывесить новую версию на **один** узел из пула (через обновление конфига haproxy: `server app-canary 10.0.0.11:8080 check weight 10`).
2. Прогнать smoke-тесты и сверить метрики (`Error Rate`, `Latency p99`) за окно наблюдения (например, 10 минут).
3. Если метрики в SLO — увеличить вес до 100 и обновить остальные узлы; иначе — вернуть вес 0 и выполнить откат (`ln -sfn` на `previous_version` + `systemctl restart app`).

### Сценарий: Релиз через Feature Flag (разделение деплоя и релиза)

Код катится в прод выключенным, релиз для пользователей выполняется независимо переключением флага:

```bash
# 1. Деплой новой версии (флаг выключен — пользователи старый поток)
ansible-playbook deploy.yml --extra-vars "app_version=2.4.0"  # → changed=3
# 2. Включение флага только для 5% трафика (постепенное открытие)
curl -X POST https://flags.internal/api/v1/flags/new-checkout-flow \
  -d '{"enabled":true,"rules":[{"percentage":5}]}'  # → {"status":"updated"}
# 3. Через час, при отсутствии инцидентов — 100%
```

Этот паттерн критически важен для TBD: он позволяет делать релизы несколько раз в день без «code freeze».

### Сценарий: Миграции БД в пайплайне (Expand-Contract)

Схема данных меняется по паттерну **Expand-Contract**, чтобы старая и новая версия приложения могли работать одновременно (это делает откат безопасным):

```bash
# Этап Expand: добавляем новую колонку, не ломая старую версию
flyway -url="$DB_URL" -user="$DB_USER" -password="$DB_PASS" \
  -locations="filesystem:db/migrations" migrate
# → Successfully applied 2 migrations (execution time 00:01.482s)
```

*   **Expand:** добавить новую структуру, начать двоенную запись/чтение, оставить старую.
*   **Contract:** после подтверждения, что старая версия приложения больше не катится, удалить устаревшее.

### Сценарий: Продвижение артефактов в изолированный контур (Air-gapped)

В закрытых периметрах без прямого доступа к сборочной CI применяется паттерн переноса артефактов «физически» (носитель/внутренний шлюз) с сохранением подписи и SBOM. Подробнее в **[Изолированные среды (Air-gapped)](./Core_Concepts/air_gapped_environments.md)**.

### Устранение неполадок (Troubleshooting)

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Canary не завершается | Analysis-гейт не получает метрики / baseline не задан | Проверить PromQL-запрос гейта (`curl .../query`), наличие данных за окно | Исправить запрос; задать эталон; снизить порог или продлить окно |
| Флаг не переключается | Кэш конфигурации на стороне сервиса / неверный scope | `curl localhost:8080/flags` на узле | Сбросить кэш, проверить права доступа к флаг-сервису |
| Расхождение конфигураций между env | Config не вышен из артефакта (нарушен паттерн #5) | Сравнить env-переменные на Staging/Prod | Вынесите настройки в ConfigMap/секреты; пересоберите иммутабельный артефакт |
| Эфемерная среда не удалилась | `teardown` не отработал (падение в основном job) | Ищем висящие ВМ: `virsh list`; `systemctl list-units 'review-*'` | Использовать `on_stop`/`after_script`, которые гарантированно запускаются; добавить периодическую очистку по возрасту |
| Проверка подписи провалена в Prod | Несовпадение ключа/идентичности или digest изменён в пути | `cosign verify` на узле, сравнить digest | Переиспользовать тот же digest (Build Once); проверить цепочку доверия ключа |
| Перегрузка CI при TBD | Слишком частые коммиты в `main`, мало слотов раннеров | Метрика Queue Time (Prometheus) | Шардировать флот, распараллелить тесты, включить кэш зависимостей |

### GitHub Actions: конкретная реализация паттернов

Для GitHub Actions централизация и стандарты достигаются через reusable workflows и organization-level templates.

**Reusable workflow как единый стандарт:**
```yaml
# .github/workflows/standard-build.yml (репозиторий-шаблон)
name: Standard Build
on:
  workflow_call:
    inputs:
      node-version:
        required: false
        type: string
        default: '24'
      build-command:
        required: false
        type: string
        default: 'npm run build'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Setup Node
        uses: actions/setup-node@v7
        with:
          node-version: ${{ inputs.node-version }}
      - name: Install
        run: npm ci
      - name: Build
        run: ${{ inputs.build-command }}
      - name: Test
        run: npm test
```

**Вызов в проекте:**
```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  build:
    uses: my-org/.github/.github/workflows/standard-build.yml@main
    with:
      node-version: '24'
      build-command: 'npm run build:prod'
```

**Ограничения и best practices:**
- Глубина вложенности reusable workflows — до 10 уровней (с ноября 2025), рекомендуется не более 2–3.
- Лимит 50 workflow'ов на один запуск (с ноября 2025).
- `secrets: inherit` — автоматическая передача секретов; используйте явную передачу для最小 привилегий.
- Типизация `inputs`: только `string`, `number`, `boolean` (нет `choice` и `environment` в `workflow_call`).

**Policy as Code в GitHub Actions:**
- `branch protection rules` — требование review и статус-чеков перед merge.
- `required_status_checks` — mandatory CI job'ы перед merge.
- `required_approvals` — минимум N ревьюеров для production-веток.
- `restrict_pushes` — только определённые команды могут pushить в защитимые ветки.
- CODEOWNERS — автоматическое назначение ревьюеров на основе путей файлов.

**Где documented:**
- [Официальное руководство: Reuse workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
- [Справочник: Reusing workflow configurations](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)

### Лучшие практики и очистка (Best Practices & Cleanup)

1. **Принимайте паттерны постепенно.** Не внедряйте все 13 сразу: начните с TBD + Fail Fast + Build Once, затем добавляйте Shift-Left, GitOps и CV.
2. **Единообразие артефакта.** Один digest во всех средах — фундамент доверия к релизу.
3. **Иммутабельность.** Не патчите «на месте» в проде; любое изменение — через пайплайн.
4. **Очистка флагов (flag debt).** Раз в спринт аудируйте реестр флагов, удаляйте мёртвые и постоянно-включенные.
5. **Гарантированная очистка эфемерных сред.** `teardown`/`after_script` должны срабатывать даже при провале пайплайна (иначе — утечка ресурсов).
6. **Документируйте свой набор паттернов** в `CONTRIBUTING.md` репозитория, чтобы новые команды следовали единым «Золотым путям`.

---

## Ограничения и крайние случаи

- **Высокая доступность CI-инфраструктуры:** Для enterprise-сред GitLab CI и Jenkins разворачиваются в кластере с репликацией БД и балансировкой. Раннеры регистрируются в нескольких экземплярах для устранения SPOF. RTO для CI-инфраструктуры обычно составляет часы; подробнее в **[Резервном копировании и DR для CI/CD](./Core_Concepts/ci_cd_backup_dr.md)**.
- **Air-gapped среды:** При отсутствии выхода в интернет используются локальные зеркала зависимостей (Nexus proxy, MinIO/S3 для образов), pré-downloaded образы раннеров и air-gapped бандлы. Подробнее: **[Изолированные среды (Air-gapped)](./Core_Concepts/air_gapped_environments.md)**.
- **Границы прав и Multi-tenancy:** В оркестраторах (Kubernetes) namespace-изоляция; в GitLab — группы и sub-groups с scoped переменными. Паблик раннеры никогда не должны иметь доступ к `prod`-секретам.
- **Производительность при больших монореpos:** Инкрементальные сборки (Bazel, Nx, Turborepo), кэширование артефактов между коммитами и remote execution для снижения времени фидбека.
- **Регуляторные требования:** Вregulated-средах (финансы, госсектор) требуется полная трассируемость: каждый артефакт должен иметь SBOM, подпись и provenance, а изменения — аудит-лог с идентификатором деплоя.

---

## Дополнительная информация

### См. также

*   **[CI/CD: Обзор](./ci_cd_overview.md)** — фундаментальные определения и процессы.
*   **[CI/CD: Антипаттерны](./ci_cd_antipatterns.md)** — чего следует избегать при автоматизации.
*   **[Стратегии развертывания](./Deployment_Strategies/comparison.md)** — детальный разбор Canary, Blue/Green и других методов.
