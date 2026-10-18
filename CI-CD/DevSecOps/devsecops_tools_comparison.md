# Сравнение инструментов DevSecOps

**Актуально для:** DevSecOps tooling 2026 (Semgrep 1.x, Trivy ≥ 0.70.1, Grype, Snyk CLI, HashiCorp Vault 1.15+, DefectDojo, OWASP ZAP)

## Определения

**SAST (Static Application Security Testing)** — анализ исходного кода без его выполнения. Инструменты SAST ищут уязвимости на уровне кода: инъекции, небезопасную десериализацию, хардкод секретов, ошибки авторизации.

**DAST (Dynamic Application Security Testing)** — анализ работающего приложения извне, имитация атаки злоумышленника. Инструменты DAST проверяют конфигурацию сервера, заголовки, логику API, бизнес-уязвимости.

**SCA (Software Composition Analysis)** — анализ сторонних зависимостей на известные CVE и лицензионные риски. Инструменты SCA проверяют lock-файлы, SBOM, уведомляют о новых уязвимостях.

**IaC Scanner** — проверка инфраструктурного кода (Terraform, Helm, Kubernetes, Dockerfile) на небезопасные конфигурации.

**Secrets Manager** — централизованное хранилище секретов с политиками доступа, аудитом и ротацией.

**ASPM (Application Security Posture Management)** — платформы, агрегирующие данные от всех сканеров (SAST, DAST, SCA, IaC) для приоритизации рисков и управления security backlog.

## Предварительные требования

Перед внедрением инструментов DevSecOps убедитесь, что runners и окружение соответствуют минимальным требованиям.

### Аппаратные требования для runners

| Инструмент | Минимум RAM | CPU | Диск |
| :--- | :--- | :--- | :--- |
| Semgrep | 2 GB | 2 cores | 5 GB |
| SonarQube | 4 GB | 2 cores | 20 GB |
| CodeQL | 4 GB | 4 cores | 10 GB |
| Trivy | 512 MB | 1 core | 2 GB |
| Grype | 256 MB | 1 core | 1 GB |
| Gitleaks | 128 MB | 1 core | 500 MB |
| Checkov | 512 MB | 1 core | 1 GB |
| Vault | 2 GB | 2 cores | 10 GB |

### Программные требования

- **Git** 2.40+ с поддержкой worktree для инкрементального сканирования
- **Docker/Podman** 24+ для контейнерных сканеров и подписи образов
- **CI/CD runner:** GitLab Runner, GitHub Actions self-hosted, или Jenkins agent с доступом к реестру и хранилищу артефактов
- **Сеть:** доступ к NVD/GitHub Advisory DB для обновления баз CVE; в air-gapped средах — локальный mirror
- **Дисковое пространство:** кэш баз CVE (Trivy ~1 GB, Grype ~500 MB), SARIF-отчёты, SBOM-артефакты

### Состояние окружения

- Все секреты (API-ключи, токены сканеров) хранятся во внешнем менеджере секретов (Vault, SOPS), не в переменных CI
- Резолвинг DNS настроен; при блокировке внешних ресурсов — локальный прокси с кэшированием
- Системное время синхронизировано по NTP; искажение часов приводит к неправильным временным меткам в отчётах и проблемам с верификацией подписей

## Базовые концепции

При выборе инструментов DevSecOps оценивайте покрытие языков, точность, производительность и возможность self-hosted развёртывания.

### Критерии выбора инструментов

| Критерий | Описание | Важность |
| :--- | :--- | :--- |
| **Покрытие языков** | Какие языки программирования и фреймворки поддерживаются | Высокая |
| **Точность (FP/FN rate)** | Процент ложных срабатываний и пропусков | Высокая |
| **Производительность** | Время сканирования, потребление ресурсов | Высокая |
| **Интеграция в CI/CD** | Наличие готовых интеграций, SARIF-экспорт, API | Высокая |
| **Цена** | Стоимость лицензий, количество пользователей/сканирований | Средняя |
| **Self-hosted vs SaaS** | Возможность развернуть on-premises или использовать облако | Средняя |
| **Кастомные правила** | Возможность писать собственные правила и политики | Средняя |
| **Сообщество и поддержка** | Активность проекта, документация, commercial support | Средняя |

### Категории инструментов

**Open Source:**
- Плюсы: бесплатные, прозрачный код, активные сообщества.
- Минусы: могут требовать больше усилий для настройки и поддержки, ограниченная commercial support.

**Commercial / Enterprise:**
- Плюсы: готовые integrations, commercial support, advanced features (Reachability Analysis, ASPM).
- Минусы: высокая стоимость, vendor lock-in.

**Cloud-native:**
- Плюсы: легко развертываются, масштабируются, интегрируются с GitHub/GitLab.
- Минусы: require отправку кода/данных в облако, может быть не подходит для air-gapped сред.

## Практические сценарии

Практические сравнения инструментов по категориям с акцентом на self-hosted развёртывание и интеграцию в CI/CD.

### Сравнение SAST-инструментов

| Критерий | Semgrep | SonarQube | CodeQL | Bandit |
| :--- | :--- | :--- | :--- | :--- |
| **Языки** | Python, JS/TS, Go, Java, C#, Ruby, Kotlin | 30+ языков | C/C++, C#, Go, Java, JS/TS, Python, Ruby | Только Python |
| **Тип анализа** | Pattern-based + light data-flow | Full AST + data-flow + quality | Deep data-flow + inter-procedural | Pattern-based для Python |
| **Скорость** | Секунды–минуты | Минуты–десятки минут | Минуты–десятки минут | Секунды |
| **Требует сборки?** | Нет | Да (опционально для некоторых языков) | Да (compile_commands.json) | Нет |
| **Кастомные правила** | Да (YAML) | Да (SonarQube Quality Profiles) | Да (QL queries) | Нет |
| **SARIF-экспорт** | Да | Да | Да | Нет |
| **Self-hosted** | Да | Да | Да (GitHub Advanced Security) | Да |
| **Цена** | Open Source + Enterprise | Community (free) + Enterprise ($) | Free for open source, $$ for enterprise | Free |
| **Лучший для** | Быстрого feedback, Shift Left, кастомных правил | Enterprise, quality + security, multi-language | Глубокого анализа, security research | Python-only проектов |

**Выводы:**
- **Semgrep** — лучший выбор для быстрого старта, кастомных правил и Shift Left. Минимальные требования к инфраструктуре.
- **SonarQube** — лучший для enterprise-окружений, где нужен единый дашборд качества и безопасности. Требует больше ресурсов.
- **CodeQL** — лучший для глубокого анализа и security research. Требует настройки сборки, но даёт максимальную точность для C/C++/Java.
- **Bandit** — простой выбор для Python-проектов, быстро внедряется, но ограничен только Python.

### Сравнение SCA-инструментов

| Критерий | Trivy | Grype | Snyk | osv-scanner |
| :--- | :--- | :--- | :--- | :--- |
| **Языки/форматы** | Multi (container, SBOM, fs, git) | SBOM, container image | Multi (npm, Maven, pip, container) | SBOM, language-specific |
| **Скорость** | Быстрый | Средний | Быстрый | Быстрый |
| **EPSS** | Нет (OSS; коммерчески — Plopsen) | Да (`--sort-by epss`) | Да | Нет |
| **VEX** | Да | Да | Да | Нет |
| **SBOM-генерация** | Да (Syft) | Нет | Да | Нет |
| **SARIF-экспорт** | Да | Да | Да | Нет |
| **Self-hosted** | Да | Да | Да | Да |
| **Цена** | Open Source + Enterprise | Open Source | Free tier + Enterprise ($) | Open Source |
| **Лучший для** | Универсального использования, air-gapped сред | Простого SCA, интеграции в CI | Developer experience, remediations | Быстрого сканирования SBOM |

**Выводы:**
- **Trivy** — лучший универсальный инструмент: SCA, image scanning, SBOM generation, IaC scanning, VEX. Рекомендуется как default.
- **Snyk** — лучший developer experience: автоматические PR с исправлениями, интеграция с IDE, good UI. Хорош для команд, где разработчики сами triage findings.
- **Grype** — простой open-source alternative для SCA; хорош, если нужен только dependency scanning без лишних функций.
- **osv-scanner** — официальный инструмент от Google/OSV database; хорош для минималистичных пайплайнов.

### Сравнение Secrets Managers

| Критерий | HashiCorp Vault | AWS Secrets Manager | Azure Key Vault | Google Secret Manager |
| :--- | :--- | :--- | :--- | :--- |
| **Self-hosted** | Да | Нет | Нет | Нет |
| **Multi-cloud** | Да | Только AWS | Только Azure | Только GCP |
| **Динамические секреты** | Да (Database, AWS, SSH, PKI) | Ограничено | Ограничено | Ограничено |
| **OIDC / Workload Identity** | Да | Да | Да | Да |
| **HSM support** | Да (Enterprise) | Да | Да | Да |
| **Audit logging** | Да (file, syslog, JSON) | Да (CloudTrail) | Да (Azure Monitor) | Да (Cloud Audit Logs) |
| **Цена** | Open Source + Enterprise ($) | $ за secret/версию | $ за операцию | $ за версию |
| **Лучший для** | Self-hosted, complex workflows, dynamic secrets | AWS-only сред, serverless | Azure-only сред | GCP-only сред |

**Выводы:**
- **HashiCorp Vault** — лучший выбор для multi-cloud, self-hosted сред, сложных workflows с dynamic secrets, JWT/OIDC аутентификацией.
- **AWS Secrets Manager** — оптимален для AWS-only архитектур, serverless приложений.
- **Azure Key Vault** — для Azure-only сред, особенно с managed identities.
- **Google Secret Manager** — для GCP-only сред, особенно с Workload Identity.

### Сравнение ASPM-платформ

| Критерий | DefectDojo | Snyk AppRisk | Cycode | Apiiro |
| :--- | :--- | :--- | :--- | :--- |
| **Open Source** | Да | Нет | Нет | Нет |
| **Self-hosted** | Да | Нет | Нет | Нет |
| **Интеграции** | 30+ сканеров, SARIF, Jira | Snyk ecosystem, GitHub, GitLab | Multi-tool, enterprise | GitHub, GitLab, Bitbucket |
| **Reachability Analysis** | Ограничено | Да | Да | Да |
| **VEX support** | Да | Да | Да | Да |
| **Цена** | Free + Enterprise | $$ | $$$ | $$$ |
| **Лучший для** | Self-hosted, open-source стек, budget | Developer-first, Snyk users | Enterprise, governance, compliance | Enterprise, risk-based prioritization |

**Выводы:**
- **DefectDojo** — лучший open-source выбор для self-hosted сред. Требует больше efforts для настройки, но даёт полный контроль.
- **Snyk AppRisk** — лучший для команд, уже использующих Snyk. Единый UX для SCA, SAST, container security.
- **Cycode** — enterprise-решение для governance, compliance, policy enforcement.
- **Apiiro** — для risk-based prioritization с фокусом на бизнес-контекст и reachability.

## Оперативные команды

| Команда / Инструмент | Назначение | Ожидаемый результат | Валидация |
| :--- | :--- | :--- | :--- |
| `semgrep scan --config auto . --sarif -o report.sarif` | Быстрый SAST | SARIF с findings | `echo $?` — 0 при success, 1 при findings; размер report.sarif > 0 |
| `sonar-scanner -Dsonar.projectKey=myapp -Dsonar.sources=src` | SAST + quality | Отчёт в SonarQube UI | Quality gate статус в UI; `sonar-scanner -X` для отладки |
| `codeql database create db --language=python && codeql database analyze db --format=sarif-latest --output=codeql.sarif` | Глубокий SAST | SARIF с межпроцедурными находками | `codeql database info db` — языки обнаружены; размер SARIF > 0 |
| `trivy fs . --format sarif -o trivy.sarif` | SCA + secrets + IaC | SARIF с CVE и misconfigurations | `trivy fs . --severity CRITICAL` — 0 critical при clean build |
| `grype sbom:sbom.json -o json` | SCA | JSON с уязвимостями | `grype sbom:sbom.json --fail-on high` — 0 high при success |
| `snyk test --json` | SCA + container | JSON с findings и remediation | `snyk test --severity-threshold=high` — exit code 0/1 |
| `checkov -d . --framework terraform,kubernetes --output sarif` | IaC scanning | SARIF с небезопасными конфигурациями | `checkov -d . --compact` — краткий вывод; `echo $?` — 0/1 |
| `gitleaks detect --source=. --report-path=gitleaks.json` | Secrets scan | JSON с находками или пустой | `gitleaks detect --source=. --redact` — маскировка в логах; пустой JSON при clean |
| `vault status` | Проверка статуса Vault | Информация о состоянии кластера | `sealed=false`, `initialized=true`; `vault operator health` для HA |
| `cosign verify --key cosign.pub registry/image:tag` | Проверка подписи образа | Валидация подписи или ошибка | `echo $?` — 0 при валидной подписи; `cosign triangulate` для поиска digest |

## Граничные случаи и ограничения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Semgrep падает на большом репозитории | Нехватка памяти или таймаут | Увеличить `--max-memory`, использовать `--jobs` для параллелизма |
| SonarQube не принимает отчёт | Неверный `sonar.projectKey` или токен | Проверить конфигурацию, убедиться что проект существует |
| CodeQL не находит findings | Нет `compile_commands.json` для C/C++ | Сгенерировать через `cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON` или `bear` |
| Trivy не обновляет базу CVE | Устаревший кэш | `trivy image --download-db-only` |
| Snyk не видит приватные репозитории | Не настроен SCM integration | Добавить SCM в Snyk dashboard, установить Snyk CLI token |
| Checkov пропускает ресурс | Ресурс не покрыт стандартными политиками | Написать кастомное правило или использовать `--check` с явным CKV-ID |
| Gitleaks false positive на тестовые данные | Шаблон совпал с тестовыми ключами | Добавить хэш находки в `.gitleaksignore` |
| Vault недоступен | Нет сети или неверный `VAULT_ADDR` | Проверить `curl $VAULT_ADDR/v1/sys/health` |

## Граничные случаи и ограничения

Эксплуатация инструментов DevSecOps в production-окружении сопряжена с особенностями, которые не покрываются типовыми руководствами.

### Air-gapped среды

- **Нет доступа к NVD/Advisory DB:** Trivy, Grype, osv-scanner не смогут обновить базы. Требуется локальный mirror (Trivy `--db-repository`, Grype `--update-url`) или периодический `curl` на станции с доступом.
- **Нет SaaS-интеграций:** Snyk, GitHub Advanced Security недоступны; используйте self-hosted ASPM (DefectDojo) и SARIF-агрегацию.
- **Секреты:** Vault должен работать в isolation; динамические секреты для внешних систем (AWS, DB) требуют промежуточного jump-хоста или локальных эмуляторов.

### Ограничения ресурсов CI runners

- **Memory:** CodeQL и SonarQube требуют ≥4 GB RAM; при less — OOM killer завершает процесс. Используйте отдельные heavy-runner labels или self-hosted API для CodeQL.
- **CPU:** Semgrep с `--jobs` насыщает все cores; ограничьте через `cgroup` или CI concurrency, чтобы не задеть другие задачи.
- **Диск:** Кэш Trivy (`~/.cache/trivy`) и SBOM-артефакты растут; настройте `tmpfs` для рабочих директорий или periodic cleanup через `find /cache -mtime +7 -delete`.

### Монорепозитории и large-scale кодовые базы

- **Сканирование всего репо за раз:** Semgrep/CodeQL тратят минуты на парсинг; используйте инкрементальный режим (Semgrep `--diff`, CodeQL `autobuild` с кэшированием).
- **Дублирование findings:** один и тот же CVE в разных сервисах монорепо; ASPM должна дедуплицировать по `package+version`, а не по пути.
- **Lock-файлы:** в монорепо lock-файлы scattered; SCA-сканер должен получать manifest per-service, не aggregating всё в один SBOM без изоляции.

### Ложные срабатывания и suppressions

- **Gitleaks на тестовые ключи:** добавьте хэш в `.gitleaksignore`; регулярно аудируйте ignore-list, чтобы не подавить реальную утечку.
- **Semgrep на сгенерированный код:** используйте `exclude` для `generated/`, `dist/`, `node_modules/`; иначе FP rate засорит пайплайн.
- **Checkov на legacy IaC:** старые модули могут не соответствовать современным политикам; используйте `--skip-check` с комментарием-обоснованием и сроком пересмотра.

### Время и синхронизация

- **Clock skew:** искажение >5 мин между runner и Vault/SCM приводит к ошибкам верификации JWT, истечению токенов, некорректным временным меткам в SBOM.
- **Race condition в параллельных сканах:** одновременный запуск Trivy и Grype в одной рабочей директории может привести к corrupted lock-файлам; используем separate workspaces.

### Self-monitoring и blind spots

- **Сканеры сами по себе:** если SAST-сканер упал, но пайплайн не проверил exit code — security gate bypassed. Обязательна проверка `$?` и наличие отчёта.
- **Новые языки/фреймворки:** сканеры покрывают mainstream языки; niche-экосистемы (Ada, COBOL, embedded C) требуют кастомных правил или ручного аудита.
- **Конфигурация сканеров:** устаревшие правила Semgrep/Trivy пропускают новые CVE; настройте автоматическое обновление правил и мониторинг release notes.

## Эксплуатация инструментов DevSecOps с точки зрения Sysadmin/SRE

Эксплуатация сканеров и платформ в production требует стандартных практик управления сервисами, резервного копирования и аудита.

### Systemd-управление длительными процессами

Для инструментов, работающих как сервисы (SonarQube, Vault, DefectDojo):

```ini
# /etc/systemd/system/vault.service
[Unit]
Description=HashiCorp Vault
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/bin/vault server -config=/etc/vault/config.hcl
ExecReload=/bin/kill -s HUP $MAINPID
LimitNOFILE=65536
LimitMEMLOCK=infinity
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now vault
journalctl -u vault -f --since "10 minutes ago"
```

### Логирование и ротация

- **Сканеры в CI:** SARIF, JSON, SBOM — хранятся как артефакты пайплайна; настройте retention policy (30–90 дней) в CI/CD settings.
- **Self-hosted платформы:** SonarQube, DefectDojo, Vault — ротация через `logrotate` или встроенные механизмы (Vault audit logs → syslog/JSON файл с max_size).
- **Gitleaks/Trivy в cron:** при scheduled scans направляйте вывод в syslog (`logger -t gitleaks`) или в Loki через Alloy для централизованного хранения.

### Firewall и сетевые требования

| Сервис | Порт | Протокол | Назначение |
| :--- | :--- | :--- | :--- |
| SonarQube | 9000 | TCP | UI + API |
| Vault | 8200 | TCP | API + UI |
| DefectDojo | 8080 | TCP | UI + API |
| Trivy/Grype DB mirror | 9999 | TCP | Локальный файловый сервер для кэша |
| Vault cluster | 8201 | TCP | Raft replication (только internal network) |

```bash
# Пример: ограничение Vault replication traffic
iptables -A INPUT -p tcp --dport 8201 -s 10.0.2.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 8201 -j DROP
```

### Управление сертификатами

- **Внутренние registry/API:** terminate TLS на ingress (Traefik, Nginx) с сертификатами от внутреннего CA; сканеры должны trust этот CA (`REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`).
- **Vault TLS:** при self-signed certs добавьте в system trust store (`update-ca-trust` на RHEL, `cp ... /usr/local/share/ca-certificates/` + `update-ca-certificates` на Debian).
- **Сканирование container image:** Trivy/Grype проверяют registry TLS; при insecure registry — `--insecure-skip-tls-verify`, но только для internal Harbor/registry.

### Аудит изменений

- **Конфиги сканеров:** Semgrep (`semgrep --config=...`), Trivy (`.trivyignore`), Checkov (`--skip-check`), Gitleaks (`.gitleaksignore`) — версионируйте в Git; изменения требуют MR + review.
- **Правила:** кастомные Semgrep-правила, Checkov-политики, Vault policies — храните в репозитории; применяйте через IaC (Terraform `vault_policy`, Checkov `--external-checks-dir`).
- **Аудит Vault:** включите audit device (`file`, `syslog`) до начала production использования; без аудита нет traceability для incident response.

### Резервное копирование

- **Vault:** периодический `vault operator raft snapshot save /backups/vault.snap` + сохранение unseal keys в безопасном хранилище (HSM, encrypted USB). При katastrofe — `vault operator raft enter` + `seal`/`unseal`.
- **SBOM/SARIF артефакты:** храните в artifact registry (Harbor, Nexus) с retention policy; при потере CI-истории — SBOM можно перегенерировать, но только если исходные lock-файлы доступны.
- **DefectDojo:** бэкап PostgreSQL (`pg_dump`) + media files; тестируйте восстановление на staging раз в квартал.

## Рекомендации

Сводные рекомендации по выбору, развёртыванию и сопровождению инструментов DevSecOps в команде DevOps/SRE.

### Выбор инструментов

- **Начинайте с open-source:** Trivy, Semgrep, Checkov, Gitleaks — достаточный набор для большинства команд.
- **Интегрируйте в CI/CD:** все сканеры должны экспортировать в SARIF, чтобы ASPM мог агрегировать результаты.
- **Не переусложняйте:** лучше один хорошо настроенный инструмент, чем пять включённых по умолчанию с шумом.
- **Оценивайте FP rate:** агрессивные правила без baseline делают инструмент бесполезным. Настройте suppression и triage SLA.
- **Проверяйте покрытие:** регулярно аудируйте, какие языки/фреймворки покрыты сканерами, добавляйте недостающие.

### Best Practices

- **Shift Left:** SAST и secret scan в pre-commit; SCA и IaC scanning в PR; DAST в staging.
- **SARIF everywhere:** используйте единый формат для interoperability между инструментами и платформами.
- **Baseline и suppression:** ведите baseline известных findings; подавляйте только с обоснованием.
- **Automated remediation:** используйте Renovate для зависимостей, Snyk auto-fix, GitGuardian для секретов.
- **Continuous tuning:** регулярно пересматривайте правила, исключения, пороги quality gates.

### Security Debt Management

- **Инвентаризация:** все security findings должны быть в едином трекере (ASPM, Jira, DefectDojo).
- **Приоритизация:** CVSS + EPSS + Reachability + контекст среды.
- **SLA:** Critical ≤ 24ч, High ≤ 7 дней, Medium ≤ 30 дней, Low — backlog.
- **Работа с долгом:** выделите 20% времени каждого спринта на закрытие security debt.

## Дополнительная информация

Данный файл является точкой входа для выбора инструментов; детальные технические обзоры находятся в связанных документах.

### Связь с другими доменами

- **SAST/DAST/SCA/IaC:** детальные обзоры инструментов — в соответствующих файлах: **[SAST — обзор](./sast_overview.md)**, **[DAST — обзор](./dast_overview.md)**, **[SCA и анализ зависимостей](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.
- **Secrets Management:** Vault и alternatives — в **[Управление секретами в CI/CD](./secrets_management.md)** и **[Обзор Vault](../../Vault/overview.md)**.
- **Container Security:** Trivy, Grype, Cosign — в **[Безопасность контейнеров](../../Docker/Docker_security/vulnerability_scanning.md)** и **[Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)**.
- **ASPM:** DefectDojo, Snyk AppRisk, Cycode — в **[DevSecOps overview](./devsecops_overview.md)**.

### Документация и ресурсы

- **Semgrep:** https://semgrep.dev/docs/
- **SonarQube:** https://docs.sonarqube.org/
- **CodeQL:** https://codeql.github.com/docs/
- **Trivy:** https://aquasecurity.github.io/trivy/
- **Snyk:** https://docs.snyk.io/
- **Checkov:** https://www.checkov.io/
- **Gitleaks:** https://gitleaks.io/
- **HashiCorp Vault:** https://developer.hashicorp.com/vault/docs
- **OWASP DevSecOps Guideline:** https://owasp.org/www-project-devsecops-guideline/

## См. также

- **[SAST — обзор](./sast_overview.md)** — архитектура движка, типы анализа, deep dive.
- **[DAST — обзор](./dast_overview.md)** — proxy-архитектура, режимы сканирования, границы применимости.
- **[Сравнение SCA-инструментов](../../Security/Supply_Chain_Security/sca_tools_comparison.md)** — расширенное сравнение Trivy, Grype, Snyk, osv-scanner, Syft.
