# DevSecOps — обзор методологии

## Определения

**DevSecOps (Development, Security, Operations)** — методология интеграции практик безопасности на всех этапах жизненного цикла разработки программного обеспечения (**SDLC — Software Development Life Cycle**). В 2026 году DevSecOps перешел от разрозненных сканеров к единой экосистеме управления рисками, глубоко интегрированной в платформенную инженерию (**Platform Engineering**).

**ASPM (Application Security Posture Management)** — центральная категория инструментов 2026 года, которая консолидирует данные из всех AST-сканеров, устраняет дубликаты и приоритизирует уязвимости на основе **анализа достижимости (Reachability Analysis)**. ASPM служит «единым окном» для ИБ-офицеров и разработчиков.

**AST (Application Security Testing)** — методы тестирования безопасности, дополненные ИИ:
- **SAST (Static AST):** семантический анализ кода с использованием LLM для понимания намерений и авто-исправлений. Подробно: [SAST](./sast_overview.md).
- **DAST (Dynamic AST):** автономный ИИ-пентестинг, исследующий API и бизнес-логику в рантайме. Подробно: [DAST](./dast_overview.md).
- **SCA (Software Composition Analysis):** анализ сторонних зависимостей через **Living SBOM** (динамический граф компонентов).
- **IAST (Interactive AST):** гибридный анализ через **eBPF**-инструментацию, обеспечивающий точность без изменения кода.

Сравнение подходов SAST и DAST, их границы применимости и комбинированный конвейер — в **[сравнении подходов SAST vs DAST](./sast_vs_dast.md)**.

**Supply Chain Security 2.0** — защита всей цепочки поставок артефактов, базирующаяся на стандарте **SLSA v2.0**, сквозной подписи образов и использовании **VEX (Vulnerability Exploitability eXchange)** для фильтрации неактуальных уязвимостей. Глубоко тема раскрыта в **[обзоре безопасности цепочки поставок](../../Security/Supply_Chain_Security/overview.md)**.

## Базовые концепции

### Принципы DevSecOps (2026)

- **Shift Left 2.0:** Безопасность встроена непосредственно в IDE и ИИ-копилоты. Уязвимости блокируются на этапе написания кода, а не после коммита.
- **Reachability-First:** Игнорирование уязвимостей в библиотеках, если уязвимый код физически не вызывается приложением. Это снижает «шум» сканеров на 70–90%.
- **Policy as Code (PaC):** Декларативное описание политик (Kyverno, OPA), которые автоматически применяются к IaC-манифестам и Kubernetes-кластерам.
- **Auto-Remediation:** Автоматическая генерация ИИ-агентами Pull Request с исправлениями, которые проходят валидацию тестами перед предложением разработчику.
- **NHI Security (Non-Human Identities):** Фокус на защите и ротации прав доступа для ИИ-агентов, сервисных аккаунтов и пайплайнов. В 2026 году NHI составляют до 95% всех цифровых сущностей.
- **Platform-Native Security:** Безопасность как часть внутреннего портала разработчика (IDP — Internal Developer Platform), где ИБ-проверки являются «золотыми путями» (Golden Paths).

### Инструменты и классификации (2026)

| Категория | Инструменты | Назначение |
| :--- | :--- | :--- |
| **ASPM** | Cycode, Apiiro, Snyk AppRisk | Оркестрация, корреляция и приоритизация рисков. |
| **SAST (AI-driven)** | Snyk DeepCode, Semgrep | Глубокий семантический анализ и авто-фикс. |
| **SCA / SBOM** | Trivy, Grype, Syft | Генерация Living SBOM и VEX-анализ. |
| **IaC Security** | Checkov, KICS, OPA | Проверка инфраструктурного кода (Terraform, Helm). Подробнее: [Defense in Depth в IaC](./iac-security-defense-in-depth.md). |
| **Secret Scan** | Gitleaks, TruffleHog | Поиск секретов в Git, Slack, документации и логах. |
| **DAST (Autonomous)** | XBOW, Penligent, Nuclei | Автономный ИИ-пентестинг и защита API. |
| **Runtime (eBPF)** | Falco, Tetragon, Pixie | Обнаружение аномалий и дрейфа конфигурации (Drift Detection) в ядре. |
| **AI Security** | Giskard, Lakera | Тестирование промптов и ИИ-моделей на уязвимости. |

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
    - ИИ-ассистенты анализируют архитектуру и требования, подсвечивая риски безопасности на этапе планирования (Threat Modeling as Code).
2.  **Разработка (Code):**
    - **IDE Scanning:** обнаружение уязвимостей и секретов в реальном времени.
    - **AI Auto-Fix:** предложение исправлений прямо в редакторе кода.
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
# → gitleaks: найден секрет (AWS_KEY) → коммит заблокирован
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

## Дополнительная информация

### Ключевые вызовы (2026)

1.  **AI Trust:** Проблема доверия к автоматическим исправлениям, генерируемым ИИ-агентами. Необходимы строгие регрессионные тесты.
2.  **Identity Sprawl:** Управление жизненным циклом миллионов кратковременных секретов и прав доступа (NHI).
3.  **Complexity of Supply Chain:** Сложность верификации всей цепочки транзитивных зависимостей даже при наличии SBOM.

### Метрики эффективности

- **Reachability Rate:** Процент обнаруженных уязвимостей, которые подтверждены как доступные для эксплуатации (цель: снижение до <5%).
- **MTTR (Mean Time to Remediate):** Среднее время от обнаружения до внедрения исправления (для критических уязвимостей в 2026 году цель — <4 часов).
- **Golden Path Adoption:** Процент команд, использующих стандартные безопасные шаблоны платформы.
- **Drift Recurrence:** Частота возникновения несанкционированных изменений в инфраструктуре.

### Операционные рекомендации для DevOps/SRE/Sysadmin

Внедрение DevSecOps — это не только установка сканеров, но и эксплуатация инфраструктуры безопасности.

- **Где запускать сканеры:** предпочтительно на **self-hosted раннерах** (GitLab Runner, GitHub Actions self-hosted), если исходный код не должен покидать периметр. SaaS-сканеры удобны, но передают код третьей стороне — для приватных репозиториев это неприемлемо.
- **Стратегия по этапам SDLC:**
  - *Pre-commit / IDE:* быстрые лёгкие проверки (gitleaks, semgrep, conftest) — мгновенный feedback разработчику (см. Пример 1, 2).
  - *PR / CI:* **инкрементальный** анализ только изменений — дешево по времени, не блокирует из-за исторических находок.
  - *Nightly / релизная ветка:* **полный** анализ всего репозитория и сборка SBOM — нахождение накопленного долга.
  - *Admission / Deploy:* проверка подписей и политик перед запуском (см. IaC-гайд и supply chain).
- **Хранение и ротация отчётов:** SARIF и отчёты сканеров сохраняйте как артефакты CI и/или в объектное хранилище (MinIO/NFS) с ротацией 30–90 дней — это основа трендов и аудита. Долгосрочная аналитика агрегируется в единый дашборд.
- **Управление секретами в раннерах:** динамические секреты через Vault/секрет-менеджер, инъекция в рантайме, маскировка в логах, строгая ротация. Подробнее — в **[управлении секретами в CI/CD](./secrets_management.md)**.
- **Мониторинг рантайма:** аномалии и дрейф конфигурации отслеживаются средствами на базе eBPF (Falco, Tetragon) и аудит-логами — это замыкание петли обратной связи (второй путь DevOps).
- **Инцидент-респонс:** runbook на случай находки критической уязвимости в проде, blameless postmortem, связь MTTR с метриками выше.
- **Безопасность самих раннеров:** эфемерность, изоляция, наименьшие привилегии (см. Пример 3).

### Чек-лист внедрения DevSecOps

Практический чек-лист для старта программы (people / process / tech):

1.  **People:** назначены security champions в командах; проведено базовое обучение разработчиков; Sec-команда перешла от «блокировщика» к « enabler».
2.  **Process:** определён владелец программы; проведён ассессмент зрелости (DSEC/OWASP SAMM); выбраны 2–3 целевых направления; заданы пороги блокировки (Critical/High).
3.  **Tech — Plan/Code:** pre-commit hooks (gitleaks + semgrep), threat modeling для критичных сервисов.
4.  **Tech — Build/Test:** инкрементальный SAST, SCA + SBOM, secret scanning в CI; quality gate на PR.
5.  **Tech — Deploy/Run:** admission control / проверка подписей; мониторинг рантайма (Falco); регулярный VEX-анализ зависимостей.
6.  **Measure:** автоматический сбор метрик (см. Пример 4) в дашборд; ежемесячный пересмотр порогов и FP-rate.

## Операционный контекст: DevOps / SRE / Sysadmin (навигатор по смежным заметкам)

DevSecOps — это надстройка над инженерией ПО, поэтому инженер обязан владеть операционной (ops) частью: релизами, наблюдаемостью, инцидентами, Linux и сетью. Ниже — навигатор по уже существующим заметкам vault (без cloud/AI, ориентир — продакшен и собеседования). Дублировать их содержимое здесь не нужно; это точки входа под конкретный угол.

### Теория (interview-уровень, без глубокой математики)
- **SRE: SLO/SLI/error budgets, four golden signals, burn rate** — [Concepts/sre_concepts_main.md](../../Concepts/sre_concepts_main.md).
- **DORA-метрики** (частота деплоев, lead time, MTTR, change failure rate) — [CI-CD/Core_Concepts/dora_metrics.md](../../CI-CD/Core_Concepts/dora_metrics.md).
- **CI/CD паттерны** (trunk-based vs GitFlow, ветвление) — [CI-CD/ci_cd_patterns.md](../../CI-CD/ci_cd_patterns.md), [CI-CD/Core_Concepts/pipeline_glossary.md](../../CI-CD/Core_Concepts/pipeline_glossary.md).
- **Стратегии деплоя (теория canary/blue-green)** — [CI-CD/Deployment_Strategies/comparison.md](../../CI-CD/Deployment_Strategies/comparison.md).

### Практика — релиз и конфигурация
- **Canary / blue-green / rolling / rollback** — [canary_deployment](../../CI-CD/Deployment_Strategies/canary_deployment.md), [rolling_update](../../CI-CD/Deployment_Strategies/rolling_update.md), [progressive_delivery_gitops](../../GitOps/Concepts/progressive_delivery_gitops.md).
- **Feature flags / toggles** — [CI-CD/Testing/feature_toggles/best_practices.md](../../CI-CD/Testing/feature_toggles/best_practices.md).
- **Configuration management (Ansible: idempotency, roles, system config)** — [ansible-os-hardening](../../Ansible/ansible-os-hardening.md), [ansible_service_and_system_config_modules](../../Ansible/Modules/ansible_service_and_system_config_modules.md), [ansible_security_best_practices](../../Ansible/ansible_security_best_practices.md).

### Практика — наблюдаемость, инциденты, нагрузка
- **Observability (Prometheus / Grafana / OTel / ELK)** — [Prometheus overview](../../Prometheus/kubernetes/overview.md), [Grafana overview](../../Grafana/grafana_overview.md), [LGTM/OTel stack](../../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_overview.md), [observability_driven_testing](../../CI-CD/Testing/observability_driven_testing.md).
- **Alerting-гигиена / on-call** — [Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).
- **Incident response / postmortem / troubleshooting-методология** — [Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md).
- **Load / performance testing** — [Testing/performance_testing_methodology.md](../../Testing/performance_testing_methodology.md), [CI-CD/Testing/load_testing_ci_cd.md](../../CI-CD/Testing/load_testing_ci_cd.md).
- **Capacity planning / saturation** — [Concepts/capacity-planning.md](../../Concepts/capacity-planning.md).

### Практика — Linux/sysadmin, сеть, контейнеры, БД
- **Linux sysadmin (systemd / cgroups / namespaces / пользователи)** — [systemd/overview](../../Linux/Core/systemd/overview.md), [cgroups](../../Linux/Core/cgroups.md), [namespaces](../../Linux/Core/namespaces.md), [users_management](../../Linux/SystemAdministration/users_management.md).
- **Харденинг / CIS / аудит Linux** — [Security/Tools/lynis.md](../../Security/Tools/lynis.md), [Linux/Security/Mechanisms/Kernel/hardening.md](../../Linux/Security/Mechanisms/Kernel/hardening.md), [Linux/Security/vulnerability_management.md](../../Linux/Security/vulnerability_management.md).
- **Сеть (iptables / nftables / firewall)** — [iptables_basics](../../Linux/Networking/Settings/tools/iptables_basics.md), [nftables/practical_scenarios](../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md), [Networking/Concepts/firewall_concepts.md](../../Networking/Concepts/firewall_concepts.md).
- **SSH / bastion (cert-auth, fail2ban)** — [ssh_certificate_authentication](../../Linux/Security/ssh/server/ssh_certificate_authentication.md), [fail2ban](../../Linux/Security/Tools/fail2ban.md).
- **Container / image hardening & runtime (Falco)** — [Docker_security/overview](../../Docker/Docker_security/overview.md), [runtime_monitoring](../../Docker/Docker_security/runtime_monitoring.md), [Security/Tools/falco.md](../../Security/Tools/falco.md), [CI-CD/Testing/container_testing.md](../../CI-CD/Testing/container_testing.md).
- **Backup / DR (K8s, БД)** — [Kubernetes/Operations/backup-strategies.md](../../Kubernetes/Operations/backup-strategies.md), [Databases/Concepts/backups.md](../../Databases/Concepts/backups.md).

## См. также

- [Интеграция безопасности в CI/CD](./sast_dast_cicd_integration.md)
- [Управление секретами в CI/CD](./secrets_management.md)
- [Атаки на CI/CD](./cicd_attacks.md)
