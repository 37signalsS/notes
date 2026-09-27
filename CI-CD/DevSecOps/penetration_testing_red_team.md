# Penetration Testing и Red Teaming

**Актуально для:** Penetration Testing & Red Teaming 2026 (PTES v1.1, MITRE ATT&CK v14+, Nuclei, OWASP ZAP, Burp Suite)

## Определения

**Penetration Testing (Пентест)** — формализованное этическое тестирование безопасности системы с целью выявления уязвимостей, которые не были найдены автоматическими сканерами. Результат — отчёт с PoC, оценкой риска и рекомендациями по исправлению.

**Red Teaming** — имитация целевых атак на организацию в условиях, близких к реальным. В отличие от пентеста, который проверяет конкретный asset или приложение, red team оценивает способность организации обнаружить, отреагировать и отразить атаку, включая людей, процессы и технологии.

**Rules of Engagement (RoE)** — документ, определяющий границы тестирования: scope, allowed techniques, time windows, escalation contacts, запрещённые действия (например, DoS в продакшене, социальная инженерия против CEO без согласования).

**TTP (Tactics, Techniques, and Procedures)** — классификация поведения злоумышленника из frameworks MITRE ATT&CK. Используется для описания атак, построения сценариев red team и mapping найденных уязвимостей к техникам.

**Bug Bounty** — программа, при которой исследователи безопасности этически сообщают об уязвимостях за вознаграждение. Отличается от пентеста тем, что тестирование инициируется исследователем, а не организацией.

## Предварительные требования

### Аппаратные требования для пентест-станции и изолированной лаборатории

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| **CPU** | 8 ядер | 16+ ядер (параллельные сканы, фаззинг) |
| **RAM** | 16 ГБ | 32–64 ГБ (Kali + несколько VM + база BloodHound) |
| **Диск** | 200 ГБ SSD | 500 ГБ–1 ТБ NVMe (snapshots, логи, артефакты) |
| **Сеть** | Два интерфейса: management + isolated | management + isolated + VPN-туннель для доступа к стенду |
| **Безопасность** | VLAN-изоляция или физический свитч | Отдельный VLAN + firewall rules + egress allowlist |

### Программные требования

- **Операционная система:** Kali Linux 2026.x ( Rolling ) илиDebian/Ubuntu с мета-пакетом `kali-linux-large`.
- **Виртуализация/контейнеризация:** KVM/QEMU (`virt-manager`, `libvirt`), VirtualBox или Docker/Podman для изоляции стендов.
- **Сетевые инструменты:** `iptables`/`nftables`, `tcpdump`, `Wireshark`, `dnsmasq` для изолированной сети.
- **CI/CD раннер (для автоматизированных сценариев):** GitLab Runner или Jenkins agent в изолированном сегменте.
- **Система управления секретами:** HashiCorp Vault 1.15+ для хранения токенов тестирования (не в CI-переменных).
- **Сертификаты:** внутренний CA (например, `step-ca` или `OpenSSL` + `cfssl`) для TLS на стенде; предварительно добавлен в trust store сканеров.

### Состояние окружения

- **Изоляция:** стенд размещён в отдельном VLAN или Docker-сети (`pentest-net`), без маршрута в production; доступ только по VPN или с management-хоста.
- **Снимки (snapshots):** перед тестированием создаётся snapshot продакшен-подобной БД/файловой системы; тест проводится на копии.
- **RoE и авторизация:** подписанный Rules of Engagement, список разрешённых техник, time windows, escalation contacts.
- **NTP:** синхронизация времени на всех узлах (пентест-станция, стенд, раннер) — обязательна для корреляции логов и Wireshark-трейсов.
- **Логирование:** включено ядерное аудирование (`auditd`), сбор логов раннера и стенда в центральный syslog/ELK.

## Базовые концепции

Пентест и red team дополняют автоматические сканеры (SAST, DAST, SCA) и проверяют человеческий фактор, бизнес-логику и способность организации к детекции/реагированию. В контексте DevOps/SRE пентест интегрируется в CI/CD как regular activity (continuous pentesting), а не разовый проект.

### Типы пентестов

| Тип | Описание | Объём знаний | Пример |
| :--- | :--- | :--- | :--- |
| **Black Box** | Тестировщик не имеет информации о системе, кроме внешнего адреса. Имитирует внешнего злоумышленника. | Только публичные данные | Сканирование IP, перебор паролей, exploitation |
| **Gray Box** | Тестировщик имеет ограниченные учётные данные или документацию (например, доступ к API как обычный пользователь). Имитирует инсайдера или compromatованного аккаунт. | Частичные данные | Логин обычного пользователя, документация API |
| **White Box** | Полный доступ к исходному коду, архитектуре, сетевым диаграммам. Тестировщик знает систему изнутри. | Полные данные | Анализ кода, аудит конфигураций, threat modeling |
| **Purple Team** | Совместная работа red team и blue team в реальном времени. Цель — не только найти уязвимости, но и улучшить детекцию и ответ. | Полные данные | Ролевая игра: red team атакует, blue team детектирует и отвечает |

### Methodology пентеста

**PTES (Penetration Testing Execution Standard)** — де-факто стандарт, описывающий этапы пентеста:

1. **Pre-engagement Interactions:** определение scope, RoE, legal authorization, NDAs, escalation contacts, time windows.
2. **Intelligence Gathering:** сбор информации о цели (OSINT, DNS enumeration, subnet scanning, technologies fingerprinting).
3. **Threat Modeling:** построение модели угроз на основе собранных данных; mapping к MITRE ATT&CK.
4. **Vulnerability Analysis:** автоматическое и ручное сканирование уязвимостей (Nessus, Nmap, Nuclei, manual review).
5. **Exploitation:** подтверждение уязвимости через exploitation (без повреждения данных). Документирование impact.
6. **Post-Exploitation:** оценка blast radius, доступ к смежным системам, lateral movement, сбор evidence.
7. **Reporting:** структурированный отчёт с executive summary, technical findings, PoC, remediation recommendations, risk rating.

**OSSTMM (Open Source Security Testing Methodology Manual)** — альтернативный framework, фокусирующийся на rigorous metrics и channel-based testing (human, physical, wireless, telecommunications, data networks).

### Red Teaming vs Penetration Testing

| Критерий | Penetration Testing | Red Teaming |
| :--- | :--- | :--- |
| **Цель** | Найти уязвимости в конкретном asset | Оценить готовность организации к целевой атаке |
| **Scope** | Ограниченный (приложение, сеть, хост) | Широкий (вся организация, включая людей и процессы) |
| **Правила** | Жёсткие RoE, запрещены некоторые техники | Минимальные ограничения, имитация реального злоумышленника |
| **Длительность** | От дней до недель | От недель до месяцев |
| **Результат** | Отчёт с уязвимостями и remediation | Оценка зрелости Detection & Response, рекомендации по улучшению |
| **Вовлечённость Blue Team** | Обычно нет (async) | Постоянное взаимодействие (Purple Team) |

### MITRE ATT&CK для DevOps/SRE

В контексте CI/CD и инфраструктуры наиболее релевантные тактики MITRE ATT&CK:

| Тактика | Примеры техник | Релевантность для DevSecOps |
| :--- | :--- | :--- |
| **Initial Access** | Phishing, Supply Chain Compromise, Exploit Public-Facing Application | Атака на разработчика, компрометация зависимости, атака на CI/CD |
| **Execution** | Command-Line Interface, PowerShell, Scripting | Выполнение вредоносных команд в пайплайне, runner compromise |
| **Persistence** | Cron, Systemd Timers, Registry Run Keys | Закрепление на раннере через cron/systemd |
| **Privilege Escalation** | Sudo/SUID, Container Escape | Повышение прав на хосте раннера, побег из контейнера |
| **Defense Evasion** | Log Clearing, Indicator Removal, Obfuscated Files | Удаление логов CI, обход сканеров |
| **Credential Access** | Brute Force, Credential Dumping, LSASS Memory | Кража секретов из CI, дамп памяти процесса |
| **Discovery** | Network Service Scanning, Account Discovery | Сканирование внутренней сети CI, перечисление сервисов |
| **Lateral Movement** | Remote Services, Internal Phishing | Перемещение между раннерами, доступ к registry и Vault |
| **Impact** | Data Destruction, Resource Hijacking | Шифрование артефактов, кража вычислительных ресурсов |

## Практические сценарии

### Пример 1: Развёртывание изолированной лаборатории для пентеста

Пентест должен проводиться в изолированной среде, не затрагивающей продакшен.

**Предусловия:** выделенный VLAN или Docker-сеть (`pentest-net`), доступ только по VPN или с management-хоста; snapshots продакшен-систем перед тестированием; согласованный RoE.

**1. Подготовка инфраструктуры (self-hosted, без облака):**

```bash
# Создание изолированной Docker-сети
docker network create --subnet=10.99.0.0/24 pentest-net

# Развёртывание стенда через Vagrant + libvirt/KVM
vagrant init ubuntu/focal
vagrant up --provider=libvirt
# → стенд включает: копию production API, тестовые данные, уязвимые версии зависимостей

# ИЛИ через Ansible на существующих хостах
ansible-playbook -i inventory.ini playbooks/pentest-lab.yml
```

**2. Настройка сканеров и инструментов:**

```bash
# Kali Linux образ с предустановленными инструментами
docker run -it --rm --net=pentest-net kalilinux/kali-rolling

# Установка специализированных инструментов
apt update && apt install -y \
  nmap nikto nuclei sqlmap \
  metasploit-framework burpsuite \
  zaproxy gobuster ffuf \
  bloodhound neo4j
```

**3. Проведение пентеста по PTES:**

```bash
# 1. Intelligence Gathering
nmap -sS -sV -p- 10.99.1.100
nuclei -u https://staging-api.example.com -severity critical,high -o nuclei-results.json

# 2. Vulnerability Analysis
nikto -h https://staging-api.example.com -o nikto.txt
burpsuite (manual proxy)

# 3. Exploitation
sqlmap -u "https://staging-api.example.com/item?id=1" --batch --level=2 --risk=1
ffuf -u https://staging-api.example.com/api/FUZZ -w /usr/share/seclists/Discovery/Web-Content/api-endpoints.txt

# 4. Post-Exploitation
# Оценка доступа к внутренним сервисам
curl http://internal-api:8080/admin/users
```

**Validation:** все этапы документированы в scratchpad; после пентеста стенд удаляется, снапшоты продакшена проверяются на отсутствие изменений.

**Troubleshooting:**
- *Стенд падает при нагрузке:* ограничьте concurrency у фаззеров (`-t 10` вместо `-t 100`); используйте rate limiting на уровне стенда.
- *Сканеры детектируются WAF:* добавьте задержки (`-p 0.5`), rotate User-Agent, используйте proxy chain (Burp Suite).

### Пример 2: Red Team сценарий — атака на CI/CD инфраструктуру

**Цель:** имитация целевой атаки на организацию с компрометацией CI/CD пайплайна и получением доступа к продакшен-секретам.

**Предусловия:** RoE, одобрение CISO, изолированный стенд с копией CI-инфраструктуры.

**Сценарий атаки (MITRE ATT&CK mapping):**

1. **Initial Access:** фишинг на разработчика → compromised workstation.
2. **Execution:** выполнение вредоносного кода в контексте разработчика; commit с backdoor в feature branch.
3. **Persistence:** модификация `.gitlab-ci.yml` для выполнения reverse shell при каждом пайплайне.
4. **Privilege Escalation:** побег из контейнера раннера через `docker.sock`; доступ к хосту.
5. **Credential Access:** сбор секретов раннера из `/proc/*/environ`, копирование Vault токенов.
6. **Lateral Movement:** доступ к внутреннему registry, заражение базового образа; доступ к Vault через украденный токен.
7. **Impact:** подпись вредоносного артефакта, деплой в продакшен.

**Оборона (Blue Team):**
- **Detection:** Falco/Tetragon детектирует аномальные системные вызовы (обращение к `/var/run/docker.sock`, запись в `/etc/cron.d`).
- **Response:** NetworkPolicy изолирует под; Vault аудит фиксирует аномальное чтение секретов; артефакт отклоняется admission controller'ом из-за несоответствия подписи.
- **Post-Incident:** пересмотр RBAC, внедрение mTLS между сервисами, усиление runner isolation.

**Validation:** red team фиксирует timeline атаки, использованные TTP, успешные и заблокированные шаги; blue team — evidence detection, время обнаружения (TTD), время реагирования (TTR).

### Пример 3: Автоматизированный пентест через Nuclei + CI

```yaml
# .gitlab-ci.yml
pentest_scan:
  stage: security
  image: projectdiscovery/nuclei:1.16.0
  variables:
    TARGET: "https://staging-api.example.com"
    SEVERITY: "critical,high"
  script:
    - nuclei -u $TARGET -severity $SEVERITY \
        -o reports/nuclei-results.json \
        -json -timeout 10 -retries 1
  artifacts:
    paths: [reports/nuclei-results.json]
    expire_in: 7 days
```

**Validation:** `nuclei-results.json` содержит структурированный отчёт с CVE, CWE, URL, HTTP-статусом; при наличии critical/high уязвимостей пайплайн блокируется.

**Troubleshooting:**
- *Слишком много ложных срабатываний:* добавьте темплейты только для критичных техник (`-t cves/`, `-t exposures/`); используйте `-ignore-templates` для нерелевантных.
- *Сканирование слишком долгое:* ограничьте scope через `-u` конкретными эндпоинтами; используйте `-rate-limit 50`.

## Оперативные команды

| Команда / Инструмент | Назначение | Ожидаемый результат | Валидация |
| :--- | :--- | :--- | :--- |
| `nmap -sS -sV -p- target` | Сканирование портов и сервисов | Список открытых портов, версий ПО | `echo $?` → `0`; в выводе есть строки `open` и `service` |
| `nuclei -u target -severity critical,high -json` | Сканирование по шаблонам CVE/misconfig | JSON-отчёт с уязвимостями | Файл `nuclei-results.json` непустой; `jq 'length'` > 0 |
| `sqlmap -u "url?id=1" --batch --level=2 --risk=1` | Проверка SQL-инъекций | Подтверждение уязвимости с PoC | В `output` есть `Payload` и `Parameter`; возвращает `0` при подтверждении |
| `ffuf -u target/api/FUZZ -w wordlist.txt -mc 200,401,403` | Фаззинг эндпоинтов | Список доступных API-путей | В выводе есть строки с `200`/`401`/`403`; `wc -l` > baseline |
| `burpsuite` (manual) | Ручной пентест, перехват запросов | Подробный анализ бизнес-логики | Запросы появляются в Proxy → HTTP history; ответы не кэшированы |
| `gobuster dir -u target -w wordlist.txt -x php,json` | Перебор директорий и файлов | Скрытые эндпоинты, admin-панели | Найдены пути с кодом `200`; исключены артефакты реврайтов |
| `bloodhound` | Анализ AD, построение графа атак | Визуализация путей lateral movement | База Neo4j заполнена; в графе есть пути от `User` до `Domain Admins` |
| `metasploit-framework` | Эксплуатация известных уязвимостей | Получение shell / доказательство impact | `sessions -i` показывает активную сессию; доступ к `id`/`whoami` на цели |
| `curl -I target` | Проверка заголовков безопасности | Наличие/отсутствие CSP, HSTS, CORS | В выводе присутствуют/отсутствуют `Strict-Transport-Security`, `Content-Security-Policy` |
| `jq '.[] | select(.severity=="critical")' nuclei-results.json` | Фильтрация критичных находок | Список критичных уязвимостей | Команда возвращает ≥0 записей; при ошибке синтаксиса — ненулевой exit code |

## Устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Сканер детектируется WAF/IPS | Изменение User-Agent, задержки, фингерпринтинг | Добавить `-timeout 10 -retries 1`, rotate User-Agent, использовать proxies |
| SQLMap зависает на TIME-Based blind | Слишком высокая задержка или неверный параметр | Уменьшить `--time-sec`, использовать `--technique=BEUSTQ` для комбинированного подхода |
| Nuclei не находит CVE на известный продукт | Шаблоны устарели или target fingerprinting неверен | Обновить шаблоны (`nuclei -update`); проверить, что target действительно уязвим |
| Burp Suite падает на больших объёмах трафика | Нехватка памяти или disk space | Увеличить heap size в `BurpSuite.config.vmoptions`; использовать только essential extensions |
 | Bloodhound не собирает данные о AD | Недостаточные права или неверный LDAP bind | Проверить учётные данные; использовать `--collection Method` (DCOnly, Default) |

## Граничные случаи и ограничения

Проведение пентестов и red team exercises в production-подобных условиях сопряжено с особенностями, которые не покрываются типовыми руководствами.

### Изоляция и побочные эффекты

- **Air-gapped среды:** сканеры не имеют доступа к интернету для обновления баз; используйте локальные зеркала (например, `apt-cacher-ng`, `nexus` для пакетов, локальный `nuclei-templates`).
- **Ресурсные ограничения стенда:** активный пентест создаёт нагрузку на БД и сервисы; ограничьте RPS (`nuclei -rate 50`, `ffuf -t 10`) и время работы (`-m 5` для ZAP).
- **Монорепозитории:** разворачивайте отдельный стенд на каждый сервис или используйте review-apps, чтобы сканеры не трогали production-подобные shared-состояния.
- **Ложные срабатывания (false positives):** baseline-скан с составлением списка FP (`zap-context`, `nuclei -ignore-templates`) обязателен перед quality gate; иначе шум маскирует реальные находки.
- **Clock skew:** NTP-рассинхронизация между пентест-станцией и стендом искажает Wireshark-трейсы и корреляцию логов; проверяйте `chronyc tracking` перед началом.
- **Self-monitoring blind spots:** если blue team не знает о расписании red team, тесты могут быть приняты за реальную атаку и привести к эскалации; согласуйте time windows в RoE.

### Правовые и операционные ограничения

- **DoS в продакшене:** даже кратковременный отказ сервиса может нарушить SLA; используйте rate limiting и exclude-списки.
- **Персональные данные:** при тестировании на production-данных требуется согласие DPO (Data Protection Officer) и маскировка PII в отчётах.
- **Третьи системы:** тестирование внешних интеграций (банки, партнёры) возможно только после их письменного согласия.

## Рекомендации

Сводные рекомендации по планированию, проведению и интеграции пентестов и red team exercises в процессы DevOps/SRE.

### Legal и Ethical

- **Обязательное письменное разрешение:** перед любым пентестом получить подписанный RoE, scope и authorization letter.
- **Изолированная среда:** стенд должен быть snapshot продакшена, но изолирован от production-сети; запрещено тестирование production без одобрения.
- **Responsible Disclosure:** уязвимости, найденные вне bug bounty-программы, сообщаются координационному центру или вендору по responsible disclosure policy.
- **Confidentiality:** все данные, полученные в ходе пентеста (логи, пароли, PII), подлежат secure storage и уничтожению после завершения отчёта.
- **Do No Harm:** запрещено выполнение действий, которые могут привести к утечке данных, нарушению работы сервисов или доступу к третьим системам.

### Methodology

- **PTES или OSSTMM:** используйте стандартизированную methodology для воспроизводимости и качества отчёта.
- **MITRE ATT&CK mapping:** каждая найденная уязвимость должна быть сопоставлена с TTP; это помогает prioritize remediation и построить detection rules.
- **Combination of approaches:** black box для внешнего периметра, gray box для внутренних систем, white box для критических приложений.
- **Manual review обязателен:** автоматические сканеры находят 30-40% уязвимостей; остальные — через manual exploitation и business logic testing.

### Reporting

- **Executive Summary:** для руководства — бизнес-риски, impact, рекомендации без технических деталей.
- **Technical Findings:** PoC, скриншоты, curl-команды, код эксплойта; risk rating (CVSS + EPSS + контекст).
- **Remediation Guidance:** пошаговые инструкции по исправлению, приоритеты, SLA.
- **Retest:** обязательное повторное тестирование после исправлений; подтверждение закрытия уязвимостей.

### Integration в DevSecOps

- **Continuous Pentesting:** интеграция автоматизированных пентест-инструментов (Nuclei, DAST) в CI/CD; регулярное сканирование staging.
- **Bug Bounty integration:** результаты bug bounty-программ интегрируются в ASPM для triage и prioritization.
- **Purple Team exercises:** регулярные учения с blue team для тренировки detection и response.
- **Threat Modeling:** перед каждым пентестом обновлять threat model, чтобы фокусироваться на новых векторах атак.

## Дополнительная информация

Данный файл является точкой входа для penetration testing и red team methodology; детальные технические обзоры находятся в связанных документах.

### Связь с другими доменами

- **Threat Modeling:** пентест начинается с threat model — в **[DevSecOps overview](./devsecops_overview.md)**.
- **DAST/IAST:** автоматизированное динамическое тестирование — в **[DAST — обзор](./dast_overview.md)**.
- **SAST:** статический анализ кода — в **[SAST — обзор](./sast_overview.md)**.
- **CI/CD attacks:** векторы атак на пайплайны — в **[Атаки на CI/CD](./cicd_attacks.md)**.
- **Incident Response:** процедуры реагирования на инциденты — в **[Incident Response для CI/CD](../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md)** и **[Kubernetes incident response](../../Kubernetes/Security/incident_response.md)**.

### Frameworks и стандарты

- **PTES:** Penetration Testing Execution Standard — эталонная methodology.
- **OSSTMM:** Open Source Security Testing Methodology Manual — альтернативный framework с rigorous metrics.
- **MITRE ATT&CK:** база знаний о тактиках и техниках злоумышленников; mapping найденных уязвимостей к MITRE помогает prioritize remediation.
- **NIST SP 800-115:** Technical Guide to Information Security Testing and Assessment — государственный стандарт США.
- **OWASP Testing Guide:** методология тестирования безопасности веб-приложений и API.

### Правовые аспекты

- **Уголовная ответственность:** несанкционированный доступ к компьютерной информации — уголовное преступление (ст. 272–274 УК РФ, Computer Fraud and Abuse Act в США, GDPR-обязательства по уведомлению).
- **Лицензирование:** в некоторых странах пентест требует лицензии (например, OSCP, CEH); проверьте локальные регуляторные требования.
- **NDA и confidentiality:** все участники пентеста (red team, blue team, координаторы) подписывают NDA; данные тестирования не разглашаются.
- **Scope violations:** выход за рамки RoE считается нарушением и может привести к ответственности.

## См. также

- **[Атаки на CI/CD](./cicd_attacks.md)** — детальные векторы атак на пайплайны и инфраструктуру (SSoT для CI/CD security).
- **[DAST — обзор](./dast_overview.md)** — архитектура DAST-сканеров, режимы сканирования, инструменты (ZAP, Nuclei, Burp Suite).
- **[DevSecOps — обзор методологии](./devsecops_overview.md)** — содержит раздел Threat Modeling как входную точку для пентеста.
