# DevSecOps — обзор методологии

## Определения

**DevSecOps (Development, Security, Operations)** — методология интеграции практик безопасности на всех этапах жизненного цикла разработки программного обеспечения (**SDLC — Software Development Life Cycle**). В 2026 году DevSecOps перешел от разрозненных сканеров к единой экосистеме управления рисками, глубоко интегрированной в платформенную инженерию (**Platform Engineering**).

**ASPM (Application Security Posture Management)** — центральная категория инструментов 2026 года, которая консолидирует данные из всех AST-сканеров, устраняет дубликаты и приоритизирует уязвимости на основе **анализа достижимости (Reachability Analysis)**. ASPM служит «единым окном» для ИБ-офицеров и разработчиков.

**AST (Application Security Testing)** — методы тестирования безопасности приложения:
- **SAST (Static AST):** статический анализ исходного кода без его выполнения. Подробно: [SAST](./sast_overview.md).
- **DAST (Dynamic AST):** динамический анализ работающего приложения в рантайме. Подробно: [DAST](./dast_overview.md).
- **SCA (Software Composition Analysis):** анализ сторонних зависимостей через **Living SBOM** (динамический граф компонентов).
- **IAST (Interactive AST):** гибридный анализ через **eBPF**-инструментацию, обеспечивающий точность без изменения кода.

Сравнение подходов SAST и DAST, их границы применимости и комбинированный конвейер — в **[сравнении подходов SAST vs DAST](./sast_vs_dast.md)**.

**Supply Chain Security 2.0** — защита всей цепочки поставок артефактов, базирующаяся на стандарте **SLSA v2.0**, сквозной подписи образов и использовании **VEX (Vulnerability Exploitability eXchange)** для фильтрации неактуальных уязвимостей. Глубоко тема раскрыта в **[обзоре безопасности цепочки поставок](../../Security/Supply_Chain_Security/overview.md)**.

## Базовые концепции

### Принципы DevSecOps (2026)

- **Shift Left:** Безопасность встроена непосредственно в инструменты разработчика. Уязвимости блокируются на этапе написания кода, а не после коммита.
- **Reachability-First:** Игнорирование уязвимостей в библиотеках, если уязвимый код физически не вызывается приложением. Это снижает «шум» сканеров на 70–90%.
- **Policy as Code (PaC):** Декларативное описание политик (Kyverno, OPA), которые автоматически применяются к IaC-манифестам и Kubernetes-кластерам.
- **Automated Remediation:** Автоматическая генерация Pull Request с исправлениями по правилам (например, Renovate для зависимостей), которые проходят валидацию тестами перед предложением разработчику.
- **NHI Security (Non-Human Identities):** Фокус на защите и ротации прав доступа для сервисных аккаунтов и пайплайнов. В 2026 году NHI составляют до 95% всех цифровых сущностей.
- **Platform-Native Security:** Безопасность как часть внутреннего портала разработчика (IDP — Internal Developer Platform), где ИБ-проверки являются «золотыми путями» (Golden Paths).

### Инструменты и классификации (2026)

| Категория | Инструменты | Назначение |
| :--- | :--- | :--- |
| **ASPM** | Cycode, Apiiro, Snyk AppRisk | Оркестрация, корреляция и приоритизация рисков. |
| **SAST** | Snyk Code, Semgrep | Глубокий семантический анализ и авто-фикс. |
| **SCA / SBOM** | Trivy, Grype, Syft | Генерация Living SBOM и VEX-анализ. |
| **IaC Security** | Checkov, KICS, OPA | Проверка инфраструктурного кода (Terraform, Helm). Подробнее: [Defense in Depth в IaC](./iac-security-defense-in-depth.md). |
| **Secret Scan** | Gitleaks, TruffleHog | Поиск секретов в Git, Slack, документации и логах. |
| **DAST** | Nuclei, ZAP, Burp Suite | Динамическое тестирование работающего приложения и защита API. |
| **Runtime (eBPF)** | Falco, Tetragon, Pixie | Обнаружение аномалий и дрейфа конфигурации (Drift Detection) в ядре. |

**Стандарты и протоколы:**
- **SLSA v2.0 (Supply-chain Levels for Software Artifacts):** уровни защиты целостности сборки и артефактов.
- **VEX (Vulnerability Exploitability eXchange):** машиночитаемый формат сообщения о статусе эксплуатации уязвимости.
- **DSEC (DevSecOps Maturity Model):** оценка зрелости процессов безопасности.
- **[Сертификация ФСТЭК](../../Linux/Security/Fstec/overview.md):** требования по безопасной разработке в рамках SDL для РФ.

### Угрожающее моделирование (Threat Modeling)

Угрожающее моделирование — это процесс выявления угроз, уязвимостей и их последствий **до написания кода**, на этапе проектирования. В отличие от SAST/DAST, которые ищут дефекты в готовом коде, моделирование находит **ошибки проектирования** (отсутствие авторизации, ненадёжные доверенные границы, утечка данных по побочным каналам), которые автоматические сканеры не видят.

**Ключевые понятия:**

- **Активы (Assets):** что защищаем — PII, секреты, ключи, бизнес-логика, инфраструктура.
- **Поверхность атаки (Attack Surface):** все точки взаимодействия с внешним миром (API, формы, порты, файлы).
- **Доверенные границы (Trust Boundaries):** границы, при пересечении которых нужна явная проверка подлинности и прав доступа (вход в систему, вызов внешнего сервиса, чтение из очереди).

**Распространённые фреймворки:**

| Фреймворк | Назначение | Суть |
| :--- | :--- | :--- |
| **STRIDE** | Категоризация угроз | Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege — по одной букве на каждый класс угроз к каждому элементу модели. |
| **PASTA** | Процессный, бизнес-ориентированный | 7 шагов от бизнес-целей к техническим угрозам. |
| **LINDDUN** | Приватность данных | Расширение STRIDE для персональных данных (Linkability, Identifiability, Non-repudiation…). |
| **DREAD** | Оценка риска | Устарел как основной метод, но используется для ранжирования (Damage, Reproducibility, Exploitability, Affected users, Discoverability). |

**Типовой процесс:**

1.  Построить **DFD (Data Flow Diagram)** — кто с кем обменивается данными, где границы доверия.
2.  Для каждого элемента и границы перечислить угрозы по STRIDE.
3.  Оценить вероятность и воздействие, расставить приоритеты.
4.  Определить контрмеры: устранить, снизить, переложить (transfer) или принять (accept) риск.
5.  Зафиксировать модель в репозитории как **Threat Modeling as Code** — диаграмму и выводы хранят вместе с кодом, проверяют изменения при ревью.

Инструменты: OWASP Threat Dragon, draw.io, PlantUML, либо чисто текстовые описания в ADR (Architecture Decision Records).

### Модель зрелости DevSecOps (DSEC / BSIMM / OWASP SAMM)

Зрелость программы безопасности нельзя оценить «на глаз». Существуют эталонные модели, помогающие понять текущее состояние и составить дорожную карту:

- **DSEC (DevSecOps Maturity Model):** разбивает практики на три измерения — **Culture and Organization**, **Process**, **Technical** — и три уровня (1 — начальный, 2 — повторяемый, 3 — измеряемый/оптимизируемый). Ориентирован именно на DevSecOps.
- **BSIMM (Building Security In Maturity Model):** наблюдательная модель, описывающая реальные практики компаний через 12 практик (например, «Strategy and Metrics», «Code Review», «Security Testing»). Помогает бенчмаркить себя против отрасли.
- **OWASP SAMM (Software Assurance Maturity Model):** пять бизнес-функций — Governance, Design, Implementation, Verification, Operations — каждая с уровнями зрелости 1–3 и набором активностей.

**Практический подход:** не пытаться сразу достичь уровня 3 везде. Проводят ассессмент, выбирают 2–3 критичных направления (например, автоматизация SAST и управление секретами), ставят целевой уровень и измеряют прогресс метриками из следующего раздела.

### Культура и экономика Shift Left

Технические сканеры бесполезны без организационной базы. DevSecOps — это прежде всего **распределение ответственности**:

- **Разработчик** владеет безопасностью своего кода (пишет без уязвимостей, сам чинит находки).
- **Оператор/SRE** владеет безопасностью рантайма, инфраструктуры и раннеров.
- **Security-команда** не «блокирует», а *включает* безопасность в инструменты (пишет правила, golden paths, обучает).

Принципы:

- **Security as Code / Compliance as Code:** политики, контроли и тесты безопасности хранятся в репозитории рядом с кодом и проверяются автоматически, как обычный код.
- **Экономика раннего обнаружения:** стоимость исправления дефекта растёт экспоненциально по мере продвижения по SDLC — по оценкам NIST/IBM, исправление уязвимости на этапе проектирования в ~10–100 раз дешевле, чем в продакшене. Это главное обоснование инвестиций в Shift Left.
- **Golden Paths / Platform Engineering:** платформа предоставляет защищённые шаблоны (репозитории, пайплайны, образы), чтобы разработчик не изобретал небезопасные велосипеды.
- **Security Champions:** в каждой команде выделяется разработчик-адвокат безопасности, связующее звено с Sec-командой.
- **Blameless postmortems:** разбор инцидентов без поиска виноватых, фокус на улучшении системы.

## Практические сценарии

### Жизненный цикл безопасности (Lifecycle 2026)

1.  **Проектирование (Plan):**
    - Автоматизированные инструменты анализируют архитектуру и требования, подсвечивая риски безопасности на этапе планирования (Threat Modeling as Code).
2.  **Разработка (Code):**
    - **IDE Scanning:** обнаружение уязвимостей и секретов в реальном времени.
    - **Auto-Fix:** предложение исправлений прямо в редакторе кода.
3.  **Интеграция (Build):**
    - **Incremental SAST:** быстрый анализ только измененного кода (diff).
    - **SBOM Generation:** создание CycloneDX/SPDX манифеста.
    - **Attestation:** создание криптографической аттестации сборки (SLSA).
4.  **Развертывание (Deploy):**
    - **Admission Control:** проверка подписей образов и аттестаций перед запуском в кластер.
    - **IaC Scan:** финальная проверка конфигурации перед применением (Terraform/Crossplane). Подробнее об уровнях проверки: [**Defense in Depth в IaC**](./iac-security-defense-in-depth.md).
5.  **Эксплуатация (Run):**
    - **eBPF Monitoring:** отслеживание подозрительных системных вызовов.
    - **Drift Detection:** автоматическое обнаружение расхождений между IaC-кодом и реальным состоянием инфраструктуры.
    - **VEX Updates:** автоматическое обновление статуса уязвимостей при появлении данных от вендоров.

Подробные технические детали — в [руководстве по интеграции безопасности](./sast_dast_cicd_integration.md).

### Пример 1: Локальный security-gate через pre-commit (git hooks)

Первый рубеж Shift Left — проверка ещё до коммита, на машине разработчика, без CI и без облака.

**Предусловия:**
- Установлены `git`, `python3` (>=3.8), `pipx` (или `pip`).
- Локально доступны `gitleaks` и `semgrep` (через `pipx install gitleaks semgrep`).

**1. Установить фреймворк pre-commit и подключить хуки:**

```bash
pipx install pre-commit
cat > .pre-commit-config.yaml <<'EOF'
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
  - repo: https://github.com/semgrep/semgrep
    rev: v1.45.0
    hooks:
      - id: semgrep
        args: ['--config', 'p/security-audit', '--error', '--quiet']
EOF
pre-commit install   # → устанавливает git hook в .git/hooks/pre-commit
```

**2. Сделать коммит — хуки запустятся автоматически:**

```bash
git add . && git commit -m "feat: add auth handler"
# → gitleaks: найден секрет → коммит заблокирован
# → semgrep: найден dangerous-eval → коммит заблокирован
```

**Validation:** при отсутствии находок коммит создаётся; при находке `pre-commit` печатает описание и прерывает коммит, оставляя изменения в индексе.

**Troubleshooting:**
- *Ложное срабатывание gitleaks на тестовом ключе:* добавьте исключение в `.gitleaksignore` (хэш находки) или пометьте файл через `gitleaks:allow` в комментарии.
- *Нужно временно пропустить:* `git commit --no-verify` (используйте только для тривиальных небезопасных правок и никогда для секретов).
- *Хук не срабатывает:* проверьте `ls -l .git/hooks/pre-commit` — должен указывать на `pre-commit`.

### Пример 2: Policy as Code локально (OPA conftest + Rego) для IaC и образов

Политики безопасности можно проверять **до** деплоя, прямо в CI или локально, без Kubernetes-кластера, с помощью **conftest** (инструмент на базе OPA).

**Предусловия:** бинарь `conftest` (скачать с GitHub releases OPA project); файл `Dockerfile` или Kubernetes-манифест для проверки.

**1. Написать правило** (`policy/dockerfile.rego`):

```rego
package main

deny[msg] {
  input[i].Cmd == "user"
  val := input[i].Value
  contains(lower(val[_]), "root")
  msg := "Запрещён запуск от root в Dockerfile"
}

deny[msg] {
  input[i].Cmd == "env"
  val := input[i].Value
  contains(lower(val[_]), "secret")
  msg := "Секрет в ENV — используйте секрет-менеджер, а не переменную сборки"
}
```

**2. Проверить Dockerfile:**

```bash
conftest test --policy policy/ Dockerfile
# → FAIL: "Запрещён запуск от root в Dockerfile" (если USER root присутствует)
```

**Validation:** `conftest` возвращает ненулевой код и список нарушений; при чистом файле — `PASS`. То же применимо к манифестам Kubernetes (`conftest test --policy policy/ deploy.yaml`).

**Troubleshooting:**
- *Ошибка синтаксиса Rego:* запускайте `conftest test` с `--trace` для диагностики; проверьте, что пакет назван `main`.
- *Dockerfile-плагин:* conftest умеет парсить Dockerfile нативно; для сложных случаев используйте официальный `policy` библиотеки (kubernetes, docker).
- Подробнее про многоуровневый контроль IaC — в **[Defense in Depth на уровне IaC](./iac-security-defense-in-depth.md)**.

### Пример 3: Аппаратное обеспечение и изоляция раннеров (Runner Hardening, SRE/Sysadmin)

Уязвимость на уровне CI/CD-раннера часто даёт полный доступ к секретам и артефактам. Жёсткая изоляция раннеров — базовая мера DevSecOps на стороне инфраструктуры.

**Чек-лист и команды проверки:**

- **Эфемерные раннеры (ephemeral):** каждый джоб выполняется на свежем экземпляре, уничтожаемом после. GitLab: флаг `--ephemeral` у `gitlab-runner`; GitHub Actions: `runs-on: [self-hosted, ephemeral]`.
- **Наименьшие привилегии:** раннер работает под выделенным пользователем без широких прав; нет SSH-ключей к проду.

```bash
id gitlab-runner                 # → проверить, что раннер не в группе sudo/wheel
sudo -l -U gitlab-runner         # → должен выдавать только необходимые NOPASSWD-команды
```

- **Сетевая изоляция:** раннеры в отдельном VLAN; исходящий трафик — только к внутреннему registry/mirror и необходимым хостам (egress allowlist). Недоверенные зависимости тянутся через внутреннее зеркало, а не напрямую из интернета.
- **Очистка диска и workspace:** шифрование диска (LUKS), `clear_readonly` / очистка workspace между джобами; для контейнерных раннеров — read-only rootfs и `--rm`.
- **Секреты в рантайме:** инъекция через Vault/секрет-менеджер в память, никогда не пишутся на диск; маскировка в логах (`--mask` / settings).
- **Ограничение ядра:** seccomp/AppArmor-профили, запрет `privileged` контейнеров.

**Validation:** `sudo -l -U gitlab-runner` не содержит `ALL`; `ip a` показывает принадлежность к изолированному сегменту; в аудит-логах нет доступа раннера к прод-секретам.

**Troubleshooting:**
- *Утечка состояния между джобами (кросс-джоб leakage):* причина — постоянный workspace или кэш. Решение — `--ephemeral` + политика очистки workspace + изолированный кэш на джоб.
- *Раннер видит чужие секреты:* проверьте, что `protected`/`untagged` настройки и scope переменных ограничены нужными ветками/окружениями.
- Подробнее про защиту секретов в пайплайнах — в **[управлении секретами в CI/CD](./secrets_management.md)**.

### Пример 4: Сбор и анализ метрик безопасности из SARIF (jq)

Метрики из раздела «Метрики эффективности» бесполезны без автоматического сбора. Все основные сканеры (Semgrep, Trivy, CodeQL, Checkov) экспортируют **SARIF** — его можно агрегировать и считать тренды.

**Предусловия:** утилита `jq`; директория `reports/` с SARIF-файлами за разные даты.

**1. Подсчитать находки по уровням серьёзности:**

```bash
jq -s '[.[].runs[].results[] | {sev: (.properties.severity // .level)}] | group_by(.sev) | map({sev: .[0].sev, count: length})' reports/*.sarif
# → [{"sev":"high","count":3},{"sev":"medium","count":7}]
```

**2. Оценить MTTR между двумя снимками (вчера/сегодня):**

```bash
# Предполагаем, что в properties каждой находки есть дата обнаружения и дата исправления
today=$(jq '[.[].runs[].results[] | select(.properties.status=="fixed")] | length' reports/today.sarif)
echo "Исправлено к сегодня: $today"
# → сверяется с историческими данными для расчёта среднего времени (MTTR)
```

**Validation:** команда возвращает агрегированные числа; при отсутствии находок — пустой/нулевой результат. Данные отправляются в дашборд (Prometheus/Grafana) или просто в еженедельный отчёт.

**Troubleshooting:**
- *jq выдаёт `null`:* разные генераторы кладут серьёзность в разные поля (`level` vs `properties.severity` vs `properties.issue_severity`) — адаптируйте `select(...)`.
- *Разные даты в именах файлов:* используйте glob по дате (`reports/2026-*.sarif`) для построения тренда.

### Быстрый старт: SBOM + сканирование уязвимостей с VEX-фильтрацией

Встраивание генерации SBOM и сканирования в этап сборки (Build) — базовая практика DevSecOps. Минимальный локальный пример (подробности и форматы — в **[анализе зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**):

```bash
# 1. Сгенерировать SBOM в формате CycloneDX
syft . -o cyclonedx-json > sbom.json
# → sbom.json содержит полный инвентарь компонентов

# 2. Отсканировать SBOM на уязвимости
trivy sbom sbom.json
# → список CVE по компонентам

# 3. Применить VEX — отфильтровать неэксплуатируемые (например, vuln не вызывается)
trivy sbom --vex vex.json sbom.json
# → из отчёта исключены CVE со статусом not_affected из vex.json
```

**Validation:** `sbom.json` непустой и валиден по схеме CycloneDX; `trivy` печатает таблицу CVE; после `--vex` количество находок уменьшается на число подтверждённо неэксплуатируемых.

## Оперативные команды

### Обнаружение и мониторинг

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `semgrep --config=auto .` | Быстрый статический анализ кода в текущей директории | # → список находок по CWE/SEC |
| `gitleaks detect --source=. --report-path=gitleaks.json` | Поиск секретов в Git-репозитории | # → JSON с находками или пустой файл |
| `trivy fs .` | SCA-анализ файловой системы (зависимости, секреты, IaC) | # → таблица CVE по критичности |
| `conftest test --policy policy/ deploy.yaml` | Проверка IaC-манифеста на соответствие политикам Rego | # → PASS или список нарушений |
| `checkov -d ./terraform` | Сканирование Terraform-кода на небезопасные конфигурации | # → результаты по CIS-бенчмаркам |
| `syft . -o cyclonedx-json > sbom.json` | Генерация SBOM в формате CycloneDX | # → sbom.json с инвентарём компонентов |
| `grype sbom:sbom.json` | Сканирование SBOM на известные CVE | # → список уязвимых пакетов |
| `git secrets --scan` | Предотвращение коммитов секретов в Git (ключи, токены) | # → найден секрет → откат коммита |

### Реагирование на инцидент (Incident Response Runbook)

При обнаружении критической уязвимости в продакшен-коде или инфраструктуре:

1. **Остановить:** если уязвимость активно эксплуатируется — изолировать компонент (отключить сервис, откатить деплой, отозвать секрет).
2. **Зафиксировать:** сохранить логи, SARIF-отчёт, evidence (скриншоты, дампы).
3. **Уведомить:** escalation в Security-команду, владельцу сервиса, compliance (если затронуты PII/PCI).
4. **Исправить:** патч, обновление зависимостей, изменение конфигурации.
5. **Проверить:** повторное сканирование после исправления; триггер quality gate.
6. **Уроки:** blameless postmortem, обновление правил сканеров и политик.

## Устранение неисправностей

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `semgrep` падает с `ParseError` | Нестандартный синтаксис или повреждённый файл | Запустить с `--verbose`; проверить, что файл поддерживается языком |
| `gitleaks` false positive на тестовом ключе | Шаблон совпал с тестовыми данными | Добавить хэш находки в `.gitleaksignore` или пометить файл через комментарий |
| `conftest` не видит политики | Неправильный путь или отсутствует `package main` | Проверить `--policy` путь; убедиться, что Rego начинается с `package main` |
| `trivy` не находит CVE | Устаревшая база или неправильный тип сканирования | Обновить `trivy image --download-db-only`; указать правильный тип (fs/image) |
| `checkov` пропускает ресурс | Ресурс не покрыт стандартными политиками | Написать кастомное правило или использовать `--check` с явным CKV-ID |
| `syft` генерирует пустой SBOM | Нет поддерживаемых артефактов в директории | Проверить, что в директории есть `package.json`, `go.mod`, `requirements.txt` и т.д. |
| Раннер видит чужие секреты | Scope переменных окружения не ограничен | Настроить `protected`/`environment` в CI; использовать masked/protected переменные |
| SARIF-файл пустой | Сканер не сработал или неверный формат вывода | Проверить команду запуска сканера; убедиться, что `--sarif` флаг активен |
| `gitlab-runner` не эфемерный | Флаг `--ephemeral` не установлен или не поддерживается | Проверить конфигурацию раннера; обновить до версии с поддержкой ephemeral |
| Pre-commit hook не срабатывает | Нет прав на выполнение или symlink сбит | `ls -l .git/hooks/pre-commit` → должен указывать на `pre-commit` |

## Рекомендации

### Хост-харднинг раннеров (Runner Hardening)

- **Эфемерные раннеры:** каждый джоб выполняется на свежем экземпляре, уничтожаемом после. GitLab: флаг `--ephemeral` у `gitlab-runner`; GitHub Actions: `runs-on: [self-hosted, ephemeral]`.
- **Наименьшие привилегии:** раннер работает под выделенным пользователем без широких прав; нет SSH-ключей к проду.

```bash
id gitlab-runner                 # → проверить, что раннер не в группе sudo/wheel
sudo -l -U gitlab-runner         # → должен выдавать только необходимые NOPASSWD-команды
```

- **Сетевая изоляция:** раннеры в отдельном VLAN; исходящий трафик — только к внутреннему registry/mirror и необходимым хостам (egress allowlist). Недоверенные зависимости тянутся через внутреннее зеркало, а не напрямую из интернета.
- **Очистка диска и workspace:** шифрование диска (LUKS), `clear_readonly` / очистка workspace между джобами; для контейнерных раннеров — read-only rootfs и `--rm`.
- **Секреты в рантайме:** инъекция через Vault/секрет-менеджер в память, никогда не пишутся на диск; маскировка в логах (`--mask` / settings).
- **Ограничение ядра:** seccomp/AppArmor-профили, запрет `privileged` контейнеров.

### Сетевая сегментация и управление доступом

- **Zero Trust на уровне раннеров:** каждый раннер обслуживает только определённый набор проектов/групп; нет общего раннера на всю организацию без network policies.
- **Egress-фильтрация:** исходящие соединения только к registry, artifact store и необходимым внешним API; всё остальное через proxy с DLP.
- **Segregation of Duties:** раннеры для PR/build отдельно от deploy/release; разные секреты, разные уровни доступа.

### Ресурсы и масштабирование

- **Ретенция артефактов:** SARIF, SBOM, логи сканеров — хранить 30–90 дней в зависимости от compliance требований; долгосрочная аналитика агрегируется в единый дашборд.
- **Кэширование зависимостей:** внутренний registry (Harbor/Nexus) с проксированием; кэш на уровне джоба для ускорения incremental SAST.
- **SLA для quality gate:** инкрементальный SAST — <5 мин, полный SAST — ночной джоб; SCA — <3 мин; gate блокирует на Critical/High с высокой уверенностью.

### Резервное копирование и восстановление CI/CD

- **Конфигурация пайплайнов:** версионируется в Git; потеря CI-конфигурации = потеря reproducibility.
- **Registry:** образы и артефакты реплицируются между регионами; retention policy = 90 дней для промежуточных, бессрочно для релизов.
- **Восстановление:** tested restore procedure для registry и artifact store; runbook на случай компрометации registry.

### Политики и метрики

- **Quality gate пороги:** Critical/High — блокировать; Medium — triage; Low — backlog.
- **Метрики программы:** Reachability Rate (<5% noise), MTTR (<4 часа для critical), Golden Path Adoption (% команд), Drift Recurrence.
- **Retention политики:** SARIF/logs 30–90 дней; SBOM — бессрочно для релизов; секреты — ротация каждые 90 дней.

### Чек-лист минимальной защищённости (Quick Reference)

1. **Pre-commit:** gitleaks + semgrep + conftest установлены у разработчиков.
2. **CI gate:** SAST/SCA/secret scan на PR; quality gate блокирует Critical/High.
3. **SBOM:** генерируется на каждом билде; хранится как артефакт.
4. **IaC:** проверка на PR; admission control на деплой.
5. **Раннеры:** эфемерные, изолированные, без широких прав.
6. **Секреты:** динамические, в памяти, маскированные, с ротацией.
7. **Мониторинг:** Falco/Tetragon для рантайма; drift detection для IaC.
8. **Backup:** registry и CI-конфигурация реплицированы; tested restore.
9. **Метрики:** автоматический сбор в дашборд; ежемесячный пересмотр порогов.

## Дополнительная информация

### Ключевые вызовы (2026)

1.  **Identity Sprawl:** Управление жизненным циклом миллионов кратковременных секретов и прав доступа (NHI).
2.  **Complexity of Supply Chain:** Сложность верификации всей цепочки транзитивных зависимостей даже при наличии SBOM.
3.  **Reachability Analysis:** Отсеивание ложных срабатываний через анализ достижимости уязвимого кода в рантайме.

### Метрики эффективности

- **Reachability Rate:** Процент обнаруженных уязвимостей, которые подтверждены как доступные для эксплуатации (цель: снижение до <5%).
- **MTTR (Mean Time to Remediate):** Среднее время от обнаружения до внедрения исправления (для критических уязвимостей в 2026 году цель — <4 часов).
- **Golden Path Adoption:** Процент команд, использующих стандартные безопасные шаблоны платформы.
- **Drift Recurrence:** Частота возникновения несанкционированных изменений в инфраструктуре.

### Операционный контекст: DevOps / SRE / Sysadmin (навигатор по смежным заметкам)

DevSecOps — это надстройка над инженерией ПО, поэтому инженер обязан владеть операционной (ops) частью: релизами, наблюдаемостью, инцидентами, Linux и сетью. Ниже — навигатор по уже существующим заметкам vault (без cloud/AI, ориентир — продакшен и собеседования). Дублировать их содержимое здесь не нужно; это точки входа под конкретный угол.

#### Теория (interview-уровень, без глубокой математики)
- **SRE: SLO/SLI/error budgets, four golden signals, burn rate** — [Concepts/sre_concepts_main.md](../../Concepts/sre_concepts_main.md).
- **DORA-метрики** (частота деплоев, lead time, MTTR, change failure rate) — [CI-CD/Core_Concepts/dora_metrics.md](../../CI-CD/Core_Concepts/dora_metrics.md).
- **CI/CD паттерны** (trunk-based vs GitFlow, ветвление) — [CI-CD/ci_cd_patterns.md](../../CI-CD/ci_cd_patterns.md), [CI-CD/Core_Concepts/pipeline_glossary.md](../../CI-CD/Core_Concepts/pipeline_glossary.md).
- **Стратегии деплоя (теория canary/blue-green)** — [CI-CD/Deployment_Strategies/comparison.md](../../CI-CD/Deployment_Strategies/comparison.md).

#### Практика — релиз и конфигурация
- **Canary / blue-green / rolling / rollback** — [canary_deployment](../../CI-CD/Deployment_Strategies/canary_deployment.md), [rolling_update](../../CI-CD/Deployment_Strategies/rolling_update.md), [progressive_delivery_gitops](../../GitOps/Concepts/progressive_delivery_gitops.md).
- **Feature flags / toggles** — [CI-CD/Testing/feature_toggles/best_practices.md](../../CI-CD/Testing/feature_toggles/best_practices.md).
- **Configuration management (Ansible: idempotency, roles, system config)** — [ansible-os-hardening](../../Ansible/ansible-os-hardening.md), [ansible_service_and_system_config_modules](../../Ansible/Modules/ansible_service_and_system_config_modules.md), [ansible_security_best_practices](../../Ansible/ansible_security_best_practices.md).
- **SCA и анализ зависимостей** — [SCA-инструменты: сравнение](../../Security/Supply_Chain_Security/sca_tools_comparison.md), [Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md), [Защита от dependency confusion](../../Security/Supply_Chain_Security/dependency_confusion_prevention.md).
- **Безопасность контейнеров** — [Сканирование образов](../../Docker/Docker_security/vulnerability_scanning.md), [Runtime monitoring](../../Docker/Docker_security/runtime_monitoring.md), [Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md), [Falco](../../Security/Tools/falco.md).

#### Практика — наблюдаемость, инциденты, нагрузка
- **Observability (Prometheus / Grafana / OTel / ELK)** — [Prometheus overview](../../Prometheus/kubernetes/overview.md), [Grafana overview](../../Grafana/grafana_overview.md), [LGTM/OTel stack](../../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_overview.md), [observability_driven_testing](../../CI-CD/Testing/observability_driven_testing.md).
- **Security Monitoring / Dashboard / Alerting** — [DevSecOps monitoring](./devsecops_monitoring.md), [Falco runtime security](../../Security/Tools/falco.md), [Tetragon eBPF](../../Security/Tools/tetragon.md).
- **Alerting-гигиена / on-call** — [Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).
- **Incident response / postmortem / troubleshooting-методология** — [Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md), [Incident Response для CI/CD](../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md), [Kubernetes incident response](../../Kubernetes/Security/incident_response.md), [Supply chain incident response](../../Security/Supply_Chain_Security/supply_chain_incident_response.md).
- **Load / performance testing** — [Testing/performance_testing_methodology.md](../../Testing/performance_testing_methodology.md), [CI-CD/Testing/load_testing_ci_cd.md](../../CI-CD/Testing/load_testing_ci_cd.md).
- **Capacity planning / saturation** — [Concepts/capacity-planning.md](../../Concepts/capacity-planning.md).
- **Vulnerability management / triage** — [CVE triage workflow](../../Security/Supply_Chain_Security/cve_triage_workflow.md), [Vulnerability management](../../Linux/Security/vulnerability_management.md), [Wazuh vulnerability detector](../../Security/Tools/Wazuh/wazuh-vulnerability-detector.md).

#### Практика — Linux/sysadmin, сеть, контейнеры, БД
- **Linux sysadmin (systemd / cgroups / namespaces / пользователи)** — [systemd/overview](../../Linux/Core/systemd/overview.md), [cgroups](../../Linux/Core/cgroups.md), [namespaces](../../Linux/Core/namespaces.md), [users_management](../../Linux/SystemAdministration/users_management.md).
- **Харденинг / CIS / аудит Linux** — [Security/Tools/lynis.md](../../Security/Tools/lynis.md), [Linux/Security/Mechanisms/Kernel/hardening.md](../../Linux/Security/Mechanisms/Kernel/hardening.md), [Linux/Security/vulnerability_management.md](../../Linux/Security/vulnerability_management.md).
- **Compliance / аудит** — [Audit and compliance overview](../../Security/audit_and_compliance_overview.md), [Ansible OS hardening](../../Ansible/ansible-os-hardening.md), [OpenSCAP](../../Ansible/ansible-os-hardening.md), [Kubernetes compliance](../../Kubernetes/Security/kyverno/Scenarios/automation_compliance.md).
- **Сеть (iptables / nftables / firewall)** — [iptables_basics](../../Linux/Networking/Settings/tools/iptables_basics.md), [nftables/practical_scenarios](../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md), [Networking/Concepts/firewall_concepts.md](../../Networking/Concepts/firewall_concepts.md).
- **SSH / bastion (cert-auth, fail2ban)** — [ssh_certificate_authentication](../../Linux/Security/ssh/server/ssh_certificate_authentication.md), [fail2ban](../../Linux/Security/Tools/fail2ban.md).
- **Container / image hardening & runtime (Falco)** — [Docker_security/overview](../../Docker/Docker_security/overview.md), [runtime_monitoring](../../Docker/Docker_security/runtime_monitoring.md), [Security/Tools/falco.md](../../Security/Tools/falco.md), [CI-CD/Testing/container_testing.md](../../CI-CD/Testing/container_testing.md).
- **Backup / DR (K8s, БД)** — [Kubernetes/Operations/backup-strategies.md](../../Kubernetes/Operations/backup-strategies.md), [Databases/Concepts/backups.md](../../Databases/Concepts/backups.md).
- **API security** — [WAF/WAAP](../../Security/ApplicationSecurity/waf.md), [HTTP security hardening](../../Networking/Protocols/HTTP/http_security_hardening.md), [API rate limiting](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md).

## См. также

- [Интеграция безопасности в CI/CD](./sast_dast_cicd_integration.md)
- [Управление секретами в CI/CD](./secrets_management.md)
- [Атаки на CI/CD](./cicd_attacks.md)