# Security Champions программа

## Определения

**Security Champion** — разработчик, тестировщик, SRE или sysadmin в продуктовой команде, который получает дополнительное обучение по безопасности и выступает как связующее звено между продуктовой командой и Security-командой. Security Champion не является заменой Security-команды, а расширяет её охват, обеспечивая Shift Left.

**Security Champions Program** — организационная программа, которая формализует роли, обязанности, обучение и метрики эффективности Security Champions в компании.

**Shift Left** — философия интеграции безопасности на ранних этапах SDLC, а не только на этапе тестирования или продакшена. Security Champions — ключевой механизм Shift Left на уровне культуры.

**Security Advocacy** — деятельность по продвижению культуры безопасности внутри команды: обучение, консультации, ревью кода на безопасность, помощь в использовании инструментов.

**Security Debt** — накопленные уязвимости, небезопасные практики и архитектурные решения, которые принимаются сознательно или по незнанию, но создают риск в будущем. Security Champions помогают снижать security debt на уровне команды.

**SRE и Security Champions** — в контексте SRE Champion дополняет роль оператора, беря на себя безопасность кода и pipeline, mientras SRE фокусируется на рантайм-безопасности, инфраструктуре и incident response.

**Sysadmin и Security Champions** — системный администратор обеспечивает жёсткий базис: hardening хостов, аудит, compliance (CIS, ФСТЭК), управление доступом и сегментацию; Champion интегрирует эти требования в процессы разработки.

## Базовые концепции

### Модель зрелости Security Champions Program

**Level 1 — Инициация:**
- Назначение 1-2 enthusiastic разработчиков/SRE/sysadmin в каждую команду.
- Базовое обучение (OWASP Top 10, secure coding, базовый аудит).
- Роль неформальная, без выделенного времени.

**Level 2 — Формализация:**
- Официальное название роли, job description.
- Регулярное обучение (раз в квартал).
- Выделенное время (10-20% рабочего времени) на security-related задачи.
- Security Champions участвуют в threat modeling и design review.
- Интеграция с SRE-процессами: Champion участвует в incident response как представитель команды.

**Level 3 — Операционная эффективность:**
- Security Champions проводят code review на безопасность.
- Написание кастомных правил для SAST-сканеров.
- Ведение security backlog в команде.
- Участие в threat modeling, design review и postmortem.
- Ведение compliance-документации (audit trail, evidence для проверок).

**Level 4 — Платформа:**
- Security Champions автоматизируют проверки (pre-commit hooks, CI gates).
- Пишут reusable security components (middleware, библиотеки).
- Участвуют в формировании security strategy команды.
- Менторство новых Champions.
- Интеграция security metrics в SLO/SLI и error budgets.

### Роли и ответственность

**Security Champion (в команде):**
- Проводит threat modeling для новых фич.
- Участвует в design review с точки зрения безопасности.
- Решает санитайзеры SAST-находок, объясняет контекст.
- Помогает команде использовать security tools (Semgrep, Checkov, Trivy).
- Является первым контактом для Security-команды по вопросам безопасности.
- Повышает security awareness внутри команды (внутренние воркшопы, lunch & learn).
- Представляет команду в incident response и postmortem.
- Следит за compliance требованиями, актуальностью audit evidence.

**Security-команда (центр компетенций):**
- Разрабатывает программу обучения и метрики.
- Обеспечивает инструменты и платформы (SAST, DAST, SCA, IaC scanning, secret scanning).
- Консультирует Champions по сложным вопросам.
- Проводит регулярные sync и обучения.
- Отвечает за глобальные политики и compliance.
- Разрабатывает runbooks для типовых escalations.

**Management:**
- Выделяет время для Champions (10-20% FTE).
- Поддерживает культуру, где безопасность ценится.
- Интегрирует security metrics в OKR/KPI команд.

**SRE / Operations:**
- Обеспечивает изоляцию и hardening CI/CD-раннеров (эфемерные инстансы, минимальные привилегии, egress allowlist).
- Настраивает runtime monitoring (Falco, auditd, journald) и алертинг на аномалии.
- Управляет секретами в рантайме (Vault, переменные окружения, маскировка в логах).
- Обеспечивает backup CI-конфигурации и артефактов, tested restore.
- Участвует в incident response как technical lead по инфраструктуре.

**Sysadmin:**
- Применяет host hardening (CIS benchmarks, kernel hardening, seccomp/AppArmor).
- Настраивает аудит (auditd, journald) и централизованный сбор логов.
- Обеспечивает compliance (ФСТЭК, PCI, GDPR) на уровне хостов и сети.
- Управляет сегментацией сети, firewall, VPN/ bastion.
- Ведёт инвентаризацию и lifecycle пакетов.

### Обучение и onboarding

**Onboarding Champion (первые 2 недели):**
1. **Базовый курс безопасности:** OWASP Top 10, secure coding principles, common pitfalls.
2. **Инструменты команды:** настройка SAST/SCA/IaC сканеров в локальной среде, использование pre-commit hooks.
3. **Security-команда introduction:** знакомство с Architect, AppSec, governance, escalation procedures.
4. **Первая задача:** threat model для текущего спринта.

**Регулярное обучение (ежемесячно/ежеквартально):**
1. **Workshops:** hands-on сессии по новым инструментам, новым типам уязвимостей.
2. **CTF и wargames:** практические задания на поиск и exploitation уязвимостей.
3. **Code review sessions:** разбор security-находок в PR команды.
4. **Threat modeling sessions:** регулярное обновление threat model для новых фич.
5. **Conferences и certifications:** поддержка участия в конференциях (OWASP, DevSecCon) и получения сертификатов (OSCP, GWAPT, CSSLP).

### Метрики эффективности

**Quantitative метрики:**
- **Security Findings Coverage:** процент security-находок, закрытых командой самостоятельно (без escalations к Security-команде).
- **Time to Triage:** среднее время от обнаружения уязвимости до её обсуждения в команде.
- **SAST/SCA Findings Resolution Rate:** процент findings, закрытых в течение SLA.
- **Security Debt Ratio:** доля security-находок, открытых более 30 дней.
- **Training Completion Rate:** процент Champions, прошедших регулярное обучение.
- **Pre-commit Adoption:** процент разработчиков команды, использующих pre-commit hooks.
- **MTTR (Mean Time to Remediate):** среднее время от обнаружения до исправления security-инцидента (для SRE-контекста).
- **Error Budget Consumption for Security:** процент «потреблённого» error budget из-за security-инцидентов (интеграция с SLO).
- **Compliance Drift:** количество отклонений от baseline hardening или policy за квартал.

**Qualitative метрики:**
- **Developer Satisfaction:** опросы разработчиков о восприятии security-инструментов и процессов.
- **Security Awareness:** количество security-related вопросов в команде, участие в lunch & learn.
- **Code Quality:** снижение количества security-находок в PR overtime.
- **Cross-functional Collaboration:** оценка Security-командой эффективности взаимодействия с Champion.
- **SRE Satisfaction:** оценка SRE-командой готовности команды к incident response и maturity security практик.

### Anti-patterns

**Security Champion как буфер:**
- Security-команда делегирует всю работу Champion и отключается. Champion не должен быть единственным security-инженером в команде.

**Только теоретическое обучение:**
- Обучение без hands-on практики не даёт результата. Champions должны практиковаться на реальных findings.

**Hero Culture:**
- Champion берёт на себя всю security-нагрузку, выгорает. Необходимо распределять ответственность и ротировать роль.

**Отсутствие времени:**
- Champion должен иметь выделенное время (10-20% FTE). Без этого роль degenerates в "дополнительную задачу поверх основной работы".

**Отсутствие поддержки management:**
- Без поддержки руководителя Security Champions program обречён. Management должен поощрять участие и учитывать в performance review.

**Security как纯 dev-концерн:**
- Игнорирование инфраструктуры и рантайма. Программа должна покрывать весь SDLC, включая deployment и operations (SRE/Sysadmin ответственность).

## Практические сценарии

### Пример 1: Запуск Security Champions Program в организации

**Phase 1: Planning (2-4 недели)**
1. **Assess maturity:** провести опрос Security-команды, разработчиков и SRE, оценить текущее состояние security culture.
2. **Define goals:** определить целевые метрики (например, снижение security findings на 30%, увеличение coverage SAST на 20%, сокращение MTTR security-инцидентов).
3. **Select Champions:** выбрать enthusiastic developers/SRE/sysadmin из каждой команды; обсудить с managers.
4. **Design program:** определить обучение, время (10% FTE), механизм escalations, feedback loop.

**Phase 2: Onboarding (1-2 недели)**
1. **Kick-off meeting:** представление программы, целей, ожиданий.
2. **Basic training:** OWASP Top 10, secure coding, инструменты команды.
3. **Mentorship:** назначение ментора из Security-команды для каждого Champion.
4. **First task:** threat model для текущего спринта, review security backlog.

**Phase 3: Operation (ongoing)**
1. **Monthly sync:** встреча Champions для обмена опытом, обсуждения сложных findings.
2. **Quarterly workshops:** hands-on сессии по новым уязвимостям, инструментам.
3. **Code review:** Champions участвуют в security review PR.
4. **Metrics tracking:** сбор метрик, dashboard в Grafana.
5. **Annual review:** оценка эффективности программы, корректировка целей.

**Validation:** program dashboard показывает динамику security findings, coverage, champion satisfaction; Security-команда получает регулярный feedback.

### Пример 2: Threat Modeling сессия с участием Security Champion

**Предусловия:** новый feature в спринте, Champion назначен, Security Architect доступен.

**1. Подготовка:**
- Champion получает документацию по feature (requirements, architecture diagram).
- Подготавливает DFD (Data Flow Diagram) с границами доверия.

**2. Сессия threat modeling (1-2 часа):**
- Участники: разработчики, QA, Champion, Security Architect, SRE (по необходимости).
- Инструменты: OWASP Threat Dragon, draw.io, либо ADR в Git.
- Процесс:
  1. Описать assets (PII, секреты, бизнес-логика, инфраструктура).
  2. Описать attack surface (API, формы, очереди, внешние интеграции).
  3. Для каждого trust boundary применить STRIDE.
  4. Оценить вероятность и impact.
  5. Определить контрмеры.

**3. Итоги:**
- Threat model зафиксирован в репозитории как `ADR-XXX-threat-model.md`.
- Security backlog пополнен задачами на mitigations.
- Champion отвечает за отслеживание выполнения mitigations.

**Validation:** threat model существует, reviewed Security-командой, mitigations tracked в backlog; Champion понимает, какие риски принимаются сознательно.

### Пример 3: Pre-commit hooks в команде под руководством Champion

Champion внедряет pre-commit hooks для автоматической проверки безопасности.

**1. Установка hooks:**

```bash
pipx install pre-commit
cat > .pre-commit-config.yaml <<'EOF'
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - id: gitleaks
  - repo: https://github.com/semgrep/semgrep
    rev: v1.178.0
    hooks:
      - id: semgrep
        args: ['--config', 'p/security-audit', '--error', '--quiet']
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
EOF
pre-commit install
```

**2. Обучение команды:**
- Champion проводит lunch & learn session (30 мин) о hooks.
- Разъясняет, как обрабатывать ложные срабатывания (`.gitleaksignore`, `# pragma: allowlist secret`).
- Настраивает CI gate, который проверяет, что hooks актуальны.

**3. Поддержание:**
- Champion обновляет baseline (`detect-secrets scan --update .secrets.baseline`) раз в квартал.
- Отвечает на вопросы команды по настройке и исключениям.
- Документирует common false positives в team wiki.

**Validation:** 100% разработчиков команды используют hooks; количество секретов в Git-истории = 0; Champion тратит <1 часа в неделю на поддержку.

### Пример 4: Security Champions Sync — формат и agenda

**Частота:** ежемесячно, 1 час.

**Участники:** все Security Champions, Security Architect, AppSec lead, представитель SRE.

**Agenda:**
1. **Updates от Champions (15 мин):**
   - Security findings в команде за месяц.
   - Сложные случаи, требующие помощи Security-команды.
   - Предложения по улучшению процессов.
   - Обновления по compliance/аудит.

2. **Training / Workshop (20 мин):**
   - Разбор нового типа уязвимости (например, GraphQL introspection leaks).
   - Hands-on: написание Semgrep правила для конкретного findings.
   - Обзор новых инструментов или обновлений.
   - Разбор recent security incidents и postmortem takeaways.

3. **Metrics Review (10 мин):**
   - Security findings coverage по командам.
   - Time to triage, MTTR.
   - Security debt ratio.
   - Error budget consumption for security.

4. **Open Discussion (15 мин):**
   - Вопросы, blockers.
   - Планы на следующий месяц.
   - Обратная связь о программе.

**Validation:** sync проходит регулярно, Champions активы, решения по blockers принимаются, feedback фиксируется.

### Пример 5: Интеграция Champions в Incident Response (SRE/Sysadmin контекст)

Security Champion — первый контакт внутри команды при security-инциденте.

**Процесс:**
1. **Detection:** SRE получает алерт (например, Falco: `Suspicious process spawned in container`).
2. **Triage:** Champion быстро определяет, затронута ли его команда; если да — эскалирует в Security-команду и инициирует war room.
3. **Containment:** Champion помогает SRE изолировать компонент (откатить деплой, отозвать секрет, заблокировать IP).
4. **Evidence:** Champion собирает логи, SARIF-отчёты, evidence для postmortem.
5. **Remediation:** Champion координирует патч с разработчиками.
6. **Postmortem:** Champion участвует в blameless postmortem, обновляет threat model и security backlog.

**Validation:** incident response runbook обновлён; threat model включает новый вектор; security backlog содержит mitigation tasks; error budget восстановлен.

### Пример 6: Compliance и audit подготовка (Sysadmin/SRE контекст)

Champion координирует подготовку к compliance аудиту (ФСТЭК, PCI, внутренний аудит).

**1. Inventory:**
- Champion собирает SARIF-отчёты, SBOM, evidence policy as code.
- Sysadmin предоставляет auditd-логи, hardening baseline (CIS benchmark).
- SRE предоставляет evidence эфемерных раннеров, секрет-менеджмента.

**2. Гap analysis:**
- Сравниваем текущее состояние с требованиями compliance.
- Champion ведёт backlog remediation задач.

**3. Remediation:**
- Champions координирует фиксы: обновление зависимостей, исправление misconfigurations, закрытие security debt.
- Sysadmin применяет host hardening, обновляет политики.

**4. Evidence package:**
- Всё собрано в Git-репозитории с версионированием.
- Champion проводит dry-run с Security-командой.

**Validation:** audit evidence package собран и проверен; все критические findings закрыты; compliance baseline пройден.

## Оперативные команды

### Безопасность и сканирование

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `pre-commit install` | Установка git hooks | Hooks активированы для текущего репозитория |
| `semgrep scan --config p/security-audit . --sarif -o report.sarif` | Быстрый SAST в локальной среде | SARIF-отчёт с security findings |
| `gitleaks detect --source=.` | Поиск секретов | Пустой вывод или список находок |
| `detect-secrets scan --update .secrets.baseline` | Обновление baseline | Обновлённый `.secrets.baseline` |
| `trivy fs .` | SCA-анализ файловой системы | Таблица CVE по критичности |
| `checkov -d . --framework dockerfile,kubernetes --compact` | IaC сканирование | Список небезопасных конфигураций |
| `conftest test --policy policy/ deploy.yaml` | Проверка IaC-манифеста на соответствие политикам Rego | PASS или список нарушений |

### Threat Modeling

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `threat-dragon` (OWASP Threat Dragon) | Инструмент threat modeling | DFD, STRIDE, mitigations; экспорт в Git |
| `draw.io` / `plantuml` | Построение DFD и диаграмм | Визуальная модель attack surface |
| `codeql database create db --language=python && codeql database analyze db --format=sarif-latest --output=codeql.sarif` | Глубокий SAST | SARIF с межпроцедурными находками |
| `nuclei -u target -severity critical,high -json` | Быстрый DAST | JSON с CVE и misconfigurations |

### SRE / Sysadmin — аудит и hardening

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `lynis audit system` | Аудит безопасности Linux-хоста | Отчёт по hardening gaps по CIS benchmark |
| `open-scap` | Сканирование хоста на соответствие STIG/CIS | HTML/XML отчёт с отклонениями |
| `auditctl -l` | Просмотр активных audit-правил | Список syscall и path monitor rules |
| `sudo -l -U gitlab-runner` | Проверка привилегий раннера | Только необходимые NOPASSWD-команды, нет ALL |
| `journalctl -u sshd --since "1 hour ago"` | Просмотр логов аутентификации | Обнаружение brute-force, подозрительных входов |
| `ss -tulpn` | Просмотр открытых портов | Список слушающих сокетов, контроль exposed surface |
| `id gitlab-runner` | Проверка группы пользователя раннера | Нет membership в sudo/wheel |
| `grype sbom:sbom.json` | Сканирование SBOM на известные CVE | Список уязвимых пакетов |

## Устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Champions не находят время | Нет выделенного FTE или поддержки management | Обсудить с руководителем; целевой показатель 10-20% FTE |
| Разработчики игнорируют findings | Слишком агрессивные правила, высокий FP rate | Настроить baseline, сузить правила под домен команды, объяснить impact |
| Security-команда перегружена escalations | Champions не обучены для решения типовых задач | Провести дополнительные workshops, создать runbooks для типовых escalations |
| Threat model устаревает быстро | Нет регулярного обновления | Встроить threat model review в Definition of Done для каждой фичи |
| Pre-commit hooks сломаны | Устаревшие версии инструментов | Настроить автообновление версий в `.pre-commit-config.yaml` |
| Раннер видит чужие секреты | Scope переменных окружения не ограничен | Настроить `protected`/`environment` в CI; использовать masked/protected переменные |
| SRE не доверяет pipeline | Нет изоляции, hardening, audit logging | Применить чек-лист hardening: эфемерные раннеры, egress allowlist, audit logs |
| Audit не проходит | Отсутствие evidence или drift от baseline | Назначить Champion ответственным за evidence; настроить drift detection |

## Рекомендации

### Успешные паттерны

- **Voluntary participation:** Champions должны быть volunteers, а не назначенные сверху. enthusiastic developers дают лучший результат.
- **Clear expectations:** чёткое описание роли, времени, ожидаемых результатов; без этого Champion не будет понимать, что от него требуется.
- **Regular feedback:** ежемесячные sync, обратная связь от Security-команды, признание достижений.
- **Integration в team processes:** Champions участвуют в sprint planning, design review, retrospective — security становится частью ежедневной работы, а не отдельным мероприятием.
- **Career growth:** участие в программе должно учитываться в performance review, способствовать карьерному росту.
- **SRE integration:** Champion и SRE совместно отвечают за безопасность от коммита до рантайма; нет разрыва между "dev security" и "ops security".
- **Compliance by design:** Champion внедряет security controls, которые одновременно закрывают compliance gaps (например, audit trail для САБ, evidence для ФСТЭК).

### Питфоллы

- **Tokenism:** назначение Champions для галочки, без реального времени и полномочий.
- **Security as blocker:** Champions воспринимаются как "полицейские", которые блокируют разработку. Фокус на enablement, а не enforcement.
- **One-size-fits-all:** разные команды имеют разные domain knowledge; Champions должны специализироваться на domain-специфичных рисках.
- **Neglecting Blue Team:** Champions концентрируются только на Shift Left, забывая про runtime monitoring и incident response. Программа должна покрывать весь SDLC.
- **Dev-only security:** Champion не должен ограничиваться кодом; инфраструктура, CI/CD, compliance — общая ответственность с SRE/Sysadmin.
- **Tool sprawl без стандартизации:** каждая команда выбирает свои инструменты; результат — несовместимые отчёты и дублирование effort. Выбирайте 1-2 инструмента на категорию и стандартизируйте.

### Tooling

- **SAST/SCA/IaC:** Semgrep, CodeQL, Checkov, Trivy — Champions должны уметь настраивать и использовать.
- **Pre-commit:** gitleaks, detect-secrets, semgrep, checkov — автоматизация в локальной среде.
- **Threat Modeling:** OWASP Threat Dragon, draw.io, ADR в Git.
- **Communication:** Slack/Teams channel для Champions, wiki для документации, Grafana dashboard для метрик.
- **SRE tools:** Falco, auditd, journald, Vault — интеграция с runtime security и секрет-менеджментом.
- **Compliance:** OpenSCAP, Lynis, CIS-CAT — Champions и Sysadmin совместно поддерживают hardening baseline.

### Ограничения и edge cases

- **Legacy-код:** Threat modeling и SAST на legacy-коде часто дают высокий FP rate; требуется калибровка правил под конкретный код.
- **Монопольный Champion:** если Champion уходит — команда теряет компетенцию. Необходимо ротировать роль и документировать процессы.
- **False positives в compliance:** автоматические сканеры не заменяют экспертизу; audit требует manual validation.
- **Гибридные команды:** распределённые команды с разной доступностью инструментов; нужны стандарты, работающие offline и в sandboxed средах.
- **Эфемерные среды:** pre-commit hooks и baseline нужно переустанавливать на новых машинах; автоматизируйте через onboarding скрипты.

## Дополнительная информация

### Связь с другими доменами

- **DevSecOps culture:** Security Champions — ключевой механизм культурного Shift Left — в **[DevSecOps overview](./devsecops_overview.md)**.
- **Threat Modeling:** methodology и практика threat modeling — в **[DevSecOps overview](./devsecops_overview.md)** (раздел Threat Modeling) и **[OWASP Threat Model cheat sheet](https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html)**.
- **SAST/DAST/SCA:** инструменты, которые Champions используют — в **[SAST — обзор](./sast_overview.md)**, **[DAST — обзор](./dast_overview.md)**, **[SCA и анализ зависимостей](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.
- **Incident Response:** Champions участвуют в postmortem как representatives команды — в **[Incident Response для CI/CD](../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md)**.
- **IaC Security:** Champions работают с Checkov и OPA для hardening инфраструктуры — в **[Defense in Depth в IaC](./iac-security-defense-in-depth.md)**.
- **SRE и Observability:** интеграция security metrics в SLO/SLI — в **[SRE Concepts](../../Concepts/sre_concepts_main.md)**, **[Prometheus overview](../../Prometheus/kubernetes/overview.md)**.
- **Sysadmin / hardening:** базовые практики hardening — в **[Linux Security Mechanisms Overview](../../Linux/Security/Linux_Security_Mechanisms_Overview.md)**, **[Lynis](../../Security/Tools/lynis.md)**, **[OpenSCAP в Ansible](../../Ansible/ansible-os-hardening.md)**.

### Ресурсы

- **OWASP Security Champions Guide:** https://owasp.org/www-project-security-champions-playbook/
- **Snyk Security Champions:** https://snyk.io/articles/security-champions

### Операционный контекст: DevOps / SRE / Sysadmin

Security Champions — организационный механизм. Его эффективность зависит от операционной базы: релизов, наблюдаемости, hardening, compliance и incident response. Ниже — навигатор по уже существующим заметкам vault (ориентир — продакшен и собеседования).

#### Теория (interview-уровень, без глубокой математики)
- **SRE: SLO/SLI/error budgets, four golden signals, burn rate** — [Concepts/sre_concepts_main.md](../../Concepts/sre_concepts_main.md).
- **DORA-метрики** (частота деплоев, lead time, MTTR, change failure rate) — [CI-CD/Core_Concepts/dora_metrics.md](../../CI-CD/Core_Concepts/dora_metrics.md).
- **CI/CD паттерны** (trunk-based vs GitFlow, ветвление) — [CI-CD/ci_cd_patterns.md](../../CI-CD/ci_cd_patterns.md), [CI-CD/Core_Concepts/pipeline_glossary.md](../../CI-CD/Core_Concepts/pipeline_glossary.md).

#### Практика — релиз и конфигурация
- **Canary / blue-green / rolling / rollback** — [canary_deployment](../../CI-CD/Deployment_Strategies/canary_deployment.md), [rolling_update](../../CI-CD/Deployment_Strategies/rolling_update.md).
- **Configuration management (Ansible: idempotency, roles, system config)** — [ansible-os-hardening](../../Ansible/ansible-os-hardening.md), [ansible_service_and_system_config_modules](../../Ansible/Modules/ansible_service_and_system_config_modules.md).
- **SCA и анализ зависимостей** — [SCA-инструменты: сравнение](../../Security/Supply_Chain_Security/sca_tools_comparison.md), [Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md).

#### Практика — наблюдаемость, инциденты, нагрузка
- **Observability (Prometheus / Grafana / OTel / ELK)** — [Prometheus overview](../../Prometheus/kubernetes/overview.md), [Grafana overview](../../Grafana/grafana_overview.md).
- **Security Monitoring / Alerting** — [DevSecOps monitoring](./devsecops_monitoring.md), [Falco runtime security](../../Security/Tools/falco.md).
- **Incident response / postmortem / troubleshooting-методология** — [Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md), [Incident Response для CI/CD](../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md).
- **Load / performance testing** — [Testing/performance_testing_methodology.md](../../Testing/performance_testing_methodology.md), [CI-CD/Testing/load_testing_ci_cd.md](../../CI-CD/Testing/load_testing_ci_cd.md).
- **Vulnerability management / triage** — [CVE triage workflow](../../Security/Supply_Chain_Security/cve_triage_workflow.md), [Vulnerability management](../../Linux/Security/vulnerability_management.md).

#### Практика — Linux/sysadmin, сеть, контейнеры, БД
- **Linux sysadmin (systemd / cgroups / namespaces / пользователи)** — [systemd/overview](../../Linux/Core/systemd/overview.md), [cgroups](../../Linux/Core/cgroups.md), [namespaces](../../Linux/Core/namespaces.md), [users_management](../../Linux/SystemAdministration/users_management.md).
- **Харденинг / CIS / аудит Linux** — [Security/Tools/lynis.md](../../Security/Tools/lynis.md), [Linux/Security/Mechanisms/Kernel/hardening.md](../../Linux/Security/Mechanisms/Kernel/hardening.md).
- **Compliance / аудит** — [Audit and compliance overview](../../Security/audit_and_compliance_overview.md), [Ansible OS hardening](../../Ansible/ansible-os-hardening.md).
- **Сеть (iptables / nftables / firewall)** — [iptables_basics](../../Linux/Networking/Settings/tools/iptables_basics.md), [nftables/practical_scenarios](../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md).
- **SSH / bastion (cert-auth, fail2ban)** — [ssh_certificate_authentication](../../Linux/Security/ssh/server/ssh_certificate_authentication.md), [fail2ban](../../Linux/Security/Tools/fail2ban.md).
- **Container / image hardening & runtime (Falco)** — [Docker_security/overview](../../Docker/Docker_security/overview.md), [runtime_monitoring](../../Docker/Docker_security/runtime_monitoring.md), [Security/Tools/falco.md](../../Security/Tools/falco.md).

## См. также

- **[DevSecOps — обзор методологии](./devsecops_overview.md)**
- **[Интеграция безопасности в CI/CD](./sast_dast_cicd_integration.md)**
- **[Incident Response для CI/CD](../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md)**
