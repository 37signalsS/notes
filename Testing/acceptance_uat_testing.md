# Приёмочное тестирование и UAT (Acceptance Testing & UAT)

## Определения

**Acceptance Testing (приёмочное тестирование)** — уровень тестирования, подтверждающий, что система соответствует заранее определенным критериям приемки (acceptance criteria) и готова к поставке. Выполняется чаще всего на стороне заказчика/продукт-владельца, может быть автоматизированным.

**UAT (User Acceptance Testing)** — форма приёмочного тестирования силами реальных пользователей/представителей бизнеса на реальных данных и в реальном окружении, перед внедрением в production.

**Acceptance Criteria** — конкретные, проверяемые условия (Given/When/Then), определяющие, когда история (story) считается готовой. Формализуются до реализации в ATDD и служат основанием для приёмочных тестов.

**BAC (Business Acceptance Criteria)** и **SAC (System Acceptance Criteria)** — критерии приемки на уровне бизнеса и системы соответственно. BAC описывают бизнес-правила и ожидаемое поведение; SAC — технические требования (производительность, безопасность, масштабируемость).

**Operational Acceptance Testing (OAT)** — форма приёмочного тестирования, проверяющая операционную готовность сервиса или инфраструктуры к эксплуатции: доступность, бэкапы, мониторинг, runbook, отказоустойчивость, disaster recovery. Пересекается со [smoke-тестированием](../CI-CD/Testing/smoke_testing.md) и SRE-чеклистами.

**Sign-off / Approval** — формальное подтверждение прохождения приёмочного тестирования. Может выполняться через электронную подпись, апрув в Merge Request / Pull Request, или issue в трекере с документальным подтверждением. В CI/CD sign-off часто реализуется как `manual approval` gate или protected environment.

**RTM (Requirements Traceability Matrix)** — матрица трассируемости требований: требование → тест-кейс → результат. Обеспечивает полноту покрытия требований тестами и аудит причин отказов при приёмке.

**Test Case / UAT-чеклист** — документ с описанием шагов и ожидаемых результатов (ручной/полуавтоматический). Для UAT используется чеклист критичных бизнес-сценариев.

**Defect Report (баг-репорт)** — запись о дефекте, найденном при приёмке. Критичность (blocker/critical/major/minor) определяет, блокирует ли дефект релиз.

**Alpha testing** — приёмочное тестирование до публичного релиза на ограниченной группе внутренних пользователей.

**Beta testing** — приёмочное тестирование после релиза на ограниченной группе внешних пользователей (beta-канал).

**Contract testing (в контексте приёмки)** — формальное подтверждение соответствия интерфейсов (API contract, сетевые протоколы) без полной выгрузки в production. См. [контрактное тестирование](../CI-CD/Testing/contract_testing_ci_cd.md).

**Dry-run / Warm-up** — пробная проверка готовности без полного cutover трафика (например, canary-прогрев, dry-run деплой).

## Основные концепции

### Место приёмочного тестирования в пирамиде

```
        ┌──────────────────┐
        │      UAT         │   ← реальные пользователи, production-like окружение
        ├──────────────────┤
    ┌───│   Acceptance     │
    │   │   (automated)    │   ← BDD-сценарии, автоматические gate-ы
    ├───┼──────────────────┤
E2E │   Integration        │   ← взаимодействие компонентов
UI  │                      │
Unit│                      │
```

- Уровень приёмки — верхушка пирамиды: медленнее, дороже, но критичен для принятия решения «выкатываем или нет».
- Хорошая практика — автоматизировать acceptance-уровень (BDD-сценарии/Cucumber), оставляя UAT для «тонких» бизнес-проверок.

### Отличие от TDD/BDD/ATDD

ATDD (Acceptance Test-Driven Development) — это методология разработки, где приёмочные тесты пишутся до реализации (см. [TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md) в книге методологий). Acceptance Testing — процесс на этапе поставки: критерии уже заданы, система уже реализована.

| Критерий | TDD | BDD/ATDD | Acceptance/UAT |
| :--- | :--- | :--- | :--- |
| Кто пишет | Разработчик | Команда+бизнес | Тестировщик/бизнес/пользователь |
| Когда | До кода | До кода (double-loop) | После реализации, перед release |
| Среда | Dev | Dev/Test | Preprod / prod-like |
| Цель | Дизайн кода | Договор о поведении/приетке | Подтверждение готовности продукта |
| Автоматизация | Обязательна | Часто (Gherkin) | Частично; UAT часто ручной/документированный |

### Уровни приёмочного тестирования

- **User Acceptance (бизнес-приёмка)**: сценарии реального использования, happy path + основные ошибки.
- **Operational Acceptance (OAT)**: эксплуатационные критерии — доступность, бэкапы, мониторинг, runbook, отказоустойчивость (пересекается с [smoke/ops-тестированием](../CI-CD/Testing/smoke_testing.md)).
- **Contract & Compliance**: SLA-критерии, соответствие лицензиям/нормативным требованиям.

### Смежные артефакты

- **Test Cases / UAT-чеклист** — описание шагов и ожидаемых результатов (ручной/полуавтоматический).
- **RTM (Requirements Traceability Matrix)** — матрица трассируемости: требование → тест-кейс → результат.
- **Sign-off / Approval** — формальное подтверждение (электронная подпись, issue в трекере с doc-подтверждением).
- **Defect Reports** — баги, найденные при приёмке (blocker/critical → блокируют release).

## Практические сценарии

### Сценарий 1: Формализация критериев приемки (Given/When/Then)

На основе BDD (формат из [TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md#формат-сценариев-bdd-gherkin)):

```gherkin
Функционал: Вход в личный кабинет
  Сценарий: успешный вход
    Допустим пользователь зарегистрирован в системе
    Когда он вводит корректные логин и пароль
    Тогда он попадает в личный кабинет
    И на странице отображается его баланс
```

Эти же сценарии автоматизируются (Behave/SpecFlow/Cypress) — см. [E2E-тестирование с помощью Cypress](./cypress_e2e_testing.md).

### Сценарий 2: Автоматизированный acceptance-трекинг в CI

**Предпосылки:**
- preprod-окружение с production-like конфигурацией;
- seed-данные, идентичные staging (фиксированные теги образов, deterministic fixtures);
- `docker-compose.acceptance.yml` с healthcheck для всех сервисов.

**Ожидаемый результат:** acceptance-спеки проходят, coverage не падает ниже порога, все acceptance-критерии зелёные.

```yaml
acceptance:
  stage: acceptance
  environment: staging
  script:
    - docker compose -f docker-compose.acceptance.yml up --abort-on-container-exit
    - npm run test:acceptance      # BDD-набор
  when: on_success
  needs: ["e2e"]
```

**Валидация:** `docker compose logs` — нет падений контейнеров; `npm run test:acceptance` — exit code 0; артефакты покрывают все acceptance criteria из RTM.

### Сценарий 3: UAT-цикл с реальными пользователями

1. Выкатка feature-флага/beta-окружения для группы пользователей (beta-канал).
2. Предоставление UAT-чеклиста — сценарии критичного пути.
3. Сбор фидбэка через тикет-трекер; классификация по severity.
4. `Sign-off` в задаче релиза (документ/чекбоксы), фиксация в release notes.
5. Пост-мониторинг после выкатки (см. [Observability-Driven Testing](../CI-CD/Testing/observability_driven_testing.md)).

**Предпосылки:**
- Feature toggle включён только для beta-группы (см. [Feature Toggles](../CI-CD/Testing/feature_toggles/overview.md));
- Доступен отдельный feedback-канал (трекер, форма);
- SLA на реакцию на найденные дефекты согласована с SRE/DevOps.

**Валидация:** Все критичные сценарии из чеклиста протестированы минимум одним реальным пользователем; найденные blocker-баги исправлены; подпись подтверждения зафиксирована в трекере.

### Сценарий 4: Acceptance-пороги в деплей (Pipeline Gate)

Связка с release-конвейерами: acceptance-результаты влияют на решение о промоушене (см. [Интеграцию тестов в CI/CD](./testing_cicd_integration.md#динамические-ворота-качества-quality-gates)):

- все acceptance-спеки зелёные → auto-promote;
- наличие blocker/документированных known issues → ручной `manual approve`;
- метрики качества (перцентили, failures) — пороги из [Методология тестирования производительности](./performance_testing_methodology.md).

```yaml
# GitLab CI: acceptance gate перед promotion в production
acceptance-gate:
  stage: acceptance
  image: cypress/included:latest
  script:
    - npx cypress run --spec 'cypress/e2e/acceptance/**' --reporter junit
  artifacts:
    when: always
    reports:
      junit: results.xml
  allow_failure: false
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

promote-to-production:
  stage: promote
  when: manual
  environment:
    name: production
  needs: ["acceptance-gate"]
```

### Сценарий 5: Операционная приёмка (OAT) в SRE-команде

Для сервисов/инфраструктуры критерии приёмки — эксплуатационные:

- smoke-тесты ключевых путей после деплоя ([Smoke-тестирование после деплоя](../CI-CD/Testing/smoke_testing.md));
- синтетический мониторинг и чёрные коробки — пороги SLI;
- бэкапы/restore-проверки;
- отказоустойчивость (chaos-тесты) — см. [Chaos Engineering как продолжение TDD](../CI-CD/Testing/tdd_bdd_overview.md#chaos-engineering-как-продолжение-tdd);
- процедуры реагирования (runbook) и оповещение (см. [Prometheus](../Prometheus/overview.md)).

**Предпосылки:**
- SLO на доступность и latency определены для каждого сервиса;
- synthetic-мониторинг настроен и алерты активны до выката;
- план восстановления (backup/restore) проверен не ранее чем за 24 ч до деплоя.

**Валидация:** все smoke-тесты pass; алерты не срабатывают в течение warm-up окна (30–60 мин); проверка restore завершается успешно; chaos-эксперимент не приводит к нарушению SLO.

### Сценарий 6: Приёмка инфраструктурных изменений (Sysadmin/DevOps)

Для инфраструктурных изменений (Ansible-роли, Terraform-модули) acceptance-критерии включают проверку конфигурации и безопасности:

- **Idempotency check:** Ansible-роль применяется дважды без изменений (`molecule idempotence`);
- **Policy compliance:** Checkov/conftest не выявляют нарушений (см. [Инфраструктурное тестирование](../CI-CD/Testing/tdd_bdd_overview.md#policy-as-code-как-расширение-tdd));
- **Service availability:** systemd-сервис стартует, listen на порту, health endpoint отвечает 200;
- **Security scan:** открыты только необходимые порты, приватные ключи имеют права `0600`.

```bash
# Проверка idempotency Ansible-роли
ansible-playbook site.yml --diff | grep -q 'changed=0' && echo "IDEMPOTENT" || echo "NOT IDEMPOTENT"

# Policy validation
checkov -d infra/ --soft-fail-on high
conftest test k8s/ -p policy/

# Service availability
systemctl is-active --quiet myapp && curl -sf http://localhost:8080/healthz
```

**Валидация:** `changed=0` на втором прогоне; нулевые нарушения policy; health endpoint возвращает 200; `ss -tlnp` показывает только нужные порты.

## Операции и команды

### Инструменты приёмочного тестирования

| Инструмент / команда | Назначение | Пример использования |
| :--- | :--- | :--- |
| `gherkin` / `cucumber` | Формализация acceptance-сценариев в Gherkin | `cucumber features/acceptance/ --format progress` |
| `behave` | BDD-фреймворк для Python | `behave features/ --no-capture --junit` |
| `specflow` | BDD для .NET | `specflow run acceptance.test.csproj` |
| `cypress` | E2E и acceptance автоматизация | `npx cypress run --spec 'e2e/acceptance/**'` |
| `playwright` | Мультибраузерное E2E | `npx playwright test --grep @acceptance` |
| `pact-broker` | Контрактное тестирование | `pact-broker can-i-deploy --to-environment production` |
| `junit` / `pytest` | Автоматизация acceptance-тестов | `pytest tests/acceptance/ --junitxml=results.xml` |
| `xmind` / `testrail` | Управление RTM и тест-кейсами | экспорт RTM → traceability matrix |
| `gitsign` / `cosign` | Sign-off с подписью | `cosign sign --key kms://...` |

### Ожидаемый вывод

```bash
# Успешный запуск acceptance-спек
$ cucumber features/acceptance/ --format progress
35 scenarios (35 passed)
105 steps (105 passed)

# Проверка покрытия acceptance-критериев RTM
$ pytest tests/acceptance/ --junitxml=results.xml
========================= 35 passed in 12.4s =========================

# Проверка policy перед деплоем
$ checkov -d infra/ --soft-fail-on high
Passed Checks: 12
```

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Acceptance-тесты дублируют unit-уровень | Критерии не связаны с бизнес-поведением | `git log --follow` показывает 1:1 с unit-тестами | Сводить acceptance к пользовательским сценариям, не к реализации |
| UAT превращается в «полное регрессионное тестирование» | Нет приоритизации критичного пути | UAT-чеклист содержит >50 пунктов | Сформировать UAT-чеклист из топ-сценариев + happy path |
| Автоматизация acceptance не используется в CI | Нет окружения/данных | `docker compose ls` показывает отсутствие acceptance-стека | Выделить стабильное preprod, фикстуры, seed-данные |
| Release блокируется субъективными оценками | Нет заранее согласованных criteria | MR не содержит acceptance-критериев | Определять acceptance criteria в начале спринта, фиксировать в RTM |
| OAT не выполняется перед выкаткой | SRE-чеклист отсутствует/непрозрачен | `kubectl get jobs` показывает отсутствие post-deploy jobs | Стандартизовать OAT-чекарек, привязать к промоушену |
| UAT-пользователи пропускают сценарии | Чеклист слишком длинный/неудобный | Анализ выполнения UAT-чеклиста показывает <50% покрытие | Сократить до top-5 критичных сценариев, добавить автоматические smoke как fallback |
| Sign-off не фиксируется в системе | Approval проходит вне трекера | MR без апрува сливается в main | Enforced branch protection + требовать issue с подтверждением |
| Feature toggle остаётся включённым после UAT | Нет cleanup-плана на флаг | `launchdarkly flags list` показывает активные release-флаги | Автоматический cleanup флагов через TTL или scheduled job |
| Приёмка проходит, но production ломается | Окружение UAT ≠ production | `diff <(docker inspect staging) <(docker inspect prod)` | Environment parity: одинаковые образы, конфиги, данные |
| Бэкапы не проверены на restore | Только проверка наличия бэкапа | Последний restore был >90 дней назад | Обязательный restore-тест перед каждым крупным релизом |

## Лучшие практики

### Формализация приёмочных критериев

- **Acceptance criteria в начале спринта:** определяйте BAC и SAC до начала разработки. Критерии должны быть проверяемыми и измеримыми.
- **Given/When/Then для каждого сценария:** даже ручные UAT-проверки формализуются в виде шагов с ожидаемыми результатами.
- **RTM-трассируемость:** каждый acceptance-критерий связан с конкретным требованием и тест-кейсом. Используйте RTM для аудита покрытия.
- **Разделение BAC и SAC:** бизнес-критерии проверяет бизнес/аналитик; технические — QA/SRE. Оба уровня должны пройдены.

### Интеграция в pipeline

- **Quality Gates:** acceptance-результаты влияют на промоушен. Используйте `allow_failure: false` и `needs` для цепочки из acceptance → promote.
- **Эфемерные окружения:** для каждого MR создавайте изолированное acceptance-окружение (review app), уничтожайте после.
- **Fail-fast:** acceptance-провал блокирует дальнейший деплой. Используйте `exit 1` и fail-fast стратегии.
- **Artifacts:** сохраняйте JUnit XML, логи и скриншоты UAT для пост-фактум анализа.

### UAT с реальными пользователями

- **Beta-канал:** используйте feature toggles для выката новой версии небольшому проценту пользователей, а не всему трафику.
- **Feedback loop:** дайте бизнес-пользователям удобный способ сообщать о проблемах (трекер, форма) с классификацией severity.
- **Пост-мониторинг:** после выката в production следите за метриками (latency, error rate, saturation) и пользовательским feedback.

### Операционная приёмка (OAT)

- **SLO на acceptance:** определяйте SLO на availability и latency для каждого сервиса. OAT проверяет, что сервис удовлетворяет SLO.
- **Synthetic monitoring:** настройте blackbox-проверки до выката, а не после.
- **Restore-тест:** регулярно проверяйте, что бэкапы можно восстановить. Минимум раз в квартал для критичных сервисов.
- **Chaos-тесты:** включайте chaos-эксперименты в OAT для проверки отказоустойчивости.

### Артефакты и governance

- **Sign-off в трекере:** фиксируйте результат приёмки в issue/MR с подписями ответственных сторон.
- **Cleanup feature flags:** удаляйте release-фичи после подтверждения стабильности. Используйте TTL на флаги.
- **Release notes:** связывайте acceptance-результаты с release notes для аудита.

## Ограничения и крайние случаи

- **UAT не покрывает все бизнес-правила:** UAT проверяет типичные сценарии, но не граничные условия. Для полного покрытия необходимы unit и integration-тесты.
- **Flaky acceptance-тесты:** зависят от внешних сервисов, данных, таймаутов. Используйте retry с backoff, фикстуры и изоляцию данных.
- **Environment drift:** окружение UAT может отличаться от production. Используйте production-like конфигурацию и seed-данные.
- **Human bias в UAT:** реальные пользователи склонны пропускать сценарии или принимать решения эмоционально. Автоматические smoke-тесты как fallback.
- **Feature toggle explosion:** слишком много активных флагов создает матрицу состояний. Ограничьте количество релив-флагов на сервис (5–10) и используйте cleanup-политику.
- **Contract testing как компромисс:** CDC/BDCT покрывает API-контракты, но не бизнес-логику. Используйте в связке с acceptance-сценариями.
- **Acceptance criteria evolution:** критерии приемки могут пересекаться с изменениями требований. Обновляйте RTM при изменении бизнес-правил.

## Очистка

- **Test data:** удаляйте или сбрасывайте seed-данные и тестовые записи, созданные во время UAT.
- **Feature toggles:** выключайте и удаляйте release-фичи после подтверждения стабильности. Используйте TTL на флаги.
- **Test accounts:** удаляйте/vыключайте тестовые пользовательские аккаунты, созданные для UAT.
- **Artifacts:** архивируйте результаты acceptance-тестов (JUnit, логи) согласно политике retention (7–30 дней).
- **Environments:** уничтожайте эфемерные acceptance-окружения после завершения цикла.

## Дополнительная информация

### См. также

- **[TDD, BDD и ATDD](../CI-CD/Testing/tdd_bdd_overview.md)** — методологическая основа (ATDD, «двойной цикл», TDI).
- **[Smoke-тестирование после деплоя](../CI-CD/Testing/smoke_testing.md)** — эксплакационный слой приёмки (OAT).
- **[E2E-тестирование с помощью Cypress](./cypress_e2e_testing.md)** — инструмент автоматизации acceptance-сценариев.
- **[Методология тестирования производительности](./performance_testing_methodology.md)** — пороги качества для acceptance в performance context.
- **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — quality gates, TIA, эфемерные окружения.
- **[Observability-Driven Testing](../CI-CD/Testing/observability_driven_testing.md)** — пост-мониторинг после выката.
- **[Feature Toggles](../CI-CD/Testing/feature_toggles/overview.md)** — управление feature flags для UAT и canary.
- **[Контрактное тестирование](../CI-CD/Testing/contract_testing_ci_cd.md)** — CDC/BDCT как форма приёмки API.
- **[VPN: чек-лист приёмки развёртывания](../Vpn/vpn-acceptance-checklist.md)** — пример OAT для инфраструктурных изменений.

### Внешние ресурсы

- [ISTQB — Acceptance Testing](https://www.istqb.org/) — стандарт тестирования, терминология уровней.
- [Cucumber](https://cucumber.io/) — BDD-фреймворк для формализации acceptance-сценариев.
- [Pact Foundation](https://docs.pact.io/) — документация по контрактному тестированию (CDC).
